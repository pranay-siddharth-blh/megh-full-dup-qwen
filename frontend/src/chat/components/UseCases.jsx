import { useEffect, useRef } from 'react';
import { CARD_QUESTIONS, SCHEME_CARDS, USE_CASES } from '../constants.js';
import { isLineEnd, isLowerAlnum, isSpace, replaceRuns, runEnd } from '../text.js';

/* The Use cases popup as an accordion: one card per scheme; opening a card
   shows that scheme's questions beneath it, and only one is open at a time
   (see App.openUseCases). Clicking a question hands it to App's existing
   ask(), the same path as a typed question and Send.

   Groups come from the existing content, never a second list: one per scheme
   in SCHEME_CARDS order (the welcome carousel's order), holding that scheme's
   USE_CASES entries and its CARD_QUESTIONS, without duplicates; then any other
   USE_CASES section, such as Cross-scheme, as its own group. Plain text
   cards in the console's purple; the only icons are the open / ask arrows. */

// 24px line icons, stroke = currentColor.
const P = {
  ask: ['M7 17 17 7', 'M8 7h9v9'],
  chevron: ['m9 6 6 6-6 6'],
};

function Icon({ name, size = 16, stroke = 2 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {P[name].map((d) => <path key={d} d={d} />)}
    </svg>
  );
}

// "Rural employment guarantee · village-year grain · …" -> "Rural employment guarantee"
const shortMeta = (meta) => dropParens(String(meta || '').split(' · ')[0]).trim();

// Every "(...)" on one line, with the spaces around it, becomes one space.
function dropParens(s) {
  let out = '';
  let i = 0;
  while (i < s.length) {
    const open = runEnd(s, i, isSpace);
    if (s[open] === '(') {
      let close = open + 1;
      while (close < s.length && s[close] !== ')' && !isLineEnd(s[close])) close++;
      if (s[close] === ')') {
        out += ' ';
        i = runEnd(s, close + 1, isSpace);
        continue;
      }
    }
    out += s[i++];
  }
  return out;
}

const dedupe = (list) => {
  const seen = new Set();
  return list.filter((q) => {
    const k = q.trim().toLowerCase();
    if (!k || seen.has(k)) return false;
    seen.add(k);
    return true;
  });
};

export function buildUseCaseGroups() {
  const used = new Set();
  const groups = SCHEME_CARDS.map((card) => {
    used.add(card.name);
    const own = USE_CASES[card.name] || [];
    const more = ((CARD_QUESTIONS[card.key] && CARD_QUESTIONS[card.key].items) || []).map((i) => i.text);
    return { key: card.key, name: card.name, desc: shortMeta(card.meta), questions: dedupe([...own, ...more]) };
  });
  Object.entries(USE_CASES).forEach(([section, items]) => {
    if (used.has(section)) return;
    groups.push({
      key: replaceRuns(section.toLowerCase(), (c) => !isLowerAlnum(c), '_'),
      name: section,
      desc: section.toLowerCase().includes('cross') ? 'Questions that combine two schemes' : '',
      questions: dedupe(items),
    });
  });
  return groups.filter((g) => g.questions.length);
}

export const USE_CASE_GROUPS = buildUseCaseGroups();

// Accordion: every scheme is a card; its header toggles the questions open
// beneath it. One scheme is open at a time (`selected`), none when the popup
// opens. Opening one scrolls it into view so its questions are visible.
export function UseCases({ selected, onSelect, onPick }) {
  const rootRef = useRef(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (!selected) { root.focus({ preventScroll: true }); return; }
    const item = root.querySelector(`[data-scheme="${selected}"]`);
    if (!item) return;
    // After the panel has started to open, so the whole item is measured.
    const t = setTimeout(() => item.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 180);
    return () => clearTimeout(t);
  }, [selected]);

  return (
    <div ref={rootRef} tabIndex={-1} className="uc-acc" aria-label="Use cases by scheme">
      {USE_CASE_GROUPS.map((g) => {
        const open = g.key === selected;
        const panelId = `uc-panel-${g.key}`;
        return (
          <div key={g.key} className={'uc-item' + (open ? ' open' : '')} data-scheme={g.key}>
            <h3 className="uc-item-h">
              <button type="button" className="uc-card" aria-expanded={open} aria-controls={panelId}
                      onClick={() => onSelect(open ? null : g.key)}>
                <span className="uc-card-text">
                  <span className="uc-card-name">{g.name}</span>
                  {g.desc && <span className="uc-card-desc">{g.desc}</span>}
                </span>
                <span className="uc-card-side">
                  <span className="uc-count">
                    {g.questions.length}<span className="uc-count-word">{' '}{g.questions.length === 1 ? 'question' : 'questions'}</span>
                  </span>
                  <span className="uc-go"><Icon name="chevron" size={16} stroke={2.4} /></span>
                </span>
              </button>
            </h3>
            <div id={panelId} className="uc-panel" role="region" aria-label={`${g.name} questions`} hidden={!open}>
              <div className="uc-panel-inner">
                <div className="uc-qlist">
                  {g.questions.map((q) => (
                    <button key={q} type="button" className="uc-q" tabIndex={open ? 0 : -1} onClick={() => onPick(q)}>
                      <span className="uc-q-text">{q}</span>
                      <span className="uc-q-ask"><span className="uc-q-ask-label">Ask</span><Icon name="ask" size={14} stroke={2.4} /></span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
