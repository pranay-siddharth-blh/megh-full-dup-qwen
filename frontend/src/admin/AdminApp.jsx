import { useCallback, useEffect, useRef, useState } from 'react';
import { isSpace, splitRuns } from '../chat/text.js';

/* The admin console (was web/admin.html): sign-in (adopting the chat console's
   session when it is an admin one), and six hash-routed tabs — Overview,
   Users, Login events, Conversations, Query audit, Answer feedback — over the
   /admin/* API. */

const ADMIN_KEY = 'megh_admin_jwt';
const CHAT_KEY = 'megh_jwt';
const ADMIN_ROLES = ['admin', 'tenant_admin', 'super_admin'];
const TABS = [
  ['overview', 'Overview'], ['users', 'Users'], ['logins', 'Login events'],
  ['conversations', 'Conversations'], ['audit', 'Query audit'], ['feedback', 'Answer feedback'],
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
const Tag = ({ ok, children }) => <span className={'tag ' + (ok ? 'ok' : 'bad')}><i className="tag-dot" />{children}</span>;
const num = (v) => Number(v || 0).toLocaleString('en-IN');

// Line icons (24px grid, stroke = currentColor).
const Ico = ({ children }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const ICONS = {
  overview: <Ico><rect x="3" y="3" width="7" height="8" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="15" width="7" height="6" rx="1.5" /></Ico>,
  users: <Ico><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0113 0" /><path d="M16 4.5a3.5 3.5 0 010 7" /><path d="M21.5 20a6.5 6.5 0 00-4-6" /></Ico>,
  logins: <Ico><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4" /><polyline points="10 17 15 12 10 7" /><line x1="15" y1="12" x2="3" y2="12" /></Ico>,
  conversations: <Ico><path d="M21 12a8 8 0 01-11.6 7.1L4 21l1.9-5.4A8 8 0 1121 12z" /><line x1="8.5" y1="10.5" x2="15.5" y2="10.5" /><line x1="8.5" y1="14" x2="13" y2="14" /></Ico>,
  audit: <Ico><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><polyline points="8.5 12 11 14.5 15.5 10" /></Ico>,
  back: <Ico><path d="M21 11.5a8.4 8.4 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.4 8.4 0 01-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.4 8.4 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z" /></Ico>,
  queries: <Ico><circle cx="11" cy="11" r="7" /><line x1="20" y1="20" x2="16.2" y2="16.2" /></Ico>,
  denied: <Ico><circle cx="12" cy="12" r="9" /><line x1="5.6" y1="5.6" x2="18.4" y2="18.4" /></Ico>,
  feedback: <Ico><path d="M7 10v11H4a1 1 0 01-1-1v-9a1 1 0 011-1h3z" /><path d="M7 10l4-8a2.5 2.5 0 012.5 2.5V8h5.3a2 2 0 012 2.3l-1.2 8A2 2 0 0117.6 20H7" /></Ico>,
};
// Navigation groups and each page's heading.
const NAV = [
  ['Menu', ['overview', 'users']],
  ['Activity', ['logins', 'conversations', 'audit', 'feedback']],
];
const PAGE = {
  overview: ['Overview', 'Usage of Megh One AI at a glance'],
  users: ['Users', 'Create officers and manage their access'],
  logins: ['Login events', 'Sign-ins, sign-outs and failed attempts'],
  conversations: ['Conversations', 'Officer chat threads and every turn in them'],
  audit: ['Query audit', 'Every question, how it was answered and whether it was allowed'],
  feedback: ['Answer feedback', 'What officers marked 👍 helpful or 👎 not helpful, with their note'],
};
const initials = (s) => splitRuns(String(s || '?').trim(), (c) => isSpace(c) || c === '.' || c === '_' || c === '-').filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('') || '?';
// A card's title row: heading, an optional count and anything on the right.
const CardHead = ({ title, count, children }) => (
  <div className="card-head">
    <h2>{title}{count != null && <span className="count-pill">{num(count)}</span>}</h2>
    {children && <div className="card-tools">{children}</div>}
  </div>
);

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
      <div className="kpis">
        {[
          ['queries', 'Queries', stats.queries, 'Questions asked by officers', ''],
          ['denied', 'Denied', stats.denied, stats.queries
            ? `${((100 * (stats.denied || 0)) / stats.queries).toFixed(1)}% of all queries` : 'No queries yet', 'bad'],
          ['users', 'Active officers', stats.active_users, 'Accounts in use', ''],
          ['conversations', 'Conversations', stats.conversations, 'Chat threads started', ''],
        ].map(([icon, label, value, note, tone]) => (
          <div key={label} className={'kpi ' + tone}>
            <div className="kpi-top"><span className="kpi-label">{label}</span><span className="kpi-ico">{ICONS[icon]}</span></div>
            <div className="kpi-value">{num(value)}</div>
            <div className="kpi-note">{note}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <CardHead title="Recent logins" count={events ? events.length : null} />
        <div className="scroll">{events && <LogTable events={events} />}</div>
      </div>
    </>
  );
}

// ── Users ───────────────────────────────────────────────────────────────────
// Roles not offered when creating a user: tenant_admin/admin are unused
// (super_admin covers admin duties); analyst/public are system fallbacks.
const HIDDEN_ROLES = new Set(['tenant_admin', 'admin', 'analyst', 'public']);
// Least privilege first: the form starts on the narrowest role, and an admin
// role is only ever picked on purpose (audit 2026-10-23: "Create officer"
// defaulted to super_admin; E11). Roles not listed here follow, in API order.
const LEAST_FIRST = ['block_officer', 'district_officer', 'state_officer', 'super_admin'];
export const roleOptions = (roles) => {
  const offered = Object.keys(roles || {}).filter((r) => !HIDDEN_ROLES.has(r));
  return [...LEAST_FIRST.filter((r) => offered.includes(r)), ...offered.filter((r) => !LEAST_FIRST.includes(r))];
};
const EMPTY_FORM = { username: '', name: '', password: '', role: '', districts: '', blocks: '', schemes: '', tenant: '' };
const csv = (v) => { const s = String(v || '').trim(); return s ? s.split(',').map((x) => x.trim()).filter(Boolean) : null; };

function Users({ me }) {
  const [roles, setRoles] = useState(null);
  const [users, setUsers] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [err, setErr] = useState('');
  const [pw, setPw] = useState({ id: null, value: '', err: '' });   // the inline password reset
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    try {
      const r = roles || (await api('/admin/roles')).roles;
      if (!roles) setRoles(r);
      const { users: list } = await api('/admin/users');
      setUsers(list);
      setForm((f) => ({ ...f, role: f.role || roleOptions(r)[0] || '' }));
    } catch (e) { /* 401 handled by api() */ }
  }, [roles]);
  useEffect(() => { load(); }, [load]);

  if (!users || !roles) return <Loading />;
  const roleOpts = roleOptions(roles);
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
  // A masked field in the row, not window.prompt() (which shows the password
  // in clear text and cannot be styled or validated; audit 2026-10-23, E11).
  const savePw = async () => {
    if (pw.value.length < 8) { setPw({ ...pw, err: 'At least 8 characters' }); return; }
    try {
      await api('/admin/users/' + pw.id, { method: 'PATCH', body: JSON.stringify({ password: pw.value }) });
      setPw({ id: null, value: '', err: '' });
      setNotice('Password updated');
    } catch (e) { setPw({ ...pw, err: e.message }); }
  };
  const req = <span style={{ color: 'var(--red)' }}>*</span>;

  return (
    <>
      <div className="card">
        <CardHead title="Create officer / admin" />
        <div className="muted" style={{ fontSize: 12, marginTop: -6 }}>All fields marked {req} are required.</div>
        <div className="row" style={{ marginTop: 8 }}>
          <div><label>Username {req}</label><input value={form.username} onChange={set('username')} /></div>
          <div><label>Name {req}</label><input value={form.name} onChange={set('name')} /></div>
          <div><label>Password {req}</label><input type="password" autoComplete="new-password" placeholder="min 8 characters" value={form.password} onChange={set('password')} /></div>
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
        <div className="form-foot">
          <button className="primary" type="button" onClick={createUser}>Create</button>
          <span className="err"> {err}</span>
        </div>
      </div>
      <div className="card">
        <CardHead title="Users" count={users.length}>{notice && <span className="muted" role="status">{notice}</span>}</CardHead>
        <div className="scroll">
          <table>
            <thead><tr><th>id</th><th>username</th><th>name</th><th>role</th><th>districts</th><th>schemes</th><th>active</th><th>last login</th><th /></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id}>
                  <td className="muted">{u.user_id}</td>
                  <td><span className="who-cell"><span className="mini-av">{initials(u.name || u.username)}</span>{u.username}</span></td>
                  <td>{u.name}</td><td><span className="chip">{u.role}</span></td>
                  <td>{(u.districts || []).join(', ')}</td><td>{(u.schemes || []).join(', ')}</td>
                  <td><Tag ok={isOnline(u)}>{isOnline(u) ? 'yes' : 'no'}</Tag></td>
                  <td className="muted">{fmtTs(u.last_login_at)}</td>
                  <td className="actions-cell">
                    <button className="danger sm" type="button" onClick={() => deactivate(u.user_id)}>Deactivate</button>{' '}
                    <button className="sm" type="button" onClick={() => { setNotice(''); setPw({ id: u.user_id, value: '', err: '' }); }}>Reset pw</button>{' '}
                    {me.is_super && <button className="danger sm" type="button" onClick={() => deleteUser(u.user_id, u.username)}>Delete</button>}
                    {pw.id === u.user_id && (
                      <form className="pw-inline" onSubmit={(e) => { e.preventDefault(); savePw(); }}>
                        <input type="password" autoComplete="new-password" aria-label={'New password for ' + u.username}
                               placeholder="new password, min 8" value={pw.value} autoFocus
                               onChange={(e) => setPw({ ...pw, value: e.target.value, err: '' })} />
                        <button className="primary sm" type="submit">Save</button>
                        <button className="sm" type="button" onClick={() => setPw({ id: null, value: '', err: '' })}>Cancel</button>
                        {pw.err && <span className="err">{pw.err}</span>}
                      </form>
                    )}
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
    <div className="card">
      <CardHead title="Login events" count={events ? events.length : null} />
      <div className="scroll">{events ? <LogTable events={events} /> : 'loading…'}</div>
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
      <div className="card">
        <CardHead title="Officer conversations" count={convs ? convs.length : null} />
        <div className="scroll">
          {!convs ? 'loading…' : (
            <table>
              <thead><tr><th>started</th><th>last</th><th>officer</th><th>turns</th><th>title</th><th /></tr></thead>
              <tbody>
                {convs.map((c) => (
                  <tr key={c.conv_id}>
                    <td className="muted">{fmtTs(c.started_at)}</td><td className="muted">{fmtTs(c.last_at)}</td>
                    <td>{c.username || c.user_id}</td><td>{c.turn_count}</td><td>{c.title}</td>
                    <td><button className="sm" type="button" onClick={() => open(c.conv_id)}>Open</button></td>
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
              <CardHead title={`Conversation #${detail.id}`} count={detail.turns.length} />
              {detail.turns.map((t, i) => (
                <div key={i} className="turn">
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
      <CardHead title="Query audit" count={records ? records.length : null}>
        <label className="toggle">
          <input type="checkbox" checked={deniedOnly} onChange={(e) => setDeniedOnly(e.target.checked)} />
          <span className="toggle-track"><span className="toggle-knob" /></span> Denied only
        </label>
      </CardHead>
      <div className="scroll">
        {!records ? 'loading…' : (
          <table>
            <thead><tr><th>time</th><th>officer</th><th>question</th><th>route</th><th>grain</th><th>schemes</th><th>rows</th><th>ms</th><th>result</th></tr></thead>
            <tbody>
              {records.map((r, i) => (
                <tr key={i}>
                  <td className="muted">{fmtTs(r.created_at)}</td><td>{r.username}</td><td>{r.question}</td>
                  <td>{r.route}</td><td>{r.granularity}</td><td>{(r.schemes || []).join(', ')}</td>
                  <td>{r.row_count ?? ''}</td><td>{Math.round(r.latency_ms || 0)}</td>
                  <td>{r.allowed ? <Tag ok>ok</Tag> : <span className="tag bad"><i className="tag-dot" />denied: {r.denied_by}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Answer feedback (RAG upgrade Phase 6) ───────────────────────────────────
// The 👍 / 👎 officers gave in the chat. A 👎 on a knowledge answer is the
// lead for a wrong or incomplete answer (and a new tests/rag_eval question).
function Feedback() {
  const [downOnly, setDownOnly] = useState(false);
  const [data, setData] = useState(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    setData(null); setErr('');
    api('/admin/feedback?limit=300' + (downOnly ? '&rating=-1' : ''))
      .then(setData).catch((e) => setErr(String(e.message || e)));
  }, [downOnly]);
  const rows = data ? data.feedback : null;
  return (
    <>
      <div className="fb-totals">
        <div className="fb-total up"><span className="fb-total-n">{data ? data.up : '–'}</span><span>👍 Helpful</span></div>
        <div className="fb-total down"><span className="fb-total-n">{data ? data.down : '–'}</span><span>👎 Not helpful</span></div>
      </div>
      <div className="card">
        <CardHead title="Votes" count={rows ? rows.length : null}>
          <label className="toggle">
            <input type="checkbox" checked={downOnly} onChange={(e) => setDownOnly(e.target.checked)} />
            <span className="toggle-track"><span className="toggle-knob" /></span> 👎 only
          </label>
        </CardHead>
        <div className="scroll">
          {err ? <div className="muted">Could not load feedback: {err}</div> : !rows ? 'loading…' : !rows.length ? (
            <div className="muted">No feedback yet.</div>
          ) : (
            <table className="fb-table">
              <thead><tr><th>time</th><th>officer</th><th>vote</th><th>question</th><th>answer</th><th>source</th><th>note</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.feedback_id}>
                    <td className="muted">{fmtTs(r.updated_at)}</td>
                    <td>{r.username}</td>
                    <td>{r.rating > 0 ? <Tag ok>👍</Tag> : <span className="tag bad"><i className="tag-dot" />👎</span>}</td>
                    <td className="fb-cell">{r.question}</td>
                    <td className="fb-cell fb-ans" title={r.answer}>{(r.answer || '').slice(0, 220)}{(r.answer || '').length > 220 ? '…' : ''}</td>
                    <td className="fb-cell muted">{(r.citations || []).map((c) => c.title + (c.section ? ' › ' + c.section : '')).join('; ') || r.route || ''}</td>
                    <td className="fb-cell">{r.comment || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
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
  // Sign out of this console. The chat's copy goes too when it is the same
  // token (the console adopted it): on a shared terminal nothing stays signed in.
  const signOut = useCallback(() => {
    if (session.token) api('/api/auth/logout', { method: 'POST' }).catch(() => {});
    if (session.token && ls.get(CHAT_KEY) === session.token) ls.del(CHAT_KEY);
    ls.del(ADMIN_KEY);
    session.token = ''; session.signedIn = false;
    setMe(null); setU(''); setP('');
    setView('login');
  }, []);
  useEffect(() => { session.onExpired = showLogin; }, [showLogin]);

  useEffect(() => {
    const onHash = () => setTab(currentTab());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const boot = useCallback(async () => {
    const m = await api('/api/auth/me');
    m.is_super = m.role === 'super_admin';
    // Adopted from the chat console: keep this console's own copy. Signing out
    // of the chat removes it too (api.js logoutRemote), and so does Sign out here.
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
      <div className="login-page"><div className="login card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 11, marginBottom: 18 }}>
          <div className="brand-logo lg">M</div>
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
      </div></div>
    );
  }

  const Panel = { overview: Overview, users: Users, logins: Logins, conversations: Conversations, audit: Audit, feedback: Feedback }[tab] || Overview;
  const label = Object.fromEntries(TABS);
  const [title, subtitle] = PAGE[tab] || PAGE.overview;
  const tenant = me.tenant ? me.tenant.name : '—';
  return (
    <div className="adm">
      <aside className="adm-side">
        <div className="adm-brand">
          <div className="brand-logo">M</div>
          <div><div className="adm-brand-name">Megh One AI</div><div className="adm-brand-sub">Admin Console</div></div>
        </div>
        <nav className="adm-nav" aria-label="Admin sections">
          {NAV.map(([section, keys]) => (
            <div className="adm-sec" key={section}>
              <div className="adm-sec-label">{section}</div>
              {keys.map((k) => (
                <a key={k} href={'#' + k} className={'adm-link' + (k === tab ? ' active' : '')} aria-current={k === tab ? 'page' : undefined}>
                  {ICONS[k]}<span>{label[k]}</span>
                </a>
              ))}
            </div>
          ))}
          <div className="adm-sec">
            <div className="adm-sec-label">General</div>
            <a className="adm-link" href="/megh-chat" title="Return to the chat console">{ICONS.back}<span>Back to chat</span></a>
          </div>
        </nav>
        <div className="adm-me">
          <span className="mini-av lg">{initials(me.name || me.username)}</span>
          <div className="adm-me-text"><div className="adm-me-name">{me.username}</div><div className="adm-me-role">{me.role} · {tenant}</div></div>
        </div>
      </aside>
      <div className="adm-main">
        <header className="adm-top">
          <div className="adm-title"><h1>{title}</h1><p>{subtitle}</p></div>
          <div className="adm-top-right">
            <div className="adm-user">
              <span className="mini-av">{initials(me.name || me.username)}</span>
              <div><div className="adm-user-name">{me.username}</div><div className="adm-user-role">{me.role}</div></div>
            </div>
            <button className="sm" type="button" onClick={signOut}>Sign out</button>
          </div>
        </header>
        <main className="adm-content"><Panel key={tab} me={me} /></main>
      </div>
    </div>
  );
}
