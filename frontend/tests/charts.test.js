// E11 (2026-10-29): missing values, rankings and comparisons, on the real
// analytics.js / chartTheme.js. Run: npm test (node --test).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { asksRanking, buildAnalytics, compareVerdict, pivotStacked, toNumber } from '../src/chat/analytics.js';
import { insightFor, insightForSeries } from '../src/chat/chartTheme.js';

test('a missing value stays null, never 0', () => {
  assert.equal(toNumber(null), null);
  assert.equal(toNumber(''), null);
  assert.equal(toNumber('1,234'), 1234);
  assert.equal(toNumber(0), 0);
});

test('a year with no row is a gap in a two-way chart, not a 0', () => {
  const rows = [
    { district: 'A', financial_year: '2022-23', v: 5 },
    { district: 'A', financial_year: '2023-24', v: 7 },
    { district: 'B', financial_year: '2023-24', v: 3 },
  ];
  const { datasets } = pivotStacked(rows, 'financial_year', 'district', 'v');
  assert.deepEqual(datasets.find((d) => d.label === 'B').data, [null, 3]);
});

test('a NULL measure is charted as a gap', () => {
  const rows = [
    { financial_year: '2021-22', houses: 10 },
    { financial_year: '2022-23', houses: null },
    { financial_year: '2023-24', houses: 14 },
  ];
  const a = buildAnalytics('houses by year', rows, null);
  assert.equal(a.kind, 'multi');
  assert.deepEqual(a.charts[0].values, [10, null, 14]);
});

test('chart headlines skip gaps', () => {
  // The latest real value, not "Latest 0 in 2024-25".
  assert.equal(insightFor('line', ['2022-23', '2023-24', '2024-25'], [10, 20, null]), 'Latest 20 in 2023-24 · up 100% since 2022-23');
  assert.equal(insightForSeries(['2022-23', '2023-24'], [{ label: 'A', data: [1, null] }], true), 'Latest (2023-24): A —');
});

test('a ranking defaults to a bar, never a donut', () => {
  const rows = [{ district: 'A', houses: 50 }, { district: 'B', houses: 40 }, { district: 'C', houses: 30 }];
  assert.ok(asksRanking('Top 3 districts by houses completed'));
  assert.equal(buildAnalytics('Top 3 districts by houses completed', rows, null).defType, 'bar');
  // ... even when the backend hinted a donut
  assert.equal(buildAnalytics('Which district has the most houses?', rows, 'doughnut').defType, 'bar');
  // A plain breakdown of a few parts of a whole may still be a donut.
  assert.equal(buildAnalytics('Houses by district', rows, null).defType, 'doughnut');
  // An officer who names the pie still gets it.
  assert.equal(buildAnalytics('Top 3 districts as a pie chart', rows, null, 'pie').defType, 'pie');
});

test('a percentage is never a pie or donut', () => {
  const rows = [{ district: 'A', completion_pct: 80 }, { district: 'B', completion_pct: 60 }, { district: 'C', completion_pct: 70 }];
  const a = buildAnalytics('completion rate by district', rows, 'pie');
  assert.equal(a.defType, 'bar');
  assert.deepEqual(a.types, ['bar', 'line']);
});

test('two schemes are shown side by side but never ranked', () => {
  const rows = [{ scheme: 'MGNREGA', beneficiaries: 1494437 }, { scheme: 'PMAY-G', beneficiaries: 171107 }];
  const a = buildAnalytics('Compare beneficiaries in mgnrega and PMAY-G', rows, null);
  assert.equal(a.kind, 'compare');
  assert.equal(a.a.value, 1494437);
  assert.equal(a.b.value, 171107);
  assert.deepEqual(a.verdict, { unlike: true, measure: 'beneficiaries' });
});

test('two districts on one measure still get a verdict', () => {
  const rows = [{ district: 'East Khasi Hills', houses: 120 }, { district: 'West Garo Hills', houses: 100 }];
  const a = buildAnalytics('East Khasi Hills vs West Garo Hills houses', rows, null);
  assert.equal(a.verdict.lead, 'East Khasi Hills');
  assert.equal(a.verdict.pct, 20);
});

test('no verdict when a side has no value', () => {
  assert.equal(compareVerdict('A', 10, 'B', null, 'Houses'), null);
});
