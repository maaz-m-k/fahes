/* Real footage of a browser at work, sped up: real video players in a phone frame and a computer window, with one
   play/pause and one scrub bar for both, a speed label, and the agent's step captions in time with the video. */
import { useEffect, useRef, useState } from 'react';
import type { Footage } from '../api/types';
import { useLang } from '../i18n';
import { Mk } from './basics';

export type FootageItem = { key: string; frame: 'phone' | 'window'; label: string; f: Footage; url?: string };

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s) % 60).padStart(2, '0')}`;

export function FootagePlayer({ items, fill }: { items: FootageItem[]; fill?: boolean }) {
  const { tx, ar } = useLang();
  const refs = useRef<Record<string, HTMLVideoElement | null>>({});
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(true);
  const all = () => items.map(i => refs.current[i.key]).filter(Boolean) as HTMLVideoElement[];
  const longest = () => all().reduce<HTMLVideoElement | null>((a, v) => (!a || (v.duration || 0) > (a.duration || 0) ? v : a), null);

  useEffect(() => { setT(0); setPlaying(true); }, [items.map(i => i.f.src).join('|')]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    for (const v of all()) { if (playing) { const p = v.play?.(); p?.catch?.(() => setPlaying(false)); } else v.pause?.(); }
  }, [playing]); // eslint-disable-line react-hooks/exhaustive-deps
  const seek = (s: number) => { for (const v of all()) { try { v.currentTime = Math.min(s, v.duration || s); } catch { /* not loaded */ } } setT(s); };
  const caption = (it: FootageItem) => {
    const real = t * it.f.speed * 1000; const m = it.f.moments.filter(x => x.t <= real).at(-1) || it.f.moments[0];
    return m ? (ar ? m.ar : m.en) : '';
  };
  const speed = items[0]?.f.speed || 1;

  return (
    <div className={'fp' + (fill ? ' fill' : '')} data-testid="footage">
      <div className={'rp-stage ' + (items.length === 1 ? 'one ' + (items[0].frame === 'phone' ? 'phone' : 'computer') : 'both')}>
        {items.map(it => {
          const video = (
            <video ref={el => { refs.current[it.key] = el; }} src={it.f.src} muted playsInline autoPlay preload="auto" aria-label={it.label}
              onLoadedMetadata={() => setDur(longest()?.duration || 0)}
              onTimeUpdate={e => { if (e.currentTarget === longest()) setT(e.currentTarget.currentTime); }}
              onEnded={e => { if (e.currentTarget === longest()) setPlaying(false); }} />
          );
          return (
            <figure key={it.key} className={'rp-dev ' + (it.frame === 'phone' ? 'phone' : 'computer')}>
              {it.frame === 'phone'
                ? <div className="rp-phone"><span className="rp-notch" /><div className="rp-screen fp-screen" style={{ aspectRatio: `${it.f.width} / ${it.f.height}` }}>{video}<span className="fp-speed">{speed}×</span></div></div>
                : <div className="rp-win"><div className="rp-bar"><i /><i /><i /><span className="addr">{it.url || ''}</span></div><div className="rp-screen fp-screen" style={{ aspectRatio: `${it.f.width} / ${it.f.height}` }}>{video}<span className="fp-speed">{speed}×</span></div></div>}
              <figcaption><b>{it.label}</b> <Mk m={it.f.marker} /><span className="rp-cap" data-testid={'fcap-' + it.key}>{caption(it)}</span></figcaption>
            </figure>
          );
        })}
      </div>
      <div className="rp-ctl">
        <button className="play" type="button" aria-label={playing ? tx('إيقاف مؤقت', 'pause') : tx('تشغيل', 'play')}
          onClick={() => { if (!playing && dur && t >= dur - 0.05) seek(0); setPlaying(p => !p); }}>{playing ? '❚❚' : '▶'}</button>
        <div className="rp-track" dir="ltr">
          <input type="range" min={0} max={dur || 1} step={0.05} value={Math.min(t, dur || 1)} aria-label={tx('الخط الزمني', 'timeline')}
            onChange={e => { setPlaying(false); seek(Number(e.target.value)); }} />
        </div>
        <span className="rp-time" dir="ltr">{mmss(t)} / {mmss(dur)} · {speed}×</span>
      </div>
    </div>
  );
}
