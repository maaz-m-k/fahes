/* The local matcher: understands a typed (or heard) request without any model. In place of the engine's text
   understanding; also the fallback when that call fails. Maps words to one tool from the closed kit. */
import type { Understanding } from '../api/types';

const normAr = (s: string) => s.toLowerCase().replace(/[ً-ْٰـ]/g, '').replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي');

export function findDomain(raw: string): string | null {
  const m = raw.toLowerCase().replace(/\s+(dot|نقطه|نقطة|دوت)\s+/g, '.').match(/[a-z0-9-]+(?:\.[a-z0-9-]+)+/);
  return m && /\.[a-z]{2,}$/.test(m[0]) ? m[0] : null;
}

export function match(raw: string): Understanding {
  const s = normAr(raw), R = (re: RegExp) => re.test(s), d = findDomain(raw);
  const u = (tool: Understanding['tool'], args: Record<string, unknown> = {}): Understanding => ({ tool, args, say: null, source: 'local' });
  if (d) return u('check_address', { domain: d });
  if (R(/check (a |some |the )?(link|links|address|addresses)|link checker|افحص رابط|افحص الرابط|ابي افحص|ابغي افحص|فحص عنوان|فحص الروابط|افحص عنوان/)) return u('open_check');
  if (R(/^\s*(close|سكر|اغلق|قفل)/) || R(/close (it|the screen|the card)|سكرها|سكر الشاشه|اغلقها|قفلها|شيلها/)) return u('close_card');
  if (R(/not a scam|licensed|typing|مرخص|طباعه|مب احتيال|ليس احتيال/)) return u('mark_licensed');
  if (R(/approve|اعتمد|اعتماد/)) return u('approve');
  if (R(/take ?down|ازاله|ازالة/)) return u('takedown');
  if (R(/seal|وثق|اختم|محضر/)) return u('seal');
  if (R(/agent|who is|doing what|الوكلاء|من يعمل|منو يشتغل|مين يشتغل/)) return u('agents');
  if (R(/run now|run it|start the round|(^|\s)شغل|ابدا الجوله/)) return u('run_now');
  if (R(/phone|موبايل|تلفون|تليفون|هاتف/)) return u('show_run', { view: 'phone' });
  if (R(/replay|the run|show.*run|الجوله|كيف اشتغل|اعد/)) return u('show_run', { view: 'both' });
  if (R(/how sure|accura|متاكد|دقه/)) return u('how_sure');
  if (R(/drill|تمرين/)) return u('drill');
  if (R(/records|drafts|محاضر|المسودات/)) return u('records');
  if (R(/internet|scale|how many|new sites|الانترنت|يولد|كم/)) return u('scale');
  if (R(/watch|schedule|الرصد|الجدول/)) return u('watch');
  if (R(/first|الاولي|الاول/)) return u('show_case', { n: 1 });
  if (R(/second|الثانيه|الثاني/)) return u('show_case', { n: 2 });
  if (R(/third|الثالثه|الثالث/)) return u('show_case', { n: 3 });
  if (R(/next|التالي/)) return u('show_case', { n: 'next' });
  if (R(/morning|today|what do we|صباح|عندي|عندنا|اليوم|لدينا/)) return u('summary');
  if (R(/thank|hello|hi\b|شكرا|مشكور|مرحبا|هلا/)) return u('chat');
  return u('help');
}
