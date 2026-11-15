/* The voice toggle (2026-11-12): the sovereign engine's voices the officer may choose. The pipeline, the ears and the
   picture are the same for every voice; only the mouth changes. The key is sent in the live session's hello (the
   relay passes it to the engine as its voice name; Gemini never receives it). The choice is remembered per browser.
   A voice listed with `ready: false` is shown but cannot be chosen yet. No regex (D-046 / D-047). */

// 16 Nov 2026 (the user's pick): two maya2-native voices on the sovereign engine, shown only as Female (Jahnavi, the
// voice the stage opens with) and Male (Akshat); the engine's voices.json maps f / m to them. a / b / c (the qwen3-tts
// clones) stay in the engine for FDX_TTS_ENGINE=qwen but are no longer offered.
export const VOICES = [
  { key: 'f', name: 'Female', tone: '', ready: true },
  { key: 'm', name: 'Male', tone: '', ready: true },
];
export const DEFAULT_VOICE = 'f';
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
