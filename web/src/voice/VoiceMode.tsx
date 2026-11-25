/* Voice mode, the Mira way: the orb rests big; an answer that needs a screen sends the orb to the top and a card is born
   below it; the card stays while the conversation goes on and its content changes in place; it folds back into the
   orb only on "close" (voice or ×) or when an answer needs no screen. */
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { Lang, Marker, ToolName, WatchState } from '../api/types';
import { useEngine, useLang } from '../i18n';
import { SchedulePill } from '../kit/pieces';
import { Mk } from '../kit/basics';
import { AnswerCard, type CardActions } from './AnswerCard';
import { deskReducer, initialDesk } from './desk';
import { match } from './matcher';
import { Orb, type Levels, type OrbState } from './Orb';
import { RealtimeVoice, type RtHooks, type VoiceLike, type VoiceProblem, type VoiceStatus } from './realtime';
import { runTool, TOOL_NAMES, type Answer, type ToolContext } from './tools';

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/* keeps the shown answer a moment longer so it can cross-fade (swap) or fold into the orb (collapse) */
function useAnimatedAnswer(answer: Answer | null, version: number) {
  const [shown, setShownRaw] = useState<Answer | null>(answer);
  const [key, setKey] = useState(0);
  const setShown = (a: Answer | null) => { setShownRaw(a); setKey(k => k + 1); };
  const [anim, setAnim] = useState<'' | 'swap' | 'collapse'>('');
  const cur = useRef(shown); cur.current = shown;
  useEffect(() => {
    let live = true;
    (async () => {
      if (!answer && cur.current) { setAnim('collapse'); await sleep(430); if (live) { setShown(null); setAnim(''); } return; }
      if (answer && cur.current && answer.card.kind === 'check' && cur.current.card.kind === 'check') { setShownRaw(answer); return; } // another link in the same checker
      if (answer && cur.current) { setAnim('swap'); await sleep(280); if (live) { setShown(answer); setAnim(''); } return; }
      setShown(answer); setAnim('');
    })();
    return () => { live = false; };
  }, [answer, version]);
  return { shown, anim, key };
}

function say(text: string, lang: string, onEnd: () => void) {
  const mute = new URLSearchParams(location.search).get('mute') === '1';
  if (mute || typeof speechSynthesis === 'undefined') { setTimeout(onEnd, Math.min(4000, 600 + text.length * 40)); return; }
  try {
    speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = lang === 'ar' ? 'ar-AE' : 'en-US';
    const v = speechSynthesis.getVoices().find(x => x.lang === u.lang); if (v) u.voice = v;
    u.onend = onEnd; u.onerror = onEnd; setTimeout(onEnd, 2500 + text.length * 90); speechSynthesis.speak(u);
  } catch { onEnd(); }
}

type VoiceProps = {
  watch: WatchState | null; onRunNow: () => void; onOpenStudio: (page: string) => void;
  toolPort?: (fn: (name: string, args: Record<string, unknown>) => Promise<unknown>) => void;
  onHeard?: (text: string) => Lang | null; // the screen follows the officer's language; returns the language now on screen
  makeVoice?: (hooks: RtHooks) => VoiceLike; // tests pass a fake session here
};

export function VoiceMode({ watch, onRunNow, onOpenStudio, toolPort, onHeard, makeVoice }: VoiceProps) {
  const engine = useEngine();
  const { lang, t, tx } = useLang();
  const [desk, dispatch] = useReducer(deskReducer, initialDesk);
  const ctx = useRef<ToolContext>({ focusCaseId: null, edits: {}, checks: [] });
  const levels = useRef<Levels>({ user: 0, self: 0, typing: 0, on: false });
  const [orb, setOrb] = useState<OrbState>('idle');
  const [heard, setHeard] = useState('');
  const [brain, setBrain] = useState<Marker>({ kind: 'real', note: 'realtime' });
  const [status, setStatus] = useState<VoiceStatus>('off');
  const [model, setModel] = useState('');
  const [problem, setProblem] = useState<VoiceProblem | null>(null);
  const [fallback, setFallback] = useState<VoiceProblem | null>(null); // realtime could not run: answers use the labelled fallback
  const [text, setText] = useState('');
  const langRef = useRef(lang); langRef.current = lang;
  const statusRef = useRef(status); statusRef.current = status;
  const failed = useRef(false);
  const { shown, anim, key: shownKey } = useAnimatedAnswer(desk.answer, desk.version);

  const hear = (v: string) => { setHeard(v); const l = onHeard?.(v); if (l) langRef.current = l; };

  /* run a tool and show its card. Speech: the realtime voice speaks for itself; the browser voice only as the fallback */
  const run = useCallback(async (name: ToolName, args: Record<string, unknown>, via: 'voice' | 'click', mark: Marker) => {
    setOrb('think'); setBrain(mark);
    const tool = TOOL_NAMES.includes(name) ? name : 'help';
    const r = await runTool(engine, ctx.current, tool, args, via);
    dispatch({ type: 'result', result: r });
    if (statusRef.current === 'on') setOrb('listen');
    else if (failed.current) { setOrb('speak'); say(r.say[langRef.current], langRef.current, () => setOrb(o => (o === 'speak' ? 'idle' : o))); }
    else setOrb('idle');
    return r.output;
  }, [engine]);

  const rt = useRef<VoiceLike | null>(null);
  if (!rt.current) {
    const hooks: RtHooks = {
      engine, lang: () => langRef.current, levels,
      onStatus: (s, m) => { setStatus(s); if (m) setModel(m); },
      onOrb: setOrb, onHeard: hear,
      onProblem: p => { if (p?.quiet) { failed.current = true; setFallback(p); } else setProblem(p); },
      onTool: (name, args) => run(name as ToolName, args, 'voice', { kind: 'real', note: 'realtime · ' + (rt.current?.model || 'gpt-realtime-2.1') }),
      testAudio: new URLSearchParams(location.search).get('testaudio'),
    };
    rt.current = makeVoice ? makeVoice(hooks) : new RealtimeVoice(hooks);
  }
  useEffect(() => () => rt.current?.stop(), []);
  // the voice tool seam: the same entry the realtime session calls, handed to tests that simulate the model's tool calls
  useEffect(() => { toolPort?.((name, args) => run(name as ToolName, args, 'voice', { kind: 'real', note: 'realtime (simulated)' })); }, [toolPort, run]);

  /* typed or pasted text joins the live voice conversation (starting it if needed); the fallback answers only if it cannot run */
  const typed = async (raw: string) => {
    const v = raw.trim(); if (!v) return;
    hear(v);
    const voice = rt.current!;
    setOrb('think');
    if (voice.on || voice.connecting) { voice.sendText(v); return; }
    if (!failed.current && (await voice.start({ quiet: true }))) { voice.sendText(v); return; }
    failed.current = true;
    let u; try { u = await engine.understand(v, langRef.current); } catch { u = match(v); }
    if (u.tool === 'help') { const l = match(v); if (l.tool !== 'help') u = l; } // the model was unsure; the matcher knows the words
    await run(u.tool, u.args, 'click', { kind: 'stand', note: (u.source === 'model' ? 'brain' : 'local matcher') + ' · browser voice' });
  };
  const talk = () => {
    const voice = rt.current!;
    if (voice.on || voice.connecting) voice.stop();
    else { failed.current = false; setFallback(null); void voice.start(); }
  };
  const close = () => { try { speechSynthesis?.cancel(); } catch { /* none */ } dispatch({ type: 'close' }); };

  /* a tap does what saying it does: the same tool; a live session is told what is now on screen */
  const tap = async (name: ToolName, args: Record<string, unknown>, label: string, via: 'voice' | 'click' = 'click') => {
    const out = await run(name, args, via, brain);
    if (rt.current?.on) rt.current.sendNote(`${label}. Facts: ${JSON.stringify(out).slice(0, 1500)}`);
  };
  const act: CardActions = {
    chip: c => void tap(c.tool, c.args || {}, c.label.en),
    pickCase: n => void tap('show_case', { n }, 'Opened case ' + n),
    recordFields: (id, f) => { ctx.current.edits[id] = f; },
    approveClick: () => void tap('approve', {}, 'Approved by click'),
    check: link => tap('check_address', { domain: link }, 'Checked ' + link),
  };
  void onOpenStudio;

  const answering = !!shown;
  const idleLine = desk.line ? t(desk.line) : heard ? '«' + heard + '»' : tx('صباح الخير.', 'Good morning.');
  return (
    <>
      <section className="voice" data-testid="voice" data-phase={answering ? 'answering' : 'idle'}>
        <div id="actV"><SchedulePill w={watch} onRunNow={onRunNow} /></div>
        <div className={`glass${answering ? ' answer' : ''}${shown?.card.kind === 'replay' ? ' wide' : ''}${anim === 'collapse' ? ' collapsing' : ''}${problem ? ' hasproblem' : ''}`} data-testid="glass">
          {answering && <button className="closecard" type="button" aria-label={tx('إغلاق', 'close')} onClick={close}>×</button>}
          <div className="orbslot" role="button" tabIndex={0} aria-label={tx('تكلّم', 'talk')} onClick={talk}><Orb state={orb} levels={levels} /></div>
          <button className={'talkbtn' + (status === 'on' ? ' live' : '')} type="button" disabled={status === 'connecting'} onClick={talk} title={status === 'on' ? 'REAL · realtime (' + model + ')' : ''}>
            {status === 'connecting' ? tx('لحظة…', 'One moment…') : status === 'on' ? <><i />{tx('أستمع · اضغط للإنهاء', 'Listening · tap to end')}</>
              : <><svg viewBox="0 0 24 24"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-2.1A7 7 0 0 0 19 12Z" /></svg>{tx('تكلّم مع فاحص', 'Talk to Fahes')}</>}
          </button>
          {!answering && <div className="hint" data-testid="line">{idleLine}</div>}
          {problem && (
            <div className="vproblem" role="alert" data-testid="voice-problem">
              <b>{tx('الصوت لم يعمل', 'Voice did not start')}</b><span>{t(problem.text)}</span>
              {problem.detail && <small dir="ltr">{problem.detail.slice(0, 140)}</small>}
              <span className="vrow">
                <button type="button" className="chip pri" onClick={() => { setProblem(null); void rt.current?.start(); }}>{tx('حاول مرة أخرى', 'Try again')}</button>
                <button type="button" className="chip" onClick={() => { setProblem(null); document.getElementById('cmd')?.focus(); }}>{tx('اكتب بدلاً من ذلك', 'Type instead')}</button>
              </span>
            </div>
          )}
          <div className={'born' + (anim ? ' ' + anim : '')} data-testid="born">
            {shown && <AnswerCard key={shownKey} answer={shown} brain={brain} act={act} />}
          </div>
        </div>
      </section>
      <div className="askwrap">
        {fallback && <div className="fallnote" data-testid="fallback-note"><Mk m={{ kind: 'stand', note: 'browser voice' }} /> {tx('الصوت الفوري غير متاح؛ أجيب بالبديل.', 'Live voice is not available; answering with the fallback.')} <small dir="ltr">{fallback.detail?.slice(0, 80)}</small></div>}
        <div className="askbar">
          <input id="cmd" aria-label={tx('اكتب سؤالاً أو عنواناً', 'Type a question or an address')} autoComplete="off" spellCheck={false} value={text}
            placeholder={tx('اكتب سؤالاً أو عنواناً…', 'Type a question or an address…')}
            onChange={e => { setText(e.target.value); levels.current.typing = 0.25 + Math.random() * 0.35; }}
            onFocus={() => { if (status !== 'on') setOrb('listen'); }}
            onBlur={() => { levels.current.typing = 0; setOrb(o => (o === 'listen' && status !== 'on' ? 'idle' : o)); }}
            onKeyDown={e => { if (e.key === 'Enter') { const v = text; setText(''); void typed(v); } }} />
        </div>
      </div>
    </>
  );
}
