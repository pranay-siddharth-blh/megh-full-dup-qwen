import { useEffect } from 'react';

/* Publishes the fixed composer's current height as --composer-h on <html>, so
   anything that floats above it (the scroll-to-top button) can sit just above
   it on every screen size — the composer grows with a long question, gains the
   "new answer" pill, and has different paddings on phones. */
export function useComposerHeight(selector = '.composer-wrap') {
  useEffect(() => {
    const el = document.querySelector(selector);
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const root = document.documentElement;
    const set = () => root.style.setProperty('--composer-h', Math.round(el.getBoundingClientRect().height) + 'px');
    set();
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  }, [selector]);
}
