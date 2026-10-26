"""Cria a sessão Appium com o Chrome do emulador."""
from __future__ import annotations

import logging
import time

from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import WebDriverException

from ..config import Settings
from .emulator import SERIAL

log = logging.getLogger(__name__)


PROXY_HOST_FROM_EMULATOR = "10.0.2.2"   # o PC visto de dentro do emulador


def create_driver(
    settings: Settings, user_agent: str | None = None, attempts: int = 3,
    proxy_port: int | None = None,
) -> webdriver.Remote:
    options = UiAutomator2Options()
    options.platform_name = "Android"
    options.udid = SERIAL
    options.browser_name = "Chrome"
    options.new_command_timeout = 300
    options.set_capability("chromedriverAutodownload", True)
    options.set_capability("autoGrantPermissions", True)
    # Pula o onboarding do Chrome ("Aceitar e continuar", sincronizar conta)
    chrome_args = ["--no-first-run", "--disable-fre", "--no-default-browser-check"]
    if user_agent:
        chrome_args.append(f"--user-agent={user_agent}")
    if proxy_port:   # proxy local do PC: autentica e troca de IP (core/proxy.py)
        chrome_args.append(f"--proxy-server=http://{PROXY_HOST_FROM_EMULATOR}:{proxy_port}")
    options.set_capability("goog:chromeOptions", {"args": chrome_args})

    options.set_capability("adbExecTimeout", 60000)
    options.set_capability("uiautomator2ServerLaunchTimeout", 90000)
    options.set_capability("uiautomator2ServerInstallTimeout", 90000)

    log.info("Abrindo sessão Appium em %s", settings.appium.url)
    for attempt in range(1, attempts + 1):
        try:
            driver = webdriver.Remote(settings.appium.url, options=options)
            break
        except WebDriverException as exc:
            # Primeira sessão após o boot costuma falhar enquanto o sistema ainda assenta
            if attempt == attempts:
                raise
            log.warning("Sessão falhou (tentativa %d/%d): %s", attempt, attempts,
                        str(exc).splitlines()[0])
            time.sleep(10)
    driver.implicitly_wait(0)  # usamos WebDriverWait explícito
    return driver


def clear_browser_state(driver: webdriver.Remote) -> None:
    """Limpa cookies e storage entre uma conta e outra."""
    driver.delete_all_cookies()
    try:
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except Exception:  # página ainda em about:blank / origem sem storage
        log.debug("Não foi possível limpar storage.", exc_info=True)
