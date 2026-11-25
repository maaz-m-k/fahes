"""Cost log: the real ``cost_sink`` and summaries/projections."""
from __future__ import annotations

from typing import Callable

from istibaq.store.db import Store, dumps, loads, now_iso

CostSink = Callable[[str, float, dict], None]

# Fixed machine cost estimate (one shared-cpu-1x 1GB Fly machine + 1GB volume), USD per month.
MACHINE_USD_PER_MONTH = 6.0


def make_sink(store: Store) -> CostSink:
    def sink(service: str, amount_usd: float, detail: dict) -> None:
        store.execute(
            "INSERT INTO costs (service, amount_usd, detail_json, at) VALUES (?,?,?,?)",
            (service, float(amount_usd), dumps(detail or {}), now_iso()),
        )
    return sink


def entries(store: Store, limit: int = 200) -> list[dict]:
    rows = store.all("SELECT * FROM costs ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["detail"] = loads(r.pop("detail_json"))
    return rows


def summary(store: Store, runs_per_day: float = 4.0) -> dict:
    by_service = store.all(
        "SELECT service, COUNT(*) AS calls, ROUND(SUM(amount_usd), 6) AS usd FROM costs GROUP BY service ORDER BY usd DESC"
    )
    total = sum(r["usd"] or 0 for r in by_service)
    runs = store.one("SELECT COUNT(*) AS n FROM watch_runs WHERE finished_at IS NOT NULL")["n"]
    watch_usd = store.one(
        "SELECT COALESCE(SUM(amount_usd),0) AS s FROM costs WHERE service IN ('brave','places','openrouter')"
    )["s"]
    per_run = (watch_usd / runs) if runs else 0.0
    monthly = per_run * runs_per_day * 30 + MACHINE_USD_PER_MONTH
    return {
        "total_usd": round(total, 6),
        "by_service": by_service,
        "watch_runs": runs,
        "watch_usd_per_run": round(per_run, 6),
        "projection": {
            "runs_per_day": runs_per_day,
            "machine_usd_per_month": MACHINE_USD_PER_MONTH,
            "monthly_usd": round(monthly, 2),
            "note_en": "Watch cost per run so far x runs per day x 30, plus machine; realtime voice minutes extra.",
            "note_ar": "كلفة الجولة حتى الآن × عدد الجولات يومياً × 30، مضافاً إليها الخادم؛ دقائق الصوت تُحسب منفصلة.",
        },
    }
