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
from ..flows.create_account import AccountCreationError, CreateAccountFlow
from .device import DeviceManager
from .driver import clear_browser_state

log = logging.getLogger(__name__)

# Eventos enviados a on_event(kind, **dados):
#   status   -> message
#   device   -> number, total   (dispositivo atual / total previsto)
#   progress -> done, total
#   account  -> record (AccountRecord)
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
        for attempt in range(1, cfg.retries + 2):
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
            except AccountCreationError as exc:
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
                if done + 1 < count and not self.stop.is_set():
                    time.sleep(cfg.delay_between)
        finally:
            self.emit("status", message="Encerrando emulador e Appium...")
            device.close()
            result.seconds = time.monotonic() - began
        self.emit("status", message="Encerrado.")
        return result
