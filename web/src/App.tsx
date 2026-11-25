/* Fahes desk: one dark app, two modes (Voice and Studio), Arabic first with an English switch. */
import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { EngineClient } from './api/client';
import type { Costs, Lang, WatchState } from './api/types';
import { EngineContext, LangContext, useLang } from './i18n';
import { Icon } from './kit/basics';
import { PAGES, Studio, type Page } from './studio/Studio';
import { VoiceMode } from './voice/VoiceMode';
import { followSpeech, type Heard } from './voice/lang';
import type { RtHooks, VoiceLike } from './voice/realtime';

function CostSheet({ onClose }: { onClose: () => void }) {
  const { t, tx } = useLang();
  const engine = useEngineSafe();
  const [costs, setCosts] = useState<Costs | null>(null);
  useEffect(() => { engine?.costs().then(setCosts).catch(() => undefined); }, [engine]);
  return (
    <aside className="sheet" data-testid="cost-sheet">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><b style={{ fontSize: 18 }}>{tx('التكلفة', 'Cost')}</b><button className="ghost" type="button" onClick={onClose}>{tx('إغلاق', 'Close')}</button></div>
      {costs && (
        <div className="piece" data-testid="costs" style={{ marginBottom: 12 }}>
          <ul className="parts">{costs.soFar.map((c, i) => <li key={i}><span>{t(c.item)}<small>${c.usd.toFixed(c.usd < 1 ? 4 : 2)} {tx('حتى الآن', 'so far')}</small></span></li>)}</ul>
          <p className="small">{tx('المتوقع شهرياً', 'Projected a month')}: <b>${costs.projectedMonthUsd}</b> · <span className="mut">{t(costs.projectedNote)}</span></p>
        </div>
      )}
    </aside>
  );
}
function useEngineSafe() { return useContext(EngineContext); }

export type AppInitial = { lang?: Lang; mode?: 'voice' | 'studio'; page?: Page };
export function App({ engine, initial = {}, toolPort, makeVoice }: { engine: EngineClient; initial?: AppInitial; toolPort?: (fn: (name: string, args: Record<string, unknown>) => Promise<unknown>) => void; makeVoice?: (hooks: RtHooks) => VoiceLike }) {
  const q = new URLSearchParams(typeof location !== 'undefined' ? location.search : '');
  const [lang, setLang] = useState<Lang>(initial.lang || (q.get('lang') === 'en' ? 'en' : 'ar'));
  const [mode, setMode] = useState<'voice' | 'studio'>(initial.mode || (q.get('mode') === 'studio' ? 'studio' : 'voice'));
  const [page, setPage] = useState<Page>(initial.page || (PAGES.find(p => p[0] === q.get('page'))?.[0]) || 'watch');
  const [costOpen, setCostOpen] = useState(false);
  const kept = useRef<Heard | null>(null); // a language the officer asked to keep
  const onHeard = (text: string) => { const f = followSpeech(text, kept.current); kept.current = f.kept; if (f.ui) setLang(f.ui); return f.ui; };
  const [watch, setWatch] = useState<WatchState | null>(null);
  const [need, setNeed] = useState<number | null>(null);

  const refresh = useCallback(() => {
    engine.watch().then(setWatch).catch(() => undefined);
    engine.desk().then(d => setNeed(d.needDecision)).catch(() => undefined);
  }, [engine]);
  useEffect(() => { refresh(); const i = setInterval(refresh, 5000); return () => clearInterval(i); }, [refresh]);
  const runNow = () => { engine.runWatch().then(setWatch).catch(() => undefined); };

  useEffect(() => {
    document.documentElement.lang = lang; document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
    document.title = lang === 'ar' ? 'فاحص' : 'Fahes';
  }, [lang]);
  useEffect(() => { document.body.classList.toggle('studio-on', mode === 'studio'); }, [mode]);

  const tx = (ar: string, en: string) => (lang === 'ar' ? ar : en);
  return (
    <EngineContext.Provider value={engine}>
      <LangContext.Provider value={lang}>
        <div className="bgglow" />
        <header className="top">
          <div className="brand"><span className="mark" /><span className="bt"><b>{tx('فاحص', 'Fahes')}</b><small>{tx('الرصد الاستباقي للروابط الوهمية', 'Proactive monitoring of fake links')}</small></span></div>
          <div className="modes">
            {(['voice', 'studio'] as const).map(m => <button key={m} type="button" className={mode === m ? 'on' : ''} onClick={() => setMode(m)}><Icon k={m} /><span>{m === 'voice' ? tx('الصوت', 'Voice') : tx('الاستوديو', 'Studio')}</span></button>)}
          </div>
          <div className="tools">
            <button className="ghost" type="button" onClick={() => setCostOpen(o => !o)}>{tx('التكلفة', 'Cost')}</button>
            <button className="ghost" type="button" onClick={() => { const l = lang === 'ar' ? 'en' : 'ar'; kept.current = l; setLang(l); }}>{lang === 'ar' ? 'English' : 'العربية'}</button>
          </div>
        </header>
        <VoiceMode toolPort={toolPort} makeVoice={makeVoice} onHeard={onHeard} watch={watch} onRunNow={runNow} onOpenStudio={p => { setPage(p as Page); setMode('studio'); }} />
        {mode === 'studio' && <Studio page={page} setPage={setPage} watch={watch} onRunNow={runNow} needDecision={need} />}
        {costOpen && <><CostSheet onClose={() => setCostOpen(false)} /><div className="scrim" onClick={() => setCostOpen(false)} /></>}
      </LangContext.Provider>
    </EngineContext.Provider>
  );
}
