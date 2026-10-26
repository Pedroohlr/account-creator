from automate_accounts.data import batches as bs
from automate_accounts.data import report
from automate_accounts.data.repository import AccountRepository


def test_formats():
    assert report.fmt_bytes(512) == "512 B" and report.fmt_bytes(1536) == "1.5 KB"
    assert report.fmt_bytes(5 * 1024**3) == "5.0 GB"
    assert report.fmt_money(1234.5, "R$") == "R$ 1.234,5000"


def test_export_batch_writes_report_accounts_and_log(tmp_path):
    db = tmp_path / "t.db"
    ar, br = AccountRepository(db), bs.BatchRepository(db)
    rec = br.create("Teste", 3, {"accounts": {"per_device": 2}, "proxy": {"mode": "dynamic"}}, notes="obs importante")
    ar.add("a@x", "pw1", "criada", duration=40, device=1, batch_id=rec.id)
    ar.add("b@x", "pw2", "falhou", "timeout", duration=90, device=1, batch_id=rec.id)
    br.add_to(rec.id, created=1, failed=1, active_seconds=130, bytes_in=2048, bytes_out=1024, rotations_ip=2)
    br.update(rec.id, cost=0.5, status=bs.INTERRUPTED)
    br.add_event(rec.id, "INFO", "core.orchestrator", "Lote iniciado")
    br.add_event(rec.id, "WARNING", "core.orchestrator", "Site limitou o IP")
    folder = report.export_batch(rec.id, ar, br, tmp_path / "exports")
    md = (folder / "relatorio.md").read_text(encoding="utf-8")
    assert "Lote #1 — Teste" in md and "criadas 1, falhas 1" in md and "Trocas de IP: 2" in md
    assert "R$ 0,5000" in md and "contas por dispositivo: 2" in md and "proxy: dynamic" in md
    assert "obs importante" in md and "Site limitou o IP" in md and "b@x: timeout" in md
    assert "pw1" in (folder / "contas.csv").read_text(encoding="utf-8-sig")
    assert "Lote iniciado" in (folder / "log.csv").read_text(encoding="utf-8-sig")


def test_export_unknown_batch(tmp_path):
    import pytest

    db = tmp_path / "t.db"
    with pytest.raises(ValueError):
        report.export_batch(9, AccountRepository(db), bs.BatchRepository(db), tmp_path)
