/* One microphone, one owner (D-111, 2026-11-15): 'dictation' (the composer mic), 'live' (the voice agent)
   or null. A feature takes the mic with acquire(); it is refused while the other holds it. The voice orb
   (another workstream) calls stopDictation() before it opens the live voice: dictation stops and keeps its
   words (the same as tapping ✓), then the orb takes the mic. */

let current = null;
const stops = {};
const listeners = new Set();

const notify = () => listeners.forEach((fn) => { try { fn(current); } catch (e) { /* a listener's own fault */ } });

export function holder() {
  return current;
}

export function acquire(owner, stop) {
  if (current && current !== owner) return false;
  current = owner;
  if (stop) stops[owner] = stop;
  notify();
  return true;
}

export function release(owner) {
  if (current !== owner) return;
  current = null;
  delete stops[owner];
  notify();
}

/* Stop whoever holds the mic in their own way (dictation: insert the words). True when someone was stopped. */
export function stopHolder() {
  const fn = current && stops[current];
  if (!fn) return false;
  fn();
  return true;
}

export function stopDictation() {
  if (current !== 'dictation' || !stops.dictation) return false;
  stops.dictation();
  return true;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/* tests only */
export function _reset() {
  current = null;
  Object.keys(stops).forEach((k) => delete stops[k]);
  listeners.clear();
}
