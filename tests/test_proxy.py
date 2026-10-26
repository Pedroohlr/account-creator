import base64
import socket
import threading

import pytest

from automate_accounts.core import proxy as px


def test_parse_formats():
    a = px.parse_upstream("https://h.test:1001:user:pa_ss-1")
    assert (a.host, a.port, a.user, a.password, a.tls) == ("h.test", 1001, "user", "pa_ss-1", True)
    b = px.parse_upstream("http://u:p@h.test:8080")
    assert (b.host, b.port, b.user, b.password, b.tls) == ("h.test", 8080, "u", "p", False)
    assert px.parse_upstream("1.2.3.4:80:u:p").port == 80
    assert px.parse_upstream("1.2.3.4:80").user == ""
    for bad in ("", "abc", "h:porta:u:p"):
        with pytest.raises(px.ProxyError):
            px.parse_upstream(bad)


def test_auth_header_with_session():
    up = px.Upstream("h", 1, "usr", "pw_country-BR")
    plain = base64.b64decode(up.auth_header().split()[1]).decode()
    sess = base64.b64decode(up.auth_header("abc").split()[1]).decode()
    assert plain == "usr:pw_country-BR" and sess == "usr:pw_country-BR_session-abc"


def test_label_never_exposes_password():
    up = px.Upstream("h.test", 1001, "usr", "SEGREDO")
    lp = px.LocalProxy([up], dynamic=True)
    try:
        assert "SEGREDO" not in lp.label and "SEGREDO" not in up.label
    finally:
        lp.stop()


def test_static_list(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("# comentário\n1.1.1.1:80:u:p\n\n2.2.2.2:81:u:p\n", encoding="utf-8")
    items = px.load_static_list(f)
    assert [i.host for i in items] == ["1.1.1.1", "2.2.2.2"]
    f.write_text("# vazio\n")
    with pytest.raises(px.ProxyError):
        px.load_static_list(f)
    with pytest.raises(px.ProxyError):
        px.load_static_list(tmp_path / "nao.txt")


class FakeUpstream:
    """Proxy de saída falso: guarda os cabeçalhos recebidos e responde 200 fixo."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        self.requests: list[str] = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            self.requests.append(data.decode())
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n1.2.3.4")
            conn.close()


def fetch_through(lp):
    c = socket.create_connection(("127.0.0.1", lp.port), timeout=5)
    c.sendall(b"GET http://exemplo.test/ HTTP/1.1\r\nHost: exemplo.test\r\nProxy-Authorization: Basic xxxx\r\n\r\n")
    data = b""
    while b"1.2.3.4" not in data:
        chunk = c.recv(4096)
        if not chunk:
            break
        data += chunk
    c.close()
    return data


def auth_user_password(request: str) -> str:
    line = next(ln for ln in request.splitlines() if ln.lower().startswith("proxy-authorization"))
    return base64.b64decode(line.split()[-1]).decode()


def test_local_proxy_injects_auth_and_counts_bytes():
    fake = FakeUpstream()
    lp = px.LocalProxy([px.Upstream("127.0.0.1", fake.port, "u", "pw")], dynamic=False)
    lp.start()
    try:
        assert b"1.2.3.4" in fetch_through(lp)
        assert auth_user_password(fake.requests[0]) == "u:pw"          # trocou a credencial do cliente
        assert "xxxx" not in fake.requests[0]
        assert lp.bytes_out > 0 and lp.bytes_in > 0
    finally:
        lp.stop()


def test_dynamic_rotation_changes_session():
    fake = FakeUpstream()
    lp = px.LocalProxy([px.Upstream("127.0.0.1", fake.port, "u", "pw")], dynamic=True)
    lp.start()
    try:
        fetch_through(lp)
        lp.rotate()
        fetch_through(lp)
        first, second = (auth_user_password(r) for r in fake.requests[:2])
        assert first != second and first.startswith("u:pw_session-") and second.startswith("u:pw_session-")
        assert lp.rotations == 1
    finally:
        lp.stop()


def test_static_rotation_uses_next_proxy():
    f1, f2 = FakeUpstream(), FakeUpstream()
    ups = [px.Upstream("127.0.0.1", f1.port, "a", "1"), px.Upstream("127.0.0.1", f2.port, "b", "2")]
    lp = px.LocalProxy(ups, dynamic=False)
    lp.start()
    try:
        fetch_through(lp)
        lp.rotate()
        fetch_through(lp)
        lp.rotate()          # volta ao primeiro (circular)
        fetch_through(lp)
        assert len(f1.requests) == 2 and len(f2.requests) == 1
        assert auth_user_password(f2.requests[0]) == "b:2"
    finally:
        lp.stop()


def test_current_ip_error_is_friendly():
    lp = px.LocalProxy([px.Upstream("127.0.0.1", 9, "u", "p")], dynamic=False)   # porta fechada
    lp.start()
    try:
        with pytest.raises(px.ProxyError, match="IP de saída"):
            px.current_ip(lp, timeout=3)
    finally:
        lp.stop()
