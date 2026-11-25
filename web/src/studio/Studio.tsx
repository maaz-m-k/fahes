/* The studio: every feature in a side menu, operated by hand with the same kit as voice mode. */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { AgentsState, CaseDetail, DeskSummary, DrillInfo, Feeds, Marker, RegisterList, ScoreResult, SealedRecord, TakedownPackage, WatchState } from '../api/types';
import { clock, useEngine, useLang } from '../i18n';
import { Icon, Mks, Ticks } from '../kit/basics';
import { AgentsFlow, AgentsRow, CasesList, CheckPanel, DrillView, FunnelView, GreyDot, Mirror, RecordsList, RecordView, Replay, ScaleView, SchedulePill, TakedownView, VerdictView } from '../kit/pieces';

export const PAGES = [
  ['watch', { ar: 'الرصد', en: 'Watch' }], ['cases', { ar: 'الحالات', en: 'Cases' }], ['check', { ar: 'فحص عنوان', en: 'Check an address' }],
  ['register', { ar: 'السجل', en: 'Register' }], ['drill', { ar: 'التمرين', en: 'Drill' }], ['scale', { ar: 'الحجم', en: 'Scale' }],
  ['records', { ar: 'المحاضر', en: 'Records' }], ['agents', { ar: 'الوكلاء', en: 'Agents' }],
] as const;
export type Page = (typeof PAGES)[number][0];

function useLoad<T>(f: () => Promise<T>, deps: unknown[] = []): [T | null, () => void] {
  const [v, setV] = useState<T | null>(null); const [n, setN] = useState(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { let live = true; f().then(x => { if (live) setV(x); }).catch(() => undefined); return () => { live = false; }; }, [n, ...deps]);
  return [v, useCallback(() => setN(x => x + 1), [])];
}

function Card({ title, sub, marks, children }: { title: ReactNode; sub?: ReactNode; marks?: Marker[]; children?: ReactNode }) {
  return <section className="card"><div className="card-h"><div className="card-t">{title}{sub && <small>{sub}</small>}</div>{marks && <Mks marks={marks} />}</div>{children}</section>;
}
function Head({ title, sub, extra }: { title: string; sub: string; extra?: ReactNode }) {
  return <div className="main-h"><div><h1>{title}</h1><p>{sub}</p></div>{extra}</div>;
}

function WatchPage({ watch, onRunNow }: { watch: WatchState | null; onRunNow: () => void }) {
  const { tx, ar } = useLang();
  const [first, setFirst] = useState<string | null>(null); const [open, setOpen] = useState<number | null>(null);
  if (!watch) return null;
  const r = watch.lastRound;
  return (
    <>
      <Head title={tx('الرصد', 'Watch')} sub={tx('يبحث كما يبحث المقيم، على الحاسوب والهاتف في الوقت نفسه، كل 6 ساعات أو عند الطلب.', 'Searches the way a resident does, on a computer and a phone at the same time, every 6 hours or on demand.')} extra={<div id="actS"><SchedulePill w={watch} onRunNow={onRunNow} /></div>} />
      <Card title={tx('محرك البحث', 'Search engine')} sub={tx('اضغط شعاراً ليبدأ به. فحص «لست روبوتاً» لا يُتجاوز أبداً: نتوقف وننتقل.', 'Tap a logo to start with it. A robot check is never bypassed: we stop and move on.')} marks={[watch.marker, { kind: 'real', note: 'BORROWED logos' }]}>
        <div className="engines">
          {watch.engines.map(e => { const on = (first || watch.engines.find(x => x.first)?.id) === e.id; return (
            <button key={e.id} type="button" className={'eng' + (on ? ' on' : '')} onClick={() => setFirst(e.id)}><img src={e.logo} alt="" /><span><b>{e.name}</b><small>{on ? tx('يبدأ به', 'goes first') : tx('احتياطي', 'fallback')}</small></span></button>
          ); })}
        </div>
      </Card>
      <Card title={tx('الحالات من آخر جولة', 'Cases from the last round')} sub={r ? `${clock(r.startedAt)} · ${Math.round(r.ms / 1000)} ${tx('ث', 's')} · ${tx('النقاط الرمادية: الاسم عند الضغط', 'grey dots: name on tap')}` : ''} marks={r ? [r.marker] : []}>
        {r?.cases.map((k, ci) => {
          const lc = k.computer.steps.at(-1), lp = k.phone.steps.at(-1); const diffN = k.onlyPhone.length + k.onlyComputer.length;
          const robots = [...k.computer.robot, ...k.phone.robot];
          const dots = (v: 'computer' | 'phone') => k[v].results.map((x, i) => x.verdict === 'green' ? <i key={i} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--green)', margin: '0 1px' }} /> : <GreyDot key={i} host={x.host} only={[...k.onlyPhone, ...k.onlyComputer].includes(x.host)} />);
          return (
            <div key={k.id}>
              <div className="casecard">
                <div className="thumbs">{!r.footage && lc && <img className="tc" src={r.shotBase + lc.shot} alt="" />}{!r.footage && lp && <img className="tp" src={r.shotBase + lp.shot} alt="" />}</div>
                <div style={{ minWidth: 0 }}>
                  <div className="q">«{ar ? k.ar : k.q}»</div>
                  <div className="m"><span>{tx('حاسوب', 'computer')} {dots('computer')}</span><span>{tx('هاتف', 'phone')} {dots('phone')}</span><span>{Math.round(k.ms / 1000)} {tx('ث', 's')}</span></div>
                  <div className="saw">{tx('رآها: ', 'Saw through: ')}<b>{tx('الحاسوب والهاتف معاً', 'computer and phone together')}</b> · {k.computer.engine || k.phone.engine}{robots.length ? tx(` بعد فحص روبوت عند ${robots[0].engine}`, ` after a robot check at ${robots[0].engine}`) : ''} · {diffN ? tx(`اختلف ما رأياه في ${diffN} عناوين`, `they differed on ${diffN} addresses`) : tx('رأيا الشيء نفسه', 'they saw the same')}</div>
                </div>
                <button type="button" className="chip pri" onClick={() => setOpen(open === ci ? null : ci)}>{tx('شاهد كيف عمل', 'Watch how it worked')}</button>
              </div>
              {open === ci && <Replay round={r} ci={ci} view="both" />}
            </div>
          );
        })}
      </Card>
    </>
  );
}

function CasesPage({ go }: { go: (p: Page) => void }) {
  const { tx } = useLang(); const engine = useEngine();
  const [desk, reloadDesk] = useLoad<DeskSummary>(() => engine.desk());
  const [pick, setPick] = useState<string | null>(null);
  const id = pick || desk?.cases[0]?.id || null;
  const [d, reload] = useLoad<CaseDetail | null>(() => (id ? engine.caseDetail(id) : Promise.resolve(null)), [id]);
  const [td, setTd] = useState<TakedownPackage | null>(null);
  const [done, setDone] = useState(false);
  useEffect(() => { setTd(null); setDone(false); }, [id]);
  if (!desk) return null;
  return (
    <>
      <Head title={tx('الحالات', 'Cases')} sub={tx('ما ينتظر قرارك. افتح حالة، اختمها، اعتمدها، جهّز الإزالة.', 'What waits for your decision. Open a case, seal it, approve it, prepare the takedown.')} />
      <div className="g2 split">
        <CasesList desk={desk} picked={id} onPick={c => setPick(c.id)} />
        <div>
          {d && <Mirror d={d} />}
          {d && (
            <div className="rec-act">
              {d.verdict === 'grey' ? (
                <button className="btn" type="button" disabled={done} onClick={async () => { await engine.markCase(d.id, 'licensed'); setDone(true); reloadDesk(); }}>{tx('ليس احتيالاً: نشاط مرخّص', 'Not a scam: licensed business')}</button>
              ) : (
                <>
                  <button className="btn" type="button" onClick={async () => { await engine.seal(d.id); reload(); go('records'); }}>{d.recordId ? tx('افتح المسودة', 'Open the draft') : tx('اختمها كمسودة محضر', 'Seal it as a draft record')}</button>
                  <button className="btn dark" type="button" disabled={!!td} onClick={async () => setTd(await engine.takedown(d.id))}>{tx('جهّز طلب الإزالة', 'Prepare the takedown')}</button>
                </>
              )}
            </div>
          )}
          {done && <Ticks items={[{ text: { ar: 'سُجّل كنشاط مرخّص · تعلّمه السجل', en: 'Recorded as licensed · the register learned it' } }]} />}
          {td && <TakedownView pkg={td} />}
        </div>
      </div>
    </>
  );
}

export function CheckPage() {
  const { tx } = useLang(); const engine = useEngine();
  const [results, setResults] = useState<ScoreResult[]>([]);
  return (
    <>
      <Head title={tx('فحص عنوان', 'Check an address')} sub={tx('أخضر رسمي، رمادي بلا اتهام، أحمر بسببين مستقلين. العنوان وحده، لا نفتح الصفحة.', 'Green official, grey not accused, red with two independent reasons. The address alone; the page is never opened.')} />
      <CheckPanel results={results} onCheck={async link => { const r = await engine.score(link); setResults(x => [r, ...x.filter(y => y.host !== r.host)].slice(0, 8)); }} />
    </>
  );
}

function RegisterPage() {
  const { t, tx } = useLang(); const engine = useEngine();
  const [q, setQ] = useState('');
  const [reg] = useLoad<RegisterList>(() => engine.register(q), [q]);
  return (
    <>
      <Head title={tx('السجل', 'Register')} sub={reg ? tx(`أبوظبي الحقيقية: ${reg.total} عنواناً رسمياً في عائلاتها.`, `The real Abu Dhabi: ${reg.total} official addresses in their families.`) : ''} />
      <Card title={tx('العائلات', 'Families')} sub={tx('ابحث لترى أيضاً الأسماء العامة من القائمة', 'Search to also see the generic names from the list')} marks={reg ? [reg.marker] : undefined}>
        <div className="field"><input aria-label={tx('ابحث في السجل', 'Search the register')} placeholder={tx('ابحث في السجل', 'Search the register')} value={q} onChange={e => setQ(e.target.value)} /></div>
        {reg?.families.map(x => (
          <div key={x.id} className="row" style={{ gridTemplateColumns: '1fr auto', marginTop: 8, cursor: 'default' }}>
            <span><span className="t">{t(x.name)}</span><div className="doors" style={{ justifyContent: 'flex-start', marginTop: 6 }}>{x.addresses.map(d => <span key={d} className="door">{d}</span>)}</div></span>
            <Mks marks={[x.marker]} />
          </div>
        ))}
      </Card>
      <Card title={tx('تعلّمه السجل', 'Learned')} sub={tx('أنشطة مرخّصة تشبه الخدمات الحكومية: رمادي، بلا اتهام', 'Licensed look-alikes: grey, not accused')}>
        {reg?.learned.length ? <div className="doors" style={{ justifyContent: 'flex-start' }}>{reg.learned.map(x => <span key={x} className="door new">{x}</span>)}</div>
          : <p className="small mut">{tx('لا شيء بعد. من «الحالات» اضغط «ليس احتيالاً» على الحالة الرمادية.', 'Nothing yet. In Cases, press "Not a scam" on the grey case.')}</p>}
      </Card>
    </>
  );
}

function DrillPage() {
  const { tx } = useLang(); const engine = useEngine();
  const [d] = useLoad<DrillInfo>(() => engine.drill());
  return (
    <>
      <Head title={tx('التمرين', 'Drill')} sub={tx('نهاجم أنفسنا ونرى من يلتقط: تمرين الجاهزية، يوم المحتال، وتزييف الحكام.', "We attack ourselves and see who catches it: the readiness drill, the attacker's day, and the judges' fakes.")} />
      <Card title={tx('هاجم والتقط', 'Attack and catch')} marks={d ? [d.marker, { kind: 'real', note: "judges' fakes" }] : undefined}>{d && <DrillView d={d} />}</Card>
    </>
  );
}

function ScalePage() {
  const { tx } = useLang(); const engine = useEngine();
  const [f] = useLoad<Feeds>(() => engine.feeds());
  return (
    <>
      <Head title={tx('الحجم', 'Scale')} sub={tx('كم يولد على الإنترنت الآن، وكم يصل إلى مكتبك.', 'How much is born on the internet right now, and how much reaches your desk.')} />
      {f && <ScaleView feeds={f} />}
      {f && <div style={{ marginTop: 14 }}><FunnelView feeds={f} /></div>}
    </>
  );
}

function RecordsPage() {
  const { tx } = useLang(); const engine = useEngine();
  const edits = useRef<Record<string, SealedRecord["fields"]>>({});
  const [recs, reload] = useLoad<SealedRecord[]>(() => engine.records());
  const [pick, setPick] = useState<string | null>(null);
  if (!recs) return null;
  const cur = recs.find(r => r.id === pick) || recs[recs.length - 1];
  return (
    <>
      <Head title={tx('المحاضر', 'Records')} sub={tx('المسودات المختومة. غيّر حرفاً واحداً وينكسر الختم.', 'Sealed drafts. Change one letter and the seal breaks.')} />
      {!recs.length ? <RecordsList records={recs} /> : (
        <div className="g2 split">
          <RecordsList records={recs} picked={cur.id} onPick={r => setPick(r.id)} />
          <RecordView key={cur.id + cur.status} record={cur} onFields={f => { edits.current[cur.id] = f; }} onApprove={async () => { await engine.approve(cur.id, 'click', edits.current[cur.id]); reload(); }} />
        </div>
      )}
    </>
  );
}

function AgentsPage() {
  const { t, tx } = useLang(); const engine = useEngine();
  const [a] = useLoad<AgentsState>(() => engine.agents());
  if (!a) return null;
  return (
    <>
      <Head title={tx('الوكلاء', 'Agents')} sub={tx('من يفعل ماذا الآن، وآخر حالة حقيقية تنتقل بينهم.', 'Who is doing what now, and the last real case travelling between them.')} />
      <Card title={tx('الآن', 'Right now')}><AgentsRow a={a} /></Card>
      <Card title={tx('آخر حالة حقيقية', 'The last real case')} sub={a.lastCase ? `«${t(a.lastCase.query)}» · ${clock(a.lastCase.at)}` : tx('لا جولة بعد', 'No round yet')} marks={a.lastCase ? [a.lastCase.marker] : undefined}><AgentsFlow a={a} /></Card>
    </>
  );
}

export function Studio({ page, setPage, watch, onRunNow, needDecision }: { page: Page; setPage: (p: Page) => void; watch: WatchState | null; onRunNow: () => void; needDecision: number | null }) {
  const { t } = useLang();
  return (
    <section className="studio" data-testid="studio">
      <nav className="side">
        {PAGES.map(([k, n]) => (
          <button key={k} type="button" className={page === k ? 'on' : ''} onClick={() => setPage(k)}><Icon k={k} /><span>{t(n)}</span>{k === 'cases' && needDecision != null && <span className="badge">{needDecision}</span>}</button>
        ))}
      </nav>
      <div className="main" data-page={page}>
        {page === 'watch' && <WatchPage watch={watch} onRunNow={onRunNow} />}
        {page === 'cases' && <CasesPage go={setPage} />}
        {page === 'check' && <CheckPage />}
        {page === 'register' && <RegisterPage />}
        {page === 'drill' && <DrillPage />}
        {page === 'scale' && <ScalePage />}
        {page === 'records' && <RecordsPage />}
        {page === 'agents' && <AgentsPage />}
      </div>
    </section>
  );
}
