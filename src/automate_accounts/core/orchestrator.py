"""Executa uma fila de contas: retries, registro no SQLite, screenshots de erro e parada."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ..config import ROOT, Settings
from ..data.generator import generate_account
from ..data.repository import AccountRecord, AccountRepository
from ..flows.create_account import AccountCreationError, CreateAccountFlow
from .driver import clear_browser_state
from .session import mobile_session

log = logging.getLogger(__name__)

# Eventos enviados a on_event(kind, **dados):
#   status   -> message
#   progress -> done, total
#   account  -> record (AccountRecord)
EventCallback = Callable[..., None]


@dataclass
class BatchResult:
    created: int = 0
    failed: int = 0
    stopped: bool = False


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        repo: AccountRepository,
        on_event: EventCallback = lambda *_a, **_k: None,
        stop: threading.Event | None = None,
        session_factory=mobile_session,
        flow_factory=CreateAccountFlow,
        generator=generate_account,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.emit = on_event
        self.stop = stop or threading.Event()
        self.session_factory = session_factory
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

    def _create_one(self, driver) -> AccountRecord:
        cfg = self.settings.accounts
        data = self.generator()
        error = "desconhecido"
        for attempt in range(1, cfg.retries + 2):
            if self.stop.is_set():
                error = "interrompido"
                break
            try:
                clear_browser_state(driver)
                self.flow_factory(driver, self.settings.target_url).run(data)
                return self.repo.add(data.email, data.password, "criada")
            except AccountCreationError as exc:
                error = str(exc)
                log.warning("Tentativa %d/%d falhou: %s", attempt, cfg.retries + 1, error)
                self._save_error_screenshot(driver)
        return self.repo.add(data.email, data.password, "falhou", error)

    def run(self, count: int) -> BatchResult:
        result = BatchResult()
        self.emit("status", message="Iniciando emulador e Appium...")
        with self.session_factory(self.settings) as driver:
            self.emit("status", message="Pronto. Criando contas...")
            for done in range(count):
                if self.stop.is_set():
                    result.stopped = True
                    break
                self.emit("status", message=f"Criando conta {done + 1} de {count}...")
                record = self._create_one(driver)
                if record.status == "criada":
                    result.created += 1
                else:
                    result.failed += 1
                self.emit("account", record=record)
                self.emit("progress", done=done + 1, total=count)
                if done + 1 < count and not self.stop.is_set():
                    time.sleep(self.settings.accounts.delay_between)
        self.emit("status", message="Encerrado.")
        return result
