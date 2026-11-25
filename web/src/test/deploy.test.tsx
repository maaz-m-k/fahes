/* Deploy-ready: the judges' page, and the desk against the real engine's responses (fetch replaced). */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { createFakeClient } from '../api/fake';
import { engineClient } from '../api/engine';
import { linksFrom, toCsv } from '../studio/Judges';

const verdict = (link: string, v: string) => ({ link, verdict: v, score: v === 'red' ? 0.99 : 0.1, model_version: 'm', reasons: [
  { code: 'brand_mismatch', ar: 'يقلّد «تم»', en: 'Imitates TAMM', evidence: { brand_ar: 'تم', brand_en: 'TAMM', official_domains: ['tamm.abudhabi'] } }] });

describe("judges' page", () => {
  it('reads links from pasted text or a CSV and writes a CSV', () => {
    expect(linksFrom('link,note\nadpolice-fines.top,x\n"https://www.tamm.abudhabi/",y\n\nnot a link')).toEqual(['adpolice-fines.top', 'https://www.tamm.abudhabi/']);
    const csv = toCsv([{ host: 'a.top', link: 'a.top', verdict: 'red', score: 0.9, family: null, officialAddresses: [], modelVersion: 'm', reasons: [{ code: 'x', ar: 'سبب', en: 'a "reason"' }] }]);
    expect(csv.split('\n')).toEqual(['link,verdict,score,reasons_en,reasons_ar', '"a.top","red","0.9","a ""reason""","سبب"']);
  });

  it('scores pasted links and lists each verdict with reasons', async () => {
    const user = userEvent.setup();
    render(<App engine={createFakeClient()} initial={{ lang: 'en', mode: 'studio', page: 'judges' }} />);
    await user.type(screen.getByRole('textbox', { name: 'links' }), 'adpolice-fines.top\ntamm.abudhabi');
    await user.click(screen.getByRole('button', { name: 'Score 2 links' }));
    await waitFor(() => expect(screen.getByTestId('judges-summary')).toHaveTextContent('1 red · 0 grey · 1 green'));
    expect(within(screen.getByTestId('judges-results')).getByText('adpolice-fines.top')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download CSV' })).toBeInTheDocument();
  });
});

describe('the desk against the real engine', () => {
  const routes: Record<string, unknown> = {
    'GET /api/cases?status=open&reveal=true': [
      { id: 7, link: 'https://tamm-abudhabi.fines-pay.test/ae/pay', source: 'brave/organic', verdict: 'red', score: 0.99, status: 'open', sealed: false, name_hidden: false },
      { id: 8, link: 'https://typing.example/', source: 'places/maps', verdict: 'grey', score: 0.5, status: 'open', sealed: false, name_hidden: false }],
    'GET /api/cases/7?reveal=true': { id: 7, link: 'https://tamm-abudhabi.fines-pay.test/ae/pay', source: 'brave/organic', verdict: 'red', score: 0.99, status: 'open', opened_at: '2026-11-25T01:00:00Z',
      verdict_full: verdict('https://tamm-abudhabi.fines-pay.test/ae/pay', 'red'), capture: { saw_through: ['hidden from server'] }, record: null, name_hidden: false },
    'POST /api/score/batch': { results: [verdict('a.top', 'red'), verdict('b.example', 'grey')], count: 2 },
    'POST /api/voice/session': { client_secret: 'ek_1', model: 'gpt-realtime-2.1', expires_at: 1, session_id: 4 },
  };
  const calls: string[] = [];
  beforeEach(() => {
    calls.length = 0;
    vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
      const key = `${init?.method || 'GET'} ${url}`; calls.push(key);
      const body = routes[key];
      return new Response(JSON.stringify(body ?? { detail: 'nope' }), { status: body ? 200 : 404 });
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('maps cases, the mirror, batch scoring and the voice key from the engine', async () => {
    const c = engineClient('');
    const desk = await c.desk();
    expect(desk.needDecision).toBe(2);
    expect(desk.cases.map(x => [x.id, x.verdict, x.n])).toEqual([['7', 'red', 1], ['8', 'grey', 2]]);
    const d = await c.caseDetail('7');
    expect(d.trick).toEqual({ decoy: 'tamm-abudhabi.', owner: 'fines-pay.test', rest: '/ae/pay' });
    expect(d.imitates?.address).toBe('tamm.abudhabi');
    expect(d.sawThrough.en).toBe('hidden from server');
    const rows = await c.scoreBatch(['a.top', 'b.example']);
    expect(rows.map(r => [r.link, r.verdict])).toEqual([['a.top', 'red'], ['b.example', 'grey']]);
    expect(await c.voiceSession()).toMatchObject({ value: 'ek_1', sessionId: 4 });
    expect(calls).toContain('POST /api/score/batch');
  });
});

describe('the replay before the first round has run on the server', () => {
  afterEach(() => vi.unstubAllGlobals());
  it('shows the recorded footage of an earlier round, with no label', async () => {
    vi.stubGlobal('fetch', async (url: string) => new Response(JSON.stringify(url.includes('schedule') ? { enabled: true, every_hours: 6 } : { status: 'none' })));
    const w = await engineClient('').watch();
    expect(w.lastRound!.footage!.computer!.src).toMatch(/overview-computer\.mp4$/);
    expect(JSON.stringify(w)).not.toMatch(/marker|demo footage/);
  });
});
