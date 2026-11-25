"""Run a watch round through the watch module and store it; suspicious results become cases.

Shapes follow the real ``istibaq.watch.Round.to_dict()``: ``results`` is a list of
``{"result": {link, source, kind, ...}, "verdict": {...}, "suspicious": bool, "topic": str}``
and ``steps`` a list of ``{"time", "action", "detail"}``. Capture follows
``istibaq.capture.Capture.to_dict()`` (``server``, ``phone``, ``differences``,
``saw_through``, ``facts``).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from istibaq.api import integrations
from istibaq.cases import service as cases
from istibaq.store.db import Store, dumps, loads, now_iso

log = logging.getLogger("istibaq.service")


FOOTAGE_DAYS = 7  # round overview videos are kept this long; case videos stay with their case


def recording() -> bool:
    """Record footage on the server (always sped up, never live): ISTIBAQ_RECORD_FOOTAGE=1."""
    return os.environ.get("ISTIBAQ_RECORD_FOOTAGE", "").lower() in {"1", "true", "yes"}


def footage_dir(store: Store) -> Path:
    base = os.environ.get("ISTIBAQ_FOOTAGE_DIR")
    if not base:
        base = str(Path(store.path).parent / "footage") if store.path != ":memory:" else "./var/footage"
    return Path(base)


def prune_footage(folder: Path, days: int = FOOTAGE_DAYS, now: float | None = None) -> list[str]:
    """Delete round overview folders older than ``days``."""
    import shutil
    import time
    now = now or time.time()
    gone = []
    if folder.exists():
        for d in folder.glob("round-*"):
            if d.is_dir() and now - d.stat().st_mtime > days * 86400:
                shutil.rmtree(d, ignore_errors=True)
                gone.append(d.name)
    return gone


def record_round_overview(store: Store, run_id: int, recorder: Callable | None = None) -> list[dict]:
    """One short overview video per view of the round's questions on the Fahes search page (real live results)."""
    from istibaq.capture.footage import fahes_provider
    from istibaq.watch import Round, record_work
    base = os.environ.get("ISTIBAQ_PUBLIC_URL", "http://127.0.0.1:8080")
    token = os.environ.get("ISTIBAQ_OFFICER_TOKEN", "")
    folder = footage_dir(store)
    prune_footage(folder)
    rnd = Round(str(run_id), now_iso())
    kw = {"providers": ("fahes",), "provider_urls": fahes_provider(base), "trusted_origins": (base,),
          "extra_headers": {"X-Istibaq-Officer-Token": token} if token else None}
    made = record_work(rnd, folder / f"round-{run_id}", recorder=recorder, **kw)
    for i, s in enumerate(rnd.steps):  # after the round's own steps
        store.execute("INSERT INTO watch_steps (run_id, seq, body_json) VALUES (?,?,?)",
                      (run_id, 10_000 + i, dumps(s.to_dict())))
    return made


def capture_dir(store: Store, case_id: int) -> str:
    base = os.environ.get("ISTIBAQ_CAPTURE_DIR")
    if not base:
        base = str(Path(store.path).parent / "captures") if store.path != ":memory:" else "./var/captures"
    return str(Path(base) / str(case_id))


def capture_case(store: Store, case_id: int, capture: Callable, mode: str = "officer") -> dict:
    """Capture a case's link from two views, store it, and re-score with the online facts."""
    case = cases.show(store, case_id, reveal=True)
    out_dir = capture_dir(store, case_id)
    if recording():  # the case's evidence includes a sped-up video of each view; it stays with the case
        try:
            raw = capture(case["link"], out_dir, record=True)
        except TypeError:  # a capture without the recording option
            raw = capture(case["link"], out_dir)
    else:
        raw = capture(case["link"], out_dir)
    cap = _relative_paths(integrations.to_plain(raw), out_dir)
    facts = cap.get("facts") if isinstance(cap, dict) else None
    if isinstance(facts, dict) and not facts.get("live_page_brand"):
        text = ((cap.get("phone") or {}).get("text") or "") or ((cap.get("server") or {}).get("text") or "")
        extra = integrations.ai_page_facts(case["link"], text)
        if extra.get("live_page_brand"):
            facts["live_page_brand"] = extra["live_page_brand"]
        if extra.get("ai_reason") and not facts.get("ai_reason"):
            facts["ai_reason"] = extra["ai_reason"]
    cases.attach_capture(store, case_id, cap)  # stored with any AI-read brand, so the record shows it
    if facts:
        cases.update_verdict(store, case_id, integrations.score(case["link"], mode=mode, online=facts))
    return cap


def _relative_paths(cap: Any, out_dir: str) -> Any:
    """Screenshot paths relative to the case's capture folder; never absolute server paths."""
    if not isinstance(cap, dict):
        return cap
    for view in ("server", "phone"):
        v = cap.get(view) or {}
        if isinstance(v.get("video"), str) and v["video"]:
            try:
                v["video"] = str(Path(v["video"]).relative_to(out_dir))
            except ValueError:
                v["video"] = Path(v["video"]).name
        for shot in v.get("screenshots") or []:
            p = shot.get("path")
            if isinstance(p, str) and p:
                try:
                    shot["path"] = str(Path(p).relative_to(out_dir))
                except ValueError:
                    shot["path"] = Path(p).name
    return cap


# reasons that say the link or listing imitates an official brand or body
BRAND_CODES = {"brand_mismatch", "live_brand_mismatch", "listing_phone_not_official", "listing_site_not_official"}


def worth_a_case(verdict: dict) -> bool:
    """A case is opened only for red, or for grey with a brand-imitation reason; other results stay in the round."""
    return verdict.get("verdict") == "red" or any(
        isinstance(r, dict) and r.get("code") in BRAND_CODES for r in verdict.get("reasons") or [])


def _dead(cap: Any) -> bool:
    """Both views failed to load: the link is dead (a fact, not an error)."""
    if not isinstance(cap, dict):
        return False
    views = [cap.get(v) for v in ("server", "phone") if isinstance(cap.get(v), dict)]
    return bool(views) and all(v.get("error") for v in views)


def feed_step(store: Store, run_id: int, phish_feed: Callable, capture: Callable | None, seq: int = 20_000) -> dict:
    """Fresh links from public scam lists: score, capture on the server, keep the red ones as cases.

    A link that does not come out red after its capture is archived (kept, not shown); a dead link is
    recorded as dead. Every link is a step in the round's replay."""
    have = {r["link"] for r in store.all("SELECT link FROM cases")}
    try:
        links, facts = phish_feed(have)
    except Exception as exc:
        log.warning("public scam lists failed: %s", exc)
        return {"status": "failed", "error": type(exc).__name__, "red": 0, "read": 0}
    integrations.note_known_bad([x.link for x in links], [x.list for x in links])

    def step(action: str, detail: dict) -> None:
        nonlocal seq
        store.execute("INSERT INTO watch_steps (run_id, seq, body_json) VALUES (?,?,?)",
                      (run_id, seq, dumps({"time": now_iso(), "action": action, "detail": detail})))
        seq += 1

    step("ask", {"query": "public scam lists", "source": "publiclist", "lists": facts})
    red, dead, opened = 0, 0, []
    for fl in links:
        verdict = integrations.score(fl.link, mode="officer")
        cid = cases.open_case(store, verdict, source=fl.source, run_id=run_id)
        cap = None
        if capture is not None:
            try:
                cap = capture_case(store, cid, capture)
            except Exception as exc:  # recorded with the case, never fatal for the round
                cases.attach_capture(store, cid, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        final = cases.show(store, cid, reveal=True)
        if _dead(cap):
            dead += 1
            store.execute("UPDATE cases SET status='archived' WHERE id=?", (cid,))
            step("dead", {"link": fl.link, "list": fl.list})
            continue
        step("flag" if final["verdict"] == "red" else "score",
             {"link": fl.link, "verdict": final["verdict"], "list": fl.list, "brand_word": fl.brand_word})
        if final["verdict"] == "red":
            red += 1
            opened.append(cid)
        else:
            store.execute("UPDATE cases SET status='archived' WHERE id=?", (cid,))
    return {"status": "done", "read": len(links), "red": red, "dead": dead, "cases": opened, "lists": facts}


def archive_quiet_grey(store: Store) -> int:
    """Open grey cases without a brand-imitation reason are archived (kept, not deleted)."""
    n = 0
    for row in store.all("SELECT id, verdict_json FROM cases WHERE status='open' AND verdict='grey'"):
        if not worth_a_case(loads(row["verdict_json"]) or {}):
            store.execute("UPDATE cases SET status='archived' WHERE id=?", (row["id"],))
            n += 1
    return n


def run_round(store: Store, watch_round: Callable | None, capture: Callable | None,
              cost_sink: Callable, trigger: str = "manual", phish_feed: Callable | None = None) -> dict:
    run_id = store.execute("INSERT INTO watch_runs (trigger, started_at) VALUES (?,?)", (trigger, now_iso()))

    def finish(summary: dict) -> dict:
        if phish_feed is not None:
            try:
                summary["public_lists"] = feed_step(store, run_id, phish_feed, capture)
                summary["cases"] = list(summary.get("cases") or []) + summary["public_lists"].get("cases", [])
            except Exception as exc:  # the lists are an extra source; never fail the round
                log.exception("public lists step failed")
                summary["public_lists"] = {"status": "failed", "error": type(exc).__name__}
        store.execute("UPDATE watch_runs SET finished_at=?, summary_json=? WHERE id=?",
                      (now_iso(), dumps(summary), run_id))
        return {"run_id": run_id, **summary}

    if watch_round is None:
        return finish({"status": "unavailable", "note_en": "Watch module not deployed yet",
                       "note_ar": "وحدة الرصد غير مفعلة بعد", "results": 0, "cases": []})
    try:
        raw = integrations.to_plain(watch_round(cost_sink))
    except Exception as exc:
        log.exception("watch round failed")
        return finish({"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                       "results": 0, "cases": []})

    steps = raw.get("steps") or []
    results = raw.get("results") or []
    for i, step in enumerate(steps):
        store.execute("INSERT INTO watch_steps (run_id, seq, body_json) VALUES (?,?,?)", (run_id, i, dumps(step)))

    opened, capture_errors = [], 0
    for res in results:
        if not res.get("suspicious"):
            continue
        result = res.get("result") or {}
        verdict = res.get("verdict")
        link = result.get("link") or (verdict or {}).get("link")  # a phone-only Maps listing has no website
        if not link or not isinstance(verdict, dict) or not worth_a_case(verdict):
            continue  # ordinary blogs and directories stay as scored results in the round
        source = "/".join(x for x in (result.get("source"), result.get("kind")) if x) or "watch"
        cid = cases.open_case(store, verdict, source=source, run_id=run_id)
        opened.append(cid)
        if capture is not None and verdict.get("verdict") == "red":
            try:
                capture_case(store, cid, capture)
            except Exception as exc:  # recorded, never fatal for the round
                capture_errors += 1
                cases.attach_capture(store, cid, {"error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    footage = 0
    if recording():
        try:
            footage = len(record_round_overview(store, run_id))
        except Exception:  # footage is a nice-to-have; never fails the round
            log.exception("round footage failed")
    return finish({"status": "done", "round_id": raw.get("id"), "results": len(results), "steps": len(steps),
                   "cases": opened, "capture_errors": capture_errors, "footage": footage})


def get_run(store: Store, run_id: int | None = None) -> dict | None:
    if run_id is None:
        row = store.one("SELECT * FROM watch_runs ORDER BY id DESC LIMIT 1")
    else:
        row = store.one("SELECT * FROM watch_runs WHERE id=?", (run_id,))
    if not row:
        return None
    row["summary"] = loads(row.pop("summary_json"))
    return row


def _mask_step(step: Any) -> Any:
    """Grey results are not named until an officer asks (story 30)."""
    if not isinstance(step, dict):
        return step
    detail = step.get("detail")
    if isinstance(detail, dict) and detail.get("verdict") == "grey" and "link" in detail:
        return {**step, "detail": {**detail, "link": cases.HIDDEN, "label": None}}
    return step


def replay(store: Store, run_id: int, reveal: bool = False) -> list[dict[str, Any]]:
    steps = [loads(r["body_json"]) for r in
             store.all("SELECT body_json FROM watch_steps WHERE run_id=? ORDER BY seq", (run_id,))]
    return steps if reveal else [_mask_step(s) for s in steps]
