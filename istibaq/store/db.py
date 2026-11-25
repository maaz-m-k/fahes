"""SQLite store for the Istibaq engine.

One file at ``ISTIBAQ_DB`` (default ``./var/istibaq.db``; ``/data/istibaq.db`` on Fly.io).
Structured fields that vary by case are stored as JSON text.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  link TEXT NOT NULL,
  source TEXT NOT NULL,
  verdict TEXT NOT NULL,
  score REAL NOT NULL,
  verdict_json TEXT NOT NULL,
  capture_json TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  run_id INTEGER,
  opened_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id INTEGER NOT NULL REFERENCES cases(id),
  body_json TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  sealed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id INTEGER NOT NULL REFERENCES records(id),
  method TEXT NOT NULL CHECK (method IN ('voice', 'click')),
  officer TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  approval_sha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS register_edits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  address TEXT NOT NULL,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  note TEXT,
  case_id INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trigger TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  summary_json TEXT
);
CREATE TABLE IF NOT EXISTS watch_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES watch_runs(id),
  seq INTEGER NOT NULL,
  body_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  address TEXT NOT NULL,
  published_at TEXT NOT NULL,
  found_at TEXT,
  feed TEXT,
  note TEXT
);
CREATE TABLE IF NOT EXISTS costs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service TEXT NOT NULL,
  amount_usd REAL NOT NULL,
  detail_json TEXT NOT NULL,
  at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_path() -> str:
    return os.environ.get("ISTIBAQ_DB", "./var/istibaq.db")


class Store:
    """Thin, thread-safe wrapper around one SQLite connection."""

    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid

    def all(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        self.conn.close()


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(text: str | None) -> Any:
    return json.loads(text) if text else None
