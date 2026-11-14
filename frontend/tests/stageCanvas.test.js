// The voice stage's canvas cards (src/chat/voice/stageCanvas.js): the pure helpers and the reveal / state contract the
// React layer drives. Pure logic only, no browser: a stub canvas, no animation frames.
// Run: node --test src/chat/voice/stageCanvas.test.js   (the repo has no vitest; node:test is its runner)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GROW, TILE_MAX, createStageCard, fitSize, fitText, grow, nice, niceAxis, rampColor, splitUnit, staggerFor, tileGrid, wrapText } from '../src/chat/voice/stageCanvas.js';

// a 2D context that accepts every call; text is 6 px per character at 12 px
function stubCtx() {
  const ctx = { font: '12px x' };
  ctx.measureText = (s) => ({ width: String(s).length * 6 * (parseFloat(String(ctx.font).split('px')[0].split(' ').pop()) / 12 || 1) });
  return new Proxy(ctx, { get: (t, k) => (k in t ? t[k] : () => ({ addColorStop() {} })), set: (t, k, v) => { t[k] = v; return true; } });
}
const stubCanvas = () => ({ width: 300, height: 150, getContext: () => stubCtx() });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const fmt = (v) => String(v);

test('GROW keeps Mitra\'s timings', () => {
  assert.deepEqual(GROW, { bars: 2000, race: 1600, line: 1300, donut: 1500, map: 1400, kpi: 1500, tiles: 1100 });
});

test('nice ticks: Mitra\'s steps; niceAxis keeps the tightest of 3-5 ticks', () => {
  assert.deepEqual(nice(80, 4), { top: 80, step: 20 });
  assert.deepEqual(nice(0), { top: 4, step: 1 });
  const a = niceAxis(7830);
  assert.equal(a.top, 8000); assert.equal(a.step, 2000); assert.equal(a.ticks, 4);
  assert.ok(niceAxis(59.3e5).top <= 7.5e6);
});

test('flush stagger: never more than 1.6 s for the rest', () => {
  assert.equal(staggerFor(260, 3), 260);
  assert.equal(staggerFor(260, 12), 1600 / 12);
  assert.equal(staggerFor(260, 0), 260);
});

test('count-up: a whole number stays whole, else 2 dp', () => {
  assert.equal(grow(1204, 0.5), 602);
  assert.equal(grow(254.75, 0.5), 127.38);
  assert.equal(grow(7, 1), 7);
});

test('the purple ramp runs from #F4ECFB to #4A2380', () => {
  assert.equal(rampColor(0), 'rgb(244,236,251)');
  assert.equal(rampColor(1), 'rgb(74,35,128)');
  assert.equal(rampColor(Number.NaN), 'rgb(244,236,251)');
});

test('tiles share the canvas sensibly', () => {
  assert.equal(tileGrid(1, 560, 320).cols, 1);
  assert.equal(tileGrid(6, 560, 320).cols, 3);
  assert.equal(tileGrid(6, 360, 300).cols, 2);
  const g = tileGrid(8, 900, 320);
  assert.ok(g.cols * g.rows >= 8 && g.tw >= 104);
});

test('labels are cut with an ellipsis; figures shrink, never cut', () => {
  const ctx = stubCtx();
  const t = fitText(ctx, 'South West Khasi Hills', 60, 12, 600);
  assert.ok(t.endsWith('…') && ctx.measureText(t).width <= 60);
  assert.equal(fitText(ctx, 'Ri Bhoi', 200, 12, 600), 'Ri Bhoi');
  assert.ok(fitSize(ctx, '5,48,96,160', 60, 30, 800, 6) < 30);
});

test('items start hidden; reveal(key) grows one, once; unknown keys are ignored', () => {
  const h = createStageCard(stubCanvas(), { kind: 'bars', fmt, items: [{ key: 'a', label: 'A', value: 3 }, { key: 'b', label: 'B', value: null }] });
  assert.deepEqual(h.state().items.map((i) => i.on), [false, false]);
  assert.equal(h.reveal('a'), true);
  assert.equal(h.reveal('a'), false);
  assert.equal(h.reveal('zzz'), false);
  const s = h.state();
  assert.equal(s.kind, 'bars');
  assert.deepEqual(s.items.map((i) => i.on), [true, false]);
  assert.ok(s.items[0].p >= 0 && s.items[0].p <= 1);
  h.destroy();
});

test('revealAll staggers the rest and reports how many', async () => {
  const items = Array.from({ length: 5 }, (_, i) => ({ key: `k${i}`, label: `K${i}`, value: i + 1 }));
  const h = createStageCard(stubCanvas(), { kind: 'race', fmt, items });
  h.reveal('k2');
  assert.equal(h.revealAll(40), 4);
  assert.equal(h.state().items.filter((i) => i.on).length, 2);   // the first of the rest at once
  await wait(200);
  assert.ok(h.state().items.every((i) => i.on));
  h.destroy();
});

test('a line reveals every point up to the named x, for all series', () => {
  const h = createStageCard(stubCanvas(), { kind: 'line', fmt, x: ['Apr', 'May', 'Jun', 'Jul'],
    series: [{ key: 'm', name: 'M', values: [1, null, 3, 4] }, { key: 'p', name: 'P', values: [2, 2, null, 5] }] });
  assert.equal(h.reveal('Jun'), true);
  assert.deepEqual(h.state().items.map((i) => [i.key, i.on]), [['Apr', true], ['May', true], ['Jun', true], ['Jul', false]]);
  assert.equal(h.reveal('May'), false);
  h.destroy();
});

test('reduced motion: everything is drawn final', () => {
  const h = createStageCard(stubCanvas(), { kind: 'tiles', fmt, items: [{ key: 'a', label: 'A', value: 1 }, { key: 'b', label: 'B', value: 2 }] }, { reduced: true });
  assert.deepEqual(h.state().items.map((i) => [i.on, i.p]), [[true, 1], [true, 1]]);
  assert.equal(h.reveal('a'), false);
  assert.equal(h.revealAll(), 0);
  h.destroy();
});

// 2026-11-14: the cap was eight when there were six schemes; it is TILE_MAX (12) so every scheme keeps its tile
test('kpi keeps one item, tiles at most TILE_MAX (12); destroy stops pending reveals', async () => {
  const many = Array.from({ length: 14 }, (_, i) => ({ key: `t${i}`, label: `T${i}`, value: i }));
  assert.equal(createStageCard(stubCanvas(), { kind: 'kpi', fmt, items: many }).state().items.length, 1);
  const h = createStageCard(stubCanvas(), { kind: 'tiles', fmt, items: many });
  assert.equal(TILE_MAX, 12);
  assert.equal(h.state().items.length, TILE_MAX);
  h.revealAll(100); h.destroy();
  await wait(250);
  assert.equal(h.state().items.filter((i) => i.on).length, 1);
});

// 2026-11-14: a tile says what it counts on up to two lines, broken between words, never inside one
test('wrapText breaks between words, keeps whole words, ends an overflow on a word and an ellipsis', () => {
  const ctx = stubCtx();   // 6 px a character at 12 px
  assert.deepEqual(wrapText(ctx, 'households given work', 200, 12, 600, 2), ['households given work']);
  const two = wrapText(ctx, 'households given work, counted once per year', 100, 12, 600, 2);
  assert.equal(two.length, 2);
  two.forEach((l) => assert.ok(ctx.measureText(l).width <= 100, l));
  assert.equal(two[0], 'households given');
  assert.ok(two[1].endsWith('…') && !two[1].includes('once per year'));
  ['households', 'given', 'work,'].forEach((w) => assert.ok(two.join(' ').includes(w.slice(0, 4))));
  // every line is made of whole words of the text (the last may carry the ellipsis)
  const words = 'households given work, counted once per year'.split(' ');
  two.forEach((l) => l.split(' ').forEach((w) => assert.ok(words.includes(w.replace('…', '')), w)));
  assert.deepEqual(wrapText(ctx, '', 100), []);
  assert.equal(wrapText(ctx, 'supercalifragilistic', 60, 12, 600, 2)[0].endsWith('…'), true);
});

test('splitUnit sets the unit word apart from the number, and leaves a count alone', () => {
  assert.deepEqual(splitUnit('₹3,628.67 crore'), ['₹3,628.67', 'crore']);
  assert.deepEqual(splitUnit('₹82.9 lakh'), ['₹82.9', 'lakh']);
  assert.deepEqual(splitUnit('14,94,437'), ['14,94,437', '']);
});

test('a figure tile shows its own unit (the planner item format), the card format otherwise', () => {
  const h = createStageCard(stubCanvas(), { kind: 'tiles', fmt, items: [
    { key: 'a', label: 'MGNREGA', value: 3628.67, fmt: (v) => `₹${v} crore`, sub: 'money spent' },
    { key: 'b', label: 'Homestay', value: 1297, sub: 'applications' }] });
  assert.deepEqual(h.state().items.map((i) => i.shown), ['₹3628.67 crore', '1297']);
  h.destroy();
});
