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


def test_local_config_overrides_and_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from automate_accounts.config import save_local_settings

    (tmp_path / "config.yaml").write_text("accounts:\n  count: 3\n  per_device: 5\n", encoding="utf-8")
    monkeypatch.setenv("TARGET_URL", "https://exemplo.test/login")
    monkeypatch.setenv("AVD_NAME", "Pixel_Env")
    monkeypatch.setenv("ANDROID_HOME", str(tmp_path))

    s = load_settings(tmp_path / "config.yaml")
    assert s.accounts.per_device == 5 and s.avd_name == "Pixel_Env"

    s.accounts.per_device = 3
    s.avd_name = "Pixel_Local"
    save_local_settings(s, tmp_path / "config.local.yaml")

    again = load_settings(tmp_path / "config.yaml")
    assert again.accounts.per_device == 3 and again.avd_name == "Pixel_Local"
    assert again.accounts.count == 3


def test_allowed_domains(tmp_path: Path):
    from automate_accounts.config import Settings

    s = Settings(target_url="https://fluxo.exemplo.test/login", avd_name="a", android_home=tmp_path,
                 allowed_domains=["exemplo.test"])
    assert s.url_allowed()
    assert s.url_allowed("https://sub.exemplo.test/x")
    assert not s.url_allowed("https://outro.com/login")
    assert not s.url_allowed("https://exemplo.test.evil.com/login")   # sufixo enganoso
    s.allowed_domains = []
    assert s.url_allowed("https://qualquer.com")
