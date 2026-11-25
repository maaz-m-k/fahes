"""Release gate: blocks any scorer/model version that regresses.

    python -m istibaq.eval.gate                      # bundled sample (Tranco ranks 200,001-210,000, above the training cut-off)
    python -m istibaq.eval.gate --tranco top-1m.csv  # full sweep (heavy: ask first on shared laptops)
    python -m istibaq.eval.gate --write-baseline     # record the current results as the baseline

Checks: (a) popular-sites sweep: counts above 0.9 and 0.98, top 20, google.com, UAE sanity list;
(b) time-split, site-split fresh fakes (PhishTank after the cut; OpenPhish held out of training);
(c) UAE real-page and UAE/DGE name false alarms. Exits 1 on any regression against the baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from istibaq.eval.scorecard import JUDGING, STRICT, load_testset

DATA = Path(__file__).resolve().parent.parent / "data" / "model"
BASELINE = DATA / "gate_baseline.json"
SAMPLE = DATA / "tranco_sample.txt"
UAE_SANITY = ["google.com", "adpolice.gov.ae", "tamm.abudhabi", "u.ae", "dge.gov.ae", "icp.gov.ae",
              "moi.gov.ae", "bankfab.com", "adcb.com", "emiratesnbd.com", "adib.ae", "dewa.gov.ae",
              "rta.ae", "etisalat.ae", "du.ae", "mohre.gov.ae", "uaepass.ae"]

# metric -> direction: "max" must not go up, "min" must not go down
RULES = {
    "sweep_over_0.9": "max", "sweep_over_0.98": "max", "uae_sanity_flagged": "max",
    "google_flagged": "max", "fresh_catch_phishtank": "min", "fresh_catch_openphish": "min",
    "uae_real_page_false_alarms": "max", "uae_name_false_alarms": "max",
}


def _run_scorer(links: list[str]):
    from istibaq.eval.scorecard import scorer_fn
    out, how = scorer_fn()(links)
    return out, how


def _scores(links: list[str]) -> list[float]:
    """Score of each link; 0 when the register or allow-list decided it (only links that get
    past those layers are counted as model alarms)."""
    out, _ = _run_scorer(links)
    return [s if passed else 0.0 for _, s, passed in out]


def read_sweep(path: Path | None, limit: int | None) -> list[str]:
    if path is None:
        names = [x.strip() for x in SAMPLE.read_text().splitlines() if x.strip()]
    else:
        names = [line.split(",")[-1].strip() for line in path.read_text().splitlines() if line.strip()]
    return names[:limit] if limit else names


def run(sweep: list[str]) -> dict:
    from istibaq.model import load
    out, how = _run_scorer(sweep)
    s = [x if passed else 0.0 for _, x, passed in out]
    top = sorted(zip(s, sweep), reverse=True)[:20]
    sanity = dict(zip(UAE_SANITY, _scores(UAE_SANITY)))
    rows, manifest = load_testset()
    ts = _scores([r["link"] for r in rows])
    by: dict[str, list[float]] = {}
    for r, v in zip(rows, ts):
        by.setdefault(r["slice"], []).append(v)

    def rate(k):
        v = by.get(k, [])
        return round(sum(x >= JUDGING for x in v) / len(v), 4) if v else 0.0

    return {
        "scored_with": how,
        "model_version": (load().version if load() else None),
        "sweep_size": len(sweep),
        "sweep_counted": sum(p for _, _, p in out),
        "sweep_over_0.9": sum(x >= JUDGING for x in s),
        "sweep_over_0.98": sum(x >= STRICT for x in s),
        "sweep_top20": [[n, round(x, 4)] for x, n in top],
        "google_flagged": int(sanity["google.com"] >= JUDGING),
        "uae_sanity_flagged": sum(v >= JUDGING for v in sanity.values()),
        "fresh_catch_phishtank": rate("fresh_fakes_phishtank"),
        "fresh_catch_openphish": rate("fresh_fakes_openphish"),
        "uae_real_page_false_alarms": sum(x >= JUDGING for x in by.get("uae_real_pages", [])),
        "uae_name_false_alarms": sum(x >= JUDGING for x in by.get("uae_names", [])),
        "testset_sha256": manifest["sha256"],
    }


def compare(cur: dict, base: dict) -> list[str]:
    fails = []
    for k in ("scored_with", "model_version", "sweep_size", "testset_sha256"):
        if base.get(k) != cur.get(k):
            fails.append(f"{k} differs from baseline: {base.get(k)!r} -> {cur.get(k)!r} (re-record the baseline deliberately)")
    for k, d in RULES.items():
        if k not in base:
            fails.append(f"{k}: missing from baseline")
            continue
        if (d == "max" and cur[k] > base[k]) or (d == "min" and cur[k] < base[k]):
            fails.append(f"{k}: {base[k]} -> {cur[k]}")
    return fails


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tranco", type=Path)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--write-baseline", action="store_true")
    a = ap.parse_args(argv)
    cur = run(read_sweep(a.tranco, a.limit))
    print(json.dumps(cur, indent=2))
    if a.write_baseline:
        a.baseline.write_text(json.dumps(cur, indent=2) + "\n")
        print(f"baseline written: {a.baseline}")
        return 0
    if not a.baseline.exists():
        print("no baseline: run with --write-baseline first", file=sys.stderr)
        return 1
    fails = compare(cur, json.loads(a.baseline.read_text()))
    for f in fails:
        print("REGRESSION", f, file=sys.stderr)
    print("GATE " + ("FAILED" if fails else "PASSED"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
