/* The captions of the live voice, paced by the audio that is actually PLAYING (2026-11-15, the user's live test:
   "the transcript at the top is flickering or not coming at all", "the whole sentence is jumping").

   What arrives: the voice's transcript (`out`) and its audio (24 kHz chunks), both well ahead of real time on the real
   Gemini Live (measured 2026-11-02: the whole answer's text in under 5 s, its audio 25 s), and, since 14 Nov
   (VOICE_BLOCK_UNSOURCED), the transcript only a checked SENTENCE at a time: a sentence is released when the next one
   begins, the last one at the end of the turn. The page used to hold each piece of text until the LAST audio chunk
   queued so far started to play, which on a burst is the end of everything received: a sentence's words appeared when
   it had already been said (a one-sentence answer: only at the very end), all at once.

   Here every piece of text is an ANCHOR: "the words received so far end at about this much audio" (the audio queued
   when the text arrived, since the transcript and the audio of a sentence arrive together). Between anchors the words
   are spread evenly, so word i shows when the audio played reaches it: words stream one by one in time with the voice,
   ChatGPT-like, whatever the size of the pieces. Text with no audio left to wait for (the audio already played, or
   none came) is typed in quickly rather than dropped in at once. Pure functions: useLiveVoice.js feeds them; tested in
   tests/captionPacer.test.js. No regex (D-046/D-047). */

export const MAX_RATE = 4.5;      // words per second of audio: the fastest an anchor may claim (text far ahead of audio)
export const CATCH_UP = 14;       // words per second: how fast words that are already due (their audio has begun) are typed in
export const CATCH_UP_DONE = 28;  // ... once every chunk of audio received has played (the voice has said them already)
export const SETTLE_MS = 450;     // text that has waited this long with all its audio played is shown (typed in)

const SPACE = ' \n\t\r';
const ENDS = '.?!,;:"\')”’';

/** The words of a text, split on any whitespace (no regex). */
export function splitWords(text) {
  const out = [];
  let cur = '';
  for (const ch of String(text || '')) {
    if (SPACE.includes(ch)) { if (cur) { out.push(cur); cur = ''; } } else cur += ch;
  }
  if (cur) out.push(cur);
  return out;
}

/** Two spoken pieces joined: a sentence end and a new word get one space ("... with 5,494.Hello, sir"). */
export function joinOut(prev, piece) {
  const p = String(piece || '');
  const last = prev ? prev[prev.length - 1] : '';
  const first = p[0] || '';
  const letter = (first >= 'A' && first <= 'Z') || (first >= 'a' && first <= 'z');
  return (prev || '') + ('.?!'.includes(last) && last !== '' && letter ? ' ' : '') + p;
}

let GEN = 0;
export function newPacer(text = '') {
  const words = splitWords(text);
  // breaks: word counts where one reading ends and the next begins (a turn's end, a cut); gen: which pacer this is
  return { text: words.join(' '), text_raw: words.length ? words.join(' ') + ' ' : '', words, complete: words.length, anchors: [[words.length, 0]], audioQ: 0, chunks: [],
    playedBase: 0, shown: words.length, final: false, textAt: 0, tickAt: 0, breaks: [words.length], gen: ++GEN };
}

/** One reading ended here (the relay's end of a turn): what comes next starts a new one (2026-11-16). */
export function markBreak(p) {
  const n = p.words.length;
  if (p.breaks[p.breaks.length - 1] !== n) p.breaks.push(n);
}

const CLOSE_Q = '"' + "'" + ')”’';
const closes = (w) => { let t = String(w || ''); while (t && CLOSE_Q.includes(t[t.length - 1])) t = t.slice(0, -1); return !!t && '.?!'.includes(t[t.length - 1]); };

/** Where the words of a reading that began when `at` words had come in start (2026-11-16, the user's live test on the
    sovereign engine: the holding line's last word was glued to the answer, "sir. West Garo Hills ..."): at `at` when
    a reading or a sentence ended there, else at the end of the sentence still coming in then (the rest of a holding
    line is never the answer's). null = that sentence has not ended yet. */
export function segmentStart(p, at) {
  if (at <= 0) return 0;
  for (let k = at; k <= p.complete; k++) {
    if (p.breaks.includes(k) || closes(p.words[k - 1])) return k;
  }
  return null;
}

/** Where the reading that holds word `at` began (the last break at or before it): the holding line said while an
    answer is worked out is shown on its own. */
export function readingStart(p, at) {
  let b = 0;
  p.breaks.forEach((k) => { if (k <= at) b = Math.max(b, k); });
  return b;
}

// the words a listener can see as whole: the last one may still be growing ("Meghal" + "aya") unless the text ends
// with a space or a sentence mark, or the turn is over
function completeCount(p) {
  const n = p.words.length;
  if (!n || p.final) return n;
  const t = p.text_raw || '';
  const last = t[t.length - 1] || '';
  return SPACE.includes(last) || ENDS.includes(last) ? n : n - 1;
}

function anchor(p) {
  const n = completeCount(p);
  const [w0, a0] = p.anchors[p.anchors.length - 1];
  if (n <= w0) { p.complete = Math.max(p.complete, n); return; }
  p.anchors.push([n, Math.max(p.audioQ, a0 + (n - w0) / MAX_RATE)]);
  p.complete = n;
}

/** A piece of the transcript arrived (`out`). */
export function addText(p, piece, nowMs) {
  // a new reading after a break never glues its first word to the last one ("That" + "One" -> "ThatOne")
  const raw = p.text_raw || '';
  const atBreak = p.breaks.includes(p.words.length) && raw && !SPACE.includes(raw[raw.length - 1]);
  const pc = String(piece || '');
  p.text_raw = joinOut(raw, atBreak && pc && !SPACE.includes(pc[0]) ? ' ' + pc : pc);
  p.words = splitWords(p.text_raw);
  p.text = p.words.join(' ');
  p.final = false;
  p.textAt = nowMs;
  anchor(p);
}

/** A chunk of audio was queued: it plays from `start` (audio-clock seconds) for `dur` seconds. */
export function addAudio(p, start, dur) {
  p.chunks.push([start, dur]);
  p.audioQ += dur;
}

/** The turn is over: every word received is whole, and its place in the audio is known. */
export function finish(p, nowMs) {
  p.final = true;
  if (nowMs != null && completeCount(p) > p.complete) p.textAt = nowMs;
  anchor(p);
}

/** Seconds of this reading's audio already played at audio-clock time `now`. */
export function played(p, now) {
  let s = p.playedBase;
  const keep = [];
  for (const [start, dur] of p.chunks) {
    if (now >= start + dur) p.playedBase += dur;
    else keep.push([start, dur]);
    s += Math.max(0, Math.min(dur, now - start));
  }
  p.chunks = keep;
  return s;
}

/** The word position the audio has reached (anchors interpolated). */
export function wordAt(p, sec) {
  const a = p.anchors;
  for (let i = 1; i < a.length; i++) {
    const [w0, t0] = a[i - 1];
    const [w1, t1] = a[i];
    if (sec < t1) return t1 > t0 ? w0 + ((w1 - w0) * Math.max(0, sec - t0)) / (t1 - t0) : w1;
  }
  return a[a.length - 1][0];
}

/** How many words to show now. `now` = the audio clock (seconds), `nowMs` = performance.now(). Advances p.shown. */
export function step(p, now, nowMs) {
  const total = p.complete;
  if (p.shown >= total) { p.tickAt = nowMs; return p.shown; }
  const pl = played(p, now);
  let target = pl > 0 ? Math.min(total, Math.floor(wordAt(p, pl)) + 1) : p.anchors[0][0];
  // nothing left to wait for: every chunk queued has played (or none came) and the text has waited a little
  const drained = pl >= p.audioQ - 0.02;
  if (drained && nowMs - p.textAt >= SETTLE_MS) target = total;
  if (target > p.shown) {
    // catching up (a sentence that arrived after its audio): typed in quickly, never dropped in at once
    // (one tick's worth at most: after a pause of the clock the words are still typed, not dropped in)
    const dt = p.tickAt ? Math.min(100, Math.max(0, nowMs - p.tickAt)) : 0;
    const room = Math.max(1, Math.floor((dt / 1000) * (drained ? CATCH_UP_DONE : CATCH_UP) + 0.5));
    p.shown = Math.min(target, p.shown + room);
  }
  p.tickAt = nowMs;
  return p.shown;
}

/** The text on screen. */
export function shownText(p) {
  return p.words.slice(0, p.shown).join(' ');
}

/** Words still to come (the reading is not over on screen). */
export function pending(p) {
  return p.shown < p.words.length || !p.final;
}

/** The audio was cut (barge-in, Stop) at audio-clock `now`: the words not heard yet are dropped (all of them heard when
    every chunk had already played); what follows starts a new reading. */
export function cut(p, now) {
  const heard = now != null && p.audioQ > 0 && played(p, now) >= p.audioQ - 0.02;
  return newPacer(heard ? p.words.slice(0, p.complete).join(' ') : shownText(p));
}

/* The engine's holding lines (2026-11-16, the user's live test on the sovereign engine: "Still working on it, sir.
   MGNREGA is highest in all 12 districts."): the fixed lines it says while an answer is worked out (D:/Full Duplex
   Architecture/megh/fixed_lines.py LEAD_FIRST / LEAD_LATER, fdx settings lead_phrases). Whatever their position, they
   are never part of an answer's caption: the answer's caption starts at its first word. */
export const HOLDING_LINES = ['One moment, sir.', 'Let me pull that up, sir.', 'Sure, give me a second.', 'Let me check that for you, sir.',
  'Still working on it, sir.', 'Almost there, sir.', 'Just a little longer, sir.',
  'One moment.', 'Let me check.', 'Just a second.', 'Let me look that up.'];
const plainKey = (s) => {
  let out = '';
  for (const ch of String(s || '').toLowerCase()) {
    if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')) out += ch; else if (out && !out.endsWith(' ')) out += ' ';
  }
  return out.trim();
};
const HOLD = new Set(HOLDING_LINES.map(plainKey));
const HOLD_LIST = [...HOLD];

/** The words of an answer's caption without the engine's holding lines: a whole holding sentence is dropped wherever it
    is; a sentence still coming in that so far reads like the start of one is held back until it is known (so it never
    flashes up and goes). */
export function withoutHolding(words) {
  const out = [];
  let cur = [];
  const flush = (done) => {
    if (!cur.length) return;
    const k = plainKey(cur.join(' '));
    if (done ? !HOLD.has(k) : !HOLD_LIST.some((h) => h === k || h.startsWith(k + ' ') || (h.startsWith(k) && k.length >= 3))) out.push(...cur);
    cur = [];
  };
  words.forEach((w) => { cur.push(w); if (closes(w)) flush(true); });
  flush(false);
  return out;
}
