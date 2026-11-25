/* The team lead's review 4 fixes, at the same seams: the app with the fake engine, typed path, simulated voice. */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App, type AppInitial } from '../App';
import { createFakeClient } from '../api/fake';
import runJson from '../api/fake/run.json';
import { detectLang, followSpeech, langCommand } from '../voice/lang';
import type { RtHooks, VoiceLike } from '../voice/realtime';
import { VOICE_INSTRUCTIONS, VOICE_TOOLS } from '../voice/toolSpec';
import { SUMMARY_CHIPS } from '../voice/tools';

const waitKind = (k: string) => waitFor(() => expect(screen.getByTestId('card-body').dataset.kind).toBe(k), { timeout: 3000 });
const box = () => screen.getByRole('textbox', { name: /type a question|اكتب سؤالاً/i });

function fakeVoice(canStart = true) {
  const f = { hooks: null as RtHooks | null, sent: [] as string[], started: 0 };
  const make = (hooks: RtHooks): VoiceLike => {
    f.hooks = hooks;
    const v: VoiceLike = {
      on: false, connecting: false, model: 'fake-realtime',
      async start() { f.started++; if (!canStart) { hooks.onProblem({ step: 'browser', text: { ar: 'لا', en: 'no' }, quiet: true }); return false; } v.on = true; hooks.onStatus('on', 'fake-realtime'); return true; },
      stop() { v.on = false; hooks.onStatus('off'); },
      sendText(t) { f.sent.push(t); },
      sendNote(t) { f.sent.push('(on screen) ' + t); },
    };
    return v;
  };
  return { f, make };
}

function setup(initial: AppInitial = { lang: 'en' }, voice = fakeVoice(false)) {
  const user = userEvent.setup();
  const speak = vi.fn();
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: { speak, cancel: () => undefined, getVoices: () => [] } });
  (globalThis as unknown as { SpeechSynthesisUtterance: unknown }).SpeechSynthesisUtterance = class { lang = ''; voice = null; onend = null; onerror = null; constructor(public text: string) {} };
  render(<App engine={createFakeClient()} initial={{ ...initial }} makeVoice={voice.make} />);
  const say = async (text: string) => { await user.clear(box()); await user.type(box(), text + '{Enter}'); };
  return { user, say, speak, voice: voice.f };
}

describe('1. language follows the officer', () => {
  it('detects the language of a sentence, ignoring pasted links', () => {
    expect(detectLang('good morning, what do we have?')).toBe('en');
    expect(detectLang('صباح الخير')).toBe('ar');
    expect(detectLang('സുപ്രഭാതം, ഇന്ന് എന്താണ്?')).toBe('other');
    expect(detectLang('افحص adpolice-fines.top')).toBe('ar');
    expect(langCommand('speak in Arabic please')).toBe('ar');
    expect(langCommand('تكلم انجليزي')).toBe('en');
    expect(followSpeech('what now?', 'ar')).toEqual({ ui: 'ar', kept: 'ar' });
    expect(followSpeech('ഇന്ന് എന്താണ്', null).ui).toBe('en');
  });

  it('the realtime instructions say: reply in the last sentence language, switch and stay when told', () => {
    expect(VOICE_INSTRUCTIONS).toMatch(/language of the officer's LAST sentence/);
    expect(VOICE_INSTRUCTIONS).toMatch(/keep using it until told otherwise/);
  });

  it('the screen switches to English when the officer writes English, and stays Arabic after "speak in Arabic"', async () => {
    const { say } = setup({});
    expect(document.documentElement.dir).toBe('rtl');
    await say('good morning, what do we have today?');
    await waitKind('summary');
    expect(document.documentElement.dir).toBe('ltr');
    expect(screen.getByTestId('words')).toHaveTextContent('3 need your decision');
    await say('speak in Arabic');
    await waitFor(() => expect(document.documentElement.dir).toBe('rtl'));
    await say('open the first one');
    await waitKind('case');
    expect(document.documentElement.dir).toBe('rtl');
    expect(screen.getByTestId('words')).toHaveTextContent('هذا ما رآه المقيم');
  });
});

describe('2. the replay plays like a video, in device frames, from sharp captures', () => {
  it('the demo round was captured sharp (phone x3, computer x2, high quality)', () => {
    expect(runJson.capture.phone.deviceScaleFactor).toBe(3);
    expect(runJson.capture.computer.deviceScaleFactor).toBe(2);
    expect(runJson.capture.jpegQuality).toBeGreaterThanOrEqual(90);
  });

  it('"show it on the phone" fills the card with the phone footage', async () => {
    const { say } = setup();
    await say('show it on the phone');
    await waitKind('replay');
    const card = screen.getByTestId('card-body');
    expect(card.querySelector('.rp.fill .rp-phone video')).toBeTruthy();
    expect(card.querySelector('.rp-win')).toBeNull();
    expect(screen.getByRole('slider', { name: 'timeline' })).toBeInTheDocument();
  });

  it('both devices share one timeline in a phone frame and a computer window', async () => {
    const { say } = setup();
    await say('show me the run');
    await waitKind('replay');
    const card = screen.getByTestId('card-body');
    expect(card.querySelector('.rp-phone')).toBeTruthy();
    expect(card.querySelector('.rp-win .rp-bar')).toBeTruthy();
    expect(within(card).getAllByRole('slider')).toHaveLength(1);
  });
});

describe('3. suggestions after the summary', () => {
  it('shows three suggestions and says one of them', async () => {
    const { say, speak } = setup();
    await say('good morning');
    await waitKind('summary');
    const chips = within(screen.getByTestId('chips')).getAllByRole('button').map(b => b.textContent);
    expect(chips).toEqual(['Open the first case', 'Check a link', 'Replay the last run']);
    await waitFor(() => expect(speak).toHaveBeenCalled());
    expect((speak.mock.calls[0][0] as { text: string }).text).toMatch(/Shall I open the first case\?/);
  });

  it('every suggestion maps to a tool the realtime model has, so saying it does the same as tapping it', () => {
    const names = VOICE_TOOLS.map(t => t.name);
    for (const c of SUMMARY_CHIPS) expect(names).toContain(c.tool);
  });

  it('tapping "Check a link" and saying it open the same checker', async () => {
    const { say, user } = setup();
    await say('good morning');
    await waitKind('summary');
    await user.click(screen.getByRole('button', { name: 'Check a link' }));
    await waitKind('check');
    await say('close it');
    await waitFor(() => expect(screen.queryByTestId('card-body')).toBeNull(), { timeout: 3000 });
    await say('check a link');
    await waitKind('check');
  });
});

describe('4. checking links by voice, in the card', () => {
  it('"I want to check some links" opens the checker; several links are checked one after another in the same card', async () => {
    const { say, user } = setup();
    await say('I want to check some links');
    await waitKind('check');
    const glass = screen.getByTestId('glass');
    const panel = screen.getByTestId('check-panel');
    expect(within(panel).getByRole('button', { name: 'Paste' })).toBeInTheDocument();
    await user.type(within(panel).getByRole('textbox', { name: 'address' }), 'adpolice-fines.top{Enter}');
    await waitFor(() => expect(screen.getByTestId('verdict-host')).toHaveTextContent('adpolice-fines.top'));
    await user.click(screen.getByRole('button', { name: 'tamm.abudhabi' }));
    await waitFor(() => expect(screen.getByTestId('verdict-host')).toHaveTextContent('tamm.abudhabi'));
    expect(screen.getByTestId('check-results')).toHaveTextContent('adpolice-fines.top');
    expect(screen.getByTestId('glass')).toBe(glass);
    expect(screen.getByTestId('card-body').dataset.kind).toBe('check');
  });
});

describe('5. typing joins the live voice conversation', () => {
  it('typed text starts the session and goes to the realtime model; its tool call fills the card; no browser voice', async () => {
    const v = fakeVoice(true);
    const { say, speak } = setup({ lang: 'en' }, v);
    await say('adpolice-fines.top');
    await waitFor(() => expect(v.f.sent).toEqual(['adpolice-fines.top']));
    expect(v.f.started).toBe(1);
    expect(screen.queryByTestId('card-body')).toBeNull(); // nothing answered locally: the model decides
    await act(async () => { await v.f.hooks!.onTool('check_address', { domain: 'adpolice-fines.top' }); });
    await waitKind('check');
        await say('and abudhabipolice.ae');
    await waitFor(() => expect(v.f.sent).toHaveLength(2));
    expect(v.f.started).toBe(1);
    expect(speak).not.toHaveBeenCalled();
  });

  it('a tapped suggestion is told to the live session', async () => {
    const v = fakeVoice(true);
    const { say, user } = setup({ lang: 'en' }, v);
    await say('good morning');
    await act(async () => { await v.f.hooks!.onTool('summary', {}); });
    await waitKind('summary');
    await user.click(screen.getByRole('button', { name: 'Open the first case' }));
    await waitKind('case');
    await waitFor(() => expect(v.f.sent.at(-1)).toMatch(/^\(on screen\) Open the first case\. Facts:/));
  });

  it('when the live session cannot start, the fallback answers and speaks', async () => {
    const { say, speak } = setup({ lang: 'en' }, fakeVoice(false));
    await say('what do we have today');
    await waitKind('summary');
    expect(screen.getByTestId('fallback-note')).toHaveTextContent('Live voice is not available');
    await waitFor(() => expect(speak).toHaveBeenCalled());
  });
});

describe('the name and the voice: Fahes / فاحص, voice cedar', () => {
  it('the screen says فاحص in Arabic and Fahes in English, never the old name', async () => {
    const user = userEvent.setup();
    render(<App engine={createFakeClient()}  makeVoice={fakeVoice(false).make} />);
    expect(document.title).toBe('فاحص');
    expect(screen.getByRole('button', { name: /تكلّم مع فاحص/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'English' }));
    expect(document.title).toBe('Fahes');
    expect(screen.getByRole('button', { name: /Talk to Fahes/ })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Istibaq|(?<!ال)استباق(?!ي)/);
  });
  it('the voice model is Fahes, says its name only when greeting or asked, with the cedar voice', async () => {
    const { VOICE_NAME } = await import('../voice/toolSpec');
    expect(VOICE_NAME).toBe('cedar');
    expect(VOICE_INSTRUCTIONS).toMatch(/You are Fahes \(فاحص/);
    expect(VOICE_INSTRUCTIONS).toMatch(/Say your name only in your first greeting or when the officer asks who you are; never repeat it after a task\./);
    expect(VOICE_INSTRUCTIONS).not.toMatch(/masculine/);
    expect(VOICE_INSTRUCTIONS).not.toMatch(/Istibaq|استباق\b/);
  });
});
