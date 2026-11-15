/* Dictation state machine (D-111, 2026-11-15). Pure: (state, event) -> state. No React, no I/O.

   idle -> permission -> connecting -> listening -> finishing -> idle
   any live state -> cancelled (CANCEL) | error(kind) (MIC_DENIED, MIC_NONE, ERROR, NO_SPEECH, CLOSED early)

   The microphone and the socket open at the same time: READY may arrive while the browser is still asking
   for the microphone (`ready` is remembered), so "listening" needs both.
   Partial words are taken only in order (seq) and only while listening or finishing; the final text ends
   the dictation. */

export const IDLE = {
  status: 'idle', ready: false, seq: 0, stable: '', tentative: '', final: null, corrections: [],
  error: null, startedAt: 0, ended: null,
};

const LIVE = ['permission', 'connecting', 'listening', 'finishing'];
export const isLive = (s) => LIVE.includes(s.status);

export function reduce(s, e) {
  switch (e.type) {
    case 'START':
      if (isLive(s)) return s;
      return { ...IDLE, status: 'permission' };
    case 'MIC_OK':
      if (s.status !== 'permission') return s;
      return s.ready ? { ...s, status: 'listening', startedAt: e.at || 0 } : { ...s, status: 'connecting' };
    case 'READY':
      if (s.status === 'permission') return { ...s, ready: true };
      if (s.status === 'connecting') return { ...s, ready: true, status: 'listening', startedAt: e.at || 0 };
      return s;
    case 'PARTIAL':
      if (!(s.status === 'listening' || s.status === 'finishing' || s.status === 'connecting')) return s;
      if ((e.seq || 0) <= s.seq) return s;
      return { ...s, seq: e.seq, stable: e.stable || '', tentative: e.tentative || '' };
    case 'STOP':
      if (s.status === 'listening' || s.status === 'connecting') return { ...s, status: 'finishing' };
      if (s.status === 'permission') return { ...IDLE, status: 'cancelled' };
      return s;
    case 'FINAL':
      if (!isLive(s)) return s;
      return { ...s, status: 'idle', final: e.text || '', corrections: e.corrections || [], stable: e.text || '',
        tentative: '', ended: e.ended || null };
    case 'NO_SPEECH':
      if (!isLive(s)) return s;
      return { ...s, status: 'error', error: 'no_speech', tentative: '' };
    case 'MIC_DENIED':
      return isLive(s) ? { ...s, status: 'error', error: 'denied' } : s;
    case 'MIC_NONE':
      return isLive(s) ? { ...s, status: 'error', error: 'nomic' } : s;
    case 'ERROR':
      if (!isLive(s)) return s;
      return { ...s, status: 'error', error: e.kind || 'unavailable' };
    case 'CLOSED':
      // the socket closed without a final: before "ready" it is unavailable (the page falls back to the
      // batch upload); a replaced dictation (another tab) is simply over
      if (!isLive(s)) return s;
      if (e.reason === 'replaced') return { ...s, status: 'cancelled' };
      return { ...s, status: 'error', error: s.ready ? 'lost' : 'unavailable' };
    case 'CANCEL':
      return isLive(s) ? { ...IDLE, status: 'cancelled' } : s;
    case 'RESET':
      return IDLE;
    default:
      return s;
  }
}

/* What the officer is told (the live region and the bar). Errors are shown with role=alert. */
export function message(s) {
  if (s.status === 'permission') return 'Allow the microphone';
  if (s.status === 'connecting') return 'Starting…';
  if (s.status === 'listening') return 'Listening';
  if (s.status === 'finishing') return 'Finishing…';
  if (s.status === 'error') {
    return {
      denied: 'Microphone access is blocked. Allow it in the browser’s site settings.',
      nomic: 'No microphone was found.',
      no_speech: 'Didn’t catch any speech. Try again, close to the microphone.',
      asr: 'Speech recognition is unavailable right now. Please type your question.',
      lost: 'Dictation was interrupted. The words so far are kept.',
      busy: 'Dictation is busy right now. Please try again in a moment.',
      rate: 'Too many attempts. Please wait a minute.',
      auth: 'Please sign in again to use dictation.',
      unavailable: 'Dictation is unavailable right now.',
    }[s.error] || 'Dictation stopped.';
  }
  return '';
}
