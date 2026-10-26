"""Proxy local que repassa o tráfego do Chrome ao proxy do provedor.

O Chrome do Android não aceita usuário/senha de proxy nem troca de IP sem reiniciar. Este proxy
roda no PC (127.0.0.1) e cuida de: autenticação, TLS até o provedor (se houver), troca de IP em
tempo de execução e contagem de bytes (para o custo do lote).

Modos:
  estático  – lista de proxies fixos (um IP cada); trocar = passar para o próximo da lista.
  dinâmico  – um gateway rotativo; trocar = nova "sessão" (parâmetro na senha), o que dá outro IP.
"""
from __future__ import annotations

import base64
import logging
import secrets
import select
import socket
import ssl
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

log = logging.getLogger(__name__)

BUFFER = 65536
CONNECT_TIMEOUT = 20


class ProxyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Upstream:
    host: str
    port: int
    user: str = ""
    password: str = ""
    tls: bool = False

    @property
    def label(self) -> str:
        """Identificação sem segredo, para logs e tela."""
        return f"{self.host}:{self.port}"

    def auth_header(self, session: str | None = None, template: str = "{password}_session-{session}") -> str:
        password = template.format(password=self.password, session=session) if session else self.password
        token = base64.b64encode(f"{self.user}:{password}".encode()).decode()
        return f"Basic {token}"


def parse_upstream(text: str) -> Upstream:
    """Aceita `esquema://host:porta:usuario:senha`, `[esquema://]usuario:senha@host:porta` e `host:porta:usuario:senha`."""
    text = text.strip()
    if not text:
        raise ProxyError("Proxy vazio.")
    scheme = ""
    if "://" in text:
        scheme, text = text.split("://", 1)
    tls = scheme.lower() == "https"
    if "@" in text:
        creds, _, hostport = text.rpartition("@")
        user, _, password = creds.partition(":")
        host, _, port = hostport.partition(":")
    else:
        parts = text.split(":", 3)
        if len(parts) == 4:
            host, port, user, password = parts
        elif len(parts) == 2:
            (host, port), user, password = parts, "", ""
        else:
            raise ProxyError("Formato de proxy inválido (use host:porta:usuario:senha).")
    if not host or not port.isdigit():
        raise ProxyError("Proxy sem host ou com porta inválida.")
    return Upstream(host, int(port), unquote(user), unquote(password), tls)


def load_static_list(path: Path) -> list[Upstream]:
    if not path.exists():
        raise ProxyError(f"Lista de proxies estáticos não encontrada: {path.name}")
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            items.append(parse_upstream(line))
    if not items:
        raise ProxyError(f"{path.name} está vazio.")
    return items


class LocalProxy:
    """Servidor HTTP/CONNECT em 127.0.0.1 que encaminha ao proxy de saída atual."""

    def __init__(
        self, upstreams: list[Upstream], dynamic: bool,
        session_template: str = "{password}_session-{session}", port: int = 0,
    ) -> None:
        if not upstreams:
            raise ProxyError("Nenhum proxy configurado.")
        self.upstreams = upstreams
        self.dynamic = dynamic
        self.session_template = session_template
        self._index = 0
        self._session = secrets.token_hex(4) if dynamic else None
        self._lock = threading.Lock()
        self._conns: set[socket.socket] = set()
        self.bytes_in = 0
        self.bytes_out = 0
        self.rotations = 0
        self._server = socket.socket()
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", port))
        self._server.listen(64)
        self.port = self._server.getsockname()[1]
        self._running = False

    # -- estado -------------------------------------------------------------
    @property
    def upstream(self) -> Upstream:
        return self.upstreams[self._index % len(self.upstreams)]

    @property
    def label(self) -> str:
        extra = f" sessão {self._session}" if self._session else f" #{self._index % len(self.upstreams) + 1}"
        return f"{self.upstream.label}{extra}"

    def rotate(self) -> None:
        """Passa a sair por outro IP e derruba as conexões abertas (o Chrome reconecta)."""
        with self._lock:
            if self.dynamic:
                self._session = secrets.token_hex(4)
            else:
                self._index += 1
            self.rotations += 1
            conns, self._conns = list(self._conns), set()
        for conn in conns:
            self._close(conn)
        log.info("IP do proxy trocado → %s", self.label)

    def snapshot(self) -> tuple[Upstream, str | None]:
        with self._lock:
            return self.upstream, self._session

    # -- ciclo de vida ------------------------------------------------------
    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._accept_loop, daemon=True, name="local-proxy").start()
        log.info("Proxy local em 127.0.0.1:%d → %s", self.port, self.label)

    def stop(self) -> None:
        self._running = False
        self._close(self._server)
        with self._lock:
            conns, self._conns = list(self._conns), set()
        for conn in conns:
            self._close(conn)

    @staticmethod
    def _close(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    # -- conexão ------------------------------------------------------------
    def _open_upstream(self) -> socket.socket:
        up, session = self.snapshot()
        raw = socket.create_connection((up.host, up.port), timeout=CONNECT_TIMEOUT)
        if up.tls:
            raw = ssl.create_default_context().wrap_socket(raw, server_hostname=up.host)
        return raw

    def _auth(self) -> str:
        up, session = self.snapshot()
        return up.auth_header(session, self.session_template)

    def _handle(self, client: socket.socket) -> None:
        upstream = None
        try:
            client.settimeout(CONNECT_TIMEOUT)
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = client.recv(BUFFER)
                if not chunk:
                    return
                head += chunk
            header, _, rest = head.partition(b"\r\n\r\n")
            lines = header.split(b"\r\n")
            lines = [ln for ln in lines if not ln.lower().startswith(b"proxy-authorization:")]
            lines.insert(1, f"Proxy-Authorization: {self._auth()}".encode())
            upstream = self._open_upstream()
            with self._lock:
                self._conns.update((client, upstream))
            payload = b"\r\n".join(lines) + b"\r\n\r\n" + rest
            self.bytes_out += len(payload)
            upstream.sendall(payload)
            client.settimeout(None)
            upstream.settimeout(None)
            self._pipe(client, upstream)
        except (OSError, ValueError) as exc:   # ValueError: socket fechado por rotate()/stop()
            log.debug("Conexão do proxy local encerrada: %s", exc)
        finally:
            for sock in (client, upstream):
                if sock:
                    self._close(sock)
                    with self._lock:
                        self._conns.discard(sock)

    def _pipe(self, a: socket.socket, b: socket.socket) -> None:
        pair = {a: b, b: a}
        while True:
            ready, _, broken = select.select(list(pair), [], list(pair), 120)
            if broken or not ready:
                return
            for src in ready:
                data = src.recv(BUFFER)
                if not data:
                    return
                if src is b:
                    self.bytes_in += len(data)
                else:
                    self.bytes_out += len(data)
                pair[src].sendall(data)


def current_ip(proxy: LocalProxy | None, url: str = "http://api.ipify.org", timeout: float = 25) -> str:
    """IP de saída visto de fora (pelo proxy, se houver). Levanta ProxyError se falhar."""
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{proxy.port}"}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(url, timeout=timeout) as resp:
            ip = resp.read().decode().strip()
    except Exception as exc:
        raise ProxyError(f"Não foi possível obter o IP de saída: {exc}") from exc
    if not ip or len(ip) > 64:
        raise ProxyError(f"Resposta inesperada ao consultar o IP: {ip[:40]!r}")
    return ip



def build_proxy(settings, root: Path | None = None) -> LocalProxy | None:
    """Monta o proxy local conforme a configuração (None quando o modo é 'none')."""
    from ..config import ROOT

    mode = settings.proxy.mode
    if mode == "none":
        return None
    if mode == "dynamic":
        if not settings.proxy_url:
            raise ProxyError("Modo dinâmico sem PROXY_URL. Defina no .env (host:porta:usuario:senha).")
        return LocalProxy([parse_upstream(settings.proxy_url)], dynamic=True,
                          session_template=settings.proxy.session_template)
    return LocalProxy(load_static_list((root or ROOT) / "proxies.txt"), dynamic=False)


def validate_config(settings, root: Path | None = None) -> None:
    """Confere (sem abrir portas) se o modo de proxy escolhido tem o que precisa."""
    from ..config import ROOT

    if settings.proxy.mode == "dynamic":
        if not settings.proxy_url:
            raise ProxyError("Modo dinâmico precisa de PROXY_URL no .env (host:porta:usuario:senha).")
        parse_upstream(settings.proxy_url)
    elif settings.proxy.mode == "static":
        load_static_list((root or ROOT) / "proxies.txt")
