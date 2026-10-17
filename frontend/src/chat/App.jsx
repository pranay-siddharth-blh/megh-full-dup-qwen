import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  adoptSessionId, archiveConversationApi, checkHealth, ConnectionError, deleteConversationApi, fetchMe, getConversation,
  getToken, listHistory, login, logoutRemote, pinConversationApi, renameConversationApi, resetSessionId,
  setToken, setUnauthorizedHandler, StoppedError, storedSessionId, streamNLPResponse,
} from './api.js';
import { GLOSSARY, LANGS, UI_STRINGS, UNIFIED_SAMPLES } from './constants.js';
import { nowTime, stampTime, todayLabel } from './format.js';
import { useVoice } from './useVoice.js';
import { useSidebarResize } from './useSidebarResize.js';
import { useComposerHeight } from './useComposerHeight.js';
import { BotMessage, TextMessage, TypingMessage } from './components/Messages.jsx';
import { LoginScreen, Modal, UndoToast } from './components/Overlays.jsx';
import { USE_CASE_GROUPS, UseCases } from './components/UseCases.jsx';
import { Sidebar } from './components/Sidebar.jsx';
import { ChatExport } from './components/ChatExport.jsx';
import { ShortcutsHelp } from './components/ShortcutsHelp.jsx';
import { plainText } from './components/Markdown.jsx';
import { copyText } from './components/Messages.jsx';
import { IS_MAC, SHORTCUTS, isTyping, keyLabel, matches } from './shortcuts.js';
import { WelcomeCard } from './components/WelcomeCard.jsx';

/* The chat console (was web/ai_query.html). Every behaviour of the original is
   kept: sign-in gate with a session check, server-backed chat history (pin,
   archive with undo, rename, delete, search), replay of a saved thread with its
   charts, the scheme carousel, voice input, the collapsible sidebar rail
   (Ctrl+B), the mobile drawer, language tabs and the admin entry point. */

const RAIL_KEY = 'megh_sidebar_rail';
const ARCH_OPEN_KEY = 'megh_archive_open';
const readFlag = (k) => { try { return localStorage.getItem(k) === '1'; } catch (e) { return false; } };
const writeFlag = (k, on) => { try { localStorage.setItem(k, on ? '1' : '0'); } catch (e) { /* ignore */ } };

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
  const setInput = (v) => { inputRef.current = v; setInputState(v); };
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
  const loadHistory = useCallback(async () => {
    if (!getToken()) { historyRef.current = []; setHistory([]); return; }
    let list = [];
    try {
      list = await listHistory(filterRef.current);
    } catch (e) {
      if (String(e.message) === 'unauthorized') return;
      list = [];
    }
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
  const runUndo = async () => {
    const fn = toast && toast.fn;
    hideUndo();
    if (fn) await fn();
  };

  // ── Auth flow ───────────────────────────────────────────────────────────
  const lockApp = useCallback(() => {
    setAuth('locked');
    setTimeout(() => usernameRef.current && usernameRef.current.focus(), 0);
  }, []);

  const handleLogout = useCallback((message) => {
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

  const addMessages = (items) => setMessages((m) => [...m, ...items.map((x) => ({ id: nextId(), time: nowTime(), at: new Date().toISOString(), ...x }))]);

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
          replay.push({ id: nextId(), time: answerTime, at: answeredAt && answeredAt.toISOString(), kind: 'bot', text: t.answer || '(no answer recorded)' });
        }
      }
      try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* ignore */ }
      speakingRef.current = null; setSpeakingId(null);
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
        // A network blip must not discard a token that may still be valid.
        if (!(e && e.name === 'AbortError')) setToken('');
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

  const runQuestion = useCallback(async (q, { skipCache = false, addUser = true } = {}) => {
    if (runningRef.current) return;           // one question at a time
    runningRef.current = true; setRunning(true);
    followRef.current = true;                 // the officer just asked: show it
    waitingRef.current = null;                // a new question replaces any waiting one
    const typingId = nextId();
    setMessages((m) => [
      ...m,
      ...(addUser ? [{ id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'user', text: q }] : []),
      { id: typingId, kind: 'typing', steps: [], draft: '' },
    ]);
    const patchTyping = (fn) => setMessages((m) => m.map((x) => (x.id === typingId ? { ...x, ...fn(x) } : x)));
    const onEvent = (ev) => {
      if (ev.type === 'step') patchTyping((x) => ({ steps: [...x.steps, ev.node] }));
      else if (ev.type === 'draft_reset') patchTyping(() => ({ draft: '' }));
      else if (ev.type === 'token') patchTyping((x) => ({ draft: x.draft + ev.text }));
    };
    const stop = new AbortController();
    stopRef.current = stop;
    const dropTyping = (m) => m.filter((x) => x.id !== typingId);
    try {
      const response = await streamNLPResponse(q, lang, sessionRef.current, { skipCache, signal: stop.signal, onEvent });
      setMessages((m) => [...dropTyping(m), response.answer
        ? { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'rich', question: q, response, animate: true, streamKey: typingId }
        : { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, text: `Error: ${response.detail || 'Unable to process your query'}` }]);
      connBack();                             // an answer arrived: the connection is fine
    } catch (err) {
      if (err instanceof ConnectionError) {
        // Not an error with the question: the banner explains, and the
        // question is asked again by itself when the connection is back.
        const msgId = nextId();
        waitingRef.current = { msgId, q };
        setConn('down');
        setMessages((m) => [...dropTyping(m), { id: msgId, time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, waiting: true,
          text: 'Waiting for the connection. This question will be asked again as soon as it is back.' }]);
      } else if (err instanceof StoppedError) {
        setMessages((m) => [...dropTyping(m), { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, text: 'Stopped.' }]);
      } else if (String(err.message) !== 'unauthorized') {
        setMessages((m) => [...dropTyping(m), { id: nextId(), time: nowTime(), at: new Date().toISOString(), kind: 'bot', retryQ: q, text: `Sorry, I encountered an error: ${err.message}` }]);
        console.error('Query error:', err);
      } else {
        setMessages(dropTyping);
      }
    } finally {
      if (stopRef.current === stop) stopRef.current = null;
      runningRef.current = false; setRunning(false);
      if (textareaRef.current) textareaRef.current.focus();
      // The turn is persisted server-side; re-read the history shortly after.
      setTimeout(loadHistory, 600);
    }
  }, [lang, loadHistory, connBack]);

  const sendQuery = useCallback(() => {
    if (runningRef.current) return;
    const q = inputRef.current.trim();
    if (!q) return;
    setInput('');
    runQuestion(q);
  }, [runQuestion]);

  const sendQueryRef = useRef(null);
  sendQueryRef.current = sendQuery;
  const stopQuery = useCallback(() => { if (stopRef.current) stopRef.current.abort(); }, []);

  // Retry (after an error or Stop) and Regenerate (the last answer): the same
  // question again in place of that message, never from the cache.
  const rerun = useCallback((msgId, q) => {
    if (runningRef.current || !q) return;
    stopSpeaking();
    setMessages((m) => m.filter((x) => x.id !== msgId));
    runQuestion(q, { skipCache: true, addUser: false });
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
      if (h === 'ok') {
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
    setInput(q);
    if (textareaRef.current) textareaRef.current.focus();
    if (runningRef.current) {
      const retry = setInterval(() => {
        if (!runningRef.current) { clearInterval(retry); setInput(q); sendQuery(); }
      }, 250);
      setTimeout(() => clearInterval(retry), 90000);
      return;
    }
    sendQuery();
  }, [sendQuery]);

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
    const u = new SpeechSynthesisUtterance(text);
    const voices = synth.getVoices();
    const voice = voices.find((v) => v.lang === 'en-IN') || voices.find((v) => (v.lang || '').startsWith('en'));
    if (voice) u.voice = voice;
    u.lang = voice ? voice.lang : 'en-IN';
    u.onend = u.onerror = () => { if (speakingRef.current === id) { speakingRef.current = null; setSpeakingId(null); } };
    setSpeakingId(id);
    synth.speak(u);
  }, [stopSpeaking]);
  useEffect(() => () => { try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (e) { /* ignore */ } }, []);

  const newChat = useCallback(() => {
    stopSpeaking();
    setSessionId(resetSessionId());          // fresh session -> no context bleed
    setMessages([]);
  }, [stopSpeaking]);

  // Edit a sent question: it and everything after it leave the screen, and the
  // edited text is asked in its place (in the same conversation).
  const editQuestion = useCallback((id, q) => {
    if (runningRef.current) return;
    stopSpeaking();
    setMessages((m) => {
      const i = m.findIndex((x) => x.id === id);
      return i < 0 ? m : m.slice(0, i);
    });
    setInput(q);
    sendQuery();
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

  // Composer auto-grows up to 160px; the scrollbar shows only when the text
  // is longer than that, never on an empty or short box.
  useLayoutEffect(() => {
    const t = textareaRef.current;
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 160) + 'px';
    t.style.overflowY = t.scrollHeight > 160 ? 'auto' : 'hidden';
  }, [input]);

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
    voice.toggleMic();
  };

  // ── Modals ──────────────────────────────────────────────────────────────
  const closeModal = useCallback(() => setModal(null), []);
  const openGlossary = () => setModal({
    title: 'Glossary', sub: 'Domain terms across all schemes',
    body: Object.entries(GLOSSARY).map(([section, terms]) => (
      <div key={section}>
        <div className="modal-section">{section}</div>
        {terms.map((t) => (
          <div key={t.term} className="glossary-term">
            <div className="glossary-term-name">{t.term}</div>
            <div className="glossary-term-def">{t.def}</div>
          </div>
        ))}
      </div>
    )),
  });
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
    // While dictating the box is filling itself: Enter waits for the final text.
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendOrFinishVoice(); }
  };

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
              <div className="lang-tabs">
                {LANGS.map((l) => (
                  <button key={l.code} type="button" className={'lang-tab' + (lang === l.code ? ' active' : '')}
                          data-lang={l.code} onClick={() => setLang(l.code)}>{l.label}</button>
                ))}
              </div>
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
              <WelcomeCard strings={strings} prompts={prompts} setPrompts={setPrompts} onAsk={ask} />
              <div>
                {messages.map((m, i) => {
                  // Regenerate / Try again sit on the latest answer only: an
                  // older one would come back below newer turns, out of place.
                  const isLast = i === messages.length - 1 && !running;
                  if (m.kind === 'typing') return <TypingMessage key={m.id} steps={m.steps} draft={m.draft} streamKey={m.id} />;
                  if (m.kind === 'rich') {
                    return <BotMessage key={m.id} id={m.id} question={m.question} response={m.response} time={m.time}
                                       animate={m.animate} streamKey={m.streamKey} at={m.at}
                                       onAsk={ask} speakingId={speakingId} onSpeak={onSpeak}
                                       onRegenerate={isLast && m.question ? () => rerun(m.id, m.question) : null}
                                       sessionId={sessionId} />;
                  }
                  if (m.kind === 'user') {
                    return <TextMessage key={m.id} id={m.id} role="user" text={m.text} time={m.time}
                                        busy={running} onEdit={(q) => editQuestion(m.id, q)}
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
              <div className="composer">
                <textarea className={'composer-input' + (voice.busy ? ' dictating' : '')} ref={textareaRef} rows={1}
                          placeholder={voice.isRecording ? 'Listening…' : strings.composerPh}
                          readOnly={voice.busy}
                          value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onComposerKey} />
                <div className="composer-bar">
                  {(voice.busy || voice.status) && (
                    <div className={'voice-status' + (voice.status && voice.status.error ? ' error' : '')}
                         role="status" aria-live="polite">
                      {voice.phase === 'finishing' && <span className="voice-spin" />}
                      {voice.isRecording && <span className="voice-bars" ref={voice.levelRef}><i /><i /><i /><i /><i /></span>}
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
                          title={(voice.isRecording ? 'Stop recording' : 'Speak your question') + ` (${keyLabel('mic')})`}
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
