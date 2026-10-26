from pathlib import Path

import pytest
import yaml
from textual.widgets import Button, DataTable, Input, Select, Static, Switch, TabbedContent

from automate_accounts.config import Settings
from automate_accounts.core import health
from automate_accounts.core.orchestrator import BatchResult
from automate_accounts.data.repository import AccountRepository
from automate_accounts.ui import pages, run_screen
from automate_accounts.ui.app import AccountsApp
from automate_accounts.ui.pages import AccountsPane, HealthPane, NewRunPane, SettingsPane
from automate_accounts.ui.run_screen import RunScreen
from automate_accounts.ui.widgets import StatCard


@pytest.fixture
def app(tmp_path: Path) -> AccountsApp:
    settings = Settings(target_url="https://x.test/login", avd_name="Pixel", android_home=tmp_path)
    repo = AccountRepository(tmp_path / "t.db")
    repo.add("ana@auth4.app", "pw", "criada", duration=100.0, device=1)
    repo.add("bia@auth4.app", "pw", "falhou", "timeout", duration=50.0, device=1)
    repo.add("caio@auth4.app", "pw", "criada", duration=200.0, device=2)
    return AccountsApp(settings, repo, local_config_path=tmp_path / "config.local.yaml",
                       config_path=tmp_path / "config.yaml")


def card_value(app, card_id: str) -> str:
    return str(app.screen.query_one(card_id, StatCard).query_one(".card-value").render())


async def test_tabs_and_dashboard_numbers(app):
    async with app.run_test() as pilot:
        tabs = app.query_one(TabbedContent)
        assert tabs.active == "tab-dashboard"
        assert card_value(app, "#d-created") == "2"
        assert card_value(app, "#d-failed") == "1"
        assert card_value(app, "#d-rate") == "67%"
        assert app.query_one("#d-recent", DataTable).row_count == 3
        for key, tab in (("f2", "tab-new"), ("f3", "tab-accounts"), ("f4", "tab-health"), ("f5", "tab-settings")):
            await pilot.press(key)
            assert tabs.active == tab


async def test_new_run_estimate_reacts_to_inputs(app):
    async with app.run_test() as pilot:
        app.show_tab("tab-new")
        await pilot.pause()
        pane = app.query_one(NewRunPane)
        box = pane.query_one("#estimate", Static)
        before = str(box.render())
        assert "4 dispositivo(s)" not in before  # padrão: 5 contas / 5 por dispositivo = 1
        pane.query_one("#nr-count", Input).value = "20"
        await pilot.pause()
        text = str(box.render())
        assert "4 dispositivo(s)" in text and "Estimativa" in text
        pane.query_one("#nr-count", Input).value = "0"
        await pilot.pause()
        assert "Quantidade" in str(box.render())


async def test_accounts_filter_and_export(app, tmp_path, monkeypatch):
    monkeypatch.setattr(pages, "ROOT", tmp_path)
    async with app.run_test() as pilot:
        app.show_tab("tab-accounts")
        await pilot.pause()
        pane = app.query_one(AccountsPane)
        table = pane.query_one("#a-table", DataTable)
        assert table.row_count == 3
        pane.query_one("#a-status", Select).value = "falhou"
        await pilot.pause()
        assert table.row_count == 1
        pane.query_one("#a-status", Select).value = ""
        pane.query_one("#a-search", Input).value = "caio"
        await pilot.pause()
        assert table.row_count == 1
        pane.query_one("#a-search", Input).value = ""
        await pilot.pause()
        pane.query_one("#a-export", Button).press()
        await pilot.pause()
        files = list((tmp_path / "exports").glob("contas_*.csv"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8-sig")
        assert "ana@auth4.app" in content and content.splitlines()[0].startswith("id;email")


async def test_health_runs_checks_and_updates_dashboard(app):
    def fake_ok(_s):
        return health.Check("Python", health.OK, "3.13")

    def fake_bad(_s):
        return health.Check("Appium", health.FAIL, "ausente", "npm i -g appium")

    app.health_checks = [("Python", fake_ok), ("Appium", fake_bad)]
    async with app.run_test() as pilot:
        app.show_tab("tab-health")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        pane = app.query_one(HealthPane)
        table = pane.query_one("#h-table", DataTable)
        assert table.row_count == 2
        assert "1 de 2 OK" in str(pane.query_one("#h-summary", Static).render())
        assert table.get_cell("Appium", "hint") == "npm i -g appium"
        assert "1 erro" in card_value(app, "#d-health")


async def test_settings_save_and_validation(app, tmp_path):
    async with app.run_test() as pilot:
        app.show_tab("tab-settings")
        await pilot.pause()
        pane = app.query_one(SettingsPane)
        pane.query_one("#st-per", Input).value = "3"
        pane.query_one("#st-ua", Switch).value = True
        pane.query_one("#st-save", Button).press()
        await pilot.pause()
        saved = yaml.safe_load((tmp_path / "config.local.yaml").read_text(encoding="utf-8"))
        assert saved["accounts"]["per_device"] == 3 and saved["accounts"]["random_user_agent"] is True
        assert app.settings.accounts.per_device == 3

        (tmp_path / "config.local.yaml").unlink()
        pane.query_one("#st-per", Input).value = "9999"   # fora do limite → não grava
        pane.query_one("#st-save", Button).press()
        await pilot.pause()
        assert not (tmp_path / "config.local.yaml").exists()
        assert app.settings.accounts.per_device == 3


async def test_run_screen_shows_live_stats(app, monkeypatch):
    class FakeOrchestrator:
        def __init__(self, settings, repo, emit, stop):
            self.repo, self.emit = repo, emit

        def run(self, count):
            self.emit("device", number=1, total=1)
            for i in range(count):
                rec = self.repo.add(f"novo{i}@auth4.app", "pw", "criada", duration=90.0, device=1)
                self.emit("account", record=rec)
                self.emit("progress", done=i + 1, total=count)
            return BatchResult(created=count, devices=1, seconds=5)

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    async with app.run_test() as pilot:
        app.start_batch(2)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RunScreen) and screen.finished
        assert card_value(app, "#c-created") == "2"
        assert card_value(app, "#c-avg") == "1min30s"
        assert screen.query_one("#results", DataTable).row_count == 2
        assert "Concluído: 2 criadas" in str(screen.query_one("#status", Static).render())
        await pilot.press("escape")
        assert not isinstance(app.screen, RunScreen)
        assert card_value(app, "#d-created") == "4"   # dashboard atualizado ao terminar
