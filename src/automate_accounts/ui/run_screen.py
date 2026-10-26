"""Tela de execução: estatísticas ao vivo, progresso, contas e log."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, ProgressBar, RichLog, Static

from ..core.orchestrator import Orchestrator
from ..core.session import mobile_session
from ..data.repository import AccountRecord
from .estimate import (
    DEFAULT_ACCOUNT_SECONDS,
    DEVICE_SETUP_SECONDS,
    WIPE_EXTRA_SECONDS,
    fmt_duration,
)
from .theme import AMBER, GREEN_SOFT, RED
from .widgets import StatCard, status_text

log = logging.getLogger("ui")


class UiLogHandler(logging.Handler):
    """Encaminha os logs da aplicação para o RichLog da tela de execução."""

    def __init__(self, screen: RunScreen) -> None:
        super().__init__(logging.INFO)
        self.screen = screen
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith(("automate_accounts", "ui", "cli")):
            return
        try:
            self.screen.app.call_from_thread(self.screen.write_log, self.format(record), record.levelno)
        except Exception:  # app já fechou, ou chamada vinda da thread principal
            pass


class RunScreen(Screen):
    BINDINGS = [
        Binding("s", "stop", "Parar"),
        Binding("escape", "back", "Voltar"),
    ]

    def __init__(self, job: str, count: int = 1) -> None:
        super().__init__()
        self.job = job
        self.count = count
        self.stop_event = threading.Event()
        self.finished = False
        self.handler: UiLogHandler | None = None
        # estatísticas
        self.created = self.failed = 0
        self.device_number = 0
        self.device_total = 0
        self.durations: list[float] = []
        self.started = time.monotonic()

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        title = "TESTE DE INFRAESTRUTURA" if self.job == "smoke" else f"EXECUÇÃO · {self.count} CONTA(S)"
        yield Label(title, classes="section")
        if self.job == "batch":
            with Horizontal(classes="cards"):
                yield StatCard("Criadas", "0", id="c-created", classes="good")
                yield StatCard("Falhas", "0", id="c-failed")
                yield StatCard("Dispositivo", "—", id="c-device")
                yield StatCard("Decorrido", "0s", id="c-elapsed")
                yield StatCard("Média / conta", "—", id="c-avg")
                yield StatCard("Restante", "—", id="c-eta")
            yield ProgressBar(total=self.count, show_eta=False, id="progress")
        yield Static("Preparando...", id="status")
        if self.job == "batch":
            yield DataTable(id="results", zebra_stripes=True)
        yield RichLog(id="log", markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Account Creator"
        if self.job == "batch":
            self.query_one("#results", DataTable).add_columns(
                "#", "E-mail", "Senha", "Dispositivo", "Status", "Tempo", "Hora"
            )
            self.device_total = self.app.devices_for(self.count)  # type: ignore[attr-defined]
            self.set_interval(1, self.tick)
        self.handler = UiLogHandler(self)
        logging.getLogger().addHandler(self.handler)
        self.run_job()

    def on_unmount(self) -> None:
        self.stop_event.set()
        if self.handler:
            logging.getLogger().removeHandler(self.handler)

    # -- thread de trabalho ------------------------------------------------
    @work(thread=True)
    def run_job(self) -> None:
        app = self.app
        emit = lambda kind, **data: app.call_from_thread(self.handle_event, kind, data)
        try:
            if self.job == "batch":
                result = Orchestrator(app.settings, app.repo, emit, self.stop_event).run(self.count)  # type: ignore[attr-defined]
                summary = (
                    f"Concluído: {result.created} criadas, {result.failed} falhas, "
                    f"{result.devices} dispositivo(s), {fmt_duration(result.seconds)}"
                )
                if result.stopped:
                    summary += " (interrompido)"
                if result.error:
                    summary = f"ATENÇÃO: {result.error} — {summary}"
            else:
                with mobile_session(app.settings) as driver:  # type: ignore[attr-defined]
                    driver.get(app.settings.target_url)  # type: ignore[attr-defined]
                    log.info("Página aberta: %r em %s", driver.title, driver.current_url)
                summary = "Infraestrutura OK: emulador, Appium e Chrome funcionando."
        except Exception as exc:
            log.exception("Execução falhou")
            summary = f"ERRO: {exc}".splitlines()[0]
        emit("done", message=summary)

    # -- atualizações de UI (thread principal) ---------------------------
    def handle_event(self, kind: str, data: dict) -> None:
        if kind == "status":
            self.query_one("#status", Static).update(data["message"])
        elif kind == "device":
            self.device_number, self.device_total = data["number"], data["total"]
            self.refresh_cards()
        elif kind == "progress":
            self.query_one(ProgressBar).update(progress=data["done"])
        elif kind == "account":
            self.add_account(data["record"])
        elif kind == "done":
            self.finished = True
            self.query_one("#status", Static).update(f"{data['message']}    [Esc] voltar")
            self.write_log(data["message"], logging.ERROR if data["message"].startswith(("ERRO", "ATEN")) else logging.INFO)
            if self.job == "batch":
                self.refresh_cards()
            self.app.refresh_data()  # type: ignore[attr-defined]
            self.app.bell()

    def add_account(self, record: AccountRecord) -> None:
        if record.status == "criada":
            self.created += 1
        else:
            self.failed += 1
        if record.duration:
            self.durations.append(record.duration)
        table = self.query_one("#results", DataTable)
        table.add_row(
            str(table.row_count + 1), record.email, record.password, f"#{record.device or '?'}",
            status_text(record.status), fmt_duration(record.duration), datetime.now().strftime("%H:%M:%S"),
        )
        table.scroll_end(animate=False)
        ok = record.status == "criada"
        self.write_log(f"{record.email}  {record.status}" + ("" if ok else f"  ({record.error})"),
                       logging.INFO if ok else logging.ERROR)
        self.refresh_cards()

    def avg_seconds(self) -> float | None:
        return sum(self.durations) / len(self.durations) if self.durations else None

    def eta_seconds(self) -> float | None:
        remaining = self.count - self.created - self.failed
        if remaining <= 0:
            return 0.0
        avg = self.avg_seconds() or DEFAULT_ACCOUNT_SECONDS
        rotations_left = max(0, self.device_total - max(self.device_number, 1))
        return remaining * avg + rotations_left * (DEVICE_SETUP_SECONDS + WIPE_EXTRA_SECONDS)

    def refresh_cards(self) -> None:
        q = self.query_one
        q("#c-created", StatCard).set(str(self.created))
        q("#c-failed", StatCard).set(str(self.failed), "bad" if self.failed else "")
        q("#c-device", StatCard).set(f"{self.device_number or '—'} / {self.device_total}")
        q("#c-avg", StatCard).set(fmt_duration(self.avg_seconds()))
        q("#c-eta", StatCard).set("—" if self.finished else fmt_duration(self.eta_seconds()))
        self.tick()

    def tick(self) -> None:
        if self.job == "batch" and not self.finished:
            self.query_one("#c-elapsed", StatCard).set(fmt_duration(time.monotonic() - self.started))

    def write_log(self, line: str, level: int = logging.INFO) -> None:
        style = RED if level >= logging.ERROR else AMBER if level >= logging.WARNING else GREEN_SOFT
        self.query_one("#log", RichLog).write(Text(line, style=style))

    # -- ações -------------------------------------------------------------
    def action_stop(self) -> None:
        if not self.finished:
            self.stop_event.set()
            self.query_one("#status", Static).update("Parando após a conta atual...")

    def action_back(self) -> None:
        if self.finished:
            self.app.pop_screen()
        else:
            self.notify("Em execução. Pressione S para parar antes de voltar.", severity="warning")
