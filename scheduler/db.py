import sqlite3
import sys
from pathlib import Path

TYPES = ("project", "item", "subitem")
STATUSES = ("todo", "in_progress", "in_review", "blocked", "done")
PRIORITIES = ("highest", "high", "medium", "low", "lowest")

SCHEMA = """
CREATE TABLE IF NOT EXISTS issues (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL CHECK (type IN ('project','item','subitem')),
    parent_id   INTEGER REFERENCES issues(id) ON DELETE CASCADE,
    key         TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    priority    TEXT NOT NULL DEFAULT 'medium',
    assignee    TEXT NOT NULL DEFAULT '',
    reporter    TEXT NOT NULL DEFAULT '',
    labels      TEXT NOT NULL DEFAULT '',
    start_date  TEXT,
    due_date    TEXT,
    estimate_h  REAL,
    progress    INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_issues_parent ON issues(parent_id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS undo_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch TEXT NOT NULL,           -- JSON list of inverse operations
    label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def app_dir() -> Path:
    """Directory holding the db: next to the .exe when frozen, else repo root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return app_dir() / "scheduler.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
