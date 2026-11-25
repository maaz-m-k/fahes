# Snapshot sources and credits

> **Warning:** `known_bad.json` lists hosts of live scam pages. Never open them in a browser.

| File | Source | Snapshot date | Licence / credit |
|---|---|---|---|
| `known_bad.json` | [OpenPhish community feed](https://openphish.com/phishing_feeds.html) (hosts only) | 2026-11-25 | Credit: OpenPhish, community feed |
| `tranco_top100k.txt.gz` | [Tranco list](https://tranco-list.eu) top 100k | 2026-11-25 | Le Pochat et al., "Tranco: A Research-Oriented Top Sites Ranking Hardened Against Manipulation", NDSS 2019 |
| `new_domains.json` + `nrd7.txt.xz` | [hagezi/nrd](https://github.com/hagezi/nrd) `nrd7.txt` (domains first seen in the 7 days before the list date) | list date 2026-11-24 07:02 UTC | GPL-3.0, credit: hagezi |
| `abused_hosts.json` | Popular domains with phishing on their subdomains in [PhishTank](https://phishtank.org) rows submitted **before** the 2026-11-17 training cut (`scripts/data/build_abused_hosts.py`) | 2026-11-24 | CC BY-SA 4.0, credit: PhishTank |
| `platforms.json` | hand-collected (Public Suffix List private section, provider docs) | 2026-11-25 | — |

The model's sealed test set (`istibaq/data/testsets/`) also uses [PhishTank](https://phishtank.org) data, licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), and the OpenPhish community feed.
