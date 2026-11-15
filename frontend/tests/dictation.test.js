// Dictation (D-111, 2026-11-15): the state machine, where the words go in the box, cancel, the mic lock.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { IDLE, isLive, message, reduce } from '../src/chat/dictation/machine.js';
import { atSentenceStart, begin, compose, restore, shape } from '../src/chat/dictation/insert.js';
import * as micLock from '../src/chat/dictation/micLock.js';

const run = (events, s = IDLE) => events.reduce((st, e) => reduce(st, e), s);

// ── the machine ─────────────────────────────────────────────────────────────

test('idle -> permission -> connecting -> listening -> finishing -> idle', () => {
  let s = reduce(IDLE, { type: 'START' });
  assert.equal(s.status, 'permission');
  s = reduce(s, { type: 'MIC_OK', at: 5 });
  assert.equal(s.status, 'connecting');
  s = reduce(s, { type: 'READY', at: 7 });
  assert.equal(s.status, 'listening');
  assert.equal(s.startedAt, 7);
  s = reduce(s, { type: 'PARTIAL', seq: 1, stable: 'How many', tentative: 'houses' });
  s = reduce(s, { type: 'STOP' });
  assert.equal(s.status, 'finishing');
  s = reduce(s, { type: 'FINAL', text: 'How many houses?', corrections: [] });
  assert.equal(s.status, 'idle');
  assert.equal(s.final, 'How many houses?');
  assert.equal(isLive(s), false);
});

test('the socket may be ready before the microphone', () => {
  const s = run([{ type: 'START' }, { type: 'READY' }, { type: 'MIC_OK', at: 3 }]);
  assert.equal(s.status, 'listening');
  assert.equal(s.startedAt, 3);
});

test('partials are taken in order only', () => {
  let s = run([{ type: 'START' }, { type: 'READY' }, { type: 'MIC_OK' }]);
  s = reduce(s, { type: 'PARTIAL', seq: 2, stable: 'b', tentative: '' });
  s = reduce(s, { type: 'PARTIAL', seq: 1, stable: 'a', tentative: '' });
  assert.equal(s.stable, 'b');
  assert.equal(s.seq, 2);
});

test('a partial after the final changes nothing', () => {
  let s = run([{ type: 'START' }, { type: 'READY' }, { type: 'MIC_OK' }, { type: 'STOP' },
    { type: 'FINAL', text: 'done' }]);
  s = reduce(s, { type: 'PARTIAL', seq: 9, stable: 'late', tentative: '' });
  assert.equal(s.stable, 'done');
});

test('errors carry their kind and a message; cancel from any live state', () => {
  const live = run([{ type: 'START' }, { type: 'READY' }, { type: 'MIC_OK' }]);
  assert.equal(reduce(live, { type: 'NO_SPEECH' }).error, 'no_speech');
  assert.equal(reduce(reduce(IDLE, { type: 'START' }), { type: 'MIC_DENIED' }).error, 'denied');
  assert.equal(reduce(reduce(IDLE, { type: 'START' }), { type: 'MIC_NONE' }).error, 'nomic');
  assert.equal(reduce(live, { type: 'ERROR', kind: 'asr' }).error, 'asr');
  assert.ok(message(reduce(live, { type: 'NO_SPEECH' })).includes('speech'));
  for (const st of ['permission', 'connecting', 'listening', 'finishing']) {
    assert.equal(reduce({ ...IDLE, status: st }, { type: 'CANCEL' }).status, 'cancelled');
  }
  assert.equal(reduce(IDLE, { type: 'CANCEL' }), IDLE);
});

test('a socket closed before ready is "unavailable" (the page falls back); after ready it is "lost"', () => {
  const opening = run([{ type: 'START' }, { type: 'MIC_OK' }]);
  assert.equal(reduce(opening, { type: 'CLOSED' }).error, 'unavailable');
  const live = run([{ type: 'START' }, { type: 'READY' }, { type: 'MIC_OK' }]);
  assert.equal(reduce(live, { type: 'CLOSED' }).error, 'lost');
  assert.equal(reduce(live, { type: 'CLOSED', reason: 'replaced' }).status, 'cancelled');
});

test('stop while still asking for the microphone is a cancel; a second start is ignored', () => {
  const asking = reduce(IDLE, { type: 'START' });
  assert.equal(reduce(asking, { type: 'STOP' }).status, 'cancelled');
  const live = run([{ type: 'START' }, { type: 'READY' }, { type: 'MIC_OK' }]);
  assert.equal(reduce(live, { type: 'START' }), live);
});

// ── where the words go ──────────────────────────────────────────────────────

test('an empty box: the words, with a capital', () => {
  const ctx = begin('', 0, 0);
  assert.equal(compose(ctx, 'how many houses?', '').value, 'How many houses?');
});

test('after a sentence: a space and a capital', () => {
  const ctx = begin('Show MGNREGA.', 13, 13);
  assert.equal(compose(ctx, 'now the wages', '').value, 'Show MGNREGA. Now the wages');
});

test('mid-sentence at the caret: spaces both sides, the model\'s capital and full stop taken off', () => {
  const v = 'show me the in Ri Bhoi';
  const ctx = begin(v, 12, 12);                      // after "the "
  assert.equal(compose(ctx, 'Houses sanctioned.', '').value, 'show me the houses sanctioned in Ri Bhoi');
  const glued = begin('show me thein Ri Bhoi', 11, 11);
  assert.equal(compose(glued, 'Houses', '').value, 'show me the houses in Ri Bhoi');
});

test('names keep their capitals mid-sentence', () => {
  const ctx = begin('houses in ', 10, 10);
  assert.equal(compose(ctx, 'Ri Bhoi', '').value, 'houses in Ri Bhoi');
  assert.equal(compose(begin('compare ', 8, 8), 'MGNREGA and PMAY-G', '').value, 'compare MGNREGA and PMAY-G');
});

test('a selection is replaced by the words', () => {
  const ctx = begin('houses in West Garo Hills', 10, 25);
  assert.equal(compose(ctx, 'Ri Bhoi', '').value, 'houses in Ri Bhoi');
});

test('no space before a comma or a full stop that follows', () => {
  const ctx = begin('houses in , please', 10, 10);
  assert.equal(compose(ctx, 'Ri Bhoi', '').value, 'houses in Ri Bhoi, please');
});

test('stable and tentative words: where each is, for the muted tentative ones', () => {
  const ctx = begin('Q: ', 3, 3);
  const c = compose(ctx, 'how many', 'houses');
  assert.equal(c.value, 'Q: how many houses');
  assert.equal(c.value.slice(c.start, c.stableEnd), 'how many');
  assert.equal(c.value.slice(c.stableEnd, c.end).trim(), 'houses');
});

test('nothing heard yet leaves the box as it was', () => {
  const ctx = begin('typed', 5, 5);
  assert.equal(compose(ctx, '', '').value, 'typed');
});

test('cancel puts back the text and the selection exactly', () => {
  const ctx = begin('show me the  houses', 4, 11);
  compose(ctx, 'some words', 'more');
  assert.deepEqual(restore(ctx), { value: 'show me the  houses', selStart: 4, selEnd: 11 });
});

test('sentence starts', () => {
  assert.equal(atSentenceStart(''), true);
  assert.equal(atSentenceStart('Done.  '), true);
  assert.equal(atSentenceStart('Why? '), true);
  assert.equal(atSentenceStart('show me'), false);
  assert.equal(shape('  Hello there. ', 'say', ''), 'hello there.');
});

// ── one microphone ──────────────────────────────────────────────────────────

test('the mic lock: one owner at a time; the orb stops dictation through it', () => {
  micLock._reset();
  let stopped = 0;
  assert.equal(micLock.acquire('dictation', () => { stopped += 1; }), true);
  assert.equal(micLock.holder(), 'dictation');
  assert.equal(micLock.acquire('live'), false);              // refused while dictation holds it
  assert.equal(micLock.stopDictation(), true);
  assert.equal(stopped, 1);
  micLock.release('dictation');
  assert.equal(micLock.holder(), null);
  assert.equal(micLock.stopDictation(), false);
  assert.equal(micLock.acquire('live'), true);
  micLock.release('dictation');                              // only the holder releases
  assert.equal(micLock.holder(), 'live');
  micLock._reset();
});

test('the mic lock tells its listeners', () => {
  micLock._reset();
  const seen = [];
  const off = micLock.subscribe((h) => seen.push(h));
  micLock.acquire('dictation');
  micLock.release('dictation');
  off();
  micLock.acquire('live');
  assert.deepEqual(seen, ['dictation', null]);
  micLock._reset();
});
