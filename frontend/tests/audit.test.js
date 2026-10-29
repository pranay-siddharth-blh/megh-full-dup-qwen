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

// ── Phase 3 / 4: overlap-aware totals and the scheme guard ───────────────────
import { canAdd, dimOf, measureKind } from '../src/chat/columns.js';

// cross_figures._rows for "Compare MGNREGA and PMAY-G villages" (one row per scheme)
const VILLAGES_BY_SCHEME = [
  { scheme: 'MGNREGA', villages: 5000 }, { scheme: 'PMAY-G', villages: 6000 }, { scheme: 'Focus Plus', villages: 2500 },
];

test('G-1 / G-2 / B-2: villages by scheme are bars, never a donut with "Total 13,500"', () => {
  const a = buildAnalytics('Villages covered by each scheme', VILLAGES_BY_SCHEME, null);
  assert.equal(a.kind, 'multi');
  assert.equal(a.defType, 'bar');
  assert.deepEqual(a.types, ['bar']);
  // asked as a donut afterwards: refused, with a note
  const d = buildAnalytics('Compare MGNREGA and PMAY-G villages in a donut chart', VILLAGES_BY_SCHEME, null, 'doughnut');
  assert.equal(d.defType, 'bar');
  assert.equal(d.refused, 'doughnut');
  assert.match(d.note, /schemes count and spend different things/);
});

test('B-12: money across schemes is bars, never "% of the total"', () => {
  const rows = [{ scheme: 'MGNREGA', amount_crore: 1050 }, { scheme: 'PMAY-G', amount_crore: 120 },
    { scheme: 'Focus Plus', amount_crore: 40 }];
  const a = buildAnalytics('Compare MGNREGA, PMAY-G and Focus Plus spending', rows, null);
  assert.equal(a.defType, 'bar');
  assert.deepEqual(a.types, ['bar']);
});

test('G-13 / G-5: villages by year are never a donut (the same villages repeat each year)', () => {
  const rows = [{ financial_year: '2023-24', villages: 4000 }, { financial_year: '2024-25', villages: 4100 }];
  const a = buildAnalytics('Villages with MGNREGA work each year as a donut', [...rows, { financial_year: '2025-26', villages: 3900 }], null, 'doughnut');
  assert.equal(a.refused, 'doughnut');
  assert.match(a.note, /counted again in each year or scheme/);
});

test('a flow by district may still be a donut (each rupee is spent in one district)', () => {
  const rows = [{ district: 'A', amount_crore: 10 }, { district: 'B', amount_crore: 20 }, { district: 'C', amount_crore: 5 }];
  assert.equal(buildAnalytics('Expenditure by district', rows, null).defType, 'doughnut');
});

// c13 _chart_hint said "stacked" for any 2-label / 1-measure result
const SCHEME_YEAR = [
  { financial_year: '2022-23', scheme: 'MGNREGA', beneficiaries: 563127 },
  { financial_year: '2022-23', scheme: 'PMAY-G', beneficiaries: 23109 },
  { financial_year: '2023-24', scheme: 'MGNREGA', beneficiaries: 530969 },
  { financial_year: '2023-24', scheme: 'PMAY-G', beneficiaries: 17240 },
];

test('A-4: schemes are never stacked or totalled — grouped bars, year on the x-axis', () => {
  const a = buildAnalytics('Compare MGNREGA and PMAY-G beneficiaries for last 3 years', SCHEME_YEAR, 'stacked');
  assert.equal(a.kind, 'twoDim');
  assert.equal(a.xKey, 'financial_year');
  assert.equal(a.sKey, 'scheme');
  assert.ok(!a.types.includes('stacked') && !a.types.includes('doughnut'));
  assert.notEqual(a.defType, 'stacked');
  assert.equal(canAdd('beneficiaries', dimOf('scheme', SCHEME_YEAR)), false);   // the pivot has no Total column
});

test('A-5: "side by side" (grouped_bar, one measure) keeps both labels', () => {
  const a = buildAnalytics('Compare MGNREGA and PMAY-G side by side for last 3 years', SCHEME_YEAR, 'grouped_bar');
  assert.equal(a.kind, 'twoDim');
  assert.deepEqual(a.labels, ['2022-23', '2023-24']);
  assert.deepEqual(a.datasets.map((d) => d.label), ['MGNREGA', 'PMAY-G']);
});

test('A-7: a pie of schemes × years is refused and drawn as bars', () => {
  const a = buildAnalytics('MGNREGA and PMAY-G beneficiaries each year as a pie chart', SCHEME_YEAR, null, 'pie');
  assert.equal(a.kind, 'twoDim');
  assert.equal(a.defType, 'bar');
  assert.equal(a.refused, 'pie');
});

test('B-3: scheme × district puts districts on the x-axis and offers no stack or donut', () => {
  const rows = ['A', 'B', 'C'].flatMap((d, i) => [
    { district: d, scheme: 'MGNREGA', beneficiaries: 100 + i }, { district: d, scheme: 'PMAY-G', beneficiaries: 10 + i }]);
  const a = buildAnalytics('Beneficiaries district wise in all schemes', rows, 'stacked');
  assert.equal(a.xKey, 'district');
  assert.equal(a.sKey, 'scheme');
  assert.deepEqual(a.types, ['bar']);
});

test('G-3 / G-4: totals down districts only, never across years for villages', () => {
  const rows = [{ district: 'A', year_key: 2023, villages: 10 }];
  assert.equal(canAdd('villages', dimOf('district', rows)), true);       // the Total row down the districts
  assert.equal(canAdd('villages', dimOf('financial_year', rows)), false); // no Total across years
  assert.equal(canAdd('person_days', dimOf('financial_year', rows)), true);
  const g4 = [2023, 2024].flatMap((y) => ['A', 'B'].map((d, i) => ({ district: d, financial_year: `${y}-${(y + 1) % 100}`, households: 5 + i })));
  // backend rows put district first: the old 'stacked' card added the years on top
  // of each district's bar. Now the year is the x-axis; a stack, if chosen, adds
  // districts within one year, which is right.
  const a = buildAnalytics('Households with work by district and year', g4, 'stacked');
  assert.equal(a.kind, 'twoDim');
  assert.equal(a.xKey, 'financial_year');
  assert.equal(a.sKey, 'district');
});

test('D-1 / X-5 / D-8: rates and negative values are never slices', () => {
  const pct = [{ district: 'Ri Bhoi', 'completion rate (%)': 81.25 }, { district: 'Tura', 'completion rate (%)': 60 },
    { district: 'Jowai', 'completion rate (%)': 74 }];
  assert.equal(measureKind('completion rate (%)'), 'rate');
  assert.equal(buildAnalytics('PMAY-G completion rate by district', pct, null).defType, 'bar');
  const growth = [{ district: 'A', growth: -5 }, { district: 'B', growth: 10 }, { district: 'C', growth: 3 }];
  assert.equal(buildAnalytics('Growth in person days by district', growth, null).defType, 'bar');
  const neg = [{ district: 'A', net_amount: -5 }, { district: 'B', net_amount: 10 }, { district: 'C', net_amount: 3 }];
  assert.equal(buildAnalytics('Net amount by district', neg, null).defType, 'bar');
});

// ── Phase 5: never drop a label; dependent labels are details ────────────────
import { splitLabels } from '../src/chat/analytics.js';
import { withoutTwins } from '../src/chat/columns.js';

test('C-2: a label with one value goes in the title, not a one-item legend', () => {
  const rows = ['2022-23', '2023-24', '2024-25'].map((fy, i) => ({ district: 'East Khasi Hills', financial_year: fy, person_days: 50 + i }));
  const a = buildAnalytics('Person days in East Khasi Hills, 2022-23 to 2024-25', rows, 'stacked');
  assert.equal(a.kind, 'multi');
  assert.match(a.charts[0].title, /in East Khasi Hills$/);
  assert.deepEqual(a.charts[0].labels, ['2022-23', '2023-24', '2024-25']);
});

test('E-1: a block\'s district is a detail, not a series of mostly-empty bars', () => {
  // model SQL for "Top 5 blocks by expenditure" returns the district beside the block
  const rows = [
    { block_name: 'MYLLIEM', district_name: 'EAST KHASI HILLS', total_exp_lakh: 900 },
    { block_name: 'UMLING', district_name: 'RI BHOI', total_exp_lakh: 800 },
    { block_name: 'MAWRYNGKNENG', district_name: 'EAST KHASI HILLS', total_exp_lakh: 700 },
    { block_name: 'TIKRIKILLA', district_name: 'WEST GARO HILLS', total_exp_lakh: 650 },
    { block_name: 'JIRANG', district_name: 'RI BHOI', total_exp_lakh: 600 },
  ];
  const a = buildAnalytics('Top 5 blocks by expenditure', rows, null);
  assert.equal(a.kind, 'multi');
  assert.deepEqual(a.charts[0].labels.slice(0, 2), ['MYLLIEM', 'UMLING']);
  assert.equal(a.charts[0].fullLabels[1], 'UMLING (RI BHOI)');
  assert.equal(a.defType, 'bar');
  assert.deepEqual(splitLabels(rows, ['block_name', 'district_name']).details, ['district_name']);
});

test('J-6: top villages in one block are a ranked list, the block in the title', () => {
  // real SQL MG-07: village_name, block_name, person_days
  const rows = [{ village_name: 'A', block_name: 'UMLING', person_days: 900 }, { village_name: 'B', block_name: 'UMLING', person_days: 800 },
    { village_name: 'C', block_name: 'UMLING', person_days: 700 }];
  const a = buildAnalytics('Top 3 villages in Umling block by person days', rows, null);
  assert.equal(a.kind, 'multi');
  assert.equal(a.defType, 'bar');
  assert.match(a.charts[0].title, /in UMLING$/);
});

test('E-7: villages with the same name are told apart by their block', () => {
  const rows = [{ village_name: 'Mawlai', block_name: 'MYLLIEM', person_days: 900 },
    { village_name: 'Mawlai', block_name: 'MAWPHLANG', person_days: 850 }, { village_name: 'Laitumkhrah', block_name: 'MYLLIEM', person_days: 800 }];
  const a = buildAnalytics('Top 3 villages by person days in East Khasi Hills', rows, null);
  assert.deepEqual(a.charts[0].labels.slice(0, 2), ['Mawlai (MYLLIEM)', 'Mawlai (MAWPHLANG)']);
});

test('I-8: each scheme\'s own top list is one ranked chart per scheme, not a union', () => {
  // merged per-scheme rows (c13), after the backend unified the place column
  const rows = [
    { district: 'West Garo Hills', scheme: 'MGNREGA', beneficiaries: 261221 }, { district: 'East Khasi Hills', scheme: 'MGNREGA', beneficiaries: 190000 },
    { district: 'East Khasi Hills', scheme: 'PMAY-G', beneficiaries: 40000 }, { district: 'Ri Bhoi', scheme: 'PMAY-G', beneficiaries: 33147 },
  ];
  const a = buildAnalytics('Top 2 districts in MGNREGA and PMAY-G', rows, 'stacked');
  assert.equal(a.kind, 'multi');
  assert.equal(a.perScheme, true);
  assert.deepEqual(a.charts.map((c) => c.labels), [['West Garo Hills', 'East Khasi Hills'], ['East Khasi Hills', 'Ri Bhoi']]);
  assert.deepEqual(a.data[0], { rank: 1, 'MGNREGA district': 'West Garo Hills', 'MGNREGA beneficiaries': 261221,
    'PMAY-G district': 'East Khasi Hills', 'PMAY-G beneficiaries': 40000 });
});

test('I-8: cross_figures per-scheme ranking rows (rank column) likewise', () => {
  const rows = [
    { rank: 1, district: 'South Garo Hills', scheme: 'MGNREGA', beneficiaries: 50000 }, { rank: 2, district: 'Ri Bhoi', scheme: 'MGNREGA', beneficiaries: 112602 },
    { rank: 1, district: 'South Garo Hills', scheme: 'PMAY-G', beneficiaries: 9000 }, { rank: 2, district: 'East Jaintia Hills', scheme: 'PMAY-G', beneficiaries: 12000 },
  ];
  const a = buildAnalytics('bottom 2 districts by beneficiaries in MGNREGA and PMAY-G', rows, null);
  assert.equal(a.perScheme, true);
  assert.equal(a.charts.length, 2);
});

test('E-2: a rank column is never hidden as a twin of the names', () => {
  const rows = [{ rank: 1, district: 'A', v: 9 }, { rank: 2, district: 'B', v: 8 }];
  assert.deepEqual(Object.keys(withoutTwins(rows)[0]), ['rank', 'district', 'v']);
});

test('C-3: month and year — months on the x-axis, years as the series', () => {
  const rows = ['2023-24', '2024-25'].flatMap((fy) => ['Apr', 'May', 'Jun'].map((m, i) => ({ financial_year: fy, month_name: m, expenditure: 10 + i })));
  const a = buildAnalytics('Month-wise expenditure for 2023-24 and 2024-25', rows, null);
  assert.equal(a.kind, 'twoDim');
  assert.equal(a.xKey, 'month_name');
  assert.equal(a.sKey, 'financial_year');
});

test('G-9: two scheme tiles carry what each figure is (from the answer\'s measure notes)', () => {
  const rows = [{ scheme: 'MGNREGA', beneficiaries: 1494437 }, { scheme: 'PMAY-G', beneficiaries: 171107 }];
  const a = buildAnalytics('Compare beneficiaries in MGNREGA and PMAY-G', rows, null);
  assert.equal(a.kind, 'compare');
  assert.equal(a.vKey, 'beneficiaries');   // Messages.jsx looks up response.measure_notes[scheme][vKey]
});
