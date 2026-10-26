"""Sessão mobile completa: emulador + Appium + driver do Chrome."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ..config import Settings
from .appium_server import AppiumServer
from .driver import create_driver
from .emulator import EmulatorManager


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
