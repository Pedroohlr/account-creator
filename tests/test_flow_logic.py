"""Lógica do fluxo (detecção de sucesso e de limite do site) com um driver falso."""
import pytest
from selenium.common.exceptions import TimeoutException

from automate_accounts.data.generator import generate_account
from automate_accounts.flows.create_account import (
    AccountCreationError,
    CreateAccountFlow,
    RateLimitError,
)


class FakeBody:
    def __init__(self, driver):
        self.driver = driver

    @property
    def text(self):
        return self.driver.body


class FakeDriver:
    def __init__(self, url="https://x.test/cadastro", body=""):
        self.current_url = url
        self.body = body

    def find_element(self, *_a):
        return FakeBody(self)

    def execute_script(self, *_a):
        return None


def flow(driver):
    f = CreateAccountFlow(driver, "https://x.test/login")
    f.wait._timeout = 0.3
    f.wait._poll = 0.05
    return f


def test_success_detected_by_url_and_welcome_title():
    flow(FakeDriver("https://x.test/conta", "auth4\nBoas-vindas, Ana")). _confirm_success()


def test_rate_limit_message_is_detected():
    with pytest.raises(RateLimitError) as exc:
        flow(FakeDriver(body="Termos\nMuitas tentativas. Aguarde alguns minutos"))._confirm_success()
    assert exc.value.step == "confirmação" and isinstance(exc.value, AccountCreationError)


def test_no_success_and_no_limit_times_out():
    with pytest.raises(TimeoutException):
        flow(FakeDriver(body="Privacidade e Termos"))._confirm_success()


def test_url_without_welcome_title_is_not_success():
    with pytest.raises(TimeoutException):
        flow(FakeDriver("https://x.test/conta", "carregando..."))._confirm_success()


def test_run_turns_timeout_into_rate_limit_when_page_says_so(monkeypatch):
    f = flow(FakeDriver(body="Muitas tentativas. Aguarde"))

    def boom():
        raise TimeoutException("sem resposta")

    monkeypatch.setattr(f, "_open_signup", boom)
    with pytest.raises(RateLimitError) as exc:
        f.run(generate_account())
    assert exc.value.step == "abrir cadastro"


def test_run_reports_step_for_ordinary_timeout(monkeypatch):
    f = flow(FakeDriver(body="tudo normal"))
    monkeypatch.setattr(f, "_open_signup", lambda: None)

    def boom(_d):
        raise TimeoutException("campo não apareceu")

    monkeypatch.setattr(f, "_name", boom)
    with pytest.raises(AccountCreationError) as exc:
        f.run(generate_account())
    assert exc.value.step == "nome" and not isinstance(exc.value, RateLimitError)
