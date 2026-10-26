"""Estimativa de tempo de uma execução (valores padrão medidos no emulador do projeto)."""
from __future__ import annotations

import math

DEFAULT_ACCOUNT_SECONDS = 140.0   # criar uma conta (média medida)
DEVICE_SETUP_SECONDS = 230.0      # ligar o dispositivo: boot + Appium/sessão + desligar
WIPE_EXTRA_SECONDS = 40.0         # boot com -wipe-data é mais lento


def devices_needed(count: int, per_device: int) -> int:
    return max(1, math.ceil(count / max(1, per_device)))


def estimate_seconds(
    count: int, per_device: int, wipe: bool = True,
    account_seconds: float | None = None,
) -> float:
    """Total = (dispositivos × custo de ligar) + (contas × tempo por conta)."""
    per_account = account_seconds or DEFAULT_ACCOUNT_SECONDS
    devices = devices_needed(count, per_device)
    rotations = devices - 1
    setup = DEVICE_SETUP_SECONDS * devices + (WIPE_EXTRA_SECONDS * rotations if wipe else 0)
    return setup + count * per_account


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = round(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}min"
    if minutes:
        return f"{minutes}min{secs:02d}s"
    return f"{secs}s"
