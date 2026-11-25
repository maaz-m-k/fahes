#!/usr/bin/env bash
# Download public training data into a scratch directory OUTSIDE the repository.
# Usage: scripts/model/download.sh <scratch-dir>
# Uses curl (Python HTTPS may fail behind TLS-inspecting proxies). Never commit the raw downloads.
set -euo pipefail
OUT="${1:?scratch dir}"; mkdir -p "$OUT"
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/downloaded_at.txt"
# Fakes: OpenPhish community feed (free, no key).
curl -fsSL https://openphish.com/feed.txt -o "$OUT/openphish.txt" || echo "openphish: unreachable" >> "$OUT/notes.txt"
# Fakes: PhishTank public data needs a registered app key for bulk downloads; try the keyless URL and record the outcome.
if curl -fsSL -A "istibaq-research" https://data.phishtank.com/data/online-valid.csv.gz -o "$OUT/phishtank.csv.gz"; then
  gunzip -f "$OUT/phishtank.csv.gz" || true
else
  echo "phishtank: keyless bulk download refused (key required); no PhishTank fakes available; OpenPhish stays held out for testing" >> "$OUT/notes.txt"
fi
# Real: Tranco top-1M registered domains.
curl -fsSL https://tranco-list.eu/top-1m.csv.zip -o "$OUT/tranco.zip" && (cd "$OUT" && unzip -o -q tranco.zip && mv -f top-1m.csv tranco.csv)
# Real: Tranco subdomain list (popular subdomain hosts).
curl -fsSL "https://tranco-list.eu/download/daily/tranco_subdomains.csv.zip" -o "$OUT/tranco_sub.zip" 2>/dev/null && (cd "$OUT" && unzip -o -q tranco_sub.zip -d sub && mv -f sub/*.csv tranco_sub.csv) || echo "tranco subdomains: unreachable" >> "$OUT/notes.txt"
# Real UAE inner pages: public sitemaps of register sites.
: > "$OUT/uae_pages.txt"
for s in u.ae tamm.abudhabi adpolice.gov.ae dge.gov.ae icp.gov.ae moi.gov.ae rta.ae adcb.com emiratesnbd.com bankfab.com adib.ae dewa.gov.ae addc.ae mohre.gov.ae; do
  for p in sitemap.xml sitemap_index.xml en/sitemap.xml; do
    curl -fsSL -m 20 "https://$s/$p" 2>/dev/null | grep -o '<loc>[^<]*</loc>' | sed 's/<\/*loc>//g' >> "$OUT/uae_pages.txt" || true
  done
done
wc -l "$OUT"/*.txt "$OUT"/*.csv 2>/dev/null || true
