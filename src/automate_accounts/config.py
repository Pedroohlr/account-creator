"""Carrega configuração de config.yaml e variáveis de ambiente (.env)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


class EmulatorConfig(BaseModel):
    headless: bool = False
    boot_timeout: int = 240
    settle_seconds: int = 20
    wipe_data: bool = False


class AppiumConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4723
    startup_timeout: int = 60

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class AccountsConfig(BaseModel):
    count: int = Field(5, ge=1)
    retries: int = Field(2, ge=0)
    delay_between: float = Field(2, ge=0)


class Settings(BaseModel):
    target_url: str
    avd_name: str
    android_home: Path
    emulator: EmulatorConfig = EmulatorConfig()
    appium: AppiumConfig = AppiumConfig()
    accounts: AccountsConfig = AccountsConfig()

    @property
    def adb(self) -> Path:
        return self.android_home / "platform-tools" / "adb.exe"

    @property
    def emulator_bin(self) -> Path:
        return self.android_home / "emulator" / "emulator.exe"


def _find_android_home() -> Path:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            return Path(os.environ[var])
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "Android" / "Sdk").exists():
        return Path(local) / "Android" / "Sdk"
    raise RuntimeError("Android SDK não encontrado: defina ANDROID_HOME no .env")


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    path = config_path or ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    raw = raw or {}

    target_url = os.environ.get("TARGET_URL")
    if not target_url:
        raise RuntimeError("TARGET_URL não definida no .env")
    avd_name = os.environ.get("AVD_NAME")
    if not avd_name:
        raise RuntimeError("AVD_NAME não definida no .env")

    return Settings(
        target_url=target_url,
        avd_name=avd_name,
        android_home=_find_android_home(),
        emulator=raw.get("emulator", {}),
        appium=raw.get("appium", {}),
        accounts=raw.get("accounts", {}),
    )
