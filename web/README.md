# Fahes desk screens (`web/`)

The voice-first desk for the duty officer (spec: issue #10). One dark web app, Arabic first, with two modes:

- **Voice**: the teal orb rests big. Talk (OpenAI gpt-realtime-2.1 over WebRTC) or type. When an answer needs a screen, the orb moves to the top and a card appears below it. The card stays while you keep talking. The next request that needs a screen changes the content inside the same card. The card closes only on «سكّرها» / "close it", on the ×, or when an answer needs no screen.
- **Studio**: every feature in a side menu (Watch, Cases, Check an address, Register, Drill, Scale, Records, Agents), built from the same components.

Every part is marked REAL, STAND-IN or DEMO DATA. One switch ("Show what is real") hides the markers.

How the voice behaves:

- **Language.** Fahes replies in the language of the officer's last sentence, whatever it is. "Speak in Arabic" / "speak English" switches the language, and it stays switched. The screen follows: Arabic or English words. For any other language the reply is spoken in that language and the screen uses English.
- **Typing.** Text typed or pasted in the bottom field joins the live voice conversation, and the session starts if it is off. The realtime voice answers and calls the tools, for example `check_address` on a pasted link. The browser's own voice is used only as the labelled fallback when the live session cannot start.
- **Suggestions.** After an answer, two or three suggestions appear and Fahes says one of them. Tapping a suggestion does the same as saying it. A tap is also told to the live session, so the voice can speak about it.
- **Checking links.** "I want to check some links" opens the same link checker as the studio's Check page inside the card. Several links can be checked one after another in the same card.

## Run it

```sh
cd web
npm install
npm run dev          # http://localhost:5173 (fake engine, the default)
npm test             # vitest + Testing Library, offline
npm run build        # static files in web/dist (serve them from the engine or Fly.io)
```

Options in the URL: `?lang=en`, `?mode=studio&page=check` (the paste-and-score page for judges), `?mk=0` (markers hidden), `?mute=1` (no browser voice for typed answers), `?engine=http|fake`.

### Voice in development

Before the engine is merged, the dev server provides a dev-only stand-in for the engine's voice endpoints (`dev/devApi.ts`; it is never part of the build). It reads `OPENAI_API_KEY` (and `OPENROUTER_API_KEY` for typed understanding) from the environment, or from the file named by `ISTIBAQ_ENV_FILE`:

```sh
ISTIBAQ_ENV_FILE=/path/to/.env npm run dev
```

The real key stays in the dev server process. The browser only gets a short-lived client secret (5 minutes). Without a key, the orb's "Talk to Fahes" button shows a plain message and typing still works (the local matcher understands typed requests).

### Against the real engine

```sh
ISTIBAQ_ENGINE_URL=http://127.0.0.1:8000 VITE_ENGINE=http npm run dev
```

For a static build served by the engine: `VITE_ENGINE=http npm run build`.

## Real footage for the replay

The replay plays real, sped-up video of a real browser, not still pictures:

- **Players:** a computer window and a phone frame, each with a real video player. One play/pause button and one scrub bar control both. The speed label (for example "3×") is on the video, and the agent's step captions stay in time with it.
- **Phone view:** "show it on the phone" fills the card with the phone video.
- **Round overview:** a round carries `footage` (one overview video per view) and `clips` (extra clips, for example a real Google clip added later). A case can carry `footage` of its two-view capture.
- **Labels:** a real browser on real results is REAL. A synthetic look-alike page is DEMO DATA.
- **Demo assets** (`public/demo-footage/`):
  - the round overview on the Fahes search page, with recorded real results, opening a real official page;
  - the two-view capture of a local synthetic look-alike page.

How the engine records it (sharpness, safety, retention) is described in `docs/watch.md` under "Footage".

## How it is put together

| Part | File |
|---|---|
| Every engine call (one client, the http client and the fake) | `src/api/client.ts`, `src/api/fake/` |
| Engine response shapes | `src/api/types.ts` |
| The tool layer: voice tool calls and typed requests become engine calls and a card | `src/voice/tools.ts` |
| Voice mode state model (idle / answering, change in place, close) | `src/voice/desk.ts` |
| Realtime voice (WebRTC, short-lived key, plain-words failures) | `src/voice/realtime.ts` |
| Voice instructions and tool list (the engine mints sessions with these) | `src/voice/toolSpec.ts` |
| The local matcher (fallback understanding) | `src/voice/matcher.ts` |
| Following the officer's language | `src/voice/lang.ts` |
| The replay playback (real footage player, stills as a fallback) | `src/kit/Replay.tsx`, `src/kit/FootagePlayer.tsx` |
| The orb (approved WebGL shader, unchanged) | `src/voice/orbGl.js`, `src/voice/Orb.tsx` |
| The closed kit of components | `src/kit/` |
| Studio pages | `src/studio/Studio.tsx` |

### Engine endpoints the http client calls

These are the screens' side of the contract with the engine (issue #9). If an engine path or shape differs, change it in `src/api/client.ts` only.

| Call | Method and path |
|---|---|
| desk summary | `GET /api/desk` |
| one case | `GET /api/cases/{id}` |
| score an address | `POST /api/score` `{link, mode}` |
| register | `GET /api/register?q=` |
| seal a case | `POST /api/cases/{id}/seal` |
| records | `GET /api/records` |
| verify a record | `POST /api/records/{id}/verify` `{fields}` |
| approve | `POST /api/records/{id}/approve` `{via, fields}` |
| takedown package | `POST /api/cases/{id}/takedown`, `POST /api/cases/{id}/takedown/{recipient}/prepare` |
| mark a case | `POST /api/cases/{id}/mark` `{as: licensed or not_scam}` |
| watch | `GET /api/watch`, `POST /api/watch/run` |
| feeds (scale) | `GET /api/feeds` |
| drill, scorecard, costs, agents | `GET /api/drill`, `/api/scorecard`, `/api/costs`, `/api/agents` |
| voice | `POST /api/voice/session` → `{value, model, expiresAt}`, `POST /api/voice/usage`, `POST /api/voice/understand` `{text, lang}` → `{tool, args, say}` |

## Tests

`src/test/` drives the whole app with the fake engine, from the user's side:

- The typed path: summary → open case → seal → tamper (verification fails, approval refused) → undo → approve → close.
- A second request changes the card in place: the same card, and the screen never goes back to idle in between.
- An answer with no screen leaves the orb big. An unknown request keeps the card. The × closes it.
- Simulated voice tool calls (the same entry the realtime session uses): summary, show_case, seal, approve by voice, close_card, run_now.
- Realtime events: sound alone only moves the orb. A model tool call reaches the tool layer with its arguments.
- A voice session that cannot start shows a plain message, and typing still works.
- The markers switch, Arabic right-to-left with the English switch, the watch schedule pill, the cost view.
- Studio: the eight pages, replays, seal/tamper/approve in Records, takedown "nothing sent", Check an address, the judges' fakes, Register, Scale, Agents.

Not covered by automated tests: live audio (needs one manual check with a real microphone before the demo), and the look at phone width (checked by hand in Chrome).
