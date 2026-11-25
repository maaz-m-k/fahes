"""Cases: open, list, show, seal, approve, mark; takedown package (never sent)."""
from __future__ import annotations

import logging
from typing import Any

from istibaq.api import integrations
from istibaq.seal import record as seal_record
from istibaq.store.db import Store, dumps, loads, now_iso

log = logging.getLogger("istibaq.service")

HIDDEN = "••• (مخفي / hidden)"
MARKS = ("not_scam", "licensed")


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def open_case(store: Store, verdict: dict, source: str, capture: dict | None = None,
              run_id: int | None = None) -> int:
    return store.execute(
        "INSERT INTO cases (link, source, verdict, score, verdict_json, capture_json, run_id, opened_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (verdict["link"], source, verdict["verdict"], float(verdict["score"]), dumps(verdict),
         dumps(capture) if capture else None, run_id, now_iso()),
    )


def attach_capture(store: Store, case_id: int, capture: dict) -> None:
    _row(store, case_id)
    store.execute("UPDATE cases SET capture_json=? WHERE id=?", (dumps(capture), case_id))


def update_verdict(store: Store, case_id: int, verdict: dict) -> None:
    """Re-scored with online facts (e.g. after capture). The case keeps its original link."""
    store.execute("UPDATE cases SET verdict=?, score=?, verdict_json=? WHERE id=?",
                  (verdict["verdict"], float(verdict["score"]), dumps(verdict), case_id))


def _row(store: Store, case_id: int) -> dict:
    row = store.one("SELECT * FROM cases WHERE id=?", (case_id,))
    if not row:
        raise NotFound(case_id)
    return row


def _present(store: Store, row: dict, reveal: bool) -> dict:
    base = {k: row[k] for k in ("id", "link", "source", "verdict", "score", "status", "run_id", "opened_at")}
    verdict = loads(row["verdict_json"]) or {}
    if base["verdict"] == "grey" and not reveal:
        # Story 30: a grey site is not named by the screen. Only id, verdict, score and reason texts.
        return {"id": base["id"], "link": HIDDEN, "verdict": "grey", "score": base["score"],
                "status": base["status"], "opened_at": base["opened_at"], "name_hidden": True,
                "reasons": [{k: r.get(k) for k in ("code", "ar", "en")} for r in verdict.get("reasons", [])]}
    return {**base, "verdict_full": verdict, "capture": loads(row["capture_json"]),
            "record": _record_for(store, row["id"]), "name_hidden": False}


def _record_for(store: Store, case_id: int) -> dict | None:
    rec = store.one("SELECT * FROM records WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,))
    if not rec:
        return None
    body = loads(rec["body_json"])
    verification = seal_record.verify(body, rec["sha256"])
    approvals = store.all("SELECT method, officer, approved_at, approval_sha FROM approvals"
                          " WHERE record_id=? ORDER BY id", (rec["id"],))
    for a in approvals:
        a["verified"] = seal_record.approval_fingerprint(rec["sha256"], a) == a["approval_sha"]
    if not all(a["verified"] for a in approvals):
        verification = dict(seal_record.FAILED)
    return {"id": rec["id"], "sha256": rec["sha256"], "sealed_at": rec["sealed_at"], "body": body,
            "verification": verification, "approvals": approvals}


def list_cases(store: Store, reveal: bool = False, status: str | None = None) -> list[dict]:
    sql, params = "SELECT * FROM cases", []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    out = []
    for r in store.all(sql + " ORDER BY id DESC", params):
        c = _present(store, r, reveal)
        out.append({k: c.get(k) for k in ("id", "link", "source", "verdict", "score", "status", "opened_at")}
                   | {"sealed": bool(c.get("record")), "name_hidden": c["name_hidden"]})
    return out


def show(store: Store, case_id: int, reveal: bool = False) -> dict:
    return _present(store, _row(store, case_id), reveal)


def seal(store: Store, case_id: int) -> dict:
    case = _present(store, _row(store, case_id), reveal=True)
    sealed_at = now_iso()
    body = seal_record.build(case, sealed_at)
    digest = seal_record.fingerprint(body)
    store.execute("INSERT INTO records (case_id, body_json, sha256, sealed_at) VALUES (?,?,?,?)",
                  (case_id, dumps(body), digest, sealed_at))
    store.execute("UPDATE cases SET status='sealed' WHERE id=?", (case_id,))
    return _record_for(store, case_id)


def approve(store: Store, case_id: int, method: str, officer: str) -> dict:
    if method not in ("voice", "click"):
        raise Invalid("method must be voice or click")
    _row(store, case_id)
    rec = _record_for(store, case_id)
    if rec is None:
        raise Invalid("seal the case before approving")
    if not rec["verification"]["ok"]:
        raise Invalid("record failed verification; cannot approve")
    approval = {"method": method, "officer": officer, "approved_at": now_iso()}
    store.execute("INSERT INTO approvals (record_id, method, officer, approved_at, approval_sha) VALUES (?,?,?,?,?)",
                  (rec["id"], method, officer, approval["approved_at"],
                   seal_record.approval_fingerprint(rec["sha256"], approval)))
    store.execute("UPDATE cases SET status='approved' WHERE id=?", (case_id,))
    return _record_for(store, case_id)


def add_register_edit(store: Store, address: str, status: str, source: str, note: str | None,
                      case_id: int | None = None) -> dict:
    """Validate and apply first, then store, so a refused edit can never reach the database."""
    if status not in MARKS:
        raise Invalid(f"status must be one of {', '.join(MARKS)}")
    try:
        applied = integrations.register_apply_edit(address, status, source, note)
    except ValueError as exc:
        raise Invalid(f"register refused the edit: {exc}")
    rid = store.execute(
        "INSERT INTO register_edits (address, status, source, note, case_id, created_at) VALUES (?,?,?,?,?,?)",
        (address, status, source, note, case_id, now_iso()))
    return {"id": rid, "applied": applied}


def mark(store: Store, case_id: int, status: str, officer: str, note: str | None = None) -> dict:
    """Officer marks a flag 'not_scam' or 'licensed'; feeds back into the register."""
    row = _row(store, case_id)
    edit = add_register_edit(store, row["link"], status, f"officer:{officer}", note, case_id)
    store.execute("UPDATE cases SET status=? WHERE id=?", (status, case_id))
    return {"case_id": case_id, "status": status, "register_applied": edit["applied"]}


def reapply_register_edits(store: Store) -> int:
    """Re-apply stored edits at start. A bad row is logged and skipped, never fatal."""
    ok = 0
    for r in store.all("SELECT * FROM register_edits ORDER BY id"):
        try:
            integrations.register_apply_edit(r["address"], r["status"], r["source"], r["note"])
            ok += 1
        except Exception as exc:
            log.warning("skipping register edit %s (%s): %s", r["id"], r["status"], exc)
    return ok


def takedown_package(store: Store, case_id: int) -> dict[str, Any]:
    case = show(store, case_id, reveal=True)
    cap = case["capture"] or {}
    rec = case["record"] or {}
    body = rec.get("body") or seal_record.build(case, now_iso())
    return {
        "case_id": case_id,
        "address": case["link"],
        "prepared_at": now_iso(),
        "sent": False,
        "notice_en": "Prepared only. Nothing is sent automatically; the officer decides.",
        "notice_ar": "تم التجهيز فقط. لا يُرسل شيء تلقائياً؛ القرار للضابط.",
        "reasons": case["verdict_full"].get("reasons", []),
        "captures": body["captures"],
        "differences": cap.get("differences") or [],
        "chain": body["chain"],
        "times": {"opened_at": case["opened_at"], "scored_at": case["verdict_full"].get("scored_at"),
                  "sealed_at": rec.get("sealed_at")},
        "record_sha256": rec.get("sha256"),
    }
