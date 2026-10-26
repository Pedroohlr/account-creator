import threading
from pathlib import Path

import pytest

from automate_accounts.config import Settings
from automate_accounts.core import orchestrator as orch
from automate_accounts.core.orchestrator import Orchestrator
from automate_accounts.data.generator import generate_account
from automate_accounts.data.repository import AccountRepository
from automate_accounts.flows.create_account import AccountCreationError


class FakeDriver:
    def delete_all_cookies(self): ...
    def execute_script(self, *_a): ...
    def save_screenshot(self, _p): ...


class FakeDevice:
    instances: list = []

    def __init__(self, _settings, fail_rotate=False):
        self.number = 0
        self.log: list[str] = []
        self.fail_rotate = fail_rotate
        FakeDevice.instances.append(self)

    def open(self):
        self.number = 1
        self.log.append("open")
        return FakeDriver()

    def rotate(self):
        if self.fail_rotate:
            raise RuntimeError("emulador não subiu")
        self.number += 1
        self.log.append("rotate")
        return FakeDriver()

    def close(self):
        self.log.append("close")


def make(tmp_path: Path, flow, per_device=5, stop=None, device_cls=FakeDevice):
    FakeDevice.instances = []
    settings = Settings(
        target_url="https://x.test/login", avd_name="a", android_home=tmp_path,
        accounts={"retries": 1, "delay_between": 0, "per_device": per_device},
    )
    repo = AccountRepository(tmp_path / "t.db")
    events: list = []
    o = Orchestrator(
        settings, repo, on_event=lambda kind, **d: events.append((kind, d)), stop=stop,
        device_factory=device_cls, flow_factory=flow, generator=generate_account,
    )
    return o, repo, events


@pytest.fixture(autouse=True)
def no_screenshots(monkeypatch):
    monkeypatch.setattr(orch.Orchestrator, "_save_error_screenshot", lambda *_: None)


class Ok:
    def __init__(self, *_): ...
    def run(self, _d): ...


class AlwaysFail:
    def __init__(self, *_): ...
    def run(self, _d):
        raise AccountCreationError("senha", "timeout")


def test_all_succeed(tmp_path):
    o, repo, events = make(tmp_path, Ok)
    result = o.run(3)
    assert (result.created, result.failed, result.devices) == (3, 0, 1)
    assert repo.counts() == {"criada": 3, "falhou": 0}
    assert [d["done"] for k, d in events if k == "progress"] == [1, 2, 3]
    assert repo.list_recent()[0].duration is not None


def test_rotates_device_every_n_accounts(tmp_path):
    o, repo, events = make(tmp_path, Ok, per_device=5)
    result = o.run(12)
    device = FakeDevice.instances[0]
    assert device.log == ["open", "rotate", "rotate", "close"]
    assert result.devices == 3 and result.created == 12
    assert [d["number"] for k, d in events if k == "device"] == [1, 2, 3]
    assert [d["total"] for k, d in events if k == "device"] == [3, 3, 3]
    by_device = {}
    for r in repo.list_recent(50):
        by_device[r.device] = by_device.get(r.device, 0) + 1
    assert by_device == {1: 5, 2: 5, 3: 2}


def test_no_rotation_when_count_fits_one_device(tmp_path):
    o, _, _ = make(tmp_path, Ok, per_device=5)
    o.run(5)
    assert FakeDevice.instances[0].log == ["open", "close"]


def test_retry_then_success_and_final_failure(tmp_path):
    calls = {"n": 0}

    class Flaky:
        def __init__(self, *_): ...
        def run(self, _d):
            calls["n"] += 1
            # conta 1: falha na 1a tentativa e passa na 2a; conta 2: falha sempre
            if calls["n"] == 1 or calls["n"] >= 3:
                raise AccountCreationError("senha", "timeout")

    o, repo, _ = make(tmp_path, Flaky)
    result = o.run(2)
    assert (result.created, result.failed) == (1, 1)
    failed = [r for r in repo.list_recent() if r.status == "falhou"][0]
    assert "senha" in failed.error


def test_stop_between_accounts_still_closes_device(tmp_path):
    stop = threading.Event()

    class StopAfterFirst:
        def __init__(self, *_): ...
        def run(self, _d):
            stop.set()

    o, _, _ = make(tmp_path, StopAfterFirst, stop=stop)
    result = o.run(5)
    assert result.created == 1 and result.stopped
    assert FakeDevice.instances[0].log[-1] == "close"


def test_emergency_rotation_then_abort(tmp_path):
    o, _, _ = make(tmp_path, AlwaysFail, per_device=50)
    result = o.run(20)
    # 3 falhas → troca de emergência → mais 3 falhas → segunda troca recusada: aborta
    assert result.failed == 6 and result.error
    assert FakeDevice.instances[0].log == ["open", "rotate", "close"]


def test_rotate_failure_aborts_batch_and_closes(tmp_path):
    class BadRotate(FakeDevice):
        def __init__(self, s):
            super().__init__(s, fail_rotate=True)

    o, _, _ = make(tmp_path, Ok, per_device=2, device_cls=BadRotate)
    result = o.run(6)
    assert result.created == 2 and "Troca de dispositivo falhou" in result.error
    assert FakeDevice.instances[0].log[-1] == "close"
