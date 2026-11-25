/* The judges' page: paste links or upload a .txt/.csv, get each verdict with its reasons, download a CSV.
   Same scoring as the judges' command in the README (the engine's batch endpoint, mode "judging"). */
import { useState } from 'react';
import type { ScoreResult } from '../api/types';
import { useEngine, useLang } from '../i18n';
import { Pill } from '../kit/basics';

export function linksFrom(text: string): string[] {
  const out: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    for (const cell of line.split(/[,;\t]/)) {
      const v = cell.trim().replace(/^"|"$/g, '');
      if (v && /[a-z0-9-]\.[a-z]{2,}/i.test(v) && !/^(link|url|address)$/i.test(v)) { out.push(v); break; }
    }
  }
  return out;
}

const csvCell = (s: string) => '"' + String(s).replace(/"/g, '""') + '"';
export function toCsv(rows: ScoreResult[]): string {
  return ['link,verdict,score,reasons_en,reasons_ar'].concat(rows.map(r => [r.link || r.host, r.verdict, r.score ?? '', r.reasons.map(x => x.en).join(' | '), r.reasons.map(x => x.ar).join(' | ')].map(x => csvCell(String(x))).join(','))).join('\n');
}

export function JudgesPage() {
  const { t, tx } = useLang(); const engine = useEngine();
  const [text, setText] = useState('');
  const [rows, setRows] = useState<ScoreResult[]>([]);
  const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const go = async () => {
    const links = linksFrom(text); if (!links.length) return;
    setBusy(true); setErr('');
    try { setRows(await engine.scoreBatch(links)); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const file = async (f: File | undefined) => { if (f) setText(await f.text()); };
  const download = () => {
    const url = URL.createObjectURL(new Blob(['﻿' + toCsv(rows)], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = 'fahes-verdicts.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const n = linksFrom(text).length;
  return (
    <>
      <div className="main-h"><div><h1>{tx('للحكام', 'For judges')}</h1><p>{tx('الصق روابط أو ارفع ملف ‎.txt أو ‎.csv، واحصل على حكم كل رابط وأسبابه. التقييم نفسه الذي يعطيه أمر الحكام.', "Paste links or upload a .txt or .csv file and get each link's verdict with its reasons. The same scoring as the judges' command.")}</p></div></div>
      <section className="card">
        <textarea aria-label={tx('الروابط', 'links')} dir="ltr" rows={8} value={text} onChange={e => setText(e.target.value)} placeholder={'adpolice-fines.top\nhttps://www.tamm.abudhabi/\nabudhabip0lice-pay.com'} className="judges-text" />
        <div className="rec-act" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
          <label className="btn sec" style={{ cursor: 'pointer' }}>{tx('ارفع ملفاً', 'Upload a file')}<input type="file" accept=".txt,.csv,text/plain,text/csv" hidden aria-label="file" onChange={e => file(e.target.files?.[0])} /></label>
          <button className="btn" type="button" disabled={!n || busy} onClick={go}>{busy ? tx('لحظة…', 'One moment…') : tx(`قيّم ${n} رابطاً`, `Score ${n} links`)}</button>
          {rows.length > 0 && <button className="btn dark" type="button" onClick={download}>{tx('نزّل CSV', 'Download CSV')}</button>}
        </div>
        {err && <p className="small" role="alert" style={{ color: 'var(--red2)' }}>{err}</p>}
        {rows.length > 0 && (
          <p className="small mut" data-testid="judges-summary">{tx(`${rows.filter(r => r.verdict === 'red').length} أحمر · ${rows.filter(r => r.verdict === 'grey').length} رمادي · ${rows.filter(r => r.verdict === 'green').length} أخضر`, `${rows.filter(r => r.verdict === 'red').length} red · ${rows.filter(r => r.verdict === 'grey').length} grey · ${rows.filter(r => r.verdict === 'green').length} green`)}</p>
        )}
        <div data-testid="judges-results">
          {rows.slice(0, 500).map((r, i) => (
            <div key={i} className="row" style={{ gridTemplateColumns: '1fr auto', marginTop: 8, cursor: 'default' }}>
              <span><span className="addr">{r.link || r.host}</span><br /><span className="m">{r.reasons.map(x => t(x)).join(' · ')}</span></span>
              <Pill v={r.verdict} sm />
            </div>
          ))}
          {rows.length > 500 && <p className="small mut">{tx('أول 500 فقط على الشاشة؛ الملف فيه الكل.', 'The first 500 on screen; the CSV has all of them.')}</p>}
        </div>
      </section>
    </>
  );
}
