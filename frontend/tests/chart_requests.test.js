// Chart requests (user 2026-10-30): "whatever chart the user asks, give it — a bar
// when bar is asked, a pie when pie is asked, a line when line is asked; a compare
// question gets a graph by default; when a question has no chart, generate one."
// On the real viewPlan() (analytics.js), which components/Messages.jsx renders.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { chartPreference, viewOnlyRequest, viewPlan } from '../src/chat/analytics.js';

const R = (data, chart_type = null, extra = {}) => ({ data, chart_type, ...extra });
const types = (plan) => plan.charts.map((c) => c.types);

/** A chart is drawn, and when a type was named every chart is that type only. */
function drawn(plan, want = null) {
  assert.ok(plan && plan.charts.length > 0, `no chart drawn (${plan && plan.mode})`);
  if (!want) return;
  for (const c of plan.charts) {
    assert.deepEqual(c.types, [want], `types ${JSON.stringify(types(plan))}`);
    assert.equal(c.initial, want);
  }
}

const SCHEMES = [
  { scheme: 'MGNREGA', beneficiaries: 1494437, amount_crore: 1066.7 },
  { scheme: 'PMAY-G', beneficiaries: 152000, amount_crore: 1800.2 },
];
const TWO_DISTRICTS = [
  { district_name: 'EAST KHASI HILLS', person_days: 5000000 },
  { district_name: 'WEST GARO HILLS', person_days: 4200000 },
];
const TWO_YEARS = [
  { financial_year: '2023-24', houses_completed: 12000 },
  { financial_year: '2024-25', houses_completed: 10400 },
];
const DISTRICTS = ['EAST KHASI HILLS', 'WEST GARO HILLS', 'RI BHOI', 'EAST GARO HILLS', 'WEST KHASI HILLS', 'SOUTH GARO HILLS',
  'NORTH GARO HILLS', 'EAST JAINTIA HILLS', 'WEST JAINTIA HILLS', 'SOUTH WEST GARO HILLS', 'SOUTH WEST KHASI HILLS', 'EASTERN WEST KHASI HILLS'];
const BY_DISTRICT = DISTRICTS.map((d, i) => ({ district_name: d, households_provided_employment: 10000 + i * 731 }));
const TWO_MEASURES = DISTRICTS.slice(0, 6).map((d, i) => ({ district_name: d, houses_sanctioned: 900 + i * 50, houses_completed: 700 + i * 40 }));
const SCHEME_YEARS = ['2022-23', '2023-24', '2024-25'].flatMap((y, i) => [
  { scheme: 'MGNREGA', financial_year: y, beneficiaries: 400000 + i * 1000 },
  { scheme: 'PMAY-G', financial_year: y, beneficiaries: 50000 + i * 900 },
]);
const BY_YEAR = ['2021-22', '2022-23', '2023-24', '2024-25'].map((y, i) => ({ financial_year: y, villages_covered: 3000 + i * 10 }));

// ── nothing asked: a comparison gets a chart by default ──
test('compare two schemes: tiles AND a chart by default', () => {
  drawn(viewPlan('Compare beneficiaries in MGNREGA and PMAY-G', R(SCHEMES)));
});
test('compare two districts: a chart by default', () => {
  drawn(viewPlan('Compare MGNREGA person days in East Khasi Hills and West Garo Hills', R(TWO_DISTRICTS)));
});
test('compare two years: a chart by default, line on offer', () => {
  const p = viewPlan('Compare PMAY-G houses completed in 2023-24 and 2024-25', R(TWO_YEARS));
  drawn(p);
  assert.ok(p.charts[0].types.includes('line'));
});
test('compare one row of two counts: a chart by default', () => {
  drawn(viewPlan('Compare MGNREGA households and PMAY-G houses', R([{ mgnrega_households: 140000, pmayg_houses: 52000 }], 'kpi_bar')));
});
test('a breakdown by district is charted by default', () => {
  drawn(viewPlan('MGNREGA households provided employment by district', R(BY_DISTRICT)));
});

// ── a plain "chart" / "graph": every type on offer ──
test('"in a graph" over a comparison draws a chart with a type switch', () => {
  const p = viewPlan('Compare beneficiaries in MGNREGA and PMAY-G in a graph', R(SCHEMES));
  drawn(p);
  assert.ok(p.charts[0].types.length >= 1);
});

// ── one named type: that type, and only it ──
test('bar chart by district', () => drawn(viewPlan('bar chart of households by district', R(BY_DISTRICT)), 'bar'));
test('pie chart by district', () => drawn(viewPlan('pie chart of households by district', R(BY_DISTRICT)), 'pie'));
test('donut chart by district', () => drawn(viewPlan('donut chart of households by district', R(BY_DISTRICT)), 'doughnut'));
test('line graph by year', () => drawn(viewPlan('line graph of villages covered by financial year', R(BY_YEAR)), 'line'));
test('bar graph by year', () => drawn(viewPlan('villages covered by year in a bar graph', R(BY_YEAR)), 'bar'));
test('pie chart of two schemes is a pie, with a caveat', () => {
  const p = viewPlan('Compare beneficiaries in MGNREGA and PMAY-G as a pie chart', R(SCHEMES));
  drawn(p, 'pie');
  assert.ok(p.note && p.note.includes('as you asked'), p.note);
});
test('"I want only bar graph" over two schemes', () => {
  drawn(viewPlan('Compare beneficiaries in MGNREGA and PMAY-G, I want only bar graph', R(SCHEMES)), 'bar');
});
test('line chart across districts is drawn as asked, with a caveat', () => {
  const p = viewPlan('Show person days by district as a line chart', R(BY_DISTRICT));
  drawn(p, 'line');
  assert.ok(p.note, 'a caveat says the points are not periods');
});
test('pie chart of a top-5 ranking is a pie', () => {
  drawn(viewPlan('pie chart of top 5 districts by households', R(BY_DISTRICT.slice(0, 5))), 'pie');
});
test('two schemes over years as a pie is a pie, not a donut, not bars', () => {
  drawn(viewPlan('beneficiaries by scheme and year as a pie chart', R(SCHEME_YEARS)), 'pie');
});
test('two schemes over years as a line', () => drawn(viewPlan('beneficiaries by scheme and year as a line graph', R(SCHEME_YEARS)), 'line'));
test('two schemes over years as a bar', () => drawn(viewPlan('beneficiaries by scheme and year as a bar chart', R(SCHEME_YEARS)), 'bar'));
test('two schemes over years as a donut', () => drawn(viewPlan('beneficiaries by scheme and year as a donut chart', R(SCHEME_YEARS)), 'doughnut'));
test('two years compared as a line graph', () => drawn(viewPlan('Compare houses completed in 2023-24 and 2024-25 as a line graph', R(TWO_YEARS)), 'line'));
test('stacked bar over two measures (grouped hint)', () => {
  drawn(viewPlan('stacked bar chart of houses sanctioned and completed by district', R(TWO_MEASURES, 'stacked')), 'stacked');
});
test('stacked bar over two measures (grouped_bar hint)', () => {
  drawn(viewPlan('stacked bar chart of houses sanctioned and completed by district', R(TWO_MEASURES, 'grouped_bar')), 'stacked');
});
test('stacked bar over two measures (no hint)', () => {
  drawn(viewPlan('stacked bar chart of houses sanctioned and completed by district', R(TWO_MEASURES)), 'stacked');
});

// ── a single figure asked as a chart: a chart is still drawn ──
test('one figure as a bar chart', () => {
  drawn(viewPlan('Total MGNREGA expenditure as a bar chart', R([{ total_expenditure_crore: 1066.7 }])), 'bar');
});
test('one figure as a pie chart', () => {
  drawn(viewPlan('How many PMAY-G houses were completed? show in pie chart', R([{ houses_completed: 152000 }])), 'pie');
});
test('one figure in a graph', () => {
  drawn(viewPlan('Show me the total Focus Plus beneficiaries in a graph', R([{ beneficiaries: 41000 }])));
});

// ── a message that only asks for a view ──
test('"I want only bar" / "now line" are view requests', () => {
  assert.equal(viewOnlyRequest('I want only bar'), 'bar');
  assert.equal(viewOnlyRequest('now give me line graph'), 'line');
  assert.equal(viewOnlyRequest('now line'), 'line');
  assert.equal(viewOnlyRequest('pie chart'), 'pie');
});
test('a question that uses "line" or "bar" in another sense is no chart request', () => {
  assert.equal(chartPreference('MGNREGA households below poverty line by district'), null);
  assert.equal(viewOnlyRequest('MGNREGA households below poverty line'), null);
});
