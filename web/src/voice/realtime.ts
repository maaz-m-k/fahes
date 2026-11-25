/* Live voice: OpenAI gpt-realtime-2.1 over WebRTC, ported from the approved prototype (public/rt.js).
   The engine mints a short-lived client secret (EngineClient.voiceSession); the real key never reaches the browser.
   The model's tool calls go to onTool (the same tool layer as typing) and only tool facts go back to the model.
   Every failure is reported in plain words through onProblem; nothing silently falls back. */
import type { EngineClient } from '../api/client';
import type { Bi, Lang } from '../api/types';
import type { Levels, OrbState } from './Orb';

export type VoiceProblem = { step: string; text: Bi; detail?: string; quiet?: boolean };
/* what the desk needs from a voice session (the real one below, or a fake in tests) */
export interface VoiceLike { on: boolean; connecting: boolean; model: string; start(opts?: { quiet?: boolean }): Promise<boolean>; stop(): void; sendText(text: string): void; sendNote(text: string): void }
export type VoiceStatus = 'off' | 'connecting' | 'on';
export type RtHooks = {
  engine: EngineClient;
  lang: () => Lang;
  levels: { current: Levels };
  onStatus: (s: VoiceStatus, model?: string) => void;
  onOrb: (s: OrbState) => void;
  onHeard: (text: string) => void;
  onProblem: (p: VoiceProblem | null) => void;
  onTool: (name: string, args: Record<string, unknown>) => Promise<Record<string, unknown>>;
  testAudio?: string | null; // TEST ONLY: a recorded question instead of the microphone
};

const bi = (ar: string, en: string): Bi => ({ ar, en });
const IDLE_S = 120, MAX_S = 1800; // ends after about 2 minutes of silence, 30-minute safety cap

export class RealtimeVoice implements VoiceLike {
  on = false; connecting = false; model = '';
  private pc: RTCPeerConnection | null = null; private dc: RTCDataChannel | null = null; private mic: MediaStream | null = null;
  private audio: HTMLAudioElement | null = null; private ac: AudioContext | null = null; private timer = 0;
  private startedAt = 0; private lastActivity = 0; private maxUser = 0; private needCreate = false; private outstanding = 0;
  private quiet = false; private pending: string[] = []; private sessionId?: number; private maxS = MAX_S;
  constructor(private h: RtHooks) {}

  private problem(step: string, ar: string, en: string, detail?: string): false { this.h.onProblem({ step, text: bi(ar, en), detail, quiet: this.quiet }); return false; }
  private ctx() { this.ac = this.ac || new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)(); if (this.ac.state === 'suspended') this.ac.resume(); return this.ac; }

  /* resolves true once the session is on its way (typed text sent meanwhile is queued), false on any failure */
  async start(opts: { quiet?: boolean } = {}): Promise<boolean> {
    if (this.on || this.connecting) return true;
    this.quiet = !!opts.quiet; this.pending = [];
    this.h.onProblem(null);
    if (!window.RTCPeerConnection || !navigator.mediaDevices?.getUserMedia) return this.problem('browser', 'هذا المتصفح لا يدعم الصوت الفوري. افتح الصفحة في Google Chrome.', 'This browser cannot do live voice. Open the page in Google Chrome.', navigator.userAgent);
    if (!window.isSecureContext) return this.problem('insecure', 'الميكروفون يعمل فقط على localhost أو https.', 'The microphone only works on localhost or https.', location.origin);
    this.connecting = true; this.h.onStatus('connecting');
    const test = this.h.testAudio;
    let perm: string | undefined;
    try { perm = (await navigator.permissions.query({ name: 'microphone' as PermissionName })).state; } catch { /* not supported */ }
    if (perm === 'denied' && !test) { this.connecting = false; this.h.onStatus('off'); return this.problem('mic-denied', 'إذن الميكروفون مرفوض لهذه الصفحة. اضغط رمز القفل بجانب العنوان، واختر «الميكروفون: سماح»، ثم أعد تحميل الصفحة.', 'Microphone permission is blocked for this page. Click the lock icon next to the address, set Microphone to Allow, and reload the page.', 'permissions.query: denied'); }
    const waitT = setTimeout(() => { if (!this.mic && this.connecting) this.problem('mic-wait', 'المتصفح ينتظر إذنك: انظر أعلى النافذة بجانب العنوان، واضغط «سماح» للميكروفون.', 'The browser is waiting for your permission: look at the top of the window, next to the address, and press Allow for the microphone.', 'permission ' + (perm || '?')); }, 4000);
    // 1. the microphone first, while the click is still fresh
    try {
      if (test) { const a = this.ctx(), el = new Audio(test); el.crossOrigin = 'anonymous'; const dst = a.createMediaStreamDestination(); a.createMediaElementSource(el).connect(dst); this.mic = dst.stream; setTimeout(() => el.play(), 1500); }
      else this.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (e) {
      clearTimeout(waitT); this.connecting = false; this.h.onStatus('off');
      const err = e as DOMException;
      if (err.name === 'NotAllowedError' || err.name === 'SecurityError') return this.problem('mic-denied', 'إذن الميكروفون مرفوض. اضغط رمز القفل بجانب العنوان، واختر «الميكروفون: سماح»، ثم حاول مرة أخرى. وفي macOS تأكد أن Chrome مسموح له بالميكروفون (إعدادات النظام › الخصوصية › الميكروفون).', 'Microphone permission is blocked. Click the lock icon next to the address, set Microphone to Allow, then try again. On macOS also check System Settings › Privacy › Microphone allows Chrome.', err.name + ': ' + err.message);
      if (err.name === 'NotFoundError' || err.name === 'OverconstrainedError') return this.problem('no-mic', 'لا يوجد ميكروفون متصل بهذا الجهاز.', 'No microphone was found on this computer.', err.name);
      if (err.name === 'NotReadableError') return this.problem('mic-busy', 'الميكروفون مشغول ببرنامج آخر (مكالمة أو تسجيل). أغلقه ثم حاول مرة أخرى.', 'The microphone is busy in another app (a call or a recording). Close it and try again.', err.name);
      return this.problem('mic', 'تعذّر فتح الميكروفون.', 'The microphone could not be opened.', err.name + ': ' + err.message);
    }
    clearTimeout(waitT); this.h.onProblem(null);
    this.meter(this.mic, 'user');
    // 2. a short-lived voice key from the engine
    let s;
    try { s = await this.h.engine.voiceSession(); }
    catch (e) {
      this.stop(); const er = e as Error & { ar?: string; status?: number };
      if (er.status === 429) return this.problem('limit', er.ar || er.message, er.message); // a plain message from the server's hard limits
      return this.problem('mint', 'لم نستطع فتح جلسة صوتية (مفتاح الصوت أو الشبكة). اكتب بدلاً من ذلك.', 'We could not open a voice session (the voice key or the network). Type instead.', er.message);
    }
    this.model = s.model; this.sessionId = s.sessionId; this.maxS = s.maxSeconds || MAX_S;
    // 3. WebRTC to OpenAI
    try {
      const pc = new RTCPeerConnection(); this.pc = pc;
      const audio = document.createElement('audio'); audio.autoplay = true; audio.setAttribute('playsinline', ''); document.body.appendChild(audio); this.audio = audio;
      pc.ontrack = e => { audio.srcObject = e.streams[0]; audio.play().catch(err => this.problem('speaker', 'المتصفح منع تشغيل صوت فاحص. اضغط «حاول مرة أخرى».', "The browser blocked Fahes's voice from playing. Press Try again.", err.name)); this.meter(e.streams[0], 'self'); };
      pc.onconnectionstatechange = () => { if (pc.connectionState === 'failed') { this.stop(); this.problem('webrtc', 'انقطع اتصال الصوت (شبكة أو جدار حماية يمنع WebRTC).', 'The live audio connection failed (the network or a firewall may block WebRTC).', 'connectionState failed'); } };
      pc.addTrack(this.mic!.getTracks()[0], this.mic!);
      const dc = pc.createDataChannel('oai-events'); this.dc = dc;
      dc.onmessage = e => { try { this.onEvent(JSON.parse(e.data)); } catch { /* ignore */ } };
      dc.onopen = () => {
        this.on = true; this.connecting = false; this.startedAt = this.lastActivity = Date.now(); this.maxUser = 0;
        this.h.levels.current.on = true; this.h.onStatus('on', this.model); this.h.onOrb('listen');
        const q = this.pending; this.pending = []; q.forEach(t => this.sendText(t));
        setTimeout(() => { if (this.on && !test && this.maxUser < 0.03) this.problem('silent-mic', 'الجلسة مفتوحة لكن لا يصل صوت من الميكروفون. تأكد من اختيار الميكروفون الصحيح.', 'The session is open but no sound reaches us from the microphone. Check the right input device is selected.', 'max level ' + this.maxUser.toFixed(3)); }, 8000);
      };
      await pc.setLocalDescription(await pc.createOffer());
      const r = await fetch('https://api.openai.com/v1/realtime/calls', { method: 'POST', body: pc.localDescription!.sdp, headers: { Authorization: 'Bearer ' + s.value, 'Content-Type': 'application/sdp' } });
      if (!r.ok) throw new Error('OpenAI answered ' + r.status);
      await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() });
      clearInterval(this.timer);
      this.timer = window.setInterval(() => { const now = Date.now(); if (this.on && ((now - this.startedAt) / 1000 > this.maxS || (now - this.lastActivity) / 1000 > IDLE_S)) this.stop(); }, 1000);
    } catch (e) {
      this.stop(); return this.problem('webrtc', 'تعذّر وصل الصوت المباشر. اكتب بدلاً من ذلك.', 'Could not connect the live audio. Type instead.', (e as Error).message);
    }
    return true;
  }

  stop() {
    const secs = this.startedAt ? (Date.now() - this.startedAt) / 1000 : 0;
    if (this.startedAt || this.sessionId) this.h.engine.voiceUsage({ model: this.model, seconds: secs, sessionId: this.sessionId }).catch(() => undefined);
    this.sessionId = undefined;
    this.startedAt = 0; this.on = false; this.connecting = false; clearInterval(this.timer);
    try { this.dc?.close(); } catch { /* closed */ } try { this.pc?.close(); } catch { /* closed */ }
    this.mic?.getTracks().forEach(t => t.stop()); this.mic = null; this.pc = null; this.dc = null;
    try { this.audio?.remove(); } catch { /* gone */ } this.audio = null;
    this.h.levels.current.on = false; this.h.levels.current.user = 0; this.h.levels.current.self = 0;
    this.h.onOrb('idle'); this.h.onStatus('off');
  }

  /* typing while a session is live goes into the same conversation */
  sendText(text: string) {
    if (this.dc?.readyState !== 'open') { if (this.connecting) this.pending.push(text); return; }
    this.send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } }); this.send({ type: 'response.create' }); this.lastActivity = Date.now();
  }
  /* the officer tapped something on screen: tell the model the facts so it says one short line */
  sendNote(text: string) { this.sendText('(on screen) ' + text); }

  private send(ev: unknown) { if (this.dc?.readyState === 'open') this.dc.send(JSON.stringify(ev)); }

  private meter(stream: MediaStream, who: 'user' | 'self') {
    try {
      const a = this.ctx(), an = a.createAnalyser(); an.fftSize = 512; a.createMediaStreamSource(stream).connect(an);
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        if (!this.mic) return; an.getByteTimeDomainData(buf); let s = 0; for (const v of buf) s += (v - 128) ** 2;
        const lv = Math.min(1, Math.sqrt(s / buf.length) / (who === 'self' ? 10 : 22)); this.h.levels.current[who] = lv;
        if (who === 'user') this.maxUser = Math.max(this.maxUser, lv);
        requestAnimationFrame(tick);
      };
      tick();
    } catch { /* no analyser */ }
  }

  /* events from the model (exported for tests through handleEvent) */
  handleEvent(ev: { type: string; [k: string]: unknown }) { this.onEvent(ev); }
  private onEvent(ev: { type: string; [k: string]: any }) { // eslint-disable-line @typescript-eslint/no-explicit-any
    this.lastActivity = Date.now();
    switch (ev.type) {
      case 'input_audio_buffer.speech_started': this.h.onOrb('listen'); break; // sound alone never changes the card
      case 'input_audio_buffer.speech_stopped': this.h.onOrb('think'); break;
      case 'conversation.item.input_audio_transcription.completed': this.h.onHeard(String(ev.transcript || '')); break;
      case 'output_audio_buffer.started': this.h.onOrb('speak'); break;
      case 'output_audio_buffer.stopped': case 'output_audio_buffer.cleared': this.h.onOrb(this.on ? 'listen' : 'idle'); break;
      case 'response.function_call_arguments.done': void this.runTool(String(ev.name), String(ev.arguments || '{}'), String(ev.call_id)); break;
      case 'response.done': {
        const u = ev.response?.usage; if (u) this.h.engine.voiceUsage({ model: this.model, usage: u }).catch(() => undefined);
        if (ev.response?.output?.some((o: { type: string }) => o.type === 'function_call')) { this.needCreate = true; this.maybeCreate(); }
        break;
      }
    }
  }
  private async runTool(name: string, argsJson: string, callId: string) {
    let a: Record<string, unknown> = {}; try { a = JSON.parse(argsJson || '{}'); } catch { /* bad args */ }
    this.outstanding++;
    let out: Record<string, unknown>;
    try { out = await this.h.onTool(name, a); } catch { out = { error: 'tool failed' }; }
    this.send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output: JSON.stringify(out) } });
    this.outstanding--; this.maybeCreate();
  }
  private maybeCreate() { if (this.needCreate && !this.outstanding) { this.needCreate = false; this.send({ type: 'response.create' }); } }
}
