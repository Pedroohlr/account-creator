import threading
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


async def click_until(pilot, selector, done, tries=3):
    """Clica e espera o efeito; repete se o clique cair durante um reflow da tela (raro sob carga)."""
    for _ in range(tries):
        await pilot.click(selector)
        for _ in range(4):
            await pilot.pause(0.1)
        if done():
            return
    assert done()


async def test_tabs_and_dashboard_numbers(app):
    async with app.run_test() as pilot:
        tabs = app.query_one(TabbedContent)
        assert tabs.active == "tab-dashboard"
        assert card_value(app, "#d-created") == "2"
        assert card_value(app, "#d-failed") == "1"
        assert card_value(app, "#d-rate") == "67%"
        assert app.query_one("#d-recent", DataTable).row_count == 3
        for key, tab in (("f2", "tab-new"), ("f3", "tab-batches"), ("f4", "tab-accounts"),
                         ("f5", "tab-health"), ("f6", "tab-settings")):
            await pilot.press(key)
            await pilot.pause()
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
        def __init__(self, settings, repo, emit, stop, batches=None, batch_id=None, pause=None):
            self.repo, self.emit, self.batch_id = repo, emit, batch_id
            self.count = batches.get(batch_id).target_count

        def run(self):
            count = self.count
            self.emit("device", number=1, total=1)
            for i in range(count):
                rec = self.repo.add(f"novo{i}@auth4.app", "pw", "criada", duration=90.0, device=1)
                self.emit("account", record=rec)
                self.emit("progress", done=i + 1, total=count)
            return BatchResult(created=count, devices=1, seconds=5)

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    async with app.run_test() as pilot:
        app.start_batch(app.batches.create("T", 2).id)
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


async def test_real_mouse_clicks_switch_tab_and_start_run(app, monkeypatch):
    """Regressão: clicar no botão do Painel trocava de aba e voltava logo em seguida."""
    class FakeOrchestrator:
        def __init__(self, settings, repo, emit, stop, **_kw): ...
        def run(self):
            return BatchResult(devices=1)

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    async with app.run_test(size=(130, 40)) as pilot:
        tabs = app.query_one(TabbedContent)
        await pilot.pause(0.5)      # deixa a montagem assentar antes do clique (evita instabilidade sob carga)
        await click_until(pilot, "#go-new", lambda: tabs.active == "tab-new")
        assert tabs.active == "tab-new"

        await pilot.click("#start")
        for _ in range(3):
            await pilot.pause()
        assert isinstance(app.screen, RunScreen)
        await app.workers.wait_for_complete()


async def test_real_click_on_tab_header_and_health_button(app):
    app.health_checks = []
    async with app.run_test(size=(130, 40)) as pilot:
        tabs = app.query_one(TabbedContent)
        await pilot.pause(0.5)
        await click_until(pilot, "#go-health", lambda: tabs.active == "tab-health")
        assert tabs.active == "tab-health"
        await click_until(pilot, "#--content-tab-tab-new", lambda: tabs.active == "tab-new")   # título da aba
        assert tabs.active == "tab-new"


async def test_run_screen_shows_cooldown_countdown(app, monkeypatch):
    class FakeOrchestrator:
        def __init__(self, settings, repo, emit, stop, **_kw):
            self.emit = emit

        def run(self):
            self.emit("cooldown", seconds=125, wait=1, max_waits=6)
            return BatchResult(error="O site continua limitando as tentativas ('Muitas tentativas').")

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    async with app.run_test() as pilot:
        app.start_batch(app.batches.create("T", 1).id)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        log_lines = "\n".join(str(line) for line in app.screen.query_one("#status", Static).render().plain.splitlines())
        assert "ATENÇÃO" in log_lines and "Muitas tentativas" in log_lines


# -- lotes -------------------------------------------------------------------
from automate_accounts.data import batches as bs  # noqa: E402
from automate_accounts.ui import batches_pane  # noqa: E402
from automate_accounts.ui.batches_pane import BatchesPane  # noqa: E402


async def test_new_batch_form_creates_batch_with_its_own_config(app):
    async with app.run_test(size=(130, 50)) as pilot:
        app.show_tab("tab-new")
        await pilot.pause()
        pane = app.query_one(NewRunPane)
        pane.query_one("#nr-name", Input).value = "Meu lote"
        pane.query_one("#nr-count", Input).value = "12"
        pane.query_one("#nr-per", Input).value = "4"
        pane.query_one("#nr-notes", Input).value = "teste manhã"
        pane.query_one("#nr-price", Input).value = "7,5"
        pane.query_one("#sw-ua", Switch).value = True
        await pilot.pause()
        pane.query_one("#plan", Button).press()
        await pilot.pause()
        rec = app.batches.list_all()[0]
        assert (rec.name, rec.target_count, rec.status, rec.notes) == ("Meu lote", 12, bs.PLANNED, "teste manhã")
        assert rec.config["accounts"]["per_device"] == 4 and rec.config["accounts"]["random_user_agent"] is True
        assert rec.config["proxy"]["price_per_gb"] == 7.5 and rec.config["proxy"]["mode"] == "none"
        assert app.settings.accounts.per_device == 5          # configuração global intacta
        assert app.query_one(TabbedContent).active == "tab-batches"
        assert app.query_one("#b-table", DataTable).row_count == 1


async def test_new_batch_validation_and_proxy_requirements(app, monkeypatch):
    monkeypatch.setenv("PROXY_URL", "")
    async with app.run_test(size=(130, 50)) as pilot:
        app.show_tab("tab-new")
        await pilot.pause()
        pane = app.query_one(NewRunPane)
        pane.query_one("#nr-count", Input).value = "0"
        pane.query_one("#plan", Button).press()
        await pilot.pause()
        assert app.batches.list_all() == []                    # quantidade inválida: nada criado
        pane.query_one("#nr-count", Input).value = "3"
        pane.query_one("#nr-proxy", Select).value = "dynamic"  # sem PROXY_URL configurado
        await pilot.pause()
        with pytest.raises(ValueError, match="PROXY_URL"):
            pane.build()
        pane.query_one("#plan", Button).press()
        await pilot.pause()
        assert app.batches.list_all() == []


async def test_batches_pane_detail_export_delete(app, tmp_path, monkeypatch):
    monkeypatch.setattr(batches_pane, "ROOT", tmp_path)
    rec = app.batches.create("Lote X", 4, {"accounts": {"per_device": 2}})
    app.repo.add("z@x", "pw", "criada", duration=30, device=1, batch_id=rec.id)
    app.batches.add_to(rec.id, created=1, active_seconds=30)
    app.batches.add_event(rec.id, "INFO", "core.orchestrator", "Lote iniciado")
    app.batches.add_event(rec.id, "WARNING", "core.orchestrator", "Site limitou o IP")
    async with app.run_test(size=(140, 50)) as pilot:
        app.show_tab("tab-batches")
        await pilot.pause(0.2)
        pane = app.query_one(BatchesPane)
        table = pane.query_one("#b-table", DataTable)
        assert table.row_count == 1
        assert pane.selected == rec.id                                  # primeira linha já selecionada
        assert "Lote X" in str(pane.query_one("#b-detail", Static).render())
        assert "contas por dispositivo: 2" in str(pane.query_one("#b-detail", Static).render())
        assert len(pane.query_one("#b-log").lines) == 2
        pane.query_one("#b-only-warn", Switch).value = True
        await pilot.pause()
        assert len(pane.query_one("#b-log").lines) == 1

        pane.query_one("#b-export", Button).press()
        await pilot.pause()
        reports = list((tmp_path / "exports").glob("lote_*/relatorio.md"))
        assert len(reports) == 1 and "Lote #1 — Lote X" in reports[0].read_text(encoding="utf-8")

        pane.query_one("#b-delete", Button).press()                     # 1º clique só pede confirmação
        await pilot.pause()
        assert app.batches.get(rec.id) is not None
        pane.query_one("#b-delete", Button).press()
        await pilot.pause()
        assert app.batches.get(rec.id) is None and table.row_count == 0
        assert app.repo.list_recent()[0].batch_id is None               # conta preservada


async def test_resume_from_batches_pane_runs_only_remaining(app, monkeypatch):
    seen = {}

    class FakeOrchestrator:
        def __init__(self, settings, repo, emit, stop, batches=None, batch_id=None, pause=None):
            seen["batch_id"], seen["remaining"] = batch_id, batches.get(batch_id).remaining
            seen["pause"] = pause

        def run(self):
            return BatchResult(devices=1)

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    rec = app.batches.create("Retomar", 5)
    app.batches.add_to(rec.id, created=2)
    app.batches.update(rec.id, status=bs.INTERRUPTED)
    done = app.batches.create("Pronto", 1)
    app.batches.add_to(done.id, created=1)
    app.batches.update(done.id, status=bs.DONE)
    async with app.run_test(size=(140, 50)) as pilot:
        app.show_tab("tab-batches")
        await pilot.pause(0.2)
        pane = app.query_one(BatchesPane)
        pane.selected = done.id
        pane.query_one("#b-run", Button).press()                         # lote concluído: não inicia
        await pilot.pause()
        assert not isinstance(app.screen, RunScreen)
        pane.selected = rec.id
        pane.query_one("#b-run", Button).press()
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert isinstance(app.screen, RunScreen)
        assert seen["batch_id"] == rec.id and seen["remaining"] == 3
        assert card_value(app, "#c-created") == "2"                      # contador já parte do que existe


async def test_run_screen_proxy_line(app, monkeypatch):
    class FakeOrchestrator:
        def __init__(self, settings, repo, emit, stop, batches=None, batch_id=None, pause=None):
            self.emit = emit

        def run(self):
            self.emit("ip", ip="200.1.2.3", label="h:1")
            self.emit("metrics", bytes_in=3 * 1024 * 1024, bytes_out=1024 * 1024, cost=1.5, rotations_ip=2)
            return BatchResult()

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    rec = app.batches.create("P", 1, {"proxy": {"mode": "dynamic", "price_per_gb": 10}})
    async with app.run_test(size=(140, 50)) as pilot:
        app.start_batch(rec.id)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        line = str(app.screen.query_one("#proxy-line", Static).render())
        assert "200.1.2.3" in line and "4.0 MB" in line and "R$ 1,5000" in line and "trocas de IP 2" in line


async def test_run_screen_pause_key_toggles(app, monkeypatch):
    release = threading.Event()

    class FakeOrchestrator:
        def __init__(self, settings, repo, emit, stop, batches=None, batch_id=None, pause=None):
            pass

        def run(self):
            release.wait(5)
            return BatchResult()

    monkeypatch.setattr(run_screen, "Orchestrator", FakeOrchestrator)
    rec = app.batches.create("P2", 1)
    async with app.run_test(size=(140, 50)) as pilot:
        app.start_batch(rec.id)
        await pilot.pause()
        screen = app.screen
        await pilot.press("p")
        assert screen.pause_event.is_set()
        await pilot.press("p")
        assert not screen.pause_event.is_set()
        release.set()
        await app.workers.wait_for_complete()


async def test_interrupted_state_recovered_on_startup(tmp_path):
    settings = Settings(target_url="https://x.test/login", avd_name="Pixel", android_home=tmp_path)
    repo = AccountRepository(tmp_path / "t.db")
    first = AccountsApp(settings, repo, local_config_path=tmp_path / "c.yaml")
    rec = first.batches.create("Morto", 3)
    first.batches.update(rec.id, status=bs.RUNNING)
    second = AccountsApp(settings, repo, local_config_path=tmp_path / "c.yaml")
    assert second.batches.get(rec.id).status == bs.INTERRUPTED
