# Istibaq engine service

The FastAPI service that wraps the scoring core and serves the voice-first desk. It stores
cases, sealed records, approvals, register edits, watch runs, drill records and costs in SQLite.

## Run locally

```sh
uv venv -p 3.12 .venv && uv pip install -p .venv -e '.[service]'   # or '.[dev]' for tests
export ISTIBAQ_OFFICER_TOKEN=$(openssl rand -hex 16)
ISTIBAQ_DB=./var/istibaq.db .venv/bin/uvicorn istibaq.api.app:create_app --factory --port 8080
# open http://127.0.0.1:8080/ for the paste-and-score page
.venv/bin/python -m pytest tests/service
```

Install extras: `pip install -e .` is the light scorer only (the judges' offline command);
`.[service]` adds FastAPI, uvicorn and httpx; `.[capture]` adds Playwright; `.[dev]` adds all of them plus pytest.
The Docker image installs `.[service,capture]`.

Environment:

| Variable | Meaning |
|---|---|
| `ISTIBAQ_DB` | SQLite path (default `./var/istibaq.db`; `/data/istibaq.db` on Fly.io) |
| `ISTIBAQ_OFFICER_TOKEN` | required. Every POST except `/api/score` and `/api/score/batch` must send it in the `X-Istibaq-Officer-Token` header. If it isn't set, those POSTs are refused (503) |
| `ISTIBAQ_SCHEDULE` | `1` runs a watch round every 6 hours (off by default; on in `fly.toml`) |
| `ISTIBAQ_FIRST_RUN_DELAY` | seconds before the first scheduled round after start (default 60) |
| `ISTIBAQ_DATAFORSEO` | `1` turns on the paid Google and ads check (DataForSEO). Off by default; this is the one switch |
| `ISTIBAQ_DATAFORSEO_RESERVE_USD` | balance the check never spends below (default 0.20, kept for the final demo) |
| `ISTIBAQ_DATAFORSEO_DAILY_CAP` | paid Google searches a UTC day (default 30; a higher value is ignored) |
| `ISTIBAQ_CAPTURE_DIR` | where screenshots go, one folder per case (default `captures/` beside the database, so `/data/captures/<case_id>` on Fly.io) |
| `ISTIBAQ_REALTIME_SESSION_USD` | estimated cost logged per minted voice session (default 0.50, marked as an estimate) |
| `ISTIBAQ_REALTIME_MODEL` / `ISTIBAQ_REALTIME_FALLBACK` | realtime voice model, default `gpt-realtime-2.1`, fallback `gpt-realtime-2.1-mini` |
| `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, `GOOGLE_PLACES_API_KEY`, `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | secrets, read only from the environment; never logged or returned |

## Endpoints

| Method and path | What it does |
|---|---|
| `GET /health` | liveness plus which modules are live or stand-ins |
| `GET /` | paste-and-score page (Arabic first, right-to-left) |
| `POST /api/score` | `{link, mode}` → one verdict (output contract) |
| `POST /api/score/batch` | `{links: [...], mode}` → `{results, count}` |
| `GET /api/register/lookup?address=` | register lookup |
| `GET/POST /api/register/edits` | list / add register edits (applied through `register.apply_edit`, re-applied at start) |
| `GET /api/cases?reveal=&status=` | list cases; grey names hidden unless `reveal=true` |
| `POST /api/cases` | `{link, source}` open a case by hand |
| `GET /api/cases/{id}?reveal=` | case with capture, sealed record, verification and approvals |
| `POST /api/cases/{id}/capture` | two-view capture through the capture module |
| `POST /api/cases/{id}/seal` | build and seal the Arabic draft record (SHA-256) |
| `POST /api/cases/{id}/approve` | `{method: voice|click, officer}`; refused if unsealed or tampered |
| `POST /api/cases/{id}/mark` | `{status: not_scam|licensed, officer, note}`; feeds the register |
| `GET /api/cases/{id}/takedown` | takedown package; `sent` is always `false` |
| `POST /api/watch/run` | run a watch round now; suspicious results become cases |
| `POST /api/google/check` | the on-demand Google and ads check (officer token): the five ad-prone questions through DataForSEO under the spend limits; stored as a watch run with trigger `google_check`, suspicious results and ads become cases. Returns `status` `off` without spending when the switch is off |
| `GET /api/google/status` | the check's limits and spend so far (`paid_today`, `daily_cap`, `reserve_usd`, `last_balance`, `spent_usd`, the five questions); reads the ledger only, no external call |
| `GET /api/watch/last`, `GET /api/watch/runs/{id}/replay`, `GET /api/watch/schedule` | watch state |
| `GET /api/feeds` | live feed counts (or `unavailable`) |
| `GET/POST /api/drills` | readiness drill records with median and slowest minutes |
| `GET /api/scorecard` | from `istibaq.eval.scorecard.load()` when present |
| `GET /api/costs?runs_per_day=` / `POST /api/costs` | cost so far, monthly projection; record a machine cost |
| `GET /api/summary`, `GET /api/agents` | desk summary; agent statuses (watch, register, check, capture, seal, drill, scale) |
| `POST /api/voice/session` | mints a short-lived OpenAI Realtime client secret; the real key never leaves the server |
| `POST /api/voice/tools/{name}` | voice tools: `summary, show_case, check_address, show_run, seal, approve, scale, run_now, google_check, agents`. `google_check` (for the voice and studio screens) runs the paid Google and ads check, same as `POST /api/google/check`; call it only when the officer asks |

Officer token: the desk sends `X-Istibaq-Officer-Token` on every POST, including voice tools and capture.
GETs are read-only and open, except that `reveal=true` and `/takedown` also need the token.
Grey look-alike names in `/api/feeds` and the voice `scale` tool are masked unless an officer passes `reveal=true`.
Screenshot paths in case JSON are relative to the case's capture folder. Grey sites are never named unless `reveal=true`: a grey case shows only its id, verdict,
score and reason texts, and replay steps mask grey links.

Register edits accept only `not_scam` or `licensed`. Each edit is checked by the register before it is
stored, and a bad stored edit is logged and skipped at start, never fatal.

The seal covers the full verdict and the full capture (both views, screenshot SHA-256s, differences,
facts). Each approval is sealed as `sha256(record_sha + canonical(approval))`; editing an approval
also shows `Verification failed`.

Every sealed record is verified on every read: a changed record shows
`Verification failed` / `فشل التحقق` and cannot be approved.

Other parts' modules (scorer, register, watch, capture, feeds, scorecard) are reached through
`istibaq/api/integrations.py`:

- the watch runs `run_round([BraveSearch], maps=PlacesSearch, mode="officer")`. It never calls DataForSEO;
- the Google and ads check runs `run_round([GoogleSearch], questions=ad_prone_questions(), mode="officer")` only on demand (`POST /api/google/check` or the voice action `google_check`). Suspicious results become cases, and red ones are captured and re-scored with the capture's `facts`;
- feeds are `certificate_count(CTReader())` and `new_domain_count(NewDomains())`, cached for 10 minutes.

When a module is missing, the bridge falls back to a labelled stand-in (`model_version`
`standin-0`, or status `unavailable`) and logs it. A module that is installed but broken
raises instead. `/health` shows `model_version`, so a deploy that fell back is visible.
A failed watch round is stored as `failed` with its error.

## Deploy (Fly.io)

```sh
fly apps create istibaq                                   # first time only
fly volumes create istibaq_data --region dxb --size 1     # first time only
export ISTIBAQ_OFFICER_TOKEN=... OPENAI_API_KEY=... BRAVE_API_KEY=... DATAFORSEO_LOGIN=... DATAFORSEO_PASSWORD=...   # whichever you have
scripts/deploy.sh                                         # stages secrets from env, then fly deploy
```

One machine, a volume at `/data`, health check on `/health`.
