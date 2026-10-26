"""Registro das contas criadas (SQLite em data/accounts.db)."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import ROOT

DB_PATH = ROOT / "data" / "accounts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL,
    password   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('criada', 'falhou')),
    error      TEXT,
    created_at TEXT NOT NULL,
    duration   REAL,
    device     INTEGER
)
"""
MIGRATIONS = (
    "ALTER TABLE accounts ADD COLUMN duration REAL",
    "ALTER TABLE accounts ADD COLUMN device INTEGER",
)


@dataclass(frozen=True)
class AccountRecord:
    id: int
    email: str
    password: str
    status: str
    error: str | None
    created_at: str
    duration: float | None = None   # segundos gastos na conta (todas as tentativas)
    device: int | None = None       # número do dispositivo (ciclo de troca) em que foi criada


class AccountRepository:
    """Abre uma conexão por operação: seguro para uso a partir de threads."""

    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute(SCHEMA)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)")}
            for statement in MIGRATIONS:
                if statement.split()[-2] not in existing:
                    conn.execute(statement)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(
        self, email: str, password: str, status: str, error: str | None = None,
        duration: float | None = None, device: int | None = None,
    ) -> AccountRecord:
        now = datetime.now().isoformat(timespec="seconds")
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO accounts (email, password, status, error, created_at, duration, device) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (email, password, status, error, now, duration, device),
            )
            return AccountRecord(
                cur.lastrowid, email, password, status, error, now, duration, device
            )

    def avg_duration(self, last: int = 20) -> float | None:
        """Média (s) das últimas contas criadas com sucesso; None se não há histórico."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT AVG(duration) AS avg FROM (SELECT duration FROM accounts "
                "WHERE status = 'criada' AND duration IS NOT NULL ORDER BY id DESC LIMIT ?)",
                (last,),
            ).fetchone()
        return row["avg"]

    def search(self, text: str = "", status: str | None = None, limit: int = 500) -> list[AccountRecord]:
        query, params = "SELECT * FROM accounts WHERE 1=1", []
        if text:
            query += " AND email LIKE ?"
            params.append(f"%{text}%")
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [AccountRecord(**dict(r)) for r in rows]

    def list_recent(self, limit: int = 50) -> list[AccountRecord]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [AccountRecord(**dict(r)) for r in rows]

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM accounts GROUP BY status")
            data = {r["status"]: r["n"] for r in rows}
        return {"criada": data.get("criada", 0), "falhou": data.get("falhou", 0)}
