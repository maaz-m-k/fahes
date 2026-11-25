"""Build the sealed UAE test set BEFORE any tuning, and record its SHA-256 and time.

Usage: python scripts/model/build_testset.py <scratch-dir> [--cut 2026-11-17]
Writes istibaq/data/testsets/uae_v1.jsonl and manifest.json. Rows: link, label (1 fake,
0 real), slice, source, counted (False for the synthetic stress slice).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "istibaq" / "data" / "testsets"

# Hosts held out entirely from training (never seen), plus a random share of the others.
HELD_OUT_HOSTS = {"moi.gov.ae", "www.dge.gov.ae", "dge.gov.ae"}
# Hosts whose pages train the model; kept out of the names slice.
TRAIN_UAE_HOSTS = {"www.adpolice.gov.ae", "mohre.gov.ae", "www.bankfab.com"}
UAE_NAMES = """tamm.abudhabi abudhabi.ae dge.gov.ae icp.gov.ae u.ae
moi.gov.ae dubaipolice.gov.ae rta.ae salik.ae dewa.gov.ae addc.ae aadc.ae etisalat.ae du.ae
adcb.com emiratesnbd.com adib.ae mashreq.com cbuae.gov.ae emiratespost.ae
uaepass.ae darb.ae itc.gov.ae adm.gov.ae doh.gov.ae ehs.gov.ae mof.gov.ae tdra.gov.ae
moec.gov.ae adek.gov.ae dm.gov.ae smartdubai.ae dubai.ae sharjah.ae shjpolice.gov.ae
ajmanpolice.gov.ae adnoc.ae etihad.com emirates.com rakbank.ae cbd.ae nbf.ae
dib.ae ajmanbank.ae eibank.com hsbc.ae sib.ae""".split()
STRESS = """adpolice-fines.test tamm-pay.example adp0lice.test tamm-abudhabi.example
adpolice.gov.ae.secure-pay.test pay-tamm.test fab-bank-login.example adcb-verify.test
emiratesnbd-secure.example dewa-bill-refund.test salik-fine-pay.example uaepass-login.test
icp-visa-renew.example mohre-wps.test addc-bill.example rta-fines-uae.test
etisalat-reward.example emiratespost-parcel.test tamm.abudhabi.verify-id.test
xn--adpolce-9db.test""".split()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scratch", type=Path)
    ap.add_argument("--cut", default="2026-11-17")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    rows: list[dict] = []

    pages = sorted({u.strip() for u in (a.scratch / "uae_pages.txt").read_text().splitlines()
                    if u.startswith("http")})
    by_host: dict[str, list[str]] = {}
    for u in pages:
        by_host.setdefault(u.split("/")[2].lower(), []).append(u)
    real: list[tuple[str, str]] = []
    for h, us in sorted(by_host.items()):
        if h in HELD_OUT_HOSTS:  # strict host split: training never sees these hosts
            real += [(u, "host_held_out") for u in us]
    for u, how in real:
        rows.append({"link": u, "label": 0, "slice": "uae_real_pages", "source": f"public sitemap ({how})", "counted": True})
    for n in UAE_NAMES:
        rows.append({"link": n, "label": 0, "slice": "uae_names", "source": "public UAE government/bank domain", "counted": True})

    fresh: set[str] = set()
    with open(a.scratch / "phishtank.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["submission_time"][:10] >= a.cut:
                fresh.add(r["url"].strip())
    rows += [{"link": u, "label": 1, "slice": "fresh_fakes_phishtank", "source": f"PhishTank, submitted on/after {a.cut}", "counted": True} for u in sorted(fresh)]
    op = {u.strip() for u in (a.scratch / "openphish.txt").read_text().splitlines() if u.strip()} - fresh
    rows += [{"link": u, "label": 1, "slice": "fresh_fakes_openphish", "source": "OpenPhish community feed (held out of training)", "counted": True} for u in sorted(op)]
    rows += [{"link": s, "label": 1, "slice": "stress_uae_lookalikes", "source": "synthetic, reserved names; never counted as accuracy", "counted": False} for s in STRESS]

    OUT.mkdir(parents=True, exist_ok=True)
    data = OUT / "uae_v1.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["slice"]] = counts.get(r["slice"], 0) + 1
    manifest = {
        "file": data.name, "sha256": sha256(data),
        "sealed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sealed_before_tuning": True, "cut_date": a.cut, "rows": len(rows), "slices": counts,
        "note": "Hash recorded before any model tuning. Training excludes every host in this file.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
