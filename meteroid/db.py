"""SQLite storage for Meteroid.

The database is a single file (``meteroid.db`` by default, override with the
``METEROID_DB`` environment variable).  Every connection has foreign keys and
WAL mode enabled, and rows behave like mappings because of ``sqlite3.Row``.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "meteroid.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    version      INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    currency     TEXT NOT NULL,
    interval     TEXT NOT NULL CHECK (interval IN ('month', 'year')),
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers (id),
    plan_id     INTEGER NOT NULL REFERENCES plans (id),
    status      TEXT NOT NULL CHECK (status IN ('active', 'pending', 'canceled')),
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions (id),
    number          TEXT NOT NULL UNIQUE,
    amount_cents    INTEGER NOT NULL,
    currency        TEXT NOT NULL,
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('open', 'paid', 'void')),
    issued_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_customer ON subscriptions (customer_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_plan ON subscriptions (plan_id);
CREATE INDEX IF NOT EXISTS idx_invoices_subscription ON invoices (subscription_id);
"""


def db_path() -> str:
    """Return the configured database path (``METEROID_DB`` or the default)."""
    return os.environ.get("METEROID_DB", str(DEFAULT_DB))


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open a connection to *path* (defaults to :func:`db_path`)."""
    target = str(path) if path is not None else db_path()
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Create the schema if it does not exist yet."""
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def open_db(path: str | None = None) -> sqlite3.Connection:
    """Connect and make sure the schema exists."""
    return init_db(connect(path))
