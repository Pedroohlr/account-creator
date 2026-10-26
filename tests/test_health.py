import urllib.error
from pathlib import Path

import pytest

from automate_accounts.config import Settings
from automate_accounts.core import health


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(target_url="https://x.test/login", avd_name="Pixel", android_home=tmp_path)


def test_python_ok(settings):
    assert health.check_python(settings).level == health.OK


def test_sdk_missing_then_present(settings, tmp_path):
    assert health.check_sdk(settings).level == health.FAIL
    (tmp_path / "platform-tools").mkdir()
    (tmp_path / "emulator").mkdir()
    (tmp_path / "platform-tools" / "adb.exe").write_text("")
    (tmp_path / "emulator" / "emulator.exe").write_text("")
    assert health.check_sdk(settings).level == health.OK


def test_avd_checks(settings, tmp_path, monkeypatch):
    (tmp_path / "emulator").mkdir()
    (tmp_path / "emulator" / "emulator.exe").write_text("")
    monkeypatch.setattr(health, "_run", lambda *_a, **_k: "Pixel\nTablet")
    assert health.check_avd(settings).level == health.OK
    monkeypatch.setattr(health, "_run", lambda *_a, **_k: "Tablet")
    c = health.check_avd(settings)
    assert c.level == health.FAIL and "Tablet" in c.detail


@pytest.mark.parametrize("gb,level", [(0.8, health.WARN), (4.0, health.OK), (None, health.WARN)])
def test_ram_levels(settings, monkeypatch, gb, level):
    monkeypatch.setattr(health, "free_ram_gb", lambda: gb)
    assert health.check_ram(settings).level == level


def test_site_unreachable(settings, monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.URLError("sem rede")

    monkeypatch.setattr(health.urllib.request, "urlopen", boom)
    c = health.check_site(settings)
    assert c.level == health.FAIL and "sem rede" in c.detail


def test_run_check_swallows_unexpected_errors(settings):
    def broken(_s):
        raise ValueError("boom")

    c = health.run_check("X", broken, settings)
    assert c.level == health.FAIL and "boom" in c.detail


def test_free_ram_is_number_or_none():
    gb = health.free_ram_gb()
    assert gb is None or gb > 0
