import subprocess
from pathlib import Path

import pytest

from automate_accounts.config import Settings
from automate_accounts.core.emulator import EmulatorError, EmulatorManager


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(target_url="https://x.test", avd_name="Pixel", android_home=tmp_path)


def fake_run(stdout: str):
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return _run


def test_list_avds(settings, monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run("Pixel\nTablet\n"))
    assert EmulatorManager(settings).list_avds() == ["Pixel", "Tablet"]


def test_device_online(settings, monkeypatch):
    out = "List of devices attached\nemulator-5554\tdevice\n"
    monkeypatch.setattr(subprocess, "run", fake_run(out))
    assert EmulatorManager(settings).is_running()


def test_device_offline(settings, monkeypatch):
    out = "List of devices attached\nemulator-5554\toffline\n"
    monkeypatch.setattr(subprocess, "run", fake_run(out))
    assert not EmulatorManager(settings).is_running()


def test_start_unknown_avd(settings, monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run("Outro\n"))
    with pytest.raises(EmulatorError):
        EmulatorManager(settings).start()
