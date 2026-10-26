from pathlib import Path

import pytest

from automate_accounts.config import load_settings


def test_load_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("accounts:\n  count: 3\nappium:\n  port: 4800\n", encoding="utf-8")
    monkeypatch.setenv("TARGET_URL", "https://exemplo.test/login")
    monkeypatch.setenv("AVD_NAME", "Pixel_Test")
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))

    s = load_settings(cfg)

    assert s.accounts.count == 3
    assert s.appium.url == "http://127.0.0.1:4800"
    assert s.adb == tmp_path / "platform-tools" / "adb.exe"


def test_missing_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TARGET_URL", raising=False)
    monkeypatch.setattr("automate_accounts.config.load_dotenv", lambda *_: None)
    with pytest.raises(RuntimeError):
        load_settings(tmp_path / "nao_existe.yaml")
