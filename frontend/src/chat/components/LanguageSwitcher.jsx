import { useEffect, useRef, useState } from 'react';
import { LANGS } from '../constants.js';

// Language switcher (#235): a dropdown that shows the chosen language's full
// name ("Khasi") and lists every language as code + name, with a tick on the
// current one. Replaces the EN / KHA / GAR tabs. Closes on a click outside,
// Esc, or a choice. Arrow keys move through the list; Enter or Space choose.
const GLOBE = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 010 18" /><path d="M12 3a14 14 0 000 18" />
  </svg>
);
const CHEVRON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <polyline points="6 9 12 15 18 9" />
  </svg>
);
const CHECK = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);

export function LanguageSwitcher({ lang, onChange }) {
  const [open, setOpen] = useState(false);
  const [focusIdx, setFocusIdx] = useState(-1);
  const ref = useRef(null);
  const btnRef = useRef(null);
  const current = LANGS.find((l) => l.code === lang) || LANGS[0];

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); if (btnRef.current) btnRef.current.focus(); }
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('touchstart', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('touchstart', onDown);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  // Focus follows the arrow keys while the list is open.
  useEffect(() => {
    if (!open || focusIdx < 0 || !ref.current) return;
    const el = ref.current.querySelectorAll('.lang-opt')[focusIdx];
    if (el) el.focus();
  }, [open, focusIdx]);

  const idxOf = (code) => Math.max(0, LANGS.findIndex((l) => l.code === code));
  const openAt = (idx) => { setOpen(true); setFocusIdx(idx); };
  const choose = (code) => { onChange(code); setOpen(false); if (btnRef.current) btnRef.current.focus(); };

  const onButtonKey = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      openAt(e.key === 'ArrowDown' ? idxOf(current.code) : LANGS.length - 1);
    }
  };
  const onListKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setFocusIdx((i) => (i + 1) % LANGS.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setFocusIdx((i) => (i - 1 + LANGS.length) % LANGS.length); }
    else if (e.key === 'Home') { e.preventDefault(); setFocusIdx(0); }
    else if (e.key === 'End') { e.preventDefault(); setFocusIdx(LANGS.length - 1); }
    else if (e.key === 'Tab') { setOpen(false); }
  };

  return (
    <div className={'lang-switch' + (open ? ' open' : '')} ref={ref}>
      <button type="button" className="lang-switch-btn" ref={btnRef}
              aria-haspopup="listbox" aria-expanded={open} aria-label={`Answer language: ${current.name}`}
              title="Answer language" data-lang={current.code}
              onClick={() => (open ? setOpen(false) : openAt(idxOf(current.code)))}
              onKeyDown={onButtonKey}>
        <span className="ls-globe">{GLOBE}</span>
        <span className="ls-name">{current.name}</span>
        <span className="ls-code" aria-hidden="true">{current.label}</span>
        <span className="ls-chev">{CHEVRON}</span>
      </button>
      {open && (
        <ul className="lang-menu" role="listbox" aria-label="Answer language" onKeyDown={onListKey}>
          {LANGS.map((l, i) => {
            const selected = l.code === current.code;
            return (
              <li key={l.code} role="option" aria-selected={selected} tabIndex={i === focusIdx ? 0 : -1}
                  className={'lang-opt' + (selected ? ' selected' : '')} data-lang={l.code}
                  onClick={() => choose(l.code)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); choose(l.code); } }}
                  onMouseMove={() => { if (focusIdx !== i) setFocusIdx(i); }}>
                <span className="lo-code">{l.label}</span>
                <span className="lo-name">{l.name}</span>
                {selected && <span className="lo-check">{CHECK}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
