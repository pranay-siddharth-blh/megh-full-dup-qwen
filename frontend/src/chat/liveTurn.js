import { useCallback, useSyncExternalStore } from 'react';

/* The in-flight answer's live state (D-112, 2026-11-15): the pipeline steps
   passed so far, the composer's draft as it streams, and whether that draft is
   being rewritten (`stale`, after a draft_reset). It changes many times a second
   while an answer is written, so it lives here, outside the App's message list:
   only the components that show it (the typing message, the voice stage's step
   label) re-render on a token, never the whole chat. The message list holds a
   plain { id, kind: 'typing' } placeholder for it. */

const EMPTY = Object.freeze({ steps: Object.freeze([]), draft: '', stale: false });
const turns = new Map();          // typing message id -> { steps, draft, stale }
const subs = new Map();           // id -> Set of listeners

function notify(id) {
  const set = subs.get(id);
  if (set) set.forEach((fn) => fn());
}

export function startLive(id) {
  turns.set(id, { steps: [], draft: '', stale: false });
  notify(id);
}

/** Merge fn(current) into the turn's state (a no-op for a turn that has ended). */
export function patchLive(id, fn) {
  const cur = turns.get(id);
  if (!cur) return;
  turns.set(id, { ...cur, ...fn(cur) });
  notify(id);
}

export function endLive(id) {
  if (!turns.has(id)) return;
  turns.delete(id);
  notify(id);
}

export function getLive(id) {
  return (id != null && turns.get(id)) || EMPTY;
}

function subscribe(id, fn) {
  if (id == null) return () => {};
  let set = subs.get(id);
  if (!set) { set = new Set(); subs.set(id, set); }
  set.add(fn);
  return () => {
    set.delete(fn);
    if (!set.size) subs.delete(id);
  };
}

/** Whether the stream's `done` result is the one its `answer` event already showed
    (the server sends the same dict twice; D-112). Compared by value. */
export function sameResult(a, b) {
  if (a === b) return true;
  try { return JSON.stringify(a) === JSON.stringify(b); } catch (e) { return false; }
}

/** The live state of one in-flight answer; re-renders only its readers. */
export function useLiveTurn(id) {
  const sub = useCallback((fn) => subscribe(id, fn), [id]);
  const get = useCallback(() => getLive(id), [id]);
  return useSyncExternalStore(sub, get, get);
}

/** One value derived from the live state (`select` must be a stable function returning a
    primitive): its reader re-renders only when that value changes, not on every token. */
export function useLiveSelect(id, select) {
  const sub = useCallback((fn) => subscribe(id, fn), [id]);
  const get = useCallback(() => select(getLive(id)), [id, select]);
  return useSyncExternalStore(sub, get, get);
}
