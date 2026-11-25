/* DEV ONLY (vite dev server, never in the build): stands in for the engine's voice endpoints while the engine is not
   merged. Keys are read from the environment or from the file named by ISTIBAQ_ENV_FILE, kept in this process only,
   and never sent to the browser or printed. The browser gets only a short-lived OpenAI client secret.
   - POST /api/dev/voice/session  -> { value, model, expires_at }   (OpenAI realtime client secret)
   - POST /api/dev/voice/usage    -> counts only, for the cost view
   - POST /api/dev/understand     -> { tool, args, say }            (typed text understanding via OpenRouter) */
import fs from 'node:fs';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Plugin } from 'vite';
import { VOICE_INSTRUCTIONS, VOICE_MODEL, VOICE_NAME, VOICE_TOOLS } from '../src/voice/toolSpec';

function readKey(name: string): string | null {
  if (process.env[name]) return process.env[name] || null;
  const file = process.env.ISTIBAQ_ENV_FILE; if (!file) return null;
  try { const m = fs.readFileSync(file, 'utf8').match(new RegExp('^\\s*' + name + '\\s*=\\s*"?([^"\\n\\r]+)"?', 'm')); return m ? m[1].trim() : null; } catch { return null; }
}
const body = (req: IncomingMessage) => new Promise<string>(res => { let b = ''; req.on('data', d => { b += d; if (b.length > 20000) req.destroy(); }); req.on('end', () => res(b)); });
const json = (res: ServerResponse, code: number, o: unknown) => { res.statusCode = code; res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(o)); };

const USAGE = { sessions: 0, failed: 0, seconds: 0, reports: 0 };
const TOOL_LIST = VOICE_TOOLS.map(t => t.name).concat(['chat', 'help']).join(' | ');
const SYS = `You understand a duty officer at Abu Dhabi Police (Gulf Arabic or English) and choose ONE tool from a closed kit: ${TOOL_LIST}.
Reply with JSON only: {"tool":"...","args":{},"say":null}. args: show_case {"n":1..3 or "next"}; check_address {"domain":"..."}; show_run {"view":"both|phone|computer"}.
Guide (Gulf Arabic examples): summary = what do we have today / صباح الخير شو عندنا. show_case = open/show case n (الأولى=1, الثانية=2, الثالثة=3, التالية="next"). check_address = any web address mentioned (args.domain). open_check = wants to check links but gave no address yet (I want to check some links, open check the address, افحص رابط). seal = seal or document the open case as a draft record (وثّقها، اختمها، سوّ محضر). approve = اعتمد / approve it. takedown = prepare removal (جهّز الإزالة). mark_licensed = it is licensed / not a scam (مرخّص). records = list the sealed drafts (المحاضر). how_sure = accuracy. agents = who is working. watch = the schedule, the last round in numbers. run_now = run the watch now (شغّل الجولة الحين). show_run = show the run / how the agent worked; "on the phone / على التلفون" => view phone. scale = how much is born on the internet, how many new sites (كم يولد على الإنترنت). drill = drill, attack and catch. close_card = close the screen (سكّرها، سكّر الشاشة، close it). chat = greetings, thanks. help = anything else. Never invent facts.`;

async function mint() {
  const key = readKey('OPENAI_API_KEY'); if (!key) return { ok: false, why: 'no OPENAI_API_KEY for the dev mint' };
  for (const model of [VOICE_MODEL, VOICE_MODEL + '-mini']) {
    try {
      const r = await fetch('https://api.openai.com/v1/realtime/client_secrets', {
        method: 'POST', signal: AbortSignal.timeout(10000),
        headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json', 'OpenAI-Safety-Identifier': 'istibaq-web-dev' },
        body: JSON.stringify({ expires_after: { anchor: 'created_at', seconds: 300 }, session: { type: 'realtime', model, instructions: VOICE_INSTRUCTIONS, tools: VOICE_TOOLS, tool_choice: 'auto', max_output_tokens: 400,
          audio: { input: { turn_detection: { type: 'semantic_vad', eagerness: 'auto', create_response: true, interrupt_response: true }, transcription: { model: 'gpt-4o-mini-transcribe' } }, output: { voice: VOICE_NAME } } } }),
      });
      const j = await r.json();
      if (r.ok && j.value) { USAGE.sessions++; return { ok: true, value: j.value, expires_at: j.expires_at, model }; }
    } catch { /* try the next model */ }
  }
  USAGE.failed++; return { ok: false, why: 'the voice session could not be minted' };
}

async function understand(text: string, lang: string) {
  const key = readKey('OPENROUTER_API_KEY'); if (!key) return null;
  const r = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST', signal: AbortSignal.timeout(9000),
    headers: { Authorization: 'Bearer ' + key, 'Content-Type': 'application/json', 'X-Title': 'Fahes web (dev)' },
    body: JSON.stringify({ model: process.env.BRAIN_MODEL || 'anthropic/claude-haiku-5.5', max_tokens: 120, temperature: 0, reasoning: { enabled: false },
      messages: [{ role: 'system', content: SYS }, { role: 'user', content: `LANG=${lang}\nOFFICER: ${String(text).slice(0, 300)}` }] }),
  });
  const j = await r.json(); const m = String(j.choices?.[0]?.message?.content || '').match(/\{[\s\S]*\}/);
  return m ? JSON.parse(m[0]) : null;
}

export function devApi(): Plugin {
  return {
    name: 'istibaq-dev-api',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = req.url || '';
        if (!url.startsWith('/api/dev/') || req.method !== 'POST') return next();
        try {
          if (url.startsWith('/api/dev/voice/session')) { const r = await mint(); return json(res, r.ok ? 200 : 503, r); }
          if (url.startsWith('/api/dev/voice/usage')) { const b = JSON.parse((await body(req)) || '{}'); USAGE.reports++; USAGE.seconds += Math.max(0, Math.min(3600, +b.seconds || 0)); return json(res, 200, USAGE); }
          if (url.startsWith('/api/dev/understand')) { const b = JSON.parse((await body(req)) || '{}'); const u = await understand(b.text, b.lang).catch(() => null); return u?.tool ? json(res, 200, u) : json(res, 503, { why: 'no understanding' }); }
        } catch { return json(res, 500, { why: 'dev api failed' }); }
        next();
      });
    },
  };
}
