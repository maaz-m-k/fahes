/* The small parts every screen shares: verdict pills, reasons, pieces, ticks, chips, icons. */
import type { ReactNode } from 'react';
import type { Bi, Reason, Verdict } from '../api/types';
import { useLang } from '../i18n';

const VERD: Record<Verdict, Bi> = { green: { ar: 'رسمي', en: 'Official' }, grey: { ar: 'غير رسمي، بدون اتهام', en: 'Not official, not accused' }, red: { ar: 'مشتبه بأنه وهمي، بأسباب', en: 'Suspected fake, with reasons' } };
export const verdictWords = (v: Verdict) => VERD[v];
export function Pill({ v, sm }: { v: Verdict; sm?: boolean }) {
  const { t } = useLang();
  return <span className={`pill ${v} ${sm ? 'sm' : ''}`} data-verdict={v}><i />{t(VERD[v])}</span>;
}

export function Reasons({ reasons, v, max }: { reasons: Reason[]; v: Verdict | string; max?: number }) {
  return (
    <ol className={'reasons ' + v}>
      {reasons.slice(0, max || 9).map((r, i) => (
        <li key={i}><b>{i + 1}</b><span><span className="ar">{r.ar}</span><span className="en">{r.en}</span></span></li>
      ))}
    </ol>
  );
}

export function Piece({ head, children, className }: { head?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={'piece' + (className ? ' ' + className : '')}>
      {head && <div className="piece-h"><span>{head}</span></div>}
      {children}
    </div>
  );
}

const CK = <svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
const NO = <svg viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17" /></svg>;
export function Ticks({ items }: { items: { text: Bi; no?: boolean }[] }) {
  const { t } = useLang();
  return (
    <ul className="done" data-testid="done">
      {items.map((x, k) => <li key={k} className={x.no ? 'no' : ''} style={{ animationDelay: k * 220 + 'ms' }}><span className="ck">{x.no ? NO : CK}</span><span>{t(x.text)}</span></li>)}
    </ul>
  );
}

export const Addr = ({ a }: { a: string }) => <bdi className="addr">{a}</bdi>;

const IC: Record<string, string> = {
  watch: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
  cases: '<rect x="3.5" y="4" width="17" height="16" rx="3"/><path d="M3.5 9h17M8 13.5h8M8 16.5h5"/>',
  check: '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 7.8 7.5 9 4.3-1.2 7.5-4.4 7.5-9V6Z"/><path d="m8.8 12 2.2 2.2 4.2-4.4"/>',
  register: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5Z"/><path d="M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"/><path d="M9 7.5h6M9 11h4"/>',
  drill: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3"/>',
  scale: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3Z"/>',
  records: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/><path d="M10 12h5M10 15.5h5"/>',
  agents: '<circle cx="8" cy="8.5" r="3"/><circle cx="16.5" cy="9.5" r="2.5"/><path d="M2.5 19.5a5.5 5.5 0 0 1 11 0"/><path d="M14 19.5a4 4 0 0 1 7.5-1.8"/>',
  capture: '<rect x="3" y="7" width="18" height="13" rx="3.5"/><path d="m8.5 7 1.6-2.5h3.8L15.5 7"/><circle cx="12" cy="13.5" r="3.3"/>',
  seal: '<path d="M7.5 5.5A7 7 0 0 1 19 11v1.5"/><path d="M5 9.5A7 7 0 0 0 5 13"/><path d="M8.5 11a3.5 3.5 0 0 1 7 0v2a8 8 0 0 1-1 4"/><path d="M12 11v2.5a10 10 0 0 1-2 6"/><path d="M6 16.5a10 10 0 0 0 1.5 2.5"/>',
  officer: '<circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/>',
  voice: '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="3"/>',
  studio: '<rect x="3.5" y="3.5" width="7" height="7" rx="2.2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2.2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2.2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2.2"/>',
  judges: '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0Zm14 0-3 7a3 3 0 0 0 6 0Z"/>',
  mic: '<path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-2.1A7 7 0 0 0 19 12Z"/>',
};
export const Icon = ({ k }: { k: string }) => <svg viewBox="0 0 24 24" dangerouslySetInnerHTML={{ __html: IC[k] || IC.voice }} />;

export function Spark({ values }: { values: number[] }) {
  if (!values || values.length < 3) return <svg className="spark" />;
  const d = values.slice(1).map((v, i) => v - values[i]); const mx = Math.max(...d, 1), w = 300, h = 46;
  const pts = d.map((v, i) => `${(i / (d.length - 1)) * w},${h - (v / mx) * (h - 6) - 3}`).join(' ');
  return <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" data-testid="spark"><polyline points={pts} fill="none" stroke="#A7F3D0" strokeWidth="1.6" /></svg>;
}
