import threading
from contextlib import contextmanager
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


@contextmanager
def fake_session(_settings):
    yield FakeDriver()


def make(tmp_path: Path, flow, stop=None):
    settings = Settings(
        target_url="https://x.test/login", avd_name="a", android_home=tmp_path,
        accounts={"count": 3, "retries": 1, "delay_between": 0},
    )
    repo = AccountRepository(tmp_path / "t.db")
    events: list = []
    o = Orchestrator(
        settings, repo, on_event=lambda kind, **d: events.append((kind, d)), stop=stop,
        session_factory=fake_session, flow_factory=flow, generator=generate_account,
    )
    return o, repo, events


@pytest.fixture(autouse=True)
def no_screenshots(monkeypatch):
    monkeypatch.setattr(orch.Orchestrator, "_save_error_screenshot", lambda *_: None)


def test_all_succeed(tmp_path):
    class Ok:
        def __init__(self, *_): ...
        def run(self, _d): ...

    o, repo, events = make(tmp_path, Ok)
    result = o.run(3)
    assert (result.created, result.failed) == (3, 0)
    assert repo.counts() == {"criada": 3, "falhou": 0}
    assert [d["done"] for k, d in events if k == "progress"] == [1, 2, 3]


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


def test_stop_between_accounts(tmp_path):
    stop = threading.Event()

    class StopAfterFirst:
        def __init__(self, *_): ...
        def run(self, _d):
            stop.set()

    o, repo, _ = make(tmp_path, StopAfterFirst, stop=stop)
    result = o.run(5)
    assert result.created == 1 and result.stopped
