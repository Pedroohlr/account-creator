"""Ponto de entrada: python -m automate_accounts <comando>."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import ROOT, load_settings
from .core.appium_server import AppiumServer
from .core.driver import create_driver
from .core.emulator import EmulatorManager
from .logging_setup import setup_logging

log = logging.getLogger("smoke")


def smoke() -> int:
    """Sobe emulador + Appium, abre a página de login no Chrome e tira um screenshot."""
    settings = load_settings()
    emulator, appium = EmulatorManager(settings), AppiumServer(settings)
    driver = None
    try:
        emulator.start()
        appium.start()
        driver = create_driver(settings)
        driver.get(settings.target_url)
        shots = ROOT / "screenshots"
        shots.mkdir(exist_ok=True)
        shot = shots / "smoke.png"
        driver.save_screenshot(str(shot))
        log.info("OK: título=%r url=%s screenshot=%s", driver.title, driver.current_url, shot)
        print(f"OK: {driver.title!r} -> {driver.current_url}\nScreenshot: {shot}")
        return 0
    except Exception:
        log.exception("Smoke test falhou")
        return 1
    finally:
        if driver:
            driver.quit()
        appium.stop()
        emulator.stop()


def main() -> int:
    parser = argparse.ArgumentParser(prog="automate-accounts")
    parser.add_argument("command", choices=["smoke"], help="smoke: valida a infraestrutura")
    args = parser.parse_args()

    setup_logging(logging.INFO, logging.StreamHandler(sys.stderr))
    return {"smoke": smoke}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
