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
    failed = next(r for r in repo.list_recent() if r.status == "falhou")
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


def test_rate_limit_waits_without_spending_attempts_then_succeeds(tmp_path, monkeypatch):
    from automate_accounts.flows.create_account import RateLimitError

    waits = []
    monkeypatch.setattr(orch.Orchestrator, "_sleep", lambda self, s: waits.append(s))
    calls = {"n": 0}

    class LimitedTwice:
        def __init__(self, *_): ...
        def run(self, _d):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise RateLimitError("confirmação", "limite")

    o, repo, events = make(tmp_path, LimitedTwice)
    o.settings.accounts.retries = 0          # sem retries comuns: só as esperas do limite
    o.settings.accounts.rate_limit_wait = 10
    result = o.run(1)
    assert (result.created, result.failed, result.error) == (1, 0, None)
    assert calls["n"] == 3
    cooldowns = [d for k, d in events if k == "cooldown"]
    assert cooldowns[0]["seconds"] == 10 and cooldowns[0]["wait"] == 1
    assert cooldowns[-1]["wait"] == 2 and len(waits) == 20   # 2 esperas × 10 s


def test_rate_limit_persisting_aborts_batch_with_clear_message(tmp_path, monkeypatch):
    from automate_accounts.flows.create_account import RateLimitError

    monkeypatch.setattr(orch.Orchestrator, "_sleep", lambda self, s: None)

    class AlwaysLimited:
        def __init__(self, *_): ...
        def run(self, _d):
            raise RateLimitError("confirmação", "limite")

    o, repo, _ = make(tmp_path, AlwaysLimited)
    o.settings.accounts.rate_limit_wait = 10
    o.settings.accounts.rate_limit_max_waits = 2
    result = o.run(5)
    assert result.failed == 1 and "Muitas tentativas" in result.error
    assert FakeDevice.instances[0].log == ["open", "close"]       # não trocou de dispositivo à toa
    assert "Limite do site persistiu" in repo.list_recent()[0].error


def test_stop_during_cooldown_returns_quickly(tmp_path, monkeypatch):
    from automate_accounts.flows.create_account import RateLimitError

    stop = threading.Event()

    class Limited:
        def __init__(self, *_): ...
        def run(self, _d):
            stop.set()                      # usuário aperta S durante a espera
            raise RateLimitError("confirmação", "limite")

    o, repo, _ = make(tmp_path, Limited, stop=stop)
    result = o.run(3)
    assert result.created == 0 and result.stopped


# -- lotes, pausa, proxy -------------------------------------------------------
from automate_accounts.data import batches as bs  # noqa: E402


class FakeProxy:
    def __init__(self):
        self.port = 7777
        self.bytes_in = self.bytes_out = self.rotations = 0
        self.label = "h:1 sessão x"
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def rotate(self):
        self.rotations += 1
        self.bytes_in += 1000
        self.bytes_out += 500


def make_batch(tmp_path, flow, count=3, per_device=5, proxy=None, proxy_cfg=None, pause=None, stop=None):
    FakeDevice.instances = []
    settings = Settings(
        target_url="https://x.test/login", avd_name="a", android_home=tmp_path,
        accounts={"retries": 0, "delay_between": 0, "per_device": 5},
        proxy={"mode": "dynamic", "price_per_gb": 10.0, **(proxy_cfg or {})} if proxy else {},
    )
    db = tmp_path / "t.db"
    repo, brepo = AccountRepository(db), bs.BatchRepository(db)
    rec = brepo.create("Lote T", count, {"accounts": {"per_device": per_device}})
    events: list = []
    o = Orchestrator(
        settings, repo, on_event=lambda kind, **d: events.append((kind, d)), stop=stop, pause=pause,
        device_factory=FakeDevice, flow_factory=flow, generator=generate_account,
        batches=brepo, batch_id=rec.id,
        proxy_factory=lambda _s: proxy, ip_lookup=lambda _p: "200.1.1.1",
    )
    return o, repo, brepo, rec.id, events


def test_batch_uses_own_config_and_records_everything(tmp_path):
    o, repo, brepo, bid, events = make_batch(tmp_path, Ok, count=3, per_device=2)
    assert o.settings.accounts.per_device == 2          # config do lote vale sobre a global (5)
    result = o.run()
    assert (result.created, result.failed) == (3, 0) and result.devices == 2
    b = brepo.get(bid)
    assert b.status == bs.DONE and (b.created, b.failed, b.devices) == (3, 0, 2)
    assert b.started_at and b.finished_at and b.active_seconds >= 0
    assert [r.batch_id for r in repo.list_for_batch(bid)] == [bid] * 3
    msgs = [e.message for e in brepo.events(bid)]
    assert any("Lote iniciado" in m for m in msgs) and any("Lote concluido" in m for m in msgs)
    assert sum(m.startswith("Conta ") and "criada" in m for m in msgs) == 3


def test_batch_stop_is_resumable_and_resume_continues(tmp_path):
    stop = threading.Event()

    class StopAfterTwo:
        n = 0

        def __init__(self, *_): ...
        def run(self, _d):
            StopAfterTwo.n += 1
            if StopAfterTwo.n == 2:
                stop.set()

    o, repo, brepo, bid, _ = make_batch(tmp_path, StopAfterTwo, count=5, per_device=2, stop=stop)
    result = o.run()
    assert result.stopped and brepo.get(bid).status == bs.INTERRUPTED and brepo.get(bid).done == 2

    # retomar: novo Orchestrator sobre o mesmo lote cria só as 3 que faltam, numerando dispositivos adiante
    events = []
    o2 = Orchestrator(
        o.settings, repo, on_event=lambda k, **d: events.append((k, d)), device_factory=FakeDevice,
        flow_factory=Ok, generator=generate_account, batches=brepo, batch_id=bid,
    )
    res2 = o2.run()
    assert res2.created == 3
    b = brepo.get(bid)
    assert b.status == bs.DONE and b.created == 5 and b.remaining == 0
    devices = [r.device for r in repo.list_for_batch(bid)]
    assert devices[:2] == [1, 1] and devices[2] == 2          # retomada abre o dispositivo seguinte
    assert [d["done"] for k, d in events if k == "progress"] == [3, 4, 5]


def test_pause_blocks_until_resumed(tmp_path):
    pause = threading.Event()
    pause.set()
    o, repo, brepo, bid, events = make_batch(tmp_path, Ok, count=2, pause=pause)
    seen = []
    orig = o.emit

    def watch(kind, **d):
        orig(kind, **d)
        if kind == "paused" and d["paused"]:
            seen.append(brepo.get(bid).status)
            pause.clear()           # "retomar" assim que a pausa for registrada

    o.emit = watch
    result = o.run()
    assert seen == [bs.PAUSED] and result.created == 2
    assert brepo.get(bid).status == bs.DONE


def test_rate_limit_with_proxy_swaps_ip_instead_of_waiting(tmp_path, monkeypatch):
    from automate_accounts.flows.create_account import RateLimitError

    waits = []
    monkeypatch.setattr(orch.Orchestrator, "_sleep", lambda self, s: waits.append(s))
    calls = {"n": 0}

    class LimitedOnce:
        def __init__(self, *_): ...
        def run(self, _d):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RateLimitError("confirmação", "limite")

    proxy = FakeProxy()
    o, repo, brepo, bid, events = make_batch(tmp_path, LimitedOnce, count=1, proxy=proxy)
    result = o.run()
    assert result.created == 1 and proxy.rotations == 1
    assert not [e for e in events if e[0] == "cooldown"] and 180 not in waits   # não esperou
    b = brepo.get(bid)
    assert b.rotations_ip == 1 and b.bytes_in == 1000 and b.bytes_out == 500
    assert b.cost == pytest.approx(1500 / 1e9 * 10.0)
    assert proxy.started and proxy.stopped
    assert FakeDevice.instances[0].proxy_port == 7777


def test_proxy_rotates_per_device_and_can_be_disabled(tmp_path):
    proxy = FakeProxy()
    o, *_ = make_batch(tmp_path, Ok, count=4, per_device=2, proxy=proxy)
    o.run()
    assert proxy.rotations == 1                          # 4 contas / 2 por dispositivo = 1 troca

    proxy2 = FakeProxy()
    o2, *_ = make_batch(tmp_path, Ok, count=4, per_device=2, proxy=proxy2, proxy_cfg={"rotate_per_device": False})
    o2.run()
    assert proxy2.rotations == 0


def test_proxy_failure_aborts_before_emulator(tmp_path):
    from automate_accounts.core.proxy import ProxyError

    o, repo, brepo, bid, _ = make_batch(tmp_path, Ok, count=2, proxy=FakeProxy())
    o.ip_lookup = lambda _p: (_ for _ in ()).throw(ProxyError("sem saída"))
    # sem IP conhecido o lote segue (aviso), mas proxy inexistente aborta:
    o.proxy_factory = lambda _s: (_ for _ in ()).throw(ProxyError("lista vazia"))
    result = o.run()
    assert "lista vazia" in result.error and FakeDevice.instances == []
    b = brepo.get(bid)
    assert b.status == bs.FAILED and "lista vazia" in b.error


def test_unexpected_error_marks_batch_failed_and_reraises(tmp_path):
    class Boom(FakeDevice):
        def open(self):
            raise RuntimeError("AVD não existe")

    o, repo, brepo, bid, _ = make_batch(tmp_path, Ok)
    o.device_factory = Boom
    with pytest.raises(RuntimeError):
        o.run()
    b = brepo.get(bid)
    assert b.status == bs.FAILED and "AVD" in b.error
