/* The closed kit of generative pieces. Voice mode and the studio build every screen from these.
   Each piece only renders what an engine response gave it. */
import { useEffect, useRef, useState } from 'react';
import type {
  AgentsState, CaseDetail, CaseSummary, DeskSummary, DrillInfo, Feeds, RecordFields, Round, ScoreResult, Scorecard,
  SealedRecord, TakedownPackage, WatchState,
} from '../api/types';
import { clock, fmt, useEngine, useLang } from '../i18n';
import { agoBi, nextInBi } from '../voice/tools';
import { FootagePlayer, type FootageItem } from './FootagePlayer';
import { Addr, Icon, Piece, Pill, Reasons, Spark, Ticks } from './basics';

/* ---------- cases ---------- */
export function CasesList({ desk, onPick, picked }: { desk: DeskSummary; onPick?: (c: CaseSummary) => void; picked?: string | null }) {
  const { t, tx } = useLang();
  return (
    <Piece head={tx('بانتظار قرارك', 'Waiting for your decision')}>
      <div className="rows" data-testid="cases-list">
        {desk.cases.map(c => (
          <button key={c.id} type="button" className="row" style={picked === c.id ? { borderColor: 'var(--teal)' } : undefined} onClick={() => onPick?.(c)}>
            <span className="n">{c.n}</span>
            <span><span className="t">{t(c.title)}</span><br /><span className="m">{t(c.source)} · <Addr a={c.address.split('/')[0]} /></span></span>
            <Pill v={c.verdict} sm />
          </button>
        ))}
        {!desk.cases.length && <p className="small mut">{tx('لا شيء ينتظرك.', 'Nothing is waiting for you.')}</p>}
      </div>
    </Piece>
  );
}

export function Mirror({ d, compact }: { d: CaseDetail; compact?: boolean }) {
  const { t, tx } = useLang();
  if (d.verdict === 'grey' || !d.imitates || !d.trick) return <GreyCase d={d} />;
  const crumbs = d.imitates.crumbs.map(t);
  return (
    <Piece head={<><Pill v={d.verdict} sm /> <span style={{ marginInlineStart: 6 }}>{t(d.source)}</span></>} className="case-mirror">
      <div className="mirror" data-testid="mirror">
        <div className="pane">
          <div className="pane-h"><span>{tx('ما رآه المقيم', 'What the resident saw')}</span></div>
          <div className="urlbar"><span className="dim">{d.trick.decoy}</span><span className="lit" data-testid="trick">{d.trick.owner}</span><span className="dim">{d.trick.rest}</span></div>
          <div className="wire"><div className="bar s" /><div className="bt2">{t(d.title)}</div><span className="urgent">{tx('ادفع خلال 24 ساعة', 'Pay within 24 hours')}</span>{!compact && <div className="bar m" />}<div className="nopay">{tx('منطقة الدفع أزيلت: لا يوجد نموذج', 'Payment area removed: no form')}</div></div>
        </div>
        <div className="pane">
          <div className="pane-h"><span>{tx('الحقيقي', 'The real one')}</span></div>
          <div className="urlbar"><span className="ok">{d.imitates.address}</span></div>
          <div className="wire"><div className="crumbs">{crumbs.join(' › ')}</div><div className="bar s" /><div className="bt2">{crumbs[crumbs.length - 1]}</div><span className="okb">{tx('في السجل · رسمي', 'In the register · official')}</span></div>
        </div>
      </div>
      <div className="saw" data-testid="saw">{t(d.sawThrough)}</div>
      {d.footage && (d.footage.server || d.footage.phone) && <CaptureFootage d={d} />}
      <Reasons reasons={d.reasons} v={d.verdict} max={compact ? 3 : 9} />
    </Piece>
  );
}

/* the two-view capture of the case, as real footage: what the police computer saw beside what the phone saw */
function CaptureFootage({ d }: { d: CaseDetail }) {
  const { tx } = useLang();
  const [open, setOpen] = useState(false);
  const f = d.footage!;
  const items: FootageItem[] = [
    ...(f.server ? [{ key: 'server', frame: 'window' as const, label: tx('كحاسوب الشرطة', 'As the police computer'), f: f.server }] : []),
    ...(f.phone ? [{ key: 'phone', frame: 'phone' as const, label: tx('كهاتف في أبوظبي', 'As a phone in Abu Dhabi'), f: f.phone }] : []),
  ];
  return (
    <div style={{ margin: '10px 0' }}>
      <button type="button" className="chip" onClick={() => setOpen(o => !o)}>{open ? tx('أخفِ الالتقاط', 'Hide the capture') : tx('شاهد الالتقاط كفيديو', 'Watch the capture as video')}</button>
      {open && <div style={{ marginTop: 10 }}><FootagePlayer items={items} /></div>}
    </div>
  );
}

export function GreyCase({ d }: { d: CaseDetail }) {
  const { t } = useLang();
  return (
    <Piece head={<Pill v="grey" sm />}>
      <div className="addrbig" style={{ fontSize: 20 }}>{d.address}</div>
      <div className="saw" style={{ textAlign: 'center' }} data-testid="saw">{t(d.sawThrough)}</div>
      <Reasons reasons={d.reasons} v="grey" />
    </Piece>
  );
}

/* ---------- an address verdict ---------- */
export function VerdictView({ r }: { r: ScoreResult }) {
  const { t, tx } = useLang();
  return (
    <Piece head={tx('فُحص في السجل', 'Checked against the register')}>
      <div className="addrbig" data-testid="verdict-host">{r.verdict === 'red' ? <span className="lit">{r.host}</span> : r.host}</div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
        <Pill v={r.verdict} />
        {r.family && r.verdict !== 'green' && <span className="small mut">{tx('يشبه', 'Looks like')}: {t(r.family)}</span>}
        {r.family && r.verdict === 'green' && <span className="small mut">{t(r.family)}</span>}
      </div>
      <Reasons reasons={r.reasons} v={r.verdict} />
      {r.verdict === 'green' && r.officialAddresses.length > 0 && (
        <div className="doors" style={{ marginTop: 12 }}>{r.officialAddresses.map(d => <span key={d} className={'door ' + (d === r.host ? 'me' : '')}>{d}</span>)}</div>
      )}
    </Piece>
  );
}

/* the link checker: the same on the studio's Check page and inside the voice card */
export const CHECK_EXAMPLES = ['abudhabipolice.ae', 'adpolice-fines.top', 'abudhabip0lice-pay.com', 'tamm.abudhabi', 'example.com'];
export function CheckPanel({ results, onCheck, compact }: { results: ScoreResult[]; onCheck: (link: string) => void | Promise<void>; compact?: boolean }) {
  const { tx } = useLang();
  const [q, setQ] = useState('');
  const go = (v = q) => { const s = v.trim(); if (!s) return; setQ(''); void onCheck(s); };
  const paste = async () => { try { const t = (await navigator.clipboard.readText()).trim(); if (t) go(t); } catch { /* clipboard blocked: the field still works */ } };
  return (
    <Piece head={tx('افحص رابطاً', 'Check a link')} className={'checkpanel' + (compact ? ' compact' : '')}>
      <div className="field" data-testid="check-panel">
        <input aria-label={tx('العنوان', 'address')} dir="ltr" placeholder={tx('الصق أو اكتب عنواناً، مثل abudhabipolice.ae', 'Paste or type an address, e.g. abudhabipolice.ae')} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') go(); }} />
        <button className="btn sec" type="button" onClick={paste}>{tx('لصق', 'Paste')}</button>
        <button className="btn" type="button" onClick={() => go()}>{tx('افحص', 'Check')}</button>
      </div>
      <div className="doors" style={{ marginTop: 10, justifyContent: 'flex-start' }}>{CHECK_EXAMPLES.map(x => <button key={x} type="button" className="door" onClick={() => go(x)}>{x}</button>)}</div>
      <div className="checks" data-testid="check-results">
        {results.map((r, i) => i === 0 ? <div key={r.host + i} style={{ marginTop: 14 }}><VerdictView r={r} /></div>
          : <div key={r.host + i} className="row" style={{ gridTemplateColumns: '1fr auto', marginTop: 8, cursor: 'default' }}><span className="addr">{r.host}</span><Pill v={r.verdict} sm /></div>)}
      </div>
    </Piece>
  );
}

/* ---------- the sealed record: a fixed layout, never generated ---------- */
export function RecordView({ record, onFields, onApprove }: { record: SealedRecord; onFields?: (f: RecordFields) => void; onApprove?: () => void }) {
  const { tx, ar } = useLang();
  const engine = useEngine();
  const [addr, setAddr] = useState(record.fields.address);
  const [ver, setVer] = useState<{ ok: boolean; now: string }>({ ok: true, now: record.fingerprint });
  const approved = record.status === 'approved';
  useEffect(() => { setAddr(record.fields.address); }, [record.id, record.fields.address]);
  useEffect(() => {
    let live = true; const fields = { ...record.fields, address: addr };
    onFields?.(fields);
    engine.verifyRecord(record.id, fields).then(v => { if (live) setVer({ ok: v.ok, now: v.fingerprintNow }); }).catch(() => undefined);
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [addr, record.id]);
  const tamper = () => {
    if (!ver.ok) return setAddr(record.fields.address);
    const a = record.fields.address, k = Math.max(0, a.indexOf('a'));
    setAddr(a.slice(0, k) + (a[k] === 'a' ? 'e' : 'x') + a.slice(k + 1));
  };
  const f = record.fields;
  return (
    <Piece head={tx('مسودة المحضر · شكل ثابت لا يُولَّد', 'Draft record · a fixed layout, never generated')}>
      <div className="record" data-testid="record">
        <div className="rec-h"><b>مسودة محضر رصد رابط مشتبه به</b><span className="hash">{record.id}</span></div>
        <dl className="rec-grid">
          <dt>وقت الختم</dt><dd>{f.time}</dd>
          <dt>مصدر الرصد</dt><dd>{f.source} · «{f.query}»</dd>
          <dt>الرابط</dt><dd><input className="addr recaddr" aria-label="record address" value={addr} disabled={approved} onChange={e => setAddr(e.target.value)} spellCheck={false} /></dd>
          <dt>النتيجة</dt><dd>{f.verdict}</dd>
          <dt>الأسباب</dt><dd>{f.reasons.map((x, k) => <span key={k}>{k + 1}. {x}<br /></span>)}</dd>
          <dt>البصمة (SHA-256)</dt><dd><code className="hash" data-testid="fingerprint">{record.fingerprint}</code></dd>
        </dl>
        <div className="caps"><div className="cap">لقطة ١: كحاسوب الشرطة (مكان محجوز)</div><div className="cap">لقطة ٢: كهاتف في أبوظبي (مكان محجوز)</div></div>
        <div className={'verify ' + (ver.ok ? 'ok' : 'bad')} dir={ar ? 'rtl' : 'ltr'} data-testid="verify">
          {ver.ok ? tx('✓ التحقق ناجح: البصمة تطابق ما خُتم.', '✓ Verified: the fingerprint matches what was sealed.')
            : <>{tx('✗ فشل التحقق: تغيّر حرف بعد الختم. البصمة الآن', '✗ Verification failed: a letter changed after the seal. Fingerprint now')} <code className="hash">{ver.now.slice(0, 16)}…</code></>}
        </div>
        <div className="rec-act" dir={ar ? 'rtl' : 'ltr'}>
          <button className="btn sec" type="button" disabled={approved} onClick={tamper}>{ver.ok ? tx('عدّل حرفاً واحداً', 'Edit one letter') : tx('تراجع عن التعديل', 'Undo the edit')}</button>
          <button className="btn" type="button" disabled={!ver.ok || approved} onClick={onApprove}>{tx('اعتماد الضابط', 'Officer approves')}<small>{tx('بالضغط أو بقول «اعتمد» · UAE PASS في التجربة', 'by click or by saying "approve" · UAE PASS in a pilot')}</small></button>
        </div>
        <div className={'stamp' + (approved ? ' on' : '')}>محضر معتمد من الضابط</div>
      </div>
    </Piece>
  );
}

export function RecordsList({ records, picked, onPick }: { records: SealedRecord[]; picked?: string | null; onPick?: (r: SealedRecord) => void }) {
  const { t, tx } = useLang();
  if (!records.length) return <Piece head={tx('لا مسودات بعد', 'No drafts yet')}><p className="small mut">{tx('من «الحالات» اختم الحالة الأولى، أو قل «وثّقها».', 'From Cases, seal the first case, or say "seal it".')}</p></Piece>;
  return (
    <div className="rows" data-testid="records-list">
      {records.map(r => (
        <button key={r.id} type="button" className="row" style={picked === r.id ? { borderColor: 'var(--teal)' } : undefined} onClick={() => onPick?.(r)}>
          <span className="n">{r.caseN}</span>
          <span><span className="t">{t(r.title)}</span><br /><span className="m">{r.id} · {clock(r.sealedAt)}</span></span>
          {r.status === 'approved' ? <span className="pill green sm"><i />{tx('معتمد', 'approved')}</span> : <span className="pill grey sm"><i />{tx('مسودة', 'draft')}</span>}
        </button>
      ))}
    </div>
  );
}

/* ---------- takedown: prepared, never sent ---------- */
export function TakedownView({ pkg }: { pkg: TakedownPackage }) {
  const { t, tx } = useLang();
  const engine = useEngine();
  const [p, setP] = useState(pkg);
  useEffect(() => setP(pkg), [pkg]);
  return (
    <Piece head={<>{tx('طلب الإزالة', 'Takedown request')} · <Addr a={p.address} /></>}>
      <ul className="td" data-testid="takedown">
        {p.recipients.map(r => (
          <li key={r.id}><span>{t(r.name)}</span>
            <button className="btn dark" type="button" disabled={r.state === 'ready'} onClick={() => engine.prepareRecipient(p.caseId, r.id).then(setP)}>
              {r.state === 'ready' ? tx('جاهز ✓ (لم يُرسل شيء)', 'Ready ✓ (nothing sent)') : tx('جهّز', 'Prepare')}
            </button>
          </li>
        ))}
      </ul>
    </Piece>
  );
}

/* ---------- watch: the schedule pill, the last round, the replay ---------- */
export function SchedulePill({ w, onRunNow }: { w: WatchState | null; onRunNow: () => void }) {
  const { t, tx } = useLang();
  const [, tick] = useState(0);
  useEffect(() => { const i = setInterval(() => tick(x => x + 1), 30000); return () => clearInterval(i); }, []);
  if (!w) return null;
  const running = w.running;
  return (
    <div className={'activity' + (running ? ' run' : '')} data-testid="schedule">
      <span className="dot" />
      <span className="t">{running
        ? tx(`وكيل الرصد يعمل الآن · ${(w.progress?.i ?? 0) + 1} من ${w.progress?.total ?? 4} · حاسوب + هاتف`, `Watch running now · ${(w.progress?.i ?? 0) + 1} of ${w.progress?.total ?? 4} · computer + phone`)
        : tx(`الرصد كل ${w.everyHours} ساعات · الجولة القادمة بعد ${t(nextInBi(w.nextAt))}`, `Watch every ${w.everyHours} h · next round in ${t(nextInBi(w.nextAt))}`)}</span>
     
      <button type="button" disabled={running} onClick={onRunNow}>{tx('شغّل الآن', 'Run now')}</button>
    </div>
  );
}

const roundCounts = (r: Round) => r.cases.reduce((a, c) => ({ read: a.read + c.counts.read, green: a.green + c.counts.green, grey: a.grey + c.counts.grey, red: a.red + c.counts.red }), { read: 0, green: 0, grey: 0, red: 0 });

export function RoundView({ w }: { w: WatchState }) {
  const { tx } = useLang();
  const r = w.lastRound;
  if (!r) return <Piece head={tx('لا جولة بعد', 'No round yet')} />;
  const c = roundCounts(r), tt = c.read || 1;
  return (
    <Piece head={tx(`آخر جولة ${clock(r.startedAt)} · ${r.cases.length} عمليات بحث · حاسوب + هاتف`, `Last round ${clock(r.startedAt)} · ${r.cases.length} searches · computer + phone`)}>
      <div className="bignum"><span className="v" data-testid="round-read">{c.read}</span><span className="k">{tx('عنواناً قرأها كما يراها المقيم', 'addresses read the way a resident sees them')}</span></div>
      <div className="stack"><i className="g" style={{ width: (c.green / tt) * 100 + '%' }} /><i className="y" style={{ width: (c.grey / tt) * 100 + '%' }} /><i className="r" style={{ width: (c.red / tt) * 100 + '%' }} /></div>
      <div className="legend"><span><i style={{ background: 'var(--green)' }} />{c.green} {tx('رسمي', 'official')}</span><span><i style={{ background: '#6c7a77' }} />{c.grey} {tx('غير رسمي، بلا اتهام', 'not official, not accused')}</span><span><i style={{ background: 'var(--red2)' }} />{c.red} {tx('أحمر', 'red')}</span></div>
    </Piece>
  );
}

/* grey sites: a quiet dot, the name only on tap, so no business is accused by the screen */
export function GreyDot({ host, only }: { host: string; only?: boolean }) {
  const { tx } = useLang();
  const [open, setOpen] = useState(false);
  if (open) return <span className={'host grey' + (only ? ' only' : '')}><i />{host}</span>;
  return <button type="button" className={'gdot' + (only ? ' only' : '')} title={tx('اضغط لرؤية الاسم', 'tap for the name')} aria-label={tx('موقع غير رسمي، اضغط لرؤية الاسم', 'not official site, tap for the name')} onClick={() => setOpen(true)} />;
}

export { Replay } from './Replay';

/* ---------- scale: one big live number, a small chart ---------- */
export function ScaleView({ feeds }: { feeds: Feeds }) {
  const { t, tx } = useLang();
  const ct = feeds.ct, nm = feeds.names;
  const [now, setNow] = useState(ct?.size ?? 0);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    if (!ct) return;
    const i = setInterval(() => setNow(ct.size + ((Date.now() - ct.at) / 60000) * ct.perMin), 150);
    return () => clearInterval(i);
  }, [ct]);
  const updated = feeds.updatedAt ? <p className="small mut" data-testid="scale-updated" style={{ margin: '6px 0 0', textAlign: 'center' }}>{t(agoBi(feeds.updatedAt))}</p> : null;
  if (!ct && !nm) return (
    <Piece head={tx('الحجم', 'Scale')}>
      <p className="small mut" data-testid="scale-warming" style={{ textAlign: 'center' }}>{tx('الأرقام قيد العدّ بعد تشغيل الخادم، تجهز خلال دقائق.', 'The numbers are still being counted after the server started; ready in a few minutes.')}</p>
      <div className="bignum"><span className="v">{fmt(feeds.needDecision)}</span><span className="k">{tx('تحتاج قرارك الآن', 'need your decision now')}</span></div>
    </Piece>
  );
  const det = [
    ...(nm ? [
      { k: 'br', v: nm.branded, l: tx('بكلمة إماراتية (7 أيام)', 'with a UAE word (7 days)'), src: nm.source, how: tx(`من ${fmt(nm.total)} اسماً جديداً`, `of ${fmt(nm.total)} new names`) },
      { k: 'la', v: nm.lookAlikes, l: tx('تشبه اسماً رسمياً · رمادي', 'look like an official name · grey'), src: nm.source, how: tx('اسم رسمي + كلمة إغراء، أو بفارق حرف. لا أحمر: العنوان وحده سبب واحد.', 'official name + lure word, or one letter off. No red: the address alone is one reason.') },
    ] : []),
    { k: 'dc', v: feeds.needDecision, l: tx('تحتاج قرارك', 'need your decision'), src: 'desk', how: tx('الحالات التي تنتظرك', 'the cases waiting for you') },
  ];
  const s = det.find(x => x.k === sel);
  return (
    <Piece head={ct ? tx('كل شهادة ويب جديدة في سجل عام واحد', 'Every new web certificate in one public log') : tx('الحجم', 'Scale')}>
      {ct && <>
        <div className="counter" data-testid="live-number">{fmt(now)}</div>
        <div className="bignum"><span className="k">{tx(`نحو ${fmt(ct.perMin)} في الدقيقة · ${ct.log}`, `about ${fmt(ct.perMin)} a minute · ${ct.log}`)}</span></div>
        <Spark values={ct.spark} />
      </>}
      <div className="scale-det">
        {det.map(x => <button key={x.k} type="button" className={sel === x.k ? 'on' : ''} onClick={() => setSel(sel === x.k ? null : x.k)}><b>{fmt(x.v)}</b><span>{x.l}</span></button>)}
      </div>
      {s ? <div className="detail"><dl><dt>{tx('المصدر', 'Source')}</dt><dd className="addr" style={{ textAlign: 'start' }}>{s.src}</dd><dt>{tx('كيف عُدّ', 'How counted')}</dt><dd>{s.how}</dd></dl></div>
        : <p className="small mut" style={{ margin: '8px 0 0', textAlign: 'center' }}>{tx('اضغط رقماً لترى مصدره.', 'Tap a number for its source.')}</p>}
      {updated}
    </Piece>
  );
}

export function FunnelView({ feeds }: { feeds: Feeds }) {
  const { t, tx } = useLang();
  return (
    <Piece head={tx('من كل الإنترنت إلى مكتبك', 'From the whole internet to your desk')}>
      <ol className="reasons">{feeds.funnel.map((f, i) => <li key={i}><b style={{ width: 'auto', padding: '0 8px', borderRadius: 999 }}>{fmt(f.n)}</b><span>{t(f.label)}</span></li>)}</ol>
    </Piece>
  );
}

/* ---------- agents ---------- */
export function AgentsRow({ a }: { a: AgentsState }) {
  const { t } = useLang();
  return (
    <div className="agentsrow" data-testid="agents">
      {a.agents.map(x => <div key={x.id} className={'ag ' + (x.busy ? 'busy' : '')}><span className="ic"><Icon k={x.id} /></span><span><span className="nm">{t(x.name)}</span><span className="st">{t(x.status)}</span></span></div>)}
    </div>
  );
}

const AGENT_NAMES: Record<string, { ar: string; en: string }> = { watch: { ar: 'الرصد', en: 'Watch' }, register: { ar: 'السجل', en: 'Register' }, check: { ar: 'التحقق', en: 'Check' }, capture: { ar: 'الالتقاط', en: 'Capture' }, seal: { ar: 'الختم', en: 'Seal' }, officer: { ar: 'الضابط', en: 'Officer' } };
export function AgentsFlow({ a }: { a: AgentsState }) {
  const { t, tx } = useLang();
  const lc = a.lastCase; const [i, setI] = useState(0);
  const flow = useRef<HTMLDivElement>(null); const [left, setLeft] = useState(0);
  useEffect(() => { const tm = setInterval(() => setI(x => x + 1), 2600); return () => clearInterval(tm); }, []);
  const step = lc ? lc.steps[i % lc.steps.length] : null;
  useEffect(() => {
    if (!step || !flow.current) return;
    const node = flow.current.querySelector<HTMLElement>(`[data-n="${step.agent}"]`); if (!node) return;
    const fr = flow.current.getBoundingClientRect(), nr = node.getBoundingClientRect();
    setLeft(nr.left - fr.left + flow.current.scrollLeft + nr.width / 2);
  }, [step]);
  if (!lc) return <p className="small mut">{tx('لا جولة بعد', 'No round yet')}</p>;
  return (
    <>
      <div className="flow" ref={flow}>
        {lc.steps.map(s => <div key={s.agent} className={'fn ' + (step?.agent === s.agent ? 'at' : '')} data-n={s.agent}><span className="ic"><Icon k={s.agent} /></span><span>{t(AGENT_NAMES[s.agent])}</span></div>)}
        <div className="token" style={{ left }}><i /><span>{t(lc.query)}</span></div>
      </div>
      <div className="handoff" data-testid="handoff"><span>{step ? t(step.line) : ''}</span></div>
    </>
  );
}

/* ---------- how sure, drill ---------- */
export function ScorecardView({ s }: { s: Scorecard }) {
  const { t, tx } = useLang();
  return (
    <Piece head={tx('كم نحن متأكدون', 'How sure we are')}>
      <div className="score">{s.rows.map((r, i) => <div key={i} className="sc"><div className={'v' + (r.pending ? ' pending' : '')}>{r.value}</div><p className="small">{t(r.label)}</p></div>)}</div>
    </Piece>
  );
}

export function DrillView({ d, initialTab = 'drill' }: { d: DrillInfo; initialTab?: 'drill' | 'attacker' | 'judges' }) {
  const { t, tx } = useLang();
  const engine = useEngine();
  const [tab, setTab] = useState(initialTab);
  const [q, setQ] = useState(''); const [tried, setTried] = useState<ScoreResult[]>([]);
  const go = async () => { const v = q.trim(); if (!v) return; const r = await engine.score(v); setTried(x => [r, ...x].slice(0, 5)); };
  return (
    <div>
      <div className="tabs">
        {([['drill', tx('تمرين الجاهزية', 'Readiness drill')], ['attacker', tx('يوم المحتال', "The attacker's day")], ['judges', tx('تزييف الحكام', "Judges' fakes")]] as const).map(([k, n]) => <button key={k} type="button" className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{n}</button>)}
      </div>
      {tab === 'judges' ? (
        <>
          <p className="small mut">{tx('اخترع عنواناً مزيفاً، والجواب في ثانيتين. لا نفتح أي صفحة: العنوان وحده.', 'Invent a fake address and get the answer in two seconds. No page is opened: the address alone.')}</p>
          <div className="field"><input aria-label="judge address" placeholder={tx('مثل adpolice-fines.top', 'e.g. adpolice-fines.top')} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') go(); }} /><button className="btn" type="button" onClick={go}>{tx('افحص', 'Check')}</button></div>
          {tried.map((r, i) => <div key={i} style={{ marginTop: 8 }}>{i === 0 ? <VerdictView r={r} /> : <div className="row" style={{ gridTemplateColumns: '1fr auto' }}><span className="addr">{r.host}</span><Pill v={r.verdict} sm /></div>}</div>)}
        </>
      ) : (
        <>
          <ol className="reasons">{d[tab].map((x, i) => <li key={i}><b style={{ width: 'auto', padding: '0 8px', borderRadius: 999 }}>{x.t}</b><span>{t(x.line)}</span></li>)}</ol>
          <p className="small mut" style={{ marginTop: 8 }}></p>
        </>
      )}
    </div>
  );
}
