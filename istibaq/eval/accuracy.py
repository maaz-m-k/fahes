"""Accuracy on the sealed test v2, in both settings, with Wilson 95% ranges. Every run is logged.

    python -m istibaq.eval.accuracy --label "baseline"      # appends one line to istibaq/eval/runs_v2.jsonl

Settings:
- judges' yes/no: ``is_fraud`` from ``score(link, mode="judging")``;
- officer: ``is_fraud`` from ``score(link, mode="officer")`` (red: two independent reasons).
The known-bad snapshot is switched off (it would be a lookup of the answers). The test file is
checked against its SHA-256 before every run; a changed file stops the run.
Catch and false-alarm ranges are clustered by registered domain (n = distinct domains, k scaled to
match). The precision range is a plain Wilson range over the flagged links.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

from istibaq.eval.stats import wilson

HERE = Path(__file__).resolve().parent
TESTSETS = HERE.parent / "data" / "testsets"
RUNS = HERE / "runs_v2.jsonl"


def load_sealed() -> tuple[list[dict], dict]:
    manifest = json.loads((TESTSETS / "manifest_v2.json").read_text())
    data = TESTSETS / manifest["file"]
    if hashlib.sha256(data.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("sealed test v2 changed: SHA-256 does not match manifest_v2.json")
    return [json.loads(x) for x in data.read_text().splitlines() if x.strip()], manifest


def _rng(k: int, n: int, n_eff: int) -> list[float]:
    k_eff = round(k * n_eff / n) if n else 0
    return [round(x, 4) for x in wilson(k_eff, n_eff)]


def summarise(rows: list[dict], flags: list[bool]) -> dict:
    from istibaq.core.normalise import normalise
    slices: dict[str, dict] = {}
    for r, f in zip(rows, flags):
        d = slices.setdefault(r["slice"], {"label": r["label"], "counted": r["counted"], "n": 0, "flagged": 0, "_dom": set()})
        d["n"] += 1
        d["flagged"] += int(f)
        d["_dom"].add(normalise(r["link"]).registered_domain)
    for d in slices.values():
        doms = d.pop("_dom")
        d["domains"] = len(doms)
        d["rate"] = round(d["flagged"] / d["n"], 4) if d["n"] else None
        d["range95"] = _rng(d["flagged"], d["n"], len(doms))
    cnt = [d for d in slices.values() if d["counted"]]
    tp = sum(d["flagged"] for d in cnt if d["label"] == 1)
    pos = sum(d["n"] for d in cnt if d["label"] == 1)
    fp = sum(d["flagged"] for d in cnt if d["label"] == 0)
    neg = sum(d["n"] for d in cnt if d["label"] == 0)
    dp = sum(d["domains"] for d in cnt if d["label"] == 1)
    dn = sum(d["domains"] for d in cnt if d["label"] == 0)
    catch = tp / pos if pos else 0.0
    fa = fp / neg if neg else 0.0
    prec = tp / (tp + fp) if tp + fp else None
    prec50 = catch / (catch + fa) if catch + fa else None  # if half the links were fake
    return {
        "catch_rate": round(catch, 4), "catch_range95": _rng(tp, pos, dp),
        "false_alarm_rate": round(fa, 4), "false_alarm_range95": _rng(fp, neg, dn),
        "false_alarms": fp, "reals": neg, "caught": tp, "fakes": pos,
        "precision": round(prec, 4) if prec is not None else None,
        "precision_range95": _rng(tp, tp + fp, tp + fp) if tp + fp else None,
        "precision_at_half_fakes": round(prec50, 4) if prec50 is not None else None,
        "slices": slices,
    }


def run(label: str, log: bool = True) -> dict:
    from istibaq.core import scorer
    from istibaq.eval.scorecard import known_bad_off

    rows, manifest = load_sealed()
    links = [r["link"] for r in rows]
    out = {}
    with known_bad_off():
        scorer.clear_cache()
        for setting, mode in (("judging", "judging"), ("officer", "officer")):
            vs = scorer.score_many(links, mode=mode)
            out[setting] = summarise(rows, [v.is_fraud for v in vs])
        model = scorer.model_version()
    scorer.clear_cache()
    try:
        commit = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--short", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    rec = {
        "label": label,
        "at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit,
        "model_version": model,
        "testset_sha256": manifest["sha256"],
        "known_bad": "off",
        **out,
    }
    if log:
        with RUNS.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="what changed since the last run")
    ap.add_argument("--no-log", action="store_true")
    a = ap.parse_args(argv)
    rec = run(a.label, log=not a.no_log)
    for s in ("judging", "officer"):
        r = rec[s]
        print(f"{s:8} catch {r['catch_rate']:.1%} {r['catch_range95']}  false alarms {r['false_alarms']}/{r['reals']} "
              f"{r['false_alarm_range95']}  precision {r['precision']}")
        for name, d in r["slices"].items():
            print(f"   {name:24} {d['flagged']:5}/{d['n']:<5} {d['rate']:.1%} {d['range95']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
