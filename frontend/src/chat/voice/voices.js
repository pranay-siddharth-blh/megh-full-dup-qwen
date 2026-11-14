/* The voice toggle (2026-11-12): the sovereign engine's voices the officer may choose. The pipeline, the ears and the
   picture are the same for every voice; only the mouth changes. The key is sent in the live session's hello (the
   relay passes it to the engine as its voice name; Gemini never receives it). The choice is remembered per browser.
   A voice listed with `ready: false` is shown but cannot be chosen yet. No regex (D-046 / D-047). */

export const VOICES = [
  { key: 'a', name: 'Indian woman', tone: 'Warm', ready: true },
  { key: 'b', name: 'Indian woman', tone: 'Bright', ready: true },
  { key: 'c', name: 'Indian woman', tone: 'Mature', ready: true },
  { key: 'd', name: 'Indian man', tone: 'Coming soon', ready: false },
];
export const DEFAULT_VOICE = 'a';
const STORE = 'megh_voice';

export function readVoice() {
  try {
    const k = window.localStorage.getItem(STORE) || '';
    return VOICES.some((v) => v.key === k && v.ready) ? k : DEFAULT_VOICE;
  } catch (e) {
    return DEFAULT_VOICE;
  }
}

export function saveVoice(k) {
  try { window.localStorage.setItem(STORE, k); } catch (e) { /* private window: the choice lasts this session */ }
}

export const voiceOf = (k) => VOICES.find((v) => v.key === k) || VOICES[0];

/** What the voice says the moment it changes (in the new voice). */
export const SWITCH_LINE = "Hello, sir. This is how I'll sound from now on.";
