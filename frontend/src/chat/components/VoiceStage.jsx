import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createOrb } from '../voiceOrb.js';
import { AI_VOICE_LABEL, greetingHeading, spokenForm } from '../voiceSpeech.js';
import { deleteConversationApi, fetchNLPResponse, fetchVoiceBoard, peekVoiceBoard } from '../api.js';
import { explainCard, plan } from '../voice/vizPlan.js';
import { CHAT_VIEWS, NAV_SPEECH, NO_PICTURE, explainAsk, isRedraw, throwawaySessionId, viewChip, viewSpeech } from '../voice/voiceViews.js';
import { StageCard, useCardReveal, KIND_LABEL } from '../voice/StageCards.jsx';
import { SecretaryDesk } from '../voice/SecretaryDesk.jsx';
import { VOICES, voiceOf } from '../voice/voices.js';
import { SCHEME_HUES } from '../chartTheme.js';
import VOICE_PACK from '../voice/meghVoicePack.js';
import '../../styles/voice-stage.css';
import '../../styles/voice-desk.css';

/* The Secretary view of the live voice (2026-11-03): an exact replica of Sakala Mitra's Chief Secretary WEB view
   (D:/Sakala POC/mitra/web/index.html, mitra.css, stage.js, mitra.js; read-only source), in Megh's purple.

   The page: Mitra's background (gradients, three auroras, the 64 px grid, the state glow), the 68 px header (halo
   mark, title, date pill, status), the three-column desk (left and right: the Secretary's command board, owned by
   voice/SecretaryDesk.jsx; centre: the orb with its mode pill, duplex meters and state chip, the captions, the trace
   chips, the composer and the hints), the 62 px footer (profile pill, the live feed of this conversation, End).

   The stage (Mitra's Stage.show): an answer with a picture sinks the side columns, tilts the grid, lights the
   particles, sweeps the beam, glides the orb to the top right with its pill under it, puts the title top left and
   the captions top centre, arcs the cards in (one, two, three across; a board of six; a map beside its cards), shows
   the insight once every item is in, the "Show as" column, and the dock (the desk's cards, earlier answers,
   ⌃ Dashboard). An answer with no picture keeps the desk and lands as an ANSWER card at the top of the right column
   (Mitra's UI.answer). Every figure on a card is drawn by voice/stageCanvas.js from the planner's cards
   (voice/vizPlan.js), revealed as the voice names it (useCardReveal).

   2026-11-11: a chart switch said by voice ("show it on the map", "... as a ranking", "... as horizontal bars") is drawn
   here at once (the answer re-planned with that view, registerStage); bar / line / pie / table come back as the chat's
   own redraw and land the same way: no wait for the voice, the cards turn in place over a ghost of the old ones, a chip
   under the title says which view the data allowed. A single figure gets the breakdown that explains it beside it
   (asked in a throwaway session; drawn only when its parts add up to the figure). */

const STATE_LABEL = {
  connecting: 'Connecting…', listening: 'Listening', thinking: 'Working it out', speaking: 'Speaking',
  muted: 'Muted · the answer still plays', standby: 'Standby',
};
const STATE_HINT = {
  connecting: 'Opening the live voice', listening: 'Say “give me the headline figure of every scheme”',
  thinking: 'Reading the data', speaking: 'Talk over me any time', muted: 'Tap the mic to unmute', standby: 'Tap the orb to talk',
};
const PARK_LABEL = { connecting: 'Connecting…', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking', muted: 'Muted', standby: 'Tap to talk' };
const MODE_LABEL = { standby: 'Standby · tap the orb', connecting: 'Connecting…', live: 'Live · full duplex' };
const TRACE = ['Listen', 'Hear', 'Understand', 'Ask Megh One AI', 'Speak'];
const KIND_ORDER = ['bars', 'line', 'donut', 'map', 'race'];
// cross-scheme first (the user, 2026-11-02): what a Secretary asks across the schemes (Mitra's hints)
const STARTERS = [
  'Give me the headline figure of every scheme',
  'Which scheme leads in each district?',
  'How much money has each scheme disbursed?',
  'MGNREGA person-days by district',
  'Compare PMAY-G houses sanctioned in West Garo Hills and East Khasi Hills',
  "In Ri Bhoi, give me each scheme's figures",
];
const lastIdOf = (msgs) => (msgs.length ? msgs[msgs.length - 1].id : 0);
const currentIdForPlan = (m) => (m ? m.id : null);
const today = () => new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const plainText = (s) => String(s || '').split('**').join('').split('__').join('');
const words = (s) => String(s || '').split(' ').filter((w) => w.length > 0);
// the greeting's second sentence ("What would you like to look at today?"): the heading above says the first
const afterGreeting = (s) => { let t = String(s || '').trim(); while (t && '.,!'.includes(t[0])) t = t.slice(1); return t.trim(); };
const trimEnd = (s) => { let t = String(s || '').trim(); while (t && '?.!'.includes(t[t.length - 1])) t = t.slice(0, -1); return t; };
// the stage title (Mitra's op.title: a short topic): the question when it is short, else the first card's title
const titleOf = (p, q) => { const t = trimEnd(q); return t && t.length <= 64 ? t : (p && p.cards[0] ? p.cards[0].title : t); };

// ' west garo hills 2023 24 ' — lower case letters and digits, single spaces, padded (no regex, D-046)
function norm(s) {
  let out = ' ';
  for (const ch of String(s || '').toLowerCase()) {
    const ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9');
    if (ok) out += ch; else if (!out.endsWith(' ')) out += ' ';
  }
  return out.endsWith(' ') ? out : out + ' ';
}
const ROUND = ['pie', 'doughnut', 'polarArea'];
const TEST = () => typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('voicetest') === '1';
const EXPLAIN_MS = 15000;           // the explaining breakdown: dropped when it takes longer than this
const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
// a throwaway question leaves no conversation behind in the officer's history (removed once the server has saved it)
function forget(sid) {
  setTimeout(() => {
    deleteConversationApi(sid).catch(() => setTimeout(() => deleteConversationApi(sid).catch(() => {}), 20000));
  }, 4000);
}

/* Reveal the charts of the answer card (no picture planned: the chat's own card) as their names are spoken. The chat's
   chart component builds a new Chart.js instance whenever the answer re-renders, so the state is kept per LABEL and
   re-applied to whatever instance the canvas holds now, every 100 ms until done. */
function useSpeechReveal(cardRef, msgId, active, spoken, turnOver) {
  const R = useRef({ on: false, said: new Set(), all: false, timers: [], tick: 0, seen: new Map(), lastHit: 0, heard: ' ', firstSeen: 0 });
  const apply = (cv) => {
    const r = R.current; const chart = cv.__chart;
    if (!chart || !chart.data || (chart.data.labels || []).length < 2) return;
    const labels = (chart.data.labels || []).map((l) => norm(Array.isArray(l) ? l.join(' ') : l));
    let s = r.seen.get(cv);
    if (!s || s.chart !== chart) {                       // a new instance: its arrays are the answer's own; keep them
      s = { chart, orig: chart.data.datasets.map((d) => d.data), type: chart.config.type, labels, sig: '' };
      r.seen.set(cv, s);
      if (!r.firstSeen) r.firstSeen = performance.now();
      labels.forEach((l) => { if (l.trim().length >= 3 && r.heard.includes(l)) r.said.add(l); });   // named before it mounted
    }
    const shown = labels.map((l) => r.all || r.said.has(l));
    const sig = shown.map((x) => (x ? 1 : 0)).join('');
    if (sig === s.sig) return;
    if (window.__meghVoice) (window.__revealLog = window.__revealLog || []).push({ t: Math.round(performance.now()), shown: shown.filter(Boolean).length, n: labels.length });
    const first = s.sig === '';
    s.sig = sig;
    try {
      if (ROUND.includes(s.type)) labels.forEach((_, i) => { if (chart.getDataVisibility(i) !== shown[i]) chart.toggleDataVisibility(i); });
      else {
        const hidden = s.type === 'line' ? null : 0;
        chart.data.datasets.forEach((d, k) => { d.data = shown.every(Boolean) ? s.orig[k] : s.orig[k].map((v, j) => (shown[j] ? v : hidden)); });
      }
      chart.update(first ? 'none' : undefined);
    } catch (e) { /* the chart went away */ }
  };
  const scan = () => {
    const card = cardRef.current; if (!card) return;
    card.querySelectorAll('canvas').forEach(apply);
  };
  const allLabels = () => {
    const out = [];
    R.current.seen.forEach((s) => s.labels.forEach((l) => { if (!out.includes(l)) out.push(l); }));
    return out;
  };
  const flush = useCallback((gap = 90) => {
    const r = R.current;
    if (!r.on || r.all || r.flushing) return;
    r.flushing = true;
    const rest = allLabels().filter((l) => !r.said.has(l));
    rest.forEach((l, i) => r.timers.push(setTimeout(() => { r.said.add(l); scan(); }, gap * i)));
    r.timers.push(setTimeout(() => { r.all = true; scan(); }, gap * rest.length + 120));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const r = R.current;
    r.timers.forEach(clearTimeout); clearInterval(r.tick);
    r.timers = []; r.said = new Set(); r.seen = new Map(); r.all = !active; r.flushing = false; r.on = !!active; r.lastHit = 0;
    r.firstSeen = 0; r.heard = ' ';
    if (!active) return undefined;
    scan();
    r.tick = setInterval(() => {
      scan();
      if (r.firstSeen && !r.lastHit && !r.flushing && performance.now() - r.firstSeen > 3500) flush(140);
      if (r.all && r.seen.size) { clearInterval(r.tick); }
    }, 100);
    r.timers.push(setTimeout(() => { R.current.all = true; scan(); }, 30000));       // safety net
    return () => { clearInterval(r.tick); };
  }, [msgId, active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const r = R.current;
    if (!r.on || r.all || !spoken) return;
    const heard = norm(spoken);
    r.heard = heard;
    let hit = false;
    allLabels().forEach((l) => { if (!r.said.has(l) && l.trim().length >= 3 && heard.includes(l)) { r.said.add(l); hit = true; } });
    if (hit) { r.lastHit = performance.now(); scan(); }
  }, [spoken]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (turnOver && R.current.on) flush(110); }, [turnOver, flush]);
  useEffect(() => () => { R.current.timers.forEach(clearTimeout); clearInterval(R.current.tick); }, []);
}

function VoiceOrb({ live, parked, rootRef }) {
  const cvRef = useRef(null);
  const orbRef = useRef(null);
  const state = live.voiceState;
  useEffect(() => {
    const orb = createOrb(cvRef.current, {
      onLevel: (v) => { if (rootRef.current) rootRef.current.style.setProperty('--lvl', v.toFixed(3)); },
    });
    orbRef.current = orb;
    return () => orb.destroy();
  }, [rootRef]);
  const analysers = live.analysers;
  useEffect(() => {
    const orb = orbRef.current; if (!orb) return;
    orb.setState(state);
    const a = analysers();
    orb.setSource(state === 'speaking' ? a.out : (state === 'listening' ? a.mic : null));
    if (state === 'listening' || state === 'speaking') orb.pulse();
  }, [state, analysers]);
  useEffect(() => { if (orbRef.current) orbRef.current.setHalf(parked); }, [parked]);
  // a tap: standby -> talk; speaking -> silence this answer; muted -> unmute
  useEffect(() => {
    if (!orbRef.current) return;
    orbRef.current.onTap = () => {
      if (live.phase === 'off') live.start();
      else if (live.speaking) live.hush();
      else if (live.muted) live.setMuted(false);
    };
  }, [live]);
  return <canvas ref={cvRef} className="vs-orb-cv" aria-label="Megh One AI voice" />;
}

/* A scroll box that holds more than it shows says so with a soft fade at that edge (2026-11-14: the desk's columns were
   cut hard at the footer, "Busiest districts" half shown). data-fade = "start" / "end" / "start end"; the CSS masks. */
function useEdgeFade(ref, axis = 'y', deps = []) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let raf = 0;
    const check = () => {
      raf = 0;
      const pos = axis === 'x' ? el.scrollLeft : el.scrollTop;
      const room = axis === 'x' ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight;
      const f = [room > 2 && pos > 2 ? 'start' : '', room > 2 && pos < room - 2 ? 'end' : ''].filter(Boolean).join(' ');
      if ((el.dataset.fade || '') !== f) { if (f) el.dataset.fade = f; else delete el.dataset.fade; }
    };
    const soon = () => { if (!raf) raf = requestAnimationFrame(check); };
    check();
    el.addEventListener('scroll', soon, { passive: true });
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(soon) : null;
    if (ro) { ro.observe(el); [...el.children].forEach((c) => ro.observe(c)); }
    window.addEventListener('resize', soon);
    return () => { cancelAnimationFrame(raf); el.removeEventListener('scroll', soon); if (ro) ro.disconnect(); window.removeEventListener('resize', soon); };
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
}

/* Mitra's stage-fx: 70 drifting glow sprites over the stage (pre-rendered radial gradients), parallax with the
   pointer, light blending (source-over, alpha x .55). It draws only while the stage is up. */
const FX_COLS = ['#9558CF', '#B27FE0', '#d55181'];
function StageFx({ on }) {
  const cvRef = useRef(null);
  useEffect(() => {
    const cv = cvRef.current;
    if (!on || !cv) return undefined;
    const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion) return undefined;
    const ctx = cv.getContext('2d');
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const sprites = FX_COLS.map((c) => {
      const s = document.createElement('canvas'); s.width = s.height = 64;
      const g = s.getContext('2d'); const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
      gr.addColorStop(0, c + 'e6'); gr.addColorStop(0.35, c + '40'); gr.addColorStop(1, c + '00');
      g.fillStyle = gr; g.fillRect(0, 0, 64, 64); return s;
    });
    let W = 0; let H = 0;
    const size = () => { const r = cv.getBoundingClientRect(); W = r.width; H = r.height; cv.width = Math.max(10, W * dpr); cv.height = Math.max(10, H * dpr); };
    size();
    const P = Array.from({ length: 70 }, () => ({ x: Math.random(), y: Math.random(), z: 0.3 + Math.random() * 0.7,
      vy: -(0.08 + Math.random() * 0.25), vx: (Math.random() - 0.5) * 0.12, ph: Math.random() * 6.28, s: Math.floor(Math.random() * 3) }));
    const cam = { x: 0, y: 0, tx: 0, ty: 0 };
    const onMove = (e) => { cam.tx = (e.clientX / window.innerWidth) * 2 - 1; cam.ty = (e.clientY / window.innerHeight) * 2 - 1; };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('resize', size);
    let raf = 0; let last = performance.now();
    const frame = (now) => {
      const dt = Math.min(64, now - last); last = now;
      cam.x += (cam.tx - cam.x) * 0.04; cam.y += (cam.ty - cam.y) * 0.04;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = 'source-over';
      for (const p of P) {
        p.y += (p.vy * dt) / 1000 * 0.1 * p.z; p.x += ((p.vx + Math.sin(now / 1800 + p.ph) * 0.08) * dt) / 1000 * 0.1;
        if (p.y < -0.05) { p.y = 1.05; p.x = Math.random(); }
        if (p.x < -0.05) p.x = 1.05; else if (p.x > 1.05) p.x = -0.05;
        const a = (0.35 + 0.35 * Math.sin(now / 900 + p.ph)) * p.z * 0.55;
        const sz = 8 + 22 * p.z;
        ctx.globalAlpha = Math.max(0, a);
        ctx.drawImage(sprites[p.s], p.x * W + cam.x * 30 * p.z - sz / 2, p.y * H + cam.y * 20 * p.z - sz / 2, sz, sz);
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('pointermove', onMove); window.removeEventListener('resize', size); ctx.clearRect(0, 0, cv.width, cv.height); };
  }, [on]);
  return <canvas ref={cvRef} className="vs-fx" aria-hidden="true" />;
}

/* Mitra's live waveform (#wave, 640 x 36) under the captions while the microphone listens: the last ~3 s of the mic's
   level as 72 bars, older ones fainter, lavender in place of Mitra's cyan. It draws only while it is shown. */
function MicWave({ analysers, on }) {
  const cvRef = useRef(null);
  useEffect(() => {
    const cv = cvRef.current;
    if (!on || !cv) return undefined;
    const ctx = cv.getContext('2d');
    const hist = new Float32Array(72);
    let hi = 0; let raf = 0; let buf = null; let lastPush = 0;
    const draw = (now) => {
      if (now - lastPush >= 42) {
        lastPush = now;
        let v = 0;
        try {
          const a = analysers ? analysers() : null; const m = a && a.mic;
          if (m) {
            if (!buf || buf.length !== m.fftSize) buf = new Float32Array(m.fftSize);
            m.getFloatTimeDomainData(buf);
            let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
            v = Math.sqrt(s / buf.length);
          }
        } catch (e) { v = 0; }
        hist[hi] = v; hi = (hi + 1) % hist.length;
      }
      const W = cv.width; const H = cv.height; const n = hist.length; const bw = W / n;
      ctx.clearRect(0, 0, W, H);
      for (let i = 0; i < n; i++) {
        const val = hist[(hi + i) % n]; const h = Math.max(2, Math.min(H, val * H * 4.5));
        ctx.fillStyle = `rgba(178, 127, 224, ${(0.25 + (i / n) * 0.75).toFixed(3)})`;
        ctx.fillRect(i * bw + 1, (H - h) / 2, bw - 2, h);
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); ctx.clearRect(0, 0, cv.width, cv.height); };
  }, [on, analysers]);
  return <canvas ref={cvRef} className={'vs-wave' + (on ? ' on' : '')} width={640} height={36} aria-hidden="true" />;
}

// a word that closes a sentence ("houses." / "district?" / "Hills.”"), so the sentence being said can be told apart
const CLOSERS = '"\')”’';
const endsSentence = (w) => { let t = String(w || ''); while (t && CLOSERS.includes(t[t.length - 1])) t = t.slice(0, -1); return !!t && '.?!'.includes(t[t.length - 1]); };
const CUR_MAX = 28;          // a very long sentence: only its last words stay bright

/* The voice toggle (2026-11-12): the voice the officer hears. Same pipeline, ears and pictures for every voice; a
   change re-opens the live session in the new voice, which says one line. Closes on a choice, an outside click or Esc. */
// Every scheme of the voice pack in its own colour (2026-11-12, the user: the footer's conversation feed and the dock chips were
// clutter): one tap asks the scheme's charted headline question (voice_overlay `dashboard`, via the generated pack).
const STRIP = (VOICE_PACK.schemes || []).map((name) => ({ name, q: (VOICE_PACK.dashboards || {})[name] || '',
  hue: (SCHEME_HUES[name] || {}).main || '#7c3fbf', deep: (SCHEME_HUES[name] || {}).deep || '#4b1f86' }));
const schemeIn = (text) => {
  const t = String(text || '').toLowerCase();
  return [...STRIP].sort((a, b) => b.name.length - a.name.length).find((s) => t.includes(s.name.toLowerCase()))?.name || '';
};

function SchemeStrip({ onAsk, active }) {
  const ref = useRef(null);
  useEdgeFade(ref, 'x', []);
  // the scheme on the stage is always in view (a narrow screen scrolls the strip)
  useEffect(() => {
    const el = ref.current; if (!el || !active) return;
    const b = el.querySelector('.vs-scheme.on');
    if (b && (b.offsetLeft < el.scrollLeft || b.offsetLeft + b.offsetWidth > el.scrollLeft + el.clientWidth)) {
      el.scrollTo({ left: Math.max(0, b.offsetLeft - 24), behavior: reducedMotion() ? 'auto' : 'smooth' });
    }
  }, [active]);
  return (
    <nav className={'vs-schemes' + (active ? ' has-on' : '')} aria-label="Scheme dashboards" ref={ref}>
      {STRIP.map((s) => (
        <button key={s.name} type="button" className={'vs-scheme' + (active === s.name ? ' on' : '')} disabled={!s.q}
                aria-current={active === s.name ? 'true' : undefined}
                style={{ '--h': s.hue, '--hd': s.deep }} title={s.q} onClick={() => s.q && onAsk(s.q)}>
          <i aria-hidden="true" /><b>{s.name}</b>
        </button>
      ))}
    </nav>
  );
}

function VoicePicker({ live }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); } };
    document.addEventListener('pointerdown', away, true);
    window.addEventListener('keydown', key, true);
    return () => { document.removeEventListener('pointerdown', away, true); window.removeEventListener('keydown', key, true); };
  }, [open]);
  if (!live || !live.setVoice) return null;
  const cur = voiceOf(live.voiceKey);
  return (
    <div className={'vs-voice' + (open ? ' open' : '')} ref={ref}>
      <button type="button" className="vs-voice-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}
              title="Choose the voice">
        <span className="vs-voice-wave" aria-hidden="true"><i /><i /><i /><i /></span>
        <b>{cur.name}</b><span className="vs-voice-tone">{cur.tone}</span>
        <span className="vs-voice-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="vs-voice-menu" role="menu">
          <div className="vs-voice-h">Voice</div>
          {VOICES.map((v) => (
            <button key={v.key} type="button" role="menuitemradio" aria-checked={v.key === cur.key} disabled={!v.ready}
                    className={'vs-voice-item' + (v.key === cur.key ? ' on' : '')}
                    onClick={() => { setOpen(false); if (v.key !== cur.key) live.setVoice(v.key); }}>
              <span className="vs-voice-dot" aria-hidden="true" />
              <b>{v.name}</b><span>{v.tone}</span>
            </button>
          ))}
          <div className="vs-voice-note">Same answers and pictures in every voice.</div>
        </div>
      )}
    </div>
  );
}

/* The captions: what the voice is saying, word by word in time with the audio (the hook holds each piece of the
   transcript until its audio plays). While it streams, the sentence being said is bright, the words already said
   settle to a quieter ink, and the newest word carries a soft glow that hands over to the next one. Static text
   (an answer seen another way) is plain ink. Each word fades up as it arrives; the box keeps the newest in view. */
function Words({ text, streaming = false }) {
  const ws = words(text);
  let start = 0;
  if (streaming) {
    for (let i = ws.length - 2; i >= 0; i--) if (endsSentence(ws[i])) { start = i + 1; break; }
    start = Math.max(start, ws.length - CUR_MAX);
  }
  const last = ws.length - 1;
  return ws.map((w, i) => (
    <span key={i} className={'w' + (streaming ? (i >= start ? ' cur' : ' past') + (i === last ? ' tip' : '') : '')}>{w}</span>
  ));
}

export function VoiceStage({ live, messages, renderMessage, onType, onClose }) {
  const rootRef = useRef(null);
  const orbWrapRef = useRef(null);
  const capRef = useRef(null);
  const cardRef = useRef(null);
  const [draft, setDraft] = useState('');
  const [pinned, setPinned] = useState(null);
  const [home, setHome] = useState(0);              // "back to the desk": answers up to this id stay off the stage
  const [ghost, setGhost] = useState(null);
  const [kinds, setKinds] = useState({});           // "Show as": card id -> kind (Mitra's Stage.morph)
  const [insightOn, setInsightOn] = useState(false);
  const [deskChips, setDeskChips] = useState([]);
  const [colsDone, setColsDone] = useState(false);
  const [navHome, setNavHome] = useState(false);
  const [, setExitTick] = useState(0);
  const [board, setBoard] = useState(() => peekVoiceBoard());   // fetched ahead: the desk opens complete
  const [voiceViews, setVoiceViews] = useState({});   // answer id -> a view switched to by voice, drawn on the stage only
  const [explain, setExplain] = useState(null);       // { key, card }: the breakdown that explains a single figure
  const [viewNote, setViewNote] = useState(null);     // the chip under the title after a switch: { title, sub, n }

  // this voice conversation: the messages since the stage opened
  const since = live.openedAt();
  const turn = useMemo(() => {
    const mine = messages.filter((m) => m.id > since);
    let u = -1;
    for (let i = mine.length - 1; i >= 0; i--) if (mine[i].kind === 'user') { u = i; break; }
    const answer = [...mine.slice(u + 1)].reverse().find((m) => m.kind !== 'user') || null;
    const answers = mine.filter((m) => m.kind === 'rich');
    const earlier = answers.filter((m) => !answer || m.id !== answer.id);
    const asked = mine.filter((m) => m.kind === 'user').map((m) => ({ id: m.id, text: m.text }));
    return { question: u >= 0 ? mine[u].text : '', userId: u >= 0 ? mine[u].id : 0, answer, earlier, answers, asked };
  }, [messages, since]);
  const answerId = turn.answer ? turn.answer.id : null;
  useEffect(() => { setPinned(null); }, [answerId]);
  const pinnedMsg = pinned ? messages.find((m) => m.id === pinned) : null;
  const latest = turn.answer && turn.answer.id > home ? turn.answer : null;
  const current = pinnedMsg || latest;
  const cardKeyId = pinnedMsg ? 'p' + pinnedMsg.id : 'u' + turn.userId;
  const working = !!current && current.kind === 'typing';

  // the picture of the answer: planned once per answer (Mitra's one picture per turn)
  const response = current && current.kind === 'rich' ? current.response : null;
  const question = current ? (current.question || turn.question) : '';
  // the view: one switched to by voice on the stage, else the chat's redraw view (bar / line / pie / table); it wins
  // over the words of the question the answer came from (vizPlan.plan)
  const vView = current ? voiceViews[current.id] || null : null;
  const curView = current ? vView || current.view || null : null;
  const vplan = useMemo(() => (response ? plan(response, question, curView) : null), [response, currentIdForPlan(current), curView]); // eslint-disable-line react-hooks/exhaustive-deps
  const planKey = vplan && current ? (vView ? `${current.id}:${vView}` : current.id) : null;
  // a chart switch: drawn at once, everything in, the cards turn in place (no arc-in, no wait for the voice)
  const instant = !!current && (isRedraw(current) || !!vView);

  // speech-synced reveal: "fresh" = an answer that arrived while the voice is on; "done" = the relay's end of turn
  const fresh = !!current && current.kind === 'rich' && live.phase === 'live' && !pinned;
  const currentId = current ? current.id : null;
  // What the voice says FOR THIS ANSWER (2026-11-10): the running transcript carries on from the previous turn (a typed
  // question has no "you said" to reset it), so what it held when this answer took the stage is set aside; the rest
  // is the voice reading this answer, in its own natural words. It is kept per answer, so the answer still shows what
  // was said once the voice has finished (or gone to standby), and an earlier answer brought back shows its own words.
  const rawMegh = live.captions.megh || '';
  const segRef = useRef({ id: undefined, base: '' });
  if (segRef.current.id !== currentId) segRef.current = { id: currentId, base: currentId == null ? '' : rawMegh };
  else if (segRef.current.base && !rawMegh.startsWith(segRef.current.base)) segRef.current.base = '';   // the transcript was reset
  const spokenLive = segRef.current.base ? rawMegh.slice(segRef.current.base.length).trim() : rawMegh;
  const spokenMap = useRef(new Map());
  if (fresh && currentId != null && spokenLive) spokenMap.current.set(currentId, spokenLive);
  const ownSpoken = currentId != null ? spokenMap.current.get(currentId) || '' : '';
  const baseRef = useRef({ id: null, n: 0 });
  if (baseRef.current.id !== currentId) baseRef.current = { id: currentId, n: live.turnsDone };
  const turnOver = live.turnsDone > baseRef.current.n && !live.speaking;
  // one picture per turn, landing with the voice (Mitra's vizHold): the cards come in when the voice starts reading the
  // answer, or 2.5 s after it arrived if the voice is slow; an answer seen another way shows at once
  const [heldKey, setHeldKey] = useState(null);
  useEffect(() => {
    if (!planKey) return undefined;
    if (!fresh || live.speaking || instant) { setHeldKey(planKey); return undefined; }
    const t = setTimeout(() => setHeldKey(planKey), 2500);
    return () => clearTimeout(t);
  }, [planKey, fresh, live.speaking, instant]);
  const cardsUp = !!vplan && heldKey === planKey;

  // what the stage shows: the last picture that came up stays while the next question is worked out (Mitra keeps the
  // stage up and crossfades the next picture over it), and for its exit (vcardOut, 750 ms) when the desk comes back
  const lastUp = useRef(null);
  if (cardsUp && (!lastUp.current || lastUp.current.key !== planKey)) lastUp.current = { key: planKey, plan: vplan, q: question, instant };
  // the explaining breakdown joins the picture it explains (the same key: no crossfade, the tile glides aside)
  if (explain && lastUp.current && lastUp.current.key === explain.key && !lastUp.current.plan.cards.includes(explain.card)) {
    lastUp.current = { ...lastUp.current, plan: { ...lastUp.current.plan, cards: [...lastUp.current.plan.cards, explain.card], explained: true } };
  }
  const stageOn = !!current && (!!vplan || (working && !!lastUp.current));
  const shown = lastUp.current;
  const exiting = !stageOn && !!shown;
  useEffect(() => {
    if (stageOn || !lastUp.current) return undefined;
    const t = setTimeout(() => { lastUp.current = null; setExitTick((n) => n + 1); }, 750);
    return () => clearTimeout(t);
  }, [stageOn]);
  const shownKey = shown ? shown.key : null;

  // a new picture crossfades over the old one (Mitra's Stage.ghost: the old cards fade as a frozen layer)
  const prevShown = useRef(null);
  // 2026-11-14: a picture that REPLACES one on the stage settles in place over the fading ghost (one continuous surface)
  // instead of arcing in from below; decided once per picture, in render, so a card's entrance never changes mid-way
  const swapRef = useRef({ key: null, on: false });
  if (swapRef.current.key !== shownKey) {
    swapRef.current = { key: shownKey, on: !!shown && !!prevShown.current && prevShown.current.key !== shownKey };
  }
  useEffect(() => {
    const prev = prevShown.current;
    prevShown.current = shown;
    setKinds({});
    if (prev && shown && prev.key !== shown.key) {
      setGhost({ ...prev, kinds: {} });
      const t = setTimeout(() => setGhost(null), 750);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [shownKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // the orb glides from the centre to the top right (Mitra: 132 px, centre at innerWidth - 28 - 66, 84 + 66;
  // a phone: a 40 px badge in the title row), measured on the untransformed layout
  const place = useCallback(() => {
    const w = orbWrapRef.current; const root = rootRef.current;
    if (!w || !root) return;
    if (!stageOn) { w.style.transform = ''; return; }
    let x = 0; let y = 0; let el = w;
    while (el && el !== root) { x += el.offsetLeft; y += el.offsetTop; el = el.offsetParent; }
    const main = root.querySelector('.vs-main'); if (main) y -= main.scrollTop;
    const phone = root.clientWidth <= 600;
    const size = phone ? 40 : 132;
    const cx = x + w.offsetWidth / 2; const cy = y + w.offsetHeight / 2;
    const tx = root.clientWidth - (phone ? 12 : 28) - size / 2;
    const ty = phone ? 56 + 4 + size / 2 : 84 + size / 2;
    w.style.transform = `translate(${(tx - cx).toFixed(1)}px, ${(ty - cy).toFixed(1)}px) scale(${(size / Math.max(1, w.offsetWidth)).toFixed(3)})`;
  }, [stageOn]);
  useEffect(() => { place(); }, [place]);
  useEffect(() => { window.addEventListener('resize', place); return () => window.removeEventListener('resize', place); }, [place]);

  // the desk's columns scroll inside themselves when they hold more than the screen; a soft fade says so
  const colLRef = useRef(null);
  const colRRef = useRef(null);
  const deskAnswerUp = !!current && !vplan && !working;
  useEdgeFade(colLRef, 'y', [board]);
  useEdgeFade(colRRef, 'y', [board, deskAnswerUp, turn.answers.length]);

  const toDesk = useCallback(() => { setPinned(null); setHome(lastIdOf(messages)); }, [messages]);
  // Esc: an answer on screen (on the stage, or the answer card) goes back to the desk; the desk goes back to the chat
  const answerUpRef = useRef(false);
  answerUpRef.current = !!current;
  // ONCE per opening: the body classes drive the entrance (the chat sinks, the desk rises); the key handler reads the
  // current values through a ref, so voice state changes never re-run it
  const keyRef = useRef({});
  keyRef.current = { live, onClose, toDesk };
  useEffect(() => {
    document.body.classList.add('vstage-on');
    const raf = requestAnimationFrame(() => document.body.classList.add('vstage-in'));
    const onKey = (e) => {
      const k = keyRef.current;
      const typing = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA');
      if (e.key === 'Escape') { e.preventDefault(); if (answerUpRef.current && !e.shiftKey) k.toDesk(); else k.onClose(); return; }
      if (!typing && (e.key === 'm' || e.key === 'M') && !e.repeat) k.live.setMuted(!k.live.muted);
    };
    window.addEventListener('keydown', onKey);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('keydown', onKey); document.body.classList.remove('vstage-on', 'vstage-in'); };
  }, []);

  // the desk's board: read-only figures beside the pipeline (app/voice/board.py)
  // (a board that cannot be read still lets the columns in, so an ANSWER card in the right column is never invisible)
  const [boardMissing, setBoardMissing] = useState(false);
  useEffect(() => {
    if (board) return undefined;
    let on = true;
    fetchVoiceBoard().then((b) => { if (!on) return; if (b) setBoard(b); else setBoardMissing(true); })
      .catch(() => { if (on) setBoardMissing(true); });
    return () => { on = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // stage in: the desk's cards become dock chips (Mitra's dockChips: each side card's h3 and its first figure);
  // stage out: the desk's cards play cardHome (body.nav-home, 1.8 s)
  const wasOn = useRef(false);
  // the chips are rebuilt on every picture (Mitra's dockChips() in each show), so a board that arrived after the first
  // question, or a new exchange, is in them
  useEffect(() => {
    const root = rootRef.current;
    if (stageOn) {
      const out = []; const seen = new Set();
      if (root) {
        root.querySelectorAll('.vs-col .sdk-card > h3, .vs-col .vs-anscard > h3').forEach((h3) => {
          const first = h3.firstChild && h3.firstChild.nodeType === 3 ? h3.firstChild.textContent : h3.textContent;
          const title = String(first || '').trim().slice(0, 26);
          if (!title || seen.has(title)) return;
          seen.add(title);
          const small = h3.querySelector('small');
          out.push({ title, num: small ? small.textContent.trim().slice(0, 14) : '' });
        });
      }
      setDeskChips(out.length ? out : [{ title: 'Command view', num: 'Meghalaya' }, { title: 'On the map', num: '' },
        { title: 'Conversation', num: `${turn.answers.length} exchange${turn.answers.length === 1 ? '' : 's'}` }]);
    }
  }, [stageOn, shownKey, board, turn.answers.length]);
  useEffect(() => {
    if (stageOn && !wasOn.current) setColsDone(true);
    let t = 0;
    if (!stageOn && wasOn.current) { setNavHome(true); t = setTimeout(() => setNavHome(false), 1800); }
    wasOn.current = stageOn;
    return () => clearTimeout(t);
  }, [stageOn]);
  // (the dock chips and their exitTo went on 2026-11-12: the scheme strip replaced them; Dashboard = toDesk)

  // headless tests only (?voicetest=1): the picture on stage and the rows it was drawn from
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('voicetest') !== '1') return;
    window.__stagePlan = vplan ? {
      id: planKey, question, route: response && response.route,
      view: curView, instant, applied: vplan.applied || null,
      cards: vplan.cards.map((c) => ({ kind: c.kind, title: c.title, unitLabel: c.unitLabel || '', mapMode: c.mapMode || null,
        items: (c.items || []).map((x) => ({ key: x.key, label: x.label, col: x.col || null, value: x.value ?? null,
          shown: (x.fmt || c.fmt)(x.value), sub: x.sub || '' })),
        x: c.x || null, series: (c.series || []).map((z) => ({ name: z.name, col: z.col || null, values: z.values })) })),
      data: (response && response.data) || [],
    } : { id: null, route: response && response.route, cards: [], data: (response && response.data) || [] };
  }, [vplan, planKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const script = useMemo(() => (response ? (spokenForm(response).speak || '') : ''), [response]);
  // the reveal listens to what the voice says for THIS answer only (a name from the previous answer never lights one)
  const heardNow = fresh ? spokenLive : '';
  const registry = useCardReveal(cardsUp ? vplan : null, cardsUp ? planKey : null, fresh && !instant, heardNow, turnOver, live.speaking, script);
  // an answer the planner draws no picture for is the chat's own card (text, chart, chips), revealed as before
  useSpeechReveal(cardRef, currentId, fresh && !vplan, heardNow, turnOver);
  const ghostRegistry = useMemo(() => ({ add: (_id, h) => h.revealAll(0), remove: () => {} }), []);

  // ── chart switches by voice (2026-11-11): useLiveVoice asks the stage how a canonical switch sentence is drawn ──
  const apiRef = useRef({});
  apiRef.current = { current, question, toDesk, answers: turn.answers };
  const registerStage = live.registerStage;
  useEffect(() => {
    if (!registerStage) return undefined;
    registerStage({
      // navigation by voice (2026-11-11; Mitra's go_to): the dashboard, or the last chart again
      nav: (k) => {
        const { current: m, toDesk: home, answers } = apiRef.current;
        if (k === 'desk') {
          if (!m) return { speak: NAV_SPEECH.already };
          home();
          return { speak: NAV_SPEECH.desk };
        }
        const withData = (answers || []).filter((a) => a && a.kind === 'rich' && a.response
          && Array.isArray(a.response.data) && a.response.data.length);
        const last = withData.length ? withData[withData.length - 1] : null;
        if (!last) return { speak: NAV_SPEECH.nochart };
        setPinned(last.id);
        return { speak: NAV_SPEECH.chart };
      },
      view: (v) => {
        const { current: m, question: q } = apiRef.current;
        const data = m && m.kind === 'rich' && m.response && Array.isArray(m.response.data) ? m.response.data : [];
        if (!data.length) return { speak: NO_PICTURE };                 // nothing on screen to draw another way
        if (CHAT_VIEWS.includes(v)) return { chat: true };              // the chat's own redraw (it shows in the chat too)
        let p = null;
        try { p = plan(m.response, m.question || q, v); } catch (e) { p = null; }
        if (p && p.applied && p.applied.drawn) setVoiceViews((o) => ({ ...o, [m.id]: v }));
        else setViewNote({ ...viewChip(v, p ? p.applied : null), n: Date.now() });
        return { speak: viewSpeech(v, p ? p.applied : null) };
      },
    });
    return () => registerStage(null);
  }, [registerStage]);
  // the chip under the title: which view the switch drew (and why another one, when the data did not allow it)
  useEffect(() => {
    if (!instant || !vplan || !cardsUp) return undefined;
    setViewNote({ ...viewChip(curView, vplan.applied), n: Date.now() });
    return undefined;
  }, [planKey, cardsUp]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!viewNote) return undefined;
    const t = setTimeout(() => setViewNote(null), 4200);
    return () => clearTimeout(t);
  }, [viewNote]);

  // ── the figure explained (2026-11-11): a fresh single-figure answer gets ONE background question for the breakdown
  // behind it (the same question by district, or by financial year when a place is named), in a throwaway session (the
  // officer's conversation and its follow-up context are never touched; nothing is added to the chat; not spoken).
  // Dropped on error, on no rows, after EXPLAIN_MS, on a new question, or when the stage moved on; drawn only when its
  // parts add up to the figure (vizPlan.explainCard).
  const exRef = useRef({ key: null, ctrl: null, userId: 0 });
  const exLog = (o) => { if (TEST()) window.__stageExplain = { ...(window.__stageExplain || {}), ...o, t: Math.round(performance.now()) }; };
  useEffect(() => {
    if (!cardsUp || !planKey || !vplan || !fresh || instant || !response) return;
    if (exRef.current.key === planKey) return;
    const data = Array.isArray(response.data) ? response.data : [];
    if (!(vplan.cards.length && vplan.cards.every((c) => c.single) && data.length === 1)) return;
    exRef.current.key = planKey;
    const key = planKey;
    if (TEST()) window.__stageExplain = { key: String(key), state: 'considering' };
    const ask = explainAsk(question, response);
    const first = vplan.cards[0];
    const tile = (first.items || []).find((x) => x.value !== null && x.value !== undefined && x.col);
    if (!ask || !tile) { exLog({ state: 'skipped', why: ask ? 'no figure' : 'a place and a year are both named' }); return; }
    const ctrl = new AbortController();
    const sid = throwawaySessionId();
    exRef.current.ctrl = ctrl; exRef.current.userId = turn.userId;
    const timer = setTimeout(() => ctrl.abort(), EXPLAIN_MS);
    exLog({ state: 'asking', q: ask.q, by: ask.by, tile: { col: tile.col, value: tile.value } });
    fetchNLPResponse(ask.q, 'en', sid, { signal: ctrl.signal })
      .then((res) => {
        if (ctrl.signal.aborted || exRef.current.key !== key) { exLog({ state: 'dropped', why: 'the stage moved on' }); return; }
        const out = explainCard(tile, res, ask.by, { oneMeasure: first.kind === 'kpi' });
        if (!out.card) { exLog({ state: 'dropped', why: out.why, sum: out.sum ?? null, total: out.total ?? null }); return; }
        setExplain({ key, card: out.card });
        exLog({ state: 'shown', sum: out.sum, total: out.total, col: out.col, data: out.data,
          card: { kind: out.card.kind, title: out.card.title, note: out.card.note,
            items: out.card.items.map((x) => ({ key: x.key, label: x.label, col: x.col, value: x.value })) } });
      })
      .catch((err) => exLog({ state: 'dropped', why: ctrl.signal.aborted ? 'cancelled or timed out' : 'error: ' + String((err && err.message) || err) }))
      .finally(() => { clearTimeout(timer); if (exRef.current.ctrl === ctrl) exRef.current.ctrl = null; forget(sid); });
  }, [cardsUp, planKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // a new question (asked by voice, typed, a tile) cancels the breakdown still on its way
  useEffect(() => {
    const x = exRef.current;
    if (x.ctrl && (live.thinking || turn.userId !== x.userId)) { x.ctrl.abort(); x.ctrl = null; }
  }, [live.thinking, turn.userId]);
  useEffect(() => () => { if (exRef.current.ctrl) exRef.current.ctrl.abort(); }, []);

  // the insight chip: once every item is in (Mitra: insight() 1.2 s after the last one)
  useEffect(() => {
    setInsightOn(false);
    if (!cardsUp) return undefined;
    let t = 0;
    const fire = () => { clearTimeout(t); t = setTimeout(() => setInsightOn(true), 1200); };
    registry.onAll = fire;
    if (registry.isAll()) fire();
    return () => { clearTimeout(t); if (registry.onAll === fire) registry.onAll = null; };
  }, [cardsUp, planKey, registry]);

  // captions: while the voice streams the newest words stay in view (the box glides, CSS scroll-behavior); a static
  // text starts at its beginning
  const capStatic = useRef(false);
  useEffect(() => {
    const c = capRef.current; if (!c) return;
    c.scrollTop = capStatic.current ? 0 : c.scrollHeight;
  }, [live.captions.megh, live.captions.you, currentId]);

  const send = (e) => {
    e.preventDefault();
    const q = draft.trim(); if (!q) return;
    setDraft(''); onType(q);
  };
  const state = live.voiceState;
  const mode = live.phase === 'off' ? 'standby' : live.phase === 'connecting' ? 'connecting' : 'live';

  // the stage's cards and their layout (Mitra: data-n 1 / 2 / 3, a board of six, a map beside its cards)
  const cards = shown ? shown.plan.cards : [];
  const kindOf = (c, map = kinds) => map[c.id] || c.kind;
  const layout = (list, map) => {
    const n = list.length;
    const boardL = n > 3;
    const mapAt = list.findIndex((c) => kindOf(c, map) === 'map');
    const lead = list[0] ? kindOf(list[0], map) : '';
    const chartFirst = !!lead && !['tiles', 'kpi', 'table', 'map'].includes(lead);
    const mapfocus = !boardL && n >= 2 && mapAt >= 0 && !chartFirst;
    return { n, board: boardL, mapfocus, mapAt, cls: 'vs-cards' + (boardL ? ' board' : '') + (mapfocus ? ' mapfocus' : ''),
      style: { '--rows': Math.max(1, n - 1) } };
  };
  const L = layout(cards, kinds);
  const explained = !!(shown && shown.plan.explained);
  const morphable = cards.filter((c) => (c.allowed || []).length > 1);
  const kindChoices = KIND_ORDER.filter((k) => morphable.some((c) => c.allowed.includes(k)));
  const activeKind = morphable.length ? kindOf(morphable[0]) : null;
  const morph = (k) => {
    if (!shown) return;
    setGhost({ ...shown, key: shown.key + ':m', kinds: { ...kinds } });
    setTimeout(() => setGhost(null), 750);
    const next = { ...kinds };
    morphable.forEach((c) => { if (c.allowed.includes(k)) next[c.id] = k; });
    setKinds(next);
  };
  const GL = ghost ? layout(ghost.plan.cards, ghost.kinds || {}) : null;
  const flipRef = useRef({ key: null, n: 0, pos: new Map() });
  const nCards = cards.length;
  useLayoutEffect(() => {
    const root = rootRef.current; const f = flipRef.current;
    const grid = root ? root.querySelector('.vs-host .vs-grid') : null;
    const next = new Map();
    const els = grid ? [...grid.children].filter((el) => el.classList.contains('vc')) : [];
    els.forEach((el) => next.set(el.dataset.card, { x: el.offsetLeft + el.offsetWidth / 2, y: el.offsetTop + el.offsetHeight / 2 }));
    if (f.key === shownKey && f.n && f.n !== nCards && !reducedMotion()) {
      els.forEach((el) => {
        const was = f.pos.get(el.dataset.card); const now = next.get(el.dataset.card);
        if (!was || !now || typeof el.animate !== 'function') return;
        const dx = was.x - now.x; const dy = was.y - now.y;
        if (Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
        el.animate([{ transform: `translate(${dx.toFixed(1)}px, ${dy.toFixed(1)}px)` }, { transform: 'none' }],
          { duration: 680, easing: 'cubic-bezier(.2, .8, .2, 1)' });
      });
    }
    flipRef.current = { key: shownKey, n: nCards, pos: next };
  }, [shownKey, nCards]);

  // what is said: the captions (you · and Megh's words); before any question the greeting heading
  const heading = greetingHeading();
  const megh = live.captions.megh || '';
  const you = live.captions.you || (current ? (isRedraw(current) ? turn.question || question : question) : '');
  const greetingOnly = !you && !current;
  const deskAnswer = !!current && !vplan && !working;
  const answerText = response ? plainText(response.answer) : '';
  // THE text on the stage: for an answer the voice reads, its natural words as they are said (never the pipeline's
  // formal text, which stays in the chat, in the cards' own figures and, for assistive technology, in .vs-answer);
  // an answer seen another way (pinned from the dock, typed while the voice is off) shows its own text
  let meghShown = megh; let capLive = live.speaking; let capOwn = false;
  if (!current) meghShown = greetingOnly && megh.startsWith(heading) ? afterGreeting(megh.slice(heading.length)) : megh;
  else if (working) meghShown = spokenLive;
  else if (ownSpoken) { meghShown = ownSpoken; capLive = live.speaking && fresh; }
  else if (fresh && !turnOver) { meghShown = ''; capLive = false; }                  // the voice is about to read it
  else { meghShown = answerText; capLive = false; capOwn = true; }
  capStatic.current = capOwn;

  // trace chips (Mitra: Listen · Hear · Understand · Act · Speak), driven by the voice state and the pipeline
  const answered = !!turn.answer && turn.answer.kind !== 'typing';
  const step = state === 'speaking' ? 4 : working ? 3 : live.thinking ? 2
    : (state === 'listening' && live.captions.you && !megh) ? 0 : answered ? 5 : -1;
  const lat = live.latencyMs != null ? (live.latencyMs / 1000).toFixed(1) + ' s' : '';

  const feed = turn.asked.slice(-8).reverse();
  const earlierChips = turn.earlier.slice(-6).reverse();
  const stageTitle = shown ? titleOf(shown.plan, shown.q) : '';
  const cls = 'vstage' + (stageOn ? ' parked' : ' desk') + (exiting ? ' stage-out' : '') + (vplan ? ' has-plan' : '')
    + (board || boardMissing ? ' board-ready' : '') + (colsDone ? ' cols-done' : '') + (navHome ? ' nav-home' : '')
    + (stageOn && L.board ? ' board-on' : '') + (stageOn && L.mapfocus ? ' mapfocus-on' : '')
    + (mode === 'live' ? ' live' : '') + (stageOn && working ? ' refine' : '') + (insightOn ? ' insight-on' : '')
    + (capLive && meghShown ? ' voicing' : '');

  return (
    <div className={cls} ref={rootRef} data-state={state} role="dialog" aria-label="Live voice">
      <div className="vs-bg" aria-hidden="true"><i className="au a1" /><i className="au a2" /><i className="au a3" /><i className="vs-gridbg" /></div>

      {/* THE STAGE (Mitra's #stageHost): between the header and the footer */}
      <div className="vs-host">
        <StageFx on={stageOn} />
        <div className="vs-veil" aria-hidden="true" />
        <div className="vs-beam" aria-hidden="true" />
        <div className="vs-title">{stageTitle}</div>
        {viewNote && stageOn && (
          <div className={'vs-viewchip' + (viewNote.sub ? ' fell' : '')} key={viewNote.n} role="status">
            <i aria-hidden="true" /><b>{viewNote.title}</b>{viewNote.sub && <span>{viewNote.sub}</span>}
          </div>
        )}
        <main className={'vs-stagearea' + (working ? ' working' : '')}>
          {answerText && <div className="vs-answer" aria-hidden={!vplan}>{answerText}</div>}
          <div className={'vs-grid ' + L.cls + (explained ? ' explained' : '') + (swapRef.current.on ? ' swap' : '')} data-n={Math.min(3, L.n)} style={L.style}>
            {cards.map((c, i) => {
              const k = kindOf(c);
              const morphed = !!kinds[c.id];
              return (
                <StageCard key={c.id + (morphed ? ':' + k : '')} spec={c} index={i} registry={registry} kind={k}
                           className={(L.mapfocus && i === L.mapAt ? 'mf-map' : '') + (morphed || (shown && shown.instant) ? ' morphing' : '')
                             + (c.explain ? ' vc-explain' : '')} />
              );
            })}
          </div>
          {ghost && (
            <div className={'vs-ghostlayer ' + GL.cls} data-n={Math.min(3, GL.n)} style={GL.style} aria-hidden="true">
              {ghost.plan.cards.map((c, i) => (
                <StageCard key={'g' + c.id} spec={c} index={i} registry={ghostRegistry} still kind={kindOf(c, ghost.kinds || {})}
                           className={'vc-ghost' + (GL.mapfocus && i === GL.mapAt ? ' mf-map' : '')} />
              ))}
            </div>
          )}
        </main>
        <div className={'vs-insight' + (insightOn && shown && shown.plan.insight ? ' on' : '')}>
          {shown && shown.plan.insight && <><span>✦</span>{shown.plan.insight}</>}
        </div>
        <div className={'vs-kinds' + (stageOn && !L.board && kindChoices.length > 1 ? ' on' : '')} role="group" aria-label="Show as">
          <span>Show as</span>
          {kindChoices.map((k) => (
            <button key={k} type="button" className={k === activeKind ? 'on' : ''} aria-pressed={k === activeKind} onClick={() => morph(k)}>
              {KIND_LABEL[k] || k}
            </button>
          ))}
        </div>
        <div className="vs-dock">
          <div className="vs-dock-chips" data-n={deskChips.length + earlierChips.length} />
          <button type="button" className="vs-chip home vs-dockclose" onClick={toDesk}><i>⌃</i> Dashboard</button>
        </div>
      </div>

      <header className="vs-top">
        <div className="vs-brand">
          <div className="vs-halo"><span className="vs-mark">M</span></div>
          <div className="vs-brand-t"><b>Megh One AI</b><span>Government of Meghalaya · Secretary</span></div>
        </div>
        <div className="vs-hdr-right">
          <div className="vs-clock" title="Today">{today()}</div>
          <VoicePicker live={live} />
          <div className={'vs-status' + (mode === 'live' ? ' ok' : '')}><span className="dot" /><span>Megh One AI · live voice</span>
            <span className="vs-ai-label" title="This voice is computer-generated. Every figure it says comes from the scheme data and is shown on screen.">{AI_VOICE_LABEL}</span></div>
          <button type="button" className="vs-back" onClick={onClose}>Back to chat <kbd>Esc</kbd></button>
        </div>
      </header>

      <div className="vs-main">
        <aside className="vs-col vs-col-l" aria-hidden={stageOn} ref={colLRef}>
          <SecretaryDesk side="left" board={board} onAsk={onType} conversation={turn.answers} onPin={setPinned} />
        </aside>

        <section className="vs-center">
          <div className="vs-orb" ref={orbWrapRef}>
            <VoiceOrb live={live} parked={stageOn} rootRef={rootRef} />
            <div className={'vs-mode' + (live.muted ? ' muted' : '')} data-m={mode}>
              <i /><b>{MODE_LABEL[mode]}</b>{lat && <span className="lat" key={lat}>{lat}</span>}
            </div>
            <div className="vs-dmeter you" ref={live.meterYou} aria-hidden="true"><i /><span>you</span></div>
            <div className="vs-dmeter me" ref={live.meterMegh} aria-hidden="true"><i /><span>Megh</span></div>
            <div className="vs-orb-state vs-pill" data-s={state}>
              <span className="k">{STATE_LABEL[state] || 'Listening'}</span><span className="v">{STATE_HINT[state] || ''}</span>
            </div>
          </div>

          <div className={'vs-captions' + (capLive ? ' streaming' : '') + (capOwn ? ' own' : '')} ref={capRef} aria-live="polite">
            {greetingOnly && <div className="vs-hello"><h2>{heading}</h2></div>}
            {you && <div className="vs-you">{you}</div>}
            {meghShown && <div className="vs-megh" key={'m' + (currentId || turn.userId || 0)}><Words text={meghShown} streaming={capLive} /></div>}
          </div>

          <MicWave analysers={live.analysers} on={state === 'listening' && !live.muted && !stageOn} />

          <div className="vs-trace" aria-hidden="true">
            {TRACE.map((t, i) => (
              <span key={t} className={i < step ? 'done' : i === step ? 'run' : ''}>
                <i />{t}{i === 4 && step === 5 && lat && <b>{lat}</b>}
              </span>
            ))}
          </div>

          <div className="vs-composer">
            <button type="button" className={'vs-mute' + (live.muted ? ' on' : '')} aria-pressed={live.muted}
                    data-tip={live.muted ? 'Tap to unmute (M)' : 'Tap to mute (M) · the answer still plays'}
                    onClick={() => (live.phase === 'off' ? live.start() : live.setMuted(!live.muted))}
                    aria-label={live.muted ? 'Unmute' : 'Mute'}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4zm6-4a6 6 0 0 1-12 0H4a8 8 0 0 0 7 7.93V22h2v-3.07A8 8 0 0 0 20 11h-2z" /></svg>
            </button>
            <button type="button" className={'vs-stop' + (state === 'speaking' || state === 'thinking' ? ' on' : '')}
                    title="Stop (tap the orb)" aria-label="Stop" onClick={() => live.hush()}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg>
            </button>
            <form className="vs-compose" onSubmit={send}>
              <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="…or type what you would say, then Enter"
                     aria-label="Type a question" maxLength={2000} autoComplete="off" spellCheck={false} />
              <button type="submit" title="Send" aria-label="Send">↵</button>
            </form>
          </div>

          <div className="vs-hints vs-starters">
            {STARTERS.map((q) => <button key={q} type="button" onClick={() => onType(q)}>{q}</button>)}
          </div>
        </section>

        {/* the right column's entrance ends last: then the entrance is dropped, so it never plays again */}
        <aside className="vs-col vs-col-r" aria-hidden={stageOn} ref={colRRef}
               onAnimationEnd={(e) => { if (e.target === e.currentTarget && e.animationName === 'vsColIn') setColsDone(true); }}>
          {deskAnswer && (
            <div className="vs-grid vs-ansgrid">
              <div className={'vs-card vs-anscard' + (ownSpoken ? ' spoken' : '')} key={cardKeyId} ref={cardRef}>
                <h3>Answer <small>{trimEnd(question).slice(0, 60) || 'Megh One AI'}</small></h3>
                <div className="vs-ansbody">{renderMessage(current)}</div>
              </div>
            </div>
          )}
          <SecretaryDesk side="right" board={board} onAsk={onType} conversation={turn.answers} onPin={setPinned} />
        </aside>
      </div>

      <button type="button" className="vs-park" onClick={() => {
        if (live.phase === 'off') live.start(); else if (live.speaking) live.hush(); else if (live.muted) live.setMuted(false);
      }} data-s={state} aria-label="Voice state">
        <i />{live.muted ? 'Muted' : PARK_LABEL[state] || 'Listening'}
      </button>

      <footer className="vs-feed">
        <div className="vs-feed-h" data-n={feed.length}><span className="pulse" />Schemes</div>
        <SchemeStrip onAsk={onType} active={schemeIn(stageTitle)} />
        <button type="button" className="vs-end" onClick={onClose}>End</button>
      </footer>
    </div>
  );
}
