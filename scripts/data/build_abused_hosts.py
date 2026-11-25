"""Popular domains whose subdomains phishers already used, from training-side data only.

Usage: python scripts/data/build_abused_hosts.py phishtank_online-valid.csv [--cut 2026-11-17]
Writes istibaq/data/snapshots/abused_hosts.json: registered domains in the popular allow-list that
hosted phishing on at least one subdomain (``--min-subdomains``, default 1) in PhishTank rows
submitted BEFORE the cut.
Their subdomains never get the "popular owner" pass. Nothing from the sealed tests is read.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

from istibaq.core import allowlist
from istibaq.core.normalise import normalise
from istibaq.core.register import platform_kind

OUT = Path(__file__).resolve().parents[2] / "istibaq" / "data" / "snapshots" / "abused_hosts.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("phishtank", type=Path)
    ap.add_argument("--cut", default="2026-11-17")
    ap.add_argument("--min-subdomains", type=int, default=1)
    ap.add_argument("--fetched", default="2026-11-24", help="day the PhishTank file was downloaded")
    a = ap.parse_args()
    popular = allowlist._popular()
    subs: dict[str, set[str]] = collections.defaultdict(set)
    with a.phishtank.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["submission_time"][:10] >= a.cut:
                continue
            n = normalise(r["url"])
            if n.host != n.registered_domain and not n.private_suffix and n.registered_domain in popular \
                    and not platform_kind(n.host):
                subs[n.registered_domain].add(n.host)
    doms = sorted(d for d, v in subs.items() if len(v) >= a.min_subdomains)
    OUT.write_text(json.dumps({
        "source": f"PhishTank verified phishing (CC BY-SA 4.0), rows submitted before {a.cut}",
        "fetched": a.fetched,
        "rule": f"popular registered domain with phishing on >= {a.min_subdomains} distinct subdomains",
        "domains": doms,
    }, indent=1) + "\n")
    print(len(doms), "domains ->", OUT)


if __name__ == "__main__":
    main()
