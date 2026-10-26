"""Tela de execução: estatísticas ao vivo, progresso, contas e log."""
from __future__ import annotations

import logging
import statistics
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
from ..data.report import fmt_bytes, fmt_money
from ..data.repository import AccountRecord
from .estimate import (
    DEFAULT_ACCOUNT_SECONDS,
    ROTATE_WIPE_SECONDS,
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
        Binding("p", "pause", "Pausar/Retomar"),
        Binding("escape", "back", "Voltar"),
    ]

    def __init__(self, job: str, batch_id: int | None = None) -> None:
        super().__init__()
        self.job = job
        self.batch_id = batch_id
        self.batch = None
        self.count = 1
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.finished = False
        self.handler: UiLogHandler | None = None
        # estatísticas
        self.created = self.failed = 0
        self.device_number = 0
        self.device_total = 0
        self.durations: list[float] = []
        self.started = time.monotonic()
        self.base_active = 0.0          # tempo ativo de execuções anteriores do mesmo lote
        self.paused_total = 0.0
        self.paused_since: float | None = None
        # proxy
        self.ip = "—"
        self.metrics = {"bytes_in": 0, "bytes_out": 0, "cost": 0.0, "rotations_ip": 0}

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        if self.job == "batch":
            self.batch = self.app.batches.get(self.batch_id)  # type: ignore[attr-defined]
            self.count = self.batch.target_count
            self.created, self.failed = self.batch.created, self.batch.failed
            self.base_active = self.batch.active_seconds
            self.metrics = {"bytes_in": self.batch.bytes_in, "bytes_out": self.batch.bytes_out,
                            "cost": self.batch.cost, "rotations_ip": self.batch.rotations_ip}
            title = f"LOTE #{self.batch.id} · {self.batch.name} · {self.count} CONTA(S)"
        else:
            title = "TESTE DE INFRAESTRUTURA"
        yield Label(title, classes="section")
        if self.job == "batch":
            with Horizontal(classes="cards"):
                yield StatCard("Criadas", str(self.created), id="c-created", classes="good")
                yield StatCard("Falhas", str(self.failed), id="c-failed")
                yield StatCard("Dispositivo", "—", id="c-device")
                yield StatCard("Decorrido", "0s", id="c-elapsed")
                yield StatCard("Típico / conta", "—", id="c-avg")
                yield StatCard("Restante", "—", id="c-eta")
            yield ProgressBar(total=self.count, show_eta=False, id="progress")
            yield Static("", id="proxy-line", classes="hint")
        yield Static("Preparando...", id="status")
        if self.job == "batch":
            yield DataTable(id="results", zebra_stripes=True)
        yield RichLog(id="log", markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Account Creator"
        if self.job == "batch":
            table = self.query_one("#results", DataTable)
            table.add_columns("#", "E-mail", "Senha", "Dispositivo", "Status", "Tempo", "Hora")
            self.query_one(ProgressBar).update(progress=self.created + self.failed)
            for rec in self.app.repo.list_for_batch(self.batch_id):  # type: ignore[attr-defined]
                self.show_row(rec, rec.created_at[11:19])
                if rec.duration:
                    self.durations.append(rec.duration)
            per_device = self.app.settings.with_overrides(self.batch.config).accounts.per_device  # type: ignore[attr-defined]
            self.device_total = -(-self.batch.remaining // per_device)
            self.refresh_proxy_line()
            self.refresh_cards()
            self.set_interval(1, self.tick)
        self.handler = UiLogHandler(self)
        logging.getLogger().addHandler(self.handler)
        self.run_job()

    def on_unmount(self) -> None:
        self.stop_event.set()
        self.pause_event.clear()
        if self.handler:
            logging.getLogger().removeHandler(self.handler)

    # -- thread de trabalho ------------------------------------------------
    @work(thread=True)
    def run_job(self) -> None:
        app = self.app
        emit = lambda kind, **data: app.call_from_thread(self.handle_event, kind, data)
        try:
            if self.job == "batch":
                result = Orchestrator(
                    app.settings, app.repo, emit, self.stop_event,  # type: ignore[attr-defined]
                    batches=app.batches, batch_id=self.batch_id, pause=self.pause_event,  # type: ignore[attr-defined]
                ).run()
                summary = (
                    f"Concluído: {result.created} criadas, {result.failed} falhas, "
                    f"{result.devices} dispositivo(s), {fmt_duration(result.seconds)}"
                )
                if result.stopped:
                    summary += " (interrompido — dá para retomar na aba Lotes)"
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
        elif kind == "cooldown":
            mins, secs = divmod(data["seconds"], 60)
            self.query_one("#status", Static).update(
                f"[{AMBER}]Site limitando tentativas ('Muitas tentativas') — retomando em "
                f"{mins}:{secs:02d}  (espera {data['wait']}/{data['max_waits']})[/]"
            )
        elif kind == "device":
            self.device_number, self.device_total = data["number"], data["total"]
            self.refresh_cards()
        elif kind == "progress":
            self.query_one(ProgressBar).update(progress=data["done"])
        elif kind == "account":
            self.add_account(data["record"])
        elif kind == "ip":
            self.ip = data["ip"]
            self.refresh_proxy_line()
        elif kind == "metrics":
            self.metrics = {k: data[k] for k in self.metrics}
            self.refresh_proxy_line()
        elif kind == "paused":
            self.set_paused(data["paused"])
        elif kind == "done":
            self.finished = True
            self.query_one("#status", Static).update(f"{data['message']}    [Esc] voltar")
            self.write_log(data["message"], logging.ERROR if data["message"].startswith(("ERRO", "ATEN")) else logging.INFO)
            if self.job == "batch":
                self.refresh_cards()
            self.app.refresh_data()  # type: ignore[attr-defined]
            self.app.bell()

    def set_paused(self, paused: bool) -> None:
        if paused and self.paused_since is None:
            self.paused_since = time.monotonic()
            self.query_one("#status", Static).update(f"[{AMBER}]⏸ PAUSADO — pressione P para retomar[/]")
        elif not paused and self.paused_since is not None:
            self.paused_total += time.monotonic() - self.paused_since
            self.paused_since = None
            self.query_one("#status", Static).update("Retomando...")

    def show_row(self, record: AccountRecord, hour: str) -> None:
        table = self.query_one("#results", DataTable)
        table.add_row(
            str(table.row_count + 1), record.email, record.password, f"#{record.device or '?'}",
            status_text(record.status), fmt_duration(record.duration), hour,
        )
        table.scroll_end(animate=False)

    def add_account(self, record: AccountRecord) -> None:
        if record.status == "criada":
            self.created += 1
        else:
            self.failed += 1
        if record.duration:
            self.durations.append(record.duration)
        self.show_row(record, datetime.now().strftime("%H:%M:%S"))
        ok = record.status == "criada"
        self.write_log(f"{record.email}  {record.status}" + ("" if ok else f"  ({record.error})"),
                       logging.INFO if ok else logging.ERROR)
        self.refresh_cards()

    def avg_seconds(self) -> float | None:
        """Mediana: a 1ª conta após trocar de dispositivo é mais lenta e distorceria a média."""
        return statistics.median(self.durations) if self.durations else None

    def eta_seconds(self) -> float | None:
        remaining = self.count - self.created - self.failed
        if remaining <= 0:
            return 0.0
        avg = self.avg_seconds() or DEFAULT_ACCOUNT_SECONDS
        rotations_left = max(0, self.device_total - max(self.device_number, 1))
        return remaining * avg + rotations_left * ROTATE_WIPE_SECONDS

    def refresh_cards(self) -> None:
        q = self.query_one
        q("#c-created", StatCard).set(str(self.created))
        q("#c-failed", StatCard).set(str(self.failed), "bad" if self.failed else "")
        q("#c-device", StatCard).set(f"{self.device_number or '—'} / {self.device_total}")
        q("#c-avg", StatCard).set(fmt_duration(self.avg_seconds()))
        q("#c-eta", StatCard).set("—" if self.finished else fmt_duration(self.eta_seconds()))
        self.tick()

    def refresh_proxy_line(self) -> None:
        mode = self.app.settings.with_overrides(self.batch.config).proxy.mode  # type: ignore[attr-defined]
        line = self.query_one("#proxy-line", Static)
        if mode == "none":
            line.update("Conexão direta (sem proxy)")
            return
        m, cur = self.metrics, self.batch.currency
        line.update(
            f"Proxy {mode}  ·  IP de saída {self.ip}  ·  tráfego {fmt_bytes(m['bytes_in'] + m['bytes_out'])}"
            f"  ·  custo {fmt_money(m['cost'], cur)}  ·  trocas de IP {m['rotations_ip']}"
        )

    def tick(self) -> None:
        if self.job == "batch" and not self.finished:
            paused_now = time.monotonic() - self.paused_since if self.paused_since else 0.0
            active = self.base_active + time.monotonic() - self.started - self.paused_total - paused_now
            self.query_one("#c-elapsed", StatCard).set(fmt_duration(active))

    def write_log(self, line: str, level: int = logging.INFO) -> None:
        style = RED if level >= logging.ERROR else AMBER if level >= logging.WARNING else GREEN_SOFT
        self.query_one("#log", RichLog).write(Text(line, style=style))

    # -- ações -------------------------------------------------------------
    def action_stop(self) -> None:
        if not self.finished:
            self.stop_event.set()
            self.query_one("#status", Static).update("Parando após a conta atual...")

    def action_pause(self) -> None:
        if self.finished or self.job != "batch":
            return
        if self.pause_event.is_set():
            self.pause_event.clear()
        else:
            self.pause_event.set()
            self.query_one("#status", Static).update(f"[{AMBER}]Pausando após a conta atual... (P para cancelar)[/]")

    def action_back(self) -> None:
        if self.finished:
            self.app.pop_screen()
        else:
            self.notify("Em execução. Pressione S para parar antes de voltar.", severity="warning")
