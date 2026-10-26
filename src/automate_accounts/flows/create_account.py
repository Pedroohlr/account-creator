"""Fluxo de criação de conta (wizard em /cadastro). Ver docs/fluxo-cadastro.md."""
from __future__ import annotations

import logging
import time

from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from ..data.generator import AccountData

log = logging.getLogger(__name__)

STEP_TIMEOUT = 20
SUCCESS_TEXT = "Sua conta foi criada"


class AccountCreationError(RuntimeError):
    def __init__(self, step: str, cause: Exception | str) -> None:
        super().__init__(f"Falha na etapa '{step}': {cause}")
        self.step = step


SUBMIT = (By.CSS_SELECTOR, "button[type=submit]")


def _button(label: str) -> tuple[str, str]:
    return By.XPATH, f"//button[normalize-space()='{label}']"


class CreateAccountFlow:
    def __init__(self, driver: WebDriver, login_url: str) -> None:
        self.driver = driver
        self.login_url = login_url
        self.wait = WebDriverWait(driver, STEP_TIMEOUT)


    MONTH = (By.CSS_SELECTOR, "select[name=month]")
    CHOICE = (By.CSS_SELECTOR, "input[name=choice]")
    PASSWORD = (By.CSS_SELECTOR, "input[name=password]")
    PHONE = (By.CSS_SELECTOR, "input[name=phone]")
    RECOVERY = (By.CSS_SELECTOR, "input[name=recoveryEmail]")
    REVIEW = (By.XPATH, "//*[contains(., 'Revise as informações')]")

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

    def _select(self, name: str, value: str) -> None:
        """Escolhe a opção pelo value via JS: Select do Selenium falha no Chrome mobile."""
        el = self._visible((By.CSS_SELECTOR, f"select[name={name}]"))
        self.driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            el, value,
        )

    def _next(self, expect: tuple[str, str], button: tuple[str, str] = SUBMIT,
              attempts: int = 3) -> None:
        """Clica no botão e confirma que a etapa seguinte apareceu; repete o clique se não."""
        self.driver.execute_script("document.activeElement && document.activeElement.blur();")
        for attempt in range(1, attempts + 1):
            self._click(button)
            try:
                WebDriverWait(self.driver, 8).until(EC.visibility_of_element_located(expect))
                return
            except TimeoutException:
                if attempt == attempts:
                    raise
                log.warning("Etapa não avançou (tentativa %d/%d); clicando de novo.",
                            attempt, attempts)

    # -- etapas ------------------------------------------------------------
    def _open_signup(self) -> None:
        self.driver.get(self.login_url)
        self._click(_button("Criar conta"))

    def _name(self, d: AccountData) -> None:
        self._type("firstName", d.first_name)
        self._type("lastName", d.last_name)
        self._next(self.MONTH)

    def _birthday(self, d: AccountData) -> None:
        self._type("day", str(d.day))
        self._select("month", str(d.month))
        self._type("year", str(d.year))
        self._select("gender", d.gender)
        self._next(self.CHOICE)

    def _address(self, d: AccountData) -> None:
        radios = self.wait.until(
            lambda drv: drv.find_elements(By.CSS_SELECTOR, "input[name=choice]")
            if len(drv.find_elements(By.CSS_SELECTOR, "input[name=choice]")) == 3
            else False
        )
        self.driver.execute_script("arguments[0].click();", radios[2])  # "Criar seu próprio"
        self._type("username", d.username)
        self._next(self.PASSWORD)

    def _password(self, d: AccountData) -> None:
        self._type("password", d.password)
        self._type("confirm", d.password)
        self._next(self.PHONE)

    def _skip(self, current: tuple[str, str], expect: tuple[str, str]) -> None:
        self._visible(current)
        self._next(expect, button=_button("Pular"))

    def _review_and_accept(self) -> None:
        self._visible(_button("Próxima"))
        self._next(_button("Concordo"))
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
            ("telefone", lambda: self._skip(self.PHONE, self.RECOVERY)),
            ("e-mail de recuperação", lambda: self._skip(self.RECOVERY, self.REVIEW)),
            ("revisão e termos", self._review_and_accept),
            ("confirmação", self._confirm_success),
        ]
        started = time.monotonic()
        for name, action in steps:
            t0 = time.monotonic()
            try:
                action()
            except (TimeoutException, WebDriverException) as exc:
                raise AccountCreationError(name, str(exc).splitlines()[0]) from exc
            log.info("etapa '%s': %.1fs", name, time.monotonic() - t0)
        log.info("Conta criada: %s (%.1fs)", data.email, time.monotonic() - started)
