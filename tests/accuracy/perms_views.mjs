/* global console, process */
// The two view readers the permutation bank checks (2026-11-16): the chat's local redraw of a TYPED message
// (analytics.js viewOnlyRequest, App.jsx) and the voice page's canonical sentence (voiceViews.js canonicalView:
// the engine's shaper turns a spoken chart switch into one of its seven sentences). Read only.
//   node tests/accuracy/perms_views.mjs <sentences.json>  ->  {sentence: {typed, voice}}
import { readFileSync } from 'node:fs';
import { viewOnlyRequest } from '../../frontend/src/chat/analytics.js';
import { canonicalView } from '../../frontend/src/chat/voice/voiceViews.js';

const qs = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const out = {};
for (const q of qs) out[q] = { typed: viewOnlyRequest(q) || null, voice: canonicalView(q) || null };
console.log(JSON.stringify(out));
