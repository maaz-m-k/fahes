"""Scorecard: per-slice results with Wilson 95% ranges on the sealed UAE test set.

Build: ``python -m istibaq.eval.scorecard`` writes ``istibaq/eval/scorecard.json``.
Read:  ``istibaq.eval.scorecard.load()`` (what the service serves).
Only our own sealed test set is reported. Benchmark numbers are never quoted as accuracy.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
from pathlib import Path

from istibaq.eval.stats import wilson

HERE = Path(__file__).resolve().parent
SCORECARD = HERE / "scorecard.json"
TESTSETS = HERE.parent / "data" / "testsets"
JUDGING = 0.9
STRICT = 0.98


def load_testset(verify: bool = True) -> tuple[list[dict], dict]:
    manifest = json.loads((TESTSETS / "manifest.json").read_text())
    data = TESTSETS / manifest["file"]
    if verify and hashlib.sha256(data.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("sealed test set changed: SHA-256 does not match manifest")
    return [json.loads(x) for x in data.read_text().splitlines() if x.strip()], manifest


@contextlib.contextmanager
def known_bad_off():
    """The scorer's known-bad snapshot is built from the same feeds as our fresh-fake slices
    (OpenPhish). Scoring with it on would be a lookup of the answers, not detection."""
    try:
        from istibaq.core import reasons as R  # type: ignore
    except Exception:
        yield
        return
    orig = getattr(R, "known_bad", None)
    if orig is None:
        yield
        return
    R.known_bad = lambda: (frozenset(), {})
    try:
        yield
    finally:
        R.known_bad = orig


def scorer_fn():
    """Prefer the full scorer (is_fraud, known_bad off) when present; else the address model alone.
    Returns run(links) -> ([(is_fraud, score, passed_register_and_allowlist)], scored_with)."""
    try:
        from istibaq.core.scorer import score_many  # type: ignore

        def run(links):
            with known_bad_off():
                vs = score_many(links, mode="judging")
            passed = [not any(r.code in ("register_official", "register_licensed", "popular_site") for r in v.reasons) for v in vs]
            return [(v.is_fraud, v.score, p) for v, p in zip(vs, passed)], "full scorer (judging mode, known_bad off)"
        return run
    except Exception:
        from istibaq.model import load

        m = load()
        if m is None:
            raise RuntimeError("no trained address model bundled")

        def run(links):
            s = m.predict_many(links)
            return [(x >= JUDGING, x, True) for x in s], f"address model alone, is_fraud = score >= {JUDGING}"
        return run


def _domain(link: str) -> str:
    from istibaq.model.features import parse
    return parse(link).site


def build() -> dict:
    rows, manifest = load_testset()
    run = scorer_fn()
    out, how = run([r["link"] for r in rows])
    out = [(f, s) for f, s, _ in out]
    slices: dict[str, dict] = {}
    for r, (flag, s) in zip(rows, out):
        d = slices.setdefault(r["slice"], {"label": r["label"], "counted": r["counted"], "n": 0, "flagged": 0, "flagged_strict": 0, "_dom": {}})
        d["n"] += 1
        d["flagged"] += int(bool(flag))
        d["flagged_strict"] += int(s >= STRICT)
        d["_dom"].setdefault(_domain(r["link"]), []).append(bool(flag))
    for name, d in slices.items():
        # Rows from one registered domain are not independent: shrink n to the number of domains.
        doms = d.pop("_dom")
        d["domains"] = len(doms)
        n_eff = len(doms)
        k_eff = round(d["flagged"] * n_eff / d["n"]) if d["n"] else 0
        lo, hi = wilson(k_eff, n_eff)
        d["metric"] = "catch rate" if d["label"] == 1 else "false-alarm rate"
        d["rate"] = round(d["flagged"] / d["n"], 4)
        d["range95"] = [round(lo, 4), round(hi, 4)]
    tp = sum(d["flagged"] for d in slices.values() if d["counted"] and d["label"] == 1)
    pos = sum(d["n"] for d in slices.values() if d["counted"] and d["label"] == 1)
    fp = sum(d["flagged"] for d in slices.values() if d["counted"] and d["label"] == 0)
    neg = sum(d["n"] for d in slices.values() if d["counted"] and d["label"] == 0)
    dp = sum(d["domains"] for d in slices.values() if d["counted"] and d["label"] == 1)
    dn = sum(d["domains"] for d in slices.values() if d["counted"] and d["label"] == 0)
    from istibaq.model import load
    m = load()
    card = {
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model_version": m.version if m else None,
        "cut_date": manifest["cut_date"],
        "testset": {"file": manifest["file"], "sha256": manifest["sha256"], "sealed_at": manifest["sealed_at"]},
        "scored_with": how,
        "threshold": JUDGING,
        "slices": slices,
        "overall_counted": {
            "catch_rate": round(tp / pos, 4) if pos else None, "catch_range95": [round(x, 4) for x in wilson(round(tp * dp / pos), dp)] if pos else None,
            "false_alarm_rate": round(fp / neg, 4) if neg else None, "false_alarm_range95": [round(x, 4) for x in wilson(round(fp * dn / neg), dn)] if neg else None,
            "fakes": pos, "reals": neg, "fake_domains": dp, "real_domains": dn,
        },
        "notes": [
            "Our own sealed test set only; public benchmark numbers are never our accuracy.",
            "Fresh fakes are global (PhishTank after the cut date, OpenPhish held out), not UAE-specific.",
            "stress_uae_lookalikes is synthetic and never counted as accuracy.",
            "Ranges are Wilson 95% intervals clustered by registered domain (n = distinct domains); small slices have wide ranges.",
            "Time split approximate: fakes trained on are PhishTank rows submitted before the cut date; Phishing.Database (undated) is no longer used.",
            "Site split is by exact site; sibling campaign subdomains can still appear on both sides.",
            "Real UAE pages come from 2 held-out hosts only (moi.gov.ae, dge.gov.ae).",
            "Any OpenPhish figure is the address model or scorer with known_bad off; a merged number with known_bad on is a lookup, never accuracy.",
        ],
    }
    SCORECARD.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n")
    return card


def load() -> dict:
    return json.loads(SCORECARD.read_text())


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
