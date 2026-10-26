"""Executa um lote de contas: troca de dispositivo, retries, proxy, pausa, métricas e registro."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..config import ROOT, Settings
from ..data import batches as batch_states
from ..data.batches import BatchRepository
from ..data.generator import generate_account
from ..data.repository import AccountRecord, AccountRepository
from ..flows.create_account import AccountCreationError, CreateAccountFlow, RateLimitError
from .device import DeviceManager
from .driver import clear_browser_state
from .proxy import ProxyError, build_proxy, current_ip

log = logging.getLogger(__name__)

# Eventos enviados a on_event(kind, **dados):
#   status   -> message
#   device   -> number, total   (dispositivo atual / total previsto)
#   progress -> done, total
#   account  -> record (AccountRecord)
#   cooldown -> seconds, wait, max_waits   (site limitando tentativas; aguardando)
#   ip       -> ip, label                  (IP de saída atual, quando há proxy)
#   paused   -> paused (bool)
#   metrics  -> bytes_in, bytes_out, cost, rotations_ip
EventCallback = Callable[..., None]

MAX_FAILS_BEFORE_ROTATE = 3   # falhas seguidas → troca de dispositivo de emergência
MAX_IP_SWAPS_PER_ACCOUNT = 5  # trocas de IP seguidas por limite do site antes de esperar


@dataclass
class BatchResult:
    created: int = 0
    failed: int = 0
    stopped: bool = False
    devices: int = 0
    error: str | None = None
    seconds: float = 0.0


class BatchLogHandler(logging.Handler):
    """Grava os logs da aplicação no registro (log) do lote."""

    def __init__(self, batches: BatchRepository, batch_id: int) -> None:
        super().__init__(logging.INFO)
        self.batches, self.batch_id = batches, batch_id

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("automate_accounts"):
            return
        try:
            source = record.name.removeprefix("automate_accounts.")
            self.batches.add_event(self.batch_id, record.levelname, source, record.getMessage())
        except Exception:   # o log nunca derruba a execução
            pass


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        repo: AccountRepository,
        on_event: EventCallback = lambda *_a, **_k: None,
        stop: threading.Event | None = None,
        device_factory=DeviceManager,
        flow_factory=CreateAccountFlow,
        generator=generate_account,
        batches: BatchRepository | None = None,
        batch_id: int | None = None,
        pause: threading.Event | None = None,
        proxy_factory=build_proxy,
        ip_lookup=current_ip,
    ) -> None:
        self.batches = batches
        self.batch_id = batch_id
        self.batch = batches.get(batch_id) if batches and batch_id else None
        # configuração própria do lote (contas por dispositivo, proxy, etc.) sobre a global
        self.settings = settings.with_overrides(self.batch.config) if self.batch else settings
        self.repo = repo
        self.emit = on_event
        self.stop = stop or threading.Event()
        self.pause = pause or threading.Event()
        self.device_factory = device_factory
        self.flow_factory = flow_factory
        self.generator = generator
        self.proxy_factory = proxy_factory
        self.ip_lookup = ip_lookup
        self.proxy = None
        self.rate_limited = False   # True quando desistimos por limite persistente do site
        self._paused_for = 0.0
        self._flushed = {"active": 0.0, "in": 0, "out": 0, "swaps": 0}
        self._cooldown_total = 0.0
        self._cooldowns = 0

    # -- utilidades -----------------------------------------------------------
    def _sleep(self, seconds: float) -> None:
        self.stop.wait(seconds)     # acorda na hora se o usuário parar

    def _set_batch(self, **fields) -> None:
        if self.batches and self.batch_id:
            self.batches.update(self.batch_id, **fields)

    def _wait_if_paused(self) -> None:
        if not self.pause.is_set() or self.stop.is_set():
            return
        began = time.monotonic()
        log.info("Lote pausado.")
        self._set_batch(status=batch_states.PAUSED)
        self.emit("paused", paused=True)
        while self.pause.is_set() and not self.stop.is_set():
            self.stop.wait(0.3)
        self._paused_for += time.monotonic() - began
        self._set_batch(status=batch_states.RUNNING)
        self.emit("paused", paused=False)
        log.info("Lote retomado.")

    def _cooldown(self, wait_number: int) -> None:
        """Espera o site liberar novas tentativas, avisando a contagem regressiva."""
        cfg = self.settings.accounts
        log.warning(
            "Site limitando tentativas ('Muitas tentativas'). Aguardando %ds (%d/%d).",
            cfg.rate_limit_wait, wait_number, cfg.rate_limit_max_waits,
        )
        began = time.monotonic()
        self._cooldowns += 1
        for remaining in range(cfg.rate_limit_wait, 0, -1):
            if self.stop.is_set():
                break
            self.emit("cooldown", seconds=remaining, wait=wait_number, max_waits=cfg.rate_limit_max_waits)
            self._sleep(1)
        self._cooldown_total += time.monotonic() - began

    def _swap_ip(self) -> None:
        """Troca o IP de saída (proxy) e confere o novo."""
        self.proxy.rotate()
        self._announce_ip("IP trocado")

    def _announce_ip(self, prefix: str) -> None:
        try:
            ip = self.ip_lookup(self.proxy)
        except ProxyError as exc:
            log.warning("%s, mas não consegui consultar o IP: %s", prefix, exc)
            ip = "?"
        log.info("%s: %s (%s)", prefix, ip, self.proxy.label)
        self.emit("ip", ip=ip, label=self.proxy.label)

    def _flush_metrics(self, began: float) -> None:
        """Grava no lote os deltas desde a última gravação (seguro de repetir)."""
        if not (self.batches and self.batch_id):
            return
        active = time.monotonic() - began - self._paused_for
        deltas = {"active_seconds": active - self._flushed["active"]}
        self._flushed["active"] = active
        if self.proxy:
            din = self.proxy.bytes_in - self._flushed["in"]
            dout = self.proxy.bytes_out - self._flushed["out"]
            dsw = self.proxy.rotations - self._flushed["swaps"]
            self._flushed.update(
                {"in": self.proxy.bytes_in, "out": self.proxy.bytes_out, "swaps": self.proxy.rotations}
            )
            deltas.update(bytes_in=din, bytes_out=dout, rotations_ip=dsw)
        deltas.update(cooldowns=self._cooldowns, cooldown_seconds=self._cooldown_total)
        self._cooldowns, self._cooldown_total = 0, 0.0
        self.batches.add_to(self.batch_id, **deltas)
        rec = self.batches.get(self.batch_id)
        cost = rec.total_bytes / 1e9 * self.settings.proxy.price_per_gb
        self.batches.update(self.batch_id, cost=cost)
        self.emit("metrics", bytes_in=rec.bytes_in, bytes_out=rec.bytes_out, cost=cost,
                  rotations_ip=rec.rotations_ip)

    def _save_error_screenshot(self, driver) -> None:
        shots = ROOT / "screenshots"
        shots.mkdir(exist_ok=True)
        path = shots / f"erro_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            driver.save_screenshot(str(path))
        except Exception:
            log.debug("Não foi possível salvar screenshot.", exc_info=True)

    # -- uma conta -----------------------------------------------------------
    def _create_one(self, driver, device_number: int) -> AccountRecord:
        cfg = self.settings.accounts
        started = time.monotonic()
        data = self.generator()
        error = "desconhecido"
        attempt = waits = swaps = 0
        while attempt < cfg.retries + 1:
            if self.stop.is_set():
                error = "interrompido"
                break
            try:
                clear_browser_state(driver)
                self.flow_factory(driver, self.settings.target_url).run(data)
                return self.repo.add(
                    data.email, data.password, "criada",
                    duration=time.monotonic() - started, device=device_number, batch_id=self.batch_id,
                )
            except RateLimitError as exc:
                if self.proxy and self.settings.proxy.rotate_on_limit and swaps < MAX_IP_SWAPS_PER_ACCOUNT:
                    # com proxy não precisa esperar: outro IP, sem o bloqueio do anterior
                    swaps += 1
                    log.warning("Site limitou o IP; trocando de IP (%d/%d).", swaps, MAX_IP_SWAPS_PER_ACCOUNT)
                    self._swap_ip()
                    continue
                waits += 1
                if waits > cfg.rate_limit_max_waits:
                    error = f"Limite do site persistiu após {cfg.rate_limit_max_waits} esperas ({exc})"
                    self.rate_limited = True
                    break
                self._cooldown(waits)
            except AccountCreationError as exc:
                attempt += 1
                error = str(exc)
                log.warning("Tentativa %d/%d falhou: %s", attempt, cfg.retries + 1, error)
                self._save_error_screenshot(driver)
        return self.repo.add(
            data.email, data.password, "falhou", error,
            duration=time.monotonic() - started, device=device_number, batch_id=self.batch_id,
        )

    # -- lote ----------------------------------------------------------------
    def run(self, count: int | None = None) -> BatchResult:
        batch = self.batch
        if batch:
            target, already, todo = batch.target_count, batch.done, batch.remaining
            device_offset = self.repo.batch_progress(batch.id)["device"]
        else:
            target = todo = count or 0
            already = device_offset = 0
        cfg = self.settings.accounts
        result = BatchResult()
        began = time.monotonic()
        log_handler = None
        if self.batches and self.batch_id:
            log_handler = BatchLogHandler(self.batches, self.batch_id)
            app_logger = logging.getLogger("automate_accounts")
            if app_logger.getEffectiveLevel() > logging.INFO:
                app_logger.setLevel(logging.INFO)      # o registro do lote precisa dos INFO
            app_logger.addHandler(log_handler)
            fields = {} if batch and batch.started_at else {"started_at": datetime.now().isoformat(timespec="seconds")}
            self._set_batch(status=batch_states.RUNNING, error=None, finished_at=None, **fields)
        device = None
        failure: Exception | None = None
        try:
            log.info("Lote iniciado: %d conta(s) a criar (%d por dispositivo).", todo, cfg.per_device)
            if self.settings.proxy.mode != "none":
                self.emit("status", message="Iniciando proxy e conferindo o IP de saída...")
                try:
                    self.proxy = self.proxy_factory(self.settings)
                    self.proxy.start()
                    self._announce_ip("IP de saída")
                except ProxyError as exc:
                    result.error = f"Proxy: {exc}"
                    log.error(result.error)
                    return result
            total_devices = device_offset + math.ceil(todo / cfg.per_device)

            self.emit("status", message="Iniciando emulador e Appium...")
            device = self.device_factory(self.settings)
            if self.proxy:
                device.proxy_port = self.proxy.port
            driver = device.open()
            number = device_offset + device.number
            result.devices = 1
            self.emit("device", number=number, total=total_devices)
            on_device = consecutive_fails = rotations_without_success = 0

            for i in range(todo):
                self._wait_if_paused()
                if self.stop.is_set():
                    result.stopped = True
                    break

                emergency = consecutive_fails >= MAX_FAILS_BEFORE_ROTATE
                if on_device >= cfg.per_device or emergency:
                    if emergency:
                        rotations_without_success += 1
                        if rotations_without_success >= 2:
                            result.error = "Falhas seguidas mesmo após trocar de dispositivo."
                            break
                    motivo = "falhas seguidas" if emergency else f"{cfg.per_device} contas criadas"
                    self.emit("status", message=f"Trocando de dispositivo ({motivo})...")
                    try:
                        if self.proxy and self.settings.proxy.rotate_per_device:
                            self._swap_ip()
                        driver = device.rotate()
                    except Exception as exc:
                        log.exception("Troca de dispositivo falhou")
                        result.error = f"Troca de dispositivo falhou: {exc}"
                        break
                    result.devices += 1
                    number = device_offset + device.number
                    self.emit("device", number=number, total=max(total_devices, number))
                    on_device = consecutive_fails = 0

                self.emit("status", message=f"Criando conta {already + i + 1} de {target}...")
                record = self._create_one(driver, number)
                on_device += 1
                if record.status == "criada":
                    result.created += 1
                    consecutive_fails = rotations_without_success = 0
                else:
                    result.failed += 1
                    consecutive_fails += 1
                if self.batches and self.batch_id:
                    self.batches.add_to(
                        self.batch_id, created=int(record.status == "criada"),
                        failed=int(record.status != "criada"),
                    )
                self._flush_metrics(began)
                log.info("Conta %s: %s (dispositivo #%s, %.0fs)%s", record.email, record.status,
                         record.device, record.duration or 0, f" — {record.error}" if record.error else "")
                self.emit("account", record=record)
                self.emit("progress", done=already + i + 1, total=target)
                if self.rate_limited:
                    result.error = (
                        "O site continua limitando as tentativas ('Muitas tentativas'). "
                        "Aguarde um tempo maior (ou use proxy) e retome o lote."
                    )
                    break
                if i + 1 < todo and not self.stop.is_set():
                    self._sleep(cfg.delay_between)
        except Exception as exc:
            failure = exc
            raise
        finally:
            self.emit("status", message="Encerrando emulador e Appium...")
            if device is not None:
                device.close()
            result.seconds = time.monotonic() - began
            self._finish(result, failure, began, already + result.created + result.failed, target)
            if self.proxy:
                self.proxy.stop()
            if log_handler:
                logging.getLogger("automate_accounts").removeHandler(log_handler)
        self.emit("status", message="Encerrado.")
        return result

    def _finish(self, result: BatchResult, failure: Exception | None, began: float, done: int,
                target: int) -> None:
        if not (self.batches and self.batch_id):
            return
        self._flush_metrics(began)
        if result.devices:
            self.batches.add_to(self.batch_id, devices=result.devices)
        if failure or result.error:
            status, error = batch_states.FAILED, str(failure) if failure else result.error
        elif result.stopped or done < target:
            status, error = batch_states.INTERRUPTED, None
        else:
            status, error = batch_states.DONE, None
        log.info("Lote %s: %d criada(s), %d falha(s) nesta execução.", status, result.created, result.failed)
        self.batches.update(self.batch_id, status=status, error=error,
                            finished_at=datetime.now().isoformat(timespec="seconds"))
