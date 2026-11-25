"""Arabic draft record with a SHA-256 fingerprint over a canonical serialisation.

The fingerprint covers the whole verdict (``is_fraud``, ``scored_at``, every reason with its
evidence and ``online`` flag) and the whole capture (both views, screenshot SHA-256s,
differences, saw-through notes, facts). Each approval is sealed on top of the record:
``approval_sha = sha256(record_sha + canonical(approval))``.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

VERIFIED = {"ok": True, "ar": "تم التحقق: السجل لم يتغير", "en": "Verified: record unchanged"}
FAILED = {"ok": False, "ar": "فشل التحقق: تغيّر السجل بعد ختمه", "en": "Verification failed: record changed after sealing"}


def canonical(body: Any) -> bytes:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def fingerprint(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


def _chain(capture: dict) -> list:
    facts = capture.get("facts") or {}
    if facts.get("redirect_chain"):
        return facts["redirect_chain"]
    for view in ("phone", "server"):
        hops = (capture.get(view) or {}).get("hops") or []
        if hops:
            return [h.get("url") for h in hops]
    return []


def build(case: dict[str, Any], sealed_at: str) -> dict[str, Any]:
    """Fixed layout: time, source, address, reasons, captures, chain (plus the full verdict and capture)."""
    verdict = case.get("verdict_full") or {}
    capture = case.get("capture") or {}
    shots = [
        {"view": view, **shot}
        for view in ("server", "phone")
        for shot in ((capture.get(view) or {}).get("screenshots") or [])
    ]
    return {
        "title_ar": "مسودة محضر رصد رابط مشبوه",
        "title_en": "Draft record: suspicious link",
        "time": sealed_at,
        "case_id": case["id"],
        "opened_at": case["opened_at"],
        "source": case["source"],
        "address": case["link"],
        "verdict": case["verdict"],
        "score": case["score"],
        "reasons": verdict.get("reasons", []),
        "captures": shots,
        "differences": capture.get("differences") or [],
        "saw_through": capture.get("saw_through") or [],
        "chain": _chain(capture),
        "verdict_full": verdict,
        "capture_full": capture,
        "status_ar": "مسودة بانتظار اعتماد الضابط",
        "status_en": "Draft awaiting officer approval",
    }


def verify(body: dict[str, Any], sha256: str) -> dict[str, Any]:
    return dict(VERIFIED if fingerprint(body) == sha256 else FAILED)


def approval_fingerprint(record_sha: str, approval: dict[str, Any]) -> str:
    core = {k: approval[k] for k in ("method", "officer", "approved_at")}
    return hashlib.sha256(record_sha.encode("ascii") + canonical(core)).hexdigest()
