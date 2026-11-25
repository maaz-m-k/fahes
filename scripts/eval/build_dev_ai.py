"""Build the development split for the AI second opinion, from data dated BEFORE the sealed test window.

Usage:
    python scripts/eval/build_dev_ai.py --phishtank phishtank_online-valid.csv \
        --tranco top-1m-incl-subdomains.csv

Writes istibaq/data/testsets/dev_ai.jsonl and manifest_dev_ai.json. The AI prompt, model choice and
every threshold are picked on this file only, and fixed before the sealed test v2 is scored.

Rules built in:
- fakes: PhishTank reports submitted 2026-11-01 to 2026-11-16 (before the sealed window, which starts
  2026-11-17), one link per site, no site that is in the sealed test. These dates are inside the address
  model's training window, so the model scores them higher than unseen fakes: the dev split is easier
  than the sealed test on the fake side;
- reals: Tranco (with subdomains) hosts not in the sealed test, drawn with a different seed:
  subdomain hosts ranked above 120,000 and popular sites ranked 300,001 to 1,000,000;
- every link is written in a random surface form (scheme, www, trailing slash), as in the sealed test.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "eval"))

from build_testset_v2 import _form  # noqa: E402  (same surface-form writer as the sealed test)

from istibaq.core.normalise import normalise  # noqa: E402

OUT = ROOT / "istibaq" / "data" / "testsets"
SEED = 20261126
FROM, TO = "2026-11-01", "2026-11-17"   # submitted on or after FROM and strictly before TO
FAKES, SUBS, POPULAR = 800, 1200, 600


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phishtank", type=Path, required=True)
    ap.add_argument("--tranco", type=Path, required=True)
    a = ap.parse_args()
    rng = random.Random(SEED)

    sealed = [json.loads(x) for x in (OUT / "sealed_v2.jsonl").read_text().splitlines() if x.strip()]
    sealed_sites = {normalise(r["link"]).site for r in sealed}
    sealed_hosts = {normalise(r["link"]).host for r in sealed}

    rows: list[dict] = []
    fakes, seen = [], set()
    with a.phishtank.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            day = (r.get("submission_time") or "")[:10]
            if not (FROM <= day < TO) or r.get("verified") != "yes":
                continue
            n = normalise(r["url"])
            if not n.host or n.site in sealed_sites or n.site in seen:
                continue
            seen.add(n.site)
            fakes.append(r["url"])
    fakes.sort()
    rng.shuffle(fakes)
    for u in sorted(fakes[:FAKES]):
        rows.append({"link": _form(rng, u), "label": 1, "slice": "dev_fakes_phishtank",
                     "source": f"PhishTank, submitted {FROM} to 2026-11-16 (before the sealed window; in the "
                               "address model's training window); one link per site", "counted": True})

    ranked = [line.split(",", 1) for line in a.tranco.read_text().splitlines() if "," in line]
    subs, pool = [], []
    for rk, h in ranked:
        h = h.strip()
        n = normalise(h)
        if n.host in sealed_hosts or n.site in sealed_sites or n.site in seen:
            continue
        if int(rk) > 120_000 and n.subdomain:
            subs.append(h)
        elif int(rk) > 300_000:
            pool.append(h)
    rng.shuffle(subs)
    rng.shuffle(pool)
    for h in sorted(subs[:SUBS]):
        rows.append({"link": _form(rng, h), "label": 0, "slice": "dev_popular_subdomains",
                     "source": "Tranco incl. subdomains (fetched 2026-11-23), subdomain hosts above rank 120,000, "
                               "none in the sealed test", "counted": True})
    for h in sorted(pool[:POPULAR]):
        rows.append({"link": _form(rng, h), "label": 0, "slice": "dev_popular_sites",
                     "source": "Tranco incl. subdomains (fetched 2026-11-23), ranks 300,001-1,000,000, "
                               "none in the sealed test", "counted": True})

    data = OUT / "dev_ai.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["slice"]] = counts.get(r["slice"], 0) + 1
    manifest = {
        "file": data.name,
        "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
        "built_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": SEED,
        "fakes_submitted": [FROM, "2026-11-16"],
        "rows": len(rows),
        "slices": counts,
        "note": "Development split for the AI second opinion. Chosen on, never the sealed test. "
                "Contains live scam links: never open them in a browser.",
    }
    (OUT / "manifest_dev_ai.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
