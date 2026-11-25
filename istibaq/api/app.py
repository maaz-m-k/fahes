"""Istibaq engine HTTP API (FastAPI). Run: ``uvicorn istibaq.api.app:create_app --factory``."""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from istibaq import __version__
from istibaq.api import integrations, limits, watchrun
from istibaq.cases import service as cases
from istibaq.costs import log as costlog
from istibaq.drill import records as drills
from istibaq.store.db import Store, now_iso
from istibaq.voice import mint as voice

PAGE = Path(__file__).with_name("page.html")
WATCH_EVERY_SECONDS = 6 * 3600
TOKEN_HEADER = "X-Istibaq-Officer-Token"
# The desk is open to the public (no passcode); hard limits bound the risk (istibaq/api/limits.py).
# The officer token is only for maintenance: these admin endpoints change shared data by hand.
ADMIN = {("POST", "/api/register/edits"), ("POST", "/api/drills"), ("POST", "/api/costs")}
WEB_DIST = Path(os.environ.get("ISTIBAQ_WEB_DIST", str(Path(__file__).resolve().parents[2] / "web" / "dist")))
log = logging.getLogger("istibaq.service")
Mode = Literal["judging", "officer"]


class ScoreOne(BaseModel):
    link: str
    mode: Mode = "judging"


class ScoreMany(BaseModel):
    links: list[str] = Field(max_length=5000)
    mode: Mode = "judging"


class OpenCase(BaseModel):
    link: str
    source: str = "manual"


class Approve(BaseModel):
    method: Literal["voice", "click"] = "click"
    officer: str = "duty-officer"


class Mark(BaseModel):
    status: Literal["not_scam", "licensed"]
    officer: str = "duty-officer"
    note: str | None = None


class RegisterEdit(BaseModel):
    address: str
    status: Literal["not_scam", "licensed"]
    source: str
    note: str | None = None


class DrillIn(BaseModel):
    address: str
    published_at: str
    found_at: str | None = None
    feed: str | None = None
    note: str | None = None


class CostIn(BaseModel):
    service: str
    amount_usd: float
    detail: dict = {}


class VerifyIn(BaseModel):
    address: str | None = None


class VoiceUsage(BaseModel):
    session_id: int | None = None
    seconds: float | None = None
    model: str | None = None


class ToolCall(BaseModel):
    case_id: int | None = None
    address: str | None = None
    run_id: int | None = None
    officer: str = "duty-officer"
    reveal: bool = False


def create_app(db_path: str | None = None, *, schedule: bool | None = None,
               watch_round: Callable | None | Literal["default"] = "default",
               capture: Callable | None | Literal["default"] = "default",
               openai_transport: httpx.BaseTransport | None = None,
               feeds: Callable[[], dict] | Literal["default"] = "default",
               google_client: httpx.Client | None = None) -> FastAPI:
    store = Store(db_path)
    sink = costlog.make_sink(store)
    wr = integrations.default_watch_round() if watch_round == "default" else watch_round
    cap = integrations.default_capture() if capture == "default" else capture
    google_round = integrations.default_google_round(store)
    feed_counts = (lambda: integrations.feed_counts(sink)) if feeds == "default" else feeds
    if schedule is None:
        schedule = os.environ.get("ISTIBAQ_SCHEDULE", "0") == "1"
    state = {"next_run_at": None, "last_error": None}

    async def scheduler():
        delay = float(os.environ.get("ISTIBAQ_FIRST_RUN_DELAY", "60"))
        while True:
            await asyncio.sleep(delay)
            try:
                await asyncio.to_thread(watchrun.run_round, store, wr, cap, sink, "schedule")
            except Exception as exc:
                state["last_error"] = type(exc).__name__
            delay = WATCH_EVERY_SECONDS

    @asynccontextmanager
    async def lifespan(_app):
        cases.reapply_register_edits(store)
        task = asyncio.create_task(scheduler()) if schedule else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Istibaq engine", version=__version__, lifespan=lifespan)
    app.state.store = store
    lim = limits.Limits(store)
    app.state.limits = lim

    def visitor(request: Request) -> str:
        fwd = request.headers.get("fly-client-ip") or request.headers.get("x-forwarded-for", "")
        return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")

    def limited(exc: limits.LimitHit) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse(exc.to_dict(), status_code=429, headers=headers)

    @app.middleware("http")
    async def officer_token(request: Request, call_next):
        if (request.method, request.url.path) in ADMIN:
            expected = os.environ.get("ISTIBAQ_OFFICER_TOKEN", "")
            given = request.headers.get(TOKEN_HEADER, "")
            if not expected:
                return JSONResponse({"detail": "officer token not configured on the server"}, status_code=503)
            if not hmac.compare_digest(given.encode(), expected.encode()):
                return JSONResponse({"detail": "officer token required"}, status_code=401)
        return await call_next(request)

    def nf(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except cases.NotFound:
            raise HTTPException(404, "case not found")
        except cases.Invalid as exc:
            raise HTTPException(409, str(exc))

    # ---------------------------------------------------------------- health and page
    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "time": now_iso(), "scorer": integrations.scorer_status(),
                "model_version": integrations.model_version(),
                "watch": "live" if wr else "unavailable", "capture": "live" if cap else "unavailable",
                "schedule": schedule}

    @app.get("/engine", response_class=HTMLResponse)
    def engine_page():
        return PAGE.read_text(encoding="utf-8")

    if not (WEB_DIST / "index.html").exists():  # no built desk: the engine's own page at /
        @app.get("/", response_class=HTMLResponse)
        def page():
            return PAGE.read_text(encoding="utf-8")

    # ---------------------------------------------------------------- the Fahes search page (recorded footage)
    @app.get("/search", response_class=HTMLResponse)
    def search_home(lang: str = "ar"):
        from istibaq.capture import searchpage
        return searchpage.render_home(lang)

    @app.get("/search/results", response_class=HTMLResponse)
    def search_results(request: Request, q: str = Query("", max_length=300), maps: bool = False, lang: str = "ar"):
        """Real live results from the search adapters, each with Fahes's verdict chip.

        Paid searches, so the officer token is required (the recorder sends it as a header)."""
        expected = os.environ.get("ISTIBAQ_OFFICER_TOKEN", "")
        if not expected or not hmac.compare_digest(request.headers.get(TOKEN_HEADER, "").encode(), expected.encode()):
            raise HTTPException(401, "officer token required")
        from istibaq.adapters.base import AdapterError, MissingKey
        from istibaq.capture import searchpage
        if not limits.paid_on():
            return searchpage.render_results(q, [], label="Paid searches are switched off (ISTIBAQ_PAID=0)", lang=lang)
        try:
            results = searchpage.live_results(q, maps=maps, lang=lang, cost_sink=sink) if q.strip() else []
            label = "Real results · Fahes search page"
        except (MissingKey, AdapterError, OSError) as exc:
            results, label = [], f"No live results: {type(exc).__name__}"
        return searchpage.render_results(q, results, label=label, lang=lang)

    # ---------------------------------------------------------------- scoring
    @app.post("/api/score")
    def score_one(body: ScoreOne, request: Request):
        try:
            lim.hit(visitor(request))
        except limits.LimitHit as exc:
            return limited(exc)
        return integrations.score(body.link, mode=body.mode)

    @app.post("/api/score/batch")
    def score_batch(body: ScoreMany, request: Request):
        try:
            lim.hit(visitor(request))
        except limits.LimitHit as exc:
            return limited(exc)
        links = [l.strip() for l in body.links if l.strip()]
        if len(links) > limits.batch_max():
            raise HTTPException(413, f"at most {limits.batch_max()} links per request")
        return {"results": integrations.score_many(links, mode=body.mode), "count": len(links)}

    # ---------------------------------------------------------------- register
    @app.get("/api/register/lookup")
    def register_lookup(address: str):
        return integrations.register_lookup(address)

    @app.post("/api/register/edits")
    def register_edit(body: RegisterEdit):
        try:
            return cases.add_register_edit(store, body.address, body.status, body.source, body.note)
        except cases.Invalid as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/register/edits")
    def register_edits():
        return store.all("SELECT * FROM register_edits ORDER BY id DESC")

    # ---------------------------------------------------------------- cases
    @app.get("/api/cases")
    def list_cases(reveal: bool = False, status: str | None = None):
        return cases.list_cases(store, reveal=reveal, status=status)

    @app.post("/api/cases")
    def open_case(body: OpenCase):
        verdict = integrations.score(body.link, mode="officer")
        return {"id": cases.open_case(store, verdict, source=body.source), "verdict": verdict}

    @app.get("/api/cases/{case_id}")
    def show_case(case_id: int, reveal: bool = False):
        return nf(cases.show, store, case_id, reveal=reveal)

    @app.post("/api/cases/{case_id}/capture")
    def capture_case(case_id: int):
        if cap is None:
            raise HTTPException(503, "capture module not deployed")
        return nf(watchrun.capture_case, store, case_id, cap)

    @app.post("/api/cases/{case_id}/seal")
    def seal_case(case_id: int):
        return nf(cases.seal, store, case_id)

    @app.post("/api/cases/{case_id}/verify")
    def verify_record(case_id: int, body: VerifyIn):
        """Would the seal still hold if the record's address read like this? (the desk's "edit one letter" check)"""
        from istibaq.seal import record as seal_record
        rec = nf(cases.show, store, case_id, reveal=True).get("record")
        if not rec:
            raise HTTPException(409, "not sealed")
        edited = {**rec["body"], "address": body.address if body.address is not None else rec["body"].get("address")}
        out = seal_record.verify(edited, rec["sha256"])
        return {**out, "fingerprint_now": seal_record.fingerprint(edited)}

    @app.post("/api/cases/{case_id}/approve")
    def approve_case(case_id: int, body: Approve):
        return nf(cases.approve, store, case_id, body.method, body.officer)

    @app.post("/api/cases/{case_id}/mark")
    def mark_case(case_id: int, body: Mark):
        return nf(cases.mark, store, case_id, body.status, body.officer, body.note)

    @app.get("/api/cases/{case_id}/takedown")
    def takedown(case_id: int):
        return nf(cases.takedown_package, store, case_id)

    # ---------------------------------------------------------------- watch
    def run_now(trigger: str, wait: bool = True) -> dict:
        """Run a round now (off with ISTIBAQ_PAID=0); ``wait=False`` starts it in the background."""
        if not limits.paid_on():
            return {"status": "off", "note_en": "Paid searches are switched off on this server (ISTIBAQ_PAID=0)",
                    "note_ar": "عمليات البحث المدفوعة متوقفة على هذا الخادم", "results": 0, "cases": []}
        if wait:
            return watchrun.run_round(store, wr, cap, sink, trigger=trigger)
        import threading
        threading.Thread(target=watchrun.run_round, args=(store, wr, cap, sink, trigger), daemon=True).start()
        return {"status": "started"}

    @app.post("/api/watch/run")
    def watch_run(wait: bool = True):
        try:
            return run_now("manual", wait)
        except limits.LimitHit as exc:
            return limited(exc)

    @app.get("/api/watch/last")
    def watch_last():
        return watchrun.get_run(store) or {"status": "none"}

    @app.get("/api/watch/runs/{run_id}/replay")
    def watch_replay(run_id: int, reveal: bool = False):
        run = watchrun.get_run(store, run_id)
        if not run:
            raise HTTPException(404, "run not found")
        return {"run": run, "steps": watchrun.replay(store, run_id, reveal=reveal)}

    @app.get("/api/watch/schedule")
    def watch_schedule():
        return {"enabled": schedule, "every_hours": WATCH_EVERY_SECONDS / 3600, "last_error": state["last_error"]}

    # ---------------------------------------------------------------- Google and ads check (paid, on demand only)
    def google_check() -> dict:
        if not limits.paid_on():
            return {"status": "off", "note_en": "Paid searches are switched off on this server (ISTIBAQ_PAID=0)",
                    "note_ar": "عمليات البحث المدفوعة متوقفة", "google": integrations.google_status(store)}
        if google_round is None:
            return {"status": "unavailable", "google": integrations.google_status(store)}
        if not integrations.google_enabled():
            return {"status": "off", "note_en": "Google and ads check is switched off (ISTIBAQ_DATAFORSEO)",
                    "note_ar": "فحص جوجل والإعلانات متوقف", "google": integrations.google_status(store)}
        out = watchrun.run_round(store, lambda s: google_round(s, client=google_client), cap, sink,
                                 trigger="google_check")
        return {**out, "questions": integrations.ad_prone_count(), "google": integrations.google_status(store)}

    @app.post("/api/google/check")
    def google_check_endpoint():
        return google_check()

    @app.get("/api/google/status")
    def google_status():
        return integrations.google_status(store)

    # ---------------------------------------------------------------- feeds, drill, scorecard, costs
    @app.get("/api/feeds")
    def feeds(reveal: bool = False):
        return integrations.mask_feed_names(feed_counts(), reveal)

    @app.get("/api/drills")
    def drill_report():
        return drills.report(store)

    @app.post("/api/drills")
    def drill_add(body: DrillIn):
        return {"id": drills.add(store, **body.model_dump())}

    @app.get("/api/scorecard")
    def scorecard():
        return integrations.scorecard()

    @app.get("/api/costs")
    def costs(runs_per_day: float = Query(4.0, ge=0, le=96)):
        return {"summary": costlog.summary(store, runs_per_day), "entries": costlog.entries(store, 50)}

    @app.post("/api/costs")
    def cost_add(body: CostIn):
        sink(body.service, body.amount_usd, body.detail)
        return {"ok": True}

    # ---------------------------------------------------------------- agents and summary
    def agents_status() -> list[dict]:
        last = watchrun.get_run(store)
        sealed = store.one("SELECT COUNT(*) n FROM records")["n"]
        dr = drills.report(store)
        feeds_status = integrations.feeds_status()
        return [
            {"agent": "watch", "status": "live" if wr else "unavailable",
             "last_run_at": last and last["started_at"]},
            {"agent": "register", "status": integrations.scorer_status(),
             "edits": store.one("SELECT COUNT(*) n FROM register_edits")["n"]},
            {"agent": "check", "status": integrations.scorer_status()},
            {"agent": "capture", "status": "live" if cap else "unavailable"},
            {"agent": "seal", "status": "live", "sealed_records": sealed},
            {"agent": "drill", "status": "live", "drills": len(dr["drills"]), "median_minutes": dr["median_minutes"]},
            {"agent": "scale", "status": feeds_status},
        ]

    def summary() -> dict:
        by = {r["status"]: r["n"] for r in store.all("SELECT status, COUNT(*) n FROM cases GROUP BY status")}
        by_verdict = {r["verdict"]: r["n"] for r in
                      store.all("SELECT verdict, COUNT(*) n FROM cases WHERE status='open' GROUP BY verdict")}
        return {"cases_by_status": by, "open_by_verdict": by_verdict, "last_run": watchrun.get_run(store),
                "cost_usd": costlog.summary(store)["total_usd"], "time": now_iso()}

    @app.get("/api/agents")
    def agents():
        return agents_status()

    @app.get("/api/summary")
    def get_summary():
        return summary()

    # ---------------------------------------------------------------- voice
    @app.post("/api/voice/session")
    def voice_session():
        """A short-lived voice key (off with ISTIBAQ_VOICE=0); each session is counted for the cost view."""
        try:
            sid = lim.start_voice()
        except limits.LimitHit as exc:
            return limited(exc)
        try:
            out = voice.mint(cost_sink=sink, transport=openai_transport)
        except voice.VoiceUnavailable as exc:
            lim.end_voice(sid, 0)
            raise HTTPException(503, f"voice unavailable: {exc}")
        return {**out, "session_id": sid}

    @app.post("/api/voice/usage")
    def voice_usage(body: VoiceUsage):
        lim.end_voice(body.session_id, body.seconds or 0)
        return lim.voice_status()

    @app.get("/api/voice/status")
    def voice_status():
        return lim.voice_status()

    @app.get("/api/register/families")
    def register_families(q: str = Query("", max_length=100)):
        return integrations.register_families(q)

    @app.post("/api/voice/tools/{name}")
    def voice_tool(name: str, body: ToolCall):
        def need_case():
            if body.case_id is None:
                raise HTTPException(422, "case_id required")
            return body.case_id
        if name == "summary":
            return summary()
        if name == "show_case":
            return nf(cases.show, store, need_case())
        if name == "check_address":
            if not body.address:
                raise HTTPException(422, "address required")
            return integrations.score(body.address, mode="officer")
        if name == "show_run":
            run = watchrun.get_run(store, body.run_id)
            return {"run": run, "steps": watchrun.replay(store, run["id"]) if run else []}
        if name == "seal":
            return nf(cases.seal, store, need_case())
        if name == "approve":
            return nf(cases.approve, store, need_case(), "voice", body.officer)
        if name == "scale":
            return integrations.mask_feed_names(feed_counts(), body.reveal)
        if name == "run_now":
            try:
                return run_now("voice")
            except limits.LimitHit as exc:
                return limited(exc)
        if name == "google_check":
            return google_check()
        if name == "agents":
            return agents_status()
        raise HTTPException(404, "unknown tool")

    # ---------------------------------------------------------------- recorded footage and the built desk
    from fastapi.staticfiles import StaticFiles
    app.mount("/media/footage", StaticFiles(directory=str(watchrun.footage_dir(store)), check_dir=False), name="footage")
    app.mount("/media/captures", StaticFiles(directory=watchrun.capture_dir(store, 0)[:-2], check_dir=False), name="captures")
    if (WEB_DIST / "index.html").exists():  # one app: the desk at /, the API where it is
        app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="desk")
    return app

