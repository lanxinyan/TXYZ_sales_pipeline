"""Local SQLite record of every thread the pipeline has looked at."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import Order

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    thread_id     TEXT PRIMARY KEY,
    subject       TEXT,
    thread_url    TEXT,
    message_count INTEGER,
    status        TEXT NOT NULL,
    order_code    TEXT,
    order_json    TEXT,
    issues        TEXT,
    zoho_id       TEXT,
    error         TEXT,
    updated_at    TEXT
)
"""


@dataclass
class Record:
    thread_id: str
    subject: str
    thread_url: str
    message_count: int
    status: str
    order_code: str | None
    order: Order | None
    issues: list[str]
    zoho_id: str | None
    error: str | None
    updated_at: str


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.commit()

    def get(self, thread_id: str) -> Record | None:
        row = self.db.execute("SELECT * FROM orders WHERE thread_id=?", (thread_id,)).fetchone()
        return self._rec(row) if row else None

    def list(self, status: str | None = None) -> list[Record]:
        q, args = "SELECT * FROM orders", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        return [self._rec(r) for r in self.db.execute(q + " ORDER BY updated_at DESC", args)]

    def save(self, thread_id: str, *, subject: str = "", thread_url: str = "", message_count: int = 0,
             status: str, order: Order | None, issues: list[str], zoho_id: str | None = None,
             error: str | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (thread_id, subject, thread_url, message_count, status,
             order.order_code if order else None,
             order.model_dump_json() if order else None,
             json.dumps(issues, ensure_ascii=False), zoho_id, error,
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        self.db.commit()

    def update(self, thread_id: str, **fields) -> None:
        rec = self.get(thread_id)
        if rec is None:
            raise KeyError(thread_id)
        merged = dict(subject=rec.subject, thread_url=rec.thread_url, message_count=rec.message_count,
                      status=rec.status, order=rec.order, issues=rec.issues, zoho_id=rec.zoho_id,
                      error=rec.error)
        merged.update(fields)
        self.save(thread_id, **merged)

    @staticmethod
    def _rec(row: sqlite3.Row) -> Record:
        return Record(
            thread_id=row["thread_id"], subject=row["subject"], thread_url=row["thread_url"],
            message_count=row["message_count"], status=row["status"], order_code=row["order_code"],
            order=Order.model_validate_json(row["order_json"]) if row["order_json"] else None,
            issues=json.loads(row["issues"] or "[]"), zoho_id=row["zoho_id"], error=row["error"],
            updated_at=row["updated_at"])
