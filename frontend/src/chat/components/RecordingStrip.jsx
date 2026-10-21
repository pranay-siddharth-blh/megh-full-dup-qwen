import { useEffect, useState } from 'react';

/* Recording strip (#307): while the officer is speaking, the text box gives
   way to a red dot, the elapsed time and a live waveform; the stop button
   sits at the end of the bar. `levelRef` is the voice hook's level-meter
   target: the hook scales each bar with the microphone level every frame.
   The hook's status line ("Listening — speak now") stays as a muted hint,
   because a Bluetooth microphone can take a second before it hears anything. */
const BARS = 20;

const clock = (startedAt) => {
  const secs = startedAt ? Math.max(0, Math.floor((Date.now() - startedAt) / 1000)) : 0;
  return { m: Math.floor(secs / 60), s: String(secs % 60).padStart(2, '0') };
};

export function RecordingStrip({ startedAt, live, status, levelRef }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 250);
    return () => clearInterval(id);
  }, []);
  const { m, s } = clock(startedAt);
  return (
    <div className="rec-strip" role="status" aria-live="polite" aria-label={`Recording, ${m} minutes ${s} seconds`}>
      <span className={'rec-dot' + (live ? ' live' : '')} aria-hidden="true" />
      <span className="rec-time" aria-hidden="true">{m}:{s}</span>
      <span className="rec-wave" ref={levelRef} aria-hidden="true">
        {Array.from({ length: BARS }, (_, i) => <i key={i} />)}
      </span>
      {status && status.text && <span className="rec-hint" title={status.sub || ''}>{status.text}</span>}
    </div>
  );
}
