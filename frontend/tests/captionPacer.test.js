// The live voice's captions are paced by the audio that PLAYS (voice/captionPacer.js, 2026-11-15): the user's live
// test found them "flickering or not coming at all" and the picture late, because each piece of text waited for the
// last audio chunk queued (on the real Gemini Live, the end of a burst) and came a whole sentence at a time.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addAudio, addText, cut, finish, joinOut, newPacer, pending, played, shownText, splitWords, step, wordAt } from '../src/chat/voice/captionPacer.js';

const words = (n, from = 0) => Array.from({ length: n }, (_, i) => `w${from + i}`).join(' ');
// a burst like the real voice: `secs` of audio queued from audio-clock 0 in 0.5 s chunks
const queue = (p, secs, from = 0) => { for (let t = from; t < from + secs - 1e-9; t += 0.5) addAudio(p, t, 0.5); };

test('words are split on any whitespace and two spoken pieces get one space between sentences', () => {
  assert.deepEqual(splitWords(' years:\nWEST  GARO\tHILLS '), ['years:', 'WEST', 'GARO', 'HILLS']);
  assert.equal(joinOut('with 5,494.', 'Hello, sir'), 'with 5,494. Hello, sir');
  assert.equal(joinOut('with 5,494', '.'), 'with 5,494.');
  assert.equal(joinOut('', 'Hello'), 'Hello');
});

test('a sentence that arrives with a burst of audio is spread over that audio, word by word', () => {
  const p = newPacer();
  queue(p, 10);                              // 10 s of audio already queued (the burst) ...
  addText(p, words(30) + '.', 0);           // ... with the text of the 30 words it holds
  assert.equal(step(p, 0, 0), 0, 'nothing shown before the audio starts');
  // the page's clock: a tick every 50 ms up to `sec`
  let clock = 0;
  const at = (sec) => { while (clock < sec - 1e-9) { clock = Math.min(sec, clock + 0.05); step(p, clock, clock * 1000); } return p.shown; };
  const first = at(0.2);
  assert.ok(first >= 1 && first <= 2, `${first}`);
  const mid = at(5);
  assert.ok(mid >= 14 && mid <= 17, `half-way through the audio about half the words, got ${mid}`);
  assert.equal(at(10.01), 30);
  assert.equal(shownText(p), words(30) + '.');
});

test('it never runs ahead of the audio: the old rule showed the whole burst at once', () => {
  const p = newPacer();
  queue(p, 20);
  addText(p, words(10) + '.', 0);
  assert.ok(wordAt(p, 1) <= 1.0 && wordAt(p, 1) >= 0.4, 'anchored to the audio queued when the text came');
  assert.ok(step(p, 1, 1000) <= 2);
});

test('a long pause of the clock still types the words in (never a sentence at once)', () => {
  const p = newPacer();
  queue(p, 1);
  step(p, 0.1, 100);
  addText(p, words(12) + '.', 9000);
  step(p, 9, 9500);
  assert.ok(p.shown <= 3, `after a 9 s pause: ${p.shown}`);
});

test('a sentence that arrives after its audio already played is typed in, a word or two per tick, never all at once', () => {
  const p = newPacer();
  queue(p, 3);
  let t = 3.2;                              // the audio is over, nothing is shown yet
  addText(p, words(24) + '.', t * 1000);
  const seen = [];
  for (let i = 0; i < 60 && p.shown < 24; i++) { t += 0.05; seen.push(step(p, t, t * 1000)); }
  assert.equal(p.shown, 24);
  const jumps = seen.map((n, i) => n - (i ? seen[i - 1] : 0));
  assert.ok(Math.max(...jumps) <= 3, `steps ${jumps}`);
});

test('text with no audio at all is shown after a short settle (a read with audio dropped never hangs)', () => {
  const p = newPacer();
  addText(p, 'Stopped.', 0);
  assert.equal(step(p, 0, 100), 0);
  step(p, 0, 500);
  step(p, 0, 560);
  assert.equal(shownText(p), 'Stopped.');
});

test('a growing last word waits until it is whole ("Meghal" + "aya")', () => {
  const p = newPacer();
  queue(p, 5);
  addText(p, 'PMAY-G houses in Meghal', 0);
  assert.equal(p.complete, 3);
  addText(p, 'aya are 33,147 ', 10);
  assert.equal(p.complete, 6);
  addText(p, 'in total', 20);
  finish(p, 30);
  assert.equal(p.complete, 8);
  for (let t = 5.1; t < 5.6; t += 0.05) step(p, t, t * 1000 + 900);
  assert.equal(p.shown, 8);
  assert.equal(shownText(p), 'PMAY-G houses in Meghalaya are 33,147 in total');
});

test('a cut keeps only the words heard; what the voice says next starts a new reading', () => {
  let p = newPacer();
  queue(p, 10);
  addText(p, words(30) + '.', 0);
  const n = step(p, 3, 3000);
  p = cut(p);
  assert.equal(p.words.length, n);
  assert.equal(p.shown, n);
  assert.equal(played(p, 99), 0, 'the old audio is gone');
  queue(p, 2, 50);
  addText(p, 'Okay, I stopped that.', 50000);
  assert.ok(shownText(p).startsWith(words(n)));
  for (let t = 50.05; t < 52.2; t += 0.05) step(p, t, t * 1000);
  assert.equal(shownText(p), words(n) + ' Okay, I stopped that.');
});

test('the reading is pending until the turn is over and every word is shown', () => {
  const p = newPacer();
  queue(p, 1);
  addText(p, 'One two.', 0);
  assert.equal(pending(p), true);
  for (let t = 1.1; t < 1.4; t += 0.05) step(p, t, t * 1000);
  assert.equal(p.shown, 2);
  assert.equal(pending(p), true, 'the turn is not over yet');
  finish(p, 1400);
  assert.equal(pending(p), false);
});

test('anchors are monotonic and limited to MAX_RATE when the text runs far ahead of the audio', () => {
  const p = newPacer();
  addText(p, words(9) + '.', 0);           // no audio yet
  addAudio(p, 0, 0.5);
  const [, t1] = p.anchors[1];
  assert.ok(t1 >= 9 / 4.5 - 1e-9, `9 words cannot end before ${9 / 4.5} s of audio, anchor ${t1}`);
  queue(p, 4, 0.5);
  addText(p, ' ' + words(3, 9) + '.', 10);
  assert.ok(p.anchors[2][1] >= p.anchors[1][1]);
});

test('a cut after every chunk had played keeps the words: they were heard (only the typing was behind)', () => {
  let p = newPacer();
  queue(p, 2);
  addText(p, words(20) + '.', 0);
  step(p, 2.5, 2500);
  assert.ok(p.shown < 20);
  p = cut(p, 2.5);
  assert.equal(p.words.length, 20);
});

// 2026-11-16, the user's live test on the sovereign engine: words of the holding line / the answer before leaked in
test('a reading after a break never glues its first word to the last one, and starts at the break', async () => {
  const P = await import('../src/chat/voice/captionPacer.js');
  const p = P.cut(P.newPacer('West Garo Hills has the most. That'), null);
  P.addText(p, 'One', 0); P.addText(p, ' moment,', 0); P.addText(p, ' sir.', 0);
  assert.equal(p.text, 'West Garo Hills has the most. That One moment, sir.');
  assert.equal(P.readingStart(p, p.complete), 7);
});

test('an answer that takes the stage mid-sentence starts after that sentence (the holding line stays its own)', async () => {
  const P = await import('../src/chat/voice/captionPacer.js');
  const p = P.newPacer();
  P.addText(p, 'One', 0); P.addText(p, ' moment,', 0);
  const at = p.complete;                                    // the answer took the stage here
  assert.equal(P.segmentStart(p, at), null);                // the holding line is still coming in
  P.addText(p, ' sir.', 0); P.addText(p, ' West', 0); P.addText(p, ' Garo', 0);
  assert.equal(P.segmentStart(p, at), 3);
  assert.deepEqual(p.words.slice(3), ['West', 'Garo']);
  // a turn's end is a break: a typed question's answer starts there even without a full stop
  const q = P.newPacer('All 12 districts are on your screen');
  P.markBreak(q);
  assert.equal(P.segmentStart(q, q.complete), q.complete);
});
