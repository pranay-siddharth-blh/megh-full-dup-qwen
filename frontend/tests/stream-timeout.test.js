// E11 / UI-03 (2026-10-29): the question timeout is an inactivity timer. A
// stream that keeps sending (tokens or ": ping") is never cut; 75 s of silence
// is. Drives the real streamNLPResponse with a fake fetch and mocked timers.
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';

// api.js reads these at load time.
globalThis.window = { location: { search: '' } };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.sessionStorage = globalThis.localStorage;
const { QUERY_IDLE_MS, streamNLPResponse } = await import('../src/chat/api.js');

const enc = new TextEncoder();
const flush = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };

// A stream that sends `frames` one every `gapMs` (mocked time), then the answer.
function fakeStreamFetch(frames, gapMs) {
  return async (_url, opts) => {
    let i = 0;
    const reader = {
      read: () => new Promise((resolve, reject) => {
        const onAbort = () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
        if (opts.signal.aborted) { onAbort(); return; }
        opts.signal.addEventListener('abort', onAbort, { once: true });
        setTimeout(() => {
          opts.signal.removeEventListener('abort', onAbort);
          const frame = i < frames.length ? frames[i] : 'data: {"type":"done","result":{"answer":"ok"}}\n\n';
          i += 1;
          resolve({ value: enc.encode(frame), done: false });
        }, gapMs);
      }),
    };
    return { ok: true, status: 200, body: { getReader: () => reader } };
  };
}

test('a stream with a chunk every 10 s for 120 s is not cut', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const frames = Array.from({ length: 12 }, (_, k) => (k % 2 ? ': ping\n\n' : 'data: {"type":"token","text":"x"}\n\n'));
    globalThis.fetch = fakeStreamFetch(frames, 10000);
    const p = streamNLPResponse('q', 'en', 's1');
    for (let t = 0; t < 13; t++) { await flush(); mock.timers.tick(10000); }
    await flush();
    assert.deepEqual(await p, { answer: 'ok' });
  } finally {
    mock.timers.reset();
  }
});

test('75 s of silence times the question out', async () => {
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    globalThis.fetch = fakeStreamFetch([], QUERY_IDLE_MS * 10);   // the first chunk never comes in time
    const p = streamNLPResponse('q', 'en', 's2');
    const settled = p.then(() => 'answered', (e) => e.message);
    await flush();
    mock.timers.tick(QUERY_IDLE_MS - 1);
    await flush();
    mock.timers.tick(1);
    await flush();
    assert.ok((await settled).includes('took too long'));
  } finally {
    mock.timers.reset();
  }
});
