"""Sessão mobile de um dispositivo só (usada por smoke e create-one)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from ..config import Settings
from .device import DeviceManager


@contextmanager
def mobile_session(settings: Settings) -> Iterator:
    """Sobe emulador + Appium, entrega o driver do Chrome e encerra tudo no final."""
    device = DeviceManager(settings)
    try:
        yield device.open()
    finally:
        device.close()
