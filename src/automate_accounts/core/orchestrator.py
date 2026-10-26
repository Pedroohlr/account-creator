"""Executa uma fila de contas: troca de dispositivo, retries, registro no SQLite e parada."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..config import ROOT, Settings
from ..data.generator import generate_account
from ..data.repository import AccountRecord, AccountRepository
from ..flows.create_account import AccountCreationError, CreateAccountFlow, RateLimitError
from .device import DeviceManager
from .driver import clear_browser_state

log = logging.getLogger(__name__)

# Eventos enviados a on_event(kind, **dados):
#   status   -> message
#   device   -> number, total   (dispositivo atual / total previsto)
#   progress -> done, total
#   account  -> record (AccountRecord)
#   cooldown -> seconds, wait, max_waits   (site limitando tentativas; aguardando)
EventCallback = Callable[..., None]

MAX_FAILS_BEFORE_ROTATE = 3   # falhas seguidas → troca de dispositivo de emergência


@dataclass
class BatchResult:
    created: int = 0
    failed: int = 0
    stopped: bool = False
    devices: int = 0
    error: str | None = None
    seconds: float = 0.0


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
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.emit = on_event
        self.stop = stop or threading.Event()
        self.device_factory = device_factory
        self.flow_factory = flow_factory
        self.generator = generator
        self.rate_limited = False   # True quando desistimos por limite persistente do site

    def _sleep(self, seconds: float) -> None:
        self.stop.wait(seconds)     # acorda na hora se o usuário parar

    def _cooldown(self, wait_number: int) -> None:
        """Espera o site liberar novas tentativas, avisando a contagem regressiva."""
        cfg = self.settings.accounts
        log.warning(
            "Site limitando tentativas ('Muitas tentativas'). Aguardando %ds (%d/%d).",
            cfg.rate_limit_wait, wait_number, cfg.rate_limit_max_waits,
        )
        for remaining in range(cfg.rate_limit_wait, 0, -1):
            if self.stop.is_set():
                return
            self.emit("cooldown", seconds=remaining, wait=wait_number, max_waits=cfg.rate_limit_max_waits)
            self._sleep(1)

    def _save_error_screenshot(self, driver) -> None:
        shots = ROOT / "screenshots"
        shots.mkdir(exist_ok=True)
        path = shots / f"erro_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            driver.save_screenshot(str(path))
        except Exception:
            log.debug("Não foi possível salvar screenshot.", exc_info=True)

    def _create_one(self, driver, device_number: int) -> AccountRecord:
        cfg = self.settings.accounts
        started = time.monotonic()
        data = self.generator()
        error = "desconhecido"
        attempt = waits = 0
        while attempt < cfg.retries + 1:
            if self.stop.is_set():
                error = "interrompido"
                break
            try:
                clear_browser_state(driver)
                self.flow_factory(driver, self.settings.target_url).run(data)
                return self.repo.add(
                    data.email, data.password, "criada",
                    duration=time.monotonic() - started, device=device_number,
                )
            except RateLimitError as exc:
                # limite do site: esperar não gasta tentativa (repetir na hora só piora)
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
            duration=time.monotonic() - started, device=device_number,
        )

    def run(self, count: int) -> BatchResult:
        cfg = self.settings.accounts
        result = BatchResult()
        began = time.monotonic()
        total_devices = math.ceil(count / cfg.per_device)

        self.emit("status", message="Iniciando emulador e Appium...")
        device = self.device_factory(self.settings)
        try:
            driver = device.open()
            result.devices = device.number
            self.emit("device", number=device.number, total=total_devices)
            on_device = consecutive_fails = rotations_without_success = 0

            for done in range(count):
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
                        driver = device.rotate()
                    except Exception as exc:
                        log.exception("Troca de dispositivo falhou")
                        result.error = f"Troca de dispositivo falhou: {exc}"
                        break
                    result.devices = device.number
                    self.emit("device", number=device.number, total=max(total_devices, device.number))
                    on_device = consecutive_fails = 0

                self.emit("status", message=f"Criando conta {done + 1} de {count}...")
                record = self._create_one(driver, device.number)
                on_device += 1
                if record.status == "criada":
                    result.created += 1
                    consecutive_fails = rotations_without_success = 0
                else:
                    result.failed += 1
                    consecutive_fails += 1
                self.emit("account", record=record)
                self.emit("progress", done=done + 1, total=count)
                if self.rate_limited:
                    result.error = (
                        "O site continua limitando as tentativas ('Muitas tentativas'). "
                        "Aguarde um tempo maior (ou use outro IP) e rode de novo."
                    )
                    break
                if done + 1 < count and not self.stop.is_set():
                    time.sleep(cfg.delay_between)
        finally:
            self.emit("status", message="Encerrando emulador e Appium...")
            device.close()
            result.seconds = time.monotonic() - began
        self.emit("status", message="Encerrado.")
        return result
