/* <Orb>: the living circle. States: idle (breathes a little), listen (reacts strongly to the mic), speak (pulses with
   Fahes's voice), think. `levels` is a live ref the voice session writes the measured audio levels into. */
import { useEffect, useRef } from 'react';
import { makeOrb, TEAL } from './orbGl.js';

export type OrbState = 'idle' | 'listen' | 'think' | 'speak';
export type Levels = { user: number; self: number; typing: number; on: boolean };

export function Orb({ state, levels }: { state: OrbState; levels: React.MutableRefObject<Levels> }) {
  const cv = useRef<HTMLCanvasElement>(null);
  const st = useRef(state); st.current = state;
  useEffect(() => {
    const canvas = cv.current; if (!canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1); canvas.width = canvas.height = Math.round(420 * dpr);
    let gl = null; try { gl = makeOrb(canvas, TEAL); } catch { gl = null; }
    if (!gl) return; // no WebGL (tests, old browsers): the slot stays empty
    const E = { user: 0, self: 0, ph: 0 }; let last = performance.now(); let raf = 0;
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; const t = now / 1000; const s = st.current, L = levels.current;
      let uT = s === 'listen' ? Math.max(L.typing, 0.12) : s === 'think' ? 0.18 + 0.08 * Math.sin(t * 5) : 0;
      let sT = s === 'speak' ? 0.3 + 0.35 * Math.abs(Math.sin(t * 7.4)) * (0.6 + 0.4 * Math.sin(t * 1.7)) : 0;
      if (L.on) { uT = Math.max(uT, Math.min(1, L.user * 1.15)); if (L.self > 0.02) sT = Math.max(sT, 0.2 + Math.min(1, L.self) * 0.95); }
      E.user += (uT - E.user) * (uT > E.user ? 0.35 : 0.06);
      E.self += (sT - E.self) * (sT > E.self ? 0.3 : 0.08);
      E.ph += dt * (1 + 3.2 * E.user + 1.2 * E.self);
      gl!.draw(t, E.ph, E.user, E.self);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [levels]);
  return <div className="orb" data-state={state} data-testid="orb"><canvas ref={cv} /></div>;
}
