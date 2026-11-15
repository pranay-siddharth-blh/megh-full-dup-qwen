/* The agent orb (D-113, 2026-11-15): the face of the live voice in the composer, the voice panel and the welcome
   hint. Plain logic only (no React, no DOM), so node tests read it:
     - sphereDots(): the dotted sphere's dots, from the same fibonacci lattice as the stage orb (voiceOrb.js),
       projected ONCE into a 100 x 100 box (the SVG is drawn from it; nothing moves but CSS transforms);
     - orbState(): which face the orb shows for what the page knows (idle / dictating / resting);
     - ORB_TEXT: the label, tooltip and description of each face;
     - the per-browser flags (the panel collapsed; the one-time "the mic now types" toast). */

export const TALK_LABEL = 'Talk to Megh One AI';
export const TALK_DESCRIPTION = 'Opens the live voice: you speak and it answers aloud. English only.';
export const RESTING_TIP = 'Live voice is resting. Back in a few minutes; the mic still types.';
export const MIC_TYPES_TOAST = 'The mic now types your words. For the live voice, tap the orb.';

export const ORB_TEXT = {
  idle: { label: TALK_LABEL, tip: TALK_LABEL, disabled: false },
  // the decision (2026-11-15): a tap while dictating stops the dictation (its words stay in the box), then the voice
  // opens; so the orb looks inert but stays a working button
  dictating: { label: 'Stop dictating and talk to Megh One AI', tip: 'Finish dictating first, or tap: your words stay in the box and the voice opens', disabled: false },
  resting: { label: TALK_LABEL + ' (live voice is resting)', tip: RESTING_TIP, disabled: true },
};

// The voice panel's "Try saying" (D-113): three of the stage's starters (VoiceStage.jsx STARTERS 1, 2 and 4),
// cross-scheme first. `scheme`: the SCHEME_HUES key whose colour dots the line, or null for every scheme (a ring).
export const PANEL_STARTERS = [
  { q: 'Give me the headline figure of every scheme', scheme: null },
  { q: 'Which scheme leads in each district?', scheme: null },
  { q: 'MGNREGA person-days by district', scheme: 'MGNREGA' },
];

// signedIn: a token is held; resting: the live voice fell back (useLiveVoice `resting`); hasMic: the browser offers a
// microphone (getUserMedia); dictating: the composer's mic is recording or finishing. Resting wins over dictating: a
// voice that cannot open is never offered, whatever else is going on.
export function orbState({ signedIn = true, resting = false, hasMic = true, dictating = false } = {}) {
  if (!signedIn || resting || !hasMic) return 'resting';
  if (dictating) return 'dictating';
  return 'idle';
}

// The dots: n points of a fibonacci lattice on the unit sphere, tilted towards the viewer (tilt radians about x), then
// projected with a little perspective. Front dots (z >= 0) are larger and brighter; back dots small and faint, so the
// two halves turning in opposite directions read as one ball turning. Rounded to 0.01 so the markup stays small.
const round = (v) => Math.round(v * 100) / 100;
const cache = new Map();
export function sphereDots(n = 64, tilt = 0.42) {
  const key = n + '|' + tilt;
  if (cache.has(key)) return cache.get(key);
  const front = [];
  const back = [];
  const ga = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = n === 1 ? 0 : 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = ga * i;
    const x = Math.cos(th) * r;
    const z = Math.sin(th) * r;
    const y1 = y * Math.cos(tilt) - z * Math.sin(tilt);
    const z1 = y * Math.sin(tilt) + z * Math.cos(tilt);
    const d = (1 + z1) / 2;                       // 0 at the back, 1 at the front
    const s = 1 + z1 * 0.18;                      // perspective
    const isFront = z1 >= 0;
    const dot = {
      cx: round(50 + x * 38 * s), cy: round(50 + y1 * 38 * s),
      r: round(isFront ? 1.35 + d * 1.55 : 0.85 + d * 0.75),
      a: round(isFront ? 0.42 + d * 0.52 : 0.16 + d * 0.24),
    };
    (isFront ? front : back).push(dot);
  }
  const out = { front, back };
  cache.set(key, out);
  return out;
}

// The sphere's own size inside a button of `size` px: three quarters, whole pixels (crisp at every zoom).
export const sphereSize = (size) => Math.max(14, Math.round(size * 0.75));

// ── per-browser flags (localStorage, in try / catch: blocked storage simply forgets) ──
export const PANEL_COLLAPSED_KEY = 'megh_voice_panel_collapsed';
export const MIC_TOAST_KEY = 'megh_mic_types_toast_seen';
const store = (s) => {
  if (s) return s;
  try { return typeof localStorage !== 'undefined' ? localStorage : null; } catch (e) { return null; }
};
export function readFlag(key, storage) {
  try { const s = store(storage); return !!s && s.getItem(key) === '1'; } catch (e) { return false; }
}
export function writeFlag(key, on, storage) {
  try { const s = store(storage); if (s) s.setItem(key, on ? '1' : '0'); } catch (e) { /* storage blocked */ }
}

// The one-time toast on the first mic press after the mic became dictation: `show(text)` is called once per browser.
// Returns true when it showed. The dictation side calls this at the top of its mic handler.
export function noteMicTypes(show, storage) {
  if (readFlag(MIC_TOAST_KEY, storage)) return false;
  writeFlag(MIC_TOAST_KEY, true, storage);
  if (typeof show === 'function') show(MIC_TYPES_TOAST);
  return true;
}
