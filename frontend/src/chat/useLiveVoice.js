import { useCallback, useEffect, useRef, useState } from 'react';
import { API_BASE, fetchVoiceBoard, getToken } from './api.js';
import { isStopText } from './stopContinue.js';
import { AI_DISCLOSURE, askedOf, greetingHeading, greetingLine, spokenForm, spokenNote } from './voiceSpeech.js';
import { plan } from './voice/vizPlan.js';
import { canonicalNav, canonicalView, CHAT_VIEWS, isRedraw, NAV_SPEECH, NO_PICTURE, viewSpeech } from './voice/voiceViews.js';
import { readVoice, saveVoice, SWITCH_LINE, VOICES } from './voice/voices.js';
import { addAudio, addText, cut as cutCaptions, finish as finishCaptions, newPacer, pending as captionsPending, shownText, step as stepCaptions } from './voice/captionPacer.js';
import workletUrl from './voiceWorklet.js?url&no-inline';   // a same-origin file: the CSP refuses data: scripts

/* Full-duplex voice (2026-11-02), the browser half. Ported from Mitra's live
   client (D:/Sakala POC/mitra/web/mitra.js, the LV block).

   The mic button opens a live conversation over /ws/voice: the microphone
   streams continuously (16 kHz PCM), the voice streams back (24 kHz PCM) and is
   cut the instant the officer talks over it. The voice has one function,
   ask_megh, and it is answered HERE through the chat's own send path (the same
   one a typed question takes, via `submit`), so the answer appears in the chat
   exactly as a typed one: card, chart, chips, history, Stop, Regenerate. When it
   lands (seen in `messages`), its spoken form goes back to the voice to be read
   word for word. A typed question or a chip tapped while live is read aloud too.

   Phases: off | connecting | live. Any failure: the hook says so (onNotice),
   stays off for 5 minutes (`available()` is false) and the mic button falls back
   to the existing dictation. 25 s of quiet closes it (the per-minute cost stops).

   2026-11-11: a chart switch said by voice (one of the shaper's seven sentences, voice/voiceViews.js) redraws the
   picture on screen with no pipeline round trip (the stage registers how: registerStage); a question that arrives while
   an answer is still being written waits (the newest one only) and is asked the moment that answer is done, or at
   once when the officer talked over it (the engine cancelled the old call). */

const FALLBACK_MS = 5 * 60 * 1000;
const MUTED_KEEP_MS = 10 * 60 * 1000;
const SILENT_MODEL_MS = 7000;           // the officer finished and the model said / called nothing: the page answers   // a muted session is kept open this long (mute must never end the conversation)
const ANSWER_TIMEOUT_MS = 95000;
const QUEUE_MAX_MS = 100000;            // a question waiting behind a running answer gives up after this
const BARGE_MS = 8000;                  // a question this soon after the officer talked over the voice: the running answer is dropped
const FIRST_ASK_MS = 9000;              // open(question): asked after the hello's turn ends, or after this at the latest
const GREETING_WORDS = ['hello', 'hi', 'hey', 'thanks', 'thank you', 'ok', 'okay', 'bye', 'goodbye'];

const wsUrl = () => {
  const base = API_BASE || window.location.origin;
  return (base.startsWith('https') ? 'wss' + base.slice(5) : 'ws' + base.slice(4)) + '/ws/voice';
};
const words = (s) => String(s || '').trim().split(' ').filter((w) => w.length > 0);
const isGreeting = (s) => {
  const t = words(String(s || '').toLowerCase().split('.').join(' ').split('?').join(' ').split('!').join(' ').split(',').join(' ')).join(' ');
  return !t || GREETING_WORDS.includes(t) || t === 'can you hear me';
};
const lastId = (msgs) => (msgs.length ? msgs[msgs.length - 1].id : 0);
const isFinal = (m) => m && (m.kind === 'rich' || m.kind === 'bot');

export function useLiveVoice({ submit, stop, isRunning, onNotice }) {
  const [phase, setPhase] = useState('off');
  // megh = the voice's words shown so far (paced by the audio that plays, voice/captionPacer.js); flow = a reading is
  // under way on screen (steady across the short gaps between audio chunks, so the captions' styling never flickers)
  const [captions, setCaptions] = useState({ you: '', megh: '', flow: false });
  const [speaking, setSpeaking] = useState(false);
  const [latencyMs, setLatencyMs] = useState(null);
  const [muted, setMutedState] = useState(false);     // the microphone track is off; the session and the answer go on
  const [view, setView] = useState(false);            // the voice stage is up (it stays up in standby)
  const [thinking, setThinking] = useState(false);    // a question is with the pipeline
  const [turnsDone, setTurnsDone] = useState(0);      // the relay's end-of-turn count (the voice finished an answer)
  const [resting, setResting] = useState(false);     // after a fallback the voice rests (the agent orb turns grey, D-113)
  const meterYou = useRef(null);
  const meterMegh = useRef(null);
  const S = useRef({
    ws: null, ctx: null, stream: null, node: null, src: null, outGain: null, an: null, nextT: 0, srcs: [],
    playing: false, cut: false, loud: 0, lastVoice: 0, idleT: 0, idleMs: 25000, fallbackUntil: 0,
    pending: null, msgs: [], seenId: 0, userEnd: 0, firstAudio: 0, inTx: '', cap: newPacer(), capTimer: 0, capFlow: false, raf: 0, micRms: 0,
    readQueue: [], muted: false, micAn: null, openedAt: 0,
    stage: null, queued: null, qT: 0, bargeAt: 0, skipStop: false,
  }).current;
  const cb = useRef({ submit, stop, isRunning, onNotice });
  cb.current = { submit, stop, isRunning, onNotice };
  const testLog = useRef([]);

  const send = (obj) => { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(obj)); };
  // typed into the live session ({type:'text'}: the model hears it as the officer's words and calls ask_megh); the
  // silent-model harness is armed as for speech. Used by open(question) and the headless test hook.
  const sendText = (t, prefix = '') => {
    if (!S.ws || S.ws.readyState !== 1) return false;
    S.typedTx = t; S.lastVoice = performance.now();
    S.ws.send(JSON.stringify({ type: 'text', text: prefix + t }));
    armSilent();
    return true;
  };
  // open(question) (D-113, a question tapped on the voice panel): asked once the hello (with the AI disclosure, D-108)
  // has been said, so the disclosure is never talked over
  const askFirst = () => {
    clearTimeout(S.firstT);
    const q = S.firstAsk; S.firstAsk = '';
    if (q && phaseRef.current === 'live') { log({ type: 'first_ask', question: q }); sendText(q); }
  };
  const log = (e) => { if (window.__meghVoice) testLog.current.push({ ...e, t: Math.round(performance.now()) }); };

  // ── playback: 24 kHz PCM on a queue, cut at once ──────────────────────
  const cutAudio = useCallback(() => {
    for (const s of S.srcs) { try { s.stop(); } catch (e) { /* ended */ } }
    S.srcs = []; S.nextT = 0; S.lastStart = 0; S.playing = false; setSpeaking(false);
    // words not yet heard are not shown; what the voice says next starts a new reading
    const kept = S.cap.shown;
    S.cap = cutCaptions(S.cap, S.ctx ? S.ctx.currentTime : null); clearInterval(S.capTimer); S.capTimer = 0;
    if (S.capFlow || S.cap.shown !== kept) {
      S.capFlow = false;
      const megh = shownText(S.cap);
      setCaptions((c) => ({ ...c, megh, flow: false }));
    }
    if (S.outGain && S.ctx) S.outGain.gain.setTargetAtTime(1, S.ctx.currentTime, 0.05);
  }, [S]);
  const duck = (on) => { if (S.outGain && S.ctx) S.outGain.gain.setTargetAtTime(on ? 0.18 : 1, S.ctx.currentTime, 0.04); };
  const playPcm = (ab) => {
    if (S.cut || !S.ctx) return;
    const i16 = new Int16Array(ab);
    const f = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f[i] = i16[i] / 32768;
    const b = S.ctx.createBuffer(1, f.length, 24000);
    b.copyToChannel(f, 0);
    const src = S.ctx.createBufferSource();
    src.buffer = b; src.connect(S.outGain);
    const t = Math.max(S.ctx.currentTime + 0.03, S.nextT);
    src.start(t); S.nextT = t + b.duration; S.lastStart = t; S.srcs.push(src);
    addAudio(S.cap, t, b.duration);
    src.onended = () => {
      S.srcs = S.srcs.filter((x) => x !== src);
      if (!S.srcs.length) { S.playing = false; setSpeaking(false); duck(false); S.lastVoice = performance.now(); armIdle(); }
    };
    if (!S.playing) {
      S.playing = true; setSpeaking(true);
      if (!S.firstAudio) {
        S.firstAudio = performance.now();
        if (S.userEnd) { const ms = S.firstAudio - S.userEnd; if (ms > 0 && ms < 60000) setLatencyMs(Math.round(ms)); }
      }
    }
  };
  // ── captions: the words shown follow the audio that plays (voice/captionPacer.js; 2026-11-15) ──
  // 20 ticks a second while a reading is on screen; a state update only when a word is added (or the flow changes)
  const capTick = () => {
    const p = S.cap;
    const nowMs = performance.now();
    const before = p.shown;
    stepCaptions(p, S.ctx ? S.ctx.currentTime : 0, nowMs);
    const idle = !captionsPending(p) || (p.shown >= p.words.length && !S.playing && nowMs - p.textAt > 1500);
    const flow = !idle || S.playing;
    if (p.shown !== before || flow !== S.capFlow) {
      S.capFlow = flow;
      const megh = shownText(p);
      setCaptions((c) => (c.megh === megh && c.flow === flow ? c : { ...c, megh, flow }));
    }
    if (idle && !S.playing) { clearInterval(S.capTimer); S.capTimer = 0; }
  };
  const capKick = () => {
    if (!S.capTimer) S.capTimer = setInterval(capTick, 50);
    capTick();
  };
  const outLevel = () => {
    if (!S.an || !S.playing) return 0;
    const d = S.ob || (S.ob = new Uint8Array(S.an.fftSize));
    S.an.getByteTimeDomainData(d);
    let s = 0; for (let i = 0; i < d.length; i++) s += (d[i] - 128) * (d[i] - 128);
    return Math.sqrt(s / d.length) / 128;
  };

  // ── capture: 80 ms frames from the worklet; echo guard; local barge-in ──
  const onFrame = (pcm, rms) => {
    S.micRms = rms;
    if (!S.ws || S.ws.readyState !== 1 || phaseRef.current !== 'live') return;
    if (S.muted) { S.ws.send(new Int16Array(pcm.byteLength / 2).buffer); return; }   // muted: silence keeps the stream's clock
    const out = outLevel();
    // while the voice plays through speakers, frames quieter than its own echo go as silence (it never cuts itself off)
    const echo = S.playing && rms < Math.max(0.05, out * 0.7);
    // a voice clearly louder than the echo ducks the playback at once; Gemini's `interrupted` then cuts it
    if (S.playing && rms > Math.max(0.09, out * 1.8)) { S.loud += 1; if (S.loud === 2) duck(true); } else S.loud = 0;
    S.ws.send(echo ? new Int16Array(pcm.byteLength / 2).buffer : pcm);
    if (rms > 0.04) { S.lastVoice = performance.now(); armIdle(); }
  };

  const phaseRef = useRef('off');
  const setPh = (p) => { phaseRef.current = p; setPhase(p); };

  const armIdle = () => {
    clearTimeout(S.idleT);
    S.idleT = setTimeout(() => {
      if (phaseRef.current !== 'live') return;
      // idle = nobody has spoken, nothing played, nothing asked for idleMs; muted: kept open (up to MUTED_KEEP_MS)
      const quiet = performance.now() - S.lastVoice;
      if (S.playing || S.pending || quiet < S.idleMs - 500 || (S.muted && quiet < MUTED_KEEP_MS)) { armIdle(); return; }
      end('idle');
    }, S.idleMs);
  };

  // the harness for a model that ignores a question (measured on the real voice 2026-11-02: "show it as a bar chart"
  // got neither a call nor a word, and the session idled out): SILENT_MODEL_MS after the officer finished, with no
  // call, no speech and nothing pending, the words go through the pipeline and the checked answer is read
  const armSilent = () => {
    clearTimeout(S.silentT);
    S.silentT = setTimeout(() => {
      if (S.pending || S.playing || phaseRef.current !== 'live') return;
      const said = (S.inTx || S.typedTx || '').trim();
      S.typedTx = '';
      if (!said || isGreeting(said) || askedJustNow(said) || S.queued) return;
      log({ type: 'harness', said, silent: true });
      ask(said, null);
    }, SILENT_MODEL_MS);
  };
  const quietModel = () => clearTimeout(S.silentT);
  // the same words already went to the pipeline in the last 2 minutes (by the call or a guard): never ask them twice
  const askedJustNow = (said) => !!S.lastAsk && S.lastAsk.q === String(said).trim().toLowerCase()
    && performance.now() - S.lastAsk.t < 120000;

  // ── answering ask_megh through the chat's own path ────────────────────
  const reply = (id, result) => {
    S.lastSpeak = result.speak;
    S.lastVoice = performance.now();
    setThinking(false);
    log({ type: 'reply', id, kind: result.kind, speak: result.speak });
    if (id) send({ type: 'tool_result', id, result });
    else send({ type: 'read', text: result.speak, kind: result.kind, asked_as: result.asked_as, frame: result.frame });
  };
  // a call that will never be answered (a newer question took its place): the relay needs a result for every call
  const supersede = (id) => {
    if (!id) return;
    log({ type: 'superseded', id });
    send({ type: 'tool_result', id, result: { speak: 'That question was replaced by the next one.', kind: 'superseded', read_exactly: false, on_screen: false } });
  };
  // the queue: one question waits behind a running answer (the newest; an older one is replaced)
  const pump = () => {
    clearTimeout(S.qT);
    const x = S.queued;
    if (!x) return;
    // free = nothing running AND the chat has drawn the end of it (no typing dots left in what this hook last saw), so
    // the next question's "after" mark is past the old answer (or its "Stopped." note)
    const tail = S.msgs[S.msgs.length - 1];
    if (!cb.current.isRunning() && !S.pending && !(tail && tail.kind === 'typing')) {
      S.queued = null; S.skipStop = false;
      log({ type: 'dequeue', id: x.id, question: x.q, waited: Math.round(performance.now() - x.at) });
      ask(x.q, x.id, x.key);
      return;
    }
    if (performance.now() - x.at > QUEUE_MAX_MS) {
      S.queued = null;
      reply(x.id, { speak: 'The earlier answer is still being written, so I could not take that question. Please ask it again.', kind: 'note', read_exactly: true });
      return;
    }
    S.qT = setTimeout(pump, 120);
  };
  const enqueue = (question, id, key) => {
    const old = S.queued;
    if (old) { log({ type: 'queue_drop', id: old.id, question: old.q }); if (old.id !== id) supersede(old.id); }
    S.queued = { q: question, id, key: key || '', at: performance.now() };
    log({ type: 'queued', id, question });
    // the officer talked over the voice just now and asks something else: the running answer is dropped, this goes at once
    const p = S.pending;
    if (p && S.bargeAt && performance.now() - S.bargeAt < BARGE_MS && S.bargeAt > p.at) {
      clearTimeout(p.timer); S.pending = null;
      log({ type: 'barge_drop', id: p.id, question: p.question });
      supersede(p.id);
      S.skipStop = true;                       // the chat's "Stopped." note for the dropped answer is not read aloud
      if (cb.current.isRunning()) cb.current.stop();
    }
    setThinking(true);
    pump();
  };
  // what the voice reads for an answer in the chat: a chart switch (the chat's local redraw) is one short line about
  // the view the stage drew; anything else as before
  const spokenOf = (m) => {
    if (isRedraw(m)) {
      let p = null;
      try { p = plan(m.response, m.question, m.view); } catch (e) { p = null; }
      return { speak: viewSpeech(m.view, p ? p.applied : null), kind: 'view', read_exactly: true, on_screen: true };
    }
    // 2026-11-16 (voice audit item 2): the pipeline's own reading of the question goes with the words to read, so
    // the voice engine remembers the conversation as the pipeline understood it (a typed or chip turn included)
    return m.kind === 'rich' ? { ...spokenForm(m.response), ...askedOf(m.response, m.question) } : spokenNote(m.text);
  };
  // the chat's last answers (at most 3), sent to the voice engine when the voice opens: a voice session that starts
  // after typed turns, or reopens, continues the same conversation (the sovereign engine; Gemini never gets them)
  const contextItems = () => {
    const out = [];
    for (let i = S.msgs.length - 1; i >= 0 && out.length < 3; i--) {
      const m = S.msgs[i];
      if (m && m.kind === 'rich' && !isRedraw(m)) {
        const sp = spokenForm(m.response);
        out.unshift({ ...askedOf(m.response, m.question), kind: sp.kind, speak: sp.speak });
      }
    }
    return out.filter((x) => x.asked_as || x.frame);
  };
  const ask = (q, id, key = '') => {
    const question = String(q || '').trim();
    if (!question) { reply(id, { speak: 'I did not catch a question.', kind: 'note', read_exactly: true }); return; }
    // navigation (2026-11-11): back to the dashboard / the chart again. Done on the stage, never asked of the pipeline,
    // and done at once even while an answer is still being worked out (Mitra's go_to)
    const nav = canonicalNav(question);
    if (nav) {
      const st = S.stage;
      const verdict = st && st.nav ? st.nav(nav) : { speak: nav === 'desk' ? NAV_SPEECH.desk : NAV_SPEECH.nochart };
      log({ type: 'ask', id, question, nav, local: true });
      log({ type: 'nav', nav, speak: verdict.speak });
      S.lastAsk = { q: question.toLowerCase(), t: performance.now() };
      reply(id, { speak: verdict.speak, kind: 'nav', read_exactly: true, on_screen: true });
      return;
    }
    if (cb.current.isRunning() || S.pending) {
      if (isStopText(question)) {
        if (S.queued) { supersede(S.queued.id); S.queued = null; }
        cb.current.stop(); reply(id, { speak: 'Stopped.', kind: 'note', read_exactly: true }); return;
      }
      enqueue(question, id, key);              // asked the moment the running answer is done
      return;
    }
    // a chart switch: the picture on screen is drawn another way, no pipeline round trip
    const view = canonicalView(question);
    if (view) {
      const st = S.stage;
      const verdict = st ? st.view(view) : (CHAT_VIEWS.includes(view) ? null : { speak: NO_PICTURE });
      if (verdict && verdict.speak) {
        log({ type: 'ask', id, question, view, local: true });
        log({ type: 'view', view, local: true, speak: verdict.speak });
        S.lastAsk = { q: question.toLowerCase(), t: performance.now() };
        reply(id, { speak: verdict.speak, kind: 'view', read_exactly: true, on_screen: true });
        return;
      }
      log({ type: 'view', view, local: false });   // bar / line / pie / table: the chat's own redraw, read by spokenOf
    }
    if (S.pending) clearTimeout(S.pending.timer);
    S.pending = { id, question, key: key || '', at: performance.now(), after: lastId(S.msgs), sawUser: false,
      timer: setTimeout(() => { if (S.pending && S.pending.id === id) { S.pending = null; reply(id, { speak: 'The answer is taking longer than usual. It will appear on your screen.', kind: 'pending', read_exactly: true }); } }, ANSWER_TIMEOUT_MS) };
    log({ type: 'ask', id, question });
    S.lastAsk = { q: question.toLowerCase(), t: performance.now() };
    setThinking(true);
    cb.current.submit(question);
  };

  // every change of the chat's messages: is the answer we wait for there? an answer to read aloud?
  const onMessages = useCallback((msgs) => {
    const prev = S.msgs;
    S.msgs = msgs;
    const p = S.pending;
    if (p) {
      if (msgs.length < prev.length && lastId(msgs) <= p.after) {     // the chat was left or cleared meanwhile
        clearTimeout(p.timer); S.pending = null;
        reply(p.id, spokenNote('That chat was closed, so the answer is not shown here.'));
        return;
      }
      // the first answer, note or redraw after the question (the typing dots are not final)
      const done = msgs.find((m) => m.id > p.after && isFinal(m));
      if (done) {
        clearTimeout(p.timer); S.pending = null; S.seenId = lastId(msgs);
        reply(p.id, spokenOf(done));
        if (S.queued) pump();
      }
      return;
    }
    // not ours: a typed question or a chip answered while live is read aloud too
    const last = msgs[msgs.length - 1];
    if (phaseRef.current === 'live' && isFinal(last) && last.id > S.seenId && msgs.length - prev.length <= 2
        && msgs.length >= 2 && msgs[msgs.length - 2].kind === 'user') {
      if (S.skipStop && last.kind === 'bot') S.skipStop = false;       // the note of an answer dropped for a newer question
      else reply(null, spokenOf(last));
    }
    S.seenId = Math.max(S.seenId, lastId(msgs));
  }, [S]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── events from the relay ─────────────────────────────────────────────
  const onEvent = (e) => {
    log(e);
    switch (e.type) {
      case 'ready':
        S.idleMs = Math.max(8000, (e.idle_seconds || 25) * 1000);
        setPh('live'); S.lastVoice = performance.now(); armIdle();
        for (const x of S.readQueue.splice(0)) send(x);
        { const items = contextItems(); if (items.length) send({ type: 'context', items }); }
        if (S.greet) {                                                                   // once per opening of the stage
          S.greet = false;
          // a question waits (open(question)): the hello is just the greeting and the disclosure, then the question
          send({ type: 'read', text: S.firstAsk ? `${greetingHeading()}. ${AI_DISCLOSURE}.` : greetingLine() });
          if (S.firstAsk) { clearTimeout(S.firstT); S.firstT = setTimeout(askFirst, FIRST_ASK_MS); }
        } else if (S.firstAsk) askFirst();
        if (S.switchLine) send({ type: 'read', text: SWITCH_LINE });                         // a new voice says hello
        S.switchLine = false;
        break;
      case 'vad':
        // the officer started talking: whatever is still queued is cut now (when the model had already sent the
        // whole answer there is nothing left for it to interrupt, so no `interrupted` would come)
        if (String(e.state).includes('START')) { S.userEnd = 0; quietModel(); if (S.playing) cutAudio(); }
        else { S.userEnd = performance.now(); armSilent(); }
        break;
      case 'in':
        if (S.playing) cutAudio();                    // the officer is talking: barge-in, whatever turn it is
        if (S.firstAsk) { clearTimeout(S.firstT); S.firstAsk = ''; log({ type: 'first_ask_dropped' }); }   // they asked their own
        if (!S.inTx) { S.cut = false; S.firstAudio = 0; }
        S.inTx += e.text; S.userEnd = performance.now(); S.lastVoice = performance.now();
        S.cap = newPacer(); S.capFlow = false;
        setCaptions({ you: S.inTx.trim(), megh: '', flow: false });
        break;
      case 'out':
        quietModel();
        // the transcript runs ahead of the audio (measured 2026-11-02 on the real voice: the whole answer's text in
        // under 5 s, its audio 25 s) and, since 14 Nov, comes a checked sentence at a time; the caption, and the
        // speech-synced reveal of the picture that reads it, show each word when the audio reaches it
        // (voice/captionPacer.js; 2026-11-15: they used to wait for the last chunk queued, i.e. the end of the burst)
        addText(S.cap, e.text || '', performance.now());
        capKick();
        break;
      case 'tool_call':
        quietModel();
        // the model's own reading of the officer's words (it is told to pass them exactly as said). Measured on real
        // speech (2026-11-02): the live transcript lags the call ("and for" while the model had "and for Ri Bhoi?")
        // and mishears ("2020 3-24" for 2023-24), so it is only the fallback
        ask(e.question || e.heard, e.id, e.key);
        break;
      case 'tool_cancel':
        // a call waiting in the queue was dropped by the engine: it simply goes (the running answer is not touched)
        if (S.queued && e.key && S.queued.key === e.key) { log({ type: 'queue_drop', id: S.queued.id, cancelled: true }); S.queued = null; break; }
        if (S.pending) { clearTimeout(S.pending.timer); S.pending = null; }
        if (S.queued) S.skipStop = true;      // the next question goes at once; the "Stopped." note is not read
        cb.current.stop();
        pump();
        break;
      case 'interrupted':
        cutAudio(); S.cut = false; S.bargeAt = performance.now();
        break;
      case 'turn_complete': {
        quietModel();
        // the harness: the officer asked something and the voice called nothing and said nothing, or said figures of
        // its own: the question goes through the pipeline anyway and its checked answer is read. A voice that answered
        // in words without figures (a greeting, "yes, go on") is left alone: re-asking those words made the edge layer
        // answer a second time ("You asked me ...", found on the real voice 2026-11-02)
        const said = e.user || S.inTx;
        const fromMemory = (e.deviations || []).length > 0;
        const voiceSilent = !String(e.said || '').trim();
        if (!e.called && said && (fromMemory || (voiceSilent && !isGreeting(said) && words(said).length >= 3))
            && !S.pending && !S.queued && !askedJustNow(said)) {
          log({ type: 'harness', said, fromMemory });
          ask(said, null);
        } else if (e.called && fromMemory && S.lastSpeak && !S.corrected) {
          // the voice was given the checked answer but said a number it does not contain: the checked answer is read
          // again, exactly (the deterministic guard behind the "read it word for word" rule; once per answer)
          S.corrected = true;
          log({ type: 'correction', deviations: e.deviations });
          send({ type: 'read', text: 'To be exact: ' + S.lastSpeak });
        }
        if (e.called) S.corrected = false;
        setTurnsDone((n) => n + 1);
        finishCaptions(S.cap, performance.now()); capKick();
        S.inTx = ''; S.firstAudio = 0;
        armIdle();
        if (S.firstAsk) askFirst();                  // the hello has been said: now the question tapped on the panel
        break;
      }
      case 'goaway':
        end('goaway', true);
        setTimeout(() => start(), 300);
        break;
      case 'closed':
        end(e.reason || 'closed', true);
        if (e.reason === 'replaced') setView(false);          // another tab took the live voice over
        break;
      case 'error':
        end('error', true); setView(false);
        cb.current.onNotice(e.reason === 'auth' ? 'Live voice needs you to be signed in. Please sign in again.'
          : 'Live voice could not start. The dictation mic still works.');
        break;
      case 'fallback':
        S.fallbackUntil = Date.now() + FALLBACK_MS;
        setResting(true); clearTimeout(S.restT); S.restT = setTimeout(() => setResting(false), FALLBACK_MS + 50);
        end('fallback', true); setView(false);
        cb.current.onNotice(e.reason === 'voice off' ? 'Live voice is switched off here. The mic types your words instead.'
          : 'Live voice is unavailable right now. The mic types your words instead.');
        break;
      default:
        break;
    }
  };

  // ── open / close ──────────────────────────────────────────────────────
  const available = useCallback(() => Date.now() > S.fallbackUntil && typeof WebSocket !== 'undefined'
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && !!getToken(), [S]);

  const meters = () => {
    // written only when the drawn level changes (two decimals): an unchanged value no longer restyles the meters 60
    // times a second while nobody talks
    let lastYou = ''; let lastMe = '';
    const tick = () => {
      if (phaseRef.current === 'off') return;
      const you = Math.min(1, S.micRms * 7).toFixed(2);
      const me = Math.min(1, outLevel() * 5).toFixed(2);
      if (meterYou.current && you !== lastYou) { lastYou = you; meterYou.current.style.setProperty('--l', you); }
      if (meterMegh.current && me !== lastMe) { lastMe = me; meterMegh.current.style.setProperty('--l', me); }
      S.raf = requestAnimationFrame(tick);
    };
    S.raf = requestAnimationFrame(tick);
  };

  // the live session's socket; the hello carries the officer's voice choice (the voice toggle, 2026-11-12)
  const openWs = () => {
    const ws = new WebSocket(wsUrl());
    ws.binaryType = 'arraybuffer';
    S.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: 'hello', token: getToken(), voice: readVoice() }));
    ws.onmessage = (ev) => {
      if (S.ws !== ws) return;
      if (typeof ev.data === 'string') { try { onEvent(JSON.parse(ev.data)); } catch (e) { /* not ours */ } }
      else playPcm(ev.data);
    };
    ws.onclose = () => { if (S.ws === ws) end('closed', true); };
    ws.onerror = () => { };
    return ws;
  };
  // a new voice: the session is opened again with it (the microphone and the stage stay), and it says one line
  const [voiceKey, setVoiceKey] = useState(readVoice);
  const setVoice = useCallback((k) => {
    if (!VOICES.some((v) => v.key === k && v.ready)) return;
    saveVoice(k); setVoiceKey(k);
    log({ type: 'voice', key: k });
    if (!S.ws || phaseRef.current === 'off') return;
    const old = S.ws; S.ws = null;
    try { if (old.readyState === 1) old.send(JSON.stringify({ type: 'bye' })); old.close(); } catch (e) { /* closed */ }
    cutAudio();
    if (S.pending) { clearTimeout(S.pending.timer); S.pending = null; }
    S.switchLine = true;
    setPh('connecting');
    openWs();
  }, [S]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = useCallback(async () => {
    if (phaseRef.current !== 'off' || !available()) return false;
    setPh('connecting'); S.cap = newPacer(); S.capFlow = false; setCaptions({ you: '', megh: '', flow: false }); setLatencyMs(null);
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      S.ctx = new AC();
      if (S.ctx.state === 'suspended') await S.ctx.resume().catch(() => {});
      S.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      S.outGain = S.ctx.createGain();
      S.an = S.ctx.createAnalyser(); S.an.fftSize = 512;
      S.outGain.connect(S.an); S.an.connect(S.ctx.destination);
      S.src = S.ctx.createMediaStreamSource(S.stream);
      S.micAn = S.ctx.createAnalyser(); S.micAn.fftSize = 512; S.micAn.smoothingTimeConstant = 0.6;
      S.src.connect(S.micAn);                                      // the orb listens to the microphone through this
      S.stream.getAudioTracks().forEach((tr) => { tr.enabled = !S.muted; });
      const sink = S.ctx.createGain(); sink.gain.value = 0; sink.connect(S.ctx.destination);
      try {
        await S.ctx.audioWorklet.addModule(workletUrl);
        S.node = new AudioWorkletNode(S.ctx, 'megh-pcm-capture');
        S.node.port.onmessage = (ev) => onFrame(ev.data.pcm, ev.data.rms);
        log({ type: 'capture', worklet: true });
      } catch (err) {
        // no AudioWorklet (old browser): the same frames from a ScriptProcessor
        const proc = S.ctx.createScriptProcessor(4096, 1, 1);
        const ratio = S.ctx.sampleRate / 16000;
        proc.onaudioprocess = (ev) => {
          const buf = ev.inputBuffer.getChannelData(0);
          const n = Math.floor(buf.length / ratio); const out = new Int16Array(n); let sq = 0;
          for (let i = 0; i < n; i++) {
            const s0 = Math.floor(i * ratio); const s1 = Math.min(buf.length, Math.floor((i + 1) * ratio)); let sum = 0;
            for (let k = s0; k < s1; k++) sum += buf[k];
            const v = Math.max(-1, Math.min(1, sum / Math.max(1, s1 - s0))); sq += v * v; out[i] = v < 0 ? v * 32768 : v * 32767;
          }
          onFrame(out.buffer, Math.sqrt(sq / Math.max(1, n)));
        };
        S.node = proc;
        log({ type: 'capture', worklet: false, why: String((err && err.message) || err) });
      }
      S.src.connect(S.node); S.node.connect(sink);
    } catch (err) {
      end('mic', true); setView(false);
      cb.current.onNotice(err && err.name === 'NotAllowedError'
        ? 'Microphone access is blocked. Allow it in the browser site settings, then try again.'
        : 'Could not start the microphone for live voice. The dictation mic may still work.');
      return false;
    }
    openWs();
    S.seenId = lastId(S.msgs);
    meters();
    return true;
  }, [S, available]); // eslint-disable-line react-hooks/exhaustive-deps

  const end = useCallback((why = 'end', quiet = false) => {
    const ws = S.ws; S.ws = null;
    if (ws) { try { if (ws.readyState === 1) ws.send(JSON.stringify({ type: 'bye' })); ws.close(); } catch (e) { /* closed */ } }
    clearTimeout(S.idleT); clearTimeout(S.silentT); clearTimeout(S.firstT); cancelAnimationFrame(S.raf);
    S.firstAsk = '';
    if (S.pending) { clearTimeout(S.pending.timer); S.pending = null; }
    clearTimeout(S.qT); S.queued = null; S.skipStop = false;
    cutAudio();
    try { if (S.node) S.node.disconnect(); } catch (e) { /* gone */ }
    try { if (S.src) S.src.disconnect(); } catch (e) { /* gone */ }
    if (S.stream) S.stream.getTracks().forEach((t) => t.stop());
    if (S.ctx) S.ctx.close().catch(() => {});
    S.node = S.src = S.stream = S.ctx = S.an = S.outGain = S.micAn = null; S.ob = null;
    S.inTx = ''; S.cap = newPacer(); clearInterval(S.capTimer); S.capTimer = 0; S.readQueue = [];
    setThinking(false);
    setPh('off');
    log({ type: 'end', why, quiet });
  }, [S, cutAudio]);

  useEffect(() => () => { end('unmount', true); clearTimeout(S.restT); }, [end, S]);
  // the Secretary desk's board is fetched ahead, so the voice view opens complete (one entrance, no stages)
  useEffect(() => {
    const t = setTimeout(() => { if (getToken()) fetchVoiceBoard(); }, 1200);
    return () => clearTimeout(t);
  }, []);

  // ── mute (Mitra's 27 Oct rule): only the microphone track is switched off. The session stays open, the answer
  // keeps playing, typed text still goes to the voice; unmute switches the track back on. Stop / End are the only cuts.
  const setMuted = useCallback((on) => {
    S.muted = !!on;
    S.lastVoice = performance.now();
    setMutedState(S.muted);
    if (S.stream) S.stream.getAudioTracks().forEach((tr) => { tr.enabled = !S.muted; });
    log({ type: 'mute', on: S.muted });
  }, [S]);
  // the stage: open it (and the session); close it (and the session). Idle leaves it up, in standby.
  // open(question): the voice opens and, after its hello, is asked that question (a tap on the voice panel, D-113)
  const open = useCallback((question) => {
    S.openedAt = lastId(S.msgs);
    S.greet = true;
    S.firstAsk = typeof question === 'string' ? question.trim() : '';
    setView(true);
    return start();
  }, [S, start]);
  const closeView = useCallback(() => { end('close', true); setView(false); }, [end]);
  // tap on the orb while it speaks: silence this answer (the session stays)
  const hush = useCallback(() => { cutAudio(); S.cut = true; log({ type: 'hush' }); }, [S, cutAudio]);
  const analysers = useCallback(() => ({ mic: S.micAn, out: S.an }), [S]);
  // the voice stage registers how it draws a chart switch: { view(v) -> { speak } (drawn on the stage, or nothing to
  // draw) | { chat: true } (the chat redraws it) }; null when the stage goes
  const registerStage = useCallback((h) => { S.stage = h || null; }, [S]);
  const voiceState = phase === 'connecting' ? 'connecting' : phase === 'off' ? 'standby'
    : (speaking ? 'speaking' : thinking ? 'thinking' : muted ? 'muted' : 'listening');

  // headless tests only (?voicetest=1): speak by text, read the event log
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('voicetest') !== '1') return undefined;
    window.__meghVoice = {
      say: (t) => { sendText(t, '[voice] '); },
      type: (t) => { sendText(t); },
      log: () => testLog.current.slice(),
      phase: () => phaseRef.current,
      playing: () => S.playing,
      muted: () => S.muted,
      trackEnabled: () => !!(S.stream && S.stream.getAudioTracks().every((tr) => tr.enabled)),
      queued: () => (S.queued ? { id: S.queued.id, question: S.queued.q } : null),
      // a relay event fed to the page as if it came from the relay (a test tool_call: its result goes to an id the relay
      // does not know, so it is never spoken)
      inject: (e) => onEvent(e),
      pending: () => (S.pending ? { id: S.pending.id, question: S.pending.question } : null),
    };
    return () => { delete window.__meghVoice; };
  }, [S]); // eslint-disable-line react-hooks/exhaustive-deps -- reads S (stable); armSilent only touches S

  return { phase, captions, speaking, latencyMs, meterYou, meterMegh, start, end, available, onMessages,
    muted, setMuted, view, open, closeView, hush, analysers, thinking, voiceState, turnsDone, openedAt: () => S.openedAt,
    resting,
    registerStage, voiceKey, setVoice };
}
