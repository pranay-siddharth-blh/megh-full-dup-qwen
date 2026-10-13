import { SHORTCUTS, TYPING_KEYS, keyParts } from '../shortcuts.js';

/* The Ctrl + / help window: every shortcut from the same table the key
   handler uses, with Mac / Windows key names. */
const Keys = ({ parts }) => (
  <span className="kbd-keys">
    {parts.map((p, i) => <kbd key={i}>{p}</kbd>)}
  </span>
);

export function ShortcutsHelp() {
  const rows = [
    ...SHORTCUTS.filter((s) => !s.hidden).map((s) => ({ label: s.label, parts: keyParts(s) })),
    ...TYPING_KEYS.map((t) => ({ label: t.label, parts: t.keys })),
  ];
  return (
    <div className="kbd-list" role="list">
      {rows.map((r) => (
        <div className="kbd-row" role="listitem" key={r.label}>
          <span className="kbd-label">{r.label}</span>
          <Keys parts={r.parts} />
        </div>
      ))}
      <div className="kbd-note">Tip: press <kbd>/</kbd> anywhere to jump to the question box.</div>
    </div>
  );
}
