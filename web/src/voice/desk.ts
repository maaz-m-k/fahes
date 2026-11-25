/* The voice mode state model (approved after video review 3):
   idle (orb big, no card) --answer that needs UI--> answering (orb small at top, card with content A)
   answering --another answer that needs UI--> answering, content B replaces A inside the same card
   answering --"close" (voice or ×)--> idle, the card folds into the orb
   any --an answer that needs no screen--> idle with the spoken line under the orb
   Sound alone never changes state (the orb only listens). A spoken reply with no tool call is not an event here. */
import type { Bi } from '../api/types';
import type { Answer, ToolResult } from './tools';

export type DeskState = { phase: 'idle' | 'answering'; answer: Answer | null; version: number; line: Bi | null };
export type DeskEvent = { type: 'result'; result: ToolResult } | { type: 'close' } | { type: 'reset' };

export const initialDesk: DeskState = { phase: 'idle', answer: null, version: 0, line: null };

export function deskReducer(s: DeskState, e: DeskEvent): DeskState {
  switch (e.type) {
    case 'close':
      return s.phase === 'idle' ? s : { phase: 'idle', answer: null, version: s.version + 1, line: null };
    case 'reset':
      return { ...initialDesk, version: s.version + 1 };
    case 'result': {
      const r = e.result;
      if (!r.answer && !r.close && r.keep) return { ...s, line: r.say };
      if (r.close || !r.answer) return { phase: 'idle', answer: null, version: s.version + 1, line: r.say };
      return { phase: 'answering', answer: r.answer, version: s.version + 1, line: r.say };
    }
  }
}
