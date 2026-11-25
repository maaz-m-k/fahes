# Sources of the sealed UAE test set

> **Warning:** `uae_v1.jsonl` contains live scam links. Never open them in a browser.

- **PhishTank** (https://phishtank.org/), public data licensed under CC BY-SA 4.0
  (https://creativecommons.org/licenses/by-sa/4.0/). We used verified phishing URLs submitted
  from 2026-11-17 to 2026-11-24 (slice `fresh_fakes_phishtank`), downloaded 2026-11-24.
- **OpenPhish community feed** (https://openphish.com/feed.txt), downloaded 2026-11-24
  (slice `fresh_fakes_openphish`; held out of training).
- Real UAE pages and names come from public sitemaps and public government/bank domains.
  The stress slice uses reserved `.test` and `.example` names only.

The data and its SHA-256 (see `manifest.json`) are unchanged since sealing.
