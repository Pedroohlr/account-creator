"""Teste de integração do fluxo de cadastro contra o site de homologação, no Chrome do desktop.

Não usa emulador: roda em ~1 min. Cria contas de teste de verdade (o site permite), por isso
só roda com:  pytest -m live
"""
import pytest
from selenium import webdriver

from automate_accounts.config import load_settings
from automate_accounts.core.driver import clear_browser_state
from automate_accounts.data.generator import generate_account
from automate_accounts.flows.create_account import AccountCreationError, CreateAccountFlow

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_experimental_option("mobileEmulation", {"deviceName": "Pixel 7"})
    drv = webdriver.Chrome(options=options)
    yield drv
    drv.quit()


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.mark.parametrize("gender", ["female", "male", "unspecified"])
def test_creates_account_for_each_gender(driver, settings, gender):
    clear_browser_state(driver)
    data = generate_account()
    data = type(data)(**{**data.__dict__, "gender": gender})
    CreateAccountFlow(driver, settings.target_url).run(data)
    assert "/conta" in driver.current_url
    assert data.first_name in driver.page_source


def test_every_month_and_edge_days(driver, settings):
    """Dia 28 e meses extremos (jan/dez) passam pela validação de data."""
    for month, day in ((1, 1), (12, 28)):
        clear_browser_state(driver)
        base = generate_account()
        data = type(base)(**{**base.__dict__, "month": month, "day": day})
        CreateAccountFlow(driver, settings.target_url).run(data)
        assert "/conta" in driver.current_url


def test_failure_reports_the_step(driver, settings):
    """Site fora do ar: o erro precisa dizer em qual etapa quebrou."""
    clear_browser_state(driver)
    flow = CreateAccountFlow(driver, "http://127.0.0.1:9/login")
    flow.wait._timeout = 3
    with pytest.raises(AccountCreationError) as exc:
        flow.run(generate_account())
    assert exc.value.step == "abrir cadastro"
