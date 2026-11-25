/* The studio, operated by hand, against the fake engine. */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from '../App';
import { createFakeClient } from '../api/fake';
import { RealtimeVoice } from '../voice/realtime';

const open = () => {
  const user = userEvent.setup();
  render(<App engine={createFakeClient()} initial={{ lang: 'en', mode: 'studio', markers: true }} />);
  return { user, page: (name: string) => user.click(within(document.querySelector('nav.side') as HTMLElement).getByRole('button', { name: new RegExp(name) })) };
};

describe('studio', () => {
  it('has the nine pages in the side menu', () => {
    open();
    const names = within(document.querySelector('nav.side') as HTMLElement).getAllByRole('button').map(b => b.textContent?.replace(/\d+$/, ''));
    expect(names).toEqual(['Watch', 'Cases', 'Check an address', 'Register', 'Drill', 'Scale', 'Records', 'Agents', 'For judges']);
  });

  it('Watch: engines as logos, the last round with replays', async () => {
    const { user } = open();
    expect(await screen.findByRole('button', { name: /DuckDuckGo/ })).toBeInTheDocument();
    const replays = await screen.findAllByRole('button', { name: 'Watch how it worked' });
    expect(replays).toHaveLength(4);
    await user.click(replays[0]);
    expect(screen.getByTestId('replay').querySelectorAll('.rp-dev')).toHaveLength(2);
  });

  it('Cases: seal a case, then the record is in Records; tamper breaks verification', async () => {
    const { user, page } = open();
    await page('Cases');
    await user.click(await screen.findByRole('button', { name: 'Seal it as a draft record' }));
    expect(await screen.findByTestId('records-list')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('verify')).toHaveTextContent('Verified'));
    await user.type(screen.getByRole('textbox', { name: 'record address' }), 'x');
    await waitFor(() => expect(screen.getByTestId('verify')).toHaveTextContent('Verification failed'));
    await user.click(screen.getByRole('button', { name: 'Undo the edit' }));
    await waitFor(() => expect(screen.getByTestId('verify')).toHaveTextContent('Verified'));
    await user.click(screen.getByRole('button', { name: /Officer approves/ }));
    await waitFor(() => expect(within(screen.getByTestId('records-list')).getByText('approved')).toBeInTheDocument());
  });

  it('Cases: the takedown is prepared and nothing is sent', async () => {
    const { user, page } = open();
    await page('Cases');
    await user.click(await screen.findByRole('button', { name: 'Prepare the takedown' }));
    const td = await screen.findByTestId('takedown');
    await user.click(within(td).getAllByRole('button', { name: 'Prepare' })[0]);
    expect(await within(td).findByText('Ready ✓ (nothing sent)')).toBeInTheDocument();
  });

  it('Check an address: green for an official address the gov.ae rule would miss', async () => {
    const { user, page } = open();
    await page('Check an address');
    await user.type(screen.getByRole('textbox', { name: 'address' }), 'abudhabipolice.ae{Enter}');
    await waitFor(() => expect(screen.getByTestId('verdict-host')).toHaveTextContent('abudhabipolice.ae'));
    expect(document.querySelector('[data-verdict="green"]')).toBeTruthy();
  });

  it("Drill: the judges' own fake turns red with reasons", async () => {
    const { user, page } = open();
    await page('Drill');
    await user.click(await screen.findByRole('button', { name: "Judges' fakes" }));
    await user.type(screen.getByRole('textbox', { name: 'judge address' }), 'abudhabip0lice-pay.com{Enter}');
    await waitFor(() => expect(document.querySelector('[data-verdict="red"]')).toBeTruthy());
  });

  it('Register, Scale and Agents render from the engine', async () => {
    const { page } = open();
    await page('Register');
    expect(await screen.findByText('Abu Dhabi Police')).toBeInTheDocument();
    await page('Scale');
    expect(await screen.findByTestId('live-number')).toBeInTheDocument();
    await page('Agents');
    expect(await screen.findByTestId('agents')).toBeInTheDocument();
    expect(screen.getByTestId('handoff')).toBeInTheDocument();
  });
});

describe('realtime session events', () => {
  const hooks = () => {
    const h = { orb: [] as string[], tools: [] as [string, unknown][] };
    const rt = new RealtimeVoice({
      engine: createFakeClient(), lang: () => 'ar', levels: { current: { user: 0, self: 0, typing: 0, on: false } },
      onStatus: () => undefined, onOrb: s => h.orb.push(s), onHeard: () => undefined, onProblem: () => undefined,
      onTool: async (n, a) => { h.tools.push([n, a]); return { ok: true }; },
    });
    return { rt, h };
  };
  it('sound alone only moves the orb', () => {
    const { rt, h } = hooks();
    rt.handleEvent({ type: 'input_audio_buffer.speech_started' });
    rt.handleEvent({ type: 'input_audio_buffer.speech_stopped' });
    expect(h.orb).toEqual(['listen', 'think']);
    expect(h.tools).toEqual([]);
  });
  it("hands the model's tool call to the tool layer with its arguments", async () => {
    const { rt, h } = hooks();
    rt.handleEvent({ type: 'response.function_call_arguments.done', name: 'show_case', arguments: '{"n":1}', call_id: 'c1' });
    await waitFor(() => expect(h.tools).toEqual([['show_case', { n: 1 }]]));
  });
});
