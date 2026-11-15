import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { API_BASE, getToken } from './api.js';
import { IDLE, isLive, reduce } from './dictation/machine.js';
import { begin, compose, restore } from './dictation/insert.js';
import * as micLock from './dictation/micLock.js';
import workletUrl from './voiceWorklet.js?url&no-inline';   // a same-origin file: the CSP refuses data: scripts

/* Dictation (D-111, 2026-11-15): the composer mic types the officer's words, like a chat app's dictation.

   Tap the mic: the microphone and /ws/dictate open together; 80 ms frames of 16 kHz PCM16 (voiceWorklet.js,
   the live voice's own capture) stream to the server, which cuts them at pauses and hears them with our own
   qwen3-asr. Live words come back as {stable, tentative} and sit in the box at the caret (stable in ink,
   tentative muted); the final text replaces them. Tap ✓ (or the mic again, or Enter to also send) to
   insert; ✕ puts the box back exactly as it was. Frames said while the socket is still opening are kept
   and sent once it is ready, so the first word is never lost.

   If the socket cannot be used (dictation switched off on the server, the network refuses WebSockets, an
   old browser), `onFallback` is called and the page uses the previous dictation (useVoice.js: record, then
   one upload to /api/query/transcribe); a network failure keeps the socket off for 5 minutes. */

const FALLBACK_MS = 5 * 60 * 1000;
const FINAL_WAIT_MS = 15000;           // a stop with no answer in this long keeps the live words
const PENDING_MAX = 150;               // frames kept while the socket opens (12 s)
let downUntil = 0;

const wsUrl = () => {
  const base = API_BASE || window.location.origin;
  return (base.startsWith('https') ? 'wss' + base.slice(5) : 'ws' + base.slice(4)) + '/ws/dictate';
};

export function dictationAvailable() {
  return Date.now() > downUntil && typeof WebSocket !== 'undefined' && typeof window !== 'undefined'
    && !!(window.AudioContext || window.webkitAudioContext)
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && !!getToken();
}

export function useDictation({ lang, textareaRef, getValue, setValue, onInserted, onFallback, onUnauthorized }) {
  const [state, dispatch] = useReducer(reduce, IDLE);
  const [range, setRange] = useState(null);      // {start, stableEnd, end} of the live words in the box
  const stateRef = useRef(state);
  stateRef.current = state;
  const levelRef = useRef(null);
  const cb = useRef({});
  cb.current = { getValue, setValue, onInserted, onFallback, onUnauthorized, lang };
  const S = useRef({}).current;                   // the running dictation's resources

  const setLevel = (rms) => {
    const el = levelRef.current;
    if (!el) return;
    const l = Math.min(1, Math.sqrt(rms) * 3.2).toFixed(2);
    if (l !== S.lastLevel) { S.lastLevel = l; el.style.setProperty('--l', l); }
  };

  const teardown = useCallback(() => {
    clearTimeout(S.finalT);
    try { if (S.node) { S.node.port.onmessage = null; S.node.disconnect(); } } catch (e) { /* gone */ }
    try { if (S.src) S.src.disconnect(); } catch (e) { /* gone */ }
    if (S.stream) S.stream.getTracks().forEach((t) => t.stop());
    if (S.ctx && S.ctx.state !== 'closed') S.ctx.close().catch(() => {});
    const ws = S.ws;
    S.ws = null; S.node = null; S.src = null; S.stream = null; S.ctx = null; S.pending = []; S.wsReady = false;
    if (ws) { ws.onmessage = null; ws.onclose = null; try { ws.close(); } catch (e) { /* closed */ } }
    micLock.release('dictation');
  }, [S]);

  // put the live words in the box (and remember where they are, for the muted tentative words)
  const showLive = (stable, tentative) => {
    if (!S.ctx0) return;
    const c = compose(S.ctx0, stable, tentative);
    cb.current.setValue(c.value);
    setRange({ start: c.start, stableEnd: c.stableEnd, end: c.end });
    S.lastLive = { stable, tentative };
  };

  const finishWith = (text, corrections, ended) => {
    const ctx = S.ctx0;
    S.ctx0 = null;
    setRange(null);
    teardown();
    if (!ctx) return;
    const c = compose(ctx, text, '');
    cb.current.setValue(c.value);
    const t = textareaRef.current;
    if (t) {
      requestAnimationFrame(() => {
        try { t.focus(); t.setSelectionRange(c.end, c.end); } catch (e) { /* not focusable */ }
      });
    }
    if (c.value !== ctx.original) cb.current.onInserted({ restore: restore(ctx), corrections: corrections || [], ended });
  };

  const undoLive = () => {
    const ctx = S.ctx0;
    S.ctx0 = null;
    setRange(null);
    if (!ctx) return;
    const r = restore(ctx);
    cb.current.setValue(r.value);
    const t = textareaRef.current;
    if (t) requestAnimationFrame(() => { try { t.focus(); t.setSelectionRange(r.selStart, r.selEnd); } catch (e) { /* */ } });
  };

  const fallback = (why) => {
    undoLive();
    teardown();
    if (why === 'network') downUntil = Date.now() + FALLBACK_MS;
    dispatch({ type: 'RESET' });
    cb.current.onFallback(why);
  };

  const onMessage = (m) => {
    switch (m.type) {
      case 'ready':
        S.wsReady = true;
        dispatch({ type: 'READY', at: Date.now() });
        if (S.ws && S.ws.readyState === 1) {
          for (const f of S.pending) S.ws.send(f);
          if (S.stopAfterReady) S.ws.send(JSON.stringify({ type: 'stop' }));
        }
        S.pending = [];
        break;
      case 'partial':
        if (m.seq > (S.seq || 0)) {
          S.seq = m.seq;
          dispatch({ type: 'PARTIAL', seq: m.seq, stable: m.stable, tentative: m.tentative });
          showLive(m.stable, m.tentative);
        }
        break;
      case 'final':
        dispatch({ type: 'FINAL', text: m.text, corrections: m.corrections, ended: m.ended });
        finishWith(m.text, m.corrections, m.ended);
        break;
      case 'no_speech':
        dispatch({ type: 'NO_SPEECH' });
        undoLive();
        teardown();
        break;
      case 'error':
        if (!S.wsReady && (m.reason === 'off' || m.reason === 'busy')) { fallback(m.reason); return; }
        if (m.reason === 'auth') { dispatch({ type: 'ERROR', kind: 'auth' }); undoLive(); teardown(); cb.current.onUnauthorized(); return; }
        dispatch({ type: 'ERROR', kind: m.reason });
        if (S.lastLive && S.lastLive.stable) finishWith(S.lastLive.stable, [], null);
        else { undoLive(); teardown(); }
        break;
      case 'closed':
        if (m.reason === 'replaced') { dispatch({ type: 'CLOSED', reason: 'replaced' }); undoLive(); teardown(); }
        break;
      default:
        break;
    }
  };

  const openSocket = () => {
    let ws;
    try { ws = new WebSocket(wsUrl()); } catch (e) { return false; }
    ws.binaryType = 'arraybuffer';
    S.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', token: getToken(), lang: cb.current.lang || 'en' }));
    ws.onmessage = (ev) => {
      if (S.ws !== ws || typeof ev.data !== 'string') return;
      try { onMessage(JSON.parse(ev.data)); } catch (e) { /* not ours */ }
    };
    ws.onclose = (ev) => {
      if (S.ws !== ws) return;
      const st = stateRef.current;
      if (!isLive(st)) return;
      if (!S.wsReady) {
        if (ev.code === 4401) { dispatch({ type: 'ERROR', kind: 'auth' }); undoLive(); teardown(); cb.current.onUnauthorized(); return; }
        if (ev.code === 4429) { dispatch({ type: 'ERROR', kind: 'rate' }); undoLive(); teardown(); return; }
        fallback('network');
        return;
      }
      // closed after ready with no final: keep what was heard
      dispatch({ type: 'CLOSED', reason: 'lost' });
      if (S.lastLive && (S.lastLive.stable || S.lastLive.tentative)) {
        finishWith([S.lastLive.stable, S.lastLive.tentative].filter(Boolean).join(' '), [], null);
      } else { undoLive(); teardown(); }
    };
    return true;
  };

  const startCapture = async () => {
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC();
    S.ctx = ctx;
    if (ctx.state === 'suspended') await ctx.resume().catch(() => {});
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    if (S.ctx !== ctx) { stream.getTracks().forEach((t) => t.stop()); return false; }   // cancelled meanwhile
    S.stream = stream;
    const src = ctx.createMediaStreamSource(stream);
    S.src = src;
    const sink = ctx.createGain(); sink.gain.value = 0; sink.connect(ctx.destination);
    await ctx.audioWorklet.addModule(workletUrl);
    if (S.ctx !== ctx) return false;
    const node = new AudioWorkletNode(ctx, 'megh-pcm-capture');
    node.port.onmessage = (ev) => {
      const { pcm, rms } = ev.data;
      setLevel(rms);
      if (S.stopped) return;
      if (S.ws && S.wsReady && S.ws.readyState === 1) S.ws.send(pcm);
      else if (S.pending.length < PENDING_MAX) S.pending.push(pcm);
    };
    src.connect(node); node.connect(sink);
    S.node = node;
    return true;
  };

  const stop = useCallback(() => {
    const st = stateRef.current;
    if (!isLive(st)) return;
    if (st.status === 'permission') { cancelRef.current(); return; }
    if (st.status === 'finishing') return;
    S.stopped = true;
    dispatch({ type: 'STOP' });
    if (S.stream) S.stream.getTracks().forEach((t) => t.stop());     // the microphone light goes off at once
    if (S.ws && S.wsReady && S.ws.readyState === 1) S.ws.send(JSON.stringify({ type: 'stop' }));
    else S.stopAfterReady = true;
    clearTimeout(S.finalT);
    S.finalT = setTimeout(() => {
      if (!isLive(stateRef.current)) return;
      dispatch({ type: 'CLOSED', reason: 'lost' });
      const l = S.lastLive;
      if (l && (l.stable || l.tentative)) finishWith([l.stable, l.tentative].filter(Boolean).join(' '), [], null);
      else { undoLive(); teardown(); }
    }, FINAL_WAIT_MS);
  }, [S]); // eslint-disable-line react-hooks/exhaustive-deps -- reads S and the latest callbacks through refs

  const cancel = useCallback(() => {
    if (!isLive(stateRef.current)) return;
    if (S.ws && S.ws.readyState === 1) { try { S.ws.send(JSON.stringify({ type: 'cancel' })); } catch (e) { /* */ } }
    dispatch({ type: 'CANCEL' });
    undoLive();
    teardown();
  }, [S]); // eslint-disable-line react-hooks/exhaustive-deps
  const cancelRef = useRef(cancel);
  cancelRef.current = cancel;
  const stopRef = useRef(stop);
  stopRef.current = stop;

  const start = useCallback(async () => {
    if (isLive(stateRef.current)) return true;
    if (!dictationAvailable()) { cb.current.onFallback('unavailable'); return false; }
    if (!micLock.acquire('dictation', () => stopRef.current())) return false;
    const t = textareaRef.current;
    const value = cb.current.getValue();
    S.ctx0 = begin(value, t ? t.selectionStart : value.length, t ? t.selectionEnd : value.length);
    S.pending = []; S.seq = 0; S.wsReady = false; S.stopped = false; S.stopAfterReady = false; S.lastLive = null;
    dispatch({ type: 'START' });
    if (!openSocket()) { fallback('network'); return false; }
    try {
      const ok = await startCapture();
      if (!ok) return false;
      dispatch({ type: 'MIC_OK', at: Date.now() });
      return true;
    } catch (e) {
      const name = e && e.name;
      if (S.ws) { try { S.ws.send(JSON.stringify({ type: 'cancel' })); } catch (err) { /* */ } }
      dispatch({ type: name === 'NotFoundError' || name === 'OverconstrainedError' ? 'MIC_NONE'
        : name === 'NotAllowedError' || name === 'SecurityError' ? 'MIC_DENIED' : 'ERROR', kind: 'unavailable' });
      undoLive();
      teardown();
      return false;
    }
  }, [S, textareaRef]); // eslint-disable-line react-hooks/exhaustive-deps

  // an error / cancelled state is shown briefly, then the bar goes away
  useEffect(() => {
    if (state.status !== 'error' && state.status !== 'cancelled') return undefined;
    const id = setTimeout(() => dispatch({ type: 'RESET' }), state.status === 'error' ? 5000 : 10);
    return () => clearTimeout(id);
  }, [state.status]);

  useEffect(() => () => { teardown(); }, [teardown]);

  return {
    state,
    active: isLive(state),
    range,
    levelRef,
    start,
    stop,
    cancel,
  };
}
