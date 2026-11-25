/* The desk against the real Fahes engine (istibaq/api/app.py). Maps the engine's responses onto the screens' shapes;
   every number, verdict and name comes from the engine. Where the engine has nothing yet (no round has run), the
   recorded footage of an earlier round is shown. */
import type { EngineClient } from './client';
import { EngineError } from './client';
import { createFakeClient } from './fake';
import type {
  AgentId, AgentsState, ApproveResult, Bi, CaseDetail, CaseSummary, Costs, DeskSummary, DrillInfo, Feeds,
  RecordFields, Reason, RegisterList, Round, RoundCase, ScoreResult, SealedRecord, TakedownPackage, Verdict, WatchState,
} from './types';
import { match } from '../voice/matcher';

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const bi = (ar: string, en: string): Bi => ({ ar, en });
const host = (u: string) => { try { return new URL(/^[a-z]+:\/\//i.test(u) ? u : 'https://' + u).hostname.replace(/^www\./, ''); } catch { return u; } };
const ms = (iso?: string | null) => (iso ? Date.parse(iso) : Date.now());
const clock = (iso?: string | null) => new Date(ms(iso)).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Dubai' });
const reasons = (v: Raw | null | undefined): Reason[] => (v?.reasons || []).map((r: Raw) => ({ code: r.code, ar: r.ar, en: r.en }));
const SOURCE: Record<string, Bi> = {
  manual: bi('أُضيفت يدوياً', 'Added by hand'), watch: bi('الرصد', 'The watch'),
  'brave/organic': bi('نتائج بحث Brave', 'Brave search results'), 'places/maps': bi('الخرائط', 'Maps'),
  'publiclist/openphish': bi('قائمة احتيال عامة: OpenPhish (مع ذكر المصدر)', 'public scam list: OpenPhish (credited)'),
  'publiclist/phishtank': bi('قائمة احتيال عامة: PhishTank (مع ذكر المصدر)', 'public scam list: PhishTank (credited)'),
  'serper/ad': bi('إعلانات جوجل', 'Google ads'), 'dataforseo/ad': bi('إعلانات جوجل', 'Google ads'), 'dataforseo/organic': bi('نتائج جوجل', 'Google results'),
};
const source = (s: string): Bi => SOURCE[s] || bi(s, s);
function brand(v: Raw | null | undefined) {
  const r = (v?.reasons || []).find((x: Raw) => x.evidence?.official_domains?.length);
  return r ? { ar: r.evidence.brand_ar as string, en: r.evidence.brand_en as string, domains: r.evidence.official_domains as string[] } : null;
}
function trickOf(link: string) {
  let u: URL; try { u = new URL(/^[a-z]+:\/\//i.test(link) ? link : 'https://' + link); } catch { return null; }
  const labels = u.hostname.replace(/^www\./, '').split('.');
  const n = labels.length >= 3 && labels.at(-2)!.length <= 3 ? 3 : 2; // e.g. example.co.ae
  const owner = labels.slice(-n).join('.'), decoy = labels.slice(0, -n).join('.');
  return { decoy: decoy ? decoy + '.' : '', owner, rest: (u.pathname === '/' ? '' : u.pathname) + u.search };
}

export function engineClient(base = ''): EngineClient {
  const call = async <T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> => {
    const r = await fetch(base + path, {
      method: init?.method || (init?.body !== undefined ? 'POST' : 'GET'),
      headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
    if (!r.ok) {
      let j: Raw = {}; try { j = await r.json(); } catch { /* not json */ }
      throw new EngineError(r.status, String(j.detail || r.status), j.detail_ar);
    }
    return r.json() as Promise<T>;
  };
  const post = <T>(path: string, body: unknown = {}) => call<T>(path, { method: 'POST', body });
  const demo = createFakeClient(); // recorded footage and timelines, used only where the engine has none yet
  const prepared: Record<string, Set<string>> = {};
  let order: string[] = []; // case ids in the officer's list order

  const summaryOf = (c: Raw, i: number, full?: Raw): CaseSummary => ({
    id: String(c.id), n: i + 1, address: c.link, verdict: c.verdict as Verdict,
    title: c.name_hidden ? bi('موقع غير رسمي (الاسم مخفي)', 'A site that is not official (name hidden)') : bi(host(c.link), host(c.link)),
    source: source(c.source),
    status: c.status === 'approved' ? 'approved' : c.status === 'licensed' || c.status === 'not_scam' ? 'licensed' : c.sealed || c.record ? 'sealed' : 'waiting',
    sawThrough: (() => { const s = (full?.capture?.saw_through || []) as string[]; return s.length ? bi(s.join(' · '), s.join(' · ')) : bi('', ''); })(),
  });
  const recordOf = (c: Raw): SealedRecord | null => {
    const r = c.record; if (!r) return null;
    const b = r.body || {};
    const fields: RecordFields = {
      time: b.time || r.sealed_at, source: (source(b.source || c.source).ar), query: '', address: b.address || c.link,
      verdict: b.status_ar || b.verdict || c.verdict, reasons: (b.reasons || []).map((x: Raw) => x.ar), captures: (b.captures || []).map((x: Raw) => String(x.path || x)),
    };
    const approved = (r.approvals || []).length > 0;
    return { id: String(c.id), caseId: String(c.id), caseN: Math.max(1, order.indexOf(String(c.id)) + 1), title: bi(host(c.link), host(c.link)),
      sealedAt: ms(r.sealed_at), fields, fingerprint: r.sha256, status: approved ? 'approved' : 'draft',
      approvedVia: approved ? r.approvals[0].method : null };
  };
  const detailOf = (c: Raw): CaseDetail => {
    const i = Math.max(0, order.indexOf(String(c.id)));
    const v = c.verdict_full || {}; const b = brand(v);
    const cap = c.capture || {};
    const vid = (x: Raw | undefined) => (x?.video ? { src: `${base}/media/captures/${c.id}/${x.video}`, speed: 3, width: 0, height: 0, moments: [] } : undefined);
    const footage = cap.server?.video || cap.phone?.video ? { server: vid(cap.server), phone: vid(cap.phone) } : null;
    return {
      ...summaryOf(c, i, c), capturedAt: clock(c.opened_at), query: source(c.source), reasons: reasons(v),
      trick: c.verdict === 'red' && b ? trickOf(c.link) : null,
      imitates: b ? { name: bi(b.ar, b.en), address: b.domains[0], crumbs: [bi(b.ar, b.en), bi('الموقع الرسمي', 'Official site')] } : null,
      recordId: c.record ? String(c.id) : null, footage,
    };
  };
  const scoreOf = (v: Raw, link: string): ScoreResult => {
    const b = brand(v);
    return { host: host(link), verdict: v.verdict, family: b ? bi(b.ar, b.en) : null, officialAddresses: v.verdict === 'green' && b ? b.domains : [],
      reasons: reasons(v), modelVersion: v.model_version || '' };
  };

  const client: EngineClient = {
    kind: 'http',
    async desk(): Promise<DeskSummary> {
      const open: Raw[] = await call('/api/cases?status=open&reveal=true');
      const rank = { red: 0, grey: 1, green: 2 } as Record<string, number>;
      open.sort((a, b) => (rank[a.verdict] - rank[b.verdict]) || b.score - a.score);
      order = open.map(c => String(c.id));
      const cases = open.slice(0, 12).map((c, i) => summaryOf(c, i));
      return { needDecision: open.length, cases };
    },
    async caseDetail(id) { return detailOf(await call(`/api/cases/${encodeURIComponent(id)}?reveal=true`)); },
    async score(link) { return scoreOf(await post('/api/score', { link, mode: 'officer' }), link); },
    async scoreBatch(links) {
      const out: ScoreResult[] = [];
      for (let i = 0; i < links.length; i += 1000) { // the server takes at most 1,000 links a request
        const chunk = links.slice(i, i + 1000);
        const r: Raw = await post('/api/score/batch', { links: chunk, mode: 'judging' });
        (r.results as Raw[]).forEach((v, k) => out.push({ ...scoreOf(v, v.link || chunk[k]), link: v.link || chunk[k], score: v.score }));
      }
      return out;
    },
    async register(q): Promise<RegisterList> {
      const r: Raw = await call('/api/register/families' + (q ? '?q=' + encodeURIComponent(q) : ''));
      return { total: r.total, learned: [],
        families: r.families.map((f: Raw) => ({ id: f.id, name: bi(f.name_ar, f.name_en), kind: f.official ? 'gov' : 'bank', addresses: f.domains })) };
    },
    async seal(caseId) { await post(`/api/cases/${caseId}/seal`); return recordOf(await call(`/api/cases/${caseId}?reveal=true`))!; },
    async records() {
      const all: Raw[] = await call('/api/cases?reveal=true');
      const sealed = await Promise.all(all.filter(c => c.sealed).slice(0, 20).map(c => call<Raw>(`/api/cases/${c.id}?reveal=true`)));
      return sealed.map(recordOf).filter(Boolean) as SealedRecord[];
    },
    async verifyRecord(id, fields) {
      const r: Raw = await post(`/api/cases/${id}/verify`, { address: fields.address });
      return { ok: !!r.ok, fingerprintNow: r.fingerprint_now };
    },
    async approve(id, via, fields): Promise<ApproveResult> {
      if (fields) { const v = await client.verifyRecord(id, fields); if (!v.ok) return { approved: false, why: bi('فشل التحقق: تغيّر حرف بعد الختم. لا اعتماد.', 'Verification failed: a letter changed after the seal. No approval.'), via, fingerprint: v.fingerprintNow, takedownReady: false }; }
      try {
        const r: Raw = await post(`/api/cases/${id}/approve`, { method: via });
        return { approved: true, why: null, via: r.approvals?.at(-1)?.method || via, fingerprint: r.sha256, takedownReady: true };
      } catch (e) { return { approved: false, why: bi('رفض المحرك الاعتماد: ' + (e as Error).message, 'The engine refused: ' + (e as Error).message), via, fingerprint: '', takedownReady: false }; }
    },
    async takedown(caseId): Promise<TakedownPackage> {
      const p: Raw = await call(`/api/cases/${caseId}/takedown`);
      const done = prepared[caseId] || new Set();
      const to = [bi('مسجّل النطاق ومزوّد الاستضافة', 'The domain registrar and the host'), bi('تنبيه مستفيد للبنك', 'A payee alert to the bank'), bi('StaySafe: فاحص الروابط العام', 'StaySafe, the public link checker')];
      return { caseId, address: host(p.address), recipients: to.map((name, k) => ({ id: 'r' + k, name, state: done.has('r' + k) ? 'ready' : 'draft' })), sent: false };
    },
    async prepareRecipient(caseId, rid) { (prepared[caseId] ||= new Set()).add(rid); return client.takedown(caseId); },
    async markCase(caseId, as) { await post(`/api/cases/${caseId}/mark`, { status: as }); return client.caseDetail(caseId); },
    async watch(): Promise<WatchState> {
      const [sched, last]: [Raw, Raw] = await Promise.all([call<Raw>('/api/watch/schedule'), call<Raw>('/api/watch/last')]);
      const every = sched.every_hours || 6;
      const started = last?.started_at ? ms(last.started_at) : null;
      const running = !!last?.started_at && !last.finished_at;
      const demoRound = (await demo.watch()).lastRound!;
      let lastRound: Round = demoRound;
      if (last?.id && last.finished_at) {
        const rep: Raw = await call(`/api/watch/runs/${last.id}/replay?reveal=true`);
        lastRound = roundOf(last, rep.steps || [], demoRound, base);
      }
      return { everyHours: every, nextAt: started ? started + every * 3600e3 : Date.now() + 60e3, running, progress: running ? { i: 0, total: 4 } : null,
        engines: [{ id: 'brave', name: 'Brave', logo: 'img/brave.png', first: true }, { id: 'duckduckgo', name: 'DuckDuckGo', logo: 'img/duckduckgo.png', first: false }, { id: 'mojeek', name: 'Mojeek', logo: 'img/mojeek.png', first: false }],
        lastRound };
    },
    async runWatch() {
      await post('/api/watch/run?wait=false'); // a 429 (once per 10 minutes) surfaces as an EngineError with a plain message
      const w = await client.watch(); return { ...w, running: true, progress: { i: 0, total: 4 } };
    },
    async feeds(): Promise<Feeds> {
      // the server counts in the background and answers from its cache at once; it says "warming" right after a start
      const [f, d]: [Raw, DeskSummary] = await Promise.all([call<Raw>('/api/feeds').catch(() => ({ status: 'error' })), client.desk()]);
      const ct = f.certificates || {}, nd = f.new_domains || {};
      const perMin = ct.rate_per_hour ? Math.round(ct.rate_per_hour / 60) : null;
      const looks = (nd.lookalikes || []).length + (ct.lookalikes || []).length;
      const names = nd.total ? { total: nd.total, branded: looks, lookAlikes: looks, source: nd.source || '' } : null;
      return {
        updatedAt: f.updated_at ? ms(f.updated_at) : null,
        ct: perMin ? { log: ct.source || 'CT log', size: ct.total || 0, at: ms(ct.at || f.at), perMin, spark: [] } : null,
        names, needDecision: d.needDecision,
        funnel: names ? [
          { n: names.total, label: bi(`أسماء نطاقات جديدة (${names.source})`, `new domain names (${names.source})`) },
          { n: looks, label: bi('تشبه اسماً رسمياً من الإمارات', 'look like an official UAE name') },
          { n: d.needDecision, label: bi('تحتاج قرارك', 'need your decision') },
        ] : [],
      };
    },
    async drill(): Promise<DrillInfo> { return demo.drill(); },
    async scorecard() {
      const s: Raw = await call('/api/scorecard');
      const o = s.scorecard?.overall_counted;
      if (!o) return demo.scorecard();
      const pct = (x: number) => (x * 100).toFixed(1) + '%';
      return { rows: [
        { value: pct(o.catch_rate), label: bi(`نسبة الالتقاط على ${o.fakes} رابطاً وهمياً حديثاً (مدى 95%: ${pct(o.catch_range95[0])}–${pct(o.catch_range95[1])})`, `Catch rate on ${o.fakes} fresh fake links (95% range ${pct(o.catch_range95[0])}–${pct(o.catch_range95[1])})`) },
        { value: pct(o.false_alarm_rate), label: bi(`إنذارات خاطئة على ${o.reals} عنواناً إماراتياً حقيقياً`, `False alarms on ${o.reals} real UAE addresses`) },
      ] };
    },
    async costs(): Promise<Costs> {
      const c: Raw = await call('/api/costs');
      const s = c.summary || {};
      return { soFar: (s.by_service || []).map((x: Raw) => ({ item: bi(x.service, x.service), usd: x.usd ?? x.amount_usd ?? 0 })),
        projectedMonthUsd: s.projection?.monthly_usd ?? 0, projectedNote: bi(s.projection?.note_ar || '', s.projection?.note_en || '') };
    },
    async agents(): Promise<AgentsState> {
      const a: Raw[] = await call('/api/agents');
      const names: Record<string, Bi> = { watch: bi('الرصد', 'Watch'), register: bi('السجل', 'Register'), check: bi('التحقق', 'Check'), capture: bi('الالتقاط', 'Capture'), seal: bi('الختم', 'Seal'), drill: bi('التمرين', 'Drill'), scale: bi('الحجم', 'Scale') };
      const st = (x: Raw): Bi => {
        if (x.agent === 'seal') return bi(`${x.sealed_records} مسودة مختومة`, `${x.sealed_records} drafts sealed`);
        if (x.agent === 'register') return bi(`${x.edits} تعديل من الضباط`, `${x.edits} officer edits`);
        if (x.agent === 'watch') return x.last_run_at ? bi(`آخر جولة ${clock(x.last_run_at)}`, `last round ${clock(x.last_run_at)}`) : bi('لا جولة بعد', 'no round yet');
        if (x.agent === 'drill') return bi(`${x.drills} تمرين`, `${x.drills} drills`);
        return x.status === 'live' ? bi('يعمل', 'live') : bi('غير متاح', 'unavailable');
      };
      const demoAgents = await demo.agents();
      return { agents: a.map(x => ({ id: x.agent as AgentId, name: names[x.agent] || bi(x.agent, x.agent), status: st(x), busy: false })),
        lastCase: demoAgents.lastCase };
    },
    async voiceSession() {
      const j: Raw = await post('/api/voice/session');
      return { value: j.client_secret || j.value, model: j.model, expiresAt: j.expires_at || 0, sessionId: j.session_id, maxSeconds: j.max_seconds };
    },
    async voiceUsage(report) { await post('/api/voice/usage', { session_id: report.sessionId ?? null, seconds: report.seconds ?? null, model: report.model }).catch(() => undefined); },
    async understand(text) { return match(text); }, // typed text goes to the live voice session; this is the fallback
  };
  return client;
}

/* a real round from the engine's replay steps: per question, what was read and how it was judged */
function roundOf(run: Raw, steps: Raw[], demoRound: Round, base: string): Round {
  const byQ = new Map<string, RoundCase>();
  let q = '';
  for (const s of steps) {
    const d = s.detail || {};
    if (s.action === 'ask') {
      q = d.query || q;
      if (!byQ.has(q)) byQ.set(q, { id: 'q' + byQ.size, q, ar: q, startedAt: ms(s.time), ms: d.ms || 0, counts: { read: 0, green: 0, grey: 0, red: 0 }, onlyPhone: [], onlyComputer: [],
        computer: { engine: d.source || '', steps: [], results: [], opened: null, robot: [] }, phone: { engine: '', steps: [], results: [], opened: null, robot: [] } });
    }
    if ((s.action === 'score' || s.action === 'flag') && byQ.has(q)) {
      const k = byQ.get(q)!; const v = (d.verdict || 'grey') as Verdict;
      k.counts.read++; k.counts[v]++;
      k.computer.results.push({ host: host(String(d.link || '')), verdict: v });
    }
  }
  const rec = steps.filter(s => s.action === 'record' && s.detail?.video);
  const vid = (view: string) => {
    const s = rec.find(x => x.detail.view === view); if (!s) return undefined;
    const path = String(s.detail.video).split('/footage/').pop();
    return { src: `${base}/media/footage/${path}`, speed: 3, width: view === 'phone' ? 1170 : 2560, height: view === 'phone' ? 1992 : 1600, moments: [] };
  };
  const footage = rec.length ? { computer: vid('computer'), phone: vid('phone') } : demoRound.footage;
  return { id: String(run.id), startedAt: ms(run.started_at), ms: ms(run.finished_at) - ms(run.started_at), shotBase: '', cases: byQ.size ? [...byQ.values()] : demoRound.cases,
    footage: footage || undefined, clips: [] };
}
