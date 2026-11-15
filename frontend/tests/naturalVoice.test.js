// 2026-11-15 (user report, live voice): (A) the voice read the whole answer like a report; a data answer now carries a
// short spoken form written and number-checked on the server (`spoken`), which the voice says instead. (B) "Take me
// back to the dashboard." went to the chat pipeline: navigation is now recognised in any wording, by a closed word
// vocabulary (no regex), while data questions that mention a dashboard or a chart stay questions.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spokenForm } from '../src/chat/voiceSpeech.js';
import { canonicalNav } from '../src/chat/voice/voiceViews.js';

const LIST = 'West Garo Hills stands out with 33,147 PMAY-G houses sanctioned.\n'
  + '- **West Garo Hills** — 33,147\n- **East Khasi Hills** — 23,952\n- **Ri Bhoi** — 17,565\n- **East Garo Hills** — 16,899';

test('a data answer with a spoken form is said in that form, not read out as a list', () => {
  const spoken = 'West Garo Hills has the most, just over 33,000 PMAY-G houses sanctioned. All 12 districts are on your screen.';
  const s = spokenForm({ route: 'data', answer: LIST, spoken });
  assert.equal(s.speak, spoken);
  assert.equal(s.read_exactly, true);
  assert.equal(s.kind, 'data');
  assert.ok(!s.speak.includes('23,952'));
});

test('without a spoken form the answer is read as before', () => {
  const s = spokenForm({ route: 'data', answer: LIST });
  assert.ok(s.speak.startsWith('West Garo Hills stands out with 33,147'));
  assert.ok(s.speak.includes('East Khasi Hills — 23,952'));
  assert.equal(spokenForm({ route: 'data', answer: LIST, spoken: '   ' }).speak, s.speak);
});

test('a clarification is still asked as its question, whatever spoken form it carries', () => {
  const s = spokenForm({ route: 'clarification', question: 'Which district?', spoken: 'ignored',
    clarification: { options: [{ label: 'Ri Bhoi' }, { label: 'West Garo Hills' }] } });
  assert.equal(s.kind, 'clarification');
  assert.ok(s.speak.startsWith('Which district?'));
});

test('navigation in any wording goes back to the dashboard', () => {
  for (const q of ['Take me back to the dashboard.', 'take me back to the dashboard', 'back to the dashboard',
    'Go back to the dashboard', 'go home', 'Take me home please', 'show the dashboard', 'show me the dashboard',
    'Can you take me to the main screen?', 'back to the main page', 'go back', 'Go back.', 'close the chart',
    'hide the chart', 'dashboard', 'the dashboard please', "let's go back to the dashboard", 'OK, take me home now']) {
    assert.equal(canonicalNav(q), 'desk', q);
  }
});

test('the chart again', () => {
  for (const q of ['bring the chart back', 'Bring the chart back.', 'show the chart again', 'show me the last chart',
    'go back to the chart', 'can you show the graph again', 'open the previous chart']) {
    assert.equal(canonicalNav(q), 'chart', q);
  }
});

test('data questions and other commands are never navigation', () => {
  for (const q of ['dashboard of MGNREGA expenditure', 'show me PMAY-G houses by district', 'MGNREGA dashboard',
    'show the MGNREGA dashboard', "what's on the dashboard", 'show me the chart', 'show it as a bar chart', 'close',
    'show it again', 'go back to 2022-23', 'back to Ri Bhoi', 'take me back to Focus Plus', 'start a new chat',
    'how many houses are on the dashboard', 'chart of person days by block', '', null, 'previous']) {
    assert.equal(canonicalNav(q), null, String(q));
  }
});
