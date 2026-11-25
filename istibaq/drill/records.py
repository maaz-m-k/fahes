"""Readiness drill records: our own harmless page, when published and when found."""
from __future__ import annotations

from datetime import datetime
from statistics import median

from istibaq.store.db import Store


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def add(store: Store, address: str, published_at: str, found_at: str | None = None,
        feed: str | None = None, note: str | None = None) -> int:
    return store.execute(
        "INSERT INTO drills (address, published_at, found_at, feed, note) VALUES (?,?,?,?,?)",
        (address, published_at, found_at, feed, note),
    )


def mark_found(store: Store, drill_id: int, found_at: str, feed: str) -> None:
    store.execute("UPDATE drills SET found_at=?, feed=? WHERE id=?", (found_at, feed, drill_id))


def report(store: Store) -> dict:
    rows = store.all("SELECT * FROM drills ORDER BY id")
    mins = []
    for r in rows:
        if r["found_at"]:
            r["minutes_to_find"] = round((_parse(r["found_at"]) - _parse(r["published_at"])).total_seconds() / 60, 1)
            mins.append(r["minutes_to_find"])
        else:
            r["minutes_to_find"] = None
    return {
        "drills": rows,
        "found": len(mins),
        "median_minutes": median(mins) if mins else None,
        "slowest_minutes": max(mins) if mins else None,
    }
