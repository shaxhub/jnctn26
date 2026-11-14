"""SQLite state: quotes, orders, approvals and the append-only, hash-chained audit log.

Audit events are chained: hash = sha256(prev_hash + canonical JSON of the event). Triggers block
UPDATE and DELETE on audit_events, and `verify_chain()` recomputes every hash.

TODO(A): Postgres for production; periodically anchor the latest hash somewhere external
         (e.g. sign it with the quote key and publish it) so a DB admin cannot rewrite history.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import TZ, settings

GENESIS = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    quote_id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',            -- open | used
    total_net REAL NOT NULL, payload_json TEXT NOT NULL, jws TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, quote_id TEXT NOT NULL UNIQUE REFERENCES quotes(quote_id), buyer_id TEXT NOT NULL,
    status TEXT NOT NULL, total_net REAL NOT NULL, currency TEXT NOT NULL, delivery_date TEXT NOT NULL,
    lines_json TEXT NOT NULL, policy_json TEXT NOT NULL, approval_id TEXT, agent_rationale TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), buyer_id TEXT NOT NULL,
    status TEXT NOT NULL, reasons_json TEXT NOT NULL, created_at TEXT NOT NULL,
    decided_at TEXT, decided_by TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL,
    buyer_id TEXT, order_id TEXT, quote_id TEXT, data_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_audit_order ON audit_events(order_id);
CREATE INDEX IF NOT EXISTS idx_audit_quote ON audit_events(quote_id);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
    BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
"""

_lock = threading.RLock()
_initialized: set[str] = set()
_demo_now: datetime | None = None


def set_demo_now(dt: datetime | None) -> None:
    global _demo_now
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    _demo_now = dt


def get_demo_now() -> datetime | None:
    return _demo_now


def now() -> datetime:
    if _demo_now is not None:
        return _demo_now
    if settings.demo_now:
        dt = datetime.fromisoformat(settings.demo_now)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=TZ)
    return datetime.now(TZ)


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        need_init = str(path) not in _initialized or not path.exists()
        conn = sqlite3.connect(path, timeout=10, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            if need_init:
                conn.executescript(SCHEMA)
                _initialized.add(str(path))
        except Exception:
            conn.close()
            raise
    try:
        yield conn
    finally:
        conn.close()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def event_hash(prev_hash: str, ev: dict) -> str:
    body = {k: ev[k] for k in ("ts", "event_type", "actor", "buyer_id", "order_id", "quote_id", "data")}
    return hashlib.sha256((prev_hash + canonical(body)).encode()).hexdigest()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise


def append_in_transaction(conn: sqlite3.Connection, event_type: str, actor: str, data: dict, *,
                          buyer_id: str | None = None, order_id: str | None = None,
                          quote_id: str | None = None) -> dict:
    row = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    prev = row["hash"] if row else GENESIS
    event = {"ts": now().isoformat(), "event_type": event_type, "actor": actor, "buyer_id": buyer_id,
             "order_id": order_id, "quote_id": quote_id, "data": json.loads(canonical(data))}
    event["prev_hash"], event["hash"] = prev, event_hash(prev, event)
    cursor = conn.execute(
        "INSERT INTO audit_events (ts,event_type,actor,buyer_id,order_id,quote_id,data_json,prev_hash,hash)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (event["ts"], event_type, actor, buyer_id, order_id, quote_id, canonical(event["data"]), prev, event["hash"]))
    event["seq"] = cursor.lastrowid
    return event


def append_event(event_type: str, actor: str, data: dict, *, buyer_id: str | None = None,
                 order_id: str | None = None, quote_id: str | None = None, db_path: Path | None = None) -> dict:
    with _lock, connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        event = append_in_transaction(conn, event_type, actor, data, buyer_id=buyer_id,
                                      order_id=order_id, quote_id=quote_id)
        conn.commit()
        return event


def _row_event(r: sqlite3.Row) -> dict:
    return {"seq": r["seq"], "ts": r["ts"], "event_type": r["event_type"], "actor": r["actor"],
            "buyer_id": r["buyer_id"], "order_id": r["order_id"], "quote_id": r["quote_id"],
            "data": json.loads(r["data_json"]), "prev_hash": r["prev_hash"], "hash": r["hash"]}


def events(order_id: str | None = None, quote_id: str | None = None, buyer_id: str | None = None,
           limit: int = 500, db_path: Path | None = None) -> list[dict]:
    where, params = [], []
    if order_id and quote_id:
        where.append("(order_id = ? OR quote_id = ?)")
        params += [order_id, quote_id]
    elif order_id:
        where.append("order_id = ?")
        params.append(order_id)
    elif quote_id:
        where.append("quote_id = ?")
        params.append(quote_id)
    if buyer_id:
        where.append("buyer_id = ?")
        params.append(buyer_id)
    sql = "SELECT * FROM audit_events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY seq LIMIT ?"
    with connect(db_path) as conn:
        return [_row_event(r) for r in conn.execute(sql, params + [limit]).fetchall()]


def verify_chain(db_path: Path | None = None) -> dict:
    prev = GENESIS
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
    for idx, r in enumerate(rows, start=1):
        ev = _row_event(r)
        if ev["seq"] != idx or ev["prev_hash"] != prev or event_hash(prev, ev) != ev["hash"]:
            return {"ok": False, "events": len(rows), "first_bad_seq": ev["seq"], "head": prev}
        prev = ev["hash"]
    return {"ok": True, "events": len(rows), "head": prev}


def reset_db(db_path: Path | None = None) -> None:
    """Clear all gateway state and audit rows (for demo resets and test isolation)."""
    with _lock, connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
            conn.execute("DELETE FROM approvals")
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM quotes")
            conn.execute("DELETE FROM audit_events")
            has_seq = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
            ).fetchone()
            if has_seq:
                conn.execute("DELETE FROM sqlite_sequence WHERE name = 'audit_events'")
            conn.execute(
                "CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events"
                " BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END"
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


# --- simple CRUD helpers -----------------------------------------------------------------------
def execute(sql: str, params: tuple = (), db_path: Path | None = None) -> None:
    with _lock, connect(db_path) as conn:
        conn.execute(sql, params)


def fetchone(sql: str, params: tuple = (), db_path: Path | None = None) -> sqlite3.Row | None:
    with connect(db_path) as conn:
        return conn.execute(sql, params).fetchone()


def fetchall(sql: str, params: tuple = (), db_path: Path | None = None) -> list[sqlite3.Row]:
    with connect(db_path) as conn:
        return conn.execute(sql, params).fetchall()
