from pathlib import Path

import pytest
from textual.widgets import DataTable, OptionList

from automate_accounts.config import Settings
from automate_accounts.data.repository import AccountRepository
from automate_accounts.ui.app import AccountsApp, AccountsScreen, CountScreen, MenuScreen


@pytest.fixture
def app(tmp_path: Path) -> AccountsApp:
    settings = Settings(target_url="https://x.test", avd_name="Pixel", android_home=tmp_path)
    repo = AccountRepository(tmp_path / "t.db")
    repo.add("a@auth4.app", "pw", "criada")
    repo.add("b@auth4.app", "pw", "falhou", "timeout")
    return AccountsApp(settings, repo)


async def test_menu_shows_options_and_counts(app):
    async with app.run_test() as pilot:
        assert isinstance(app.screen, MenuScreen)
        assert app.screen.query_one(OptionList).option_count == 5
        info = str(app.screen.query_one("#info").render())
        assert "Pixel" in info and "1 criadas" in info and "1 falhas" in info


async def test_accounts_screen_lists_and_goes_back(app):
    async with app.run_test() as pilot:
        await pilot.press("4")
        assert isinstance(app.screen, AccountsScreen)
        assert app.screen.query_one(DataTable).row_count == 2
        await pilot.press("escape")
        assert isinstance(app.screen, MenuScreen)


async def test_count_dialog_validates(app):
    async with app.run_test() as pilot:
        await pilot.press("2")
        assert isinstance(app.screen, CountScreen)
        await pilot.press("escape")
        assert isinstance(app.screen, MenuScreen)


async def test_quit(app):
    async with app.run_test() as pilot:
        await pilot.press("5")
