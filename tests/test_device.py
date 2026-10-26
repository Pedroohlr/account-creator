from pathlib import Path

from automate_accounts.config import Settings
from automate_accounts.core.device import DeviceManager
from automate_accounts.core.useragent import PROFILES, random_user_agent


class FakeEmu:
    def __init__(self): self.calls = []
    def begin(self): self.calls.append("begin")
    def wait_boot(self): self.calls.append("wait_boot")
    def stop(self): self.calls.append("stop")
    def start(self, wipe=None): self.calls.append(f"start(wipe={wipe})")
    def chrome_major_version(self): return "140"


class FakeAppium:
    def __init__(self, calls): self.calls = calls
    def start(self): self.calls.append("appium.start")
    def stop(self): self.calls.append("appium.stop")


class FakeDriver:
    def __init__(self, ua): self.ua = ua; self.quit_called = False
    def quit(self): self.quit_called = True


def make(tmp_path: Path, **accounts):
    s = Settings(target_url="https://x.test", avd_name="a", android_home=tmp_path, accounts=accounts)
    emu = FakeEmu()
    created: list[FakeDriver] = []

    def factory(_s, ua=None):
        d = FakeDriver(ua); created.append(d); return d

    return DeviceManager(s, emulator=emu, appium=FakeAppium(emu.calls), driver_factory=factory), emu, created


def test_open_starts_appium_while_emulator_boots(tmp_path):
    dev, emu, created = make(tmp_path)
    dev.open()
    assert emu.calls == ["begin", "appium.start", "wait_boot"]
    assert dev.number == 1 and len(created) == 1


def test_rotate_restarts_emulator_with_wipe_and_keeps_appium(tmp_path):
    dev, emu, created = make(tmp_path, wipe_on_rotate=True)
    dev.open()
    emu.calls.clear()
    dev.rotate()
    assert emu.calls == ["stop", "start(wipe=True)"]   # sem appium.stop/start
    assert created[0].quit_called and dev.number == 2 and len(created) == 2


def test_rotate_without_wipe(tmp_path):
    dev, emu, _ = make(tmp_path, wipe_on_rotate=False)
    dev.open(); emu.calls.clear(); dev.rotate()
    assert "start(wipe=False)" in emu.calls


def test_random_user_agent_per_device(tmp_path):
    dev, _, created = make(tmp_path, random_user_agent=True)
    dev.open(); dev.rotate()
    assert all("Chrome/140.0.0.0" in d.ua for d in created)


def test_no_user_agent_by_default(tmp_path):
    dev, _, created = make(tmp_path)
    dev.open()
    assert created[0].ua is None


def test_close_stops_everything(tmp_path):
    dev, emu, created = make(tmp_path)
    dev.open(); emu.calls.clear(); dev.close()
    assert emu.calls == ["appium.stop", "stop"] and created[0].quit_called


def test_user_agent_format():
    ua = random_user_agent("131")
    assert ua.startswith("Mozilla/5.0 (Linux; Android ") and "Chrome/131.0.0.0 Mobile" in ua
    assert any(model in ua for model, _ in PROFILES)
