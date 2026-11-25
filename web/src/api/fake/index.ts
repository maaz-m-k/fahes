/* FAKE ENGINE, built from the approved prototype's data (data/proto-studio). It answers the same EngineClient calls as
   the real engine so the screens run and the tests pass on their own. Everything here is labelled by its marker:
   the three cases are DEMO DATA on .test addresses, the watch round is a REPLAY of a real prototype run,
   the register rule is the prototype's rule (STAND-IN for the engine's layered scorer). */
import type { EngineClient } from '../client';
import type {
  AgentsState, Bi, CaseDetail, CaseSummary, DeskSummary, Feeds, Marker, RecordFields, Round, RoundCase, SealedRecord,
  TakedownPackage, Understanding, WatchState,
} from '../types';
import demo from './demo-data.json';
import runJson from './run.json';
import overview from './overview.json';
import { buildRegister, FAMILIES, normHost, resolve } from './register';
import { match } from '../../voice/matcher';

const DEMO: Marker = { kind: 'demo' };
/* a real browser recording of a LOCAL SYNTHETIC look-alike page (127.0.0.1, fictional names): DEMO DATA */
const FOOT = (import.meta.env?.BASE_URL || '/') + 'demo-footage/';
/* the round overview: a real browser on the Fahes search page showing recorded real results, sped up 3x */
const OVERVIEW_MK: Marker = { kind: 'real', note: 'real browser · recorded real results · Fahes search page' };
const OVERVIEW = {
  computer: { src: FOOT + 'overview-computer.mp4', speed: 3, ...overview.computer, marker: OVERVIEW_MK },
  phone: { src: FOOT + 'overview-phone.mp4', speed: 3, ...overview.phone, marker: OVERVIEW_MK },
};
const SYN: Marker = { kind: 'demo', note: 'synthetic page, real browser recording' };
const LOOKALIKE = {
  server: { src: FOOT + 'lookalike-server.mp4', speed: 1.5, width: 2560, height: 1600, marker: SYN, moments: [{ t: 0, ar: 'حاسوب الشرطة فتح الرابط: صفحة حديقة بريئة (إخفاء).', en: 'The police computer opened the link: a harmless garden page (cloaking).' }] },
  phone: { src: FOOT + 'lookalike-phone.mp4', speed: 1.5, width: 1170, height: 1992, marker: SYN, moments: [{ t: 0, ar: 'الهاتف فتح الرابط نفسه: تحويلات ثم صفحة دفع وهمية.', en: 'The phone opened the same link: redirects, then a fake payment page.' }, { t: 1500, ar: 'صفحة دفع مخالفات وهمية مع حساب مستلم.', en: 'A fake fines payment page with a receiving account.' }] },
};
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
const bi = (ar: string, en: string): Bi => ({ ar, en });

const SAW: Bi[] = [
  bi('رآها: الهاتف في أبوظبي. حاسوب الشرطة عُرضت له صفحة بريئة (إخفاء).', 'Saw through: the phone in Abu Dhabi. The police computer was shown a harmless page (cloaking).'),
  bi('رآها: اسم بنك على استضافة مجانية، خلف رابط قصير.', 'Saw through: a bank name on a free host, behind a short link.'),
  bi('لا شيء يُكشف: مكتب طباعة مرخّص يذكر خدمات حكومية.', 'Nothing to see through: a licensed typing office that mentions government services.'),
];
const VERD_AR = { green: 'رسمي', grey: 'غير رسمي، بدون اتهام', red: 'مشتبه بأنه وهمي، بأسباب' };

export async function sha256(s: string): Promise<string> {
  const b = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join('');
}

export type FakeOptions = { remote?: boolean; latencyMs?: number; now?: () => number };

export function createFakeClient(opts: FakeOptions = {}): EngineClient {
  const now = opts.now || (() => Date.now());
  const lat = opts.latencyMs ?? 0;
  const wait = () => (lat ? sleep(lat) : Promise.resolve());
  const fams = buildRegister();
  const licensed: string[] = [];
  const status: Record<string, CaseSummary['status']> = {};
  const records: Record<string, SealedRecord> = {};
  const prepared: Record<string, Set<string>> = {};
  let watchRunning = false; let runStarted = 0;
  let nextAt = now() + (2 * 60 + 47) * 60e3;
  const ctBase = { size: 1_402_337_120, at: now(), perMin: 3420 };

  const items = demo.items;
  const idx = (id: string) => { const i = items.findIndex(x => x.id === id); if (i < 0) throw new Error('no such case ' + id); return i; };
  const summary = (i: number): CaseSummary => {
    const it = items[i];
    return { id: it.id, n: i + 1, title: it.title, source: it.source, address: it.address, verdict: it.verdict as CaseSummary['verdict'], status: status[it.id] || 'waiting', sawThrough: SAW[i], marker: { kind: 'demo', note: 'REPLAY ' + it.sealedAt } };
  };
  const detail = (i: number): CaseDetail => {
    const it = items[i];
    const fam = FAMILIES.find(f => f.id === it.imitates);
    const imitates = !fam ? null : it.imitates === 'tamm'
      ? { name: bi(fam.ar, fam.en), address: demo.realPath.address, crumbs: demo.realPath.crumbs.ar.map((a, k) => bi(a, demo.realPath.crumbs.en[k])) }
      : { name: bi(fam.ar, fam.en), address: fam.domains[0], crumbs: [bi(fam.ar, fam.en), bi('الموقع الرسمي', 'Official site')] };
    const rec = Object.values(records).find(r => r.caseId === it.id);
    return { ...summary(i), footage: it.id === 'c1' ? LOOKALIKE : null, capturedAt: it.sealedAt, query: it.query, reasons: it.reasons.map(r => ({ code: r.kind, ar: r.ar, en: r.en })), trick: it.trick || null, imitates, recordId: rec?.id || null };
  };
  const desk = (): DeskSummary => {
    const cases = items.map((_, i) => summary(i)).filter(c => c.status !== 'licensed');
    return { needDecision: cases.filter(c => c.status !== 'approved').length, cases, marker: DEMO };
  };
  const fieldsHash = (f: RecordFields) => sha256(JSON.stringify(f));

  const round = (): Round => {
    const shift = (runStarted || runJson.startedAt) - runJson.startedAt;
    return {
      id: runJson.id, startedAt: runJson.startedAt + shift, ms: runJson.ms, shotBase: (import.meta.env?.BASE_URL || '/') + 'demo-run/',
      cases: (runJson.cases as unknown as RoundCase[]).map(c => ({ ...c, startedAt: c.startedAt + shift })),
      footage: OVERVIEW, clips: [], // a slot for extra clips (a real Google clip is added later)
      marker: { kind: 'real', note: 'REPLAY of a real round (sharp capture, 25 Nov)' },
    };
  };
  const watchState = (): WatchState => {
    if (watchRunning && now() - runStarted > 9000) { watchRunning = false; nextAt = now() + 6 * 3600e3; }
    return {
      everyHours: 6, nextAt, running: watchRunning,
      progress: watchRunning ? { i: Math.min(3, Math.floor((now() - runStarted) / 2250)), total: 4 } : null,
      engines: [
        { id: 'duckduckgo', name: 'DuckDuckGo', logo: 'img/duckduckgo.png', first: true },
        { id: 'brave', name: 'Brave', logo: 'img/brave.png', first: false },
        { id: 'mojeek', name: 'Mojeek', logo: 'img/mojeek.png', first: false },
      ],
      lastRound: round(),
      marker: { kind: 'stand', note: 'fake engine: the round is a replay' },
    };
  };

  const takedownPkg = (id: string): TakedownPackage => {
    const i = idx(id); const done = prepared[id] || new Set();
    return { caseId: id, address: items[i].address.split('/')[0], recipients: demo.takedown.to.map((t, k) => ({ id: 'r' + k, name: t, state: done.has('r' + k) ? 'ready' : 'draft' })), sent: false, marker: { kind: 'demo', note: 'nothing is sent' } };
  };

  const client: EngineClient = {
    kind: 'fake',
    async desk() { await wait(); return desk(); },
    async caseDetail(id) { await wait(); return detail(idx(id)); },
    async score(link) {
      await wait();
      return { ...resolve(fams, licensed, link), modelVersion: 'heuristic-proto', marker: { kind: 'stand', note: 'prototype rule' } };
    },
    async register(q) {
      await wait();
      const s = (q || '').toLowerCase();
      const list = fams.filter(f => f.kind !== 'generic' || s).filter(f => !s || f.domains.some(d => d.includes(s)) || f.en.toLowerCase().includes(s) || f.ar.includes(s)).slice(0, 40);
      return {
        total: fams.reduce((a, f) => a + f.domains.length, 0),
        families: list.map(f => ({ id: f.id, name: bi(f.ar, f.en), kind: f.kind, addresses: f.domains, marker: f.kind === 'bank' ? { kind: 'demo', note: 'by hand' } : { kind: 'real', note: f.kind === 'generic' ? 'seed list' : 'family' } })),
        learned: [...licensed], marker: { kind: 'real', note: 'public seed list' },
      };
    },
    async seal(id) {
      await wait();
      const i = idx(id), it = items[i];
      if (it.verdict === 'grey') throw new Error('a grey case is not sealed; it is not accused');
      const existing = Object.values(records).find(r => r.caseId === id); if (existing) return existing;
      const t = new Date(now());
      const fields: RecordFields = {
        time: t.toLocaleString('ar-AE-u-nu-latn', { timeZone: 'Asia/Dubai', dateStyle: 'medium', timeStyle: 'medium' }) + ' (توقيت أبوظبي)',
        source: it.source.ar, query: it.query.ar, address: it.address, verdict: VERD_AR[it.verdict as 'red'], reasons: it.reasons.map(r => r.ar),
        captures: ['placeholder:police-computer', 'placeholder:abu-dhabi-phone'],
      };
      const rec: SealedRecord = { id: 'ISB-DEMO-' + String(t.getTime()).slice(-6) + i, caseId: id, caseN: i + 1, title: it.title, sealedAt: t.getTime(), fields, fingerprint: await fieldsHash(fields), status: 'draft', approvedVia: null, marker: { kind: 'real', note: 'SHA-256' } };
      records[rec.id] = rec; status[id] = 'sealed';
      return rec;
    },
    async records() { await wait(); return Object.values(records).sort((a, b) => a.sealedAt - b.sealedAt); },
    async verifyRecord(rid, fields) {
      const rec = records[rid]; if (!rec) throw new Error('no such record');
      const h = await fieldsHash(fields); return { ok: h === rec.fingerprint, fingerprintNow: h };
    },
    async approve(rid, via, fields) {
      await wait();
      const rec = records[rid];
      if (!rec) return { approved: false, why: bi('لا شيء مختوم بعد.', 'Nothing sealed yet.'), via, fingerprint: '', takedownReady: false };
      if (fields) { const v = await client.verifyRecord(rid, fields); if (!v.ok) return { approved: false, why: bi('فشل التحقق: تغيّر حرف بعد الختم. لا اعتماد.', 'Verification failed: a letter changed after the seal. No approval.'), via, fingerprint: v.fingerprintNow, takedownReady: false }; }
      if (rec.status !== 'approved') { rec.status = 'approved'; rec.approvedVia = via; status[rec.caseId] = 'approved'; }
      return { approved: true, why: null, via: rec.approvedVia || via, fingerprint: rec.fingerprint, takedownReady: true };
    },
    async takedown(id) { await wait(); return takedownPkg(id); },
    async prepareRecipient(id, rid) { await wait(); (prepared[id] ||= new Set()).add(rid); return takedownPkg(id); },
    async markCase(id, _as) {
      await wait();
      const host = normHost(items[idx(id)].address); if (!licensed.includes(host)) licensed.push(host);
      status[id] = 'licensed'; return detail(idx(id));
    },
    async watch() { await wait(); return watchState(); },
    async runWatch() { await wait(); if (!watchRunning) { watchRunning = true; runStarted = now(); } return watchState(); },
    async feeds(): Promise<Feeds> {
      await wait();
      const t = now(); const size = Math.round(ctBase.size + (t - ctBase.at) / 60000 * ctBase.perMin);
      const spark = Array.from({ length: 30 }, (_, k) => Math.round(size - (29 - k) * 114 + ((k * 37) % 11) * 9));
      return {
        ct: { log: 'DigiCert Wyvern 2027h1', size, at: t, perMin: ctBase.perMin, spark, marker: { kind: 'demo', note: 'LIVE once the engine ships' } },
        names: { total: 712_440, branded: 1_318, lookAlikes: 214, source: 'newly registered domains (7 days)', marker: { kind: 'demo' } },
        needDecision: desk().needDecision,
        funnel: demo.funnel.stages.map(s => ({ n: s.n, label: bi(s.ar, s.en), marker: s.src === 'BORROWED' ? { kind: 'real' as const, note: 'BORROWED' } : DEMO })),
      };
    },
    async drill() {
      await wait();
      const T = (rows: [string, string, string][]) => rows.map(([t, ar, en]) => ({ t, line: bi(ar, en) }));
      return {
        drill: T([['0:00', 'نُشرت صفحة التمرين fahes-drill.example (علامتنا، بلا نموذج، والمنظمون على علم)', 'Drill page published: fahes-drill.example (our brand, no form, organisers told)'], ['4:10', 'وكيل الحجم رآها في سجل الشهادات العام', 'Scale agent saw it in the public certificate log'], ['4:12', 'وكيل السجل: ليست في سجل أبوظبي الحقيقي', 'Register agent: not in the register of the real Abu Dhabi'], ['5:30', 'وكيل الالتقاط: لقطتان، حاسوب وهاتف', 'Capture agent: two captures, computer and phone'], ['6:40', 'وكيل الختم: مسودة وبصمة. بانتظار الضابط', 'Seal agent: draft and fingerprint. Waiting for the officer']]),
        attacker: T([['06:00', 'المحتال يشتري اسماً يشبه «تم» ويضع عليه شهادة', 'The fraudster buys a TAMM-like name and puts a certificate on it'], ['06:04', 'وكيل الحجم: الاسم ظهر في سجل الشهادات', 'Scale agent: the name appears in the certificate log'], ['07:30', 'ينسخ صفحة دفع بأداة جاهزة ويخفيها عن حواسيب الشرطة', 'Copies a payment page with a ready kit and hides it from police computers'], ['09:00', 'يشتري إعلاناً على «دفع مخالفات المرور»', 'Buys an ad on "pay traffic fines"'], ['09:20', 'وكيل الرصد: الهاتف رأى الإعلان، والحاسوب رأى صفحة بريئة', 'Watch agent: the phone saw the ad, the computer saw a harmless page'], ['09:21', 'وكيل التحقق: أحمر بسببين؛ وكيل الختم: مسودة', 'Check agent: red with two reasons; Seal agent: a draft']]),
        marker: { kind: 'demo', note: 'example timeline' },
      };
    },
    async scorecard() {
      await wait(); const s = demo.scorecard;
      return { rows: [
        { value: s.easy.pct + '%', label: bi(s.easy.ar, s.easy.en), marker: { kind: 'real', note: 'measured earlier' } },
        { value: '~' + s.honest.caught + '%', label: bi(`عند ${s.honest.falseAlarms}% إنذارات خاطئة، ${s.honest.ar}`, `at ${s.honest.falseAlarms}% false alarms, ${s.honest.en}`), marker: { kind: 'real', note: 'measured earlier' } },
        { value: 'X / Y', label: bi(s.sealed.ar, s.sealed.en), marker: { kind: 'stand', note: 'not run' } },
      ] };
    },
    async costs() {
      await wait();
      return {
        soFar: [
          { item: bi('الصوت الفوري (تقدير)', 'Realtime voice (estimate)'), usd: 0.89, marker: { kind: 'real', note: 'prototype counter' } },
          { item: bi('دماغ OpenRouter', 'OpenRouter brain'), usd: 0.0063, marker: { kind: 'real', note: 'prototype counter' } },
          { item: bi('البحث والخرائط', 'Search and maps'), usd: 0, marker: { kind: 'stand', note: 'engine not live' } },
        ],
        projectedMonthUsd: 180, projectedNote: bi('تقدير: جولة كل 6 ساعات + 30 دقيقة صوت يومياً.', 'Estimate: a round every 6 hours + 30 minutes of voice a day.'),
        marker: { kind: 'demo', note: 'projection' },
      };
    },
    async agents(): Promise<AgentsState> {
      await wait();
      const w = watchState(), r = w.lastRound;
      if (!r || !r.cases.length) return { agents: [], lastCase: null };
      const k = r.cases[r.cases.length - 1];
      const c = r.cases.reduce((a, x) => ({ read: a.read + x.counts.read, green: a.green + x.counts.green, grey: a.grey + x.counts.grey, red: a.red + x.counts.red }), { read: 0, green: 0, grey: 0, red: 0 });
      const diffs = r.cases.reduce((a, x) => a + x.onlyPhone.length + x.onlyComputer.length, 0);
      const shots = r.cases.reduce((a, x) => a + x.computer.steps.length + x.phone.steps.length, 0);
      const sealedN = Object.keys(records).length; const op = k.computer.opened || k.phone.opened;
      const REAL: Marker = { kind: 'real' };
      return {
        agents: [
          { id: 'watch', name: bi('الرصد', 'Watch'), status: w.running ? bi(`يبحث الآن ${w.progress!.i + 1}/4`, `searching ${w.progress!.i + 1}/4`) : bi(`${r.cases.length} بحث · ${r.cases.length * 2} منظر · ${diffs} اختلاف`, `${r.cases.length} searches · ${r.cases.length * 2} views · ${diffs} differences`), busy: w.running, marker: REAL },
          { id: 'register', name: bi('السجل', 'Register'), status: bi(`${fams.reduce((a, f) => a + f.domains.length, 0)} عنواناً · تعلّم ${licensed.length}`, `${fams.reduce((a, f) => a + f.domains.length, 0)} addresses · learned ${licensed.length}`), busy: false, marker: REAL },
          { id: 'check', name: bi('التحقق', 'Check'), status: bi(`${c.green} أخضر · ${c.grey} رمادي · ${c.red} أحمر`, `${c.green} green · ${c.grey} grey · ${c.red} red`), busy: w.running, marker: REAL },
          { id: 'capture', name: bi('الالتقاط', 'Capture'), status: bi(`${shots} لقطة`, `${shots} captures`), busy: w.running, marker: REAL },
          { id: 'seal', name: bi('الختم', 'Seal'), status: bi(`${sealedN} مسودة مختومة`, `${sealedN} drafts sealed`), busy: false, marker: REAL },
          { id: 'drill', name: bi('التمرين', 'Drill'), status: bi('آخر تمرين 6:40 (مثال)', 'last drill 6:40 (example)'), busy: false, marker: DEMO },
          { id: 'scale', name: bi('الحجم', 'Scale'), status: bi(`${ctBase.perMin.toLocaleString('en-US')} في الدقيقة`, `${ctBase.perMin.toLocaleString('en-US')} a minute`), busy: true, marker: { kind: 'demo', note: 'LIVE once the engine ships' } },
        ],
        lastCase: {
          query: bi(k.ar, k.q), at: k.startedAt, marker: { kind: 'real', note: 'last real case' },
          steps: [
            { agent: 'watch', line: bi(`وكيل الرصد بحث «${k.ar}» على الحاسوب والهاتف معاً`, `The Watch agent searched "${k.q}" on computer and phone together`) },
            { agent: 'register', line: bi(`وكيل السجل: ${k.counts.green} من ${k.counts.read} عنواناً في السجل`, `Register agent: ${k.counts.green} of ${k.counts.read} addresses are in the register`) },
            { agent: 'check', line: bi(`وكيل التحقق: ${k.counts.green} أخضر، ${k.counts.grey} رمادي، ${k.counts.red} أحمر`, `Check agent: ${k.counts.green} green, ${k.counts.grey} grey, ${k.counts.red} red`) },
            { agent: 'capture', line: op ? bi(`وكيل الالتقاط: صوّر ${op.landed}، الصفحة الرسمية فقط`, `Capture agent: captured ${op.landed}, the official page only`) : bi('وكيل الالتقاط: لا صفحة رسمية لتصويرها', 'Capture agent: no official page to capture') },
            { agent: 'seal', line: bi('وكيل الختم: لا شيء يُختم، لا أحمر', 'Seal agent: nothing to seal, no red') },
            { agent: 'officer', line: bi('لا قرار مطلوب منك في هذه الحالة', 'No decision needed from you on this case') },
          ],
        },
      };
    },
    async voiceSession() {
      if (!opts.remote) throw new Error('no voice in the fake engine');
      const r = await fetch('/api/dev/voice/session', { method: 'POST' });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.value) throw new Error(j.why || 'the voice key could not be made (' + r.status + ')');
      return { value: j.value, model: j.model, expiresAt: j.expires_at };
    },
    async voiceUsage(report) { if (opts.remote) await fetch('/api/dev/voice/usage', { method: 'POST', body: JSON.stringify(report) }).catch(() => undefined); },
    async understand(text, lang): Promise<Understanding> {
      if (opts.remote) {
        try {
          const r = await fetch('/api/dev/understand', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, lang }) });
          if (r.ok) { const j = await r.json(); if (j.tool) return { tool: j.tool, args: j.args || {}, say: j.say || null, source: 'model' }; }
        } catch { /* fall back */ }
      }
      return match(text);
    },
  };
  return client;
}
