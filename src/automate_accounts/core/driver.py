"""Cria a sessão Appium com o Chrome do emulador."""
from __future__ import annotations

import logging

from appium import webdriver
from appium.options.android import UiAutomator2Options

from ..config import Settings
from .emulator import SERIAL

log = logging.getLogger(__name__)


def create_driver(settings: Settings) -> webdriver.Remote:
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.udid = SERIAL
    options.browser_name = "Chrome"
    options.new_command_timeout = 300
    options.set_capability("chromedriverAutodownload", True)
    options.set_capability("autoGrantPermissions", True)
    # Pula o onboarding do Chrome ("Aceitar e continuar", sincronizar conta)
    options.set_capability(
        "goog:chromeOptions",
        {"args": ["--no-first-run", "--disable-fre", "--no-default-browser-check"]},
    )

    log.info("Abrindo sessão Appium em %s", settings.appium.url)
    driver = webdriver.Remote(settings.appium.url, options=options)
    driver.implicitly_wait(0)  # usamos WebDriverWait explícito
    return driver


def clear_browser_state(driver: webdriver.Remote) -> None:
    """Limpa cookies e storage entre uma conta e outra."""
    driver.delete_all_cookies()
    try:
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except Exception:  # página ainda em about:blank / origem sem storage
        log.debug("Não foi possível limpar storage.", exc_info=True)
