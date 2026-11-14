import '../../styles/voice.css';

/* Live voice strip (full-duplex voice, 2026-11-02): sits just above the
   composer while a live conversation is open. A pill (Connecting / Listening /
   Speaking), the time from the end of the question to the first word of the
   answer, two live meters (your voice, Megh's voice, both at once), the words
   as they are heard and said, and End. The answer itself appears in the chat
   as for a typed question. */
export function LiveVoiceStrip({ live }) {
  if (!live || live.phase === 'off' || live.view) return null;     // the voice stage shows it all
  const state = live.phase === 'connecting' ? 'connecting' : (live.speaking ? 'speaking' : 'listening');
  const label = { connecting: 'Connecting…', listening: 'Listening', speaking: 'Speaking' }[state];
  const { you, megh } = live.captions;
  return (
    <div className={'live-strip ' + state} role="status" aria-live="polite" data-live={state}>
      <span className="live-pill"><i aria-hidden="true" />Live · {label}</span>
      <span className="live-meters" aria-hidden="true">
        <span className="live-meter you" ref={live.meterYou} title="Your voice"><b /></span>
        <span className="live-meter megh" ref={live.meterMegh} title="Megh One AI"><b /></span>
      </span>
      <span className="live-caption">
        {megh ? <><em>Megh</em> {megh}</> : (you ? <><em>You</em> {you}</> : (state === 'connecting' ? 'Opening the live voice…'
          : 'Speak naturally. You can interrupt at any time.'))}
      </span>
      {live.latencyMs != null && <span className="live-latency" title="From the end of your question to the first word of the answer">{(live.latencyMs / 1000).toFixed(1)} s</span>}
      <button type="button" className="live-end" onClick={() => live.end('button')} aria-label="End live voice">End</button>
    </div>
  );
}
