/* The shapes the screens read from the Fahes engine (spec: issue #9).
   Every number, name, address and verdict on screen comes from one of these responses.
   `marker` says what each part is: REAL, STAND-IN (holds the place of something real) or DEMO DATA. */

export type Lang = 'ar' | 'en';
export type Bi = { ar: string; en: string };
export type MarkerKind = 'real' | 'stand' | 'demo';
export type Marker = { kind: MarkerKind; note?: string };
export type Verdict = 'green' | 'grey' | 'red';

export type Reason = { code: string; ar: string; en: string };

export type CaseStatus = 'waiting' | 'sealed' | 'approved' | 'licensed';

export interface CaseSummary {
  id: string;
  n: number; // 1-based position in the officer's list
  title: Bi;
  source: Bi;
  address: string;
  verdict: Verdict;
  status: CaseStatus;
  sawThrough: Bi;
  marker: Marker;
}

/* real footage of a browser at work: a sped-up video and its captioned moments (t in real-time ms) */
export interface Footage { src: string; speed: number; width: number; height: number; moments: { t: number; ar: string; en: string }[]; marker: Marker }

export interface CaseDetail extends CaseSummary {
  capturedAt: string; // "02:14"
  query: Bi;
  reasons: Reason[];
  /* how the address fools the eye: the decoy part, the real owner, the rest */
  trick: { decoy: string; owner: string; rest: string } | null;
  /* the real path the fake imitates (null for a grey case) */
  imitates: { name: Bi; address: string; crumbs: Bi[] } | null;
  recordId: string | null;
  footage?: { server?: Footage; phone?: Footage } | null; // the two-view capture, recorded
}

export interface DeskSummary {
  needDecision: number;
  cases: CaseSummary[];
  marker: Marker;
}

export interface ScoreResult {
  host: string;
  verdict: Verdict;
  family: Bi | null; // the official family it belongs to (green) or looks like (grey/red)
  officialAddresses: string[]; // a green family's addresses
  reasons: Reason[];
  modelVersion: string;
  marker: Marker;
  link?: string; // as given
  score?: number;
}

export interface RegisterFamily {
  id: string;
  name: Bi;
  kind: 'gov' | 'bank' | 'generic' | 'licensed';
  addresses: string[];
  marker: Marker;
}
export interface RegisterList { total: number; families: RegisterFamily[]; learned: string[]; marker: Marker }

export interface RecordFields {
  time: string;
  source: string;
  query: string;
  address: string;
  verdict: string;
  reasons: string[];
  captures: string[];
}
export interface SealedRecord {
  id: string;
  caseId: string;
  caseN: number;
  title: Bi;
  sealedAt: number;
  fields: RecordFields;
  fingerprint: string; // SHA-256 of the sealed fields
  status: 'draft' | 'approved';
  approvedVia: 'voice' | 'click' | null;
  marker: Marker;
}
export interface VerifyResult { ok: boolean; fingerprintNow: string }
export interface ApproveResult { approved: boolean; why: Bi | null; via: 'voice' | 'click'; fingerprint: string; takedownReady: boolean }

export interface TakedownPackage {
  caseId: string;
  address: string;
  recipients: { id: string; name: Bi; state: 'draft' | 'ready' }[];
  sent: false; // nothing is ever sent outward
  marker: Marker;
}

export type Device = 'computer' | 'phone';
export interface CaptureStep { at: number; shot: string; url: string; ar: string; en: string }
export interface ViewResult { host: string; verdict: Verdict; title?: string }
export interface DeviceView {
  engine: string;
  steps: CaptureStep[];
  results: ViewResult[];
  opened: { host: string; landed: string } | null;
  robot: { engine: string }[];
}
export interface RoundCase {
  id: string;
  q: string;
  ar: string;
  startedAt: number;
  ms: number;
  counts: { read: number; green: number; grey: number; red: number };
  onlyPhone: string[];
  onlyComputer: string[];
  computer: DeviceView;
  phone: DeviceView;
  footage?: { computer?: Footage; phone?: Footage }; // real sped-up footage of this search, when recorded
}
export interface Round {
  id: string;
  startedAt: number;
  ms: number;
  shotBase: string; // URL prefix for step shots
  cases: RoundCase[];
  /* ONE short overview video per view of the round, always sped up; plus extra clips (e.g. a real Google clip) */
  footage?: { computer?: Footage; phone?: Footage };
  clips?: { label: Bi; footage: { computer?: Footage; phone?: Footage } }[];
  marker: Marker;
}
export interface WatchState {
  everyHours: number;
  nextAt: number;
  running: boolean;
  progress: { i: number; total: number } | null;
  engines: { id: string; name: string; logo: string; first: boolean }[];
  lastRound: Round | null;
  marker: Marker;
}

export interface Feeds {
  ct: { log: string; size: number; at: number; perMin: number; spark: number[]; marker: Marker };
  names: { total: number; branded: number; lookAlikes: number; source: string; marker: Marker };
  needDecision: number;
  funnel: { n: number; label: Bi; marker: Marker }[];
}

export interface DrillInfo {
  drill: { t: string; line: Bi }[];
  attacker: { t: string; line: Bi }[];
  marker: Marker;
}

export interface Scorecard {
  rows: { value: string; label: Bi; marker: Marker }[];
}

export interface Costs {
  soFar: { item: Bi; usd: number; marker: Marker }[];
  projectedMonthUsd: number;
  projectedNote: Bi;
  marker: Marker;
}

export type AgentId = 'watch' | 'register' | 'check' | 'capture' | 'seal' | 'drill' | 'scale' | 'officer';
export interface AgentsState {
  agents: { id: AgentId; name: Bi; status: Bi; busy: boolean; marker: Marker }[];
  lastCase: { query: Bi; at: number; steps: { agent: AgentId; line: Bi }[]; marker: Marker } | null;
}

export interface VoiceSession { value: string; model: string; expiresAt: number; sessionId?: number; maxSeconds?: number }

/* the tools the voice model (and the typed path) may call; mapped to engine endpoints in src/voice/tools.ts */
export type ToolName =
  | 'summary' | 'show_case' | 'check_address' | 'open_check' | 'show_run' | 'seal' | 'approve' | 'scale' | 'run_now' | 'agents' | 'close_card'
  | 'takedown' | 'mark_licensed' | 'records' | 'how_sure' | 'drill' | 'watch' | 'chat' | 'help';
export interface Understanding { tool: ToolName; args: Record<string, unknown>; say: string | null; source: 'model' | 'local' }
