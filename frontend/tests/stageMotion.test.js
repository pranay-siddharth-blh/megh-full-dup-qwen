// The voice view's motion and layout math (2026-11-14 smoothness pass): the level written only in visible steps, the
// orb's parked place, a card's lean from a rect read once, and the sentences announced to a screen reader.
import test from 'node:test';
import assert from 'node:assert/strict';
import { leanVars, levelText, parkOffset, parkTransform, spokenSentences } from '../src/chat/voice/stageMotion.js';

test('the level is written in 0.02 steps, clamped to 0..1, so a tiny wobble is not a style change', () => {
  assert.equal(levelText(0), '0.00');
  assert.equal(levelText(0.361), '0.36');
  assert.equal(levelText(0.369), '0.36');
  assert.equal(levelText(0.371), '0.38');
  assert.equal(levelText(1.7), '1.00');
  assert.equal(levelText(-0.2), '0.00');
  assert.equal(levelText(NaN), '0.00');
  // values that round to the same text are the same write
  assert.equal(levelText(0.501), levelText(0.509));
});

test('the parked orb: 132 px at the top right on a desktop, its centre 94 px from the right and 150 px from the top', () => {
  const o = parkOffset({ cx: 960, cy: 300, w: 400, rootW: 1920 });
  assert.equal(o.scale, 0.33);
  assert.equal(960 + o.dx, 1920 - 28 - 66);
  assert.equal(300 + o.dy, 84 + 66);
  assert.equal(parkTransform(o), `translate(${o.dx}px, ${o.dy}px) scale(0.33)`);
});

test('the parked orb on a phone: a 40 px badge in the title row, 12 px from the edge', () => {
  const o = parkOffset({ cx: 195, cy: 250, w: 280, rootW: 390 });
  assert.equal(195 + o.dx, 390 - 12 - 20);
  assert.equal(250 + o.dy, 56 + 4 + 20);
  assert.equal(o.scale, +(40 / 280).toFixed(3));
  // the boundary: 600 is a phone, 601 is not
  assert.equal(parkOffset({ cx: 0, cy: 0, w: 100, rootW: 600 }).scale, 0.4);
  assert.equal(parkOffset({ cx: 0, cy: 0, w: 100, rootW: 601 }).scale, 1.32);
  // a zero-width box never divides by zero
  assert.ok(Number.isFinite(parkOffset({ cx: 0, cy: 0, w: 0, rootW: 1000 }).scale));
});

test('a card leans towards the pointer: centre = flat, corners = the full tilt, never more', () => {
  const r = { left: 100, top: 50, width: 400, height: 200 };
  assert.deepEqual(leanVars(300, 150, r), { mx: '50.0%', my: '50.0%', rx: '0.00deg', ry: '0.00deg' });
  const tl = leanVars(100, 50, r);
  assert.deepEqual([tl.mx, tl.my, tl.rx, tl.ry], ['0.0%', '0.0%', '3.00deg', '-3.50deg']);
  const br = leanVars(500, 250, r);
  assert.deepEqual([br.rx, br.ry], ['-3.00deg', '3.50deg']);
  // a pointer past the edge (the card moved under it while it leaned) is held at the edge
  assert.deepEqual(leanVars(900, 900, r), br);
  assert.equal(leanVars(0, 0, { left: 0, top: 0, width: 0, height: 0 }).mx, '0.0%');
});

test('the screen reader hears whole sentences: the one still being said waits for its end', () => {
  const t = 'MGNREGA leads with 9 crore person-days. PMAY-G sanctioned 1,71,107 houses in West';
  assert.deepEqual(spokenSentences(t, true), ['MGNREGA leads with 9 crore person-days.']);
  assert.deepEqual(spokenSentences(t, false), ['MGNREGA leads with 9 crore person-days.', 'PMAY-G sanctioned 1,71,107 houses in West']);
  // closing quotes and question marks end a sentence; extra spaces and line breaks collapse
  assert.deepEqual(spokenSentences('He said “yes.”  Is it  done?\nNo', true), ['He said “yes.”', 'Is it done?']);
  assert.deepEqual(spokenSentences('', true), []);
  assert.deepEqual(spokenSentences(null, false), []);
  // a number with a decimal point is not a sentence end
  assert.deepEqual(spokenSentences('It is ₹3,628.67 crore so far', true), []);
});
