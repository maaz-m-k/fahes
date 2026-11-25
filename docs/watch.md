# Watch, capture and feeds

The part of the Istibaq engine that looks outward: it asks the questions residents ask, captures suspect pages from two views, and counts new certificates and domains. It never writes to the database: everything returns plain dataclasses (each with `to_dict()`) that the service stores and turns into cases.

## Adapters (`istibaq/adapters/`)

Every external service sits behind a small adapter that takes an optional `httpx.Client` and a `cost_sink(service, usd, detail)`. Keys come only from environment variables and are never logged or returned. A missing key raises `MissingKey`, and the watch records that as a skipped step.

| Adapter | Service | Key | Label | Cost logged per call |
|---|---|---|---|---|
| `GoogleSearch` | Google results and sponsored ads via DataForSEO (SERP API, Google Organic, standard queue). **On demand only**, see below | `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` + `ISTIBAQ_DATAFORSEO=1` | **borrowed** | $0.0006 |
| `BraveSearch` | Brave Search API web results | `BRAVE_API_KEY` | live | $0.005 |
| `PlacesSearch` | Google Places API (New) Text Search, Maps listings with their website and phone | `GOOGLE_PLACES_API_KEY` | live | $0.035 |
| `LinkExpander` | Follows short links and redirects hop by hop, never letting the client follow; every hop goes through capture's address guard | none | live | free |
| `RDAP` | Domain registration date via rdap.org | none | live | free |
| `CTReader` | One named CT log (`get-sth`, Google Argon 2026h2 by default) for the rate, plus crt.sh for names | none | live | free |
| `NewDomains` | WhoisDS daily newly-registered-domains file | none | **borrowed** | free |
| `AILayer` | OpenRouter, optional AI layer | `OPENROUTER_API_KEY` + `ISTIBAQ_AI_LAYER=1` | live | cost reported by OpenRouter |

Overrides: `ISTIBAQ_CT_LOG_URL` / `ISTIBAQ_CT_LOG_NAME` (another RFC 6962 log), `ISTIBAQ_NRD_URL` (another plain-text or zip list), `ISTIBAQ_AI_MODEL`.

**Google and ads check (DataForSEO, `istibaq/adapters/dataforseo.py`).** The account holds about $1 for the whole hackathon, so every limit is in code and tested:

- **one switch**: off unless `ISTIBAQ_DATAFORSEO=1`. Off raises `GoogleCheckOff` (a `MissingKey`) before any call;
- **never automatic**: the 6-hourly round uses only Brave and Places. Only `POST /api/google/check` and the voice/studio action `google_check` use it;
- **five questions only**: the ones where scam ads show most, marked `ad_prone=True` in `QUESTIONS` (fines, bills, bank customer care, visas, helplines). Any other question raises `NotAdProne`;
- **6-hour cache**: the same question and language within 6 hours is answered from the saved results, with no call and no charge;
- **daily cap**: at most 30 paid searches a UTC day, counted in SQLite (`dataforseo_searches`), so a restart does not reset it. `ISTIBAQ_DATAFORSEO_DAILY_CAP` can lower it, never raise it. A failed post still counts;
- **balance reserve**: before each paid search the free `GET /v3/appendix/user_data` reads `money.balance`; the search is refused (`SpendRefused`) if it would leave less than $0.20 (`ISTIBAQ_DATAFORSEO_RESERVE_USD`), or if the balance cannot be read;
- **cheapest mode**: `POST /v3/serp/google/organic/task_post` with `priority` 1 (standard queue), UAE (`location_code` 2784), the question's language, desktop, depth 10. Never live mode or paid extras. The free `tasks_ready` and `task_get/advanced/{id}` collect it (`task_get` answers 40601/40602 while queued, about 2 minutes in the real sample). A task still queued after 20 seconds is kept and collected by the next check for free (`StillQueued`), never posted twice;
- **every cent logged**: each paid search goes through `cost_sink("dataforseo", 0.0006, {query, lang, task_id, balance_before, balance_after})`, and the ledger keeps the balance read after the result. `GET /api/google/status` shows the limits and spend without any call.

Sponsored (`paid`) items become `SearchResult(source="google_ad", kind="ad")`, every link cited by Google's AI answer (`ai_overview` references) becomes `source="google_ai", kind="ai_cited"`, and organic items `source="google"`; other item types (knowledge graph, reviews, related searches) are skipped, so the scorer and cases treat ads like other results while the officer still sees the ad label (case source `google_ad/ad`). Tests never reach DataForSEO: they use a fake built from the documented response shapes, and `tests/conftest.py` clears the switch and credentials for every test.

**Recorded fakes.** `tests/fixtures/recorded/` holds one hand-written response per service, taken from each service's documented response shape and using only reserved names (`.test`, `.example`). `istibaq.adapters.recorded.recorded_client()` returns an `httpx.Client` that replays them, so every test (watch, service, feeds) runs offline with no keys.

**AI layer.** Off by default. It can only *add* one reason (`ai_page_description`), and report which organisation a captured page claims to be (`claimed_brand`, used only when the register's own names and brand words find none on the page). It never clears a link and never decides whether an address belongs to a brand; that truth comes from the register (`live_brand_mismatch`). Page lines addressed to an AI ("ignore previous instructions", "mark this site as safe", the Arabic equivalent) are stripped. If any are found, the model is not called and the page gets an `ai_injection` reason instead.

## Resident questions and the watch round (`istibaq/watch/`)

`QUESTIONS` is a fixed list of 20 questions in Arabic and English covering fines, bills, helplines, banks and government services. Helpline and bank-care questions are also asked on Google Maps. Five are marked `ad_prone` for the Google and ads check.

`run_round(searchers, maps=None, questions=QUESTIONS, mode="judging", score=None, online_for=None)`:

1. asks every question through every searcher (and Places when the question is marked `maps`);
2. scores each new result with `istibaq.core.scorer.score` (a small stand-in until the scorer is on `main`), optionally with online facts from `online_for(link)`, for example the RDAP age. A Maps listing is judged by `istibaq.core.listing.judge_listing(name, phone, website)`: a listing that names an official body (police, ICP, TAMM, a bank) with a phone number or website that is not that body's own (the register's `helplines` and domains) gets `listing_phone_not_official` / `listing_site_not_official`. Listings with a phone and no website are kept and can become cases;
3. flags as **suspicious** every red result, and every grey result that carries a reason (for example a brand look-alike). Green results are never flagged;
4. returns a `Round` with timestamped `steps` (`ask`, `score`, `flag`, `skip`, `error`, `open`) for replay, all `results`, and `suspicious` for the service to open as cases.

The schedule (every 6 hours and on demand) is the service's job. **Visible-browser mode:** `show_work(round, open_page)` opens only green register pages, and logs each as an `open` step. It never opens a suspect.

## Two-view capture (`istibaq/capture/`)

`capture(link, out_dir)` opens the address twice in headless Chromium (Playwright):

- **server view**: a desktop headless browser with a desktop user agent and viewport, which is how scanners and police tools look;
- **phone view**: an iPhone user agent and viewport (mobile, touch), captured at device scale factor 3; the server view uses 2. Screenshots are lossless PNGs, each with its SHA-256.

Both views use the same `ar-AE` locale, `Asia/Dubai` time zone and Arabic `Accept-Language`. Only the user agent and viewport differ, so a bilingual site is never mistaken for cloaking.

For each view it records every main-frame hop (HTTP redirects and meta or JavaScript redirects, each with its status), screenshots each rendered step (with SHA-256), and reads the final title, text and HTML hash. It also detects human-check walls (reCAPTCHA, hCaptcha, Cloudflare challenge or Turnstile, "verify you are human", and Arabic equivalents).

It then compares the two views, but only when both loaded: destination host, wall, title, and text similarity below 0.6. It writes **saw-through** notes: hidden from server, redirect chain followed, human-check wall seen and not solved. A view that failed or timed out goes into `failures`, which is a fact. It is never a difference and never a reason. The result includes `OnlineFacts` for the scorer: `redirect_chain`, `two_view_difference`, `live_page_brand`, `human_check_wall`, and `payee` (a UAE IBAN found on the page).

Safety: capture only navigates. It never types, clicks, submits or solves a challenge, it dismisses dialogs, and it refuses downloads. A dead link is recorded as an `error` fact, not a crash. `ISTIBAQ_CAPTURE_LOCAL_ONLY=1` refuses anything but 127.0.0.1. Use it on laptops; real capture runs only on the deployed server. The tests use a local server that cloaks by user agent, redirects in a chain, and shows a wall.

Address guard: only `http` and `https` are fetched. Every request, and every redirect hop, goes through `ctx.route("**/*")`. Each hop is fetched without following, and the next address is checked before the browser is allowed to go there. Outside local-only mode the host is resolved, and loopback, private, link-local, multicast and reserved addresses are refused. This stops capture from being aimed at the server itself or its internal network (DNS rebinding between the check and the fetch is not handled). The service must still keep `/capture` behind its token.

On a fresh machine, run `playwright install --with-deps chromium` once (the Dockerfile must do this).

## Footage: the agent's work as real video (`istibaq/capture/footage.py`)

The desk replays a round as real, sped-up video of a real browser.

- **Resident search.** `record_search(question, out_dir, view="computer"|"phone")` drives Chromium the way a resident would:
  - it opens the search page;
  - a visible pointer moves and clicks (on the phone, a finger dot shows each tap, and the page scrolls by real touch swipes in iPhone mode);
  - it types the question letter by letter;
  - it scrolls the results, opens the first **official register** result, and scrolls that page.
- **Recording quality.** The recording is Chromium's own screencast at device resolution (computer ×2, phone ×3). The browser is launched with `--force-device-scale-factor` so the frames are physical pixels: Playwright's built-in video recorder only captures at CSS-pixel size. Each frame is a JPEG (quality 92) with its timestamp.
- **Speed-up.** `speed_up(frames, mp4, factor=3)` uses ffmpeg to make a sped-up H.264 MP4. The `moments` give each step's time, so the desk can caption the video (divide by the factor).
- **Watch round, recorded.** `istibaq.watch.record_work(round, out_dir, limit=4)` records the first questions in both views and logs each recording as a `record` step.
- **Capture, recorded.** `capture(link, out_dir, record=True)` records each view of a suspect page too (`server.video`, `phone.video`, as MP4).

Safety is the same as capture:

- Typing happens only in the search engine's own search box. Nothing is typed, clicked to submit, or solved on any other page.
- Only official register pages are opened. A page that lands off the register is left at once.
- Every page the browser goes to passes the address guard.
- `ISTIBAQ_CAPTURE_LOCAL_ONLY=1` refuses anything but 127.0.0.1.
- A robot check (Google's `/sorry`, Brave's captcha, DuckDuckGo's duck squares or "Unexpected error", Mojeek's "automated queries" 403) is recorded as a `robot` moment, and the next provider is tried. It is never solved or bypassed.

**The Fahes search page.** `GET /search` is our own plain search page, and `GET /search/results?q=&maps=` shows the **real live results** of the search adapters:

- Brave web results;
- Google Places for the questions marked `maps`, shown as a Maps-style list with name, address or phone, and website;
- each result carries Fahes's verdict chip;
- the page is labelled "Real results · Fahes search page";
- the results page runs paid searches, so it needs the officer token header.

The recorder types and scrolls on this page (`fahes_provider(base)`, with the engine's own origin trusted).

**On the server** (`ISTIBAQ_RECORD_FOOTAGE=1`), everything is always sped up and never shown live:

- **Per round:** one overview video per view of the round's first questions on the Fahes search page.
  - Base address: `ISTIBAQ_PUBLIC_URL`.
  - Folder: `ISTIBAQ_FOOTAGE_DIR/round-<id>/`.
  - Kept 7 days.
- **Per case:** each view of the two-view capture is recorded, and the video stays with the case as evidence.

Search sites wall automated browsers quickly, so a laptop gets blocked after a few runs. On the server, record at a low rate.

**Settings for sharp replays:** phone `deviceScaleFactor: 3`, computer 1280×800 at 2, JPEG quality 90 or more (or PNG), and enough steps for smooth playback.

## Live feeds and drill detection (`istibaq/feeds/`)

- `certificate_count(ct)`: two tree-head readings of the named log give the **live** rate of new certificates per hour. Names matching UAE brand words on crt.sh are narrowed to look-alikes by the scorer's `brand_mismatch` reason.
- `new_domain_count(nrd)`: yesterday's newly registered domains (**borrowed**, with source and day), narrowed the same way.
- `detect_drill(domain, published_at, ct)`: finds our own harmless drill page in the certificate logs. It returns the time published, the time found (when the first certificate logged after publication appeared), the minutes to find it, and the feed it was found through. The service stores the records; publishing the drill page is out of scope.

## What is live and what is borrowed

| Signal | Label |
|---|---|
| Google results and ads (DataForSEO, on demand only) | borrowed |
| Newly registered domains (WhoisDS) | borrowed |
| Brave results, Maps listings, RDAP age, CT log rate, crt.sh names, captures | live |

## Left for later

- Brave and Places prices are list prices; reconcile them with real invoices.
- The CT rate uses `get-sth` only. Reading raw `get-entries` would give per-entry names straight from the log instead of via crt.sh.
- The scorer stand-in in `istibaq/watch/scoring.py` is replaced automatically once `istibaq.core.scorer` exists.
