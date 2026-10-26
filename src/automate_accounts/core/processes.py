"""Controle de processos: limpeza de órfãos (emulador/Appium) e instância única.

Só mexe em processos que ESTA ferramenta registrou: nunca encerra um emulador que você abriu
por conta própria no Android Studio.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import subprocess
from pathlib import Path

from ..config import ROOT

log = logging.getLogger(__name__)

DATA_DIR = ROOT / "data"
REGISTRY = DATA_DIR / "processes.json"
LOCK = DATA_DIR / "app.lock"

# nomes de imagem aceitos para cada tipo (confere antes de matar, para não acertar um PID reciclado)
EXPECTED = {
    "emulator": {"emulator.exe", "qemu-system-x86_64.exe", "qemu-system-aarch64.exe"},
    "appium": {"cmd.exe", "node.exe"},
}


class AlreadyRunning(RuntimeError):
    pass


def _tasklist(pid: int) -> str | None:
    """Nome da imagem do processo, ou None se não existe."""
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False,
    )
    rows = list(csv.reader(io.StringIO(result.stdout)))
    for row in rows:
        if len(row) > 1 and row[1].strip() == str(pid):
            return row[0].lower()
    return None


def pid_alive(pid: int) -> bool:
    return _tasklist(pid) is not None


def kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def register(kind: str, pid: int, path: Path | None = None) -> None:
    path = path or REGISTRY
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _read(path)
    data["owner"] = os.getpid()
    data.setdefault("children", {})[kind] = pid
    path.write_text(json.dumps(data), encoding="utf-8")


def unregister(kind: str, path: Path | None = None) -> None:
    path = path or REGISTRY
    data = _read(path)
    data.get("children", {}).pop(kind, None)
    if path.exists():
        path.write_text(json.dumps(data), encoding="utf-8")


def cleanup_orphans(path: Path | None = None) -> list[str]:
    """Encerra emulador/Appium deixados por uma execução anterior que morreu sem limpar."""
    path = path or REGISTRY
    data = _read(path)
    if not data:
        return []
    owner = data.get("owner")
    if owner and owner != os.getpid() and pid_alive(owner):
        return []   # outra instância ainda está viva e é dona deles
    killed: list[str] = []
    for kind, pid in data.get("children", {}).items():
        image = _tasklist(pid)
        if image and image in EXPECTED.get(kind, set()):
            log.warning("Encerrando %s órfão (PID %s, %s) de uma execução anterior.", kind, pid, image)
            kill_tree(pid)
            killed.append(f"{kind} (PID {pid})")
    path.unlink(missing_ok=True)
    return killed


def acquire_lock(path: Path | None = None) -> None:
    """Impede duas instâncias do painel ao mesmo tempo (disputariam o emulador e o banco)."""
    path = path or LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        other = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        other = None
    if other and other != os.getpid() and pid_alive(other):
        raise AlreadyRunning(f"Já existe outra instância em execução (PID {other}). Feche-a primeiro.")
    path.write_text(str(os.getpid()), encoding="utf-8")


def release_lock(path: Path | None = None) -> None:
    path = path or LOCK
    try:
        if path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass
