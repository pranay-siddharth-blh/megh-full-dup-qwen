import { useCallback, useEffect, useRef, useState } from 'react';

/* The admin console (was web/admin.html): sign-in (adopting the chat console's
   session when it is an admin one), and five hash-routed tabs — Overview,
   Users, Login events, Conversations, Query audit — over the /admin/* API. */

const ADMIN_KEY = 'megh_admin_jwt';
const CHAT_KEY = 'megh_jwt';
const ADMIN_ROLES = ['admin', 'tenant_admin', 'super_admin'];
const TABS = [
  ['overview', 'Overview'], ['users', 'Users'], ['logins', 'Login events'],
  ['conversations', 'Conversations'], ['audit', 'Query audit'],
];
const ls = {
  get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
};
const fmtTs = (s) => (s ? new Date(s).toLocaleString() : '');
// "active" = signed in: the most recent auth event is a login, not a logout.
const isOnline = (u) => !!u.is_active && !!u.is_logged_in;
const currentTab = () => {
  const t = window.location.hash.replace('#', '') || 'overview';
  return TABS.some(([k]) => k === t) ? t : 'overview';
};

// Token and sign-in state live outside React so api() can use them anywhere.
const session = { token: ls.get(ADMIN_KEY) || ls.get(CHAT_KEY) || '', signedIn: false, onExpired: () => {} };

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(session.token ? { Authorization: 'Bearer ' + session.token } : {}),
      ...(opts.headers || {}),
    },
  });
  if (r.status === 401) {
    // While probing stored sessions at startup the caller decides; only a 401
    // during normal use tears the UI down.
    if (session.signedIn) { session.token = ''; ls.del(ADMIN_KEY); session.onExpired(); }
    throw new Error('unauthorized');
  }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || JSON.stringify(body));
  return body;
}

const Loading = () => <div className="card"><div className="muted">loading…</div></div>;
const Tag = ({ ok, children }) => <span className={'tag ' + (ok ? 'ok' : 'bad')}>{children}</span>;

function LogTable({ events }) {
  return (
    <table>
      <thead><tr><th>time</th><th>event</th><th>user</th><th>ok</th><th>ip</th><th>detail</th></tr></thead>
      <tbody>
        {events.map((e, i) => (
          <tr key={i}>
            <td className="muted">{fmtTs(e.created_at)}</td><td>{e.event}</td><td>{e.username}</td>
            <td><Tag ok={e.ok}>{e.ok ? 'ok' : 'fail'}</Tag></td>
            <td className="muted">{e.ip}</td><td className="muted">{e.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Overview ────────────────────────────────────────────────────────────────
function Overview() {
  const [stats, setStats] = useState(null);
  const [events, setEvents] = useState(null);
  useEffect(() => {
    api('/admin/stats').then(setStats).catch(() => {});
    api('/admin/logins?limit=15').then((l) => setEvents(l.events)).catch(() => {});
  }, []);
  if (!stats) return <Loading />;
  return (
    <>
      <div className="grid4">
        <div className="card"><div className="muted">Queries</div><div className="stat">{stats.queries ?? 0}</div></div>
        <div className="card"><div className="muted">Denied</div><div className="stat" style={{ color: 'var(--bad)' }}>{stats.denied ?? 0}</div></div>
        <div className="card"><div className="muted">Active officers</div><div className="stat">{stats.active_users ?? 0}</div></div>
        <div className="card"><div className="muted">Conversations</div><div className="stat">{stats.conversations ?? 0}</div></div>
      </div>
      <div className="card"><b>Recent logins</b>
        <div className="scroll" style={{ marginTop: 8 }}>{events && <LogTable events={events} />}</div>
      </div>
    </>
  );
}

// ── Users ───────────────────────────────────────────────────────────────────
// Roles not offered when creating a user: tenant_admin/admin are unused
// (super_admin covers admin duties); analyst/public are system fallbacks.
const HIDDEN_ROLES = new Set(['tenant_admin', 'admin', 'analyst', 'public']);
const EMPTY_FORM = { username: '', name: '', password: '', role: '', districts: '', blocks: '', schemes: '', tenant: '' };
const csv = (v) => { const s = String(v || '').trim(); return s ? s.split(',').map((x) => x.trim()).filter(Boolean) : null; };

function Users({ me }) {
  const [roles, setRoles] = useState(null);
  const [users, setUsers] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try {
      const r = roles || (await api('/admin/roles')).roles;
      if (!roles) setRoles(r);
      const { users: list } = await api('/admin/users');
      setUsers(list);
      setForm((f) => ({ ...f, role: f.role || Object.keys(r).filter((x) => !HIDDEN_ROLES.has(x))[0] || '' }));
    } catch (e) { /* 401 handled by api() */ }
  }, [roles]);
  useEffect(() => { load(); }, [load]);

  if (!users || !roles) return <Loading />;
  const roleOpts = Object.keys(roles).filter((r) => !HIDDEN_ROLES.has(r));
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const createUser = async () => {
    setErr('');
    const body = {
      username: form.username.trim(), name: form.name.trim(), password: form.password, role: form.role,
      districts: csv(form.districts), blocks: csv(form.blocks), schemes: csv(form.schemes),
    };
    // Every field is mandatory except the tenant id (defaults to the caller's).
    const missing = [];
    if (!body.username) missing.push('Username');
    if (!body.name) missing.push('Name');
    if (!body.password) missing.push('Password');
    if (!body.role) missing.push('Role');
    if (!body.districts) missing.push('Districts');
    if (!body.blocks) missing.push('Blocks');
    if (!body.schemes) missing.push('Schemes');
    if (missing.length) { setErr('Required: ' + missing.join(', ')); return; }
    if (body.password.length < 8) { setErr('Password must be at least 8 characters'); return; }
    if (me.is_super && form.tenant.trim()) body.tenant_id = +form.tenant.trim();
    try {
      await api('/admin/users', { method: 'POST', body: JSON.stringify(body) });
      setForm({ ...EMPTY_FORM, role: form.role });
      load();
    } catch (e) { setErr(e.message); }
  };
  const deactivate = async (id) => {
    if (!window.confirm('Deactivate user ' + id + '?')) return;
    await api('/admin/users/' + id, { method: 'DELETE' }); load();
  };
  const deleteUser = async (id, uname) => {
    if (!window.confirm('Permanently DELETE user ' + id + ' (' + uname + ')?\n\nThis removes the account for good. Their past login/audit history stays but shows no linked account. This cannot be undone.')) return;
    if (window.prompt('Type the username to confirm deletion:') !== uname) { window.alert('Username did not match — nothing deleted.'); return; }
    await api('/admin/users/' + id + '?hard=true', { method: 'DELETE' }); load();
  };
  const resetPw = async (id) => {
    const p = window.prompt('New password (min 8 chars):');
    if (!p) return;
    await api('/admin/users/' + id, { method: 'PATCH', body: JSON.stringify({ password: p }) });
    window.alert('Password updated');
  };
  const req = <span style={{ color: 'var(--red)' }}>*</span>;

  return (
    <>
      <div className="card">
        <b>Create officer / admin</b>
        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>All fields marked {req} are required.</div>
        <div className="row" style={{ marginTop: 8 }}>
          <div><label>Username {req}</label><input value={form.username} onChange={set('username')} /></div>
          <div><label>Name {req}</label><input value={form.name} onChange={set('name')} /></div>
          <div><label>Password {req}</label><input type="text" placeholder="min 8 characters" value={form.password} onChange={set('password')} /></div>
          <div><label>Role {req}</label>
            <select value={form.role} onChange={set('role')}>{roleOpts.map((r) => <option key={r}>{r}</option>)}</select>
          </div>
        </div>
        <div className="row">
          <div><label>Districts (comma, UPPERCASE) {req}</label><input placeholder="WEST GARO HILLS" value={form.districts} onChange={set('districts')} /></div>
          <div><label>Blocks (comma) {req}</label><input value={form.blocks} onChange={set('blocks')} /></div>
          <div><label>Schemes (comma) {req}</label><input placeholder="MGNREGA, PMAY-G" value={form.schemes} onChange={set('schemes')} /></div>
          {me.is_super && <div><label>Tenant id</label><input placeholder="(caller tenant)" value={form.tenant} onChange={set('tenant')} /></div>}
        </div>
        <div style={{ marginTop: 10 }}>
          <button className="primary" type="button" onClick={createUser}>Create</button>
          <span className="err"> {err}</span>
        </div>
      </div>
      <div className="card"><b>Users ({users.length})</b>
        <div className="scroll" style={{ marginTop: 8 }}>
          <table>
            <thead><tr><th>id</th><th>username</th><th>name</th><th>role</th><th>districts</th><th>schemes</th><th>active</th><th>last login</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id}>
                  <td>{u.user_id}</td><td>{u.username}</td><td>{u.name}</td><td>{u.role}</td>
                  <td>{(u.districts || []).join(', ')}</td><td>{(u.schemes || []).join(', ')}</td>
                  <td><Tag ok={isOnline(u)}>{isOnline(u) ? 'yes' : 'no'}</Tag></td>
                  <td className="muted">{fmtTs(u.last_login_at)}</td>
                  <td>
                    <button className="danger" type="button" onClick={() => deactivate(u.user_id)}>Deactivate</button>{' '}
                    <button type="button" onClick={() => resetPw(u.user_id)}>Reset pw</button>{' '}
                    {me.is_super && <button className="danger" type="button" onClick={() => deleteUser(u.user_id, u.username)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

// ── Login events ────────────────────────────────────────────────────────────
function Logins() {
  const [events, setEvents] = useState(null);
  useEffect(() => { api('/admin/logins?limit=300').then((l) => setEvents(l.events)).catch(() => {}); }, []);
  return (
    <div className="card"><b>Login events</b>
      <div className="scroll" style={{ marginTop: 8 }}>{events ? <LogTable events={events} /> : 'loading…'}</div>
    </div>
  );
}

// ── Conversations ───────────────────────────────────────────────────────────
function Conversations() {
  const [convs, setConvs] = useState(null);
  const [detail, setDetail] = useState(null);   // {id, turns|null}
  useEffect(() => { api('/admin/conversations?limit=200').then((d) => setConvs(d.conversations)).catch(() => {}); }, []);
  const open = async (id) => {
    setDetail({ id, turns: null });
    const { turns } = await api('/admin/conversations/' + id);
    setDetail({ id, turns });
  };
  return (
    <>
      <div className="card"><b>Officer conversations</b>
        <div className="scroll" style={{ marginTop: 8 }}>
          {!convs ? 'loading…' : (
            <table>
              <thead><tr><th>started</th><th>last</th><th>officer</th><th>turns</th><th>title</th><th /></tr></thead>
              <tbody>
                {convs.map((c) => (
                  <tr key={c.conv_id}>
                    <td className="muted">{fmtTs(c.started_at)}</td><td className="muted">{fmtTs(c.last_at)}</td>
                    <td>{c.username || c.user_id}</td><td>{c.turn_count}</td><td>{c.title}</td>
                    <td><button type="button" onClick={() => open(c.conv_id)}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      {detail && (
        <div className="card">
          {!detail.turns ? 'loading…' : (
            <>
              <b>Conversation #{detail.id}</b> — {detail.turns.length} turns
              {detail.turns.map((t, i) => (
                <div key={i} style={{ margin: '10px 0', borderLeft: '2px solid var(--line)', paddingLeft: 10 }}>
                  <div><b>Q:</b> {t.question} {t.rewritten_question && <span className="muted">→ {t.rewritten_question}</span>}</div>
                  <div><b>A:</b> {t.answer}</div>
                  <div className="muted">
                    {t.route} · {t.allowed ? 'allowed' : <span className="tag bad">denied: {t.denied_by}</span>} ·{' '}
                    {t.row_count ?? '–'} rows · {Math.round(t.latency_ms || 0)} ms
                  </div>
                  {t.sql && <pre>{t.sql}</pre>}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </>
  );
}

// ── Query audit ─────────────────────────────────────────────────────────────
function Audit() {
  const [deniedOnly, setDeniedOnly] = useState(false);
  const [records, setRecords] = useState(null);
  useEffect(() => {
    setRecords(null);
    api('/admin/audit?limit=400' + (deniedOnly ? '&denied_only=true' : '')).then((d) => setRecords(d.records)).catch(() => {});
  }, [deniedOnly]);
  return (
    <div className="card">
      <b>Query audit</b>
      <label style={{ display: 'inline-block', marginLeft: 10 }}>
        <input type="checkbox" style={{ width: 'auto' }} checked={deniedOnly} onChange={(e) => setDeniedOnly(e.target.checked)} /> denied only
      </label>
      <div className="scroll" style={{ marginTop: 8 }}>
        {!records ? 'loading…' : (
          <table>
            <thead><tr><th>time</th><th>officer</th><th>question</th><th>route</th><th>grain</th><th>schemes</th><th>rows</th><th>ms</th><th>result</th></tr></thead>
            <tbody>
              {records.map((r, i) => (
                <tr key={i}>
                  <td className="muted">{fmtTs(r.created_at)}</td><td>{r.username}</td><td>{r.question}</td>
                  <td>{r.route}</td><td>{r.granularity}</td><td>{(r.schemes || []).join(', ')}</td>
                  <td>{r.row_count ?? ''}</td><td>{Math.round(r.latency_ms || 0)}</td>
                  <td>{r.allowed ? <Tag ok>ok</Tag> : <span className="tag bad">denied: {r.denied_by}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Shell ───────────────────────────────────────────────────────────────────
export default function AdminApp() {
  const [view, setView] = useState('boot');   // boot | login | app
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState(currentTab);
  const [loginErr, setLoginErr] = useState('');
  const [u, setU] = useState('');
  const [p, setP] = useState('');
  const booted = useRef(false);

  const showLogin = useCallback(() => setView('login'), []);
  useEffect(() => { session.onExpired = showLogin; }, [showLogin]);

  useEffect(() => {
    const onHash = () => setTab(currentTab());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const boot = useCallback(async () => {
    const m = await api('/api/auth/me');
    m.is_super = m.role === 'super_admin';
    // Adopted from the chat console: keep this console's own copy, so signing
    // out of one page does not sign the other out.
    if (session.token && !ls.get(ADMIN_KEY)) ls.set(ADMIN_KEY, session.token);
    if (!ADMIN_ROLES.includes(m.role)) {
      // A valid session, but not an admin one: every panel would 403.
      window.alert('Your account does not have administrator access.');
      window.location.href = '/megh-chat';
      return;
    }
    session.signedIn = true;
    setMe(m);
    setView('app');
  }, []);

  // Try every stored session: this console's own token, then the chat's.
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    (async () => {
      const candidates = [ls.get(ADMIN_KEY), ls.get(CHAT_KEY)].filter(Boolean);
      for (const t of candidates) {
        session.token = t;
        try { await boot(); return; } catch (e) {
          if (t === ls.get(ADMIN_KEY)) ls.del(ADMIN_KEY);
          if (t === ls.get(CHAT_KEY)) ls.del(CHAT_KEY);
        }
      }
      session.token = '';
      showLogin();
    })();
  }, [boot, showLogin]);

  const doLogin = async () => {
    setLoginErr('');
    try {
      const b = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: u.trim(), password: p }) });
      session.token = b.access_token;
      ls.set(ADMIN_KEY, session.token);
      await boot();
    } catch (e) { setLoginErr(e.message); }
  };

  if (view === 'boot') return null;

  if (view === 'login') {
    return (
      <div className="login card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 16 }}>
          <div className="brand-logo">M</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 16 }}>Admin Console</h1>
            <div className="muted" style={{ fontSize: 12 }}>Megh One AI · MGNREGA / PMAY-G</div>
          </div>
        </div>
        <label>Username</label><input autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} />
        <label>Password</label>
        <input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') doLogin(); }} />
        <div style={{ marginTop: 14, display: 'flex', gap: 10 }}>
          <button className="primary" style={{ flex: 1 }} type="button" onClick={doLogin}>Sign in</button>
        </div>
        <div className="err">{loginErr}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          First run: <code>POST /api/auth/bootstrap</code> to create a super_admin.
        </div>
      </div>
    );
  }

  const Panel = { overview: Overview, users: Users, logins: Logins, conversations: Conversations, audit: Audit }[tab] || Overview;
  return (
    <>
      <header>
        <div className="brand-logo">M</div>
        <h1>Megh One AI · Admin Console</h1>
        <span className="who">{me.username} · {me.role} · {me.tenant ? me.tenant.name : '—'}</span>
        <button className="primary" type="button" title="Return to the chat console" onClick={() => { window.location.href = '/megh-chat'; }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
               style={{ width: 14, height: 14, verticalAlign: -2, marginRight: 6 }}>
            <path d="M21 11.5a8.4 8.4 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.4 8.4 0 01-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.4 8.4 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" />
          </svg>Back to chat
        </button>
      </header>
      <div className="wrap">
        <nav>
          {TABS.map(([k, label]) => <a key={k} href={'#' + k} className={k === tab ? 'active' : ''}>{label}</a>)}
        </nav>
        <main><Panel key={tab} me={me} /></main>
      </div>
    </>
  );
}
