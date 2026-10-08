import { useCallback, useEffect, useRef, useState } from 'react';
import { transcribe } from './api.js';
import { VOICE_LANG } from './constants.js';

/* Voice dictation with live text, like the mic in a chat app.

   While the officer speaks, the recording so far is transcribed about every
   2 s and the text appears in the composer as it grows (onPartial). On stop,
   the whole recording is transcribed once more and that final, most accurate
   text replaces the live one (onTranscript). Everything goes through our own
   ASR (POST /api/query/transcribe, qwen3-asr on the gateway): no audio leaves
   the government network. The ASR rejects webm/opus, so every upload is
   re-encoded as 16 kHz mono WAV first. The guards of the original page stay:
   silence, a recording stopped too soon, no speech, size. */

const PARTIAL_EVERY_MS = 2000;   // one live transcription at a time, at most this often
const MAX_RECORD_MS = 150000;    // ~2.5 min keeps the WAV under the 5 MB upload cap

// One shared AudioContext for the page, warmed on the first gesture.
let audioCtx = null;
function getAudioCtx() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!audioCtx || audioCtx.state === 'closed') audioCtx = new AC();
  return audioCtx;
}

// `keepRunning`: a live (partial) conversion happens while the level meter is
// using the same context, so it must not be suspended underneath it.
async function blobToWav(blob, keepRunning = false) {
  const ctx = getAudioCtx();
  if (!ctx) throw new Error('Web Audio API unavailable');
  try {
    if (ctx.state === 'suspended') await ctx.resume().catch(() => {});
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    // Downmix to mono by averaging the channels.
    const chans = decoded.numberOfChannels;
    const mono = new Float32Array(decoded.length);
    for (let c = 0; c < chans; c++) {
      const d = decoded.getChannelData(c);
      for (let i = 0; i < d.length; i++) mono[i] += d[i] / chans;
    }
    // Resample to 16 kHz by linear interpolation.
    const RATE = 16000;
    const ratio = decoded.sampleRate / RATE;
    const n = Math.max(1, Math.floor(mono.length / ratio));
    const pcm = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const pos = i * ratio; const i0 = Math.floor(pos); const frac = pos - i0;
      const a = mono[i0] || 0; const b = mono[i0 + 1] !== undefined ? mono[i0 + 1] : a;
      pcm[i] = a + (b - a) * frac;
    }
    // Signal level, so a silent clip is refused instead of hallucinated.
    let peak = 0; let sumSq = 0;
    for (let i = 0; i < n; i++) {
      const v = pcm[i] < 0 ? -pcm[i] : pcm[i];
      if (v > peak) peak = v;
      sumSq += pcm[i] * pcm[i];
    }
    const rms = n ? Math.sqrt(sumSq / n) : 0;
    // 44-byte WAV header + signed 16-bit little-endian samples.
    const buf = new ArrayBuffer(44 + n * 2); const view = new DataView(buf);
    const str = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
    str(0, 'RIFF'); view.setUint32(4, 36 + n * 2, true); str(8, 'WAVE');
    str(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
    view.setUint16(22, 1, true); view.setUint32(24, RATE, true);
    view.setUint32(28, RATE * 2, true); view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    str(36, 'data'); view.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) {
      const s = Math.max(-1, Math.min(1, pcm[i]));
      view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    const wav = new Blob([buf], { type: 'audio/wav' });
    try {
      Object.defineProperty(wav, 'audioPeak', { value: peak });
      Object.defineProperty(wav, 'audioRms', { value: rms });
    } catch (_) { /* level unknown */ }
    return wav;
  } finally {
    // SUSPEND, never close: closing broke every recording after the first.
    if (!keepRunning && ctx.state === 'running') ctx.suspend().catch(() => {});
  }
}

// Always the system default microphone (no in-page picker).
function openMicStream() {
  return navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
}

// phase: idle | starting | listening | finishing.  status: a short line shown
// in the composer ({text, sub, error}) or null.
export function useVoice({ lang, onPartial, onTranscript, onUnauthorized }) {
  const [phase, setPhase] = useState('idle');
  const [status, setStatus] = useState(null);
  const recorderRef = useRef(null);
  const meterRef = useRef(null);
  const levelRef = useRef(null);          // the level bars' container
  const recordingRef = useRef(false);
  const deviceRef = useRef('');
  const statusTimer = useRef(0);
  const partialTimer = useRef(0);
  const stopTimer = useRef(0);
  const sessionRef = useRef(0);            // bumps per recording; stale replies are ignored
  const langRef = useRef(lang);
  langRef.current = lang;

  // Warm the AudioContext on the first click / key press (no mic access here).
  useEffect(() => {
    try { localStorage.removeItem('megh_mic_device'); } catch (_) { /* ignore */ }
    const warm = () => {
      const ctx = getAudioCtx();
      if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
    };
    window.addEventListener('pointerdown', warm, { once: true, passive: true });
    window.addEventListener('keydown', warm, { once: true, passive: true });
    return () => {
      window.removeEventListener('pointerdown', warm);
      window.removeEventListener('keydown', warm);
    };
  }, []);

  const say = useCallback((text, sub, error, ms) => {
    clearTimeout(statusTimer.current);
    setStatus({ text, sub: sub || '', error: !!error });
    if (ms) statusTimer.current = setTimeout(() => setStatus(null), ms);
  }, []);
  const clearStatus = useCallback(() => { clearTimeout(statusTimer.current); setStatus(null); }, []);

  const micHint = () => 'Wait for “speak now”, then speak close to the microphone.'
    + (deviceRef.current ? ' Recording from: ' + deviceRef.current + '. Check it is the microphone you are speaking into.' : '');

  const markLive = useCallback(() => {
    if (!recordingRef.current) return;
    setPhase('listening');
    say('Listening — speak now', 'Say your whole question, then tap Stop (or press Esc)');
  }, [say]);

  // A Bluetooth mic delivers ~0.9 s of nothing while switching profile, so
  // "speak now" waits until samples actually arrive. The bars follow the level.
  const startMeter = useCallback((stream) => {
    const ctx = getAudioCtx();
    if (!ctx) { markLive(); return; }
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    const src = ctx.createMediaStreamSource(stream);
    const an = ctx.createAnalyser();
    an.fftSize = 1024; src.connect(an);
    const buf = new Float32Array(an.fftSize);
    const t0 = performance.now(); let live = false;
    const tick = () => {
      if (!meterRef.current) return;
      an.getFloatTimeDomainData(buf);
      let sq = 0; for (let i = 0; i < buf.length; i++) sq += buf[i] * buf[i];
      const rms = Math.sqrt(sq / buf.length);
      if (!live && (rms > 1e-4 || performance.now() - t0 > 3000)) { live = true; markLive(); }
      const level = Math.max(0, Math.min(1, (20 * Math.log10(rms + 1e-9) + 60) / 50));
      const box = levelRef.current;
      if (box) {
        const t = performance.now() / 160;
        Array.from(box.children).forEach((bar, i) => {
          const wobble = 0.55 + 0.45 * Math.abs(Math.sin(t + i * 1.3));
          bar.style.transform = `scaleY(${Math.max(0.18, level * wobble)})`;
        });
      }
      meterRef.current.raf = requestAnimationFrame(tick);
    };
    meterRef.current = { src, raf: requestAnimationFrame(tick) };
  }, [markLive]);

  const stopMeter = useCallback(() => {
    const m = meterRef.current;
    if (!m) return;
    cancelAnimationFrame(m.raf);
    try { m.src.disconnect(); } catch (_) { /* ignore */ }
    meterRef.current = null;
    const box = levelRef.current;
    if (box) Array.from(box.children).forEach((bar) => { bar.style.transform = ''; });
  }, []);

  // The final transcription of the whole recording, with every guard.
  const sendAudio = useCallback(async (blob) => {
    const done = () => setPhase('idle');
    if (blob.size > 5 * 1024 * 1024) {
      say('Recording too long', 'Please keep it under ~2 minutes', true, 3000); done(); return;
    }
    // Too short to contain anything. A cheap first check; note it is a DURATION
    // test, not a content test: after blobToWav the blob is uncompressed 16 kHz
    // PCM at 32 kB/s, so 1200 bytes is only ~36 ms.
    if (!blob || blob.size < 1200) {
      say('No speech detected', 'Hold the mic a bit longer and speak clearly', true, 3000); done(); return;
    }
    // Under a second: the stop was pressed too early (16 kHz 16-bit mono = 32,000 B/s).
    if ((blob.type || '').includes('wav')) {
      const secs = (blob.size - 44) / 32000;
      if (secs < 1.0) {
        say('Recording stopped too soon (' + secs.toFixed(1) + ' s)',
          'Tap the mic, wait for “speak now”, say the whole question, then tap Stop.', true, 4000);
        done(); return;
      }
    }
    // Digitally SILENT only; quieter speech is left to the server's no_speech check.
    const peak = typeof blob.audioPeak === 'number' ? blob.audioPeak : null;
    const rms = typeof blob.audioRms === 'number' ? blob.audioRms : null;
    if (peak !== null) console.info('mic:', deviceRef.current || '(unknown device)', 'peak', peak.toFixed(4), 'rms', (rms || 0).toFixed(5));
    if (peak !== null && peak < 0.003) {
      say('No sound was recorded', micHint(), true, 5000); done(); return;
    }
    const fail = (msg) => { say('Transcription failed', msg || 'Please try again', true, 4000); done(); };
    try {
      const res = await transcribe(blob, VOICE_LANG[langRef.current] || 'en', deviceRef.current);
      if (res.status === 401) { clearStatus(); done(); onUnauthorized(); return; }
      let data = {};
      try { data = await res.json(); } catch (_) { /* ignore */ }
      const transcript = data && (data.text || data.transcript);
      if (res.ok && data && data.no_speech) {
        say('Didn’t catch any speech', micHint(), true, 5000); done(); return;
      }
      if (res.ok && transcript) {
        clearStatus(); done();
        onTranscript(transcript);
      } else {
        fail(data && data.detail ? data.detail : `Server returned ${res.status}. Please try again.`);
      }
    } catch (e) {
      fail(e.name === 'AbortError' ? 'Timed out — please try a shorter recording'
        : `Could not reach the server (${e.message}). Is the backend running on this port?`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [say, clearStatus, onTranscript, onUnauthorized]);

  const stopMic = useCallback(() => {
    if (!recordingRef.current) return;
    recordingRef.current = false;
    clearInterval(partialTimer.current);
    clearTimeout(stopTimer.current);
    setPhase('finishing');
    say('Transcribing…', 'Finishing your question');
    const rec = recorderRef.current;
    if (rec && rec.state !== 'inactive') rec.stop();
  }, [say]);

  const startMic = useCallback(async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      alert('Microphone not supported in this browser. Please use Chrome, Edge, or Safari.'); return;
    }
    const session = ++sessionRef.current;
    setPhase('starting');
    say('Starting microphone…', 'Wait for “speak now”');
    try {
      const stream = await openMicStream();
      const track = stream.getAudioTracks()[0];
      deviceRef.current = (track && track.label) || '';
      const chunks = [];
      const prefer = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
      const picked = (window.MediaRecorder && MediaRecorder.isTypeSupported)
        ? prefer.find((t) => MediaRecorder.isTypeSupported(t)) : null;
      const rec = picked ? new MediaRecorder(stream, { mimeType: picked }) : new MediaRecorder(stream);
      const type = () => (rec.mimeType || picked || 'audio/webm').split(';')[0];
      recorderRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      rec.onstop = async () => {
        stopMeter();
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: type() });
        let out = blob;
        try { out = await blobToWav(blob); } catch (e) { console.warn('WAV conversion failed, sending original:', e); }
        await sendAudio(out);
      };
      // Small slices, so the recording so far can be transcribed while it grows.
      rec.start(250);
      recordingRef.current = true;
      startMeter(stream);

      // Live text: transcribe the recording so far, one request at a time.
      let busy = false; let lastLen = 0; const t0 = performance.now();
      partialTimer.current = setInterval(async () => {
        if (busy || !recordingRef.current || chunks.length === lastLen || performance.now() - t0 < 1500) return;
        busy = true; lastLen = chunks.length;
        try {
          const wav = await blobToWav(new Blob(chunks, { type: type() }), true);
          if (typeof wav.audioPeak === 'number' && wav.audioPeak < 0.003) return;   // nothing said yet
          const res = await transcribe(wav, VOICE_LANG[langRef.current] || 'en', deviceRef.current);
          if (!res.ok || session !== sessionRef.current || !recordingRef.current) return;
          const data = await res.json().catch(() => ({}));
          const text = data && !data.no_speech && (data.text || data.transcript);
          if (text && session === sessionRef.current && recordingRef.current) onPartial(text);
        } catch (_) {
          /* a live update is best-effort; the final transcription decides */
        } finally {
          busy = false;
        }
      }, PARTIAL_EVERY_MS);
      // Long recordings stop on their own before the upload cap.
      stopTimer.current = setTimeout(() => { if (session === sessionRef.current) stopMic(); }, MAX_RECORD_MS);
    } catch (e) {
      recordingRef.current = false;
      setPhase('idle');
      clearStatus();
      console.error('startMic getUserMedia failed:', e && e.name, e && e.message, e);
      let msg;
      switch (e && e.name) {
        case 'NotAllowedError':
          msg = 'Microphone access is blocked. Allow it in the browser site settings (and check the OS microphone privacy settings), then try again.'; break;
        case 'NotFoundError':
        case 'OverconstrainedError':
          msg = 'No microphone was found. Plug one in or select an input device, then try again.'; break;
        case 'NotReadableError':
          msg = 'The microphone is in use by another app. Close it and try again.'; break;
        default:
          msg = 'Could not start the microphone' + (e && e.name ? ' (' + e.name + ')' : '') + '. Please try again.';
      }
      alert(msg);
    }
  }, [say, clearStatus, sendAudio, startMeter, stopMeter, stopMic, onPartial]);

  const toggleMic = useCallback(() => {
    if (recordingRef.current) stopMic();
    else if (phase === 'idle') startMic();
  }, [phase, startMic, stopMic]);

  useEffect(() => () => { clearInterval(partialTimer.current); clearTimeout(stopTimer.current); clearTimeout(statusTimer.current); }, []);

  return {
    phase,
    isRecording: phase === 'starting' || phase === 'listening',
    busy: phase !== 'idle',
    status, levelRef, toggleMic, stopMic, recordingRef, clearStatus,
  };
}
