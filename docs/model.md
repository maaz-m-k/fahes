# Address model, scorecard and release gate

The address model scores a bare link (no network, so dead links are scored too) and returns a
fraud probability. The scorer (`istibaq/core/scorer.py`) calls it through
`istibaq.model.load()` → `AddressModel.predict(link)`; `AddressModel.version` names the cut date.

- **Model:** character 3-to-5-gram logistic regression over the host (hashed, 2^20 features),
  then LightGBM over that score plus address facts: host length, longest label, subdomain count,
  hyphens, digits, IP host, punycode, free host, shortener, private suffix, brand on an unowned
  domain, keywords, host entropy, suffix phish rate.
- **Forbidden features:** path length, scheme, www, trailing slash, popularity rank. A test fails
  if one returns, and another checks that scheme, `www` and trailing slash never change a score.
- **Keywords** are counted on the host only, so adding a path to a real domain never moves the
  score much (tested: under 0.1). Backslashes are read as `/` and `user@` is stripped, as browsers do.
- **Current version:** `addr-lr3to5+lgbm-cut2026-11-17-v2`. **Training cut date: 2026-11-17.**

## Data (public only)

| Side | Source |
|---|---|
| Fakes (train) | PhishTank public data, rows submitted before the cut only (about 41k) |
| Reals (train) | Tranco ranks 1–120,000, written with and without trailing slash and `www`; popular subdomain hosts (synthesised from common subdomains, because the Tranco subdomain list was unreachable); UAE inner pages from the public sitemaps of adpolice.gov.ae, mohre.gov.ae and bankfab.com |
| Held out | OpenPhish community feed; PhishTank on/after the cut; every site in the sealed test set |

**Time split approximate.** It is exact on PhishTank submission time, but a site reported before the
cut can return after it. Phishing.Database (undated) is no longer used. The site split is by exact site, so
sibling campaign subdomains can sit on both sides. There are still no real free-host sites on the real side.

## Retrain

```sh
scripts/model/download.sh /path/to/scratch            # outside the repository; uses curl
python scripts/model/build_testset.py /path/to/scratch  # only for a NEW test set version: seal before tuning
python -m istibaq.model.train /path/to/scratch          # ~25 s on a laptop; writes istibaq/data/model/
python -m istibaq.eval.scorecard                        # writes istibaq/eval/scorecard.json
python -m istibaq.eval.gate                             # must print GATE PASSED
```

## Sealed UAE test set

The quotable accuracy now comes from the larger **sealed test v2** (fresh fakes one per site, real UAE
inner pages from 25 domains, popular sites and subdomain hosts, leak traps kept out): see
[`accuracy.md`](accuracy.md). The v1 set below still drives the scorecard and the release gate.

`istibaq/data/testsets/uae_v1.jsonl`, with its SHA-256 recorded in `manifest.json` at 2026-11-24T22:11:23Z.
Every read checks the hash. Proof of order is self-written only: the seal, the training and the scorecard
went into one commit. Slices: 124 real UAE pages from 2 hosts never trained on (moi.gov.ae, dge.gov.ae),
47 UAE government and bank names, fresh PhishTank fakes after the cut, OpenPhish (held out), and a
synthetic UAE look-alike stress slice on reserved names that is never counted as accuracy.

## Scorecard (address model alone, flag at score ≥ 0.9; v2)

Ranges are Wilson 95% intervals clustered by registered domain (n = distinct domains).

| Slice | Result | 95% range |
|---|---|---|
| Fresh fakes, PhishTank after cut (1,064 rows, 749 domains) | 66.7% caught | 63.3–70.0% |
| Fresh fakes, OpenPhish held out (299 rows, 270 domains) | 84.3% caught | 79.6–88.3% |
| Real UAE pages (124 rows, **2 hosts**) | 0 flagged | 0–66% (2 hosts prove little) |
| UAE government/bank names (47) | 0 flagged | 0–7.6% |
| Stress: synthetic UAE look-alikes (20) | 7 flagged | not counted |

All counted fakes: 70.6% caught (67.7–73.3%); counted reals: 0 of 171 rows flagged (0–7.3% over 49 domains).
With the full scorer from `fm/istibaq-scorer` (register, allow-list and reasons; **known_bad off**), the
same set gives PhishTank 67.8% and OpenPhish 86.0%. The scorer's known-bad snapshot *is* the OpenPhish
feed, so an OpenPhish number with known_bad on (≈100%) is a lookup and is never quoted as accuracy.
`scorecard.py` and the gate always score with known_bad off. These are fresh *global* fakes, not UAE
fakes. Public benchmark numbers are never quoted as our accuracy.

## Release gate

`python -m istibaq.eval.gate` runs (a) a popular-sites sweep on Tranco ranks 200,001–210,000, all above
the training cut-off of rank 120,000. It reports counts above 0.9 and 0.98, the top 20, google.com and a
UAE sanity list. Only links that get past the register and allow-list are counted. (b) The time-split,
site-split fresh-fake test. (c) UAE real-page and name false alarms. It compares with
`istibaq/data/model/gate_baseline.json` and exits 1 on any regression. It also fails when `scored_with`,
`model_version`, the sweep size or the test-set hash differ from the baseline; re-record the baseline
on purpose with `--write-baseline`. Baseline (v2, model alone): 14 of 10,000 above 0.9 and 4 above 0.98.
The full top-1M sweep (`--tranco top-1m.csv`) is heavy: run it on the server or with approval.

## Data credits

> **Warning:** the sealed test set contains live scam links. Never open them in a browser.

- PhishTank (https://phishtank.org/), CC BY-SA 4.0: training fakes submitted before 2026-11-17;
  test fakes submitted 2026-11-17 to 2026-11-24; downloaded 2026-11-24.
- OpenPhish community feed (https://openphish.com/feed.txt), downloaded 2026-11-24: test only.

See `istibaq/data/testsets/SOURCES.md`.
