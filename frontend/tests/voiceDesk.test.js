// The Secretary's desk, derived from the board (2026-11-14): every scheme the board holds is on the desk with no code
// change, in the voice pack's order; a scheme that records no money is named, never drawn as ₹0; the figures are the
// board's own, untouched.
import test from 'node:test';
import assert from 'node:assert/strict';
import { andList, deskModel, headlineMeasure, moneyMeasure, orderedSchemes } from '../src/chat/voice/deskModel.js';
import { plainCount, plan } from '../src/chat/voice/vizPlan.js';
import VOICE_PACK from '../src/chat/voice/meghVoicePack.js';

const M = (key, label, unit, total, extra = {}) => ({ key, label, unit, counts: label.toLowerCase(), total,
  by_district: { 'RI BHOI': total }, by_year: { '2024-25': total }, ...extra });
// the eight schemes as /api/voice/board returned them on 14 Nov 2026 (totals as served)
const BOARD = { schemes: [
  { name: 'MGNREGA', measures: [M('person_days', 'Person-days', 'person-days', 90915181), M('households', 'Households employed', 'count', 1494437),
    M('expenditure', 'Expenditure', 'rupees', 36286657000)] },
  { name: 'PMAY-G', measures: [M('sanctioned', 'Houses sanctioned', 'count', 171107), M('completed', 'Houses completed', 'count', 129941),
    M('released', 'Funds released', 'rupees', 21852598500)] },
  { name: 'Focus Plus', measures: [M('payments', 'Disbursements', 'count', 385671), M('amount', 'Amount disbursed', 'rupees', 1197392500)] },
  { name: 'CM Elevate', measures: [M('applications', 'Applications', 'count', 8938, { by_year: {} })] },
  { name: 'Focus Legacy', measures: [M('groups', 'Producer groups', 'count', 11906), M('amount', 'Amount remitted', 'rupees', 510105000)] },
  { name: 'CM Elevate Legacy', measures: [M('disbursed', 'Disbursed', 'rupees', 828978537.75), M('records', 'Sanction records', 'count', 2823)] },
  { name: 'CMSS', measures: [M('students_paid', 'Students paid', 'count', 98751), M('applications', 'Applications', 'count', 104827),
    M('amount', 'Amount disbursed', 'rupees', 592506000)] },
  { name: 'Homestay', measures: [M('applications', 'Applications', 'count', 1297), M('approved', 'Approved', 'count', 80)] },
] };

test('eight schemes: one command tile each, what the scheme counts, in the pack order, figures untouched', () => {
  const d = deskModel(BOARD, VOICE_PACK.schemes);
  assert.deepEqual(d.schemes, VOICE_PACK.schemes);
  assert.equal(d.tiles.length, 8);
  assert.deepEqual(d.tiles.map((t) => t.m.key), ['person_days', 'sanctioned', 'payments', 'applications', 'groups', 'records', 'students_paid', 'applications']);
  assert.equal(d.tiles[0].m.total, 90915181);
  assert.ok(d.tiles.every((t) => t.m.unit !== 'rupees'));
  assert.ok(d.tiles.some((t) => t.m.label === 'Person-days') && d.tiles.some((t) => t.m.label === 'Houses sanctioned'));
});

test('money: every scheme that records money (CMSS included); Homestay and CM Elevate named, never ₹0', () => {
  const d = deskModel(BOARD, VOICE_PACK.schemes);
  assert.deepEqual(d.money.map((x) => x.s), ['MGNREGA', 'PMAY-G', 'Focus Plus', 'Focus Legacy', 'CM Elevate Legacy', 'CMSS']);
  assert.ok(d.money.every((x) => x.m.unit === 'rupees' && x.m.total > 0));
  assert.equal(d.money.find((x) => x.s === 'CMSS').m.total, 592506000);
  assert.deepEqual(d.noMoney, ['CM Elevate', 'Homestay']);
  assert.equal(moneyMeasure(BOARD.schemes[7]), null);
  // a money measure with a zero total is not money to draw
  assert.equal(moneyMeasure({ name: 'X', measures: [M('amount', 'Amount', 'rupees', 0)] }), null);
});

test('the map: one chip per scheme, its headline by district; the years note names the schemes with none', () => {
  const d = deskModel(BOARD, VOICE_PACK.schemes);
  assert.deepEqual(d.maps.map((x) => x.s), VOICE_PACK.schemes);
  assert.equal(d.maps.find((x) => x.s === 'Homestay').m.key, 'applications');
  assert.equal(d.lead.s, 'MGNREGA');
  assert.equal(d.lead.m.key, 'person_days');
  assert.deepEqual(d.noYear, ['CM Elevate']);
  assert.ok(d.years.cols.includes('2024-25'));
});

test('a ninth scheme the code has never heard of appears everywhere, after the known ones', () => {
  const nine = { schemes: [{ name: 'Lakadong Mission', measures: [M('farmers', 'Farmers enrolled', 'count', 4321), M('grant', 'Grant paid', 'rupees', 120000000)] },
    ...BOARD.schemes] };
  const d = deskModel(nine, VOICE_PACK.schemes);
  assert.equal(d.schemes.length, 9);
  assert.equal(d.schemes[8], 'Lakadong Mission');
  assert.equal(d.tiles.length, 9);
  assert.equal(d.tiles[8].m.total, 4321);
  assert.ok(d.money.some((x) => x.s === 'Lakadong Mission'));
  assert.ok(d.maps.some((x) => x.s === 'Lakadong Mission'));
  assert.deepEqual(orderedSchemes(nine, []).map((s) => s.name)[0], 'Lakadong Mission');   // no pack: the board's order
});

test('a scheme that holds only money shows its money; an empty board is an empty desk', () => {
  assert.equal(headlineMeasure({ name: 'X', measures: [M('amount', 'Amount', 'rupees', 5)] }).key, 'amount');
  const d = deskModel(null, VOICE_PACK.schemes);
  assert.deepEqual([d.tiles.length, d.money.length, d.maps.length, d.lead], [0, 0, 0, null]);
  assert.equal(andList(['A']), 'A');
  assert.equal(andList(['A', 'B']), 'A and B');
  assert.equal(andList(['A', 'B', 'C']), 'A, B and C');
});

test('a figure tile says plainly what it counts; the whole note stays as its tooltip', () => {
  assert.equal(plainCount('household-years: households given work, counted once per year worked'), 'households given work');
  assert.equal(plainCount('students paid (scholarship applications that were paid)'), 'students paid');
  assert.equal(plainCount('producer-group members, counted once per payment (a group paid twice counts twice)'), 'producer-group members');
  assert.equal(plainCount('houses sanctioned'), 'houses sanctioned');
  assert.equal(plainCount(''), '');
  const data = VOICE_PACK.schemes.map((s, i) => ({ scheme: s, beneficiaries: 1000 + i }));
  const p = plan({ data, route: 'data', measure_notes: { CMSS: { beneficiaries: 'students paid (scholarship applications that were paid)' } } },
    'Compare beneficiaries across all schemes');
  const tiles = p.cards[0];
  assert.equal(tiles.kind, 'tiles');
  assert.equal(tiles.items.length, 8);
  assert.deepEqual(tiles.items.map((x) => x.value), data.map((r) => r.beneficiaries));
  assert.ok(tiles.items.every((x) => x.sub && x.note));
});

test('nine schemes on the stage: every scheme keeps its tile (the cap follows the schemes, up to twelve)', () => {
  // a ninth scheme arrives through the regenerated voice pack (data, not code): simulated here, then put back
  VOICE_PACK.schemes.push('Lakadong Mission');
  try {
    const data = VOICE_PACK.schemes.map((s, i) => ({ scheme: s, beneficiaries: 10 + i }));
    const p = plan({ data, route: 'data' }, 'Compare beneficiaries across all schemes');
    assert.equal(p.cards[0].kind, 'tiles');
    assert.equal(p.cards[0].items.length, 9);
    assert.equal(p.cards[0].items[8].label, 'Lakadong Mission');
    assert.deepEqual(p.cards[0].items.map((x) => x.value), data.map((r) => r.beneficiaries));
  } finally { VOICE_PACK.schemes.pop(); }
  // eight schemes with two figures each: still eight tiles, the first figure of every scheme
  const two = VOICE_PACK.schemes.map((s, i) => ({ scheme: s, beneficiaries: 10 + i, amount_crore: 1 + i }));
  const q = plan({ data: two, route: 'data' }, 'Give me the headline figure of every scheme');
  assert.equal(q.cards[0].items.length, 8);
  assert.ok(q.cards[0].items.every((x) => x.col === 'beneficiaries'));
});
