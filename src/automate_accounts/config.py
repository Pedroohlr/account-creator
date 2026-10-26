"""Carrega configuração: config.yaml < config.local.yaml (painel) e variáveis de ambiente (.env)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
LOCAL_CONFIG = ROOT / "config.local.yaml"


class EmulatorConfig(BaseModel):
    headless: bool = False
    boot_timeout: int = Field(240, ge=30)
    settle_seconds: int = Field(20, ge=0)
    wipe_data: bool = False


class AppiumConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(4723, ge=1, le=65535)
    startup_timeout: int = Field(60, ge=5)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


class AccountsConfig(BaseModel):
    count: int = Field(5, ge=1)
    retries: int = Field(2, ge=0)
    delay_between: float = Field(2, ge=0)
    per_device: int = Field(5, ge=1)          # contas por dispositivo antes da troca
    wipe_on_rotate: bool = True               # troca = reinício com -wipe-data
    random_user_agent: bool = False           # User-Agent diferente a cada dispositivo


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

    def editable(self) -> dict[str, Any]:
        """Parte da configuração que o painel de Configurações grava em config.local.yaml."""
        return {
            "target_url": self.target_url,
            "avd_name": self.avd_name,
            "emulator": self.emulator.model_dump(),
            "appium": self.appium.model_dump(),
            "accounts": self.accounts.model_dump(),
        }


def _find_android_home() -> Path:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            return Path(os.environ[var])
    local = os.environ.get("LOCALAPPDATA")
    if local and (Path(local) / "Android" / "Sdk").exists():
        return Path(local) / "Android" / "Sdk"
    raise RuntimeError("Android SDK não encontrado: defina ANDROID_HOME no .env")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings(config_path: Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    path = config_path or ROOT / "config.yaml"
    local = LOCAL_CONFIG if config_path is None else path.with_name("config.local.yaml")
    raw = _merge(_read_yaml(path), _read_yaml(local))

    target_url = raw.get("target_url") or os.environ.get("TARGET_URL")
    if not target_url:
        raise RuntimeError("TARGET_URL não definida no .env")
    avd_name = raw.get("avd_name") or os.environ.get("AVD_NAME")
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


def save_local_settings(settings: Settings, path: Path = LOCAL_CONFIG) -> None:
    """Grava as configurações editadas no painel (não altera o config.yaml do repositório)."""
    path.write_text(
        "# Gerado pelo painel (Configurações). Sobrescreve o config.yaml.\n"
        + yaml.safe_dump(settings.editable(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
