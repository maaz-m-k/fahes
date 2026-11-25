"""Train the Istibaq address model from public data downloaded by scripts/model/download.sh.

Usage: python -m istibaq.model.train <scratch-dir> [--cut 2026-11-17] [--fakes N] [--reals N]

Time split: PhishTank fakes submitted before the cut date only; OpenPhish is held out for
testing. Site split: no registered site that appears in the sealed test set is trained on.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import time
from pathlib import Path

import numpy as np

from istibaq.model import ARTIFACT_DIR, vectorizer
from istibaq.model.features import FEATURE_NAMES, facts, parse

TESTSET = ARTIFACT_DIR.parent / "testsets" / "uae_v1.jsonl"
TRAIN_UAE_HOSTS = {"www.adpolice.gov.ae", "mohre.gov.ae", "www.bankfab.com"}
COMMON_SUBS = ("mail", "login", "accounts", "support", "app", "m", "shop", "docs", "help",
               "account", "secure", "pay", "my", "portal", "api", "blog", "news", "store")


def _sites_in_testset() -> set[str]:
    out = set()
    for line in TESTSET.read_text().splitlines():
        p = parse(json.loads(line)["link"])
        out |= {p.site, p.registered}
    return out


def collect(scratch: Path, cut: str, n_fakes: int, n_reals: int, seed: int):
    """Fakes: dated PhishTank rows before the cut only (undated Phishing.Database is dropped,
    so the time split is exact on submission time). n_fakes caps the fake side."""
    rng = random.Random(seed)
    banned = _sites_in_testset()
    shared = {"github.io", "weebly.com", "wixsite.com", "blogspot.com"}

    def ok(link: str) -> bool:
        p = parse(link)
        return bool(p.host) and p.site not in banned and (p.registered not in banned or p.registered in shared or p.is_private)

    fakes: list[str] = []
    with open(scratch / "phishtank.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["submission_time"][:10] < cut and ok(r["url"]):
                fakes.append(r["url"].strip())
    fakes = list(dict.fromkeys(fakes))[:n_fakes]

    tranco = [line.split(",", 1)[1].strip() for line in (scratch / "tranco.csv").read_text().splitlines()[: n_reals]]
    tranco = [d for d in tranco if ok(d)]
    reals: list[str] = []
    for d in tranco:  # trailing-slash and www trap: every form appears on the real side
        reals.append(rng.choice([d, d + "/", "https://" + d + "/", "https://www." + d]))
    for d in tranco[:8000]:  # popular subdomain hosts (synthesised: Tranco subdomain list unreachable)
        reals.append(f"https://{rng.choice(COMMON_SUBS)}.{d}/")
    uae = [u.strip() for u in (scratch / "uae_pages.txt").read_text().splitlines()
           if u.startswith("http") and u.split("/")[2].lower() in TRAIN_UAE_HOSTS]
    rng.shuffle(uae)
    reals += uae[:3000]
    return fakes, reals


def suffix_rates(links: list[str], y: np.ndarray, alpha: float = 20.0):
    base = float(y.mean())
    tot: dict[str, list[float]] = {}
    for link, lab in zip(links, y):
        t = tot.setdefault(parse(link).suffix, [0.0, 0.0])
        t[0] += lab
        t[1] += 1
    return {s: (a + alpha * base) / (n + alpha) for s, (a, n) in tot.items() if n >= 5}, base


def main() -> None:
    from lightgbm import LGBMClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold

    ap = argparse.ArgumentParser()
    ap.add_argument("scratch", type=Path)
    ap.add_argument("--cut", default="2026-11-17")
    ap.add_argument("--fakes", type=int, default=80_000)
    ap.add_argument("--reals", type=int, default=120_000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=ARTIFACT_DIR)
    a = ap.parse_args()
    t0 = time.time()
    fakes, reals = collect(a.scratch, a.cut, a.fakes, a.reals, a.seed)
    links = fakes + reals
    y = np.array([1] * len(fakes) + [0] * len(reals), dtype=np.float64)
    print(f"collected fakes={len(fakes)} reals={len(reals)} in {time.time()-t0:.0f}s", flush=True)

    from istibaq.model.features import model_text
    X = vectorizer().transform([model_text(x) for x in links])
    lr_kw = dict(C=4.0, max_iter=300, solver="liblinear", class_weight="balanced")
    oof = np.zeros(len(links))
    for tr, te in StratifiedKFold(3, shuffle=True, random_state=a.seed).split(X, y):
        m = LogisticRegression(**lr_kw).fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
    lr = LogisticRegression(**lr_kw).fit(X, y)
    print(f"lr done {time.time()-t0:.0f}s", flush=True)

    rates, base = suffix_rates(links, y)
    F = np.asarray([[s] + facts(x, rates, base) for x, s in zip(links, oof)])
    gbm = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=40,
                         class_weight="balanced", random_state=a.seed, verbose=-1)
    gbm.fit(F, y, feature_name=list(FEATURE_NAMES))
    print(f"gbm done {time.time()-t0:.0f}s", flush=True)

    a.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out / "lr.npz", coef=lr.coef_[0].astype(np.float32), intercept=np.float64(lr.intercept_[0]))
    (a.out / "lgbm.txt").write_text(gbm.booster_.model_to_string())
    trained = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "version": f"addr-lr3to5+lgbm-cut{a.cut}-v2",
        "cut_date": a.cut, "trained_at": trained, "tranco_rank_cutoff": a.reals,
        "features": list(FEATURE_NAMES),
        "train_counts": {"fakes": len(fakes), "reals": len(reals)},
        "sources": {
            "fakes": f"PhishTank public data submitted before {a.cut} (dated rows only)",
            "reals": f"Tranco top {a.reals} registered domains (with/without trailing slash and www); synthesised popular subdomain hosts; UAE inner pages from public sitemaps of adpolice.gov.ae, mohre.gov.ae, bankfab.com",
            "held_out": "OpenPhish community feed; PhishTank on/after cut date; every site in the sealed UAE test set",
        },
        "suffix_phish_rate": rates, "default_suffix_rate": base,
    }
    (a.out / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    print(f"saved to {a.out} in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
