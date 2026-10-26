import json
import sys
from pathlib import Path

import pytest

from automate_accounts import __main__ as cli
from automate_accounts.config import Settings
from automate_accounts.core import appium_server as srv
from automate_accounts.core.appium_server import AppiumError, AppiumServer


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(target_url="https://x.test", avd_name="Pixel", android_home=tmp_path)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self, *_a):
        return json.dumps(self.payload).encode()


def test_appium_ready_and_not_ready(settings, monkeypatch):
    server = AppiumServer(settings)
    monkeypatch.setattr(srv.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse({"value": {"ready": True}}))
    assert server._is_ready()
    monkeypatch.setattr(srv.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse({"value": {"ready": False}}))
    assert not server._is_ready()

    def boom(*_a, **_k):
        raise OSError("recusado")

    monkeypatch.setattr(srv.urllib.request, "urlopen", boom)
    assert not server._is_ready()


def test_appium_start_reuses_running_server(settings, monkeypatch):
    server = AppiumServer(settings)
    monkeypatch.setattr(server, "_is_ready", lambda: True)
    server.start()
    assert server._proc is None


def test_appium_start_without_binary(settings, monkeypatch):
    server = AppiumServer(settings)
    monkeypatch.setattr(server, "_is_ready", lambda: False)
    monkeypatch.setattr(srv.shutil, "which", lambda _n: None)
    with pytest.raises(AppiumError, match="npm i -g appium"):
        server.start()


def test_appium_stop_is_safe_when_never_started(settings):
    AppiumServer(settings).stop()  # não levanta


def test_menu_reports_missing_config(monkeypatch, capsys):
    def no_config():
        raise RuntimeError("AVD_NAME não definida no .env")

    monkeypatch.setattr(cli, "load_settings", no_config)
    assert cli.menu() == 1
    out = capsys.readouterr().out
    assert "AVD_NAME" in out and ".env" in out


def test_default_command_is_menu(monkeypatch):
    called = []
    monkeypatch.setitem(cli.COMMANDS, "menu", lambda: called.append("menu") or 0)
    monkeypatch.setattr(sys, "argv", ["automate-accounts"])
    assert cli.main() == 0 and called == ["menu"]


def test_unknown_command_exits(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["automate-accounts", "inexistente"])
    with pytest.raises(SystemExit):
        cli.main()
