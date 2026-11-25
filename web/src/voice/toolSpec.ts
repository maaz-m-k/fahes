/* The voice model's settings, instructions and tool list. One source: istibaq/voice/session.json, which the engine
   mints sessions with (istibaq/voice/mint.py) and the dev mint in web/dev/devApi.ts uses too. The tool names must
   match src/voice/tools.ts. */
import session from '../../../istibaq/voice/session.json';

export const VOICE_MODEL: string = session.model;
export const VOICE_NAME: string = session.voice; // the voice the team lead picked
export const VOICE_INSTRUCTIONS: string = session.instructions;
export const VOICE_TOOLS = session.tools;
