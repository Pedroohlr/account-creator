"""Gerencia o processo do servidor Appium."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import urllib.error
import urllib.request

from ..config import ROOT, Settings

log = logging.getLogger(__name__)


class AppiumError(RuntimeError):
    pass


class AppiumServer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._proc: subprocess.Popen | None = None
        self._log_file = None

    def _is_ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.settings.appium.url}/status", timeout=2) as r:
                return bool(json.load(r).get("value", {}).get("ready", False))
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def start(self) -> None:
        if self._is_ready():
            log.info("Appium já está rodando em %s; reutilizando.", self.settings.appium.url)
            return
        exe = shutil.which("appium")
        if not exe:
            raise AppiumError("Comando 'appium' não encontrado. Instale com: npm i -g appium")

        cfg = self.settings.appium
        cmd = [
            exe, "--address", cfg.host, "--port", str(cfg.port),
            "--allow-insecure", "uiautomator2:chromedriver_autodownload",
        ]
        (ROOT / "logs").mkdir(exist_ok=True)
        self._log_file = open(ROOT / "logs" / "appium.log", "ab")
        log.info("Iniciando Appium: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=self._log_file, stderr=subprocess.STDOUT)

        deadline = time.monotonic() + cfg.startup_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise AppiumError("Appium encerrou ao iniciar; veja logs/appium.log")
            if self._is_ready():
                log.info("Appium pronto.")
                return
            time.sleep(1)
        self.stop()
        raise AppiumError(f"Timeout de {cfg.startup_timeout}s esperando o Appium.")

    def stop(self) -> None:
        if self._proc:
            log.info("Encerrando Appium.")
            # appium é um .cmd no Windows: taskkill /T derruba a árvore inteira
            subprocess.run(
                ["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                capture_output=True, check=False,
            )
            self._proc = None
        if self._log_file:
            self._log_file.close()
            self._log_file = None
