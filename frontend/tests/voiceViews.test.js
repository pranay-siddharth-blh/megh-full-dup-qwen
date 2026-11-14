// Chart switches by voice, the best picture by the words, the table, and the breakdown that explains a single figure
// (2026-11-11). Every figure drawn stays a cell of an answer.
import test from 'node:test';
import assert from 'node:assert/strict';
import { plan, explainCard } from '../src/chat/voice/vizPlan.js';
import { canonicalView, viewSpeech, viewChip, explainAsk, throwawaySessionId, isRedraw, NO_PICTURE } from '../src/chat/voice/voiceViews.js';
import { dropRedrawNote, spokenForm, spokenNote } from '../src/chat/voiceSpeech.js';

const kinds = (p) => p.cards.map((c) => c.kind);
const DIST = [{ district: 'WEST GARO HILLS', houses: 33147 }, { district: 'RI BHOI', houses: 17565 },
  { district: 'EAST KHASI HILLS', houses: 23952 }, { district: 'SOUTH GARO HILLS', houses: 9000 }];
const YEARS = [{ financial_year: '2021-22', amount_crore: 10.2 }, { financial_year: '2022-23', amount_crore: 12.1 },
  { financial_year: '2023-24', amount_crore: 14.5 }];

test('the seven canonical switch sentences, and only they', () => {
  assert.equal(canonicalView('show it as a bar chart'), 'bar');
  assert.equal(canonicalView('Show it as a line chart.'), 'line');
  assert.equal(canonicalView('  SHOW IT AS A PIE CHART!  '), 'pie');
  assert.equal(canonicalView('show it as a table'), 'table');
  assert.equal(canonicalView('Show it on the map?'), 'map');
  assert.equal(canonicalView('show it as a ranking'), 'ranking');
  assert.equal(canonicalView('show  it as   horizontal bars.'), 'horizontal');
  assert.equal(canonicalView('show it on the map of Meghalaya'), null);
  assert.equal(canonicalView('MGNREGA person-days by district as a bar chart'), null);
  assert.equal(canonicalView(''), null);
});

test('a switch wins over the words of the question the data came from (the map question redrawn as bars)', () => {
  const q = 'Show PMAY-G houses by district on the map';
  assert.equal(plan({ data: DIST }, q).cards[0].kind, 'map');
  const p = plan({ data: DIST }, q, 'bar');
  assert.equal(p.cards[0].kind, 'bars');
  assert.deepEqual(p.applied, { asked: 'bar', want: 'bars', drawn: 'bars', reason: '' });
  assert.equal(p.cards.filter((c) => c.kind === 'bars').length, 1);       // never the same picture twice
  assert.deepEqual(p.cards[0].items.map((x) => x.value), [33147, 23952, 17565, 9000]);
});

test('map / ranking / horizontal: drawn when the data holds them, the closest view otherwise, with the reason', () => {
  const m = plan({ data: DIST }, 'PMAY-G houses by district', 'map');
  assert.equal(m.cards[0].kind, 'map');
  assert.equal(viewSpeech('map', m.applied), 'Here it is on the map, sir.');
  const r = plan({ data: DIST }, 'PMAY-G houses by district', 'ranking');
  assert.equal(r.cards[0].kind, 'race');
  assert.deepEqual(r.cards[0].items.map((x) => x.key), ['WEST GARO HILLS', 'EAST KHASI HILLS', 'RI BHOI', 'SOUTH GARO HILLS']);
  assert.equal(viewSpeech('ranking', r.applied), 'Here it is as a ranking.');
  const h = plan({ data: DIST }, 'PMAY-G houses by district', 'horizontal');
  assert.equal(h.cards[0].kind, 'race');
  assert.equal(viewSpeech('horizontal', h.applied), 'Here it is as horizontal bars.');
  // years are not districts: no map; the years ranked instead, and the voice says why
  const y = plan({ data: YEARS }, 'Focus Legacy amount by year', 'map');
  assert.equal(y.applied.drawn, 'race');
  assert.equal(y.applied.reason, 'not-district');
  assert.deepEqual(y.cards[0].items.map((x) => x.value), [14.5, 12.1, 10.2]);
  assert.equal(viewSpeech('map', y.applied), "This one isn't by district, so it can't go on the map. Here it is as a ranking instead.");
  // districts are not a time series: no line, bars instead
  const l = plan({ data: DIST }, 'PMAY-G houses by district', 'line');
  assert.equal(l.applied.drawn, 'bars');
  assert.ok(viewSpeech('line', l.applied).startsWith("This one isn't over time"));
  assert.ok(l.cards.every((c) => c.kind !== 'line'));
});

test('a single figure: no chart to switch to, said plainly; a table still works', () => {
  const one = [{ houses_sanctioned: 171107 }];
  const p = plan({ data: one }, 'How many PMAY-G houses were sanctioned?', 'map');
  assert.equal(p.applied.drawn, null);
  assert.equal(p.applied.reason, 'single');
  assert.equal(viewSpeech('map', p.applied), "This answer is a single figure, so there's nothing to draw as the map, sir.");
  assert.equal(p.cards[0].kind, 'kpi');
  const t = plan({ data: [{ houses_sanctioned: 171107, houses_completed: 129941 }] }, 'x', 'table');
  assert.deepEqual(kinds(t), ['table']);
  assert.deepEqual(t.cards[0].items.map((x) => [x.col, x.value]), [['houses_sanctioned', 171107], ['houses_completed', 129941]]);
  assert.deepEqual(t.cards[0].items.map((x) => x.cells[0]), ['1,71,107', '1,29,941']);
});

test('the answer as a table: its own rows and every column, money with its unit', () => {
  const data = [{ district: 'WEST GARO HILLS', beneficiaries: 120, amount_crore: 3.5 }, { district: 'RI BHOI', beneficiaries: 80, amount_crore: 2.25 }];
  const p = plan({ data }, 'Focus Plus beneficiaries and amount by district', 'table');
  const c = p.cards[0];
  assert.equal(c.kind, 'table');
  assert.deepEqual(c.columns.map((x) => x.title), ['District', 'Beneficiaries', 'Amount']);
  assert.equal(c.columns[2].unit, '₹ crore');
  assert.deepEqual(c.items.map((x) => x.label), ['West Garo Hills', 'Ri Bhoi']);   // the answer's order, not re-sorted
  assert.deepEqual(c.items[0].cells, ['120', '₹3.5 crore']);
  assert.equal(c.items[0].value, 120);
  assert.equal(viewSpeech('table', p.applied), 'Here it is as a table.');
});

test('a donut only for parts of one whole; a rate falls back to bars and the voice says why', () => {
  const rate = DIST.map((r, i) => ({ district: r.district, completion_rate_pct: 50 + i }));
  const p = plan({ data: rate }, 'completion rate by district', 'pie');
  assert.equal(p.applied.drawn, 'bars');
  assert.equal(p.applied.reason, 'not-parts');
  assert.equal(viewSpeech('pie', p.applied), "These figures aren't parts of one whole, so a pie would mislead. Here it is as a bar chart instead.");
  assert.equal(plan({ data: DIST }, 'x', 'pie').cards[0].kind, 'donut');
});

test('the best picture by the words, only when the data holds it; a named chart always wins', () => {
  assert.deepEqual(kinds(plan({ data: DIST }, 'Top 3 districts by PMAY-G houses')), ['race', 'map']);
  assert.deepEqual(kinds(plan({ data: DIST }, 'PMAY-G houses district-wise')), ['map', 'bars']);
  assert.deepEqual(kinds(plan({ data: DIST }, 'Where are the PMAY-G houses?')), ['map', 'bars']);
  assert.deepEqual(kinds(plan({ data: DIST }, 'Top districts by PMAY-G houses on the map')), ['map', 'bars']);
  const dy = [];
  ['WEST GARO HILLS', 'RI BHOI'].forEach((d, i) => ['2022-23', '2023-24'].forEach((y, j) => dy.push({ district: d, financial_year: y, person_days: 100 * (i + 1) + j })));
  assert.equal(plan({ data: dy }, 'MGNREGA person-days trend by financial year in each district').cards[0].kind, 'line');
  assert.equal(plan({ data: dy }, 'MGNREGA person-days by district and year').cards[0].kind, 'map');
  const money = [{ scheme: 'MGNREGA', amount_crore: 3628.67 }, { scheme: 'PMAY-G', amount_crore: 2185.26 }, { scheme: 'Focus Plus', amount_crore: 119.74 }];
  assert.deepEqual(kinds(plan({ data: money }, 'What is the share of money by scheme?')), ['donut', 'tiles']);
  assert.deepEqual(kinds(plan({ data: money }, 'Compare the money of MGNREGA, PMAY-G and Focus Plus')), ['tiles', 'bars']);
  // the twelve districts are too many for a share donut: the map stays the picture
  const twelve = ['EAST GARO HILLS', 'NORTH GARO HILLS', 'SOUTH GARO HILLS', 'SOUTH WEST GARO HILLS', 'WEST GARO HILLS',
    'EAST JAINTIA HILLS', 'WEST JAINTIA HILLS', 'EASTERN WEST KHASI HILLS', 'EAST KHASI HILLS', 'RI BHOI',
    'SOUTH WEST KHASI HILLS', 'WEST KHASI HILLS'].map((d, i) => ({ district: d, houses: 100 + i }));
  assert.equal(plan({ data: twelve }, 'distribution of houses by district').cards[0].kind, 'map');
});

test('the breakdown that explains a figure: drawn only when its parts add up to it', () => {
  const tile = { col: 'houses', value: 83664, color: '#7C3FBF' };
  const ok = explainCard(tile, { data: DIST }, 'district');
  assert.ok(ok.card, ok.why);
  assert.equal(ok.card.title, 'By district');
  assert.equal(ok.card.explain, 'district');
  assert.equal(ok.sum, 83664);
  assert.deepEqual(ok.card.items.map((x) => x.value), [33147, 23952, 17565, 9000]);
  assert.equal(ok.card.note, 'They add up to 83,664.');
  // a rounding difference within 0.5 % is allowed and said; beyond it the card is dropped
  assert.ok(explainCard({ ...tile, value: 83700 }, { data: DIST }, 'district').card.note.includes('rounding'));
  assert.equal(explainCard({ ...tile, value: 90000 }, { data: DIST }, 'district').why, 'the parts do not add up to the figure');
  // a rate never adds up across districts
  const rate = DIST.map((r) => ({ district: r.district, completion_rate_pct: 50 }));
  assert.ok(explainCard({ col: 'completion_rate_pct', value: 50 }, { data: rate }, 'district').why.startsWith('the measure does not add up'));
  // people are counted once across years: beneficiaries by year never explain a total
  const ben = [{ financial_year: '2022-23', beneficiaries: 10 }, { financial_year: '2023-24', beneficiaries: 12 }];
  assert.ok(explainCard({ col: 'beneficiaries', value: 22 }, { data: ben }, 'period').why.startsWith('the measure does not add up'));
  // money flows: by financial year, in year order, gaps kept
  const yr = explainCard({ col: 'amount_crore', value: 36.8 }, { data: YEARS }, 'period');
  assert.ok(yr.card, yr.why);
  assert.equal(yr.card.title, 'By financial year');
  assert.deepEqual(yr.card.items.map((x) => x.key), ['2021-22', '2022-23', '2023-24']);
  assert.equal(yr.card.fmt(36.8), '₹36.8 crore');
  // another measure is never taken for this one; one row per part
  assert.equal(explainCard({ col: 'houses_completed', value: 83664 }, { data: DIST }, 'district').why, 'not the same measure');
  assert.ok(explainCard({ col: 'house_count', value: 83664 }, { data: DIST }, 'district', { oneMeasure: true }).card);
  assert.equal(explainCard(tile, { data: [...DIST, DIST[0]] }, 'district').why, 'more than one row per district');
  assert.equal(explainCard(tile, { data: [] }, 'district').why, 'no breakdown rows');
});

test('what to ask for the breakdown: by district, or by year when a place is named, nothing when both are', () => {
  assert.deepEqual(explainAsk('How many PMAY-G houses were completed?', { data: [{ houses: 1 }] }),
    { q: 'How many PMAY-G houses were completed by district', by: 'district' });
  assert.deepEqual(explainAsk('MGNREGA person-days in West Garo Hills', { data: [{ person_days: 1 }] }),
    { q: 'MGNREGA person-days in West Garo Hills by financial year', by: 'period' });
  assert.deepEqual(explainAsk('person-days in west garo', { data: [{ person_days: 1 }] }).by, 'period');
  assert.deepEqual(explainAsk('houses in Dalu block', { data: [{ houses: 1 }] }).by, 'period');
  assert.equal(explainAsk('MGNREGA person-days in West Garo Hills in 2023-24', { data: [{ person_days: 1 }] }), null);
  assert.equal(explainAsk('MGNREGA person-days', { data: [{ district: 'RI BHOI', financial_year: '2023-24', person_days: 1 }] }), null);
  // the question as the pipeline understood it (a follow-up such as "And for Ri Bhoi?")
  assert.equal(explainAsk('And for Ri Bhoi?', { rewritten_question: 'PMAY-G houses in Ri Bhoi', data: [{ houses: 1 }] }).q,
    'PMAY-G houses in Ri Bhoi by financial year');
  const sid = throwawaySessionId();
  assert.ok(sid.startsWith('voice_explain_') && sid.length < 128);
  assert.ok(Array.from(sid).every((c) => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c === '_'));
});

test('the voice never reads the chat\'s redraw note; a switch with nothing on screen says so', () => {
  const ans = 'Here is the same data as a bar chart. (Drawn here from the answer above; it is not saved with the chat.)';
  assert.equal(dropRedrawNote(ans), 'Here is the same data as a bar chart.');
  assert.ok(!spokenForm({ answer: ans }).speak.includes('Drawn'));
  assert.ok(!spokenNote(ans).speak.includes('Drawn'));
  assert.equal(isRedraw({ kind: 'rich', local: true, view: 'bar' }), true);
  assert.equal(isRedraw({ kind: 'rich', view: 'bar' }), false);
  assert.ok(NO_PICTURE.startsWith("There's no chart on screen yet"));
  assert.deepEqual(viewChip('map', { want: 'map', drawn: 'map', reason: '' }), { title: 'On the map', sub: '' });
  assert.deepEqual(viewChip('map', { want: 'map', drawn: 'race', reason: 'not-district' }), { title: 'Ranking', sub: 'Map: not by district' });
});
