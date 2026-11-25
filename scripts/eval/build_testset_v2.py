"""Build the sealed accuracy test v2 BEFORE any tuning, and record its SHA-256 and time.

Usage:
    python scripts/eval/build_testset_v2.py --uae-pages uae_deeplinks.txt --search search_results.txt \
        --names dge_cert_names.txt --tranco top-1m-incl-subdomains.csv

Writes istibaq/data/testsets/sealed_v2.jsonl and manifest_v2.json. Never edit either by hand:
improve the parts, never the test. Rows: link, label (1 fake, 0 real), slice, source, counted.

Fairness rules built in:
- time split: fakes are the v1 fresh fakes (submitted on/after the 2026-11-17 training cut);
- site split: one link per site (private-suffix aware), and no fake site is a real site;
- real UAE inner pages: never from the three hosts the address model trained on;
- popular subdomain hosts: Tranco ranks above 120,000 (training used synthesised subdomains only);
- popular sites: Tranco (with subdomains) ranks 300,001 to 1,000,000, whose registered domain is
  not in ranks 1 to 120,000 (the model's training range) and not in the gate sample range;
- leak traps: every link is written in a random form (scheme or none, www or none, trailing slash
  or none) on both sides, and the real side has subdomain hosts; the shares go in the manifest.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

from istibaq.core.normalise import normalise

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "istibaq" / "data" / "testsets"
V1 = OUT / "uae_v1.jsonl"
TRAIN_UAE_DOMAINS = {"adpolice.gov.ae", "mohre.gov.ae", "bankfab.com"}
PER_DOMAIN = 12          # real UAE inner pages per registered domain, so no one site dominates
POPULAR = 2500           # popular hosts sampled
SUBDOMAINS = 3000        # popular subdomain hosts sampled
SEED = 20261125

# Synthetic, reserved names only (.test / .example). Never counted as accuracy.
STRESS_FAKES = """adpolice-fines.test tamm-pay.example adp0lice.test tamm-abudhabi.example
adpolice.gov.ae.secure-pay.test pay-tamm.test fab-bank-login.example adcb-verify.test
emiratesnbd-secure.example dewa-bill-refund.test salik-fine-pay.example uaepass-login.test
icp-visa-renew.example mohre-wps.test addc-bill.example rta-fines-uae.test
etisalat-reward.example emiratespost-parcel.test tamm.abudhabi.verify-id.test
xn--adpolce-9db.test adcbank-online.test u-ae.example evil.test\\@adpolice.gov.ae
adcb-card-unblock.example tammservices-pay.test""".split()


def _form(rng: random.Random, link: str) -> str:
    """Write a link in a random surface form so scheme, www and trailing slash say nothing."""
    a = normalise(link)
    host = a.host
    if rng.random() < 0.5 and not host.startswith("www.") and not a.is_ip:
        host = "www." + host
    scheme = rng.choice(["https://", "http://", ""])
    path = a.path
    if (not path or path.startswith("/")) and "?" not in path and "#" not in path and rng.random() < 0.5:
        path = path + "/"
    return scheme + host + (":" + a.port if a.port else "") + path


def _forms_stats(rows: list[dict]) -> dict:
    out = {}
    for lab in (0, 1):
        rs = [r for r in rows if r["label"] == lab and r["counted"]]
        n = len(rs) or 1
        out["fake" if lab else "real"] = {
            "rows": len(rs),
            "trailing_slash": round(sum(r["link"].endswith("/") for r in rs) / n, 3),
            "www": round(sum("www." in r["link"].split("/")[2 if "://" in r["link"] else 0] for r in rs) / n, 3),
            "scheme": round(sum("://" in r["link"] for r in rs) / n, 3),
            "has_subdomain": round(sum(bool(normalise(r["link"]).subdomain) for r in rs) / n, 3),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uae-pages", type=Path, required=True)
    ap.add_argument("--search", type=Path, required=True)
    ap.add_argument("--names", type=Path, required=True)
    ap.add_argument("--tranco", type=Path, required=True)
    a = ap.parse_args()
    rng = random.Random(SEED)
    rows: list[dict] = []

    # Fakes: v1 fresh fakes (time split already applied there), one link per site.
    v1 = [json.loads(x) for x in V1.read_text().splitlines() if x.strip()]
    v1_reals = {normalise(r["link"]).site for r in v1 if r["label"] == 0}
    seen_sites: set[str] = set()
    for r in sorted((r for r in v1 if r["slice"].startswith("fresh_fakes")), key=lambda r: r["link"]):
        site = normalise(r["link"]).site
        if site in seen_sites or site in v1_reals:
            continue
        seen_sites.add(site)
        rows.append({"link": _form(rng, r["link"]), "label": 1, "slice": r["slice"],
                     "source": r["source"] + "; one link per site", "counted": True})

    # Real UAE inner pages, never from the hosts the model trained on.
    by_dom: dict[str, list[str]] = {}
    for u in sorted({x.strip() for x in a.uae_pages.read_text().splitlines() if x.startswith("http")}):
        d = normalise(u).registered_domain
        if d not in TRAIN_UAE_DOMAINS:
            by_dom.setdefault(d, []).append(u)
    for u in (r["link"] for r in v1 if r["slice"] == "uae_real_pages"):
        by_dom.setdefault(normalise(u).registered_domain, []).append(u)
    for d, us in sorted(by_dom.items()):
        us = sorted(set(us))
        rng.shuffle(us)
        for u in us[:PER_DOMAIN]:
            rows.append({"link": _form(rng, u), "label": 0, "slice": "uae_real_pages",
                         "source": "public sitemap / site links of a real UAE site", "counted": True})

    # Real search results for UAE fine/bank questions (includes unofficial but real guide sites).
    for u in sorted({x.strip() for x in a.search.read_text().splitlines() if x.strip()}):
        rows.append({"link": u, "label": 0, "slice": "uae_search_results",
                     "source": "real web search results, UAE fine and bank questions", "counted": True})

    # UAE government and bank names: v1 names plus DGE certificate names.
    names = {r["link"] for r in v1 if r["slice"] == "uae_names"}
    names |= {x.strip() for x in a.names.read_text().splitlines() if x.strip()}
    for n in sorted(names):
        rows.append({"link": _form(rng, n), "label": 0, "slice": "uae_names",
                     "source": "public UAE government/bank domain names", "counted": True})

    # Popular hosts (with subdomains), above the training and gate ranges.
    ranked = [line.split(",", 1) for line in a.tranco.read_text().splitlines() if "," in line]
    train_doms = {normalise(h).registered_domain for rk, h in ranked if int(rk) <= 120_000}
    pool, subs = [], []
    for rk, h in ranked:
        n = normalise(h)
        if n.site in seen_sites:
            continue
        if int(rk) > 120_000 and n.subdomain:
            subs.append(h)  # real subdomain hosts, so "has a subdomain" cannot give the label away
        elif int(rk) > 300_000 and n.registered_domain not in train_doms:
            pool.append(h)
    rng.shuffle(pool)
    rng.shuffle(subs)
    for h in sorted(pool[:POPULAR]):
        rows.append({"link": _form(rng, h), "label": 0, "slice": "popular_sites",
                     "source": "Tranco list incl. subdomains (fetched 2026-11-23), ranks 300,001-1,000,000", "counted": True})
    for h in sorted(subs[:SUBDOMAINS]):
        rows.append({"link": _form(rng, h), "label": 0, "slice": "popular_subdomains",
                     "source": "Tranco list incl. subdomains (fetched 2026-11-23), subdomain hosts ranked above 120,000", "counted": True})

    rows += [{"link": s, "label": 1, "slice": "stress_uae_lookalikes",
              "source": "synthetic, reserved names; never counted as accuracy", "counted": False} for s in STRESS_FAKES]

    data = OUT / "sealed_v2.jsonl"
    data.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["slice"]] = counts.get(r["slice"], 0) + 1
    manifest = {
        "file": data.name,
        "sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
        "sealed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sealed_before_tuning": True,
        "cut_date": "2026-11-17",
        "seed": SEED,
        "rows": len(rows),
        "slices": counts,
        "surface_forms": _forms_stats(rows),
        "note": "Hash recorded before any lever was tuned. Never edit; improve the parts, never the test.",
    }
    (OUT / "manifest_v2.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
