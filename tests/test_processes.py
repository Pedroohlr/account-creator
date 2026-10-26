import json
import os

import pytest

from automate_accounts.core import processes as proc


@pytest.fixture
def fake_os(monkeypatch):
    """Simula a tabela de processos: {pid: nome_da_imagem}."""
    table: dict[int, str] = {}
    killed: list[int] = []
    monkeypatch.setattr(proc, "_tasklist", lambda pid: table.get(pid))
    monkeypatch.setattr(proc, "kill_tree", lambda pid: killed.append(pid))
    return table, killed


def test_register_and_unregister(tmp_path):
    reg = tmp_path / "p.json"
    proc.register("emulator", 111, reg)
    proc.register("appium", 222, reg)
    data = json.loads(reg.read_text())
    assert data["owner"] == os.getpid() and data["children"] == {"emulator": 111, "appium": 222}
    proc.unregister("emulator", reg)
    assert json.loads(reg.read_text())["children"] == {"appium": 222}


def test_cleanup_kills_orphans_of_dead_owner(tmp_path, fake_os):
    table, killed = fake_os
    reg = tmp_path / "p.json"
    reg.write_text(json.dumps({"owner": 999, "children": {"emulator": 111, "appium": 222}}))
    table[111] = "qemu-system-x86_64.exe"
    table[222] = "node.exe"          # dono (999) não existe mais
    result = proc.cleanup_orphans(reg)
    assert sorted(killed) == [111, 222] and len(result) == 2
    assert not reg.exists()


def test_cleanup_respects_live_owner(tmp_path, fake_os):
    table, killed = fake_os
    reg = tmp_path / "p.json"
    reg.write_text(json.dumps({"owner": 999, "children": {"emulator": 111}}))
    table[999] = "python.exe"        # outra instância viva
    table[111] = "emulator.exe"
    assert proc.cleanup_orphans(reg) == [] and killed == []
    assert reg.exists()


def test_cleanup_never_kills_unexpected_process(tmp_path, fake_os):
    """PID reciclado por outro programa (ex.: navegador) não pode ser encerrado."""
    table, killed = fake_os
    reg = tmp_path / "p.json"
    reg.write_text(json.dumps({"owner": 999, "children": {"emulator": 111}}))
    table[111] = "chrome.exe"
    assert proc.cleanup_orphans(reg) == [] and killed == []


def test_cleanup_without_registry(tmp_path):
    assert proc.cleanup_orphans(tmp_path / "nada.json") == []


def test_lock_blocks_second_instance_but_not_stale_lock(tmp_path, fake_os):
    table, _ = fake_os
    lock = tmp_path / "app.lock"
    lock.write_text("4242")
    table[4242] = "python.exe"
    with pytest.raises(proc.AlreadyRunning, match="4242"):
        proc.acquire_lock(lock)
    table.clear()                      # processo antigo morreu: lock obsoleto
    proc.acquire_lock(lock)
    assert lock.read_text() == str(os.getpid())
    proc.release_lock(lock)
    assert not lock.exists()
