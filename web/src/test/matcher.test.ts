import { match } from '../voice/matcher';

it.each([
  ['صباح الخير، شو عندنا اليوم؟', 'summary'],
  ['افتح الحالة الأولى', 'show_case'],
  ['وثّقها', 'seal'],
  ['اعتمد', 'approve'],
  ['ورني الجولة على التلفون', 'show_run'],
  ['مين يشتغل الحين؟', 'agents'],
  ['شغّل الجولة الحين', 'run_now'],
  ['سكّرها', 'close_card'],
  ['adpolice-fines.top', 'check_address'],
])('the local matcher understands %s', (text, tool) => {
  expect(match(text).tool).toBe(tool);
});
