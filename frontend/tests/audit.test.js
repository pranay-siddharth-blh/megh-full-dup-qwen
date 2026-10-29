// Chat UI audit 2026-10-29: each case runs the row shape the backend sends for
// that question through the real buildAnalytics / chartTheme. Run: npm test.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildAnalytics, pivotStacked } from '../src/chat/analytics.js';
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

// ── Phase 6: the measure kind decides chart and wording ──────────────────────
import { compareVerdict, askedMeasureCol } from '../src/chat/analytics.js';
import { fmtUnit, insightFor, verdictText } from '../src/chat/chartTheme.js';
import { formatCell, isLabelCol, isNumeric, unitOf } from '../src/chat/columns.js';

test('X-1: a ₹ lakh headline is in lakh / crore, not "1.2L"', () => {
  assert.equal(insightFor('bar', ['East Khasi Hills', 'Ri Bhoi'], [120000, 90000], { unit: 'lakh' }),
    'Highest: East Khasi Hills · ₹1,200 crore');
  const rows = ['A', 'B', 'C', 'D', 'E', 'F', 'G'].map((d, i) => ({ district: d, total_exp_lakh: [120000, 9000, 50, 70, 1, 2, 3][i] }));
  assert.equal(buildAnalytics('MGNREGA expenditure by district', rows, null).charts[0].axes.unit, 'lakh');
});

test('X-13 / X-14: small amounts are never 0; rupees get ₹ and lakh / crore', () => {
  assert.equal(formatCell(0.004, 'amount_crore'), '₹40,000');
  assert.equal(fmtUnit(0.004, 'crore'), '₹40,000');
  assert.equal(unitOf('amount sanctioned (Rs)'), 'rupees');
  assert.equal(fmtUnit(2222753000, 'rupees'), '₹222.28 crore');
});

test('D-2 / D-6: "(%)" with spaces, rates, shares and ratios are %; fractions read ×100', () => {
  assert.equal(unitOf('completion rate (%)'), 'pct');
  assert.equal(unitOf('women_share'), 'pct');
  assert.equal(unitOf('completion_ratio'), 'pct');
  assert.equal(unitOf('wage_rate'), null);                 // a wage rate is money
  const a = buildAnalytics('completion ratio by district', [{ district: 'A', completion_ratio: 0.753 },
    { district: 'B', completion_ratio: 0.5 }, { district: 'C', completion_ratio: 0.6 }], null);
  assert.deepEqual(a.charts[0].values, [75.3, 50, 60]);
});

test('D-9: a % trend headline is in points, matching the table', () => {
  assert.equal(insightFor('line', ['2022-23', '2023-24', '2024-25'], [50, 55, 60], { unit: 'pct' }),
    'Latest 60% in 2024-25 · up 10 points since 2022-23');
});

test('C-1: two years compared are a change from the earlier year', () => {
  const rows = [{ financial_year: '2024-25', expenditure: 930 }, { financial_year: '2023-24', expenditure: 1070 }];
  const a = buildAnalytics('Compare MGNREGA expenditure 2023-24 vs 2024-25', rows, null);
  assert.equal(a.kind, 'compare');
  assert.equal(verdictText(a.verdict), 'Fell 13% from 2023-24 to 2024-25 (−140) on expenditure.');
});

test('D-4: two percentages differ by points', () => {
  const v = compareVerdict('Ri Bhoi', 80, 'West Garo Hills', 60, 'completion %', false, { unit: 'pct' });
  assert.equal(verdictText(v), 'Ri Bhoi is 20 points ahead on completion %.');
});

test('D-5 / D-12: for pending works the lower side leads and the highest is a warning', () => {
  const v = compareVerdict('A', 900, 'B', 300, 'pending works', false, { lowerBetter: true });
  assert.equal(verdictText(v), 'B has 600 fewer pending works (lower is better).');
  const rows = [{ district: 'A', pending_works: 900 }, { district: 'B', pending_works: 300 }, { district: 'C', pending_works: 500 }];
  const a = buildAnalytics('Pending works by district', rows, null);
  assert.equal(a.charts[0].axes.lowerBetter, true);
  assert.equal(insightFor('bar', ['A', 'B', 'C'], [900, 300, 500], a.charts[0].axes),
    'Most pending works (lower is better): A · 900');
});

test('B-15: "difference" leads with the gap', () => {
  const rows = [{ district: 'East Khasi Hills', houses: 1494437 }, { district: 'Ri Bhoi', houses: 171107 }];
  const a = buildAnalytics('Difference between East Khasi Hills and Ri Bhoi houses', rows, null);
  assert.match(verdictText(a.verdict), /^The difference is 13,23,330 houses: East Khasi Hills has more/);
});

test('D-10 / D-11: tiles carry the unit; a missing side gives no verdict', () => {
  const rows = [{ district: 'Ri Bhoi', completion_pct: 80.5 }, { district: 'Tura', completion_pct: 60.25 }];
  assert.equal(buildAnalytics('Compare Ri Bhoi and Tura completion percentage', rows, null).unit, 'pct');
  const miss = [{ district: 'A', avg_days: 45 }, { district: 'B', avg_days: null }];
  assert.equal(buildAnalytics('Compare A and B average days', miss, null).verdict, null);
});

test('C-4 / C-10: month names are periods in financial-year order (Apr → Mar)', () => {
  const rows = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'].map((m, i) => ({ month_name: m, expenditure: 10 + i }));
  const a = buildAnalytics('Monthly expenditure in 2024-25', rows, null);
  assert.deepEqual(a.charts[0].labels, ['Apr', 'May', 'Jun', 'Jan', 'Feb', 'Mar']);
  assert.equal(a.defType, 'line');
});

test('C-8: a month number is a label, not a measure', () => {
  const rows = [4, 5, 6].map((m, i) => ({ month: m, month_name: ['Apr', 'May', 'Jun'][i], person_days: 100 + i }));
  const a = buildAnalytics('MGNREGA person days by month in 2024-25', rows, null);
  assert.equal(a.charts.length, 1);
  assert.match(a.charts[0].title, /^Person days by/);
});

test('C-9: quarters are time in order, never a donut', () => {
  const rows = ['Q3', 'Q1', 'Q4', 'Q2'].map((q, i) => ({ quarter: q, expenditure: 10 + i }));
  const a = buildAnalytics('MGNREGA expenditure by quarter in 2024-25', rows, null);
  assert.deepEqual(a.charts[0].labels, ['Q1', 'Q2', 'Q3', 'Q4']);
  assert.notEqual(a.defType, 'doughnut');
});

test('C-11: year series are drawn oldest first', () => {
  const rows = ['2024-25', '2022-23', '2023-24'].flatMap((fy) => ['A', 'B'].map((b) => ({ block: b, financial_year: fy, person_days: 5 })));
  const { datasets } = pivotStacked(rows, 'block', 'financial_year', 'person_days');
  assert.deepEqual(datasets.map((d) => d.label), ['2022-23', '2023-24', '2024-25']);
});

test('C-13: a year the scheme does not hold is a gap labelled "no data"', () => {
  const rows = [{ financial_year: '2021-22', amount: 10 }, { financial_year: '2022-23', amount: 12 }, { financial_year: '2024-25', amount: 40 }];
  const a = buildAnalytics('Focus Legacy amount disbursed each year', rows, null);
  assert.deepEqual(a.charts[0].labels, ['2021-22', '2022-23', '2023-24', '2024-25']);
  assert.deepEqual(a.charts[0].values, [10, 12, null, 40]);
  assert.equal(a.charts[0].fullLabels[2], '2023-24 (no data)');
});

test('C-15: a daily series headlines the total and the peak, not first-vs-last', () => {
  const labels = Array.from({ length: 30 }, (_, i) => '2023-04-' + String(i + 1).padStart(2, '0'));
  const values = labels.map((_, i) => (i === 9 ? 50 : 1));
  assert.equal(insightFor('line', labels, values), 'Total 79 · peak 50 on 2023-04-10');
});

test('C-16: titles read as words', () => {
  const rows = ['A', 'B'].flatMap((d) => ['2023-24', '2024-25'].map((fy) => ({ district_name: d, financial_year: fy, person_days: 5 })));
  const a = buildAnalytics('person days by district and year', rows, null);
  assert.equal(a.title, 'Person days by financial year and district');
});

test('I-10 / J-7: a "lowest" question is headlined "Lowest"', () => {
  const rows = [{ village: 'A', person_days: 5 }, { village: 'B', person_days: 2 }, { village: 'C', person_days: 9 }];
  const a = buildAnalytics('lowest 3 villages by person days', rows, null);
  assert.equal(insightFor('bar', a.charts[0].labels, a.charts[0].values, a.charts[0].axes), 'Lowest: B · 2');
});

test('X-6 / X-7 / X-12: N/A blanks, Indian grouping, label words only at the end', () => {
  const a = buildAnalytics('houses by district', [{ district: 'A', houses: 5 }, { district: 'B', houses: 'N/A' }, { district: 'C', houses: 7 }], null);
  assert.deepEqual(a.charts[0].values, [5, null, 7]);
  assert.ok(isNumeric('2,72,64,054'));
  assert.equal(isLabelCol('houses_per_year'), false);
  assert.equal(isLabelCol('person_days_this_year'), false);
  assert.equal(isLabelCol('beneficiary_key_count'), false);
  assert.equal(isLabelCol('year_key'), true);
  assert.equal(isLabelCol('district_code'), true);
});

test('B-10: "money per beneficiary" picks the per-head column', () => {
  assert.equal(askedMeasureCol('Money per beneficiary in MGNREGA vs PMAY-G',
    ['beneficiaries', 'amount_crore', 'rupees_per_beneficiary']), 'rupees_per_beneficiary');
});

// ── Phase 7: export, feedback ────────────────────────────────────────────────
import { sheetXml, tableSheet, tablesAsLines } from '../src/chat/exporters.js';
import { answerKey } from '../src/chat/format.js';

test('K-5: years and codes are text in Excel; quantities use Indian grouping', () => {
  const sh = tableSheet('Q1 table', [{ year_key: 2023, lgd_code: 263456, sanction_no: '1234567890123456789', person_days: 120000 }], '');
  assert.deepEqual(sh.textCols, [0, 1]);
  const xml = sheetXml(sh.header, sh.rows, sh.textCols, sh.title);
  assert.match(xml, /<t xml:space="preserve">2023<\/t>/);                  // text, never "2,023"
  assert.match(xml, /<t xml:space="preserve">263456<\/t>/);
  assert.match(xml, /<t xml:space="preserve">1234567890123456789<\/t>/);   // all 19 digits kept
  assert.match(xml, /<c r="D2" s="2"><v>120000<\/v><\/c>/);                // a number, Indian-grouped style
});

test('H-4 / H-10: screen headings and the scope on top of each table sheet', () => {
  const sh = tableSheet('Q2 table', [{ lgd_village_name: 'A', total_exp_lakh: 5 }], 'MGNREGA · East Khasi Hills · FY 2023-24');
  assert.deepEqual(sh.header, ['Village name', 'Total expenditure (₹ lakh)']);
  assert.equal(sh.title, 'Answered for: MGNREGA · East Khasi Hills · FY 2023-24');
  assert.match(sheetXml(sh.header, sh.rows, sh.textCols, sh.title), /<row r="1"><c r="A1" t="inlineStr" s="5">/);
});

test('H-12: a table in the answer text becomes lines in the Answer cell', () => {
  const text = 'Mawkynrew village:\n| Village | Block |\n|---|---|\n| Mawkynrew | Mawkynrew |';
  assert.equal(tablesAsLines(text), 'Mawkynrew village:\nVillage · Block\nMawkynrew · Mawkynrew');
});

test('K-4: a vote is keyed on the answer itself, the same live or reopened', () => {
  assert.equal(answerKey('Q2', 'answer two'), answerKey('Q2', 'answer two'));
  assert.notEqual(answerKey('Q2', 'answer two'), answerKey('Q3', 'answer three'));
});

test('E-5: places with no figure are left out of a ranking, and the note says how many', () => {
  const rows = [{ village: 'A', women_person_days: null }, { village: 'B', women_person_days: null },
    { village: 'C', women_person_days: 900 }, { village: 'D', women_person_days: 800 }];
  const a = buildAnalytics('Top 4 villages by women person days in 2025-26', rows, null);
  assert.deepEqual(a.charts[0].labels, ['C', 'D']);
  assert.match(a.note, /^2 of 4 have no figure/);
  const none = buildAnalytics('Top 2 villages by women person days', rows.slice(0, 2), null);
  assert.equal(none.kind, 'table');
  assert.match(none.note, /nothing to rank/);
});

test('E-6: a ranking charts its ranking measure only', () => {
  const rows = ['A', 'B', 'C'].map((b, i) => ({ block: b, person_days: 900 - i * 100, households: 50 + i * 30, expenditure_lakh: 5 + i }));
  const a = buildAnalytics('Top 3 blocks by MGNREGA person days, with households and expenditure', rows, null);
  assert.equal(a.charts.length, 1);
  assert.match(a.charts[0].title, /^Person days by block/);
});

test('X-2: 300 villages draw the top 15 with a note', () => {
  const rows = Array.from({ length: 300 }, (_, i) => ({ village: `V${i}`, person_days: i }));
  const a = buildAnalytics('Person days by village', rows, null);
  assert.equal(a.charts[0].labels.length, 15);
  assert.equal(a.charts[0].labels[0], 'V299');
  assert.equal(a.note, 'Top 15 of 300 shown; the full list is in the table.');
  assert.equal(a.data.length, 300);                    // the table keeps every row
});

test('X-3: one row with figures in different units is a record card, not one axis', () => {
  const row = [{ person_days: 120000, total_exp_lakh: 900, households_employed: 4000 }];
  assert.equal(buildAnalytics('MGNREGA summary for Ri Bhoi', row, 'kpi_bar').kind, 'record');
  const same = [{ wage_exp_lakh: 600, material_exp_lakh: 300 }];
  assert.equal(buildAnalytics('wages vs material', same, 'kpi_bar').kind, 'kpi');
});
