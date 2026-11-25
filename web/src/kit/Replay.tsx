/* The replay of a watch round as a smooth, video-like playback: the agent's captures cross-fade and pan gently on one
   timeline, inside a phone frame and a computer window, with play/pause and scrubbing. Both devices share the timeline,
   and an amber ring marks what one device saw and the other did not. */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { CaptureStep, Device, Round } from '../api/types';
import { clock, useLang } from '../i18n';
import { Piece } from './basics';
import { GreyDot } from './pieces';
import { FootagePlayer, type FootageItem } from './FootagePlayer';

type Step = CaptureStep & { v: Device };
const TAIL = 2200; // the last capture stays on screen a moment

function activeIndex(steps: Step[], t: number) { let k = 0; steps.forEach((s, i) => { if (s.at <= t) k = i; }); return k; }

function Screen({ steps, t, base }: { steps: Step[]; t: number; base: string }) {
  const k = activeIndex(steps, t);
  const next = steps[k + 1]?.at ?? steps[k].at + TAIL;
  const p = Math.max(0, Math.min(1, (t - steps[k].at) / Math.max(1, next - steps[k].at)));
  return (
    <div className="rp-screen">
      {steps.map((s, i) => (
        <img key={s.shot} alt="" src={base + s.shot} className={'rp-layer' + (i === k ? ' on' : '')} loading="eager" decoding="async"
          style={i === k ? { transform: `scale(${1.012 - 0.012 * p}) translateY(${(1 - p) * 1.2}%)` } : undefined} />
      ))}
    </div>
  );
}

export function Replay({ round, ci, view, fill }: { round: Round; ci: number; view: 'both' | Device; fill?: boolean }) {
  const { tx, ar } = useLang();
  const k = round.cases[ci];
  const views: Device[] = view === 'both' ? ['computer', 'phone'] : [view];
  const byView = useMemo(() => Object.fromEntries(views.map(v => [v, k[v].steps.map(s => ({ ...s, v }))])) as Record<Device, Step[]>, [k, view]); // eslint-disable-line react-hooks/exhaustive-deps
  const all = useMemo(() => views.flatMap(v => byView[v] || []).sort((a, b) => a.at - b.at), [byView]); // eslint-disable-line react-hooks/exhaustive-deps
  const dur = Math.max(1000, ...all.map(s => s.at)) + TAIL;
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(true);
  const last = useRef(0);
  useEffect(() => { setT(0); setPlaying(true); }, [ci, view, round.id]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0; last.current = performance.now();
    const tick = (now: number) => {
      const dt = now - last.current; last.current = now;
      setT(x => { const n = Math.min(dur, x + dt); if (n >= dur) setPlaying(false); return n; });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, dur]);
  const only = { computer: k.onlyComputer, phone: k.onlyPhone };
  const cur = (v: Device) => { const s = byView[v]; return s?.length ? s[activeIndex(s, t)] : null; };
  const mmss = (ms: number) => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

  const src = round.footage || k.footage;
  const foot = src ? views.flatMap(v => (src[v] ? [{ key: v, frame: v === 'phone' ? 'phone' : 'window', label: v === 'phone' ? tx('هاتف · وضع iPhone', 'Phone · iPhone mode') : tx('حاسوب', 'Computer'), f: src[v]! } as FootageItem] : [])) : [];
  const clips = (round.clips || []).map(c => ({ label: c.label, items: views.flatMap(v => (c.footage[v] ? [{ key: 'clip-' + v, frame: v === 'phone' ? 'phone' : 'window', label: ar ? c.label.ar : c.label.en, f: c.footage[v]! } as FootageItem] : [])) })).filter(c => c.items.length);
  if (foot.length) return (
    <Piece head={round.footage ? tx(`آخر جولة · ${round.cases.length} أسئلة المقيمين`, `The last round · residents' questions`) : `«${ar ? k.ar : k.q}»`} marks={[foot[0].f.marker]} className={'rp' + (fill ? ' fill' : '')}>
      <div data-testid="replay" data-view={view}><FootagePlayer items={foot} fill={fill} /></div>
      {clips.map((c, i) => <div key={i} style={{ marginTop: 16 }} data-testid="extra-clip"><div className="small mut" style={{ marginBottom: 6 }}>{ar ? c.label.ar : c.label.en}</div><FootagePlayer items={c.items} /></div>)}
    </Piece>
  );
  return (
    <Piece head={`«${ar ? k.ar : k.q}» · ${k.computer.engine || k.phone.engine || ''} · ${Math.round(k.ms / 1000)} ${tx('ث', 's')}`}
      marks={[{ kind: round.marker.kind, note: 'REPLAY ' + clock(k.startedAt) }, { kind: 'stand', note: 'phone = emulation' }]}
      className={'rp' + (fill ? ' fill' : '')}>
      <div className={'rp-stage ' + (views.length === 1 ? 'one ' + view : 'both')} data-testid="replay" data-view={view}>
        {views.map(v => {
          const s = cur(v);
          return (
            <figure key={v} className={'rp-dev ' + v + (only[v].length ? ' diff' : '')} data-v={v}>
              {v === 'phone' ? (
                <div className="rp-phone"><span className="rp-notch" />{s && <Screen steps={byView[v]} t={t} base={round.shotBase} />}</div>
              ) : (
                <div className="rp-win">
                  <div className="rp-bar"><i /><i /><i /><span className="addr">{(s?.url || '').replace(/^https?:\/\//, '').slice(0, 70)}</span></div>
                  {s && <Screen steps={byView[v]} t={t} base={round.shotBase} />}
                </div>
              )}
              <figcaption>
                <b>{v === 'phone' ? tx('هاتف · Pixel 7', 'Phone · Pixel 7') : tx('حاسوب', 'Computer')}</b>
                {only[v].length > 0 && <span className="difftag">{tx(`رأى ${only[v].length} لم يرها الآخر`, `saw ${only[v].length} the other did not`)}</span>}
                <span className="rp-cap" data-testid={'caption-' + v}>{s ? (ar ? s.ar : s.en) : ''}</span>
              </figcaption>
            </figure>
          );
        })}
      </div>
      <div className="rp-ctl">
        <button className="play" type="button" aria-label={playing ? tx('إيقاف مؤقت', 'pause') : tx('تشغيل', 'play')} onClick={() => { if (t >= dur) setT(0); setPlaying(p => !p); }}>{playing ? '❚❚' : '▶'}</button>
        <div className="rp-track" dir="ltr">
          {all.map((s, i) => <span key={i} className={`rp-tick ${s.v}${s.at <= t ? ' past' : ''}`} style={{ left: (s.at / dur) * 100 + '%' }} />)}
          <input type="range" min={0} max={dur} step={10} value={Math.round(t)} aria-label={tx('الخط الزمني', 'timeline')}
            onChange={e => { setPlaying(false); setT(Number(e.target.value)); }} />
        </div>
        <span className="rp-time" dir="ltr">{mmss(t)} / {mmss(dur)}</span>
      </div>
      {views.map(v => (
        <div key={v} style={{ marginTop: 10 }}>
          <div className="small mut" style={{ marginBottom: 6 }}>{v === 'phone' ? tx('الهاتف قرأ', 'The phone read') : tx('الحاسوب قرأ', 'The computer read')}</div>
          <div className="hosts">
            {k[v].results.length ? k[v].results.map((r, i) => r.verdict === 'green'
              ? <span key={i} className={`host green ${k[v].opened?.host === r.host ? 'opened' : ''} ${only[v].includes(r.host) ? 'only' : ''}`}><i />{r.host}</span>
              : <GreyDot key={i} host={r.host} only={only[v].includes(r.host)} />)
              : <span className="small mut">{k[v].robot.length ? tx('فحص روبوت: توقف', 'robot check: stopped') : '—'}</span>}
          </div>
        </div>
      ))}
      {<p className="small mut" style={{ margin: '8px 0 0' }}>{tx('● أخضر رسمي (مفتوح بإطار) · نقطة رمادية: غير رسمي، الاسم عند الضغط · إطار كهرماني: رآه جهاز واحد فقط', '● green official (ringed = opened) · grey dot: not official, name on tap · amber ring: seen by one device only')}</p>}
    </Piece>
  );
}
