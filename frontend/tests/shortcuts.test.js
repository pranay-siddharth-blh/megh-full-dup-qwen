// The keyboard shortcut table (src/chat/shortcuts.js): one key per action, none of the browser's or the OS's own keys,
// and the agent orb's Alt + V (D-113, 2026-11-15).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { RESERVED_KEYS, SHORTCUTS, matches } from '../src/chat/shortcuts.js';

const sig = (s) => [s.mod ? 'mod' : '', s.shift ? 'shift' : '', s.alt ? 'alt' : '', String(s.key).toLowerCase()].join('+');

test('no two shortcuts share an id or a key', () => {
  const ids = SHORTCUTS.map((s) => s.id);
  assert.equal(new Set(ids).size, ids.length);
  const keys = SHORTCUTS.map(sig);
  assert.equal(new Set(keys).size, keys.length, keys.join(' | '));
});

test('no shortcut takes a key the browser or the OS keeps', () => {
  const reserved = new Set(RESERVED_KEYS.map(sig));
  for (const s of SHORTCUTS) assert.ok(!reserved.has(sig(s)), s.id + ' takes ' + sig(s));
});

test('talk is Alt + V, works in the question box, and is listed in the help', () => {
  const t = SHORTCUTS.find((s) => s.id === 'talk');
  assert.ok(t);
  assert.equal(sig(t), '++alt+v');
  assert.equal(t.whileTyping, true);
  assert.ok(!t.hidden);
  assert.ok(!SHORTCUTS.some((s) => s.key === ' '), 'Ctrl + Shift + Space switches the keyboard layout on Windows');
});

test('Alt + V matches; Ctrl + Alt + V (AltGr) and plain V do not', () => {
  const t = SHORTCUTS.find((s) => s.id === 'talk');
  const ev = (o) => ({ ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, key: 'v', code: 'KeyV', ...o });
  assert.equal(matches(ev({ altKey: true }), t), true);
  assert.equal(matches(ev({ altKey: true, key: '√' }), t), true, 'Option + V on a Mac types √: matched by its code');
  assert.equal(matches(ev({ altKey: true, ctrlKey: true }), t), false);
  assert.equal(matches(ev({}), t), false);
});
