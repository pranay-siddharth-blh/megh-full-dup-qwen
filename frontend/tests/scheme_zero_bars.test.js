// A scheme the answer covered but the rows hold no figure for is drawn as 0 on a chart
// of schemes (user 2026-11-04: "How much total amount has been disbursed under Focus+,
// FOCUS, and CM-ELEVATE?" drew two bars under a "3 schemes" heading — CM Elevate
// records no money). Only there: tiles, tables and year lines keep E11's "no value".
// On the real viewPlan() (analytics.js), which components/Messages.jsx renders.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { viewPlan, withAllSchemes } from '../src/chat/analytics.js';

const Q = 'How much total amount has been disbursed under Focus+, FOCUS, and CM-ELEVATE?';
const ROWS = [{ scheme: 'Focus Plus', amount_crore: 119.74 }, { scheme: 'Focus Legacy', amount_crore: 51.01 }];
const SCHEMES = ['Focus Plus', 'Focus Legacy', 'CM Elevate'];

test('the user report: CM Elevate is a 0 bar beside the two schemes with money', () => {
  const plan = viewPlan(Q, { data: ROWS, chart_type: null, schemes: SCHEMES });
  assert.equal(plan.mode, 'compare');
  const c = plan.charts[0];
  assert.deepEqual(c.labels, ['Focus Plus', 'Focus Legacy', 'CM Elevate']);
  assert.deepEqual(c.values, [119.74, 51.01, 0]);
});

test('the tiles and the table keep the rows as they are (E11: no "X vs 0" tiles)', () => {
  const plan = viewPlan(Q, { data: ROWS, chart_type: null, schemes: SCHEMES });
  assert.equal(plan.a.a.value, 119.74);
  assert.equal(plan.a.b.value, 51.01);
  assert.deepEqual(plan.a.data, ROWS);
});

test('nothing changes when every scheme has a figure, or one scheme was asked', () => {
  const full = viewPlan(Q, { data: ROWS, chart_type: null, schemes: ['Focus Plus', 'Focus Legacy'] });
  assert.deepEqual(full.charts[0].values, [119.74, 51.01]);
  const one = { kind: 'multi', charts: [{ labels: ['Focus Plus'], values: [1] }] };
  assert.equal(withAllSchemes(one, ['Focus Plus']), one);
});

test('a chart of districts, years or several series is never given scheme bars', () => {
  const byDistrict = { kind: 'multi', charts: [{ labels: ['EAST KHASI HILLS', 'RI BHOI'], values: [5, 7] }] };
  assert.deepEqual(withAllSchemes(byDistrict, SCHEMES).charts[0].labels, ['EAST KHASI HILLS', 'RI BHOI']);
  const years = { kind: 'multi', charts: [{ labels: ['2022-23', '2023-24'], values: [5, null] }] };
  assert.deepEqual(withAllSchemes(years, SCHEMES).charts[0].values, [5, null]);
  const series = { kind: 'multi', charts: [{ labels: ['Focus Plus'], values: [1], datasets: [{ label: 'x', data: [1] }] }] };
  assert.deepEqual(withAllSchemes(series, SCHEMES).charts[0].labels, ['Focus Plus']);
});

test('no rows, no charts, no schemes: unchanged', () => {
  assert.equal(withAllSchemes(null, SCHEMES), null);
  const rec = { kind: 'record', row: { a: 1 } };
  assert.equal(withAllSchemes(rec, SCHEMES), rec);
  const c = { kind: 'compare', charts: [{ labels: ['Focus Plus', 'Focus Legacy'], values: [1, 2] }] };
  assert.equal(withAllSchemes(c, undefined), c);
});
