import { useEffect, useState } from 'react';
import { message } from '../dictation/machine.js';

/* The dictation strip in the composer (D-111, 2026-11-15): a red dot, the time, the input level, ✕ (put the
   box back as it was) and ✓ (insert the words). The prompt box stays visible above it with the words
   arriving in place. Screen readers hear only "Listening" and, at the end, the App's "Dictation inserted";
   an error is an alert. */

const clock = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
};

export function DictationBar({ dict, maxSeconds = 120 }) {
  const { state } = dict;
  const [now, setNow] = useState(Date.now());
  const listening = state.status === 'listening';
  useEffect(() => {
    if (!listening) return undefined;
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, [listening]);

  if (state.status === 'idle') return null;
  if (state.status === 'error') {
    return (
      <div className="dict-bar error" role="alert">
        <span className="dict-msg">{message(state)}</span>
      </div>
    );
  }
  if (state.status === 'cancelled') return null;
  const elapsed = state.startedAt ? now - state.startedAt : 0;
  const nearEnd = elapsed > (maxSeconds - 10) * 1000;
  return (
    <div className={'dict-bar ' + state.status}>
      <span className="dict-dot" aria-hidden="true" />
      <span className={'dict-time' + (nearEnd ? ' near-end' : '')} aria-hidden="true">
        {listening ? clock(elapsed) : message(state)}
      </span>
      <span className="dict-level" ref={dict.levelRef} aria-hidden="true"><span /></span>
      <button type="button" className="dict-cancel" onClick={dict.cancel}
              title="Cancel dictation (Esc)" aria-label="Cancel dictation">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.4"
             strokeLinecap="round"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
      <button type="button" className="dict-done" onClick={dict.stop} disabled={state.status === 'finishing'}
              title="Insert the words" aria-label="Insert the dictated words">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.6"
             strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.5 4.5L19 7" /></svg>
      </button>
    </div>
  );
}

/* The words in the box with the tentative ones muted: drawn over the (transparent-text) textarea while
   dictating, with the textarea's own font, padding and scroll. */
export function DictationMirror({ value, range, textareaRef }) {
  const [box, setBox] = useState(null);
  useEffect(() => {
    const t = textareaRef.current;
    if (!t || !range) { setBox(null); return; }
    const cs = window.getComputedStyle(t);
    setBox({
      top: t.offsetTop, left: t.offsetLeft, width: t.offsetWidth, height: t.offsetHeight,
      font: cs.font, letterSpacing: cs.letterSpacing, lineHeight: cs.lineHeight,
      paddingTop: cs.paddingTop, paddingRight: cs.paddingRight, paddingBottom: cs.paddingBottom,
      paddingLeft: cs.paddingLeft, borderTopWidth: cs.borderTopWidth, borderLeftWidth: cs.borderLeftWidth,
      scroll: t.scrollTop,
    });
  }, [value, range, textareaRef]);
  if (!range || !box) return null;
  const a = value.slice(0, range.stableEnd);
  const b = value.slice(range.stableEnd, range.end);
  const c = value.slice(range.end);
  return (
    <div className="dict-mirror" aria-hidden="true"
         style={{ top: box.top, left: box.left, width: box.width, height: box.height, font: box.font,
           letterSpacing: box.letterSpacing, lineHeight: box.lineHeight, paddingTop: box.paddingTop,
           paddingRight: box.paddingRight, paddingBottom: box.paddingBottom, paddingLeft: box.paddingLeft,
           borderTopWidth: box.borderTopWidth, borderLeftWidth: box.borderLeftWidth }}>
      <div style={{ transform: `translateY(${-box.scroll}px)` }}>
        {a}<span className="dict-tentative">{b}</span>{c}{'​'}
      </div>
    </div>
  );
}
