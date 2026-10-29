// E11 (2026-10-29): "Create officer" starts on the least-privileged role. The
// real AdminApp.jsx is bundled with the esbuild Vite ships, then imported.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';

const out = await build({
  entryPoints: [new URL('../src/admin/AdminApp.jsx', import.meta.url).pathname.slice(process.platform === 'win32' ? 1 : 0)],
  bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', write: false, logLevel: 'silent',
});
const { roleOptions } = await import('data:text/javascript;base64,' + Buffer.from(out.outputFiles[0].text).toString('base64'));

// The roles /admin/roles returns (app/auth.py ROLE_PERMISSIONS), in its order.
const API_ROLES = Object.fromEntries(['super_admin', 'tenant_admin', 'admin', 'state_officer', 'district_officer',
  'block_officer', 'analyst', 'public'].map((r) => [r, {}]));

test('the role list starts on the narrowest role, admin last', () => {
  assert.deepEqual(roleOptions(API_ROLES), ['block_officer', 'district_officer', 'state_officer', 'super_admin']);
});

test('a role the console does not know is still offered, after the known ones', () => {
  assert.deepEqual(roleOptions({ super_admin: {}, auditor: {}, block_officer: {} }), ['block_officer', 'super_admin', 'auditor']);
});
