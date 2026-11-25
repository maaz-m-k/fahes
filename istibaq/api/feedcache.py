"""The scale numbers, counted in the background and served at once.

Counting the live feeds takes minutes on a cold server (a day's list of new names is downloaded and
scored), so it never happens on a request. The server counts at start and then every hour, keeps the
last numbers in memory and in a JSON file on the volume (so a restart answers at once with the last
known numbers), and every request gets the cache plus "updated N minutes ago". Right after a first
start, before anything was counted, the answer is a short "warming up".
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger("istibaq.feedcache")

EVERY_SECONDS = int(os.environ.get("ISTIBAQ_FEEDS_EVERY", "3600"))
WARMING = {"status": "warming",
           "note_en": "The numbers are still being counted after the server started; ready in a few minutes.",
           "note_ar": "الأرقام قيد العدّ بعد تشغيل الخادم، تجهز خلال دقائق."}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FeedCache:
    def __init__(self, compute: Callable[[], dict], path: str | Path | None = None, every: int = EVERY_SECONDS,
                 clock: Callable[[], float] = time.time):
        self.compute, self.every, self.clock = compute, every, clock
        self.path = Path(path) if path else None
        self.value: dict | None = None
        self.at: float | None = None
        self.busy = False
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if self.path and self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.value, self.at = saved["value"], float(saved["at"])
            except Exception as exc:  # a broken file only means we count again
                log.warning("feed cache file unreadable: %s", exc)

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"at": self.at, "value": self.value}), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            log.warning("feed cache not saved: %s", exc)

    def stale(self) -> bool:
        return self.at is None or self.clock() - self.at >= self.every

    def refresh(self) -> None:
        """Count now (blocking). Only one count runs at a time; a failed count keeps the last numbers."""
        with self._lock:
            if self.busy:
                return
            self.busy = True
        try:
            v = self.compute()
            if isinstance(v, dict) and v.get("status") != "error":
                self.value, self.at = v, self.clock()
                self._save()
        except Exception as exc:
            log.warning("feed count failed: %s", exc)
        finally:
            self.busy = False

    def refresh_soon(self) -> None:
        if not self.busy:
            threading.Thread(target=self.refresh, daemon=True, name="feed-count").start()

    def get(self) -> dict:
        """At once: the last numbers with their age, or "warming". A stale cache starts a count in the background."""
        if self.stale():
            self.refresh_soon()
        if self.value is None:
            return {**WARMING, "refreshing": True}
        mins = int(max(0.0, self.clock() - (self.at or 0)) // 60)
        return {**self.value, "updated_at": _iso(self.at or 0), "updated_minutes_ago": mins, "refreshing": self.busy}

    async def loop(self) -> None:
        """Count at start, then every ``every`` seconds."""
        import asyncio
        while True:
            if self.stale():
                await asyncio.to_thread(self.refresh)
            await asyncio.sleep(max(60, min(self.every, (self.at or 0) + self.every - self.clock())))
