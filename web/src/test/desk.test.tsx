/* The main seam: the whole app with the engine client replaced by the fake, driven through the typed path and through
   simulated voice tool calls. We check what appears on screen and which engine calls are made. */
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App, type AppInitial } from '../App';
import { createFakeClient } from '../api/fake';
import type { EngineClient } from '../api/client';

function setup(initial: AppInitial = { lang: 'en' }) {
  const engine = createFakeClient();
  const calls: string[] = [];
  const spied = new Proxy(engine, {
    get(t, k) { const v = Reflect.get(t, k); return typeof v === 'function' ? (...a: unknown[]) => { calls.push(String(k) + (a.length && typeof a[0] === 'string' ? ':' + a[0] : '')); return v.apply(t, a); } : v; },
  }) as EngineClient;
  let voiceTool: ((n: string, a: Record<string, unknown>) => Promise<unknown>) | null = null;
  const user = userEvent.setup();
  render(<App engine={spied} initial={{ markers: true, ...initial }} toolPort={fn => { voiceTool = fn; }} />);
  const say = async (text: string) => { const box = screen.getByRole('textbox', { name: /type a question|اكتب سؤالاً/i }); await user.clear(box); await user.type(box, text + '{Enter}'); };
  const voice = async (name: string, args: Record<string, unknown> = {}) => { await act(async () => { await voiceTool!(name, args); }); };
  const phase = () => screen.getByTestId('voice').dataset.phase;
  const kind = () => screen.queryByTestId('card-body')?.dataset.kind;
  return { user, say, voice, phase, kind, calls };
}

const waitKind = (k: string) => waitFor(() => expect(screen.getByTestId('card-body').dataset.kind).toBe(k), { timeout: 3000 });

describe('voice mode, typed path', () => {
  it('starts calm: the orb big, no card, a greeting', () => {
    const { phase } = setup();
    expect(phase()).toBe('idle');
    expect(screen.queryByTestId('card-body')).toBeNull();
    expect(screen.getByTestId('line')).toHaveTextContent('Good morning.');
  });

  it('summary → open case → seal → tamper → approve → close', async () => {
    const { say, user, phase, calls } = setup();
    await say('good morning, what do we have today?');
    await waitKind('summary');
    expect(phase()).toBe('answering');
    expect(screen.getByTestId('words')).toHaveTextContent('3 need your decision');
    expect(within(screen.getByTestId('cases-list')).getAllByRole('button')).toHaveLength(3);
    expect(calls).toContain('desk');

    await say('open the first one');
    await waitKind('case');
    expect(screen.getByTestId('trick')).toHaveTextContent('fines-pay.test');
    expect(screen.getByTestId('saw')).toHaveTextContent(/Saw through/);
    expect(calls).toContain('caseDetail:c1');

    await say('seal it');
    await waitKind('record');
    expect(calls).toContain('seal:c1');
    expect(screen.getByTestId('fingerprint').textContent).toMatch(/^[0-9a-f]{64}$/);
    await waitFor(() => expect(screen.getByTestId('verify')).toHaveTextContent('Verified'));

    await user.click(screen.getByRole('button', { name: 'Edit one letter' }));
    await waitFor(() => expect(screen.getByTestId('verify')).toHaveTextContent('Verification failed'));
    expect(screen.getByRole('button', { name: /Officer approves/ })).toBeDisabled();

    await say('approve');
    await waitKind('done');
    expect(screen.getByTestId('words')).toHaveTextContent('Not approved');
    expect(screen.getByTestId('done')).toHaveTextContent('Verification failed');

    await user.click(screen.getByRole('button', { name: 'Open the draft' }));
    await waitKind('record');
    await waitFor(() => expect(screen.getByTestId('verify')).toHaveTextContent('Verified'));
    await say('approve');
    await waitKind('done');
    expect(screen.getByTestId('words')).toHaveTextContent('Done');
    expect(screen.getByTestId('done')).toHaveTextContent('Takedown request ready. Nothing sent.');

    await say('close it');
    await waitFor(() => expect(phase()).toBe('idle'), { timeout: 3000 });
    expect(screen.queryByTestId('card-body')).toBeNull();
  });

  it('a second request that needs UI changes the content inside the same card', async () => {
    const { say, phase } = setup();
    await say('what do we have today');
    await waitKind('summary');
    const glass = screen.getByTestId('glass');
    const phases: string[] = [];
    const obs = new MutationObserver(() => phases.push(phase()!)); obs.observe(screen.getByTestId('voice'), { attributes: true });
    await say('how many new sites right now?');
    await waitKind('scale');
    obs.disconnect();
    expect(screen.getByTestId('glass')).toBe(glass);
    expect(phases).not.toContain('idle');
    expect(screen.getByTestId('live-number').textContent).toMatch(/\d{1,3}(,\d{3})+/);
    expect(screen.getByTestId('spark')).toBeInTheDocument();
  });

  it('an answer with no screen leaves the orb big', async () => {
    const { say, phase } = setup();
    await say('thanks');
    await waitFor(() => expect(screen.getByTestId('line')).toHaveTextContent('At your service.'));
    expect(phase()).toBe('idle');
    expect(screen.queryByTestId('card-body')).toBeNull();
  });

  it('the × closes the card', async () => {
    const { say, user, phase } = setup();
    await say('show me the run');
    await waitKind('replay');
    await user.click(screen.getByRole('button', { name: 'close' }));
    await waitFor(() => expect(phase()).toBe('idle'), { timeout: 3000 });
  });

  it('an unknown request keeps the card as it is', async () => {
    const { say } = setup();
    await say('what do we have today');
    await waitKind('summary');
    await say('blue elephants');
    await new Promise(r => setTimeout(r, 400));
    expect(screen.getByTestId('card-body').dataset.kind).toBe('summary');
  });

  it('chips run the next step', async () => {
    const { user } = setup();
    await userEvent.type(screen.getByRole('textbox', { name: /type a question/i }), 'what do we have today{Enter}');
    await waitKind('summary');
    await user.click(screen.getByRole('button', { name: 'Open the first case' }));
    await waitKind('case');
  });

  it('checks an address: a look-alike turns red with at least two reasons', async () => {
    const { say } = setup();
    await say('adpolice-fines.top');
    await waitKind('check');
    expect(screen.getByTestId('words')).toHaveTextContent('Suspected fake, with reasons');
    expect(screen.getByTestId('card-body').querySelectorAll('ol.reasons li').length).toBeGreaterThanOrEqual(2);
  });

  it('the phone view shows only the phone footage', async () => {
    const { say } = setup();
    await say('show it on the phone');
    await waitKind('replay');
    expect(screen.getByTestId('replay').dataset.view).toBe('phone');
    expect(screen.getByTestId('replay').querySelectorAll('.rp-dev')).toHaveLength(1);
    expect(screen.getByTestId('replay').querySelectorAll('video')).toHaveLength(1);
  });

  it('marks the grey case licensed and the list shrinks', async () => {
    const { say } = setup();
    await say('open the third');
    await waitKind('case');
    await say('it is licensed');
    await waitKind('done');
    await say('what do we have today');
    await waitKind('summary');
    expect(screen.getByTestId('words')).toHaveTextContent('2 need your decision');
  });
});

describe('voice mode, simulated tool calls from the voice model', () => {
  it('drives the same card: summary, show_case, seal, approve by voice, close_card', async () => {
    const { voice, phase, calls } = setup();
    await voice('summary');
    await waitKind('summary');
    await voice('show_case', { n: 2 });
    await waitKind('case');
    expect(screen.getByTestId('trick')).toHaveTextContent('freehost.test');
    await voice('seal');
    await waitKind('record');
    await voice('approve');
    await waitKind('done');
    expect(screen.getByTestId('done')).toHaveTextContent('Approved by the officer, by voice');
    expect(calls.some(c => c.startsWith('approve:'))).toBe(true);
    await voice('close_card');
    await waitFor(() => expect(phase()).toBe('idle'), { timeout: 3000 });
  });

  it('run_now starts a round and the schedule pill shows it running', async () => {
    const { voice, calls } = setup();
    await voice('run_now');
    await waitKind('done');
    expect(calls).toContain('runWatch');
    expect(screen.getByTestId('words')).toHaveTextContent('Round started');
  });
});

describe('the desk around the voice', () => {
  it('shows the watch schedule with run now', async () => {
    setup();
    await waitFor(() => expect(screen.getAllByTestId('schedule')[0]).toHaveTextContent(/Watch every 6 h · next round in \d+ h \d+ min/));
  });

  it('a voice session that cannot start says so in plain words and typing still works', async () => {
    const { user, say } = setup();
    await user.click(screen.getByRole('button', { name: /Talk to Fahes/ }));
    expect(await screen.findByTestId('voice-problem')).toHaveTextContent('This browser cannot do live voice');
    await user.click(screen.getByRole('button', { name: 'Type instead' }));
    await say('what do we have today');
    await waitKind('summary');
  });

  it('one switch hides every marker', async () => {
    const { user } = setup();
    expect(document.body).toHaveClass('show-mk');
    await user.click(screen.getByRole('checkbox', { name: 'markers' }));
    expect(document.body).not.toHaveClass('show-mk');
  });

  it('Arabic first, right to left, with an English switch', async () => {
    const user = userEvent.setup();
    render(<App engine={createFakeClient()} initial={{ markers: true }} />);
    expect(document.documentElement.dir).toBe('rtl');
    expect(screen.getByTestId('line')).toHaveTextContent('صباح الخير.');
    await user.type(screen.getByRole('textbox'), 'صباح الخير، شو عندنا اليوم؟{Enter}');
    await waitKind('summary');
    expect(screen.getByTestId('words')).toHaveTextContent('3 تحتاج قرارك');
    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(document.documentElement.dir).toBe('ltr');
    expect(screen.getByTestId('words')).toHaveTextContent('3 need your decision');
  });

  it('shows cost so far and projected in the real-vs-demo sheet', async () => {
    const { user } = setup();
    await user.click(screen.getByRole('button', { name: 'Real vs demo' }));
    expect(await screen.findByTestId('costs')).toHaveTextContent(/Projected a month/);
  });
});
