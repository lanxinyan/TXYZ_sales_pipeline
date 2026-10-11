"""Local SQLite record of every thread the pipeline has looked at."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import Conversation, Order

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
# Columns added for the review dashboard (migrated onto older databases).
EXTRA_COLUMNS = {
    "kind": "TEXT DEFAULT 'order'",
    "priority": "INTEGER DEFAULT 0",
    "reasons": "TEXT",
    "plan_json": "TEXT",
    "waiting_since": "TEXT",
    "conv_json": "TEXT",
    "due_at": "TEXT",
}
OTHER_TABLES = """
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, thread_id TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS ignored (domain TEXT PRIMARY KEY, ts TEXT);
CREATE TABLE IF NOT EXISTS crm_logged (message_id TEXT PRIMARY KEY, thread_id TEXT, note_id TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS feed_sent (key TEXT PRIMARY KEY, ts TEXT);
CREATE TABLE IF NOT EXISTS seen (thread_id TEXT PRIMARY KEY, history_id TEXT);
CREATE TABLE IF NOT EXISTS feed_items (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, thread_id TEXT, text TEXT,
                                       exported INTEGER DEFAULT 0);
"""
FIELDS = ["thread_id", "subject", "thread_url", "message_count", "status", "order_code", "order_json",
          "issues", "zoho_id", "error", "updated_at", *EXTRA_COLUMNS]


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
    kind: str = "order"
    priority: int = 0
    reasons: list[str] = field(default_factory=list)
    plan: list[dict] = field(default_factory=list)
    waiting_since: str | None = None
    conv: Conversation | None = None
    due_at: str | None = None


class Store:
    """One SQLite file. Safe to share between the dashboard's threads: every
    statement runs under a lock and results are read out before it is released."""

    def __init__(self, path: str):
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.execute(SCHEMA)
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(orders)")}
            for col, typ in EXTRA_COLUMNS.items():
                if col not in have:
                    self.db.execute(f"ALTER TABLE orders ADD COLUMN {col} {typ}")
            self.db.executescript(OTHER_TABLES)
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('started_at', ?)", (_now(),))
            self.db.commit()

    def _all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def _write(self, sql: str, args=()) -> None:
        with self._lock:
            self.db.execute(sql, args)
            self.db.commit()

    def get(self, thread_id: str) -> Record | None:
        rows = self._all("SELECT * FROM orders WHERE thread_id=?", (thread_id,))
        return self._rec(rows[0]) if rows else None

    def list(self, status: str | list[str] | None = None) -> list[Record]:
        q, args = "SELECT * FROM orders", []
        if status:
            statuses = [status] if isinstance(status, str) else list(status)
            q += f" WHERE status IN ({','.join('?' * len(statuses))})"
            args = statuses
        return [self._rec(r) for r in self._all(q + " ORDER BY priority DESC, updated_at DESC", args)]

    def save(self, thread_id: str, *, subject: str = "", thread_url: str = "", message_count: int = 0,
             status: str, order: Order | None, issues: list[str], zoho_id: str | None = None,
             error: str | None = None, kind: str = "order", priority: int = 0,
             reasons: list[str] | None = None, plan: list[dict] | None = None,
             waiting_since: str | None = None, conv: Conversation | None = None,
             due_at: str | None = None) -> None:
        values = dict(
            thread_id=thread_id, subject=subject, thread_url=thread_url, message_count=message_count,
            status=status, order_code=order.order_code if order else None,
            order_json=order.model_dump_json() if order else None,
            issues=json.dumps(issues, ensure_ascii=False), zoho_id=zoho_id, error=error,
            updated_at=_now(),
            kind=kind, priority=priority, reasons=json.dumps(reasons or [], ensure_ascii=False),
            plan_json=json.dumps(plan or [], ensure_ascii=False), waiting_since=waiting_since,
            conv_json=conv.model_dump_json() if conv else None, due_at=due_at)
        self._write(f"INSERT OR REPLACE INTO orders ({','.join(FIELDS)}) VALUES ({','.join('?' * len(FIELDS))})",
                    [values[f] for f in FIELDS])

    def update(self, thread_id: str, **fields) -> None:
        with self._lock:   # read-modify-write as one step
            rec = self.get(thread_id)
            if rec is None:
                raise KeyError(thread_id)
            merged = dict(subject=rec.subject, thread_url=rec.thread_url, message_count=rec.message_count,
                          status=rec.status, order=rec.order, issues=rec.issues, zoho_id=rec.zoho_id,
                          error=rec.error, kind=rec.kind, priority=rec.priority, reasons=rec.reasons,
                          plan=rec.plan, waiting_since=rec.waiting_since, conv=rec.conv, due_at=rec.due_at)
            merged.update(fields)
            self.save(thread_id, **merged)

    @staticmethod
    def _rec(row: sqlite3.Row) -> Record:
        return Record(
            thread_id=row["thread_id"], subject=row["subject"], thread_url=row["thread_url"],
            message_count=row["message_count"], status=row["status"], order_code=row["order_code"],
            order=Order.model_validate_json(row["order_json"]) if row["order_json"] else None,
            issues=json.loads(row["issues"] or "[]"), zoho_id=row["zoho_id"], error=row["error"],
            updated_at=row["updated_at"], kind=row["kind"] or "order", priority=row["priority"] or 0,
            reasons=json.loads(row["reasons"] or "[]"), plan=json.loads(row["plan_json"] or "[]"),
            waiting_since=row["waiting_since"],
            conv=Conversation.model_validate_json(row["conv_json"]) if row["conv_json"] else None,
            due_at=row["due_at"])

    # ---------- activity log, ignore list, CRM log, meta ----------

    def log(self, thread_id: str, text: str) -> None:
        self._write("INSERT INTO activity (ts, thread_id, text) VALUES (?,?,?)", (_now(), thread_id, text))

    def activity(self, thread_id: str | None = None, limit: int = 100) -> list[dict]:
        q, args = "SELECT ts, thread_id, text FROM activity", []
        if thread_id:
            q, args = q + " WHERE thread_id=?", [thread_id]
        return [dict(r) for r in self._all(q + " ORDER BY id DESC LIMIT ?", [*args, limit])]

    def ignore_domain(self, domain: str) -> None:
        self._write("INSERT OR REPLACE INTO ignored VALUES (?,?)", (domain.lower(), _now()))

    def ignored_domains(self) -> set[str]:
        return {r["domain"] for r in self._all("SELECT domain FROM ignored")}

    def crm_logged(self, message_id: str) -> bool:
        return bool(self._all("SELECT 1 FROM crm_logged WHERE message_id=?", (message_id,)))

    def mark_crm_logged(self, message_id: str, thread_id: str, note_id: str) -> None:
        self._write("INSERT OR REPLACE INTO crm_logged VALUES (?,?,?,?)", (message_id, thread_id, note_id, _now()))

    def meta(self, key: str) -> str | None:
        rows = self._all("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        self._write("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def seen_history(self, thread_id: str) -> str | None:
        rows = self._all("SELECT history_id FROM seen WHERE thread_id=?", (thread_id,))
        return rows[0]["history_id"] if rows else None

    def set_seen_history(self, thread_id: str, history_id: str) -> None:
        self._write("INSERT OR REPLACE INTO seen VALUES (?,?)", (thread_id, history_id))

    # ---------- what has already gone to Cowork in a Gmail feed ----------

    def feed_seen(self, key: str) -> bool:
        return bool(self._all("SELECT 1 FROM feed_sent WHERE key=?", (key,)))

    def mark_feed(self, keys: list[str]) -> None:
        with self._lock:
            self.db.executemany("INSERT OR IGNORE INTO feed_sent VALUES (?,?)", [(k, _now()) for k in keys])
            self.db.commit()

    def add_feed_item(self, thread_id: str, text: str) -> None:
        """A decision made in Sales Desk (e.g. tag 不买了) for Cowork to carry out in Zoho."""
        self._write("INSERT INTO feed_items (ts, thread_id, text) VALUES (?,?,?)", (_now(), thread_id, text))

    def feed_items(self, pending_only: bool = True) -> list[dict]:
        q = "SELECT id, ts, thread_id, text FROM feed_items" + (" WHERE exported=0" if pending_only else "")
        return [dict(r) for r in self._all(q + " ORDER BY id")]

    def mark_items_exported(self, ids: list[int]) -> None:
        with self._lock:
            self.db.executemany("UPDATE feed_items SET exported=1 WHERE id=?", [(i,) for i in ids])
            self.db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
