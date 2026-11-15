// D-112 (streaming, 2026-11-15): the in-flight answer's live state lives outside the
// App's message list (liveTurn.js), and the stream's `answer` event reaches the page
// before `done` (api.js streamNLPResponse passes it to onEvent; `done` resolves).
import { test } from 'node:test';
import assert from 'node:assert/strict';

globalThis.window = { location: { search: '' } };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = globalThis.localStorage;
const { endLive, getLive, patchLive, sameResult, startLive } = await import('../src/chat/liveTurn.js');
const { streamNLPResponse } = await import('../src/chat/api.js');

test('a turn holds its steps and draft; patches merge; an ended turn reads empty and ignores patches', () => {
  startLive(901);
  patchLive(901, (x) => ({ steps: [...x.steps, 'entities'] }));
  patchLive(901, (x) => ({ draft: x.draft + 'MGNREGA ' }));
  patchLive(901, (x) => ({ draft: x.draft + 'generated' }));
  assert.deepEqual(getLive(901).steps, ['entities']);
  assert.equal(getLive(901).draft, 'MGNREGA generated');
  patchLive(901, () => ({ stale: true }));
  assert.equal(getLive(901).stale, true);
  assert.equal(getLive(901).draft, 'MGNREGA generated', 'a draft_reset keeps the old words until new ones come');
  endLive(901);
  assert.equal(getLive(901).draft, '');
  patchLive(901, () => ({ draft: 'late token' }));
  assert.equal(getLive(901).draft, '', 'a token frame after the turn ended changes nothing');
  assert.equal(getLive(null).draft, '');
});

test('the done result is recognised as the answer already shown', () => {
  const a = { answer: 'x', data: [{ d: 'Ri Bhoi', v: 3 }], row_count: 1 };
  assert.ok(sameResult(a, JSON.parse(JSON.stringify(a))));
  assert.ok(!sameResult(a, { ...a, answer: 'y' }));
});

const enc = new TextEncoder();
function frames(list) {
  return async () => {
    let i = 0;
    const reader = { read: async () => (i < list.length ? { value: enc.encode(list[i++]), done: false } : { done: true }) };
    return { ok: true, status: 200, body: { getReader: () => reader } };
  };
}

test('the answer event reaches onEvent before done resolves, with the same result', async () => {
  const result = { answer: '42 applications.', route: 'data', row_count: 1 };
  globalThis.fetch = frames([
    'data: {"type":"step","node":"compose"}\n\n',
    `data: ${JSON.stringify({ type: 'answer', result })}\n\n`,
    ': ping\n\n',
    `data: ${JSON.stringify({ type: 'done', result })}\n\n`,
  ]);
  const seen = [];
  const out = await streamNLPResponse('q', 'en', 's-answer', { onEvent: (e) => seen.push(e.type === 'answer' ? ['answer', e.result] : [e.type]) });
  assert.deepEqual(seen, [['step'], ['answer', result]]);
  assert.deepEqual(out, result);
});
