/* global console, process */
// Grades a tests/live_chat_charts.py run with the real chat code (2026-10-30): each
// answer is drawn by viewPlan() in src/chat/analytics.js, which is what
// components/Messages.jsx renders. A message that only asks for a view ("pie chart")
// is redrawn from the last answer's rows, as App.jsx does.
//   node frontend/tests/chart_live_grade.mjs tests/nl2sql_eval/results/<run>.json
import { readFileSync } from 'node:fs';
import { viewOnlyRequest, viewPlan } from '../src/chat/analytics.js';

const run = JSON.parse(readFileSync(process.argv[2], 'utf-8'));

function grade(turn, plan, route, answer = '') {
  if (turn.says && !String(answer).includes(turn.says)) return [`the answer does not say "${turn.says}"`];
  if (turn.want === 'any') return [];
  if (route !== 'data') return [`no data answer (route ${route})`];
  if (!plan || !plan.charts.length) return [`no chart drawn (${plan ? plan.mode : 'nothing'})`];
  if (turn.want === 'chart') return [];
  const errs = [];
  for (const c of plan.charts) {
    if (c.types.length !== 1 || c.types[0] !== turn.want) errs.push(`types ${c.types.join('/')} for ${turn.want}`);
    if (c.initial !== turn.want) errs.push(`opens as ${c.initial} for ${turn.want}`);
  }
  return [...new Set(errs)];
}

let ok = 0;
let all = 0;
const groups = {};
for (const chat of run.results) {
  let last = null;
  let chatOk = true;
  const lines = [];
  for (const t of chat.turns) {
    const r = t.response || {};
    const only = viewOnlyRequest(t.q);
    let plan;
    let route = String(r.route || '');
    if (only && last) {
      plan = viewPlan(last.q, { ...last.r, rewritten_question: undefined }, only);
      route = 'data';
    } else {
      plan = Array.isArray(r.data) && r.data.length ? viewPlan(t.q, r, t.view) : null;
      if (Array.isArray(r.data) && r.data.length) last = { q: t.q, r };
    }
    const errs = grade(t, plan, route, r.answer);
    chatOk = chatOk && !errs.length;
    const drawn = plan ? `${plan.mode}: ${plan.charts.map((c) => `${c.initial}[${c.types.join('/')}]`).join(' ') || '-'}` : '-';
    lines.push(`     Q: ${t.q}\n        want ${t.want} -> ${drawn} rows=${(r.data || []).length} hint=${r.chart_type || '-'} ${errs.length ? '!! ' + errs.join('; ') : ''}`
      + (plan && plan.note ? `\n        note: ${plan.note}` : '')
      + (errs.length ? `\n        answer: ${String(r.answer || '').split('\n').join(' ').slice(0, 200)}\n        cols: ${Object.keys((r.data || [])[0] || {}).join(', ')}` : ''));
  }
  all += 1;
  ok += chatOk ? 1 : 0;
  const g = (groups[chat.group] = groups[chat.group] || [0, 0]);
  g[0] += chatOk ? 1 : 0;
  g[1] += 1;
  console.log(`${chatOk ? 'PASS' : 'FAIL'} ${chat.id}\n${lines.join('\n')}`);
}
console.log(`\nby group: ${Object.entries(groups).map(([k, [a, b]]) => `${k} ${a}/${b}`).join(', ')}`);
console.log(`chats ${ok}/${all} (${((100 * ok) / Math.max(1, all)).toFixed(1)}%)`);
process.exit(ok === all ? 0 : 1);
