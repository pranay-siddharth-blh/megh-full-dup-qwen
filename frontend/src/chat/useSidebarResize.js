import { useCallback, useEffect, useRef, useState } from 'react';

/* Drag-to-resize for the desktop sidebar, the way ChatGPT and Claude do it.

   The width is the --sidebar-w the layout already runs on (the grid column and
   the fixed composer's left offset both read it), so setting that one variable
   on .app moves everything together. The handle is a thin strip on the
   sidebar's right edge:
     - drag it: 200..480 px, remembered per browser (localStorage);
     - drag it past the left threshold and let go: the sidebar collapses to the
       icon rail (the same state as the toggle button / Ctrl+B);
     - double-click it: back to the default 260 px;
     - keyboard: Tab to it, ArrowLeft / ArrowRight 16 px, Home / End min / max.
   Phones and tablets (<= 880 px) keep the slide-in drawer; CSS hides the
   handle there. */

const KEY = 'megh_sidebar_w';
export const SIDEBAR_MIN = 200;
export const SIDEBAR_MAX = 480;
export const SIDEBAR_DEFAULT = 260;
const COLLAPSE_AT = 150;   // released left of this -> collapse to the rail
const STEP = 16;           // keyboard step

const clamp = (w) => Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, Math.round(w)));

function readWidth() {
  try {
    const v = parseInt(localStorage.getItem(KEY), 10);
    return Number.isFinite(v) ? clamp(v) : SIDEBAR_DEFAULT;
  } catch (e) { return SIDEBAR_DEFAULT; }
}
function saveWidth(w) {
  try { localStorage.setItem(KEY, String(w)); } catch (e) { /* private mode: not remembered */ }
}
// Charts measure their box once; let them re-measure after the column moved.
const reflow = () => window.dispatchEvent(new Event('resize'));

export function useSidebarResize({ onCollapse }) {
  const [width, setWidth] = useState(readWidth);
  const [dragging, setDragging] = useState(false);
  const widthRef = useRef(width);
  widthRef.current = width;
  const stopRef = useRef(null);

  const onPointerDown = useCallback((e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const start = widthRef.current;
    let collapse = false;
    setDragging(true);
    const move = (ev) => {
      // The sidebar starts at the window's left edge, so the pointer's x IS the width.
      collapse = ev.clientX < COLLAPSE_AT;
      setWidth(collapse ? SIDEBAR_MIN : clamp(ev.clientX));
    };
    const stop = () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', stop);
      document.removeEventListener('pointercancel', stop);
      stopRef.current = null;
      setDragging(false);
      if (collapse) {
        setWidth(start);              // re-expanding opens at the width it had
        onCollapse();
      } else {
        saveWidth(widthRef.current);
      }
      setTimeout(reflow, 30);
    };
    stopRef.current = stop;
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', stop);
    document.addEventListener('pointercancel', stop);
  }, [onCollapse]);

  // A drag still running when the component goes away must not leak listeners.
  useEffect(() => () => { if (stopRef.current) stopRef.current(); }, []);

  const setAndSave = useCallback((w) => {
    const v = clamp(w);
    setWidth(v);
    saveWidth(v);
    setTimeout(reflow, 30);
  }, []);

  const onKeyDown = useCallback((e) => {
    const w = widthRef.current;
    const next = { ArrowLeft: w - STEP, ArrowRight: w + STEP, Home: SIDEBAR_MIN, End: SIDEBAR_MAX }[e.key];
    if (next === undefined) return;
    e.preventDefault();
    setAndSave(next);
  }, [setAndSave]);

  const onDoubleClick = useCallback(() => setAndSave(SIDEBAR_DEFAULT), [setAndSave]);

  return {
    width,
    dragging,
    handleProps: {
      role: 'separator',
      'aria-orientation': 'vertical',
      'aria-label': 'Resize sidebar',
      'aria-valuemin': SIDEBAR_MIN,
      'aria-valuemax': SIDEBAR_MAX,
      'aria-valuenow': width,
      tabIndex: 0,
      title: 'Drag to resize · double-click to reset',
      onPointerDown,
      onKeyDown,
      onDoubleClick,
    },
  };
}
