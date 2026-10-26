"""Ponto de entrada: python -m automate_accounts <comando>."""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from .config import ROOT, Settings, load_settings
from .core.appium_server import AppiumServer
from .core.driver import clear_browser_state, create_driver
from .core.emulator import EmulatorManager
from .data.generator import generate_account
from .flows.create_account import AccountCreationError, CreateAccountFlow
from .logging_setup import setup_logging

log = logging.getLogger("cli")


@contextmanager
def mobile_session(settings: Settings) -> Iterator:
    """Sobe emulador + Appium, entrega o driver do Chrome e encerra tudo no final."""
    emulator, appium = EmulatorManager(settings), AppiumServer(settings)
    driver = None
    try:
        emulator.start()
        appium.start()
        driver = create_driver(settings)
        yield driver
    finally:
        if driver:
            driver.quit()
        appium.stop()
        emulator.stop()


def screenshot(driver, name: str) -> str:
    shots = ROOT / "screenshots"
    shots.mkdir(exist_ok=True)
    path = shots / f"{name}.png"
    driver.save_screenshot(str(path))
    return str(path)


def smoke() -> int:
    """Abre a página de login no Chrome do emulador e tira um screenshot."""
    settings = load_settings()
    try:
        with mobile_session(settings) as driver:
            driver.get(settings.target_url)
            shot = screenshot(driver, "smoke")
            print(f"OK: {driver.title!r} -> {driver.current_url}\nScreenshot: {shot}")
        return 0
    except Exception:
        log.exception("Smoke test falhou")
        return 1


def create_one() -> int:
    """Cria uma única conta de teste e imprime as credenciais."""
    settings = load_settings()
    data = generate_account()
    try:
        with mobile_session(settings) as driver:
            clear_browser_state(driver)
            try:
                CreateAccountFlow(driver, settings.target_url).run(data)
            except AccountCreationError as exc:
                print(f"FALHOU: {exc}\nScreenshot: {screenshot(driver, 'erro_create_one')}")
                return 1
            print(f"Conta criada: {data.email}\nSenha: {data.password}")
            print(f"Screenshot: {screenshot(driver, 'create_one')}")
        return 0
    except Exception:
        log.exception("create-one falhou")
        return 1


COMMANDS = {"smoke": smoke, "create-one": create_one}


def main() -> int:
    parser = argparse.ArgumentParser(prog="automate-accounts")
    parser.add_argument(
        "command", choices=COMMANDS,
        help="smoke: valida a infraestrutura; create-one: cria uma conta de teste",
    )
    args = parser.parse_args()

    setup_logging(logging.INFO, logging.StreamHandler(sys.stderr))
    return COMMANDS[args.command]()


if __name__ == "__main__":
    sys.exit(main())
