# Istibaq (استباق) — proactive detection of fake links

**Istibaq** is Team Fortress's engine for the SCAMSHIELD AI hackathon (42 Abu Dhabi × Abu Dhabi Police). It knows the
real Abu Dhabi (the **Genuine Register**), scores every link with reasons in Arabic and English, and works offline on
bare addresses — dead links included.

**Requires Python 3.12+.**

Each link gets one of three verdicts:

| verdict | meaning |
|---|---|
| **green** | official: the address is in the Genuine Register (Abu Dhabi Police, TAMM, DGE, ICP, u.ae, UAE PASS, `*.gov.ae`, `*.gov.abudhabi`, `*.abudhabi.ae`, UAE banks, telecoms, utilities) |
| **grey** | not official, not accused |
| **red** | fake, with at least two independent reasons |

## Install

Python 3.12 or newer.

```bash
git clone https://github.com/maaz-codes/ad-police-hackathon.git
cd ad-police-hackathon
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

## Score a file of links (judges' offline command)

No keys and no internet are needed.

```bash
istibaq score links.txt --out results.csv
# same thing:
python -m istibaq score links.txt --out results.csv
```

- **Input:** one link per line, or a CSV with a `url` column. Use `-` to read from stdin.
- **Options:** `--mode judging|officer` (default `judging`), `--out <file>` (default stdout),
  `--format csv|jsonl` (default `csv`), `--online` (server only: follow short links and redirects hop by
  hop through the capture address guard, and read RDAP age; never on a laptop with suspect links).

### Output columns

| column | content |
|---|---|
| `link` | the link exactly as given |
| `is_fraud` | `yes` / `no` (JSONL: `true` / `false`) — use this for precision and recall |
| `score` | 0 to 1 |
| `verdict` | `green` / `grey` / `red` |
| `reasons` | `code: Arabic / English`, separated by ` \| ` (JSONL: list of `{code, ar, en, evidence, time, online}`) |
| `model_version` | scorer model and training cut date (`heuristic-…` when no trained address model is bundled) |
| `scored_at` | ISO-8601 UTC |

### The two modes

- **judging** (default) — maximum catch for the judges' file: `is_fraud = yes` when the link is not green and its score
  is at least 0.9.
- **officer** — a quiet desk: `is_fraud = yes` only when the verdict is red: not green, score at least 0.9 **and**
  at least one independent reason besides the address pattern.

In both modes red always needs two independent reasons. Real UAE government and bank sites are green before any model
runs. Popular sites (Tranco top 100k, exact domain only; never free hosts, tunnels, dynamic DNS or shorteners) are
never flagged. A page on a free host says plainly that the address alone cannot tell real from fake. Offline, a short
link is grey with "short link, destination unknown"; given a redirect chain (online), every hop is judged.

## How a link is scored

1. **Normalise** — lowercase; strip scheme, `www`, trailing slash; split registered domain and private-suffix site
   (bundled Public Suffix List, no network); decode punycode for display.
2. **Genuine Register** (`istibaq/data/register/register.json`, each entry with source and date) — official ends it
   (green). Officers' "not a scam" / "licensed" marks are applied on top.
3. **Popular allow-list** — grey, not accused.
4. **Address model** — `istibaq.model.load()`; a transparent heuristic when no trained model is present.
5. **Independent reason families** — brand mismatch (typos, digit for letter, Arabic/Cyrillic/Greek look-alike letters,
   brand plus a word, brand glued to an account word, an official address with its dots turned into hyphens, brand on
   an unowned domain); disguised address (an official name before `@` or after `\@`); new domain (bundled
   newly-registered-domains list offline, RDAP age online); free host, short link or IP host, and account words in a
   free-host page's own name; known-bad (bundled OpenPhish snapshot). Reverse-DNS names (`*.arpa`) are never accused,
   and a subdomain of a popular site is not accused on its address alone. Online only: young certificate, cross-domain
   redirect, two-view difference, live page brand vs domain, human-check wall, payee not in the register, optional AI
   reason (it can only add a reason, never clear a link).
6. **Thresholds** — as in the modes above.

Never used as evidence: path length, scheme, `www`, trailing slash, popularity rank.

Bundled snapshots live in `istibaq/data/snapshots/` with their source and fetch date:

- **Popular allow-list:** the [Tranco list](https://tranco-list.eu) top 100k, fetched 2026-11-25. Le Pochat et al.,
  "Tranco: A Research-Oriented Top Sites Ranking Hardened Against Manipulation", NDSS 2019.
- **Known-bad:** the OpenPhish community feed (hosts only), fetched 2026-11-25.
- **New domains:** the [hagezi/nrd](https://github.com/hagezi/nrd) 7-day newly-registered-domains list (GPL-3.0),
  list date 24 Nov 2026, bundled as `nrd7.txt.xz`; each reason names the list and its day. It is a week wide:
  refresh it before a judging run with `scripts/data/refresh_nrd.sh`. Online, RDAP age is used too.
- **Shared platforms, tunnels, dynamic DNS, shorteners:** `platforms.json`, hand-collected.

Global consumer brands (Microsoft, Apple, PayPal, Amazon, DHL and others) are never green: their domains host other
people's content. Look-alikes of them are still caught; their own domains are "owned, not accused".

## Data sources and credits

> **Warning:** the known-bad list and the test set contain live scam links. Never open them in a browser.

- **PhishTank** — https://phishtank.org, data under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- **OpenPhish community feed** — https://openphish.com/phishing_feeds.html.
- **Tranco** — https://tranco-list.eu. Le Pochat, Van Goethem, Tajalizadehkhoob, Korczyński, Joosen,
  "Tranco: A Research-Oriented Top Sites Ranking Hardened Against Manipulation", NDSS 2019.

See also `istibaq/data/snapshots/SOURCES.md`.

## Accuracy

Accuracy claims come only from our sealed test, with ranges: see [`docs/accuracy.md`](docs/accuracy.md)
(method, before and after numbers per change, and what they do not cover). Public benchmark numbers are never
quoted as our accuracy.

## Model and scorecard

See [`docs/model.md`](docs/model.md): the address model, the sealed UAE test set, the scorecard and the release gate
(`python -m istibaq.eval.gate`).

## Service and deployment

See [`docs/service.md`](docs/service.md) for the HTTP API, the officer token and the Fly.io deployment, and
[`docs/watch.md`](docs/watch.md) for the watch round and the two-view capture. The desk screens live in [`web/`](web/README.md).

Environment variables (secrets are read only from the environment, never logged or returned):

| Variable | Meaning |
|---|---|
| `ISTIBAQ_OFFICER_TOKEN` | officer token for every POST except scoring |
| `OPENAI_API_KEY` | realtime voice |
| `OPENROUTER_API_KEY` + `ISTIBAQ_AI_LAYER=1` | optional AI layer |
| `BRAVE_API_KEY`, `GOOGLE_PLACES_API_KEY` | the 6-hourly watch round |
| `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | Google results and sponsored ads, used **only** by the on-demand Google and ads check |
| `ISTIBAQ_DATAFORSEO` | `1` turns the Google and ads check on (off by default; the one switch) |
| `ISTIBAQ_DATAFORSEO_RESERVE_USD` / `ISTIBAQ_DATAFORSEO_DAILY_CAP` | balance kept back (default 0.20) / paid searches a day (default 30, can only be lowered) |

See [`docs/service.md`](docs/service.md) for the full list.

## Tests

```bash
pytest
```
