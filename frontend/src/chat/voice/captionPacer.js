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

export function newPacer(text = '') {
  const words = splitWords(text);
  return { text: words.join(' '), text_raw: words.length ? words.join(' ') + ' ' : '', words, complete: words.length, anchors: [[words.length, 0]], audioQ: 0, chunks: [],
    playedBase: 0, shown: words.length, final: false, textAt: 0, tickAt: 0 };
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
  p.text_raw = joinOut(p.text_raw, piece);
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
