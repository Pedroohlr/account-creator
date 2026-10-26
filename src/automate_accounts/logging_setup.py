"""Logging em arquivo (logs/app.log) e opcionalmente em handlers extras (ex.: painel)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import ROOT

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int = logging.INFO, *extra: logging.Handler) -> None:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        ),
        *extra,
    ]
    for handler in handlers:
        handler.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(handler)
