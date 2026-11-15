import { useState } from 'react';
import { AgentOrb } from './AgentOrb.jsx';
import { PANEL_COLLAPSED_KEY, PANEL_STARTERS, RESTING_TIP, TALK_LABEL, readFlag, writeFlag } from '../agentOrb.js';
import { SCHEME_HUES } from '../chartTheme.js';
import { AI_VOICE_LABEL } from '../voiceSpeech.js';
import { keyLabel } from '../shortcuts.js';

/* The voice panel (D-113, 2026-11-15): the live voice offered beside the chat, never over it. Three tiers chosen by
   the MAIN area's own width (a container query on .main, agent-orb.css), because the sidebar can be dragged:
     - full card (main >= 1,580 px): what the voice does, three questions to say (a tap opens the voice and asks it),
       Start talking; compact once a conversation is on screen ("Talk about this answer"); an x folds it to the rail,
       remembered per browser;
     - slim rail (1,140-1,579 px): a glass pill on the right edge; a tap opens the voice;
     - below that nothing here: the welcome screen shows TalkHint under its title instead.
   Hidden while the voice view or a modal is up (the caller does not render it) and in print. */

const MULTI = ['MGNREGA', 'PMAY-G', 'Focus Plus', 'CM Elevate'].map((k) => SCHEME_HUES[k].main);
const multiDot = `conic-gradient(${MULTI[0]} 0 25%, ${MULTI[1]} 0 50%, ${MULTI[2]} 0 75%, ${MULTI[3]} 0)`;
const dotStyle = (scheme) => ({ background: scheme && SCHEME_HUES[scheme] ? SCHEME_HUES[scheme].main : multiDot });

const Foot = () => (
  <div className="vp-foot">English only · <b title="This voice is computer-generated. Every figure it says comes from the scheme data and is shown on screen.">{AI_VOICE_LABEL}</b></div>
);

export function VoicePanel({ state = 'idle', welcome = true, onTalk }) {
  const [collapsed, setCollapsed] = useState(() => readFlag(PANEL_COLLAPSED_KEY));
  const fold = (on) => { setCollapsed(on); writeFlag(PANEL_COLLAPSED_KEY, on); };
  const resting = state === 'resting';
  const talk = (q) => { if (onTalk) onTalk(q); };
  const shortcut = keyLabel('talk');
  return (
    <aside className={'vpanel' + (collapsed ? ' is-collapsed' : '') + (welcome ? '' : ' is-conv') + (resting ? ' is-resting' : '')}
           aria-label="Voice" data-testid="voice-panel">
      <section className="vp-card" aria-label={TALK_LABEL}>
        <div className="vp-top">
          <span className="vp-eyebrow"><i aria-hidden="true" />Voice</span>
          <button type="button" className="vp-x" onClick={() => fold(true)}
                  aria-label="Fold the voice card to the edge" title="Fold to the edge">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="vp-head">
          <AgentOrb size={welcome ? 64 : 48} state={state} onTalk={() => talk()} testId="panel-orb" />
          <div className="vp-title">{welcome ? <>Talk to<br />Megh One AI</> : <>Talk about<br />this answer</>}</div>
        </div>
        <p className="vp-sub">
          {resting ? RESTING_TIP
            : welcome ? 'Ask out loud and hear the answer. Charts and maps appear while it speaks, and you can interrupt at any time.'
              : 'Ask a follow-up out loud: “show it on the map”, “only the Garo Hills”.'}
        </p>
        {welcome && (
          <>
            <div className="vp-try">Try saying</div>
            {PANEL_STARTERS.map((s) => (
              <button type="button" className="vp-q" key={s.q} onClick={() => talk(s.q)}
                      aria-disabled={resting || undefined} title={resting ? RESTING_TIP : 'Opens the voice and asks this'}>
                <span className="vp-qd" style={dotStyle(s.scheme)} aria-hidden="true" />
                <span className="vp-qt">“{s.q}”</span>
              </button>
            ))}
            <button type="button" className="vp-start" onClick={() => talk()} aria-disabled={resting || undefined}
                    aria-haspopup="dialog">
              <span>{resting ? 'Live voice is resting' : 'Start talking'}</span>
              {!resting && shortcut && <kbd>{shortcut}</kbd>}
            </button>
          </>
        )}
        <Foot />
      </section>

      <div className="vp-slim">
        <button type="button" className="vp-rail" onClick={() => talk()} aria-haspopup="dialog" data-testid="voice-rail"
                aria-disabled={resting || undefined} aria-label={resting ? RESTING_TIP : TALK_LABEL}
                title={resting ? RESTING_TIP : 'Talk to Megh One AI: ask out loud, hear the answer'}>
          <AgentOrb size={46} state={state} decorative />
          <span className="vp-vtext">Talk to Megh One AI</span>
          <span className="vp-ai" title={AI_VOICE_LABEL}>AI</span>
        </button>
        <button type="button" className="vp-unfold" onClick={() => fold(false)}
                aria-label="Show the voice card" title="Show the voice card">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
        </button>
      </div>
    </aside>
  );
}

// The welcome hint (main narrower than 1,140 px, phones): one chip under the title. The whole chip opens the voice.
export function TalkHint({ state = 'idle', onTalk }) {
  const resting = state === 'resting';
  return (
    <button type="button" className={'talk-hint' + (resting ? ' is-resting' : '')} onClick={() => { if (onTalk) onTalk(); }}
            aria-haspopup="dialog" aria-disabled={resting || undefined} data-testid="talk-hint">
      <AgentOrb size={26} state={state} decorative />
      <span>{resting ? 'Live voice is resting. The mic still types.' : 'Prefer to talk? Tap the orb beside the send button.'}</span>
    </button>
  );
}
