import pytest

from automate_accounts.data import batches as b
from automate_accounts.data.repository import AccountRepository


@pytest.fixture
def repos(tmp_path):
    db = tmp_path / "t.db"
    return AccountRepository(db), b.BatchRepository(db)


def test_create_and_defaults(repos):
    _, br = repos
    rec = br.create("  Lote A ", 20, {"per_device": 5}, notes="teste")
    assert rec.name == "Lote A" and rec.status == b.PLANNED and rec.config == {"per_device": 5}
    assert rec.remaining == 20 and rec.success_rate is None and rec.seconds_per_account is None
    assert br.create("", 1).name == "Lote sem nome"


def test_counters_and_derived_metrics(repos):
    _, br = repos
    rec = br.create("L", 10)
    br.add_to(rec.id, created=3, failed=1, active_seconds=200, bytes_in=1000, bytes_out=500)
    br.add_to(rec.id, created=1)
    got = br.get(rec.id)
    assert (got.created, got.failed, got.done, got.remaining) == (4, 1, 5, 5)
    assert got.total_bytes == 1500 and got.seconds_per_account == 40 and got.success_rate == 80
    with pytest.raises(ValueError):
        br.add_to(rec.id, status="x")


def test_update_and_interrupted_recovery(repos):
    _, br = repos
    a, c = br.create("A", 1), br.create("C", 1)
    br.update(a.id, status=b.RUNNING)
    br.update(c.id, status=b.DONE)
    assert br.mark_interrupted_running() == 1
    assert br.get(a.id).status == b.INTERRUPTED and "encerrado" in br.get(a.id).error
    assert br.get(c.id).status == b.DONE


def test_events_filter_and_order(repos):
    _, br = repos
    rec = br.create("L", 1)
    br.add_event(rec.id, "INFO", "orquestrador", "início")
    br.add_event(rec.id, "WARNING", "flow", "limite")
    assert [e.message for e in br.events(rec.id)] == ["início", "limite"]
    assert [e.message for e in br.events(rec.id, level="WARNING")] == ["limite"]


def test_accounts_linked_to_batch_and_progress(repos):
    ar, br = repos
    rec = br.create("L", 5)
    ar.add("a@x", "p", "criada", device=1, batch_id=rec.id)
    ar.add("b@x", "p", "falhou", device=2, batch_id=rec.id)
    ar.add("c@x", "p", "criada")                       # fora do lote
    assert [r.email for r in ar.list_for_batch(rec.id)] == ["a@x", "b@x"]
    assert ar.batch_progress(rec.id) == {"criada": 1, "falhou": 1, "device": 2}
    assert len(ar.search(batch_id=rec.id)) == 2
    assert ar.batch_progress(999) == {"criada": 0, "falhou": 0, "device": 0}


def test_delete_keeps_accounts(repos):
    ar, br = repos
    rec = br.create("L", 1)
    br.add_event(rec.id, "INFO", "x", "y")
    ar.add("a@x", "p", "criada", batch_id=rec.id)
    br.delete(rec.id)
    assert br.get(rec.id) is None and br.events(rec.id) == []
    assert ar.list_recent()[0].batch_id is None
