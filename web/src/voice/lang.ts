/* Fahes answers in the language of the officer's last sentence, and a spoken "speak in Arabic" / "speak English"
   switches it and keeps it switched. The screen follows: Arabic or English words; any other language speaks in that
   language while the screen uses English. */
import type { Lang } from '../api/types';

export type Heard = 'ar' | 'en' | 'other';

export function detectLang(text: string): Heard | null {
  const letters = text.replace(/\S*[./@]\S*/g, "").replace(/[\s\d\p{P}\p{S}]/gu, '');
  if (!letters) return null;
  const ar = (letters.match(/[؀-ۿݐ-ݿ]/g) || []).length;
  const latin = (letters.match(/[A-Za-z]/g) || []).length;
  if (ar >= latin && ar > 0) return 'ar';
  if (latin > 0 && latin >= letters.length / 2) return 'en';
  return 'other';
}

/* "speak in Arabic", "talk English", «تكلم انجليزي», «كلمني بالعربي» ... -> the language to keep using */
export function langCommand(text: string): Heard | null {
  const s = text.toLowerCase().replace(/[ً-ْـ]/g, '').replace(/[أإآ]/g, 'ا');
  const asks = /(speak|talk|answer|reply|respond|switch)( to| in)?|(تكلم|كلمني|احكي|رد|جاوب|تحدث)( معي)?/.test(s);
  if (!asks) return null;
  if (/arabic|عربي|بالعربي|العربيه|العربية/.test(s)) return 'ar';
  if (/english|انجليزي|انقليزي|بالانجليزي|الانجليزيه|الانجليزية/.test(s)) return 'en';
  if (/malayalam|hindi|urdu|tagalog|french|russian|chinese|bengali|tamil|ماليالام|هندي|اردو/.test(s)) return 'other';
  return null;
}

/* the screen's language after the officer said `text`, given a language the officer asked to keep (or null) */
export function followSpeech(text: string, kept: Heard | null): { ui: Lang | null; kept: Heard | null } {
  const cmd = langCommand(text);
  if (cmd) return { ui: cmd === 'ar' ? 'ar' : 'en', kept: cmd };
  if (kept) return { ui: kept === 'ar' ? 'ar' : 'en', kept };
  const d = detectLang(text);
  return { ui: d === null ? null : d === 'ar' ? 'ar' : 'en', kept: null };
}
