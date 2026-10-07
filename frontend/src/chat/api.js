/* Backend connection for the chat console. Same contract as web/ai_query.html:
   POST /api/auth/login -> JWT kept in localStorage under megh_jwt; every /api/*
   call carries it as a Bearer token; a 401 anywhere drops the token and returns
   to the sign-in gate. The API is same-origin; `?api=<origin>` overrides it for
   debugging. */

export const API_BASE = (new URLSearchParams(window.location.search).get('api') || '').replace(/\/$/, '');
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
    if (!res.ok) throw new Error('stale token');
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

export function logoutRemote() {
  if (!token) return;
  fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', headers: authHeaders() }).catch(() => {});
}

// ── Query ───────────────────────────────────────────────────────────────────
// Hard client-side ceiling on a single question, so a stalled backend can never
// leave the typing dots up forever.
const QUERY_TIMEOUT_MS = 75000;

export async function fetchNLPResponse(question, language, sessionId) {
  const body = { question, language, session_id: sessionId, include_sql: true };
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), QUERY_TIMEOUT_MS);
  let response;
  try {
    response = await apiFetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (err) {
    if (err.message === 'unauthorized') throw err;
    if (err.name === 'AbortError') {
      throw new Error('The request took too long and timed out. The service may be busy — please try again in a moment.');
    }
    throw new Error('Could not reach the server. Please check your connection and try again.');
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    let detail = 'API request failed';
    try { detail = (await response.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  return response.json();
}

// ── Conversation history (server-backed, per officer) ───────────────────────
export async function listHistory(filter) {
  const qs = filter ? '&q=' + encodeURIComponent(filter) : '';
  const res = await apiFetch('/api/history?limit=60' + qs);
  if (!res.ok) throw new Error('history ' + res.status);
  const data = await res.json();
  return data.conversations || [];
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
