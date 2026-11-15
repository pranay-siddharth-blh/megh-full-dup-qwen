// The agent orb (D-113, 2026-11-15): which face the orb shows for what the page knows, the dotted sphere's maths,
// and the per-browser flags (the folded panel, the one-time "the mic now types" toast). src/chat/agentOrb.js.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MIC_TOAST_KEY, MIC_TYPES_TOAST, ORB_TEXT, PANEL_STARTERS, RESTING_TIP, noteMicTypes, orbState, readFlag,
  sphereDots, sphereSize, writeFlag,
} from '../src/chat/agentOrb.js';
import { SCHEME_HUES } from '../src/chat/chartTheme.js';

const memory = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); } };
};

test('orbState: idle when signed in, a mic exists and the voice is not resting', () => {
  assert.equal(orbState({ signedIn: true, resting: false, hasMic: true, dictating: false }), 'idle');
  assert.equal(orbState(), 'idle');
});

test('orbState: dictating dims the orb but keeps it a working button', () => {
  assert.equal(orbState({ dictating: true }), 'dictating');
  assert.equal(ORB_TEXT.dictating.disabled, false);
});

test('orbState: resting after a fallback, without a mic, or signed out; resting wins over dictating', () => {
  assert.equal(orbState({ resting: true }), 'resting');
  assert.equal(orbState({ hasMic: false }), 'resting');
  assert.equal(orbState({ signedIn: false }), 'resting');
  assert.equal(orbState({ resting: true, dictating: true }), 'resting');
  assert.equal(ORB_TEXT.resting.disabled, true);
  assert.equal(ORB_TEXT.resting.tip, RESTING_TIP);
});

test('every face has a label and a tooltip', () => {
  for (const k of ['idle', 'dictating', 'resting']) {
    assert.ok(ORB_TEXT[k].label.length > 0 && ORB_TEXT[k].tip.length > 0, k);
  }
  assert.equal(ORB_TEXT.idle.label, 'Talk to Megh One AI');
});

test('sphereDots: 64 lattice points inside the sphere, front ones larger and brighter, computed once', () => {
  const d = sphereDots(64);
  assert.equal(d.front.length + d.back.length, 64);
  assert.ok(d.front.length > 20 && d.back.length > 20);
  for (const p of [...d.front, ...d.back]) {
    const reach = Math.hypot(p.cx - 50, p.cy - 50) + p.r;
    assert.ok(reach < 50, 'a dot leaves the sphere: ' + JSON.stringify(p));
    assert.ok(p.a > 0 && p.a <= 1);
  }
  const avg = (xs, k) => xs.reduce((s, p) => s + p[k], 0) / xs.length;
  assert.ok(avg(d.front, 'r') > avg(d.back, 'r'));
  assert.ok(avg(d.front, 'a') > avg(d.back, 'a'));
  assert.equal(sphereDots(64), d, 'the same object: drawn from one computation');
});

test('sphereSize: three quarters of the button, whole pixels', () => {
  assert.equal(sphereSize(40), 30);
  assert.equal(sphereSize(64), 48);
  assert.equal(sphereSize(26), 20);
  assert.ok(Number.isInteger(sphereSize(38)));
});

test('the panel examples are cross-scheme first and every scheme dot has a colour', () => {
  assert.equal(PANEL_STARTERS.length, 3);
  assert.equal(PANEL_STARTERS[0].scheme, null);
  for (const s of PANEL_STARTERS) if (s.scheme) assert.ok(SCHEME_HUES[s.scheme], s.scheme);
});

test('flags: written and read per browser; blocked storage forgets quietly', () => {
  const st = memory();
  assert.equal(readFlag('k', st), false);
  writeFlag('k', true, st);
  assert.equal(readFlag('k', st), true);
  writeFlag('k', false, st);
  assert.equal(readFlag('k', st), false);
  const blocked = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.equal(readFlag('k', blocked), false);
  assert.doesNotThrow(() => writeFlag('k', true, blocked));
});

test('the "mic now types" toast shows once per browser', () => {
  const st = memory();
  const shown = [];
  assert.equal(noteMicTypes((t) => shown.push(t), st), true);
  assert.equal(noteMicTypes((t) => shown.push(t), st), false);
  assert.deepEqual(shown, [MIC_TYPES_TOAST]);
  assert.equal(st.getItem(MIC_TOAST_KEY), '1');
});
