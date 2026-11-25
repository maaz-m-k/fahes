/* The one module that talks to the Fahes engine. Every engine call the screens make goes through EngineClient.
   - httpClient: the real engine (FastAPI, spec issue #9). Paths below are the screens' side of the contract.
   - createFakeClient (./fake): built from the prototype's data, used until the engine ships and in every test.
   Pick with VITE_ENGINE=http (and VITE_ENGINE_URL for another origin) or ?engine=http|fake. Default: fake. */
import type {
  AgentsState, ApproveResult, CaseDetail, Costs, DeskSummary, DrillInfo, Feeds, Lang, RecordFields, RegisterList,
  ScoreResult, Scorecard, SealedRecord, TakedownPackage, Understanding, VerifyResult, VoiceSession, WatchState,
} from './types';
import { createFakeClient } from './fake';

export interface EngineClient {
  readonly kind: 'http' | 'fake';
  desk(): Promise<DeskSummary>;
  caseDetail(id: string): Promise<CaseDetail>;
  score(link: string): Promise<ScoreResult>;
  register(q?: string): Promise<RegisterList>;
  seal(caseId: string): Promise<SealedRecord>;
  records(): Promise<SealedRecord[]>;
  verifyRecord(recordId: string, fields: RecordFields): Promise<VerifyResult>;
  approve(recordId: string, via: 'voice' | 'click', fields?: RecordFields): Promise<ApproveResult>;
  takedown(caseId: string): Promise<TakedownPackage>;
  prepareRecipient(caseId: string, recipientId: string): Promise<TakedownPackage>;
  markCase(caseId: string, as: 'licensed' | 'not_scam'): Promise<CaseDetail>;
  watch(): Promise<WatchState>;
  runWatch(): Promise<WatchState>;
  feeds(): Promise<Feeds>;
  drill(): Promise<DrillInfo>;
  scorecard(): Promise<Scorecard>;
  costs(): Promise<Costs>;
  agents(): Promise<AgentsState>;
  voiceSession(): Promise<VoiceSession>;
  voiceUsage(report: { model: string; seconds?: number; usage?: unknown }): Promise<void>;
  understand(text: string, lang: Lang): Promise<Understanding>;
}

export class EngineError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function httpClient(base = ''): EngineClient {
  const call = async <T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> => {
    const r = await fetch(base + path, {
      method: init?.method || (init?.body !== undefined ? 'POST' : 'GET'),
      headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
    if (!r.ok) {
      let why = `${r.status}`;
      try { const j = await r.json(); why = j.detail || j.why || why; } catch { /* not json */ }
      throw new EngineError(r.status, String(why));
    }
    return r.json() as Promise<T>;
  };
  const post = <T>(path: string, body: unknown = {}) => call<T>(path, { method: 'POST', body });
  const q = encodeURIComponent;
  return {
    kind: 'http',
    desk: () => call('/api/desk'),
    caseDetail: id => call(`/api/cases/${q(id)}`),
    score: link => post('/api/score', { link, mode: 'officer' }),
    register: qs => call(`/api/register${qs ? '?q=' + q(qs) : ''}`),
    seal: caseId => post(`/api/cases/${q(caseId)}/seal`),
    records: () => call('/api/records'),
    verifyRecord: (id, fields) => post(`/api/records/${q(id)}/verify`, { fields }),
    approve: (id, via, fields) => post(`/api/records/${q(id)}/approve`, { via, fields }),
    takedown: caseId => post(`/api/cases/${q(caseId)}/takedown`),
    prepareRecipient: (caseId, rid) => post(`/api/cases/${q(caseId)}/takedown/${q(rid)}/prepare`),
    markCase: (caseId, as) => post(`/api/cases/${q(caseId)}/mark`, { as }),
    watch: () => call('/api/watch'),
    runWatch: () => post('/api/watch/run'),
    feeds: () => call('/api/feeds'),
    drill: () => call('/api/drill'),
    scorecard: () => call('/api/scorecard'),
    costs: () => call('/api/costs'),
    agents: () => call('/api/agents'),
    voiceSession: async () => { // the engine answers {client_secret, expires_at, model}
      const j = await post<{ client_secret?: string; value?: string; expires_at?: number; expiresAt?: number; model: string }>('/api/voice/session');
      return { value: j.client_secret || j.value || '', model: j.model, expiresAt: j.expires_at ?? j.expiresAt ?? 0 };
    },
    voiceUsage: async report => { await post('/api/voice/usage', report).catch(() => undefined); },
    understand: (text, lang) => post('/api/voice/understand', { text, lang }),
  };
}

export function pickClient(): EngineClient {
  const qs = typeof location !== 'undefined' ? new URLSearchParams(location.search).get('engine') : null;
  const mode = qs || import.meta.env.VITE_ENGINE || 'fake';
  if (mode === 'http') return httpClient(import.meta.env.VITE_ENGINE_URL || '');
  return createFakeClient({ remote: true });
}
