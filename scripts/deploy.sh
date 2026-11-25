#!/usr/bin/env bash
# One-command deploy of Fahes (the desk and the engine, one app) to Fly.io: https://fahes.fly.dev
# Reads secrets from the operator's environment (never from the repository) and pushes
# only those that are set. First run: `fly apps create fahes` and
# `fly volumes create istibaq_data --region fra --size 3` (one machine, one volume).
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
