import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  adoptSessionId, archiveConversationApi, checkHealth, ConnectionError, deleteConversationApi, fetchMe, friendlyError, getConversation,
  getToken, listHistory, login, logoutRemote, pinConversationApi, renameConversationApi, resetSessionId,
  setToken, setUnauthorizedHandler, StoppedError, storedSessionId, streamNLPResponse,
} from './api.js';
import { GLOSSARY, UI_STRINGS, UNIFIED_SAMPLES } from './constants.js';
import { nowTime, stampTime, todayLabel } from './format.js';
import { useVoice } from './useVoice.js';
import { isContinueText, isStopText } from './stopContinue.js';
import { speechChunks } from './text.js';
import { useSidebarResize } from './useSidebarResize.js';
import { useComposerHeight } from './useComposerHeight.js';
import { BotMessage, TextMessage, TypingMessage } from './components/Messages.jsx';
import { LoginScreen, Modal, UndoToast } from './components/Overlays.jsx';
import { USE_CASE_GROUPS, UseCases } from './components/UseCases.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ChatExport } from './components/ChatExport.jsx';
import { LanguageSwitcher } from './components/LanguageSwitcher.jsx';
import { RecordingStrip } from './components/RecordingStrip.jsx';
import { SlashMenu } from './components/SlashMenu.jsx';
import { langFromArg, parseSlash, slashMenuItems, viewRequest } from './slashCommands.js';
import { VIEW_NAMES, viewOnlyRequest } from './analytics.js';
import { ShortcutsHelp } from './components/ShortcutsHelp.jsx';
import { plainText } from './components/Markdown.jsx';
import { copyText } from './components/Messages.jsx';
import { IS_MAC, SHORTCUTS, enterSends, isComposing, isTyping, keyLabel, matches } from './shortcuts.js';
import { WelcomeCard } from './components/WelcomeCard.jsx';

// K-10 (audit 2026-10-29): the server refuses a question over 2,000 characters
// (settings.MAX_QUESTION_CHARS); the box stops there and counts near the end.
const MAX_QUESTION_CHARS = 2000;

/* The chat console (was web/ai_query.html). Every behaviour of the original is
   kept: sign-in gate with a session check, server-backed chat history (pin,
   archive with undo, rename, delete, search), replay of a saved thread with its
   charts, the scheme carousel, voice input, the collapsible sidebar rail
   (Ctrl+B), the mobile drawer, the language dropdown and the admin entry point. */

const RAIL_KEY = 'megh_sidebar_rail';
const ARCH_OPEN_KEY = 'megh_archive_open';
const readFlag = (k) => { try { return localStorage.getItem(k) === '1'; } catch (e) { return false; } };
const writeFlag = (k, on) => { try { localStorage.setItem(k, on ? '1' : '0'); } catch (e) { /* ignore */ } };

// The glossary modal, optionally filtered to the terms (or definitions) that
// hold `filter` (any case). An empty filter lists everything.
function glossaryModal(filter) {
  const f = String(filter || '').trim().toLowerCase();
  const match = (t) => !f || t.term.toLowerCase().includes(f) || t.def.toLowerCase().includes(f);
  const sections = Object.entries(GLOSSARY)
    .map(([section, terms]) => [section, terms.filter(match)])
    .filter(([, terms]) => terms.length);
  return {
    title: 'Glossary',
    sub: f ? `Terms matching “${filter.trim()}”` : 'Domain terms across all schemes',
    body: sections.length ? sections.map(([section, terms]) => (
      <div key={section}>
        <div className="modal-section">{section}</div>
        {terms.map((t) => (
          <div key={t.term} className="glossary-term">
            <div className="glossary-term-name">{t.term}</div>
            <div className="glossary-term-def">{t.def}</div>
          </div>
        ))}
      </div>
    )) : <div className="glossary-empty">No glossary term matches “{filter.trim()}”.</div>,
  };
}

// K-6: the turns the server saved for these messages — answers and pauses it
// sent, not local redraws, hints or errors
const savedTurns = (msgs) => msgs.filter((x) => (x.kind === 'rich' && x.response && !x.local) || x.saved).length;

export default function App() {
  // ── Auth ────────────────────────────────────────────────────────────────
  const [auth, setAuth] = useState(getToken() ? 'pending' : 'locked');   // pending | locked | unlocked
  const [user, setUser] = useState(null);
  const [loginError, setLoginError] = useState('');
  const [loginInvalid, setLoginInvalid] = useState([]);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginKey, setLoginKey] = useState(0);
  const usernameRef = useRef(null);
  const appStarted = useRef(false);

  // ── Conversation ────────────────────────────────────────────────────────
  const [sessionId, setSessionIdState] = useState(storedSessionId);
  const sessionRef = useRef(sessionId);
  const setSessionId = (sid) => { sessionRef.current = sid; setSessionIdState(sid); };
  const [messages, setMessages] = useState([]);
  const msgId = useRef(0);
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);
  const [input, setInputState] = useState('');
  const inputRef = useRef('');
  // Slash-command menu (#319): the highlighted row, and whether Esc closed it
  // for the current text (any edit opens it again).
  const [slashIdx, setSlashIdx] = useState(0);
  const [slashClosed, setSlashClosed] = useState(false);
  const setInput = (v) => { inputRef.current = v; setInputState(v); setSlashIdx(0); setSlashClosed(false); };
  const textareaRef = useRef(null);
  const chatAreaRef = useRef(null);
  const chatInnerRef = useRef(null);
  // Smart auto-scroll: the chat follows new content only while the officer is
  // at the bottom. Scrolled up to read, nothing moves; a "New answer" pill
  // appears instead. Sending a question or opening a chat always goes down.
  const followRef = useRef(true);
  const [newBelow, setNewBelow] = useState(null);   // null | 'writing' | 'answer'
  const [lang, setLang] = useState('en');
  const strings = UI_STRINGS[lang] || UI_STRINGS.en;
  const [prompts, setPrompts] = useState({ title: 'Try a question', items: [] });

  // ── History ─────────────────────────────────────────────────────────────
  const [history, setHistory] = useState([]);
  const historyRef = useRef([]);
  const [filter, setFilter] = useState('');
  const filterRef = useRef('');
  const [searchOpen, setSearchOpenState] = useState(false);
  const [archOpen, setArchOpen] = useState(() => readFlag(ARCH_OPEN_KEY));
  const histTimer = useRef(0);

  // ── Chrome ──────────────────────────────────────────────────────────────
  const [navOpen, setNavOpen] = useState(false);
  const [rail, setRail] = useState(() => readFlag(RAIL_KEY));
  const [modal, setModal] = useState(null);
  const [useCaseScheme, setUseCaseScheme] = useState(null);   // Use cases popup: open scheme, or null
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(0);
  const [scrollTopShow, setScrollTopShow] = useState(false);
  const [speakingId, setSpeakingId] = useState(null);
  const speakingRef = useRef(null);

  const nextId = () => ++msgId.current;
  const closeNav = useCallback(() => setNavOpen(false), []);

  // Body classes drive the boot splash / sign-in gate (see chat.css).
  useLayoutEffect(() => {
    const b = document.body.classList;
    b.toggle('locked', auth !== 'unlocked');
    b.toggle('auth-pending', auth === 'pending');
  }, [auth]);

  // ── History ─────────────────────────────────────────────────────────────
  // Silent on failure: the chat stays usable when the history table is down.
  const histSeq = useRef(0);
  const loadHistory = useCallback(async () => {
    if (!getToken()) { historyRef.current = []; setHistory([]); return; }
    // K-30 (audit 2026-10-29): an older search answering late replaced a newer one
    const seq = ++histSeq.current;
    let list = [];
    try {
      list = await listHistory(filterRef.current);
    } catch (e) {
      if (String(e.message) === 'unauthorized') return;
      list = [];
    }
    if (seq !== histSeq.current) return;
    historyRef.current = list;
    setHistory(list);
  }, []);

  const onFilter = (v) => {
    setFilter(v);
    filterRef.current = (v || '').trim();
    clearTimeout(histTimer.current);
    histTimer.current = setTimeout(loadHistory, 250);   // debounce — search hits the DB
  };
  // Closing the search box with an active filter clears it.
  const setSearchOpen = useCallback((open) => {
    setSearchOpenState(open);
    if (!open && filterRef.current) {
      setFilter(''); filterRef.current = '';
      clearTimeout(histTimer.current);
      histTimer.current = setTimeout(loadHistory, 250);
    }
  }, [loadHistory]);

  // ── Undo toast ──────────────────────────────────────────────────────────
  const hideUndo = useCallback(() => setToast(null), []);
  const showUndo = (message, fn) => {
    setToast({ message, fn: fn || null });
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(hideUndo, 7000);
  };
  const showUndoRef = useRef(showUndo);
  showUndoRef.current = showUndo;
  const runUndo = async () => {
    const fn = toast && toast.fn;
    hideUndo();
    if (fn) await fn();
  };

  // Filled in below (leaveChat is defined with the sending code); sign-out and
  // opening a chat call it through this ref.
  const leaveChatRef = useRef(() => {});

  // ── Auth flow ───────────────────────────────────────────────────────────
  const lockApp = useCallback(() => {
    setAuth('locked');
    setTimeout(() => usernameRef.current && usernameRef.current.focus(), 0);
  }, []);

  const handleLogout = useCallback((message) => {
    // K-2 (audit 2026-10-29): the next officer on this computer must not see this
    // officer's open chat or continue their conversation: stop the answer, clear
    // the screen and start a new session id.
    leaveChatRef.current();
    setMessages([]);
    setSessionId(resetSessionId());
    logoutRemote();
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* ignore */ }
    speakingRef.current = null; setSpeakingId(null);
    setToken('');
    setUser(null);
    // Clear the previous officer's threads: shared terminals must not leak
    // one user's conversation titles to the next.
    historyRef.current = []; setHistory([]);
    setFilter(''); filterRef.current = '';
    setSearchOpenState(false);
    hideUndo();
    setLoginKey((k) => k + 1);           // resets the sign-in form
    setLoginInvalid([]);
    setLoginError(typeof message === 'string' ? message : '');
    lockApp();
  }, [hideUndo, lockApp]);

  useEffect(() => { setUnauthorizedHandler((msg) => handleLogout(msg)); }, [handleLogout]);

  // Replay a stored thread and continue it (the session id is adopted).
  const openConversation = useCallback(async (sid) => {
    try {
      const turns = await getConversation(sid);
      const replay = [];
      for (const t of turns) {
        // The times the officer actually asked and got the answer, not "now":
        // the turn is saved when the answer is ready (created_at), and
        // latency_ms is how long that took, so the question was asked that
        // much earlier.
        const answeredAt = t.created_at ? new Date(t.created_at) : null;
        const askedAt = answeredAt ? new Date(answeredAt.getTime() - (Number(t.latency_ms) || 0)) : null;
        const askedTime = askedAt ? stampTime(askedAt) : nowTime();
        const answerTime = answeredAt ? stampTime(answeredAt) : nowTime();
        replay.push({ id: nextId(), time: askedTime, at: askedAt && askedAt.toISOString(), kind: 'user', text: t.question });
        // A turn saved with its full payload replays through the rich renderer
        // (charts, SQL, follow-ups); older turns fall back to text.
        if (t.response && typeof t.response === 'object') {
          replay.push({ id: nextId(), time: answerTime, at: answeredAt && answeredAt.toISOString(), kind: 'rich', question: t.question, response: t.response });
        } else {
          replay.push({ id: nextId(), time: answerTime, at: answeredAt && answeredAt.toISOString(), kind: 'bot', saved: true, text: t.answer || '(no answer recorded)' });
        }
      }
      try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* ignore */ }
      speakingRef.current = null; setSpeakingId(null);
      leaveChatRef.current();
      followRef.current = true;
      setMessages(replay);
      setSessionId(sid);
      adoptSessionId(sid);
      closeNav();
    } catch (e) {
      if (String(e.message) !== 'unauthorized') alert('Could not open that conversation.');
    }
  }, [closeNav]);

  // Reveal the app and run the one-time boot work. The splash / gate stays up
  // until a resumed chat has been replayed, so a refresh never flashes empty.
  const unlockApp = useCallback(async (u) => {
    setUser(u || null);
    await loadHistory();
    if (!appStarted.current) {
      appStarted.current = true;
      setPrompts({ title: 'Try a question', items: UNIFIED_SAMPLES });
      // A refresh keeps the tab's session id: if it has recorded turns, replay it.
      const existing = historyRef.current.find((c) => c.session_id === sessionRef.current);
      if (existing) await openConversation(sessionRef.current);
      // K-29 (audit 2026-10-29): a chat not in the latest list showed an empty screen
      // while the old session went on, so the next question inherited its scheme,
      // place and year unseen. It starts a new conversation instead.
      else setSessionId(resetSessionId());
    }
    setAuth('unlocked');
  }, [loadHistory, openConversation]);

  // On load: a stored JWT is confirmed with /api/auth/me before unlocking.
  useEffect(() => {
    (async () => {
      if (!getToken()) { lockApp(); return; }
      try {
        const me = await fetchMe();
        unlockApp(me);
      } catch (e) {
        // A network blip must not discard a token that may still be valid: only a
        // token the server refused (401 / 403) is dropped (K-12, audit 2026-10-29).
        if (e && (e.status === 401 || e.status === 403)) setToken('');
        lockApp();
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogin = async (username, password) => {
    setLoginError(''); setLoginInvalid([]);
    if (!username || !password) {
      setLoginError('Enter both your username and password.');
      setLoginInvalid([!username && 'user', !password && 'pass'].filter(Boolean));
      return null;
    }
    setLoginBusy(true);
    try {
      const { ok, data } = await login(username, password);
      if (!ok) {
        setLoginError(data.detail || 'Incorrect username or password.');
        setLoginInvalid(['user', 'pass']);
        return 'clear-password';
      }
      setToken(data.access_token);
      await unlockApp(data.user || null);
    } catch (e) {
      setLoginError('Could not reach the sign-in service. Check your connection and try again.');
    } finally {
      setLoginBusy(false);
    }
    return null;
  };

  // ── Sending ─────────────────────────────────────────────────────────────
  // The in-flight message shows the pipeline's steps and the answer as it is
  // written (/api/query/stream, D-039). Stop aborts the request, which also
  // cancels the turn on the server. `skipCache` (Regenerate) answers afresh.
  const stopRef = useRef(null);
  // K-9 (audit 2026-10-29): one chip tap waits for the running answer, not one
  // timer per tap; Stop and leaving the chat forget it.
  const pendingAskRef = useRef(null);
  const dropPendingAsk = () => { if (pendingAskRef.current) { clearInterval(pendingAskRef.current); pendingAskRef.current = null; } };
  const stopQuery = useCallback(() => { dropPendingAsk(); if (stopRef.current) stopRef.current.abort(); }, []);
  // The question the officer last stopped, until another one runs.
  const stoppedRef = useRef(null);
  // ── Connection ──────────────────────────────────────────────────────────
  // 'online' | 'down' (the server can't be reached, or it can't reach megh_db:
  // the VPN dropped) | 'back' (just recovered; the banner says so briefly).
  // A question that failed on the connection waits (waitingRef) and is asked
  // again, once, when /health says the service is back.
  const [conn, setConn] = useState('online');
  const waitingRef = useRef(null);            // { msgId, q }
  const messagesRef = useRef([]);
  useEffect(() => { messagesRef.current = messages; }, [messages]);
  const backTimer = useRef(0);
  const connBack = useCallback(() => {
    setConn((c) => (c === 'online' ? c : 'back'));
    clearTimeout(backTimer.current);
    backTimer.current = setTimeout(() => setConn((c) => (c === 'back' ? 'online' : c)), 4000);
  }, []);

  // K-1 / K-2 / K-8 / K-26 (audit 2026-10-29): leaving a chat — another chat, a new
  // one, a delete, a sign-out — stops its running answer and forgets its stopped
  // question, its waiting question and any chip tap. An answer that lands after the
  // switch belongs to the chat it was asked in: it is dropped here (the server has
  // saved it there) instead of appearing under the other chat.
  const chatGenRef = useRef(0);
  const leaveChat = useCallback(() => {
    chatGenRef.current += 1;
    dropPendingAsk();
    if (stopRef.current) stopRef.current.abort();
    stoppedRef.current = null;
    waitingRef.current = null;
  }, []);

  leaveChatRef.current = leaveChat;

  // K-14: the box takes focus back only when focus was already in the chat, and
  // never on a touch screen (the keyboard would cover the answer)
  const refocusComposer = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    try { if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) return; } catch (e) { /* ignore */ }
    const a = document.activeElement;
    if (a && a !== document.body && a !== el && !(chatAreaRef.current && chatAreaRef.current.contains(a))) return;
    el.focus();
  }, []);

  const keepTurnsRef = useRef(null);       // K-6: set by Edit for the run it starts
  const englishRef = useRef(false);         // K-18: set by a chip tap for the run it starts
  const runQuestion = useCallback(async (q, { skipCache = false, addUser = true, keepTurns = keepTurnsRef.current,
    english = englishRef.current } = {}) => {
    keepTurnsRef.current = null;
    englishRef.current = false;
    if (runningRef.current) return;           // one question at a time
    // "/chart …" or "/table …" (#319): the question goes without its command;
    // the answer remembers the view. The bubble shows what was typed.
    const { view, question: asked } = viewRequest(q);
    runningRef.current = true; setRunning(true);
    stoppedRef.current = null;                // a new run replaces a stopped question
    followRef.current = true;                 // the officer just asked: show it
    waitingRef.current = null;                // a new question replaces any waiting one
    const typingId = nextId();
    setMessages((m) => [
      ...m,
      ...(addUser ? [{ id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'user', text: q }] : []),
      { id: typingId, kind: 'typing', steps: [], draft: '' },
    ]);
    const patchTyping = (fn) => setMessages((m) => m.map((x) => (x.id === typingId ? { ...x, ...fn(x) } : x)));
    // X-10 (audit 2026-10-29): tokens are added once per animation frame, not one
    // state update (and re-render) per word
    let pending = '';
    let frame = 0;
    const flush = () => { frame = 0; const t = pending; pending = ''; if (t) patchTyping((x) => ({ draft: x.draft + t })); };
    const onEvent = (ev) => {
      if (ev.type === 'step') patchTyping((x) => ({ steps: [...x.steps, ev.node] }));
      else if (ev.type === 'draft_reset') { pending = ''; patchTyping(() => ({ draft: '' })); }
      else if (ev.type === 'token') {
        pending += ev.text;
        if (!frame) frame = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(flush) : setTimeout(flush, 16);
      }
    };
    const stop = new AbortController();
    stopRef.current = stop;
    const dropTyping = (m) => m.filter((x) => x.id !== typingId);
    const gen = chatGenRef.current;
    const here = () => gen === chatGenRef.current;     // still the chat it was asked in (K-1)
    const setMessagesHere = (fn) => { if (here()) setMessages(fn); };
    try {
      // K-18 (audit 2026-10-29): a chip's text is already the app's English; translating
      // it again was slower, sometimes reworded it, and broke the "Continue" match
      const response = await streamNLPResponse(asked, english ? 'en' : lang, sessionRef.current, { skipCache, signal: stop.signal, onEvent, keepTurns });
      setMessagesHere((m) => [...dropTyping(m), response.answer
        ? { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'rich', question: q, response, animate: true, streamKey: typingId, view }
        : { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, text: friendlyError(response.detail || '') }]);
      connBack();                             // an answer arrived: the connection is fine
    } catch (err) {
      if (err instanceof ConnectionError) {
        // Not an error with the question: the banner explains, and the
        // question is asked again by itself when the connection is back.
        const msgId = nextId();
        if (here()) waitingRef.current = { msgId, q };
        setConn('down');
        setMessagesHere((m) => [...dropTyping(m), { id: msgId, time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, waiting: true,
          text: 'Waiting for the connection. This question will be asked again as soon as it is back.' }]);
      } else if (err instanceof StoppedError) {
        if (here()) stoppedRef.current = q;
        setMessagesHere((m) => [...dropTyping(m), { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q,
          text: 'Stopped. Type "continue" when you want this answer.' }]);
      } else if (String(err.message) !== 'unauthorized') {
        setMessagesHere((m) => [...dropTyping(m), { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, text: friendlyError(err.message) }]);
        console.error('Query error:', err);
      } else {
        // K-27: signed out mid-answer; after signing back in the question can be asked again
        setMessagesHere((m) => [...dropTyping(m), { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q,
          text: 'You were signed out before this answer arrived. Sign in again, then use Try again.' }]);
      }
    } finally {
      if (stopRef.current === stop) stopRef.current = null;
      runningRef.current = false; setRunning(false);
      refocusComposer();
      // The turn is persisted server-side; re-read the history shortly after.
      setTimeout(loadHistory, 600);
    }
  }, [lang, loadHistory, connBack, refocusComposer]);

  // "stop" typed while an answer runs stops it, like the Stop button; a
  // "continue" typed right after a stop asks the stopped question again
  // (the server also remembers it, so "continue" works after a reload too:
  // conversation_layer.remember_stopped).
  const sendQuery = useCallback(() => {
    const q = inputRef.current.trim();
    if (!q) return;
    const sc = parseSlash(q);
    // K-39 (audit 2026-10-29): "/chart" alone, "/lang hindi" and "/help" did nothing
    // (or "/help" was asked as a question); each says what to type instead
    const hint = (text) => {
      setInput('');
      setMessages((m) => [...m, { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'user', text: q },
        { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', text }]);
    };
    const SLASH_HELP = 'Commands: /chart <question> draws the answer as a chart, /table <question> shows it as a '
      + 'table, /glossary <term> explains a term, /lang <language> sets the question language.';
    if (!sc && q.startsWith('/') && !q.includes(' ')) { hint(`"${q}" is not a command. ${SLASH_HELP}`); return; }
    if (sc) {
      if ((sc.cmd === 'chart' || sc.cmd === 'table') && !sc.rest) {
        hint(`Type a question after /${sc.cmd}, for example "/${sc.cmd} MGNREGA person days by district".`);
        return;
      }
      if (sc.cmd === 'glossary') { setInput(''); setModal(glossaryModal(sc.rest)); return; }
      if (sc.cmd === 'lang') {
        const code = langFromArg(sc.rest);
        if (code) { setLang(code); setInput(''); } else hint(`"${sc.rest || ''}" is not a language here. ${SLASH_HELP}`);
        return;
      }
    }
    if (runningRef.current) {
      if (isStopText(q)) { setInput(''); stopQuery(); return; }
      // K-23 (audit 2026-10-29): a question typed while an answer runs was ignored
      // with no word; it stays in the box and the officer is told why
      showUndoRef.current('An answer is still being written. Your question stays in the box: press Enter when it is done, or type "stop".');
      return;
    }
    setInput('');
    // "I want a bar chart", "pie chart", "show it as a table": nothing new is
    // asked, only a different view of the last answer's data — drawn here from
    // the rows already on screen, for every kind of answer (user, 2026-10-19).
    const viewOnly = viewOnlyRequest(q);
    if (viewOnly) {
      setMessages((m) => {
        const now = { time: nowTime(), at: new Date().toISOString() };
        const userMsg = { id: nextId(), ...now, kind: 'user', text: q };
        const last = [...m].reverse().find((x) => x.kind === 'rich' && x.response
          && Array.isArray(x.response.data) && x.response.data.length);
        if (!last) {
          return [...m, userMsg, { id: nextId(), ...now, kind: 'bot',
            text: `There is no data in this chat to show as ${VIEW_NAMES[viewOnly]} yet. Ask a data question, for example "MGNREGA person-days by district", and I'll draw it.` }];
        }
        const r = last.response;
        const userCount = (upTo) => m.slice(0, m.indexOf(upTo) + 1).filter((x) => x.kind === 'user').length;
        return [...m, userMsg, { id: nextId(), ...now, kind: 'rich', question: last.question, view: viewOnly,
          redrawOf: `Q${userCount(last)} table`, local: true,
          response: { ...r, answer: `Here is the same data as ${VIEW_NAMES[viewOnly]}. (Drawn here from the answer above; it is not saved with the chat.)`, rewritten_question: undefined,
                      follow_up: '', follow_up_options: [], follow_ups: [], suggestions: [] } }];
      });
      return;
    }
    const stoppedQ = stoppedRef.current;
    if (stoppedQ && isContinueText(q)) {
      setMessages((m) => [...m, { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'user', text: q }]);
      runQuestion(stoppedQ, { addUser: false });
      return;
    }
    runQuestion(q);
  }, [runQuestion, stopQuery]);

  const sendQueryRef = useRef(null);
  sendQueryRef.current = sendQuery;

  // Retry (after an error or Stop) and Regenerate (the last answer): the same
  // question again in place of that message, never from the cache.
  const rerun = useCallback((msgId, q) => {
    if (runningRef.current || !q) return;
    stopSpeaking();
    const msgs = messagesRef.current;
    const at = msgs.findIndex((x) => x.id === msgId);
    setMessages((m) => m.filter((x) => x.id !== msgId));
    // K-6: the replaced answer is removed on the server too
    runQuestion(q, { skipCache: true, addUser: false, keepTurns: at < 0 ? null : savedTurns(msgs.slice(0, at)) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runQuestion]);
  const rerunRef = useRef(rerun);
  rerunRef.current = rerun;

  // While the connection is down: poll /health (3 s, backing off to 15 s; at
  // once when the browser reports it is online again). When it is back, ask
  // the waiting question again if it is still the latest message.
  const pollNow = useRef(() => {});
  const connDown = conn === 'down';
  useEffect(() => {
    if (!connDown) return undefined;
    let stopped = false;
    let delay = 3000;
    let timer = 0;
    const tick = async () => {
      clearTimeout(timer);
      const h = navigator.onLine === false ? 'down' : await checkHealth();
      if (stopped) return;
      if (h === 'ok' || h === 'degraded') {     // K-13: degraded is reachable
        connBack();
        const w = waitingRef.current;
        const msgs = messagesRef.current;
        if (w && msgs.length && msgs[msgs.length - 1].id === w.msgId && !runningRef.current) {
          rerunRef.current(w.msgId, w.q);
        }
        waitingRef.current = null;
        return;
      }
      delay = Math.min(delay * 1.5, 15000);
      timer = setTimeout(tick, delay);
    };
    pollNow.current = tick;
    timer = setTimeout(tick, delay);
    window.addEventListener('online', tick);
    return () => { stopped = true; clearTimeout(timer); window.removeEventListener('online', tick); pollNow.current = () => {}; };
  }, [connDown, connBack]);
  // The browser knows first when the machine itself goes offline.
  useEffect(() => {
    const onOffline = () => setConn('down');
    window.addEventListener('offline', onOffline);
    return () => window.removeEventListener('offline', onOffline);
  }, []);

  // Run `text` as the next question. A click while an answer is in flight is
  // kept in the box and sent once the current answer lands.
  const ask = useCallback((text) => {
    const q = String(text == null ? '' : text).trim();
    if (!q) return;
    if (runningRef.current) {
      // the typed draft is left alone; the latest tap replaces an earlier one (K-9)
      dropPendingAsk();
      const gen = chatGenRef.current;
      const started = Date.now();
      pendingAskRef.current = setInterval(() => {
        if (gen !== chatGenRef.current || Date.now() - started > 90000) { dropPendingAsk(); return; }
        if (!runningRef.current) { dropPendingAsk(); setInput(q); englishRef.current = true; sendQueryRef.current(); englishRef.current = false; }
      }, 250);
      return;
    }
    setInput(q);
    refocusComposer();
    englishRef.current = true;
    sendQuery();
    englishRef.current = false;
  }, [sendQuery, refocusComposer]);

  // ── Chat pane ───────────────────────────────────────────────────────────
  // ── Read aloud (browser speech, no server call) ─────────────────────────
  const stopSpeaking = useCallback(() => {
    speakingRef.current = null;
    setSpeakingId(null);
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* ignore */ }
  }, []);
  const onSpeak = useCallback((id, text) => {
    const synth = window.speechSynthesis;
    if (!synth) return;
    if (speakingRef.current === id) { stopSpeaking(); return; }     // second tap stops it
    speakingRef.current = id;                                       // before cancel: the old
    synth.cancel();                                                 // utterance's onend sees it
    const voices = synth.getVoices();
    const voice = voices.find((v) => v.lang === 'en-IN') || voices.find((v) => (v.lang || '').startsWith('en'));
    // K-34: tables read as their cells, and the answer spoken in pieces
    const parts = speechChunks(text);
    if (!parts.length) { speakingRef.current = null; return; }
    const done = () => { if (speakingRef.current === id) { speakingRef.current = null; setSpeakingId(null); } };
    setSpeakingId(id);
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part);
      if (voice) u.voice = voice;
      u.lang = voice ? voice.lang : 'en-IN';
      u.onerror = done;
      if (i === parts.length - 1) u.onend = done;
      synth.speak(u);
    });
  }, [stopSpeaking]);
  useEffect(() => () => { try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* ignore */ } }, []);

  const newChat = useCallback(() => {
    leaveChat();
    stopSpeaking();
    setSessionId(resetSessionId());          // fresh session -> no context bleed
    setMessages([]);
  }, [stopSpeaking, leaveChat]);

  // Edit a sent question: it and everything after it leave the screen, and the
  // edited text is asked in its place (in the same conversation).
  const editQuestion = useCallback((id, q) => {
    if (runningRef.current) return;
    // K-31 (audit 2026-10-29): editing a question into /glossary, /lang or /chart cut
    // the chat after it and asked nothing; a command runs without cutting anything
    if (String(q || '').trim().startsWith('/')) { setInput(q); sendQuery(); return; }
    stopSpeaking();
    const msgs = messagesRef.current;
    const at = msgs.findIndex((x) => x.id === id);
    setMessages((m) => {
      const i = m.findIndex((x) => x.id === id);
      return i < 0 ? m : m.slice(0, i);
    });
    setInput(q);
    // K-6 (audit 2026-10-29): the replaced turns came back when the chat was reopened
    // and still steered follow-ups; the server now keeps only the turns before this one
    keepTurnsRef.current = at < 0 ? null : savedTurns(msgs.slice(0, at));
    sendQuery();
    keepTurnsRef.current = null;
  }, [sendQuery, stopSpeaking]);

  const scrollToEnd = useCallback((smooth) => {
    const el = chatAreaRef.current;
    if (!el) return;
    if (smooth) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    else el.scrollTop = el.scrollHeight + 9999;
  }, []);
  useEffect(() => {
    if (!messages.length) { setNewBelow(null); return; }
    if (followRef.current) { scrollToEnd(false); setNewBelow(null); return; }
    const last = messages[messages.length - 1];
    setNewBelow(last.kind === 'typing' ? 'writing' : 'answer');
  }, [messages, scrollToEnd]);
  // Late growth (charts, tables, the draft) keeps a following view pinned.
  useEffect(() => {
    const inner = chatInnerRef.current;
    if (!inner || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => { if (followRef.current) scrollToEnd(false); });
    ro.observe(inner);
    return () => ro.disconnect();
  }, [scrollToEnd]);
  const onChatScroll = (e) => {
    const el = e.currentTarget;
    setScrollTopShow(el.scrollTop > 200);
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    followRef.current = atBottom;
    if (atBottom) setNewBelow(null);
  };

  // ── History actions (row menu) ──────────────────────────────────────────
  const archiveConversation = async (sid, archived, quiet) => {
    const conv = historyRef.current.find((c) => c.session_id === sid) || {};
    const name = conv.title || 'Chat';
    try {
      await archiveConversationApi(sid, archived);
      // Archiving the open thread starts a clean chat, matching the sidebar.
      if (archived && sid === sessionRef.current) newChat();
      await loadHistory();
      if (!quiet) {
        showUndo(archived ? `“${name}” moved to Archived chats` : `“${name}” restored to your chats`,
          () => archiveConversation(sid, !archived, true));
      }
    } catch (e) {
      if (String(e.message) !== 'unauthorized') alert('Could not ' + (archived ? 'archive' : 'unarchive') + ' that chat.');
    }
  };

  const onHistAction = async (act, sid, conv) => {
    if (act === 'rename') {
      const title = prompt('Rename conversation', conv.title || '');
      if (title === null || !title.trim()) return;
      try { await renameConversationApi(sid, title.trim()); await loadHistory(); }
      catch (e) { if (String(e.message) !== 'unauthorized') alert('Rename failed.'); }
    } else if (act === 'pin') {
      try { await pinConversationApi(sid, !conv.pinned); await loadHistory(); }
      catch (e) { if (String(e.message) !== 'unauthorized') alert('Could not ' + (!conv.pinned ? 'pin' : 'unpin') + ' that chat.'); }
    } else if (act === 'archive') {
      await archiveConversation(sid, !conv.archived);
    } else {
      // Delete is irreversible: confirmed up front, naming the reversible option.
      const nm = conv.title || 'this chat';
      if (!confirm(`Delete “${nm}” permanently?\n\nThis cannot be undone. If you only want it out of your list, `
        + 'cancel and choose Archive instead — that keeps the chat and can be reversed.\n\n'
        + '(The audit record is retained for compliance.)')) return;
      try {
        await deleteConversationApi(sid);
        if (sid === sessionRef.current) newChat();
        await loadHistory();
      } catch (e) {
        if (String(e.message) !== 'unauthorized') alert('Delete failed.');
      }
    }
  };

  const toggleArch = () => { const v = !archOpen; setArchOpen(v); writeFlag(ARCH_OPEN_KEY, v); };

  // ── Sidebar rail ────────────────────────────────────────────────────────
  const toggleRail = useCallback(() => {
    setRail((r) => { writeFlag(RAIL_KEY, !r); return !r; });
    // Let the 180ms grid transition finish, then let Chart.js re-measure.
    setTimeout(() => window.dispatchEvent(new Event('resize')), 220);
  }, []);
  // Drag-to-resize (useSidebarResize.js). Dragging it shut collapses to the rail.
  const collapseToRail = useCallback(() => {
    setRail(true);
    writeFlag(RAIL_KEY, true);
  }, []);
  const sidebarResize = useSidebarResize({ onCollapse: collapseToRail });
  // --composer-h keeps the scroll-to-top button above the composer on every screen.
  useComposerHeight();

  // ── Voice dictation ─────────────────────────────────────────────────────
  // Whatever was already typed stays; the spoken words are added after it, live
  // while speaking (onPartial) and finally as the full transcript (onTranscript).
  const dictBase = useRef('');
  // One click to finish: Send (or Enter) while dictating stops the mic and sends
  // the final transcript as soon as it arrives. The mic button alone only
  // stops, leaving the text in the box to check (2026-10-13).
  const sendAfterVoice = useRef(false);
  const withBase = (t) => { const b = dictBase.current.trim(); return b ? b + ' ' + t : t; };
  const voice = useVoice({
    lang,
    onPartial: (t) => setInput(withBase(t)),
    onTranscript: (t) => {
      setInput(withBase(t));
      if (sendAfterVoice.current) { sendAfterVoice.current = false; sendQueryRef.current(); return; }
      if (textareaRef.current) textareaRef.current.focus();
    },
    onUnauthorized: () => handleLogout(),
  });
  // Composer auto-grows up to 160px; the scrollbar shows only when the text
  // is longer than that, never on an empty or short box.
  // 2026-10-18: while recording (#307) the box is hidden at 1px wide, so its
  // scrollHeight is meaningless (every word wraps onto its own line). The live
  // transcript used to be measured in that state, pinning the box at the 160px
  // cap, and it stayed that tall after the recording stopped because nothing
  // measured it again. Skip the hidden box and re-measure when it is shown.
  useLayoutEffect(() => {
    const t = textareaRef.current;
    if (!t) return;
    if (voice.isRecording || t.clientWidth < 40) return;
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 160) + 'px';
    t.style.overflowY = t.scrollHeight > 160 ? 'auto' : 'hidden';
  }, [input, voice.isRecording, voice.busy, voice.status]);

  // Send was pressed but the final transcription gave nothing (no speech,
  // network, ASR error): the live text already in the box is what the officer
  // saw and meant to send, so it is sent. An empty box sends nothing and the
  // reason stays on screen.
  useEffect(() => {
    if (voice.phase !== 'idle' || !sendAfterVoice.current) return;
    sendAfterVoice.current = false;
    if (inputRef.current.trim()) { voice.clearStatus(); sendQueryRef.current(); }
  }, [voice.phase]); // eslint-disable-line react-hooks/exhaustive-deps
  const sendOrFinishVoice = () => {
    if (!voice.busy) { sendQuery(); return; }
    if (voice.recordingRef.current) { sendAfterVoice.current = true; voice.stopMic(); return; }
    if (voice.phase === 'finishing') sendAfterVoice.current = true;
    // still opening the microphone: nothing recorded yet, nothing to send
  };
  const onMic = () => {
    sendAfterVoice.current = false;   // the mic button only stops: the text stays to check
    if (!voice.busy) dictBase.current = inputRef.current;
    // K-40 (audit 2026-10-29): with Khasi / Garo chosen, speech was recognised as
    // English with no warning; starting the mic now says so on every device
    if (!voice.busy && lang && lang !== 'en') showUndo('Voice input is English only. Speak in English, or type your question in Khasi / Garo.');
    voice.toggleMic();
  };

  // ── Modals ──────────────────────────────────────────────────────────────
  const closeModal = useCallback(() => setModal(null), []);
  const openGlossary = () => setModal(glossaryModal(''));
  // Slash menu (#319): a picked row either completes the command in the box
  // or acts at once (a language, the glossary).
  const applySlash = (item) => {
    if (!item) return;
    if (item.apply.lang) { setLang(item.apply.lang); setInput(''); return; }
    if (item.apply.cmd === 'glossary') { setInput(''); setModal(glossaryModal('')); return; }
    setInput('/' + item.apply.cmd + ' ');
    focusComposer();
  };
  // Use cases: an accordion of schemes; `useCaseScheme` is the one open (or
  // null). Built on every render so the popup follows it; reopening the popup
  // starts with all schemes closed. A picked question goes through ask(),
  // exactly like a typed question and Send.
  const openUseCases = () => { setUseCaseScheme(null); setModal({ kind: 'use-cases' }); };
  const pickUseCase = useCallback((q) => { closeModal(); ask(q); }, [closeModal, ask]);
  const useCaseGroup = USE_CASE_GROUPS.find((g) => g.key === useCaseScheme) || null;
  const modalView = modal && modal.kind === 'use-cases'
    ? {
      title: 'Use cases',
      sub: useCaseGroup
        ? `${useCaseGroup.name} · click a question to ask it`
        : 'Open a scheme to see its example questions',
      body: <UseCases selected={useCaseScheme} onSelect={setUseCaseScheme} onPick={pickUseCase} />,
    }
    : modal;

  // ── Keyboard shortcuts (shortcuts.js) ────────────────────────────────────
  // Each action returns false when it does not apply right now (no answer to
  // copy, nothing running to stop…), so the key keeps its normal meaning.
  const [editRequest, setEditRequest] = useState(null);     // {id, n}: open that question for editing
  const [exportSignal, setExportSignal] = useState(0);      // opens the Download chat menu
  const shortcutsOn = useRef(false);
  shortcutsOn.current = auth === 'unlocked';
  const lastOf = (kinds) => [...messages].reverse().find((m) => kinds.includes(m.kind));
  const focusComposer = () => { const t = textareaRef.current; if (t) { t.focus(); t.setSelectionRange(t.value.length, t.value.length); } };
  const openShortcuts = () => setModal((m) => (m && m.kind === 'shortcuts' ? null : {
    kind: 'shortcuts', title: 'Keyboard shortcuts',
    sub: IS_MAC ? '⌘ is the Command key' : 'Works anywhere in the chat',
    body: <ShortcutsHelp />,
  }));
  const shortcutActions = useRef({});
  shortcutActions.current = {
    newChat: () => { newChat(); setTimeout(focusComposer, 0); },
    search: () => {
      if (window.matchMedia('(max-width: 880px)').matches) setNavOpen(true);
      else if (rail) toggleRail();
      setSearchOpen(true);
      setTimeout(() => { const el = document.querySelector('.hist-search'); if (el) el.focus(); }, 60);
    },
    focus: () => { if (modal) return false; focusComposer(); },
    focusSlash: () => { if (modal) return false; focusComposer(); },
    stop: () => { if (!runningRef.current || modal || navOpen) return false; stopQuery(); },
    editLast: (e) => {
      if (e.target !== textareaRef.current || input || runningRef.current) return false;
      const last = lastOf(['user']);
      if (!last) return false;
      setEditRequest({ id: last.id, n: Date.now() });
    },
    copyLast: () => {
      const last = lastOf(['rich', 'bot']);
      if (!last) { showUndo('No answer to copy yet'); return; }
      const text = last.kind === 'rich' ? plainText((last.response && last.response.answer) || '') : (last.text || '');
      copyText(text, () => showUndo('Answer copied'));
    },
    regenerate: () => {
      if (runningRef.current) return;
      const last = messages.filter((m) => m.kind !== 'typing').slice(-1)[0];
      if (last && last.kind === 'rich' && last.question) rerun(last.id, last.question);
      else if (last && last.kind === 'bot' && last.retryQ) rerun(last.id, last.retryQ);
      else showUndo('Nothing to regenerate yet');
    },
    download: () => {
      if (!messages.some((m) => m.kind === 'user' || m.kind === 'rich')) { showUndo('Nothing to download yet'); return; }
      setExportSignal((n) => n + 1);
    },
    mic: () => onMic(),
    sidebar: () => toggleRail(),
    help: () => openShortcuts(),
  };

  // ── Keyboard ────────────────────────────────────────────────────────────
  const voiceRef = useRef(voice);
  voiceRef.current = voice;
  useEffect(() => {
    const onKey = (e) => {
      // Keyboard shortcuts (shortcuts.js): one table, also shown by Ctrl + /.
      if (shortcutsOn.current) {
        for (const sc of SHORTCUTS) {
          if (!matches(e, sc)) continue;
          if (isTyping(e.target) && !sc.whileTyping) continue;
          const act = shortcutActions.current[sc.id];
          if (!act || act(e) === false) continue;   // not applicable now: the key does its usual thing
          e.preventDefault();
          return;
        }
      }
      if (e.key === 'Escape') {
        closeNav();
        closeModal();
        if (voiceRef.current.recordingRef.current) voiceRef.current.stopMic();
        else if (!voiceRef.current.busy) voiceRef.current.clearStatus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [toggleRail, closeNav, closeModal]);

  const onComposerKey = (e) => {
    if (isComposing(e)) return;   // the IME is still building a word
    if (slashItems.length) {
      // The slash menu is open: the arrows move in it, Enter / Tab pick, Esc closes.
      if (e.key === 'ArrowDown') { e.preventDefault(); setSlashIdx((i) => (i + 1) % slashItems.length); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSlashIdx((i) => (i - 1 + slashItems.length) % slashItems.length); return; }
      if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') { e.preventDefault(); applySlash(slashItems[slashActive]); return; }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setSlashClosed(true); return; }
    }
    // While dictating the box is filling itself: Enter waits for the final text.
    if (enterSends(e)) { e.preventDefault(); sendOrFinishVoice(); }
  };
  const slashItems = slashClosed || voice.busy ? [] : slashMenuItems(input);
  const slashActive = Math.min(slashIdx, Math.max(0, slashItems.length - 1));

  const signedIn = auth === 'unlocked' && !!getToken();

  return (
    <>
      <div className="boot-splash" aria-hidden="true">
        <div className="mark">M</div>
        <div className="bar"><i /></div>
      </div>

      <LoginScreen key={loginKey} ref={usernameRef} error={loginError} invalid={loginInvalid} busy={loginBusy}
                   onSubmit={handleLogin} onInput={() => { setLoginError(''); setLoginInvalid([]); }} />

      <Modal modal={modalView} onClose={closeModal} />

      <div className={'app' + (navOpen ? ' nav-open' : '') + (rail ? ' rail' : '')
                      + (sidebarResize.dragging ? ' resizing' : '')}
           style={rail ? undefined : { '--sidebar-w': sidebarResize.width + 'px' }}>
        <Sidebar
          signedIn={signedIn} user={user} history={history} filter={filter} onFilter={onFilter}
          searchOpen={searchOpen} setSearchOpen={setSearchOpen} archOpen={archOpen} onToggleArch={toggleArch}
          activeSid={sessionId} onOpen={openConversation} onHistAction={onHistAction}
          onNewChat={newChat} onGlossary={openGlossary} onUseCases={openUseCases}
          onToggleRail={toggleRail} rail={rail} onLogout={(e) => { if (e) e.preventDefault(); handleLogout(); }}
          onCloseNav={closeNav}
        />
        {!rail && <div className="sidebar-resizer" {...sidebarResize.handleProps} />}
        <div className="sidebar-backdrop" onClick={closeNav} />

        <UndoToast toast={toast} onUndo={runUndo} />

        <main className="main">
          <div className="topbar">
            <button className="menu-btn" type="button" onClick={() => setNavOpen(!navOpen)} aria-label="Open menu">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
            </button>
            <div className="scheme-switch" />
            <div className="actions">
              <ChatExport messages={messages} openSignal={exportSignal}
                          title={(history.find((c) => c.session_id === sessionId) || {}).title} />
              <div className="date-pill">{todayLabel()}</div>
              <LanguageSwitcher lang={lang} onChange={setLang} />
            </div>
          </div>

          {conn !== 'online' && (
            <div className={'conn-banner ' + conn} role="status" aria-live="polite">
              {conn === 'down' ? (
                <>
                  <span className="conn-spin" aria-hidden="true" />
                  <span className="conn-text"><b>Can't reach the server — retrying…</b>
                    <span className="conn-sub"> Usually the VPN or network. Your question is kept.</span></span>
                  <button type="button" className="conn-retry" onClick={() => pollNow.current()}>Retry now</button>
                </>
              ) : (
                <span className="conn-text"><b>Connected again.</b></span>
              )}
            </div>
          )}

          <div className="chat-area" ref={chatAreaRef} onScroll={onChatScroll}>
            <div className={'chat-inner' + (messages.length ? '' : ' is-welcome')} ref={chatInnerRef}>
              <WelcomeCard strings={strings} prompts={prompts} setPrompts={setPrompts} onAsk={ask}
                signedIn={auth === 'unlocked'} />
              <div>
                {messages.map((m, i) => {
                  // Regenerate / Try again sit on the latest answer only: an
                  // older one would come back below newer turns, out of place.
                  const isLast = i === messages.length - 1 && !running;
                  if (m.kind === 'typing') return <TypingMessage key={m.id} steps={m.steps} draft={m.draft} streamKey={m.id} />;
                  if (m.kind === 'rich') {
                    return <BotMessage key={m.id} id={m.id} question={m.question} response={m.response} time={m.time}
                                       animate={m.animate} streamKey={m.streamKey} at={m.at} view={m.view}
                                       onAsk={ask} speakingId={speakingId} onSpeak={onSpeak}
                                       onRegenerate={isLast && m.question && !m.local ? () => rerun(m.id, m.question) : null}
                                       sessionId={sessionId} />;
                  }
                  if (m.kind === 'user') {
                    return <TextMessage key={m.id} id={m.id} role="user" text={m.text} time={m.time}
                                        busy={running} onEdit={editQuestion}
                                        editRequest={editRequest && editRequest.id === m.id ? editRequest.n : 0} />;
                  }
                  return <TextMessage key={m.id} id={m.id} role="bot" text={m.text} time={m.time} at={m.at}
                                      speakingId={speakingId} onSpeak={onSpeak}
                                      onRetry={isLast && m.retryQ ? () => rerun(m.id, m.retryQ) : null} />;
                })}
              </div>
            </div>
          </div>

          <button className={'scroll-top' + (scrollTopShow ? ' show' : '')} type="button" title="Scroll to top"
                  onClick={() => chatAreaRef.current && chatAreaRef.current.scrollTo({ top: 0, behavior: 'smooth' })}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M18 15l-6-6-6 6" /></svg>
          </button>

          <div className="composer-wrap">
            {newBelow && (
              <button type="button" className="new-below" onClick={() => {
                // Smooth there, then snap: the answer may have grown meanwhile.
                followRef.current = true; setNewBelow(null); scrollToEnd(true);
                setTimeout(() => { followRef.current = true; scrollToEnd(false); }, 450);
              }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M12 5v14M5 12l7 7 7-7" /></svg>
                {newBelow === 'writing' ? 'Answer is being written' : 'New answer'}
              </button>
            )}
            <div className="composer-inner">
              <SlashMenu items={slashItems} active={slashActive} onPick={applySlash} onHover={setSlashIdx} />
              {/* While recording (#307) the text box is kept but hidden, so Enter and
                  the shortcuts still work; the strip takes its place. The live text
                  keeps filling the box and shows when the recording stops. */}
              <div className={'composer' + (voice.isRecording ? ' recording' : '')}>
                <textarea className={'composer-input' + (voice.busy ? ' dictating' : '')} ref={textareaRef} rows={1} enterKeyHint="send"
                          placeholder={voice.isRecording ? 'Listening…' : strings.composerPh}
                          readOnly={voice.busy} aria-hidden={voice.isRecording || undefined}
                          aria-autocomplete="list" aria-controls={slashItems.length ? 'slash-menu' : undefined}
                          aria-activedescendant={slashItems.length ? 'slash-opt-' + slashActive : undefined}
                          maxLength={MAX_QUESTION_CHARS}
                          value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onComposerKey} />
                {input.length > MAX_QUESTION_CHARS - 200 && (
                  <span className="composer-count" role="status">{input.length.toLocaleString('en-IN')} / {MAX_QUESTION_CHARS.toLocaleString('en-IN')}</span>
                )}
                {voice.isRecording && (
                  <RecordingStrip startedAt={voice.startedAt} live={voice.phase === 'listening'}
                                  status={voice.status} levelRef={voice.levelRef} />
                )}
                <div className="composer-bar">
                  {!voice.isRecording && (voice.busy || voice.status) && (
                    <div className={'voice-status' + (voice.status && voice.status.error ? ' error' : '')}
                         role="status" aria-live="polite">
                      {voice.phase === 'finishing' && <span className="voice-spin" />}
                      {voice.status && (
                        <span className="vs-text" title={voice.status.sub}>
                          <b>{voice.status.text}</b>
                          {voice.status.sub && <span className="vs-sub"> — {voice.status.sub}</span>}
                        </span>
                      )}
                    </div>
                  )}
                  <button className={'mic-btn' + (voice.isRecording ? ' recording' : '')} type="button"
                          onClick={onMic} disabled={voice.phase === 'finishing'}
                          title={(voice.isRecording ? 'Stop recording' : 'Speak your question')
                            // K-40 (audit 2026-10-29): speech is recognised as English whatever the question language
                            + (lang && lang !== 'en' ? ' — voice input is English only' : '') + ` (${keyLabel('mic')})`}
                          aria-label={voice.isRecording ? 'Stop recording' : 'Speak your question'}>
                    {voice.isRecording
                      ? <svg className="orb-stop" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2" /></svg>
                      : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" y1="19" x2="12" y2="23" /><line x1="8" y1="23" x2="16" y2="23" /></svg>}
                  </button>
                  {running ? (
                    <button className="send-btn stop" type="button" onClick={stopQuery}
                            title="Stop this answer (Esc)" aria-label="Stop this answer">
                      <span>Stop</span>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2" /></svg>
                    </button>
                  ) : (
                    <button className={'send-btn' + (voice.busy ? ' voice-send' : '')} type="button" onClick={sendOrFinishVoice}
                            title={voice.busy ? 'Stop recording and send (Enter)' : 'Send (Enter)'}>
                      <span>{strings.sendBtn}</span>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>

      <footer><div>&copy; 2026 Government of Meghalaya — Megh One AI NLP Dashboard</div></footer>
    </>
  );
}
