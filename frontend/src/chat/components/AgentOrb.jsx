import { useId, useState } from 'react';
import { ORB_TEXT, TALK_DESCRIPTION, sphereDots, sphereSize } from '../agentOrb.js';
import { keyLabel } from '../shortcuts.js';
import '../../styles/agent-orb.css';

/* The agent orb (D-113, 2026-11-15): a small dotted sphere that opens the live voice. Drawn once as four stacked SVG
   layers: the body (a gradient through the purple tokens), the back dots, the front dots (~64 white dots from the stage
   orb's fibonacci lattice, agentOrb.js), and the glass (depth shade, specular highlight, rim light). Motion is CSS
   transforms only, on their own layers: the front and back dots turn in opposite directions, a halo breathes, a wake
   ring on press. No canvas, no animation loop, no audio. Everything pauses while the voice view is up
   (body.vstage-on) and stands still under reduced motion.

   Faces (agentOrb.js orbState): idle; dictating (dimmed and still, but a tap stops the dictation and opens the voice);
   resting (grey and still, aria-disabled, the tooltip says why; a tap explains it again).
   `decorative`: drawn as a plain picture inside a bigger button (the panel's rail, the welcome hint). */

const Sphere = ({ uid }) => {
  const { front, back } = sphereDots(64);
  const id = (k) => uid + k;
  const dot = (d, i) => <circle key={i} cx={d.cx} cy={d.cy} r={d.r} fillOpacity={d.a} />;
  return (
    <>
      <svg className="ao-svg" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <defs>
          <radialGradient id={id('b')} cx="34%" cy="27%" r="80%">
            <stop offset="0" className="ao-s0" />
            <stop offset=".17" className="ao-s1" />
            <stop offset=".45" className="ao-s2" />
            <stop offset=".75" className="ao-s3" />
            <stop offset="1" className="ao-s4" />
          </radialGradient>
        </defs>
        <circle cx="50" cy="50" r="50" fill={`url(#${id('b')})`} />
      </svg>
      <svg className="ao-svg ao-layer ao-back" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <g fill="#fff">{back.map(dot)}</g>
      </svg>
      <svg className="ao-svg ao-layer ao-front" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <g fill="#fff">{front.map(dot)}</g>
      </svg>
      <svg className="ao-svg" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
        <defs>
          <radialGradient id={id('d')} cx="50%" cy="44%" r="56%">
            <stop offset=".58" stopColor="#241038" stopOpacity="0" />
            <stop offset="1" stopColor="#241038" stopOpacity=".36" />
          </radialGradient>
          <radialGradient id={id('h')} cx="50%" cy="50%" r="50%">
            <stop offset="0" stopColor="#fff" stopOpacity=".92" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </radialGradient>
          <linearGradient id={id('r')} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#fff" stopOpacity=".35" />
            <stop offset=".45" stopColor="#fff" stopOpacity="0" />
            <stop offset="1" className="ao-rim" />
          </linearGradient>
        </defs>
        <circle cx="50" cy="50" r="50" fill={`url(#${id('d')})`} />
        <ellipse className="ao-spec" cx="37" cy="25" rx="20" ry="12.5" fill={`url(#${id('h')})`} />
        <circle cx="50" cy="50" r="48.6" fill="none" stroke={`url(#${id('r')})`} strokeWidth="1.6" />
      </svg>
    </>
  );
};

export function AgentOrb({ size = 40, state = 'idle', onTalk, decorative = false, tip = false, className = '', testId }) {
  const raw = useId();
  const uid = 'ao' + raw.split(':').join('');       // React's ids carry colons; an SVG url(#…) is safer without
  const [wake, setWake] = useState(0);
  const text = ORB_TEXT[state] || ORB_TEXT.idle;
  const style = { '--ao': size + 'px', '--ao-s': sphereSize(size) + 'px' };
  const cls = 'agent-orb is-' + state + (className ? ' ' + className : '');
  const body = (
    <>
      <span className="ao-sphere"><Sphere uid={uid} /></span>
      {wake > 0 && <span className="ao-wake" key={wake} aria-hidden="true" />}
    </>
  );
  if (decorative) return <span className={cls} style={style} aria-hidden="true">{body}</span>;
  const shortcut = keyLabel('talk');
  return (
    <button type="button" className={cls} style={style} data-testid={testId} data-state={state}
            aria-label={text.label} aria-haspopup="dialog" aria-describedby={uid + 'x'}
            aria-disabled={text.disabled || undefined}
            onPointerDown={() => { if (!text.disabled) setWake((n) => n + 1); }}
            onClick={() => { if (onTalk) onTalk(); }}>
      {body}
      <span id={uid + 'x'} className="ao-sr">{text.disabled ? text.tip : TALK_DESCRIPTION}</span>
      {tip && (
        <span className="ao-tip" aria-hidden="true">
          {text.tip}{state === 'idle' && shortcut && <kbd>{shortcut}</kbd>}
        </span>
      )}
    </button>
  );
}
