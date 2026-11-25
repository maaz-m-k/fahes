"""Bridges to other parts' modules (scorer, register, watch, capture, feeds, scorecard).

Each bridge uses the real module when it is installed and otherwise a small, clearly
labelled stand-in so the service runs on its own. Only a *missing* module falls back
(``ModuleNotFoundError``, logged); a module that is present but broken raises, so a bad
deploy is visible instead of silently serving the stand-in. Everything leaves here as
plain dicts.
"""
from __future__ import annotations

import dataclasses
import importlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from istibaq.store.db import now_iso

log = logging.getLogger("istibaq.service")
_warned: set[str] = set()


def _try(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        # Fall back only when the module itself (or a parent package) is missing; a missing
        # dependency inside an installed module is a broken deploy and must raise.
        if not exc.name or not (name == exc.name or name.startswith(exc.name + ".")):
            raise
        if name not in _warned:
            _warned.add(name)
            log.warning("module %s not available (%s); using stand-in", name, exc)
        return None


def to_plain(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "to_dict"):
        return to_plain(obj.to_dict())
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_plain(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------- online facts

def online_facts(facts: dict | None):
    """Turn a plain facts dict (e.g. ``Capture.to_dict()["facts"]``) into ``OnlineFacts``.

    ``ai_reason`` is converted into a ``Reason`` rather than dropped.
    """
    if not facts:
        return None
    contract = _try("istibaq.core.contract") or _try("istibaq.adapters.contract")
    if contract is None:
        return dict(facts)
    fields = {f.name for f in dataclasses.fields(contract.OnlineFacts)}
    kw = {k: v for k, v in facts.items() if k in fields}
    ai = kw.get("ai_reason")
    if isinstance(ai, dict):
        rf = {f.name for f in dataclasses.fields(contract.Reason)}
        kw["ai_reason"] = contract.Reason(**{k: v for k, v in ai.items() if k in rf})
    return contract.OnlineFacts(**kw)


# ---------------------------------------------------------------- scorer

_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "rb.gy", "t.ly"}
_BRANDS = {"tamm": "TAMM", "adpolice": "Abu Dhabi Police", "adcb": "ADCB", "emiratesnbd": "Emirates NBD",
           "etisalat": "e&"}
_OFFICIAL = {"tamm.abudhabi", "adpolice.gov.ae", "abudhabi.gov.ae", "icp.gov.ae", "adcb.com",
             "bankfab.com", "emiratesnbd.com", "u.ae"}


def _standin_score(link: str, mode: str = "judging", online: Any = None) -> dict:
    """Very small heuristic used only when the real scorer is not installed."""
    host = link.strip().lower().split("://")[-1].split("/")[0].split("\\")[0].split("?")[0].removeprefix("www.")
    t = now_iso()
    reasons: list[dict] = []
    if any(host == d or host.endswith("." + d) for d in _OFFICIAL):
        return {"link": link, "verdict": "green", "is_fraud": False, "score": 0.0,
                "reasons": [{"code": "register_official", "ar": "موقع رسمي مسجل", "en": "Official registered site",
                             "evidence": {"host": host}, "time": t, "online": False}],
                "model_version": "standin-0", "scored_at": t}
    if host in _SHORTENERS:
        reasons.append({"code": "short_link", "ar": "رابط مختصر، الوجهة غير معروفة",
                        "en": "Short link, destination unknown", "evidence": {"host": host}, "time": t, "online": False})
    for word, brand in _BRANDS.items():
        if word in host.replace("-", "").replace(".", ""):
            reasons.append({"code": "brand_mismatch", "ar": f"يشبه علامة {brand} على نطاق غير مملوك لها",
                            "en": f"Looks like {brand} on a domain it does not own",
                            "evidence": {"brand": brand, "host": host}, "time": t, "online": False})
            break
    if host.count("-") >= 2 or any(k in host for k in ("pay", "fine", "login", "verify")):
        reasons.append({"code": "suspicious_words", "ar": "كلمات مشبوهة في العنوان",
                        "en": "Suspicious words in the address", "evidence": {"host": host}, "time": t, "online": False})
    facts = to_plain(online) if online is not None else {}
    if isinstance(facts, dict) and facts.get("two_view_difference"):
        reasons.append({"code": "two_view_difference", "ar": "الصفحة تظهر بشكل مختلف للهاتف والخادم",
                        "en": "Page differs between phone and server views",
                        "evidence": {"difference": facts["two_view_difference"]}, "time": t, "online": True})
    score = min(1.0, 0.45 * len(reasons) + (0.1 if reasons else 0.0))
    verdict = "red" if len(reasons) >= 2 and score >= 0.9 else "grey"
    return {"link": link, "verdict": verdict, "is_fraud": verdict == "red", "score": round(score, 3),
            "reasons": reasons, "model_version": "standin-0", "scored_at": t}


def score(link: str, mode: str = "judging", online: Any = None, reviewer: Any = None) -> dict:
    """``reviewer``: the optional AI second opinion (``Reviewer``); it never raises and falls back to pure code."""
    if isinstance(online, dict):
        online = online_facts(online)
    mod = _try("istibaq.core.scorer")
    if mod is not None:
        v = mod.score(link, mode=mode, online=online)
        if reviewer is not None:
            v = reviewer.review([v], mode)[0]
        return to_plain(v)
    return _standin_score(link, mode, online)


def score_many(links: list[str], mode: str = "judging", reviewer: Any = None) -> list[dict]:
    mod = _try("istibaq.core.scorer")
    if mod is not None:
        vs = mod.score_many(links, mode=mode)
        if reviewer is not None:
            vs = reviewer.review(vs, mode)
        return to_plain(vs)
    return [_standin_score(link, mode) for link in links]


def ai_reviewer(store, cost_sink, client=None):
    """The live AI second opinion when ``ISTIBAQ_AI_SECOND=1`` (needs ``OPENROUTER_API_KEY``), else None.

    Frozen model and policy, answers cached by address (``ISTIBAQ_AI_CACHE``), every call in the cost log, and a
    daily cap (``ISTIBAQ_AI_DAILY_USD``, default $1) read from that log; above it, scoring is pure code."""
    if os.environ.get("ISTIBAQ_AI_SECOND", "0") != "1":
        return None
    from istibaq.adapters.second_opinion import OpinionCache, Reviewer

    def spent_today() -> float:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = store.one("SELECT COALESCE(SUM(amount_usd), 0) AS s FROM costs WHERE service='openrouter' "
                        "AND at LIKE ? AND detail_json LIKE '%second_opinion%'", (day + "%",))
        return float(row["s"] or 0.0)

    cache = os.environ.get("ISTIBAQ_AI_CACHE") or os.path.join(
        os.path.dirname(os.path.abspath(store.path)) if getattr(store, "path", None) else ".", "ai_cache.jsonl")
    try:
        cap = float(os.environ.get("ISTIBAQ_AI_DAILY_USD", "1.0"))
    except ValueError:
        cap = 1.0
    return Reviewer(client=client, cost_sink=cost_sink, cache=OpinionCache(cache), max_usd_per_day=cap,
                    spent_today=spent_today)


def scorer_status() -> str:
    return "live" if _try("istibaq.core.scorer") else "stand-in"


def model_version() -> str:
    return score("https://health-check.example/", mode="judging")["model_version"]


# ---------------------------------------------------------------- register

def register_lookup(address: str) -> dict:
    mod = _try("istibaq.core.register")
    if mod is not None:
        return to_plain(mod.lookup(address))
    v = _standin_score(address)
    return {"status": "official" if v["verdict"] == "green" else "unknown", "family": None,
            "evidence": {"standin": True}}


def register_apply_edit(address: str, status: str, source: str, note: str | None) -> bool:
    """Apply an edit through the real register. Raises ``ValueError`` on a status it refuses."""
    mod = _try("istibaq.core.register")
    if mod is not None:
        mod.apply_edit(address, status, source, note)
        return True
    return False


# ---------------------------------------------------------------- optional AI layer

def ai_page_facts(link: str, page_text: str) -> dict:
    """Ask the optional AI layer (``ISTIBAQ_AI_LAYER=1`` and ``OPENROUTER_API_KEY``) which brand a captured
    page claims, and for its one added reason. Off, or on any failure: no facts. The register, not the
    model, decides whether the address belongs to the claimed brand."""
    mod = _try("istibaq.adapters.openrouter")
    if mod is None or not mod.enabled() or not page_text.strip():
        return {}
    try:
        ai = mod.AILayer()
        reason = ai.describe(link, page_text)
        out: dict = {"live_page_brand": ai.last_claim} if ai.last_claim else {}
        if reason is not None:
            out["ai_reason"] = reason.to_dict()
        return out
    except Exception as exc:  # the AI layer is optional; never fatal and never evidence when it fails
        log.warning("AI layer failed: %s", type(exc).__name__)
        return {}


# ---------------------------------------------------------------- watch and capture

WatchRound = Callable[[Callable], Any]          # (cost_sink) -> Round
CaptureFn = Callable[[str, str], Any]           # (link, out_dir) -> Capture


def default_watch_round() -> WatchRound | None:
    watch = _try("istibaq.watch")
    search = _try("istibaq.adapters.search")
    if watch is None or search is None:
        return None

    def run(cost_sink, client=None):
        # Brave and Places only: the paid Google check (DataForSEO) is never automatic.
        return watch.run_round([search.BraveSearch(client=client, cost_sink=cost_sink)],
                               maps=search.PlacesSearch(client=client, cost_sink=cost_sink), mode="officer")
    return run


GOOGLE_WAIT_SECONDS = 20  # per question; a task still queued is collected free by the next check


def default_google_round(store) -> Callable | None:
    """The on-demand Google and ads check (DataForSEO): the five ad-prone questions only.

    Never part of :func:`default_watch_round`; the scheduled round uses Brave and Places only.
    """
    watch = _try("istibaq.watch")
    dfs = _try("istibaq.adapters.dataforseo")
    if watch is None or dfs is None:
        return None
    ledger = dfs.Ledger(store)

    def run(cost_sink, client=None):
        google = dfs.GoogleSearch(ledger, client=client, cost_sink=cost_sink, wait_seconds=GOOGLE_WAIT_SECONDS)
        return watch.run_round([google], questions=dfs.ad_prone_questions(), mode="officer")
    return run


def google_status(store) -> dict:
    """Limits and spend so far, from the ledger only (no external call)."""
    dfs = _try("istibaq.adapters.dataforseo")
    if dfs is None:
        return {"enabled": False, "status": "unavailable"}
    from datetime import UTC, datetime
    return dfs.Ledger(store).status(datetime.now(UTC))


def google_enabled() -> bool:
    dfs = _try("istibaq.adapters.dataforseo")
    return bool(dfs and dfs.enabled())


def ad_prone_count() -> int:
    dfs = _try("istibaq.adapters.dataforseo")
    return len(dfs.ad_prone_questions()) if dfs else 0


# ---------------------------------------------------------------- public scam lists (OpenPhish, PhishTank)

PHISH_PER_ROUND = 10


def default_phish_feed(client=None) -> Callable | None:
    """Fresh links from public scam lists, each round (off with ISTIBAQ_PUBLIC_LISTS=0)."""
    import os
    if os.environ.get("ISTIBAQ_PUBLIC_LISTS", "1") == "0":
        return None
    mod = _try("istibaq.adapters.phishfeed")
    if mod is None:
        return None
    limit = int(os.environ.get("ISTIBAQ_PUBLIC_LISTS_PER_ROUND", PHISH_PER_ROUND))
    return lambda seen: mod.fetch(client=client, limit=limit, seen=seen)


def note_known_bad(links: list[str], lists: list[str]) -> None:
    """Hosts the public lists name now give the scorer's known-bad reason, credited to their list."""
    from urllib.parse import urlsplit
    reasons = _try("istibaq.core.reasons")
    feed = _try("istibaq.adapters.phishfeed")
    if reasons is None or feed is None or not hasattr(reasons, "add_known_bad"):
        return
    for link, name in zip(links, lists):
        host = (urlsplit(link).hostname or "").lower()
        reasons.add_known_bad([host], feed.CREDIT.get(name, name), now_iso())
    scorer = _try("istibaq.core.scorer")
    if scorer is not None and hasattr(scorer, "_score_offline"):
        scorer._score_offline.cache_clear()


def default_capture() -> CaptureFn | None:
    mod = _try("istibaq.capture")
    if mod is None:
        return None

    def run(link: str, out_dir: str):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return mod.capture(link, out_dir=out_dir)
    return run


# ---------------------------------------------------------------- feeds (cached ~10 minutes)

FEED_TTL_SECONDS = 600
_feed_cache: dict[str, Any] = {"at": 0.0, "value": None}
_feed_lock = threading.Lock()


def feed_counts(cost_sink: Callable | None = None, client=None, refresh: bool = False) -> dict:
    feeds = _try("istibaq.feeds")
    ct = _try("istibaq.adapters.ct")
    nrd = _try("istibaq.adapters.nrd")
    if feeds is None or ct is None or nrd is None:
        return {"status": "unavailable", "note_en": "Feeds module not deployed yet", "note_ar": "وحدة البث غير مفعلة بعد"}
    with _feed_lock:
        if not refresh and _feed_cache["value"] and time.monotonic() - _feed_cache["at"] < FEED_TTL_SECONDS:
            return _feed_cache["value"]
        sink_kw = {"cost_sink": cost_sink} if cost_sink else {}
        out: dict[str, Any] = {"status": "live", "at": now_iso()}
        for key, fn in (("certificates", lambda: feeds.certificate_count(ct.CTReader(client=client, **sink_kw))),
                        ("new_domains", lambda: feeds.new_domain_count(nrd.NewDomains(client=client, **sink_kw)))):
            try:
                out[key] = to_plain(fn())
            except Exception as exc:  # a feed being down is reported, never invented
                log.warning("feed %s failed: %s", key, exc)
                out[key] = {"status": "error", "error": type(exc).__name__}
        _feed_cache.update(at=time.monotonic(), value=out)
        return out


HIDDEN = "••• (مخفي / hidden)"


def mask_feed_names(feeds: dict, reveal: bool = False) -> dict:
    """Grey look-alikes are not named unless an officer asks (token + reveal=true)."""
    if reveal or not isinstance(feeds, dict):
        return feeds
    out = dict(feeds)
    for key in ("certificates", "new_domains"):
        feed = out.get(key)
        if isinstance(feed, dict) and isinstance(feed.get("lookalikes"), list):
            out[key] = {**feed, "lookalikes": [
                {**h, "name": HIDDEN} if isinstance(h, dict) and h.get("verdict") != "red" else h
                for h in feed["lookalikes"]]}
    return out


def feeds_status() -> str:
    """Status without fetching anything: cached result if fresh, else whether the module is installed."""
    cached = _feed_cache["value"]
    if cached and time.monotonic() - _feed_cache["at"] < FEED_TTL_SECONDS:
        return cached["status"]
    return "live" if _try("istibaq.feeds") else "unavailable"


def scorecard() -> dict:
    mod = _try("istibaq.eval.scorecard")
    if mod is not None:
        data = mod.load()
        if data is not None:
            return {"status": "live", "scorecard": to_plain(data)}
    return {"status": "unavailable", "note_en": "No sealed scorecard yet", "note_ar": "لا توجد بطاقة دقة مختومة بعد"}


def register_families(q: str = "", limit: int = 40) -> dict:
    """The register's families (official bodies and their addresses), for the desk's Register page."""
    from istibaq.core import register
    q = (q or "").strip().lower()
    fams = register.families()
    out = []
    for f in fams:
        if q and not (q in f.name_en.lower() or q in f.name_ar or any(q in d for d in f.domains)):
            continue
        out.append({"id": f.family, "name_ar": f.name_ar, "name_en": f.name_en, "domains": list(f.domains),
                    "official": f.official, "source": f.source, "date": f.date})
    return {"total": sum(len(f.domains) for f in fams), "families": out[:limit], "count": len(out)}
