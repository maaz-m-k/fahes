/* What is born below the orb: a few large words, only the pieces that matter, and next-step chips. */
import type { RecordFields } from '../api/types';
import { useLang } from '../i18n';
import { Ticks } from '../kit/basics';
import { AgentsRow, CasesList, CheckPanel, DrillView, Mirror, RecordsList, RecordView, Replay, RoundView, ScaleView, ScorecardView, TakedownView, VerdictView } from '../kit/pieces';
import type { Answer, Card, Chip } from './tools';

export type CardActions = {
  chip: (c: Chip) => void;
  pickCase: (n: number) => void;
  recordFields: (recordId: string, f: RecordFields) => void;
  approveClick: () => void;
  check: (link: string) => Promise<void>;
};

export function CardBody({ card, act }: { card: Card; act: CardActions }) {
  switch (card.kind) {
    case 'summary': return <CasesList desk={card.desk} onPick={c => act.pickCase(c.n)} />;
    case 'case': return <Mirror d={card.detail} compact />;
    case 'verdict': return <VerdictView r={card.score} />;
    case 'check': return <CheckPanel results={card.results} onCheck={act.check} compact />;
    case 'record': return <RecordView record={card.record} onFields={f => act.recordFields(card.record.id, f)} onApprove={act.approveClick} />;
    case 'done': return <Ticks items={card.items} />;
    case 'replay': return <Replay round={card.round} ci={card.ci} view={card.view} fill={card.view === 'phone'} />;
    case 'round': return <RoundView w={card.watch} />;
    case 'scale': return <ScaleView feeds={card.feeds} />;
    case 'agents': return <AgentsRow a={card.agents} />;
    case 'takedown': return <TakedownView pkg={card.pkg} />;
    case 'drill': return <div className="piece"><DrillView d={card.drill} /></div>;
    case 'scorecard': return <ScorecardView s={card.scorecard} />;
    case 'records': return <div className="piece"><RecordsList records={card.records} /></div>;
  }
}

export function AnswerCard({ answer, act }: { answer: Answer; act: CardActions }) {
  const { t } = useLang();
  const words = t(answer.words);
  return (
    <>
      <div className="words" data-testid="words">{words.split(/(\s+)/).map((x, k) => <span key={k} style={{ animationDelay: k * 45 + 'ms' }}>{x}</span>)}</div>
      <div data-testid="card-body" data-kind={answer.card.kind} style={{ width: '100%', animationDelay: '220ms' }}><CardBody card={answer.card} act={act} /></div>
      {answer.chips.length > 0 && (
        <div className="chips" data-testid="chips">
          {answer.chips.slice(0, 3).map((c, k) => <button key={k} type="button" className={'chip' + (k === 0 ? ' pri' : '')} onClick={() => act.chip(c)}>{t(c.label)}</button>)}
        </div>
      )}
    </>
  );
}
