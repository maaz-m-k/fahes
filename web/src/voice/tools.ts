/* The tool layer: the voice model's tool calls and the typed path both land here. Each tool calls the engine through
   the EngineClient and returns (1) what the answer card should show, from the closed kit, (2) a short line to say,
   (3) the facts to hand back to the voice model. Nothing here invents a number, name, address or verdict. */
import type { EngineClient } from '../api/client';
import type {
  AgentsState, Bi, CaseDetail, DeskSummary, DrillInfo, Feeds, RecordFields, Round, ScoreResult, Scorecard, SealedRecord,
  TakedownPackage, ToolName, WatchState,
} from '../api/types';

export type View = 'both' | 'phone' | 'computer';
export type Card =
  | { kind: 'summary'; desk: DeskSummary }
  | { kind: 'case'; detail: CaseDetail }
  | { kind: 'verdict'; score: ScoreResult }
  | { kind: 'check'; results: ScoreResult[] }
  | { kind: 'record'; record: SealedRecord }
  | { kind: 'done'; items: { text: Bi; no?: boolean }[] }
  | { kind: 'replay'; round: Round; ci: number; view: View }
  | { kind: 'round'; watch: WatchState }
  | { kind: 'scale'; feeds: Feeds }
  | { kind: 'agents'; agents: AgentsState }
  | { kind: 'takedown'; pkg: TakedownPackage }
  | { kind: 'drill'; drill: DrillInfo }
  | { kind: 'scorecard'; scorecard: Scorecard }
  | { kind: 'records'; records: SealedRecord[] };

export type Chip = { label: Bi; tool: ToolName; args?: Record<string, unknown> };
export type Answer = { tool: ToolName; words: Bi; card: Card; chips: Chip[] };
export type ToolResult = {
  answer: Answer | null; // null: this answer needs no screen
  close?: boolean; // the officer asked to close the card
  say: Bi;
  output: Record<string, unknown>; // facts for the voice model (function_call_output)
  keep?: boolean; // no screen for this one, but leave the card as it is (an unknown request or a refusal)
};

/* what the desk remembers between tool calls */
export type ToolContext = {
  focusCaseId: string | null;
  edits: Record<string, RecordFields>; // record id -> fields as currently shown (a tamper shows here)
  checks: ScoreResult[]; // links checked in the voice card's checker, newest first
};

const bi = (ar: string, en: string): Bi => ({ ar, en });
const chip = (ar: string, en: string, tool: ToolName, args?: Record<string, unknown>): Chip => ({ label: bi(ar, en), tool, args });
const VERD: Record<string, Bi> = { green: bi('رسمي', 'Official'), grey: bi('غير رسمي، بدون اتهام', 'Not official, not accused'), red: bi('مشتبه بأنه وهمي، بأسباب', 'Suspected fake, with reasons') };
const fmt = (n: number | null | undefined) => (n == null ? '…' : Math.round(n).toLocaleString('en-US'));

/* the suggestions after the morning summary; saying one out loud calls the same tool */
export const SUMMARY_CHIPS: Chip[] = [chip('افتح الحالة الأولى', 'Open the first case', 'show_case', { n: 1 }), chip('افحص رابطاً', 'Check a link', 'open_check'), chip('أعد آخر جولة', 'Replay the last run', 'show_run', { view: 'both' })];

export const TOOL_NAMES: ToolName[] = ['summary', 'show_case', 'check_address', 'open_check', 'show_run', 'seal', 'approve', 'scale', 'run_now', 'agents', 'close_card', 'takedown', 'mark_licensed', 'records', 'how_sure', 'drill', 'watch', 'chat', 'help'];

function nextIn(ms: number, lang: 'ar' | 'en') { const d = Math.max(0, ms); const h = Math.floor(d / 3600e3), m = Math.floor((d % 3600e3) / 60e3); return lang === 'ar' ? `${h} س ${m} د` : `${h} h ${m} min`; }
export const nextInBi = (at: number, now = Date.now()): Bi => ({ ar: nextIn(at - now, 'ar'), en: nextIn(at - now, 'en') });
/* "updated N minutes ago" for numbers the server counted in the background */
export function agoBi(at: number, now = Date.now()): Bi {
  const m = Math.max(0, Math.round((now - at) / 60e3));
  if (m < 1) return bi('حُدّثت الآن', 'updated just now');
  if (m < 120) return bi(`حُدّثت قبل ${m} دقيقة`, `updated ${m} minute${m === 1 ? '' : 's'} ago`);
  const h = Math.round(m / 60); return bi(`حُدّثت قبل ${h} ساعة`, `updated ${h} hours ago`);
}

async function focusCase(c: EngineClient, ctx: ToolContext): Promise<CaseDetail | null> {
  if (ctx.focusCaseId) return c.caseDetail(ctx.focusCaseId);
  const d = await c.desk(); const first = d.cases.find(x => x.verdict === 'red') || d.cases[0];
  if (!first) return null; ctx.focusCaseId = first.id; return c.caseDetail(first.id);
}

export async function runTool(c: EngineClient, ctx: ToolContext, name: ToolName, args: Record<string, unknown> = {}, via: 'voice' | 'click' = 'click'): Promise<ToolResult> {
  switch (name) {
    case 'summary': {
      const desk = await c.desk();
      return {
        answer: { tool: name, words: bi(`${desk.needDecision} تحتاج قرارك`, `${desk.needDecision} need your decision`), card: { kind: 'summary', desk }, chips: SUMMARY_CHIPS },
        say: bi(`صباح النور. ${desk.needDecision} تحتاج قرارك اليوم. أفتح الحالة الأولى؟`, `Good morning. ${desk.needDecision} need your decision today. Shall I open the first case?`),
        output: { needDecision: desk.needDecision, cases: desk.cases.map(x => ({ n: x.n, title: x.title.en, verdict: x.verdict, source: x.source.en })) },
      };
    }
    case 'show_case': {
      const desk = await c.desk();
      let n = args.n === 'next' ? null : Number(args.n || 1);
      if (n == null) { const cur = desk.cases.findIndex(x => x.id === ctx.focusCaseId); n = Math.min(desk.cases.length, cur + 2); }
      const pick = desk.cases[Math.max(0, Math.min(desk.cases.length - 1, n - 1))];
      if (!pick) return { answer: null, keep: true, say: bi('لا حالات تنتظرك.', 'No cases are waiting.'), output: { error: 'no cases' } };
      const detail = await c.caseDetail(pick.id); ctx.focusCaseId = detail.id;
      const grey = detail.verdict === 'grey';
      return {
        answer: {
          tool: name, card: { kind: 'case', detail },
          words: grey ? bi('غير رسمي، ولا نتّهمه', 'Not official, not accused') : bi('هذا ما رآه المقيم', 'This is what the resident saw'),
          chips: grey ? [chip('نشاط مرخّص', 'It is licensed', 'mark_licensed'), chip('الأولى', 'The first', 'show_case', { n: 1 })]
            : [chip('وثّقها', 'Seal it', 'seal'), chip('على الهاتف', 'On the phone', 'show_run', { view: 'phone' })],
        },
        say: grey ? bi('هذه رمادية. لا دليل ضدها.', 'This one is grey. No evidence against it.') : bi(`هذا ما رآه المقيم، والحقيقي بجانبه. ${detail.reasons.length} أسباب.`, `This is what the resident saw, the real one beside it. ${detail.reasons.length} reasons.`),
        output: { n: detail.n, title: detail.title.en, verdict: detail.verdict, reasons: detail.reasons.map(r => r.en), sawThrough: detail.sawThrough.en, shownOnScreen: grey ? 'the grey case' : 'the mirror: what the resident saw beside the real one' },
      };
    }
    case 'open_check':
      return {
        answer: { tool: name, words: bi('افحص رابطاً', 'Check a link'), card: { kind: 'check', results: [...ctx.checks] }, chips: [chip('ماذا لدينا اليوم؟', 'What do we have today?', 'summary')] },
        say: bi('الصق الرابط أو قله، وأفحصه لك.', 'Paste or say the link and I will check it.'), output: { opened: 'the link checker', checkedSoFar: ctx.checks.length },
      };
    case 'check_address': {
      if (!String(args.domain || '').trim()) return runTool(c, ctx, 'open_check');
      const score = await c.score(String(args.domain || ''));
      ctx.checks = [score, ...ctx.checks.filter(x => x.host !== score.host)].slice(0, 8);
      const say = { green: bi('نعرفه. عنوان رسمي.', 'We know it. An official address.'), grey: bi('غير رسمي، ولا نتّهمه.', 'Not official, and not accused.'), red: bi(`مشتبه به، بـ${score.reasons.length} أسباب مستقلة.`, `Suspected, with ${score.reasons.length} independent reasons.`) }[score.verdict];
      return {
        answer: { tool: name, words: VERD[score.verdict], card: { kind: 'check', results: [...ctx.checks] }, chips: [chip('افحص abudhabip0lice-pay.com', 'Check abudhabip0lice-pay.com', 'check_address', { domain: 'abudhabip0lice-pay.com' }), chip('ماذا لدينا اليوم؟', 'What do we have today?', 'summary')] },
        say, output: { host: score.host, verdict: score.verdict, family: score.family?.en || null, reasons: score.reasons.map(r => r.en) },
      };
    }
    case 'show_run': {
      const w = await c.watch(); const round = w.lastRound;
      if (!round || !round.cases.length) return { answer: null, keep: true, say: bi('لا جولة بعد.', 'No round yet.'), output: { error: 'no round yet' } };
      const view: View = (['phone', 'computer'] as View[]).includes(args.view as View) ? (args.view as View) : 'both';
      const ci = Math.max(0, Math.min(round.cases.length - 1, Number(args.case || 1) - 1));
      const k = round.cases[ci];
      return {
        answer: {
          tool: name, card: { kind: 'replay', round, ci, view },
          words: view === 'phone' ? bi('كما رآها الهاتف', 'As the phone saw it') : bi('هكذا عمل الوكيل', 'This is how the agent worked'),
          chips: [view === 'phone' ? chip('الجهازان معاً', 'Both devices', 'show_run', { view: 'both', case: ci + 1 }) : chip('على الهاتف فقط', 'Phone only', 'show_run', { view: 'phone', case: ci + 1 }), chip('البحث التالي', 'Next search', 'show_run', { view, case: ((ci + 1) % round.cases.length) + 1 })],
        },
        say: view === 'phone' ? bi('هذه الجولة على الهاتف. إعادة، لا جولة جديدة.', 'This is the run on the phone. A replay, not a new round.') : bi('الحاسوب والهاتف معاً، خطوة بخطوة.', 'Computer and phone together, step by step.'),
        output: { note: 'a replay of the last round, nothing was started', search: k.q, view, read: k.counts.read, official: k.counts.green, notOfficialNotAccused: k.counts.grey, red: k.counts.red, onlyPhoneSaw: k.onlyPhone.length, onlyComputerSaw: k.onlyComputer.length, seconds: Math.round(k.ms / 1000) },
      };
    }
    case 'seal': {
      const d = await focusCase(c, ctx);
      if (!d) return { answer: null, keep: true, say: bi('لا حالة مفتوحة.', 'No case is open.'), output: { sealed: false, why: 'no case open' } };
      if (d.verdict === 'grey') {
        const r = await runTool(c, ctx, 'show_case', { n: d.n });
        return { ...r, say: bi('الرمادي لا يُختم؛ لا نتّهمه.', 'A grey case is not sealed; we accuse nothing.'), output: { sealed: false, why: 'a grey case is not sealed; it is not accused' } };
      }
      const record = await c.seal(d.id);
      return {
        answer: { tool: name, words: bi('المسودة جاهزة ومختومة', 'Sealed and ready'), card: { kind: 'record', record }, chips: [chip('اعتمد', 'Approve', 'approve'), chip('جهّز الإزالة', 'Prepare the takedown', 'takedown')] },
        say: bi('المسودة جاهزة ومختومة. أعتمدها؟', 'The draft is sealed. Shall I approve it?'),
        output: { sealed: true, case: d.n, recordId: record.id, fingerprintStart: record.fingerprint.slice(0, 8), status: 'draft, waiting for the officer' },
      };
    }
    case 'approve': {
      const d = await focusCase(c, ctx);
      const recId = d?.recordId;
      if (!d || !recId) return { answer: null, keep: true, say: bi('لا شيء مختوم بعد. قل «وثّقها» أولاً.', 'Nothing is sealed yet. Say "seal it" first.'), output: { approved: false, why: 'nothing sealed yet' } };
      const res = await c.approve(recId, via, ctx.edits[recId]);
      if (!res.approved) {
        return {
          answer: { tool: name, words: bi('لا اعتماد', 'Not approved'), card: { kind: 'done', items: [{ text: res.why || bi('رُفض الاعتماد.', 'Approval refused.'), no: true }] }, chips: [chip('افتح المسودة', 'Open the draft', 'seal')] },
          say: bi('فشل التحقق. لا أعتمد.', 'Verification failed. I will not approve.'), output: { approved: false, why: res.why?.en || 'refused' },
        };
      }
      return {
        answer: {
          tool: name, words: bi('تم', 'Done'), chips: [chip('التالية', 'Next one', 'show_case', { n: 'next' }), chip('جهّز الإزالة', 'Prepare the takedown', 'takedown')],
          card: { kind: 'done', items: [{ text: bi(`خُتمت المسودة · البصمة ${res.fingerprint.slice(0, 8)}…`, `Draft sealed · fingerprint ${res.fingerprint.slice(0, 8)}…`) }, { text: res.via === 'voice' ? bi('اعتمدها الضابط بصوته', 'Approved by the officer, by voice') : bi('اعتمدها الضابط بالضغط', 'Approved by the officer, by click') }, { text: bi('طلب الإزالة جاهز. لم يُرسل شيء.', 'Takedown request ready. Nothing sent.') }] },
        },
        say: bi('تم. اعتمدتَ المحضر، وطلب الإزالة جاهز.', 'Done. You approved the record; the takedown is ready.'),
        output: { approved: true, by: 'the officer, by ' + res.via, takedown: 'ready, nothing sent' },
      };
    }
    case 'takedown': {
      const d = await focusCase(c, ctx);
      if (!d || d.verdict === 'grey') return { answer: null, keep: true, say: bi('لا إزالة لحالة رمادية.', 'No takedown for a grey case.'), output: { error: 'no red case open' } };
      const pkg = await c.takedown(d.id);
      return {
        answer: { tool: name, words: bi(`${pkg.recipients.length} جهات جاهزة`, `${pkg.recipients.length} recipients ready`), card: { kind: 'takedown', pkg }, chips: [chip('ماذا لدينا اليوم؟', 'What do we have today?', 'summary')] },
        say: bi('لا يُرسل شيء إلا بقرارك.', 'Nothing goes out without your decision.'), output: { recipients: pkg.recipients.length, sent: false },
      };
    }
    case 'mark_licensed': {
      const desk = await c.desk();
      const target = (ctx.focusCaseId && desk.cases.find(x => x.id === ctx.focusCaseId && x.verdict === 'grey')) || desk.cases.find(x => x.verdict === 'grey');
      if (!target) return { answer: null, keep: true, say: bi('لا حالة رمادية مفتوحة.', 'No grey case is open.'), output: { error: 'no grey case' } };
      await c.markCase(target.id, 'licensed');
      return {
        answer: { tool: name, words: bi('تعلّمه السجل', 'The register learned it'), chips: [chip('ماذا بقي؟', 'What is left?', 'summary')], card: { kind: 'done', items: [{ text: bi('سُجّل كنشاط مرخّص', 'Recorded as a licensed business') }, { text: bi('يبقى رمادياً، بلا اتهام', 'It stays grey, not accused') }, { text: bi('لن يعود إلى قائمة قرارك', 'It will not come back to your list') }] } },
        say: bi('سُجّل كنشاط مرخّص.', 'Recorded as licensed.'), output: { marked: target.address, as: 'licensed' },
      };
    }
    case 'scale': {
      const feeds = await c.feeds();
      const answer: Answer = { tool: name, words: bi('الإنترنت يولد الآن', 'The internet, being born now'), card: { kind: 'scale', feeds }, chips: [chip('ماذا يحتاجني؟', 'What needs me?', 'summary')] };
      if (!feeds.ct && !feeds.names) return {
        answer, say: bi(`الأرقام قيد العدّ بعد تشغيل الخادم، تجهز خلال دقائق. ${feeds.needDecision} تحتاجك الآن.`, `The numbers are still being counted after the server started; ready in a few minutes. ${feeds.needDecision} need you now.`),
        output: { warmingUp: true, needDecision: feeds.needDecision },
      };
      const ago = feeds.updatedAt ? agoBi(feeds.updatedAt) : null;
      const certs = feeds.ct ? bi(`نحو ${fmt(feeds.ct.perMin)} شهادة جديدة في الدقيقة. `, `About ${fmt(feeds.ct.perMin)} new certificates a minute. `) : bi('', '');
      const names = feeds.names ? bi(`${fmt(feeds.names.lookAlikes)} اسماً جديداً يشبه اسماً رسمياً. `, `${fmt(feeds.names.lookAlikes)} new names look like an official one. `) : bi('', '');
      return {
        answer,
        say: bi(`${certs.ar}${names.ar}${feeds.needDecision} تحتاجك.${ago ? ' ' + ago.ar + '.' : ''}`, `${certs.en}${names.en}${feeds.needDecision} need you.${ago ? ' Numbers ' + ago.en + '.' : ''}`),
        output: { certificatesPerMinute: feeds.ct?.perMin ?? null, logName: feeds.ct?.log ?? null, newNames: feeds.names?.total ?? null, lookAlikesGrey: feeds.names?.lookAlikes ?? null,
          needDecision: feeds.needDecision, updated: ago?.en ?? null },
      };
    }
    case 'run_now': {
      const w = await c.runWatch();
      return {
        answer: { tool: name, words: bi('بدأت الجولة', 'Round started'), card: { kind: 'done', items: [{ text: bi('أربع عمليات بحث كما يبحث المقيم', 'Four searches the way a resident searches') }, { text: bi('الحاسوب والهاتف في الوقت نفسه', 'Computer and phone at the same time') }, { text: bi('سأخبرك حين تنتهي', 'I will tell you when it ends') }] }, chips: [chip('مين يشتغل الحين؟', 'Who is working now?', 'agents')] },
        say: bi('بدأت. الحاسوب والهاتف معاً.', 'Started. Computer and phone together.'), output: { started: w.running, searches: w.progress?.total ?? 4, devices: 'computer and phone at the same time' },
      };
    }
    case 'watch': {
      const w = await c.watch();
      return {
        answer: { tool: name, words: w.lastRound ? bi('آخر جولة', 'The last round') : bi('لا جولة بعد', 'No round yet'), card: { kind: 'round', watch: w }, chips: [chip('ورّني الجولة', 'Show me the run', 'show_run', { view: 'both' }), chip('شغّلها الآن', 'Run it now', 'run_now')] },
        say: { ar: `الجولة القادمة بعد ${nextInBi(w.nextAt).ar}.`, en: `Next round in ${nextInBi(w.nextAt).en}.` }, output: { everyHours: w.everyHours, running: w.running, nextRoundIn: nextInBi(w.nextAt).en },
      };
    }
    case 'agents': {
      const agents = await c.agents();
      return {
        answer: { tool: name, words: bi('من يعمل الآن', 'Who is working now'), card: { kind: 'agents', agents }, chips: [chip('ورّني الجولة', 'Show me the run', 'show_run', { view: 'both' })] },
        say: bi(`${agents.agents.length} وكلاء يتعاونون، والقرار لك.`, `${agents.agents.length} agents working together; the decision is yours.`),
        output: { agents: agents.agents.map(a => ({ name: a.name.en, status: a.status.en, busy: a.busy })) },
      };
    }
    case 'records': {
      const records = await c.records();
      return {
        answer: { tool: name, words: bi(`${records.length} مسودة مختومة`, `${records.length} sealed drafts`), card: { kind: 'records', records }, chips: [chip('ماذا لدينا اليوم؟', 'What do we have today?', 'summary')] },
        say: records.length ? bi('هذه مسوداتك.', 'These are your drafts.') : bi('لا مسودات بعد.', 'No drafts yet.'), output: { sealedDrafts: records.length, approved: records.filter(r => r.status === 'approved').length },
      };
    }
    case 'how_sure': {
      const scorecard = await c.scorecard();
      return { answer: { tool: name, words: bi('رقمنا الصادق', 'Our honest number'), card: { kind: 'scorecard', scorecard }, chips: [] }, say: bi('لا نتباهى برقم.', 'No boasting.'), output: { rows: scorecard.rows.map(r => r.value + ' ' + r.label.en) } };
    }
    case 'drill': {
      const drill = await c.drill();
      return { answer: { tool: name, words: bi('تمرين على علامتنا', 'A drill on our own brand'), card: { kind: 'drill', drill }, chips: [] }, say: bi('لا علامة حقيقية، ولا نموذج.', 'No real brand, no form.'), output: { steps: drill.drill.length } };
    }
    case 'close_card':
      return { answer: null, close: true, say: bi('حاضر.', 'Sure.'), output: { closed: true } };
    case 'chat':
      return { answer: null, say: bi('في الخدمة.', 'At your service.'), output: {} };
    case 'help':
    default:
      return { answer: null, keep: true, say: bi('اسألني عن اليوم، أو عن عنوان، أو عن الجولة.', 'Ask me about today, an address, or the run.'), output: { error: 'unknown request' } };
  }
}
