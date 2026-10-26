"""Lotes de execução: configuração usada, estado, métricas e log de eventos (SQLite)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .repository import DB_PATH

PLANNED, RUNNING, PAUSED, DONE, INTERRUPTED, FAILED = (
    "planejado", "executando", "pausado", "concluido", "interrompido", "falhou",
)
STATUSES = (PLANNED, RUNNING, PAUSED, DONE, INTERRUPTED, FAILED)
RESUMABLE = (PLANNED, PAUSED, INTERRUPTED, FAILED)   # estados de onde dá para (re)iniciar

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    notes           TEXT NOT NULL DEFAULT '',
    config          TEXT NOT NULL DEFAULT '{}',
    target_count    INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    created         INTEGER NOT NULL DEFAULT 0,
    failed          INTEGER NOT NULL DEFAULT 0,
    devices         INTEGER NOT NULL DEFAULT 0,
    active_seconds  REAL NOT NULL DEFAULT 0,
    cooldowns       INTEGER NOT NULL DEFAULT 0,
    cooldown_seconds REAL NOT NULL DEFAULT 0,
    rotations_ip    INTEGER NOT NULL DEFAULT 0,
    bytes_in        INTEGER NOT NULL DEFAULT 0,
    bytes_out       INTEGER NOT NULL DEFAULT 0,
    cost            REAL NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'R$',
    error           TEXT
);
CREATE TABLE IF NOT EXISTS batch_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    ts       TEXT NOT NULL,
    level    TEXT NOT NULL,
    source   TEXT NOT NULL,
    message  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batch_events_batch ON batch_events (batch_id, id);
"""

# colunas numéricas que podem ser acumuladas com add_to()
COUNTERS = {
    "created", "failed", "devices", "active_seconds", "cooldowns", "cooldown_seconds",
    "rotations_ip", "bytes_in", "bytes_out",
}


@dataclass(frozen=True)
class BatchRecord:
    id: int
    name: str
    status: str
    notes: str
    config: dict[str, Any]
    target_count: int
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    created: int = 0
    failed: int = 0
    devices: int = 0
    active_seconds: float = 0.0
    cooldowns: int = 0
    cooldown_seconds: float = 0.0
    rotations_ip: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    cost: float = 0.0
    currency: str = "R$"
    error: str | None = None

    @property
    def done(self) -> int:
        return self.created + self.failed

    @property
    def remaining(self) -> int:
        return max(0, self.target_count - self.done)

    @property
    def total_bytes(self) -> int:
        return self.bytes_in + self.bytes_out

    @property
    def seconds_per_account(self) -> float | None:
        return self.active_seconds / self.done if self.done else None

    @property
    def success_rate(self) -> float | None:
        return self.created * 100 / self.done if self.done else None


@dataclass(frozen=True)
class BatchEvent:
    id: int
    batch_id: int
    ts: str
    level: str
    source: str
    message: str


def _row_to_batch(row: sqlite3.Row) -> BatchRecord:
    data = dict(row)
    try:
        data["config"] = json.loads(data["config"] or "{}")
    except ValueError:
        data["config"] = {}
    return BatchRecord(**data)


class BatchRepository:
    """Uma conexão por operação (seguro entre threads), no mesmo banco das contas."""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    # -- lotes -------------------------------------------------------------
    def create(
        self, name: str, target_count: int, config: dict[str, Any] | None = None,
        notes: str = "", currency: str = "R$",
    ) -> BatchRecord:
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO batches (name, status, notes, config, target_count, created_at, currency) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name.strip() or "Lote sem nome", PLANNED, notes, json.dumps(config or {}),
                 target_count, now, currency),
            )
            batch_id = cur.lastrowid
        return self.get(batch_id)

    def get(self, batch_id: int) -> BatchRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        return _row_to_batch(row) if row else None

    def list_all(self, limit: int = 200) -> list[BatchRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM batches ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_row_to_batch(r) for r in rows]

    def update(self, batch_id: int, **fields: Any) -> None:
        """Atualiza colunas (status, started_at, finished_at, error, cost, notes, name...)."""
        if not fields:
            return
        if "config" in fields:
            fields["config"] = json.dumps(fields["config"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        with closing(self._connect()) as conn, conn:
            conn.execute(f"UPDATE batches SET {cols} WHERE id = ?", (*fields.values(), batch_id))

    def add_to(self, batch_id: int, **deltas: float) -> None:
        """Soma valores a contadores (created, failed, bytes_in, active_seconds...)."""
        bad = set(deltas) - COUNTERS
        if bad:
            raise ValueError(f"Colunas não acumuláveis: {sorted(bad)}")
        sets = ", ".join(f"{k} = {k} + ?" for k in deltas)
        with closing(self._connect()) as conn, conn:
            conn.execute(f"UPDATE batches SET {sets} WHERE id = ?", (*deltas.values(), batch_id))

    def delete(self, batch_id: int) -> None:
        """Remove o lote e seu log; as contas criadas ficam (sem vínculo)."""
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM batch_events WHERE batch_id = ?", (batch_id,))
            conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
            try:
                conn.execute("UPDATE accounts SET batch_id = NULL WHERE batch_id = ?", (batch_id,))
            except sqlite3.OperationalError:
                pass   # tabela de contas ainda não criada

    def mark_interrupted_running(self) -> int:
        """No início do programa: lotes 'executando/pausado' de uma sessão que morreu viram 'interrompido'."""
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "UPDATE batches SET status = ?, error = COALESCE(error, 'Programa encerrado durante a execução') "
                "WHERE status IN (?, ?)",
                (INTERRUPTED, RUNNING, PAUSED),
            )
            return cur.rowcount

    # -- eventos (log do lote) -------------------------------------------
    def add_event(self, batch_id: int, level: str, source: str, message: str) -> None:
        now = datetime.now().isoformat(timespec="milliseconds")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO batch_events (batch_id, ts, level, source, message) VALUES (?, ?, ?, ?, ?)",
                (batch_id, now, level, source, message),
            )

    def events(self, batch_id: int, level: str | None = None, limit: int = 5000) -> list[BatchEvent]:
        query, params = "SELECT * FROM batch_events WHERE batch_id = ?", [batch_id]
        if level:
            query += " AND level = ?"
            params.append(level)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [BatchEvent(**dict(r)) for r in rows]

