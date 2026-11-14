/* global console, process */
// What the chat UI draws for an answer (2026-11-11, accuracy gold bank): viewPlan() of
// frontend/src/chat/analytics.js — the function components/Messages.jsx renders — read only.
// A message that only asks for a view ("pie chart") is redrawn from the previous answer's rows,
// as App.jsx does. Input: a JSON file [{key, q, r, last: {q, r} | null}]; output: one JSON object
// {key: {mode, charts: [{initial, types}], note} | null} on stdout.
//   node tests/accuracy/chart_view.mjs <items.json>
import { readFileSync } from 'node:fs';
import { viewOnlyRequest, viewPlan } from '../../frontend/src/chat/analytics.js';

// --view-only <questions.json>: {question: view | null} — the messages App.jsx redraws locally
// from the last answer's rows WITHOUT sending them to the server (sendQuery, viewOnlyRequest).
if (process.argv[2] === '--view-only') {
  const qs = JSON.parse(readFileSync(process.argv[3], 'utf-8'));
  const vo = {};
  for (const q of qs) vo[q] = viewOnlyRequest(q) || null;
  console.log(JSON.stringify(vo));
  process.exit(0);
}

const items = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const out = {};
for (const it of items) {
  try {
    const only = viewOnlyRequest(it.q);
    let plan = null;
    if (only && it.last && Array.isArray(it.last.r.data) && it.last.r.data.length) {
      plan = viewPlan(it.last.q, { ...it.last.r, rewritten_question: undefined }, only);
    } else if (Array.isArray(it.r.data) && it.r.data.length) {
      plan = viewPlan(it.q, it.r, null);
    }
    out[it.key] = plan ? { mode: plan.mode, note: plan.note || null, asked: plan.asked || null,
      charts: plan.charts.map((c) => ({ initial: c.initial || null, types: c.types || [] })) } : null;
  } catch (e) {
    out[it.key] = { error: String(e) };
  }
}
console.log(JSON.stringify(out));
