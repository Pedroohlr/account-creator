"""Painel interativo no terminal (Textual), tema verde."""
from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from ..config import LOCAL_CONFIG, Settings, load_settings, save_local_settings
from ..core import health
from ..core.emulator import EmulatorManager
from ..data.repository import AccountRepository
from .estimate import devices_needed
from .pages import AccountsPane, DashboardPane, HealthPane, NewRunPane, SettingsPane
from .run_screen import RunScreen
from .theme import CSS

TABS = [
    ("tab-dashboard", "Painel"),
    ("tab-new", "Nova execução"),
    ("tab-accounts", "Contas"),
    ("tab-health", "Saúde"),
    ("tab-settings", "Configurações"),
]


class ExplicitTabbedContent(TabbedContent):
    """TabbedContent que só troca de aba quando pedimos.

    O padrão do Textual ativa a aba do widget que ganhou foco; esse evento chega atrasado e
    desfazia a troca feita ao clicar num botão do Painel (voltava para a aba anterior).
    """

    def _on_tab_pane_focused(self, event) -> None:
        event.stop()


class AccountsApp(App):
    CSS = CSS
    TITLE = "Account Creator"
    BINDINGS = [
        Binding("f1", "tab('tab-dashboard')", "Painel"),
        Binding("f2", "tab('tab-new')", "Nova execução"),
        Binding("f3", "tab('tab-accounts')", "Contas"),
        Binding("f4", "tab('tab-health')", "Saúde"),
        Binding("f5", "tab('tab-settings')", "Config"),
    ]

    def __init__(
        self,
        settings: Settings,
        repo: AccountRepository | None = None,
        local_config_path: Path = LOCAL_CONFIG,
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.repo = repo or AccountRepository()
        self.local_config_path = local_config_path
        self.config_path = config_path
        self.health_checks = list(health.CHECKS)
        self.health_results: dict[str, health.Check] = {}

    # -- layout ------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with ExplicitTabbedContent(initial="tab-dashboard"):
            with TabPane("Painel", id="tab-dashboard"):
                yield DashboardPane()
            with TabPane("Nova execução", id="tab-new"):
                yield NewRunPane()
            with TabPane("Contas", id="tab-accounts"):
                yield AccountsPane()
            with TabPane("Saúde", id="tab-health"):
                yield HealthPane()
            with TabPane("Configurações", id="tab-settings"):
                yield SettingsPane()
        yield Footer()

    def on_mount(self) -> None:
        self.update_subtitle()

    def update_subtitle(self) -> None:
        self.sub_title = f"AVD {self.settings.avd_name}  ·  {self.settings.target_url}"

    # -- navegação ---------------------------------------------------------
    def show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id
        self.call_after_refresh(self._focus_pane, tab_id)

    def _focus_pane(self, tab_id: str) -> None:
        """Leva o foco para o primeiro campo da aba (o teclado continua de onde o usuário está)."""
        target = next(iter(self.query(f"#{tab_id} Input, #{tab_id} Select, #{tab_id} DataTable")), None)
        if target is not None:
            target.focus()

    def action_tab(self, tab_id: str) -> None:
        if not isinstance(self.screen, RunScreen):
            self.show_tab(tab_id)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = event.pane.id
        if pane_id == "tab-health":
            pane = self.query_one(HealthPane)
            if not pane.ran_once:
                pane.run_all()
        elif pane_id in ("tab-dashboard", "tab-accounts"):
            self.refresh_data()

    # -- ações -------------------------------------------------------------
    def devices_for(self, count: int) -> int:
        return devices_needed(count, self.settings.accounts.per_device)

    def start_batch(self, count: int) -> None:
        self.push_screen(RunScreen("batch", count))

    def start_smoke(self) -> None:
        self.push_screen(RunScreen("smoke"))

    def refresh_data(self) -> None:
        self.query_one(DashboardPane).refresh_data()
        self.query_one(AccountsPane).refresh_data()
        self.query_one(NewRunPane).update_estimate()

    def on_health(self, results: dict[str, health.Check]) -> None:
        self.health_results = results
        self.query_one(DashboardPane).set_health(results)

    def emulator_avds(self) -> list[str]:
        return EmulatorManager(self.settings).list_avds()

    def apply_settings(self, new: Settings) -> None:
        self.settings = new
        save_local_settings(new, self.local_config_path)
        self.update_subtitle()
        self.query_one(NewRunPane).load_defaults()

    def reset_settings(self) -> None:
        self.local_config_path.unlink(missing_ok=True)
        self.settings = load_settings(self.config_path)
        self.update_subtitle()
        self.query_one(NewRunPane).load_defaults()
        self.call_later(self.query_one(SettingsPane).recompose)

    async def action_quit(self) -> None:
        if isinstance(self.screen, RunScreen) and not self.screen.finished:
            self.notify("Em execução. Pressione S para parar antes de sair.", severity="warning")
            return
        self.exit()
