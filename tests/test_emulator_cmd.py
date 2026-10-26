import subprocess
from pathlib import Path

import pytest

from automate_accounts.config import Settings
from automate_accounts.core import emulator as emu_mod
from automate_accounts.core.emulator import EmulatorError, EmulatorManager


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        target_url="https://x.test", avd_name="Pixel", android_home=tmp_path,
        emulator={"headless": False, "settle_seconds": 0, "boot_timeout": 30},
    )


class FakeProc:
    def __init__(self, cmd):
        self.cmd = cmd
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.returncode = -9


def capture_launch(monkeypatch, mgr):
    launched: list[FakeProc] = []
    monkeypatch.setattr(mgr, "list_avds", lambda: ["Pixel"])
    monkeypatch.setattr(mgr, "_device_online", lambda: False)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **_k: launched.append(FakeProc(cmd)) or launched[-1])
    return launched


def test_begin_builds_command_with_wipe_and_port(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    launched = capture_launch(monkeypatch, mgr)
    mgr.begin(wipe=True)
    cmd = launched[0].cmd
    assert "-wipe-data" in cmd and "-no-window" not in cmd
    assert cmd[cmd.index("-avd") + 1] == "Pixel"
    assert cmd[cmd.index("-port") + 1] == str(emu_mod.EMULATOR_PORT)


def test_begin_headless_without_wipe(settings, monkeypatch):
    settings.emulator.headless = True
    mgr = EmulatorManager(settings)
    launched = capture_launch(monkeypatch, mgr)
    mgr.begin(wipe=False)
    assert "-no-window" in launched[0].cmd and "-wipe-data" not in launched[0].cmd


def test_begin_uses_config_when_wipe_not_given(settings, monkeypatch):
    settings.emulator.wipe_data = True
    mgr = EmulatorManager(settings)
    launched = capture_launch(monkeypatch, mgr)
    mgr.begin()
    assert "-wipe-data" in launched[0].cmd


def test_begin_reuses_running_emulator(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    launched = capture_launch(monkeypatch, mgr)
    monkeypatch.setattr(mgr, "_device_online", lambda: True)
    mgr.begin(wipe=True)
    assert launched == []


def test_begin_unknown_avd(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    monkeypatch.setattr(mgr, "list_avds", lambda: ["Outro"])
    with pytest.raises(EmulatorError, match="Outro"):
        mgr.begin()


def test_wait_boot_fails_when_process_dies(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    proc = FakeProc([])
    proc.returncode = 1
    mgr._proc = proc
    with pytest.raises(EmulatorError, match="encerrou"):
        mgr.wait_boot()


def test_wait_boot_succeeds(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    monkeypatch.setattr(mgr, "_device_online", lambda: True)
    answers = {"getprop": "1", "pm": "package:/system/framework/framework-res.apk"}
    monkeypatch.setattr(mgr, "adb", lambda *a, **_k: answers["getprop" if "getprop" in a else "pm"])
    mgr.wait_boot()  # não levanta


def test_stop_waits_until_device_disappears(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    states = iter([True, True, False])   # online ao começar, ainda online, depois offline
    calls = []
    monkeypatch.setattr(mgr, "_device_online", lambda: next(states, False))
    monkeypatch.setattr(mgr, "adb", lambda *a, **_k: calls.append(a) or "")
    monkeypatch.setattr(emu_mod.time, "sleep", lambda _s: None)
    mgr.stop()
    assert ("emu", "kill") in calls


def test_chrome_major_version_parsing(settings, monkeypatch):
    mgr = EmulatorManager(settings)
    monkeypatch.setattr(mgr, "adb", lambda *a, **_k: "    versionName=124.0.6367.179\n    other=1")
    assert mgr.chrome_major_version() == "124"
    monkeypatch.setattr(mgr, "adb", lambda *a, **_k: "nada")
    assert mgr.chrome_major_version() is None
