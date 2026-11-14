// Full-duplex voice (2026-11-02): what the live voice reads for each kind of
// answer (src/chat/voiceSpeech.js). The figures are never changed: a number is
// read as the checked answer writes it, a long answer is cut only at a sentence
// end, a table is read as its first rows, a clarification as its question and
// options.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { cutAtSentence, plainForSpeech, spokenForm, spokenNote } from '../src/chat/voiceSpeech.js';

test('a data answer is read word for word, markdown removed, figures untouched', () => {
  const r = { route: 'data', answer: '**54,89,616** person-days were generated in **West Garo Hills** in FY 2023-24 under the MGNREGA scheme.' };
  const s = spokenForm(r);
  assert.equal(s.speak, '54,89,616 person-days were generated in West Garo Hills in FY 2023-24 under the MGNREGA scheme.');
  assert.equal(s.kind, 'data');
  assert.equal(s.read_exactly, true);
});

test('an exact rupee figure with its approximation is said once, as the approximation; the exact one stays on screen', () => {
  const s = spokenForm({ route: 'data', answer: 'Total disbursed: ₹37,49,31,500 (≈ ₹37.49 crore).' });
  assert.equal(s.speak, 'Total disbursed: about ₹37.49 crore.');
  // a bracket after words, not a figure, keeps its words; its ≈ is still said "about"
  assert.equal(spokenForm({ route: 'data', answer: 'Spent in the year (≈ ₹5 crore).' }).speak, 'Spent in the year (about ₹5 crore).');
  // a plain exact figure is read as it is
  assert.equal(spokenForm({ route: 'data', answer: 'Houses: 1,71,107.' }).speak, 'Houses: 1,71,107.');
});

test('a data answer is cut for the voice at about 320 characters (20-25 s), at a sentence end', () => {
  const long = 'West Garo Hills had 54,89,616 person-days in FY 2023-24 under the MGNREGA scheme. '.repeat(8);
  const s = spokenForm({ route: 'data', answer: long });
  assert.ok(s.speak.length <= 320 + ' The rest of the answer is on your screen.'.length);
  assert.ok(s.speak.endsWith('The rest of the answer is on your screen.'));
});

test('a table is read as its header and first three rows, the rest is on screen', () => {
  const answer = [
    'Person-days by district, FY 2023-24:',
    '| District | Person-days |',
    '|---|---|',
    '| West Garo Hills | 54,89,616 |',
    '| East Khasi Hills | 41,02,118 |',
    '| Ri Bhoi | 12,04,331 |',
    '| Tura | 9,00,001 |',
    '| Jowai | 8,00,002 |',
  ].join('\n');
  const t = plainForSpeech(answer);
  assert.ok(t.includes('District, Person-days.'));
  assert.ok(t.includes('West Garo Hills, 54,89,616.'));
  assert.ok(t.includes('Ri Bhoi, 12,04,331.'));
  assert.ok(!t.includes('Tura'));
  assert.ok(t.includes('and 2 more rows are on your screen.'));
  assert.ok(!t.includes('|') && !t.includes('---'));
});

test('a clarification is asked with its options', () => {
  const s = spokenForm({
    route: 'clarification', intent: 'CLARIFY', question: 'Which **Focus** do you mean?',
    clarification: { options: [{ label: 'Focus Plus', question: 'Focus Plus' }, { label: 'Focus Legacy', question: 'Focus Legacy' }] },
  });
  assert.equal(s.kind, 'clarification');
  assert.equal(s.speak, 'Which Focus do you mean? The options are Focus Plus or Focus Legacy.');
});

test('a long option list reads six and points to the screen', () => {
  const options = Array.from({ length: 12 }, (_, i) => ({ label: `District ${i + 1}` }));
  const s = spokenForm({ route: 'clarification', question: 'Which district?', clarification: { options } });
  assert.ok(s.speak.includes('District 5 or District 6.'));
  assert.ok(s.speak.endsWith('There are 6 more on your screen.'));
});

test('a long answer is cut at a sentence end, never inside a number', () => {
  const sentence = 'In FY 2023-24 the district generated 54,89,616 person-days under the scheme. ';
  const long = sentence.repeat(12);
  const { text, cut } = cutAtSentence(long, 200);
  assert.ok(cut);
  assert.ok(text.endsWith('scheme.'));
  const s = spokenForm({ route: 'knowledge', answer: long });
  assert.ok(s.speak.endsWith('The rest of the answer is on your screen.'));
  assert.ok(!s.speak.includes('54,89,6 '));
});

test('lists and headings are read as plain sentences', () => {
  const t = plainForSpeech('### Eligibility\n- Rural households\n* Adult members\n• Willing to do unskilled work');
  assert.equal(t, 'Eligibility\nRural households\nAdult members\nWilling to do unskilled work');
});

test('an empty answer points to the screen; a note is read as written', () => {
  assert.equal(spokenForm({ route: 'data', answer: '' }).speak, 'The answer is on your screen.');
  assert.equal(spokenNote('Stopped. Type "continue" when you want this answer.').speak, 'Stopped. Type "continue" when you want this answer.');
});

test('a long list is read as its first three items and a count of the rest', () => {
  const items = Array.from({ length: 9 }, (_, i) => `- DALU village ${i + 1}: ${i * 10} person-days`).join('\n');
  const t = plainForSpeech('Here are the 9 results:\n' + items + '\n\nThe full list is in the table.');
  assert.ok(t.startsWith('Here are the 9 results:'));
  assert.ok(t.includes('DALU village 3: 20 person-days'));
  assert.ok(!t.includes('DALU village 4'));
  assert.ok(t.includes('and 6 more are on your screen.'));
  assert.ok(t.endsWith('The full list is in the table.'));
});

test('a numbered list counts the same way; a short list is read whole', () => {
  const t = plainForSpeech('Top districts:\n1. West Garo Hills\n2. Ri Bhoi\n3. Tura\n4. Jowai');
  assert.ok(t.includes('Tura') && !t.includes('Jowai') && t.endsWith('and 1 more is on your screen.'));
  assert.equal(plainForSpeech('Two:\n- a one\n- b two'), 'Two:\na one\nb two');
});
