"""Limits for the open desk (no passcode for the public).

All server-side and configurable by environment:

| Limit | Env | Default |
|---|---|---|
| Voice off switch | ``ISTIBAQ_VOICE=0`` | on |
| All paid searches off (watch round, Google check, Fahes search page) | ``ISTIBAQ_PAID=0`` | on |
| Scoring requests per visitor per minute | ``ISTIBAQ_SCORE_PER_MINUTE`` | 60 |
| Links per batch request | ``ISTIBAQ_BATCH_MAX`` | 1000 |

The Google and ads check keeps its own DataForSEO limits. Voice sessions are counted in SQLite (``voice_sessions``)
for the cost view; on the team lead's word there is no session length, concurrency or daily voice cap, and "run a
round now" is not rate-limited.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from istibaq.store.db import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started REAL NOT NULL,          -- unix time the key was minted
  day TEXT NOT NULL,              -- UTC day
  seconds REAL                    -- reported length; NULL until the browser reports it
);
"""


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def voice_on() -> bool:
    return os.environ.get("ISTIBAQ_VOICE", "1") != "0"


def paid_on() -> bool:
    return os.environ.get("ISTIBAQ_PAID", "1") != "0"


def batch_max() -> int:
    return int(_env_float("ISTIBAQ_BATCH_MAX", 1000))


class LimitHit(Exception):
    """A hard limit was reached; ``ar`` and ``en`` are plain messages for the desk."""

    def __init__(self, en: str, ar: str, retry_after: int | None = None):
        super().__init__(en)
        self.en, self.ar, self.retry_after = en, ar, retry_after

    def to_dict(self) -> dict:
        return {"detail": self.en, "detail_ar": self.ar, "retry_after": self.retry_after}


class Limits:
    def __init__(self, store: Store, now=time.time):
        self.store, self.now = store, now
        with store._lock:
            store.conn.executescript(SCHEMA)
            store.conn.commit()
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)

    # ------------------------------------------------------------------ voice
    def _day(self) -> str:
        return datetime.fromtimestamp(self.now(), timezone.utc).strftime("%Y-%m-%d")

    def voice_status(self) -> dict:
        row = self.store.one("SELECT COUNT(*) n, COALESCE(SUM(seconds), 0) s FROM voice_sessions WHERE day=?", (self._day(),))
        return {"on": voice_on(), "sessions_today": row["n"], "minutes_today": round(row["s"] / 60, 1)}

    def start_voice(self) -> int:
        """Count a voice session (for the cost view) or raise LimitHit when voice is switched off."""
        if not voice_on():
            raise LimitHit("Voice is switched off on this server. Typing still works.",
                           "الصوت متوقف على هذا الخادم. الكتابة ما زالت تعمل.")
        return self.store.execute("INSERT INTO voice_sessions (started, day) VALUES (?,?)", (self.now(), self._day()))

    def end_voice(self, session_id: int | None, seconds: float) -> None:
        if session_id:
            self.store.execute("UPDATE voice_sessions SET seconds=? WHERE id=? AND seconds IS NULL",
                               (max(0.0, float(seconds or 0)), session_id))

    # ------------------------------------------------------------------ per-visitor rate
    def hit(self, visitor: str, per_minute: int | None = None) -> None:
        per_minute = per_minute or int(_env_float("ISTIBAQ_SCORE_PER_MINUTE", 60))
        now = self.now()
        with self._lock:
            q = self._hits[visitor]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                raise LimitHit("Too many requests from this address; wait a minute.",
                               "طلبات كثيرة من هذا العنوان؛ انتظر دقيقة.", retry_after=int(60 - (now - q[0])) + 1)
            q.append(now)
