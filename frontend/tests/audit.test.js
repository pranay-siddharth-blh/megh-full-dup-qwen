// Chat UI audit 2026-10-29: each case runs the row shape the backend sends for
// that question through the real buildAnalytics / chartTheme. Run: npm test.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildAnalytics } from '../src/chat/analytics.js';
import { insightForSeries } from '../src/chat/chartTheme.js';
import { fyLabel, unifyPeriods } from '../src/chat/columns.js';

// ── Phase 2: one shape for scheme × year rows ─────────────────────────────────

// A-1: the per-scheme merge (c13 _data_per_scheme_rows) as it came before the
// backend renamed the year: MGNREGA's query names its year year_key, PMAY-G's
// financial_year_short; the merge adds `scheme`.
const MERGED_A1 = [
  { year_key: 2022, total_expenditure: 1050, scheme: 'MGNREGA' },
  { year_key: 2023, total_expenditure: 990, scheme: 'MGNREGA' },
  { year_key: 2024, total_expenditure: 870, scheme: 'MGNREGA' },
  { financial_year_short: '2022-23', total_expenditure: 120, scheme: 'PMAY-G' },
  { financial_year_short: '2023-24', total_expenditure: 140, scheme: 'PMAY-G' },
];

test('A-1: scheme × year rows with differently named year columns keep the year', () => {
  const a = buildAnalytics('Compare MGNREGA and PMAY-G expenditure in 2022-23, 2023-24 and 2024-25', MERGED_A1, null);
  assert.equal(a.kind, 'twoDim');
  assert.equal(a.xKey, 'financial_year');
  assert.equal(a.sKey, 'scheme');
  assert.deepEqual(a.labels, ['2022-23', '2023-24', '2024-25']);
  assert.deepEqual(a.datasets.map((d) => d.label), ['MGNREGA', 'PMAY-G']);
  assert.deepEqual(a.datasets[1].data, [120, 140, null]);      // PMAY-G holds no 2024-25: a gap, not 0
});

test('A-1: the year columns fold into one financial_year', () => {
  const rows = unifyPeriods(MERGED_A1);
  assert.deepEqual(rows[0], { financial_year: '2022-23', total_expenditure: 1050, scheme: 'MGNREGA' });
  assert.deepEqual(rows[3], { financial_year: '2022-23', total_expenditure: 120, scheme: 'PMAY-G' });
});

test('A-2: answer_many rows (one financial_year, one measure column) draw both schemes per year', () => {
  // conversation_layer.answer_many after the fix
  const rows = [
    { scheme: 'MGNREGA', financial_year: '2022-23', beneficiaries: 563127 },
    { scheme: 'MGNREGA', financial_year: '2023-24', beneficiaries: 530969 },
    { scheme: 'PMAY-G', financial_year: '2022-23', beneficiaries: 23109 },
    { scheme: 'PMAY-G', financial_year: '2023-24', beneficiaries: 17240 },
  ];
  const a = buildAnalytics('Beneficiaries of MGNREGA and PMAY-G year wise', rows, null);
  assert.equal(a.kind, 'twoDim');
  assert.deepEqual(a.labels, ['2022-23', '2023-24']);
  assert.deepEqual(a.datasets.map((d) => d.data), [[563127, 530969], [23109, 17240]]);
});

test('A-8: a lone year_key reads as a financial year', () => {
  const rows = [{ year_key: 2022, person_days: 50 }, { year_key: 2023, person_days: 60 }, { year_key: 2024, person_days: 55 }];
  const a = buildAnalytics('MGNREGA person days by year', rows, null);
  assert.deepEqual(a.charts[0].labels, ['2022-23', '2023-24', '2024-25']);
  assert.equal(a.charts[0].axes.x, 'Financial year');
  assert.equal(fyLabel(2023), '2023-24');
  assert.equal(fyLabel('2023-2024'), '2023-24');
  assert.equal(fyLabel('FY 2023-24'), '2023-24');
  assert.equal(fyLabel('East Khasi Hills'), null);
});

test('A-13: each scheme is headlined at its own latest year, never "PMAY-G 0"', () => {
  const labels = ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26'];
  const datasets = [
    { label: 'MGNREGA', data: [null, 563127, 530969, 510000, 498000] },
    { label: 'PMAY-G', data: [21000, 23109, 17240, null, null] },
  ];
  assert.equal(insightForSeries(labels, datasets, true), 'Latest: MGNREGA 5L (2025-26) · PMAY-G 17,240 (2023-24)');
});
