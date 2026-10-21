import { useEffect, useRef, useState } from 'react';
import { countWords, isSpace, runEnd } from './text.js';

/* Word-by-word reveal of a fresh answer.

   Most answers never stream from the model (clarifications, deterministic
   answers built from the rows, edge replies), and the composer's own answers
   are short enough to arrive in well under a second. So every fresh answer is
   revealed here at a steady pace, about 30 words a second, taking more words
   per step on a long answer so none takes much over 2 s.

   The streamed draft and the final answer share one `key` (the in-flight
   message id): the final answer continues from what the draft already showed,
   and when the checked answer differs from the draft (a guard corrected a
   figure) it resumes from the first changed word. */

const TICK_MS = 33;
const TARGET_TICKS = 60;                 // ~2 s for a long answer
const shownByKey = new Map();            // key -> text already on screen

const reducedMotion = () => {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
};

// Length of the common prefix of a and b, cut back to a word boundary.
function commonWordPrefix(a, b) {
  let i = 0;
  const n = Math.min(a.length, b.length);
  while (i < n && a[i] === b[i]) i++;
  if (i === b.length || i === a.length) return i;
  while (i > 0 && !isSpace(b[i - 1])) i--;
  return i;
}

// End of the next `k` words of `text` from `pos` (a word plus its trailing space).
function advanceWords(text, pos, k) {
  for (let j = 0; j < k && pos < text.length; j++) {
    const wordStart = runEnd(text, pos, isSpace);
    const wordEnd = runEnd(text, wordStart, (c) => !isSpace(c));
    if (wordEnd === wordStart) return text.length;          // only spaces left
    pos = runEnd(text, wordEnd, isSpace);
  }
  return pos;
}

// A half-revealed "**17,2" would show its marker: hide an unmatched trailing **.
function balanced(slice) {
  const count = slice.split('**').length - 1;
  if (count % 2 === 0) return slice;
  const at = slice.lastIndexOf('**');
  return slice.slice(0, at) + slice.slice(at + 2);
}

/* Returns [visibleText, done]. `animate` false shows the text at once (a
   replayed thread). */
export function useReveal(text, key, animate = true) {
  const full = String(text || '');
  const start = () => {
    if (!animate || reducedMotion()) return full.length;
    const prev = key != null ? shownByKey.get(key) : '';
    return prev ? commonWordPrefix(prev, full) : 0;
  };
  const [n, setN] = useState(start);
  const fullRef = useRef(full);
  fullRef.current = full;

  // The text changed under us (a draft reset, a corrected final answer):
  // keep only the part that still matches.
  const shownRef = useRef('');
  useEffect(() => {
    const shown = shownRef.current;
    if (shown && !full.startsWith(shown)) setN(commonWordPrefix(shown, full));
  }, [full]);

  // One steady interval while there is text left to show. It restarts only
  // when the text grows after being fully shown, never on every token, so a
  // fast stream cannot starve it.
  const caughtUp = n >= full.length;
  useEffect(() => {
    if (caughtUp) return undefined;
    const id = setInterval(() => {
      const f = fullRef.current;
      setN((p) => {
        if (p >= f.length) return p;
        const remaining = countWords(f.slice(p));
        return advanceWords(f, p, Math.max(1, Math.ceil(remaining / TARGET_TICKS)));
      });
    }, TICK_MS);
    return () => clearInterval(id);
  }, [caughtUp]);

  const visible = full.slice(0, Math.min(n, full.length));
  shownRef.current = visible;
  if (key != null) shownByKey.set(key, visible);
  if (shownByKey.size > 200) shownByKey.delete(shownByKey.keys().next().value);
  return [balanced(visible), n >= full.length];
}
