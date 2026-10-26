"""Um 'dispositivo' = emulador + sessão do Chrome. O Appium fica ligado entre as trocas."""
from __future__ import annotations

import logging

from ..config import Settings
from .appium_server import AppiumServer
from .driver import create_driver
from .emulator import EmulatorManager
from .useragent import random_user_agent

log = logging.getLogger(__name__)


class DeviceManager:
    def __init__(
        self,
        settings: Settings,
        emulator: EmulatorManager | None = None,
        appium: AppiumServer | None = None,
        driver_factory=create_driver,
    ) -> None:
        self.settings = settings
        self.emulator = emulator or EmulatorManager(settings)
        self.appium = appium or AppiumServer(settings)
        self.driver_factory = driver_factory
        self.driver = None
        self.number = 0  # 1 = primeiro dispositivo

    def _new_driver(self):
        user_agent = None
        if self.settings.accounts.random_user_agent:
            user_agent = random_user_agent(self.emulator.chrome_major_version())
            log.info("User-Agent deste dispositivo: %s", user_agent)
        return self.driver_factory(self.settings, user_agent)

    def open(self):
        """Liga emulador e Appium em paralelo (o boot demora) e abre o Chrome."""
        if not self.settings.url_allowed():
            raise PermissionError(
                f"Domínio fora de allowed_domains ({', '.join(self.settings.allowed_domains)}): "
                f"{self.settings.target_url}"
            )
        self.emulator.begin()
        self.appium.start()
        self.emulator.wait_boot()
        self.number = 1
        self.driver = self._new_driver()
        return self.driver

    def rotate(self):
        """Troca de dispositivo: fecha o Chrome, reinicia o emulador (com wipe) e reabre."""
        log.info("Trocando de dispositivo (%d → %d).", self.number, self.number + 1)
        self._quit_driver()
        self.emulator.stop()
        self.emulator.start(wipe=self.settings.accounts.wipe_on_rotate)
        self.number += 1
        self.driver = self._new_driver()
        return self.driver

    def _quit_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                log.debug("driver.quit() falhou (sessão já encerrada).", exc_info=True)
            self.driver = None

    def close(self) -> None:
        self._quit_driver()
        self.appium.stop()
        self.emulator.stop()
