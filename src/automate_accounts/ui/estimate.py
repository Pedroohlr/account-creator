"""Estimativa de tempo de uma execução (valores padrão medidos no emulador do projeto)."""
from __future__ import annotations

import math

# Medidos no emulador do projeto (Pixel 4 API 35, com RAM livre):
DEFAULT_ACCOUNT_SECONDS = 45.0    # criar uma conta (mediana de 25 a 110 s, conforme a RAM livre)
FIRST_DEVICE_SECONDS = 105.0      # boot (~64 s) + Appium em paralelo + abrir a sessão
ROTATE_WIPE_SECONDS = 220.0       # desligar + boot com -wipe-data (~136 s) + sessão e 1º uso do Chrome
ROTATE_NOWIPE_SECONDS = 110.0     # desligar + boot normal + sessão


def devices_needed(count: int, per_device: int) -> int:
    return max(1, math.ceil(count / max(1, per_device)))


def estimate_seconds(
    count: int, per_device: int, wipe: bool = True,
    account_seconds: float | None = None,
) -> float:
    """Total = ligar o 1º dispositivo + trocas + (contas × tempo por conta)."""
    per_account = account_seconds or DEFAULT_ACCOUNT_SECONDS
    rotations = devices_needed(count, per_device) - 1
    rotate = ROTATE_WIPE_SECONDS if wipe else ROTATE_NOWIPE_SECONDS
    return FIRST_DEVICE_SECONDS + rotations * rotate + count * per_account


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
