// The voice desk's picture planner (D-100): real answer shapes from the pipeline (captured 2026-11-02) become the
// right cards, every figure a cell of the answer, schemes never added together, gaps never zeros.
import test from 'node:test';
import assert from 'node:assert/strict';
import { plan, heardItem, norm, shapeOf } from '../src/chat/voice/vizPlan.js';

const kinds = (p) => p.cards.map((c) => c.kind);

test('a figure per scheme: tiles, each scheme in its own unit, the first figure of every scheme first, never a total', () => {
  const data = [
    { scheme: 'MGNREGA', person_days: 90915181, total_expenditure_crore: 3628.67 },
    { scheme_code: 'PMAY-G', houses_sanctioned: 171107, released_rupees: 21852598500.0, scheme: 'PMAY-G' },
    { payments: 385671, amount_raw: 1197392500.0, beneficiaries: 105813, scheme: 'Focus Plus' },
    { scheme_name: 'PRIME SEED', applications: 3149, scheme: 'CM Elevate' },
    { scheme_name: 'Meghalaya Piggery Development Scheme', applications: 2455, scheme: 'CM Elevate' },
  ];
  const p = plan({ data, route: 'data' }, 'Give me the headline figure of every scheme');
  assert.equal(p.cards[0].kind, 'tiles');
  const t = p.cards[0].items;
  assert.deepEqual(t.slice(0, 3).map((x) => x.label), ['MGNREGA', 'PMAY-G', 'Focus Plus']);
  assert.equal(t[0].value, 90915181);
  assert.ok(t.every((x) => x.label !== 'Total'));
  assert.ok(p.cards[0].note.includes('never added'));
  // CM Elevate's sub-schemes: its own ranking card, not a summed tile
  const cm = p.cards.find((c) => c.title.startsWith('CM Elevate'));
  assert.ok(cm && ['race', 'bars'].includes(cm.kind));
  assert.deepEqual(cm.items.map((x) => x.value), [3149, 2455]);
});

test('money by scheme also gets a bar (money is the one unit schemes share)', () => {
  const data = [{ scheme: 'MGNREGA', amount_crore: 3628.67 }, { scheme: 'PMAY-G', amount_crore: 2185.26 },
    { scheme: 'Focus Plus', amount_crore: 119.74 }, { scheme: 'Focus Legacy', amount_crore: 51.01 }];
  const p = plan({ data }, 'How much money has each scheme disbursed?');
  assert.deepEqual(kinds(p), ['tiles', 'bars']);
  assert.equal(p.cards[1].unitLabel, '₹ crore');
  assert.equal(p.cards[1].fmt(3628.67), '₹3,628.67 crore');
});

test('by district: the map and the ranking, sorted, values as given', () => {
  const data = [{ district: 'EASTERN WEST KHASI HILLS', employment_generated: 2140592 },
    { district: 'WEST GARO HILLS', employment_generated: 17539710 }, { district: 'RI BHOI', employment_generated: 4761757 }];
  const p = plan({ data }, 'MGNREGA person-days by district');
  assert.deepEqual(kinds(p), ['map', 'bars']);
  assert.equal(p.cards[0].items.find((x) => x.key === 'RI BHOI').value, 4761757);
  assert.deepEqual(p.cards[1].items.map((x) => x.label), ['West Garo Hills', 'Ri Bhoi', 'Eastern West Khasi Hills']);
  assert.ok(p.cards[1].allowed.includes('map'));
});

test('the lowest is asked: the insight names the lowest', () => {
  const data = [{ district: 'WEST GARO HILLS', houses: 33147 }, { district: 'RI BHOI', houses: 17565 }, { district: 'EAST KHASI HILLS', houses: 23952 }];
  const p = plan({ data }, 'Which district has the lowest PMAY-G houses?');
  assert.ok(p.cards.find((c) => c.insight).insight.startsWith('Lowest: Ri Bhoi'));
});

test('the leader of each district: the leader map, from the answer\'s own first row per district', () => {
  const data = [{ district: 'East Garo Hills', scheme: 'MGNREGA', beneficiaries: 106136 },
    { district: 'East Garo Hills', scheme: 'PMAY-G', beneficiaries: 16899 },
    { district: 'Ri Bhoi', scheme: 'MGNREGA', beneficiaries: 112602 }];
  const p = plan({ data }, 'Which scheme leads in each district?');
  assert.equal(p.cards[0].kind, 'map');
  assert.equal(p.cards[0].mapMode, 'leader');
  assert.equal(p.cards[0].leaders['EAST GARO HILLS'].label, 'MGNREGA');
  assert.equal(p.cards[0].items.find((x) => x.key === 'EAST GARO HILLS').value, 106136);
  assert.equal(p.cards[0].title, 'MGNREGA leads in every district');
});

test('over the years: a line; a 4-digit count is never taken for a year', () => {
  const data = [{ year_key: 2022, financial_year: '2022-23', employment_generated: 25596237 },
    { year_key: 2023, financial_year: '2023-24', employment_generated: 27264054 }];
  const p = plan({ data }, 'MGNREGA person-days by financial year');
  assert.deepEqual(kinds(p), ['line']);
  assert.deepEqual(p.cards[0].x, ['2022-23', '2023-24']);
  assert.deepEqual(p.cards[0].series[0].values, [25596237, 27264054]);
  const blocks = [{ lgd_block: 'DEMDEMA', completed_houses: 5274 }, { lgd_block: 'SONGSAK', completed_houses: 4850 }];
  const b = plan({ data: blocks }, 'Top blocks by PMAY-G houses completed');
  assert.equal(shapeOf(blocks).period, undefined);
  assert.ok(['race', 'bars'].includes(b.cards[0].kind));
});

test('each scheme over the years: a year a scheme does not hold is a gap, never a zero', () => {
  const data = [{ scheme: 'Focus Plus', financial_year: '2022-23', amount_crore: 60.1 },
    { scheme: 'Focus Plus', financial_year: '2025-26', amount_crore: 59.6 },
    { scheme: 'MGNREGA', financial_year: '2023-24', amount_crore: 1066.7 }];
  const p = plan({ data }, 'money each scheme by year');
  const line = p.cards[0];
  assert.equal(line.kind, 'line');
  assert.deepEqual(line.x, ['2022-23', '2023-24', '2024-25', '2025-26']);   // 2024-25 held by none: on the axis, a gap
  assert.deepEqual(line.series.find((s) => s.key === 'Focus Plus').values, [60.1, null, null, 59.6]);
});

test('two districts compared: tiles side by side, a bar and the map', () => {
  const data = [{ district: 'East Khasi Hills', houses: 23952, 'completed houses': 18154 },
    { district: 'West Garo Hills', houses: 33147, 'completed houses': 26822 }];
  const p = plan({ data }, 'Compare PMAY-G houses sanctioned in West Garo Hills and East Khasi Hills');
  assert.deepEqual(kinds(p), ['tiles', 'bars', 'map']);
  assert.equal(p.cards[0].items.length, 4);
});

test('no picture for a clarification, an empty answer or text only', () => {
  assert.equal(plan({ route: 'clarification', clarification: { options: [] }, data: [] }, 'x'), null);
  assert.equal(plan({ data: [] }, 'x'), null);
  assert.equal(plan({ data: [{ district: 'RI BHOI' }] }, 'x'), null);
});

test('a chart type asked for is honoured when the card allows it', () => {
  const data = [{ district: 'WEST GARO HILLS', houses: 33147 }, { district: 'RI BHOI', houses: 17565 }, { district: 'EAST KHASI HILLS', houses: 23952 }];
  assert.equal(plan({ data }, 'PMAY-G houses by district as a donut chart').cards.find((c) => c.kind === 'donut').kind, 'donut');
});

test('speech: a name reveals its item; a shorter name inside a longer one does not', () => {
  const p = plan({ data: [{ district: 'WEST KHASI HILLS', v_count: 1 }, { district: 'EASTERN WEST KHASI HILLS', v_count: 2 },
    { district: 'WEST GARO HILLS', v_count: 3 }] }, 'x');
  const items = p.cards[0].items;
  const wk = items.find((x) => x.key === 'WEST KHASI HILLS');
  const ewk = items.find((x) => x.key === 'EASTERN WEST KHASI HILLS');
  const heard = norm('Eastern West Khasi Hills has two.');
  assert.equal(heardItem(heard, ewk), true);
  assert.equal(heardItem(heard, wk), false);
  assert.equal(heardItem(norm('then West Khasi Hills'), wk), true);
  const cm = { say: ['cm elevate'], notBefore: ['legacy'] };
  assert.equal(heardItem(norm('CM Elevate Legacy disbursed'), cm), false);
  assert.equal(heardItem(norm('CM Elevate had 8,921'), cm), true);
});

test('speech: a year said in words reveals its point', () => {
  const p = plan({ data: [{ financial_year: '2023-24', person_days: 5 }, { financial_year: '2024-25', person_days: 6 }] }, 'x');
  const it = p.cards[0].items.find((x) => x.key === '2023-24');
  assert.equal(heardItem(norm('In twenty twenty-three twenty-four it was'), it), true);
  assert.equal(heardItem(norm('FY 2023-24'), it), true);
});

test('a donut asked for by name is drawn even with all twelve districts; never offered for a rate', () => {
  const names = ['EAST GARO HILLS', 'NORTH GARO HILLS', 'SOUTH GARO HILLS', 'SOUTH WEST GARO HILLS', 'WEST GARO HILLS',
    'EAST JAINTIA HILLS', 'WEST JAINTIA HILLS', 'EASTERN WEST KHASI HILLS', 'EAST KHASI HILLS', 'RI BHOI',
    'SOUTH WEST KHASI HILLS', 'WEST KHASI HILLS'];
  const data = names.map((d, i) => ({ district: d, houses: 1000 + i }));
  const p = plan({ data }, 'PMAY-G houses sanctioned by district as a donut chart');
  const d = p.cards.find((c) => c.kind === 'donut');
  assert.ok(d && d.items.length === 12);
  assert.equal(plan({ data }, 'PMAY-G houses sanctioned by district').cards.some((c) => c.kind === 'donut'), false);
  const rate = names.map((d, i) => ({ district: d, completion_rate_pct: 50 + i }));
  assert.equal(plan({ data: rate }, 'completion rate by district as a donut').cards.some((c) => c.kind === 'donut'), false);
});

test('the chat\'s redraw of an earlier answer carries its view: "show the same as a pie chart" draws the donut', () => {
  const data = [{ district: 'WEST GARO HILLS', houses: 33147 }, { district: 'RI BHOI', houses: 17565 }, { district: 'EAST KHASI HILLS', houses: 23952 }];
  assert.ok(plan({ data }, 'PMAY-G houses sanctioned by district', 'pie').cards.some((c) => c.kind === 'donut'));
  assert.ok(plan({ data }, 'PMAY-G houses sanctioned by district', 'line').cards.every((c) => c.kind !== 'line'));
});

test('the PDF chart cases: a missing financial year is a gap; a year line drawn as bars has its values; horizontal is the ranking; a chart over two schemes is side by side', () => {
  const fl = [{ financial_year: '2021-22', amount_crore: 10.2 }, { financial_year: '2022-23', amount_crore: 12.1 },
    { financial_year: '2024-25', amount_crore: 14.5 }, { financial_year: '2025-26', amount_crore: 14.2 }];
  const line = plan({ data: fl }, 'Show total Focus Legacy amount remitted in each financial year as a line chart').cards[0];
  assert.deepEqual(line.x, ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26']);
  assert.deepEqual(line.series[0].values, [10.2, 12.1, null, 14.5, 14.2]);
  const bars = plan({ data: fl }, 'Show it by financial year as bar chart').cards[0];
  assert.equal(bars.kind, 'bars');
  assert.deepEqual(bars.items.map((x) => x.value), [10.2, 12.1, null, 14.5, 14.2]);
  const d = [{ district: 'WEST GARO HILLS', houses: 3 }, { district: 'RI BHOI', houses: 2 }, { district: 'EAST KHASI HILLS', houses: 1 }];
  assert.ok(plan({ data: d }, 'now show the same as a horizontal bar chart').cards.some((c) => c.kind === 'race'));
  const two = [{ scheme: 'MGNREGA', beneficiaries: 1494437 }, { scheme: 'PMAY-G', beneficiaries: 171107 }];
  assert.ok(!plan({ data: two }, 'So compare total beneficiaries in PMAY-G and MGNREGA').cards.some((c) => c.kind === 'bars'));
  const pie = plan({ data: two }, 'for above one give me', 'pie').cards.find((c) => c.kind === 'donut');
  assert.ok(pie && pie.items.length === 2 && pie.note.includes('not a split'));
});
