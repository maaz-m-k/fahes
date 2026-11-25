/* FAKE ENGINE ONLY: the prototype's register and green/grey/red rule, so the screens run before the engine ships.
   The real register and scorer live in the engine (istibaq.core). */
import type { Bi, Reason, ScoreResult } from '../types';
import seedText from './register-seed.txt?raw';

export type Family = { id: string; ar: string; en: string; kind: 'gov' | 'bank' | 'generic'; domains: string[]; brand: string[] };

export const FAMILIES: Family[] = [
  { id: 'adp', ar: 'شرطة أبوظبي', en: 'Abu Dhabi Police', kind: 'gov', domains: ['adpolice.gov.ae', 'adpolice.ae', 'abudhabipolice.ae', 'abudhabipolice.gov.ae', 'police.abudhabi'], brand: ['adpolice', 'abudhabipolice', 'policeabudhabi'] },
  { id: 'tamm', ar: 'منصة تم، حكومة أبوظبي', en: 'TAMM, Abu Dhabi Government', kind: 'gov', domains: ['tamm.abudhabi'], brand: ['tamm'] },
  { id: 'dge', ar: 'دائرة التمكين الحكومي', en: 'Department of Government Enablement', kind: 'gov', domains: ['dge.gov.ae', 'dge.abudhabi'], brand: [] },
  { id: 'adpay', ar: 'أبوظبي باي', en: 'Abu Dhabi Pay', kind: 'gov', domains: ['abudhabipay.gov.ae'], brand: ['abudhabipay'] },
  { id: 'itc', ar: 'مركز النقل المتكامل', en: 'Integrated Transport Centre', kind: 'gov', domains: ['itc.gov.ae', 'admobility.gov.ae'], brand: ['darb', 'mawaqif', 'admobility'] },
  { id: 'icp', ar: 'الهيئة الاتحادية للهوية والجنسية', en: 'Federal Authority for Identity and Citizenship', kind: 'gov', domains: ['icp.gov.ae', 'ica.gov.ae'], brand: ['icp'] },
  { id: 'dubaipolice', ar: 'شرطة دبي', en: 'Dubai Police', kind: 'gov', domains: ['dubaipolice.gov.ae'], brand: ['dubaipolice'] },
  { id: 'adcb', ar: 'بنك أبوظبي التجاري', en: 'ADCB', kind: 'bank', domains: ['adcb.com'], brand: ['adcb'] },
  { id: 'fab', ar: 'بنك أبوظبي الأول', en: 'First Abu Dhabi Bank', kind: 'bank', domains: ['bankfab.com'], brand: ['bankfab'] },
  { id: 'adib', ar: 'مصرف أبوظبي الإسلامي', en: 'Abu Dhabi Islamic Bank', kind: 'bank', domains: ['adib.ae'], brand: ['adib'] },
  { id: 'enbd', ar: 'بنك الإمارات دبي الوطني', en: 'Emirates NBD', kind: 'bank', domains: ['emiratesnbd.com'], brand: ['emiratesnbd'] },
];
const FREEHOSTS = ['netlify.app', 'vercel.app', 'pages.dev', 'github.io', 'web.app', 'firebaseapp.com', 'wixsite.com', 'weebly.com', 'glitch.me', 'freehost.test'];
const RISKYTLD = ['top', 'xyz', 'icu', 'shop', 'online', 'site', 'live', 'click', 'info', 'cc', 'buzz', 'vip', 'cyou', 'sbs', 'lol'];
const LUREWORDS = ['pay', 'payment', 'fine', 'fines', 'verify', 'secure', 'login', 'refund', 'update', 'wallet', 'reward', 'gift', 'portal'];
const SUFFIX2 = ['gov.ae', 'gov.abudhabi', 'co.ae', 'net.ae', 'org.ae', 'ac.ae', 'com.ae'];

export function buildRegister(): Family[] {
  const fams: Family[] = FAMILIES.map(f => ({ ...f }));
  const owned = new Set(fams.flatMap(f => f.domains));
  const seed = seedText.split(/\s+/).map(s => s.trim().toLowerCase()).filter(Boolean);
  for (const d of seed) {
    if (!owned.has(d) && !fams.some(f => f.domains.some(x => d.endsWith('.' + x)))) {
      fams.push({ id: d, ar: 'جهة حكومية في السجل', en: 'A government body in the register', kind: 'generic', domains: [d], brand: [] });
      owned.add(d);
    }
  }
  return fams;
}

export const normHost = (s: string) => String(s).trim().toLowerCase().replace(/^[a-z]+:\/\//, '').split(/[/?#\s]/)[0].replace(/\.$/, '').replace(/^www\./, '');
function core(host: string) { const p = host.split('.'); const n = SUFFIX2.includes(p.slice(-2).join('.')) ? 2 : 1; return { labels: p.slice(0, -n), suffix: p.slice(-n).join('.') }; }
function lev(a: string, b: string) {
  const m = a.length, n = b.length; if (Math.abs(m - n) > 2) return 9;
  let p = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) { const c = [i]; for (let j = 1; j <= n; j++) c[j] = Math.min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); p = c; }
  return p[n];
}
const r = (code: string, ar: string, en: string): Reason => ({ code, ar, en });
const bi = (f: Family): Bi => ({ ar: f.ar, en: f.en });

export function resolve(fams: Family[], licensed: string[], input: string): Omit<ScoreResult, 'marker' | 'modelVersion'> {
  const host = normHost(input);
  for (const f of fams) for (const d of f.domains) if (host === d || host.endsWith('.' + d)) {
    const reasons = [r('register', `في سجل أبوظبي الحقيقي: عنوان رسمي لـ${f.ar}.`, `In the register of the real Abu Dhabi: an official address of ${f.en}.`)];
    if (!/\.gov\.ae$|\.gov\.abudhabi$/.test(host)) reasons.push(r('not_gov', 'قاعدة بسيطة تثق بـ gov.ae فقط كانت ستعلّمه كمشبوه. السجل يعرفه.', 'A simple rule that trusts only gov.ae would have flagged this one. The register knows it.'));
    return { host, verdict: 'green', family: bi(f), officialAddresses: f.kind === 'generic' ? [] : f.domains, reasons };
  }
  if (licensed.includes(host)) return { host, verdict: 'grey', family: null, officialAddresses: [], reasons: [r('licensed', 'ليس جهة رسمية. سجّله ضابط كنشاط مرخّص، فلا نتّهمه.', 'Not official. An officer recorded it as a licensed business, so we accuse nothing.')] };
  const { labels, suffix } = core(host);
  const flat = host.replace(/[-.]/g, ''); const deglyph = flat.replace(/0/g, 'o').replace(/1/g, 'l').replace(/3/g, 'e').replace(/5/g, 's');
  let F: { f: Family; how: 'brand' | 'typo'; glyph?: boolean; real?: string } | null = null;
  for (const f of fams) for (const b of f.brand) if (b && (flat.includes(b) || deglyph.includes(b))) F = F || { f, how: 'brand', glyph: !flat.includes(b) };
  if (!F) outer: for (const f of fams) for (const d of f.domains) {
    const rl = core(d).labels.join(''); if (rl.length < 5) continue;
    for (const l of [labels.join(''), ...labels]) if (l !== rl && lev(l, rl) <= (rl.length >= 8 ? 2 : 1)) { F = { f, how: 'typo', real: d }; break outer; }
  }
  const B: Reason[] = [];
  if (F && F.glyph) B.push(r('glyph', 'يضع رقماً مكان حرف (مثل 0 مكان o)، وهو تمويه معروف.', 'It puts a digit in place of a letter (like 0 for o), a known disguise.'));
  const fh = FREEHOSTS.find(x => host.endsWith('.' + x)); if (fh) B.push(r('free_host', `منشور على استضافة مجانية (${fh}) لا تستخدمها الجهات الرسمية.`, `It sits on a free host (${fh}) that official bodies do not use.`));
  const tld = host.split('.').pop() || ''; if (RISKYTLD.includes(tld)) B.push(r('tld', `الامتداد ‎.${tld} لا تستخدمه الجهات الرسمية في أبوظبي.`, `The ending .${tld} is not used by official bodies in Abu Dhabi.`));
  const words = host.split(/[-.]/).filter(w => LUREWORDS.includes(w)); if (words.length) B.push(r('lure', `كلمة دفع أو دخول في اسم الموقع (${words.join('، ')}).`, `A payment or login word in the name (${words.join(', ')}).`));
  if (/gov/.test(labels.join('-')) && !/gov\./.test(suffix)) B.push(r('gov_place', 'يضع «gov» في مكان خادع، وليس تحت gov.ae.', 'It puts "gov" in a misleading place, not under gov.ae.'));
  if (F) {
    const ra = F.how === 'brand'
      ? r('brand', `يستخدم اسم ${F.f.ar} وليس من عناوينه الرسمية في السجل.`, `It uses the name of ${F.f.en} and is not one of its official addresses.`)
      : r('typo', `يشبه عنواناً رسمياً (${F.real}) مع اختلاف حرف أو حرفين، وليس في السجل.`, `It looks like an official address (${F.real}) with a letter or two changed, and it is not in the register.`);
    if (B.length) return { host, verdict: 'red', family: bi(F.f), officialAddresses: [], reasons: [ra, ...B] };
    return { host, verdict: 'grey', family: bi(F.f), officialAddresses: [], reasons: [ra, r('one_reason', 'سبب واحد فقط. الأحمر يحتاج سببين مستقلين، فنراقبه ولا نتّهمه.', 'Only one reason. Red needs two independent reasons, so we watch it and accuse nothing.')] };
  }
  return { host, verdict: 'grey', family: null, officialAddresses: [], reasons: [r('unknown', 'ليس في سجل أبوظبي الحقيقي، ولا يشبه اسماً رسمياً نعرفه. غير رسمي، بدون اتهام.', 'Not in the register of the real Abu Dhabi, and it does not look like an official name we know. Not official, not accused.')] };
}
