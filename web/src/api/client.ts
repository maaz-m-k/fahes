/* The one module that talks to the Fahes engine. Every engine call the screens make goes through EngineClient.
   - httpClient: the real engine (FastAPI, spec issue #9). Paths below are the screens' side of the contract.
   - createFakeClient (./fake): built from the prototype's data, used until the engine ships and in every test.
   Pick with VITE_ENGINE=http (and VITE_ENGINE_URL for another origin) or ?engine=http|fake. Default: fake. */
import type {
  AgentsState, ApproveResult, CaseDetail, Costs, DeskSummary, DrillInfo, Feeds, Lang, RecordFields, RegisterList,
  ScoreResult, Scorecard, SealedRecord, TakedownPackage, Understanding, VerifyResult, VoiceSession, WatchState,
} from './types';
import { createFakeClient } from './fake';
import { engineClient } from './engine';

export interface EngineClient {
  readonly kind: 'http' | 'fake';
  desk(): Promise<DeskSummary>;
  caseDetail(id: string): Promise<CaseDetail>;
  score(link: string): Promise<ScoreResult>;
  scoreBatch(links: string[]): Promise<ScoreResult[]>; // the judges' page: same scoring as the judges' command
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
  voiceUsage(report: { model: string; seconds?: number; usage?: unknown; sessionId?: number }): Promise<void>;
  understand(text: string, lang: Lang): Promise<Understanding>;
}

export class EngineError extends Error {
  constructor(public status: number, message: string, public ar?: string) { super(message); }
}

export function pickClient(): EngineClient {
  const qs = typeof location !== 'undefined' ? new URLSearchParams(location.search).get('engine') : null;
  const mode = qs || import.meta.env.VITE_ENGINE || 'fake';
  if (mode === 'http') return engineClient(import.meta.env.VITE_ENGINE_URL || '');
  return createFakeClient({ remote: true });
}
