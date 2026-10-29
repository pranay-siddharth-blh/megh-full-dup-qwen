/* Backend connection for the chat console. Same contract as web/ai_query.html:
   POST /api/auth/login -> JWT kept in localStorage under megh_jwt; every /api/*
   call carries it as a Bearer token; a 401 anywhere drops the token and returns
   to the sign-in gate. The API is same-origin; `?api=<origin>` overrides it for
   debugging. */

const _apiParam = new URLSearchParams(window.location.search).get('api') || '';
export const API_BASE = _apiParam.endsWith('/') ? _apiParam.slice(0, -1) : _apiParam;   // no trailing slash
export const MEGH_JWT_KEY = 'megh_jwt';

let token = '';
try { token = localStorage.getItem(MEGH_JWT_KEY) || ''; } catch (e) { /* storage blocked */ }

export const getToken = () => token;
export function setToken(t) {
  token = t || '';
  try {
    if (token) localStorage.setItem(MEGH_JWT_KEY, token);
    else localStorage.removeItem(MEGH_JWT_KEY);
  } catch (e) { /* storage blocked */ }
}

// The app registers what a 401 does (log out + show the gate with a message).
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn || (() => {}); }

export function authHeaders(extra) {
  return Object.assign({}, extra || {}, token ? { Authorization: 'Bearer ' + token } : {});
}

// Every authenticated API call. On 401 it clears the session, shows the login
// gate, then throws so the caller stops.
export async function apiFetch(path, opts) {
  opts = { ...(opts || {}) };
  opts.headers = authHeaders(opts.headers);
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (res.status === 401) {
    onUnauthorized('Your session has expired — please sign in again.');
    throw new Error('unauthorized');
  }
  return res;
}

// ── Session id (sessionStorage, per tab) ─────────────────────────────────────
const SESSION_KEY = 'focusSessionId';
export function generateSessionId() {
  const id = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  try { sessionStorage.setItem(SESSION_KEY, id); } catch (e) { /* ignore */ }
  return id;
}
export function storedSessionId() {
  try { return sessionStorage.getItem(SESSION_KEY) || generateSessionId(); } catch (e) { return generateSessionId(); }
}
// Start a brand-new conversation: rotate the id so the backend loads NO prior
// context (the previous district must not bleed into an unrelated question).
export function resetSessionId() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch (e) { /* ignore */ }
  return generateSessionId();
}
export function adoptSessionId(sid) {
  try { sessionStorage.setItem(SESSION_KEY, sid); } catch (e) { /* ignore */ }
}

// ── Auth ────────────────────────────────────────────────────────────────────
export async function login(username, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  const data = await res.json().catch(() => ({}));
  return { ok: res.ok, data };
}

// Bounded: a stalled /api/auth/me must fall through to the sign-in screen.
export async function fetchMe(timeoutMs = 8000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders(), signal: ctrl.signal });
    if (!res.ok) { const e = new Error('stale token'); e.status = res.status; throw e; }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// The admin console's own copy of a token (AdminApp.jsx ADMIN_KEY).
const MEGH_ADMIN_JWT_KEY = 'megh_admin_jwt';

// Signing out of the chat signs the admin console out too: a JWT is stateless
// (the server's logout only logs it), so a copy left in localStorage stays
// usable on a shared terminal (audit 2026-10-23, E11).
export function logoutRemote() {
  try { localStorage.removeItem(MEGH_ADMIN_JWT_KEY); } catch (e) { /* storage blocked */ }
  if (!token) return;
  fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', headers: authHeaders() }).catch(() => {});
}

// ── Query ───────────────────────────────────────────────────────────────────
// How long a question may go with NOTHING arriving, so a stalled backend can
// never leave the typing dots up forever. On the stream every chunk (a token, a
// step, the server's ": ping" keep-alive) restarts it: a long but healthy answer
// is never cut (E11 / UI-03, 2026-10-29; it was a 75 s ceiling on the whole
// answer). The plain request has no chunks, so there it is the whole wait.
export const QUERY_IDLE_MS = 75000;
const TIMED_OUT = 'The request took too long and timed out. The service may be busy — please try again in a moment.';
const UNREACHABLE = 'Could not reach the server. Please check your connection and try again.';

// Thrown when the officer pressed Stop (not a failure: the UI says "Stopped").
export class StoppedError extends Error {
  constructor() { super('stopped'); this.name = 'StoppedError'; }
}

// The network, not the question: the server can't be reached, the proxy
// answers for an app that is gone, or the app can't reach megh_db (the VPN
// dropped). The UI shows the connection banner and asks again once it's back,
// instead of an error under the question. "Busy" and "took too long" are not
// connection errors: the server answered.
export class ConnectionError extends Error {
  constructor(message) { super(message || UNREACHABLE); this.name = 'ConnectionError'; }
}
// The router's 503 for an unreachable megh_db (DatabaseUnavailableError, KI-025).
// "couldn't reach the megh one data service" (any case, any apostrophe).
const DATA_SERVICE_DOWN = (detail) => {
  const low = String(detail).toLowerCase();
  for (let i = low.indexOf('couldn'); i !== -1; i = low.indexOf('couldn', i + 1)) {
    const c = low[i + 6];
    if (c !== undefined && c !== '\n' && c !== '\r' && c !== '\u2028' && c !== '\u2029'
      && low.startsWith('t reach the megh one data service', i + 7)) return true;
  }
  return false;
};
const isConnectionStatus = (status, detail, fromApp) =>
  (status === 503 && DATA_SERVICE_DOWN(detail || ''))
  // 502/503/504 without the app's own JSON detail come from nginx: the app is down or unreachable.
  || ([502, 503, 504].includes(status) && !fromApp);

// One AbortController for a question: QUERY_IDLE_MS of silence, or the caller's
// Stop (`stopSignal`). `alive()` restarts the silence timer; `stopped()` tells
// the two aborts apart afterwards.
export function questionAbort(stopSignal, idleMs = QUERY_IDLE_MS) {
  const ctrl = new AbortController();
  let byUser = false;
  let timer = setTimeout(() => ctrl.abort(), idleMs);
  const onStop = () => { byUser = true; ctrl.abort(); };
  if (stopSignal) {
    if (stopSignal.aborted) onStop();
    else stopSignal.addEventListener('abort', onStop, { once: true });
  }
  return {
    signal: ctrl.signal,
    stopped: () => byUser,
    alive: () => {
      if (ctrl.signal.aborted) return;
      clearTimeout(timer);
      timer = setTimeout(() => ctrl.abort(), idleMs);
    },
    done: () => { clearTimeout(timer); if (stopSignal) stopSignal.removeEventListener('abort', onStop); },
  };
}

// X-17 (audit 2026-10-29): "Sorry, I encountered an error: Internal Server Error"
// told the officer nothing. A plain sentence, with the technical text after it.
export function friendlyError(message) {
  const m = String(message || '').trim();
  const low = m.toLowerCase();
  let say = 'Something went wrong while answering. Try again, or ask it in other words.';
  if (!m || low.includes('internal server error') || low.includes('api request failed') || low.includes('bad gateway')
    || low.includes('timeout') || low.includes('timed out')) {
    say = 'The data service did not respond. Try again in a minute.';
  } else if (low.includes('another signed-in user')) {
    return m;
  } else if (low.includes('at most') || low.includes('too long') || low.includes('2000 characters')) {
    say = 'The question is too long. Ask it in 2,000 characters or fewer.';
  }
  return m ? `${say} (Details: ${m})` : say;
}

// K-10 (audit 2026-10-29): a validation error's detail is a list of objects and
// showed as "[object Object]"; its message is said instead.
export function detailText(detail) {
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d && typeof d === 'object' ? d.msg : String(d))).filter(Boolean);
    return msgs.join('; ');
  }
  return detail && typeof detail === 'object' ? String(detail.msg || '') : String(detail || '');
}

// The error for a non-2xx response: a ConnectionError when it means the
// network or the data service, else the app's own message.
async function httpFailure(response) {
  let detail = '';
  let fromApp = false;
  try { detail = (await response.json()).detail || ''; fromApp = !!detail; } catch (e) { /* not the app's JSON */ }
  if (isConnectionStatus(response.status, detail, fromApp)) return new ConnectionError();
  return new Error(detailText(detail) || 'API request failed');
}

// opts: { skipCache, signal, keepTurns } — skipCache answers afresh (Regenerate); signal is Stop;
// keepTurns (K-6): the saved turns to keep — the rest were replaced by Edit / Regenerate.
export async function fetchNLPResponse(question, language, sessionId, opts = {}) {
  const body = { question, language, session_id: sessionId, include_sql: true, skip_cache: !!opts.skipCache };
  if (Number.isInteger(opts.keepTurns)) body.keep_turns = opts.keepTurns;   // K-6
  const ab = questionAbort(opts.signal);
  let response;
  try {
    response = await apiFetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ab.signal,
    });
    if (!response.ok) throw await httpFailure(response);
    return await response.json();
  } catch (err) {
    if (err.message === 'unauthorized') throw err;
    if (err.name === 'AbortError') throw ab.stopped() ? new StoppedError() : new Error(TIMED_OUT);
    if (err instanceof TypeError) throw new ConnectionError();
    throw err;
  } finally {
    ab.done();
  }
}

// The same question over POST /api/query/stream (Server-Sent Events, D-039).
// onEvent gets every live event: {type:'step', node}, {type:'draft_reset'},
// {type:'token', text}. Resolves with the same result /api/query returns.
// A server without the stream route (404/405), or a stream that fails before
// any event arrived, falls back to the plain request.
export async function streamNLPResponse(question, language, sessionId, opts = {}) {
  const onEvent = opts.onEvent || (() => {});
  const body = { question, language, session_id: sessionId, include_sql: true, skip_cache: !!opts.skipCache };
  if (Number.isInteger(opts.keepTurns)) body.keep_turns = opts.keepTurns;   // K-6
  const ab = questionAbort(opts.signal);
  let gotEvent = false;
  let response;
  try {
    response = await apiFetch('/api/query/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal: ab.signal,
    });
    if (response.status === 404 || response.status === 405 || !response.body) {
      ab.done();
      return fetchNLPResponse(question, language, sessionId, opts);
    }
    if (!response.ok) throw Object.assign(await httpFailure(response), { fromServer: true });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      ab.alive();                            // any chunk, pings included
      buf += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) >= 0) {
        const frame = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const data = frame.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trimStart()).join('\n');
        if (!data) continue;                 // ": ping" keep-alive
        let ev;
        try { ev = JSON.parse(data); } catch (e) { continue; }
        gotEvent = true;
        if (ev.type === 'done') return ev.result;
        if (ev.type === 'error') {
          if (ev.status === 401) { onUnauthorized('Your session has expired — please sign in again.'); throw new Error('unauthorized'); }
          const e = isConnectionStatus(ev.status, ev.detail, true) ? new ConnectionError() : new Error(detailText(ev.detail) || 'API request failed');
          throw Object.assign(e, { fromServer: true });
        }
        onEvent(ev);
      }
    }
    // The stream ended without `done`: the connection dropped mid-answer.
    throw new ConnectionError('The connection dropped before the answer finished.');
  } catch (err) {
    if (err.message === 'unauthorized' || err.fromServer) throw err;
    if (err.name === 'AbortError') throw ab.stopped() ? new StoppedError() : new Error(TIMED_OUT);
    if (!gotEvent && err instanceof TypeError) {
      // The stream never started (a proxy that drops it, a network blip):
      // the plain request still answers.
      ab.done();
      return fetchNLPResponse(question, language, sessionId, opts);
    }
    if (err instanceof TypeError) throw new ConnectionError('The connection dropped before the answer finished.');
    throw err;
  } finally {
    ab.done();
  }
}

// Live figures for the scheme overview cards: GET /api/scheme-stats ->
// { cards: { <card key>: [[value, label], ...] }, as_of }. Computed from megh_db by
// the backend (cached there), so the cards follow every data refresh. null on any
// failure — the cards then keep their built-in numbers.
export async function fetchSchemeStats() {
  try {
    const res = await apiFetch('/api/scheme-stats', { cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    // { cards: {key: [[value, label], ...]}, periods: {key: 'FY …'}, as_of: ISO time }
    return data && data.cards ? data : null;
  } catch (e) {
    return null;
  }
}

// Is the service back? GET /health (anonymous: {status}). 'ok' when the app
// and its database answer; 'degraded' when the app answers but a dependency
// (megh_db behind the VPN, Qdrant) does not; 'down' when the app can't be
// reached. Bounded, so a hung connection can't stall the retry loop.
export async function checkHealth(timeoutMs = 6000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/health`, { cache: 'no-store', signal: ctrl.signal });
    if (!res.ok) return 'down';
    const data = await res.json().catch(() => ({}));
    return data.status === 'ok' ? 'ok' : 'degraded';
  } catch (e) {
    return 'down';
  } finally {
    clearTimeout(timer);
  }
}

// ── Conversation history (server-backed, per officer) ───────────────────────
export async function listHistory(filter) {
  const one = async (qs) => {
    const res = await apiFetch('/api/history?limit=60' + qs);
    if (!res.ok) throw new Error('history ' + res.status);
    const data = await res.json();
    return data.conversations || [];
  };
  if (filter) return one('&q=' + encodeURIComponent(filter));
  // K-28 (audit 2026-10-29): one list of 60 with archived chats last cut the Archived
  // section off for an officer with 60+ active chats; each shelf is fetched on its own
  const [active, archived] = await Promise.all([one('&archived=false'), one('&archived=true')]);
  return [...active, ...archived];
}

export async function getConversation(sid) {
  const res = await apiFetch('/api/history/' + encodeURIComponent(sid));
  if (!res.ok) throw new Error('load ' + res.status);
  const data = await res.json();
  return data.turns || [];
}

async function jsonCall(path, method, body, label) {
  const res = await apiFetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(label + ' ' + res.status);
}
export const renameConversationApi = (sid, title) =>
  jsonCall('/api/history/' + encodeURIComponent(sid), 'PATCH', { title }, 'rename');
export const deleteConversationApi = (sid) =>
  jsonCall('/api/history/' + encodeURIComponent(sid), 'DELETE', null, 'delete');
export const pinConversationApi = (sid, pinned) =>
  jsonCall('/api/history/' + encodeURIComponent(sid) + '/pin', 'POST', { pinned }, 'pin');
export const archiveConversationApi = (sid, archived) =>
  jsonCall('/api/history/' + encodeURIComponent(sid) + '/archive', 'POST', { archived }, 'archive');

// 👍 / 👎 on an answer (RAG upgrade Phase 6). rating 1 / -1 sets the vote,
// 0 takes it back; one vote per officer per answer (messageKey).
export const sendFeedbackApi = (body) => jsonCall('/api/feedback', 'POST', body, 'feedback');

// ── Voice transcription ─────────────────────────────────────────────────────
// Backend contract: multipart field `file`, response `{ "text": ... }`. The
// self-hosted ASR can cold-start, so the client waits up to 150 s.
export async function transcribe(blob, language, device) {
  const form = new FormData();
  const t = blob.type || 'audio/webm';
  const ext = t.includes('wav') ? 'wav' : t.includes('ogg') ? 'ogg' : t.includes('mp4') ? 'mp4' : 'webm';
  form.append('file', blob, `audio.${ext}`);
  form.append('language', language);
  form.append('device', device || '');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 150000);
  try {
    return await fetch(`${API_BASE}/api/query/transcribe`, {
      method: 'POST', body: form, headers: authHeaders(), signal: ctrl.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}
