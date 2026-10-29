// 2026-10-29: the scheme cards showed "Live figures unavailable — showing figures last
// synced 22 Oct 2026" after sign-in. The card read /api/scheme-stats before sign-in (401),
// then waited 10 min to try again. The real WelcomeCard.jsx is bundled with the esbuild
// Vite ships, then imported (as admin.test.js does).
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { build } from 'esbuild';

const path = (rel) => new URL(rel, import.meta.url).pathname.slice(process.platform === 'win32' ? 1 : 0);
const out = await build({
  entryPoints: [path('../src/chat/components/WelcomeCard.jsx')],
  bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', write: false, logLevel: 'silent',
});
globalThis.window ??= { location: { search: '' } };   // api.js reads ?api= at load
const { pollSchemeStats } = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64'));

const flush = () => new Promise((r) => setImmediate(r));

test('reads at once, retries every 30 s while offline, stops retrying once live', async () => {
  mock.timers.enable({ apis: ['setInterval', 'Date'] });
  try {
    const answers = [null, null, { cards: {} }];
    let calls = 0;
    const results = [];
    const stop = pollSchemeStats(() => Promise.resolve(calls < answers.length ? answers[calls++] : (calls++, { cards: {} })), (d) => results.push(d));
    await flush();
    assert.equal(calls, 1);
    assert.deepEqual(results, [null]);
    mock.timers.tick(30_000); await flush();
    assert.equal(calls, 2, 'a failed read is retried after 30 s, not 10 min');
    mock.timers.tick(30_000); await flush();
    assert.equal(calls, 3);
    assert.deepEqual(results.at(-1), { cards: {} });
    mock.timers.tick(5 * 60_000); await flush();
    assert.equal(calls, 3, 'once live, only the 10-min refresh reads again');
    mock.timers.tick(5 * 60_000); await flush();
    assert.equal(calls, 4);
    stop();
    mock.timers.tick(60 * 60_000); await flush();
    assert.equal(calls, 4, 'stopped');
  } finally {
    mock.timers.reset();
  }
});

test('the app reads the card figures only once signed in', () => {
  const app = readFileSync(path('../src/chat/App.jsx'), 'utf8');
  assert.ok(app.includes("signedIn={auth === 'unlocked'}"), 'App.jsx passes the sign-in state to WelcomeCard');
  const card = readFileSync(path('../src/chat/components/WelcomeCard.jsx'), 'utf8');
  assert.ok(card.includes('if (!signedIn)') && card.includes('}, [signedIn]);'),
    'WelcomeCard skips the read while signed out and reads again on sign-in');
});
