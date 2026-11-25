#!/usr/bin/env bash
# One-command deploy of the Istibaq engine to Fly.io.
# Reads secrets from the operator's environment (never from the repository) and pushes
# only those that are set. First run: `fly apps create istibaq` and
# `fly volumes create istibaq_data --region dxb --size 1` (one machine, one volume).
set -euo pipefail
cd "$(dirname "$0")/.."

names=(ISTIBAQ_OFFICER_TOKEN OPENAI_API_KEY OPENROUTER_API_KEY BRAVE_API_KEY GOOGLE_PLACES_API_KEY DATAFORSEO_LOGIN DATAFORSEO_PASSWORD)
args=()
for n in "${names[@]}"; do
  if [ -n "${!n:-}" ]; then args+=("$n=${!n}"); echo "secret: $n (set)"; else echo "secret: $n (not set, skipped)"; fi
done
if [ ${#args[@]} -gt 0 ]; then
  printf '%s\n' "${args[@]}" | fly secrets import --stage
fi
fly deploy "$@"
