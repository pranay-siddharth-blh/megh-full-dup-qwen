// 2026-11-16 (the voice audit, typed vs spoken): (1) a data answer's server-written spoken form is flagged
// `spoken_form`, so a voice engine that re-words answers (the sovereign engine's natural.py) reads it as given;
// (2) every answer the voice reads carries the pipeline's own reading of the question (`asked_as` = its rewritten
// question, `frame` = a short answer-frame summary), so the engine's memory of the conversation is the pipeline's.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { askedOf, spokenForm } from '../src/chat/voiceSpeech.js';

test('a spoken form is flagged for the engine; an answer without one is not', () => {
  const s = spokenForm({ route: 'data', answer: 'X 12.', spoken: 'Tikrikilla has the most. Demdema has the fewest, 0.' });
  assert.equal(s.spoken_form, true);
  assert.equal(s.speak, 'Tikrikilla has the most. Demdema has the fewest, 0.');
  assert.equal(spokenForm({ route: 'data', answer: 'The figure is 12,345.' }).spoken_form, undefined);
  assert.equal(spokenForm({ route: 'clarification', question: 'Which one?', spoken: 'x' }).spoken_form, undefined);
});

test('askedOf: the rewritten question first, else the translation, else the words asked', () => {
  assert.deepEqual(askedOf({ rewritten_question: 'How many CM Elevate applications are there by district?' }, 'CM Elevate'),
    { asked_as: 'How many CM Elevate applications are there by district?' });
  assert.deepEqual(askedOf({ translated_question: 'How many MGNREGA households?' }, 'मनरेगा'),
    { asked_as: 'How many MGNREGA households?' });
  assert.deepEqual(askedOf({}, 'only Ri Bhoi'), { asked_as: 'only Ri Bhoi' });
  assert.deepEqual(askedOf(null, ''), {});
});

test('askedOf: a short frame summary, plain data only', () => {
  const r = askedOf({
    rewritten_question: 'Top 5 districts by Focus Plus beneficiaries',
    answer_frame: { schemes: ['Focus Plus'], qtype: 'ranking', group: 'district', order: 'desc', limit: 5,
      filters: { year_key: 2023, village_code: 12 }, sql_shape: 'x', question: 'q', items: ['A', 'B'] },
  }, 'top five');
  assert.deepEqual(r.frame, { schemes: ['Focus Plus'], qtype: 'ranking', group: 'district', order: 'desc', limit: 5,
    filters: { year_key: 2023 } });
  assert.equal(askedOf({ answer_frame: 'nope' }, 'q').frame, undefined);
  assert.ok(askedOf({ rewritten_question: 'x'.repeat(900) }, '').asked_as.length === 400);
});
