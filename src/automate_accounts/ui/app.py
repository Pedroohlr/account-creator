"""Menu interativo no terminal (Textual), tema verde."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import DataTable, Footer, Input, Label, OptionList, ProgressBar, RichLog, Static
from textual.widgets.option_list import Option

from ..config import Settings
from ..core.orchestrator import Orchestrator
from ..core.session import mobile_session
from ..data.repository import AccountRecord, AccountRepository

log = logging.getLogger("ui")

GREEN = "#22c55e"
RED = "#ef4444"

CSS = """
Screen { background: #07130b; color: #d1fae5; }
Footer { background: #0b1f12; color: #86efac; }
Label.title { color: #22c55e; text-style: bold; margin: 1 2 0 2; }
Static.hint { color: #4ade80; margin: 0 2; }

#banner {
    width: 64; height: auto; margin: 1 0 0 0; padding: 1 2;
    border: double #22c55e; background: #0b1f12; color: #22c55e;
    text-align: center; text-style: bold;
}
#info { width: 64; height: auto; margin: 1 0; color: #86efac; text-align: center; }
#menu { width: 64; height: auto; max-height: 14; border: round #22c55e; background: #0b1f12; }
OptionList > .option-list--option-highlighted { background: #16a34a; color: #052e16; text-style: bold; }
OptionList:focus > .option-list--option-highlighted { background: #22c55e; color: #052e16; }

DataTable { background: #0b1f12; border: round #166534; margin: 0 1; height: 1fr; }
DataTable > .datatable--header { background: #14532d; color: #bbf7d0; text-style: bold; }
DataTable > .datatable--cursor { background: #16a34a; color: #052e16; }
RichLog { background: #04100a; border: round #166534; margin: 0 1; height: 1fr; }
#status { margin: 1 2 0 2; color: #4ade80; text-style: bold; }
ProgressBar { margin: 0 2; }
Bar > .bar--bar { color: #22c55e; background: #14532d; }
Bar > .bar--complete { color: #4ade80; }
PercentageStatus { color: #86efac; }

CountScreen { align: center middle; background: #07130bcc; }
#dialog { width: 50; height: auto; padding: 1 2; border: double #22c55e; background: #0b1f12; }
#dialog Label { color: #86efac; margin-bottom: 1; }
Input { background: #04100a; border: tall #166534; color: #d1fae5; }
Input:focus { border: tall #22c55e; }
"""

MENU_ITEMS = [
    ("one", "1  ▸  Criar 1 conta"),
    ("many", "2  ▸  Criar várias contas"),
    ("smoke", "3  ▸  Testar infraestrutura (emulador + Appium)"),
    ("accounts", "4  ▸  Ver contas criadas"),
    ("quit", "5  ▸  Sair"),
]


def status_text(status: str) -> Text:
    return Text("✔ criada", style=GREEN) if status == "criada" else Text("✘ falhou", style=RED)


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
            self.screen.app.call_from_thread(
                self.screen.write_log, self.format(record), record.levelno
            )
        except Exception:  # app já fechou ou chamada na thread principal
            pass


class CountScreen(ModalScreen[int | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Cancelar")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("Quantas contas deseja criar? (1 a 500)")
            yield Input(placeholder="ex.: 10", type="integer", id="count")
            yield Static("Enter confirma · Esc cancela", classes="hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value.isdigit() and 1 <= int(value) <= 500:
            self.dismiss(int(value))
        else:
            self.notify("Digite um número entre 1 e 500.", severity="warning")


class MenuScreen(Screen):
    BINDINGS = [
        Binding("1", "pick('one')", "1 conta"),
        Binding("2", "pick('many')", "Várias"),
        Binding("3", "pick('smoke')", "Testar"),
        Binding("4", "pick('accounts')", "Contas"),
        Binding("5,q", "pick('quit')", "Sair"),
    ]

    def compose(self) -> ComposeResult:
        with Center():
            yield Static("ACCOUNT CREATOR\n[dim]automação de contas · homologação[/dim]", id="banner")
        with Center():
            yield Static("", id="info")
        with Center():
            yield OptionList(*[Option(label, id=key) for key, label in MENU_ITEMS], id="menu")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_screen_resume(self) -> None:
        app: AccountsApp = self.app  # type: ignore[assignment]
        counts = app.repo.counts()
        self.query_one("#info", Static).update(
            f"AVD: {app.settings.avd_name}   ·   "
            f"[{GREEN}]{counts['criada']} criadas[/]   [{RED}]{counts['falhou']} falhas[/]"
        )

    @on(OptionList.OptionSelected)
    def selected(self, event: OptionList.OptionSelected) -> None:
        self.action_pick(event.option_id)

    def action_pick(self, key: str) -> None:
        self.app.handle_menu(key)  # type: ignore[attr-defined]


class AccountsScreen(Screen):
    BINDINGS = [Binding("escape,q", "app.pop_screen", "Voltar")]

    def compose(self) -> ComposeResult:
        yield Label("CONTAS CRIADAS (últimas 200)", classes="title")
        yield DataTable(zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("#", "E-mail", "Senha", "Status", "Data", "Erro")
        repo: AccountRepository = self.app.repo  # type: ignore[attr-defined]
        for r in repo.list_recent(200):
            table.add_row(
                str(r.id), r.email, r.password, status_text(r.status),
                r.created_at.replace("T", " "), (r.error or "")[:60],
            )
        table.focus()


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

    def compose(self) -> ComposeResult:
        title = "TESTE DE INFRAESTRUTURA" if self.job == "smoke" else f"CRIANDO {self.count} CONTA(S)"
        yield Label(title, classes="title")
        yield Static("Preparando...", id="status")
        if self.job == "batch":
            yield ProgressBar(total=self.count, show_eta=False, id="progress")
            yield DataTable(id="results", zebra_stripes=True)
        yield RichLog(id="log", markup=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        if self.job == "batch":
            self.query_one("#results", DataTable).add_columns("#", "E-mail", "Senha", "Status", "Hora")
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
        app: AccountsApp = self.app  # type: ignore[assignment]
        emit = lambda kind, **data: app.call_from_thread(self.handle_event, kind, data)  # noqa: E731
        try:
            if self.job == "batch":
                result = Orchestrator(app.settings, app.repo, emit, self.stop_event).run(self.count)
                summary = f"Concluído: {result.created} criadas, {result.failed} falhas" + (
                    " (interrompido)" if result.stopped else ""
                )
            else:
                with mobile_session(app.settings) as driver:
                    driver.get(app.settings.target_url)
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
        elif kind == "progress":
            self.query_one(ProgressBar).update(progress=data["done"])
        elif kind == "account":
            record: AccountRecord = data["record"]
            table = self.query_one("#results", DataTable)
            table.add_row(
                str(table.row_count + 1), record.email, record.password,
                status_text(record.status), datetime.now().strftime("%H:%M:%S"),
            )
            table.scroll_end(animate=False)
            self.write_log(f"{record.email}  {record.status}", logging.INFO if record.status == "criada" else logging.ERROR)
        elif kind == "done":
            self.finished = True
            self.query_one("#status", Static).update(f"{data['message']}   [Esc] voltar ao menu")

    def write_log(self, line: str, level: int = logging.INFO) -> None:
        style = RED if level >= logging.ERROR else "#fbbf24" if level >= logging.WARNING else "#86efac"
        self.query_one("#log", RichLog).write(Text(line, style=style))

    def action_stop(self) -> None:
        if not self.finished:
            self.stop_event.set()
            self.query_one("#status", Static).update("Parando após a conta atual...")

    def action_back(self) -> None:
        if self.finished:
            self.app.pop_screen()
        else:
            self.notify("Em execução. Pressione S para parar antes de voltar.", severity="warning")


class AccountsApp(App):
    CSS = CSS
    TITLE = "Account Creator"
    BINDINGS = [Binding("ctrl+c", "request_quit", show=False)]

    def __init__(self, settings: Settings, repo: AccountRepository | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.repo = repo or AccountRepository()

    def on_mount(self) -> None:
        self.push_screen(MenuScreen())

    def action_request_quit(self) -> None:
        if isinstance(self.screen, RunScreen) and not self.screen.finished:
            self.notify("Em execução. Pressione S para parar.", severity="warning")
        else:
            self.exit()

    def handle_menu(self, key: str) -> None:
        if key == "one":
            self.push_screen(RunScreen("batch", 1))
        elif key == "many":
            self.push_screen(CountScreen(), self._start_many)
        elif key == "smoke":
            self.push_screen(RunScreen("smoke"))
        elif key == "accounts":
            self.push_screen(AccountsScreen())
        elif key == "quit":
            self.exit()

    def _start_many(self, count: int | None) -> None:
        if count:
            self.push_screen(RunScreen("batch", count))

