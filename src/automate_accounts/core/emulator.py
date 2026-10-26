"""Ciclo de vida do AVD do Android Studio (emulator + adb)."""
from __future__ import annotations

import logging
import re
import subprocess
import time

from ..config import Settings

log = logging.getLogger(__name__)

EMULATOR_PORT = 5554
SERIAL = f"emulator-{EMULATOR_PORT}"


class EmulatorError(RuntimeError):
    pass


class EmulatorManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._proc: subprocess.Popen | None = None

    # -- adb helpers -------------------------------------------------------
    def adb(self, *args: str, timeout: float = 30) -> str:
        cmd = [str(self.settings.adb), "-s", SERIAL, *args]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return result.stdout.strip()

    def _device_online(self) -> bool:
        result = subprocess.run(
            [str(self.settings.adb), "devices"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        return any(
            line.startswith(SERIAL) and line.split()[-1] == "device"
            for line in result.stdout.splitlines()
        )

    # -- API pública -------------------------------------------------------
    def list_avds(self) -> list[str]:
        result = subprocess.run(
            [str(self.settings.emulator_bin), "-list-avds"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def is_running(self) -> bool:
        return self._device_online()

    def chrome_major_version(self) -> str | None:
        """Versão principal do Chrome instalado no emulador (ex.: '131'), se detectável."""
        out = self.adb("shell", "dumpsys", "package", "com.android.chrome", timeout=20)
        match = re.search(r"versionName=(\d+)\.", out)
        return match.group(1) if match else None

    def begin(self, wipe: bool | None = None) -> None:
        """Dispara o boot do emulador sem esperar (permite subir o Appium em paralelo)."""
        avd = self.settings.avd_name
        avds = self.list_avds()
        if avd not in avds:
            raise EmulatorError(f"AVD '{avd}' não existe. Disponíveis: {avds or 'nenhum'}")
        if self._device_online():
            log.info("Emulador já está rodando (%s); reutilizando.", SERIAL)
            return
        cfg = self.settings.emulator
        cmd = [str(self.settings.emulator_bin), "-avd", avd, "-port", str(EMULATOR_PORT),
               "-no-snapshot-save", "-no-boot-anim"]
        if cfg.headless:
            cmd.append("-no-window")
        if cfg.wipe_data if wipe is None else wipe:
            cmd.append("-wipe-data")
        log.info("Iniciando emulador: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start(self, wipe: bool | None = None) -> None:
        self.begin(wipe)
        self.wait_boot()

    def wait_boot(self) -> None:
        deadline = time.monotonic() + self.settings.emulator.boot_timeout
        while time.monotonic() < deadline:
            if self._proc and self._proc.poll() is not None:
                raise EmulatorError(f"Emulador encerrou (código {self._proc.returncode}).")
            if self._device_online() and self.adb("shell", "getprop", "sys.boot_completed") == "1":
                self._settle()
                log.info("Emulador pronto.")
                return
            time.sleep(3)
        raise EmulatorError(
            f"Timeout de {self.settings.emulator.boot_timeout}s esperando o boot do emulador."
        )

    def _settle(self) -> None:
        """Logo após o boot o sistema ainda carrega apps; espera o package manager e uma folga."""
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.adb("shell", "pm", "path", "android").startswith("package:"):
                break
            time.sleep(2)
        time.sleep(self.settings.emulator.settle_seconds)

    def stop(self) -> None:
        if not self._device_online() and not self._proc:
            return
        log.info("Encerrando emulador.")
        try:
            self.adb("emu", "kill", timeout=15)
        except subprocess.TimeoutExpired:
            pass
        if self._proc:
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        # a porta só fica livre para o próximo boot depois que o device some do adb
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and self._device_online():
            time.sleep(1)
