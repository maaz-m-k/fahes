#!/bin/sh
# Refresh the bundled newly-registered-domains list (offline domain age) from hagezi/nrd.
# Usage: scripts/data/refresh_nrd.sh   (needs curl and python; writes istibaq/data/snapshots/)
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TMP=$(mktemp -d)
curl -fsSL -o "$TMP/nrd7.txt" https://raw.githubusercontent.com/hagezi/nrd/main/domains/nrd7.txt
python3 - "$TMP/nrd7.txt" "$ROOT/istibaq/data/snapshots" <<'PY'
import json, lzma, re, sys, datetime as dt
src, out = sys.argv[1], sys.argv[2]
lines = open(src, "rb").read().split(b"\n")
mod = next((l.decode() for l in lines if l.startswith(b"# Last modified:")), "")
m = re.search(r"(\d+) (\w+) (\d{4}) (\d\d:\d\d)", mod)
day = dt.datetime.strptime(" ".join(m.groups()), "%d %b %Y %H:%M").strftime("%Y-%m-%dT%H:%MZ") if m else ""
names = sorted({l.strip().lower() for l in lines if l.strip() and not l.startswith(b"#")})
open(f"{out}/nrd7.txt.xz", "wb").write(lzma.compress(b"\n".join(names) + b"\n", preset=9 | lzma.PRESET_EXTREME))
meta = json.load(open(f"{out}/new_domains.json"))
meta.update(fetched=dt.date.today().isoformat(), list_date=day)
json.dump(meta, open(f"{out}/new_domains.json", "w"), indent=1)
print(len(names), "names, list date", day)
PY
rm -rf "$TMP"
