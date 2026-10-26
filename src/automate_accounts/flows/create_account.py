"""Fluxo de criação de conta (wizard em /cadastro). Ver docs/fluxo-cadastro.md."""
from __future__ import annotations

import logging

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from ..data.generator import AccountData

log = logging.getLogger(__name__)

STEP_TIMEOUT = 20
SUCCESS_TEXT = "Sua conta foi criada"


class AccountCreationError(RuntimeError):
    def __init__(self, step: str, cause: Exception | str) -> None:
        super().__init__(f"Falha na etapa '{step}': {cause}")
        self.step = step


def _button(label: str) -> tuple[str, str]:
    return By.XPATH, f"//button[normalize-space()='{label}']"


class CreateAccountFlow:
    def __init__(self, driver: WebDriver, login_url: str) -> None:
        self.driver = driver
        self.login_url = login_url
        self.wait = WebDriverWait(driver, STEP_TIMEOUT)

    # -- helpers -----------------------------------------------------------
    def _visible(self, locator: tuple[str, str]) -> WebElement:
        return self.wait.until(EC.visibility_of_element_located(locator))

    def _click(self, locator: tuple[str, str]) -> None:
        el = self.wait.until(EC.presence_of_element_located(locator))
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        try:
            self.wait.until(EC.element_to_be_clickable(locator)).click()
        except (ElementClickInterceptedException, TimeoutException):
            # teclado virtual ou elemento sobreposto: clique direto via JS
            self.driver.execute_script("arguments[0].click();", el)

    def _type(self, name: str, value: str) -> None:
        el = self._visible((By.CSS_SELECTOR, f"input[name={name}]"))
        el.clear()
        el.send_keys(value)

    def _next(self) -> None:
        self._click((By.CSS_SELECTOR, "button[type=submit]"))

    # -- etapas ------------------------------------------------------------
    def _open_signup(self) -> None:
        self.driver.get(self.login_url)
        self._click(_button("Criar conta"))

    def _name(self, d: AccountData) -> None:
        self._type("firstName", d.first_name)
        self._type("lastName", d.last_name)
        self._next()

    def _birthday(self, d: AccountData) -> None:
        self._type("day", str(d.day))
        Select(self._visible((By.CSS_SELECTOR, "select[name=month]"))).select_by_index(d.month - 1)
        self._type("year", str(d.year))
        Select(self._visible((By.CSS_SELECTOR, "select[name=gender]"))).select_by_index(
            d.gender_index
        )
        self._next()

    def _address(self, d: AccountData) -> None:
        radios = self.wait.until(
            lambda drv: drv.find_elements(By.CSS_SELECTOR, "input[name=choice]")
            if len(drv.find_elements(By.CSS_SELECTOR, "input[name=choice]")) == 3
            else False
        )
        self.driver.execute_script("arguments[0].click();", radios[2])  # "Criar seu próprio"
        self._type("username", d.username)
        self._next()

    def _password(self, d: AccountData) -> None:
        self._type("password", d.password)
        self._type("confirm", d.password)
        self._next()

    def _skip(self, label_field: str) -> None:
        self._visible((By.CSS_SELECTOR, f"input[name={label_field}]"))
        self._click(_button("Pular"))

    def _review_and_accept(self) -> None:
        self._visible(_button("Próxima"))
        self._visible((By.XPATH, "//*[contains(., 'Revise as informações')]"))
        self._next()
        self._click(_button("Concordo"))

    def _confirm_success(self) -> None:
        self.wait.until(EC.url_contains("/conta"))
        self.wait.until(EC.text_to_be_present_in_element((By.TAG_NAME, "body"), SUCCESS_TEXT))

    # -- execução ----------------------------------------------------------
    def run(self, data: AccountData) -> None:
        steps = [
            ("abrir cadastro", self._open_signup),
            ("nome", lambda: self._name(data)),
            ("data de nascimento", lambda: self._birthday(data)),
            ("endereço", lambda: self._address(data)),
            ("senha", lambda: self._password(data)),
            ("telefone", lambda: self._skip("phone")),
            ("e-mail de recuperação", lambda: self._skip("recoveryEmail")),
            ("revisão e termos", self._review_and_accept),
            ("confirmação", self._confirm_success),
        ]
        for name, action in steps:
            log.debug("Etapa: %s", name)
            try:
                action()
            except (TimeoutException, WebDriverException) as exc:
                raise AccountCreationError(name, str(exc).splitlines()[0]) from exc
        log.info("Conta criada: %s", data.email)
