"""DataForSEO: Google results and sponsored ads, behind hard spend limits.

The account holds about $1 for the whole hackathon, so every limit lives here in code:

- off unless ``ISTIBAQ_DATAFORSEO=1`` (the one switch);
- only the five ad-prone questions marked in ``QUESTIONS`` (``ad_prone=True``);
- a saved answer for the same question and language is reused for 6 hours, free;
- at most 30 paid searches a UTC day, counted in SQLite so a restart does not reset it
  (``ISTIBAQ_DATAFORSEO_DAILY_CAP`` can lower it, never raise it);
- the free balance call runs before every paid search, which is refused if it would
  leave less than the $0.20 reserve kept for the final demo (``ISTIBAQ_DATAFORSEO_RESERVE_USD``);
- standard queue only (``priority`` 1, $0.0006 per search), never live mode or paid extras;
- every paid search goes through ``cost_sink`` at $0.0006 with the balance before and after.

A task that is still queued is kept in the ledger and collected by the next call for the
same question, so a slow queue never pays twice. Nothing here is called by the scheduled
watch round: only the on-demand "Google and ads check" uses it.
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Callable

import httpx

from .base import AdapterError, CostSink, MissingKey, check, env_key, make_client, no_cost
from .search import SearchResult

API = "https://api.dataforseo.com"
COST_PER_SEARCH = 0.0006      # SERP Google Organic, standard queue, depth 10
DAILY_CAP = 30
RESERVE_USD = 0.20
CACHE_HOURS = 6
UAE = 2784
SWITCH = "ISTIBAQ_DATAFORSEO"

Clock = Callable[[], datetime]


class GoogleCheckOff(MissingKey):
    """The switch is off. Subclasses ``MissingKey`` so a round records it as a skip."""


class NotAdProne(ValueError):
    """Only the five ad-prone questions may be searched."""


class SpendRefused(AdapterError):
    """A spend limit (daily cap, balance reserve) stopped a paid search before it was made."""


class StillQueued(AdapterError):
    """The paid task is still in DataForSEO's standard queue; the next call collects it for free."""


def enabled() -> bool:
    return os.environ.get(SWITCH, "").strip() == "1"


def daily_cap() -> int:
    try:
        n = int(os.environ.get("ISTIBAQ_DATAFORSEO_DAILY_CAP", DAILY_CAP))
    except ValueError:
        n = DAILY_CAP
    return max(0, min(n, DAILY_CAP))


def reserve_usd() -> float:
    try:
        return max(0.0, float(os.environ.get("ISTIBAQ_DATAFORSEO_RESERVE_USD", RESERVE_USD)))
    except ValueError:
        return RESERVE_USD


def ad_prone_questions():
    from istibaq.watch.questions import QUESTIONS  # late import: the watch package imports adapters
    return tuple(q for q in QUESTIONS if q.ad_prone)


def _utc(clock: Clock) -> datetime:
    return clock().astimezone(UTC)


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


LEDGER_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS dataforseo_searches (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      query TEXT NOT NULL,
      lang TEXT NOT NULL,
      task_id TEXT,
      status TEXT NOT NULL,          -- pending, done, failed
      cost_usd REAL NOT NULL,
      balance_before REAL,
      balance_after REAL,
      day TEXT NOT NULL,             -- UTC day the search was paid for
      posted_at TEXT NOT NULL,
      finished_at TEXT,
      results_json TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS dataforseo_searches_q ON dataforseo_searches (query, lang, posted_at)",
)


class Ledger:
    """Paid searches in SQLite: the daily count, the 6-hour cache and queued tasks.

    Takes the service's ``Store`` (anything with ``execute``/``one``/``all``).
    """

    def __init__(self, store):
        self.store = store
        for sql in LEDGER_SCHEMA:
            store.execute(sql)

    def paid_today(self, now: datetime) -> int:
        day = now.astimezone(UTC).date().isoformat()
        return self.store.one("SELECT COUNT(*) AS n FROM dataforseo_searches WHERE day=?", (day,))["n"]

    def record_post(self, query: str, lang: str, task_id: str | None, cost: float, balance_before: float,
                    now: datetime, status: str = "pending") -> int:
        return self.store.execute(
            "INSERT INTO dataforseo_searches (query, lang, task_id, status, cost_usd, balance_before, balance_after,"
            " day, posted_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (query, lang, task_id, status, cost, balance_before,
             round(balance_before - cost, 6) if balance_before is not None else None,
             now.astimezone(UTC).date().isoformat(), _iso(now)))

    def cached(self, query: str, lang: str, now: datetime) -> list[dict] | None:
        since = _iso(now - timedelta(hours=CACHE_HOURS))
        row = self.store.one(
            "SELECT results_json FROM dataforseo_searches WHERE query=? AND lang=? AND status='done'"
            " AND finished_at>=? ORDER BY finished_at DESC LIMIT 1", (query, lang, since))
        if row is None:
            return None
        return json.loads(row["results_json"])

    def pending(self, query: str, lang: str, now: datetime) -> dict | None:
        since = _iso(now - timedelta(hours=CACHE_HOURS))
        return self.store.one(
            "SELECT id, task_id FROM dataforseo_searches WHERE query=? AND lang=? AND status='pending'"
            " AND posted_at>=? ORDER BY id DESC LIMIT 1", (query, lang, since))

    def finish(self, row_id: int, results: list[dict], now: datetime, balance_after: float | None) -> None:
        if balance_after is None:
            self.store.execute("UPDATE dataforseo_searches SET status='done', finished_at=?, results_json=? WHERE id=?",
                               (_iso(now), json.dumps(results, ensure_ascii=False), row_id))
        else:
            self.store.execute("UPDATE dataforseo_searches SET status='done', finished_at=?, results_json=?,"
                               " balance_after=? WHERE id=?",
                               (_iso(now), json.dumps(results, ensure_ascii=False), balance_after, row_id))

    def status(self, now: datetime) -> dict:
        last = self.store.one("SELECT balance_after, posted_at FROM dataforseo_searches"
                              " WHERE balance_after IS NOT NULL ORDER BY id DESC LIMIT 1")
        total = self.store.one("SELECT COUNT(*) AS n, COALESCE(SUM(cost_usd),0) AS usd FROM dataforseo_searches"
                               " WHERE status != 'failed'")
        return {"enabled": enabled(), "paid_today": self.paid_today(now), "daily_cap": daily_cap(),
                "reserve_usd": reserve_usd(), "cost_per_search_usd": COST_PER_SEARCH,
                "cache_hours": CACHE_HOURS, "paid_total": total["n"], "spent_usd": round(total["usd"], 6),
                "last_balance": last and last["balance_after"], "last_paid_at": last and last["posted_at"],
                "questions": [{"topic": q.topic, "lang": q.lang, "text": q.text} for q in ad_prone_questions()]}


class GoogleSearch:
    """Google organic results and sponsored ads for the five ad-prone questions (labelled borrowed)."""

    name = "google"

    def __init__(self, ledger: Ledger, client: httpx.Client | None = None, cost_sink: CostSink = no_cost, *,
                 clock: Clock = lambda: datetime.now(UTC), sleep: Callable[[float], None] = time.sleep,
                 wait_seconds: float = 60.0, poll_every: float = 5.0, reserve_usd: float | None = None):
        self.ledger = ledger
        self.client = make_client(client, timeout=30.0)
        self.cost_sink = cost_sink
        self.clock = clock
        self.sleep = sleep
        self.wait_seconds = wait_seconds
        self.poll_every = poll_every
        self.reserve = reserve_usd

    # -------------------------------------------------------------- guards, cheapest first
    def search(self, query: str, lang: str = "en") -> list[SearchResult]:
        if not enabled():
            raise GoogleCheckOff(f"{SWITCH} is not 1; the Google and ads check is switched off")
        if not any(q.text == query and q.lang == lang for q in ad_prone_questions()):
            raise NotAdProne(f"not one of the five ad-prone questions: {query!r} ({lang})")
        now = _utc(self.clock)
        hit = self.ledger.cached(query, lang, now)
        if hit is not None:
            return [SearchResult(**r) for r in hit]
        auth = (env_key("DATAFORSEO_LOGIN"), env_key("DATAFORSEO_PASSWORD"))
        queued = self.ledger.pending(query, lang, now)
        if queued is not None:
            return self._collect(queued["id"], queued["task_id"], query, auth)
        cap = daily_cap()
        if self.ledger.paid_today(now) >= cap:
            raise SpendRefused(f"daily cap reached: {cap} paid Google searches today (limit 30)")
        balance = self._balance(auth)
        reserve = self.reserve if self.reserve is not None else reserve_usd()
        if balance is None or balance - COST_PER_SEARCH < reserve:
            raise SpendRefused(f"balance {balance} would fall below the ${reserve:.2f} reserve kept for the demo")
        return self._post(query, lang, auth, balance, now)

    # -------------------------------------------------------------- calls
    def _balance(self, auth) -> float | None:
        """The free account call: ``tasks[0].result[0].money.balance``."""
        resp = check(self.client.get(f"{API}/v3/appendix/user_data", auth=auth), "dataforseo")
        try:
            value = resp.json()["tasks"][0]["result"][0]["money"]["balance"]
            return float(value) if value is not None else None
        except (KeyError, IndexError, TypeError, ValueError):
            return None

    def _post(self, query, lang, auth, balance, now) -> list[SearchResult]:
        task = [{"keyword": query, "location_code": UAE, "language_code": lang, "device": "desktop",
                 "os": "windows", "depth": 10, "priority": 1, "tag": "istibaq"}]
        try:
            resp = check(self.client.post(f"{API}/v3/serp/google/organic/task_post", json=task, auth=auth),
                         "dataforseo")
            t = resp.json()["tasks"][0]
            if t.get("status_code") != 20100 or not t.get("id"):
                raise AdapterError(f"dataforseo refused the task: {t.get('status_code')} {t.get('status_message')}")
        except Exception:
            # We cannot be sure no charge happened, so the attempt counts against the daily cap.
            self.ledger.record_post(query, lang, None, 0.0, balance, now, status="failed")
            raise
        task_id = t["id"]
        row_id = self.ledger.record_post(query, lang, task_id, COST_PER_SEARCH, balance, now)
        self.cost_sink("dataforseo", COST_PER_SEARCH,
                       {"query": query, "lang": lang, "task_id": task_id, "queue": "standard",
                        "balance_before": balance, "balance_after": round(balance - COST_PER_SEARCH, 6)})
        return self._collect(row_id, task_id, query, auth)

    def _collect(self, row_id: int, task_id: str, query: str, auth) -> list[SearchResult]:
        """Wait (free calls only) for the queued task, then read the advanced result."""
        waited = 0.0
        while True:
            resp = check(self.client.get(f"{API}/v3/serp/google/organic/tasks_ready", auth=auth), "dataforseo")
            ready = [r.get("id") for t in (resp.json().get("tasks") or []) for r in (t.get("result") or [])]
            if task_id in ready:
                break
            if waited >= self.wait_seconds:
                raise StillQueued(f"task {task_id} still queued; ask again later (no new charge)")
            self.sleep(self.poll_every)
            waited += self.poll_every
        resp = check(self.client.get(f"{API}/v3/serp/google/organic/task_get/advanced/{task_id}", auth=auth),
                     "dataforseo")
        t = (resp.json().get("tasks") or [{}])[0]
        if t.get("status_code") != 20000:
            raise StillQueued(f"task {task_id}: {t.get('status_code')} {t.get('status_message')}")
        results = parse_advanced(t, query)
        balance_after = self._balance(auth)
        self.ledger.finish(row_id, [r.to_dict() for r in results], _utc(self.clock), balance_after)
        return results


def _ai_references(item: dict) -> list[dict]:
    """Every source an ``ai_overview`` cites: its own ``references`` and each element's."""
    refs = list(item.get("references") or [])
    for el in item.get("items") or []:
        refs.extend(el.get("references") or [])
    return refs


def parse_advanced(task: dict, query: str) -> list[SearchResult]:
    """``task_get/advanced`` items.

    ``paid`` become ``google_ad`` ads, links cited by Google's AI answer (``ai_overview``)
    become ``google_ai`` results, and ``organic`` become ``google`` results. Other item
    types (knowledge graph, reviews, related searches) are not results.
    """
    out: list[SearchResult] = []
    ads: list[SearchResult] = []
    ai: list[SearchResult] = []
    for res in task.get("result") or []:
        for item in res.get("items") or []:
            kind = item.get("type")
            if kind == "ai_overview":
                for ref in _ai_references(item):
                    link = ref.get("url")
                    if link and link not in {r.link for r in ai}:
                        ai.append(SearchResult("google_ai", "ai_cited", query, len(ai) + 1, ref.get("title") or "",
                                               link, ref.get("source") or ref.get("domain") or "", "borrowed"))
                continue
            url = item.get("url")
            if not url:
                continue
            if kind == "paid":
                snippet = item.get("description") or (item.get("extra") or {}).get("description") or ""
                ads.append(SearchResult("google_ad", "ad", query, item.get("rank_group") or len(ads) + 1,
                                        item.get("title") or "", url, snippet, "borrowed"))
            elif kind == "organic":
                out.append(SearchResult("google", "organic", query, item.get("rank_group") or len(out) + 1,
                                        item.get("title") or "", url, item.get("description") or "", "borrowed"))
    return ads + ai + out
