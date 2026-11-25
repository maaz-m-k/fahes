/* Real sped-up footage instead of still pictures: real video players in device frames, one play/pause and scrub bar. */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import type { EngineClient } from '../api/client';
import { createFakeClient } from '../api/fake';
import type { Footage, WatchState } from '../api/types';

const foot = (src: string, w: number, h: number): Footage => ({ src, speed: 3, width: w, height: h, marker: { kind: 'real', note: 'real browser, sped up' },
  moments: [{ t: 0, ar: 'فتحت صفحة البحث.', en: 'Opened the search page.' }, { t: 9000, ar: 'أكتب السؤال.', en: 'Typing the question.' }] });

function withFootage(): EngineClient {
  const c = createFakeClient();
  return { ...c, async watch(): Promise<WatchState> {
    const w = await c.watch(); const r = w.lastRound!;
    r.footage = { computer: foot('/demo-footage/q1-computer.mp4', 2560, 1600), phone: foot('/demo-footage/q1-phone.mp4', 1170, 1992) };
    r.clips = [{ label: { ar: 'مقطع جوجل حقيقي', en: 'A real Google clip' }, footage: { computer: foot('/demo-footage/google-computer.mp4', 2560, 1600) } }];
    return w;
  } };
}

beforeAll(() => {
  Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: () => Promise.resolve() });
  Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: () => undefined });
});

const type = async (text: string) => { const u = userEvent.setup(); await u.type(screen.getByRole('textbox', { name: /type a question/i }), text + '{Enter}'); };
const waitKind = (k: string) => waitFor(() => expect(screen.getByTestId('card-body').dataset.kind).toBe(k), { timeout: 3000 });

it('the demo round carries the real overview footage on the Fahes search page', async () => {
  const w = await createFakeClient().watch();
  expect(w.lastRound!.footage!.phone!.src).toMatch(/overview-phone\.mp4$/);
  expect(w.lastRound!.footage!.computer!.marker).toEqual({ kind: 'real', note: 'real browser · recorded real results · Fahes search page' });
  expect(w.lastRound!.footage!.phone!.moments.map(m => m.en)).toContain('Typing the question the way a resident does.');
});

it('the run plays real footage in a computer window and a phone frame, with one play/pause and scrub bar and the speed', async () => {
  render(<App engine={withFootage()} initial={{ lang: 'en', markers: true }} />);
  await type('show me the run');
  await waitKind('replay');
  const card = screen.getByTestId('card-body');
  const videos = card.querySelectorAll('video');
  expect([...videos].map(v => v.getAttribute('src'))).toEqual(['/demo-footage/q1-computer.mp4', '/demo-footage/q1-phone.mp4', '/demo-footage/google-computer.mp4']);
  expect(within(card).getByTestId('extra-clip')).toHaveTextContent('A real Google clip'); // the slot for an extra clip
  expect(card.querySelector('.rp-win video')).toBeTruthy();
  expect(card.querySelector('.rp-phone video')).toBeTruthy();
  expect(card.querySelector('.rp-layer')).toBeNull(); // no stills, no cross-fades
  expect(within(card).getAllByRole('slider', { name: 'timeline' })).toHaveLength(2); // the round's, and the extra clip's
  expect(within(card).getAllByRole('button', { name: 'pause' }).length).toBeGreaterThan(0);
  expect(card.textContent).toMatch(/3×/);
  expect(within(card).getAllByText('REAL · real browser, sped up', { exact: false }).length).toBeGreaterThan(0);
  expect(screen.getByTestId('fcap-phone')).toHaveTextContent('Opened the search page.');
  const phone = card.querySelector('.rp-phone video') as HTMLVideoElement;
  Object.defineProperty(phone, 'duration', { configurable: true, value: 20 });
  fireEvent.loadedMetadata(phone);
  fireEvent.change(within(card).getAllByRole('slider')[0], { target: { value: '4' } });
  expect(screen.getByTestId('fcap-phone')).toHaveTextContent('Typing the question.'); // 4 s at 3× = 12 s real
});

it('"show it on the phone" fills the card with the phone footage only', async () => {
  render(<App engine={withFootage()} initial={{ lang: 'en', markers: true }} />);
  await type('show it on the phone');
  await waitKind('replay');
  const card = screen.getByTestId('card-body');
  expect(card.querySelectorAll('.rp-phone video').length).toBeGreaterThan(0);
  expect(card.querySelector('.rp-win')).toBeNull();
  expect(card.querySelector('.rp.fill .rp-phone video')).toBeTruthy();
});

it('a case shows its two-view capture as real footage, labelled DEMO DATA because the page is synthetic', async () => {
  const u = userEvent.setup();
  render(<App engine={createFakeClient()} initial={{ lang: 'en', markers: true }} />);
  await type('open the first one');
  await waitKind('case');
  await u.click(screen.getByRole('button', { name: 'Watch the capture as video' }));
  const f = screen.getByTestId('footage');
  expect([...f.querySelectorAll('video')].map(v => v.getAttribute('src'))).toEqual(['/demo-footage/lookalike-server.mp4', '/demo-footage/lookalike-phone.mp4']);
  expect(f.textContent).toMatch(/DEMO DATA · synthetic page, real browser recording/);
});
