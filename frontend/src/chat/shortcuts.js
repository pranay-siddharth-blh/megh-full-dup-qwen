/* Keyboard shortcuts: ONE table read by both the key handler (App.jsx) and
   the help window (Ctrl + /), so the two can never disagree.

   Rules:
   - The browser's own keys are never taken: Ctrl + N / T / W / R / L and
     Ctrl + Shift + R (hard reload) stay the browser's. Our shortcuts use
     Ctrl + Shift + letter where a plain Ctrl + letter is the browser's.
   - "mod" is Ctrl on Windows / Linux and ⌘ on a Mac.
   - `whileTyping: false` shortcuts never fire while the cursor is in a text
     box (plain keys like "/" would otherwise eat a typed character).
   - Nothing destructive (delete a chat) has a shortcut. */

export const IS_MAC = typeof navigator !== 'undefined'
  && /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '');

// key: the KeyboardEvent.key, lower-cased for letters.
export const SHORTCUTS = [
  { id: 'newChat', mod: true, shift: true, key: 'o', label: 'New chat', whileTyping: true },
  { id: 'search', mod: true, key: 'k', label: 'Search chat history', whileTyping: true },
  { id: 'focus', shift: true, key: 'Escape', label: 'Jump to the question box', whileTyping: true },
  { id: 'focusSlash', key: '/', label: 'Jump to the question box', whileTyping: false, hidden: true },
  { id: 'stop', key: 'Escape', label: 'Stop the answer being written', whileTyping: true },
  { id: 'editLast', key: 'ArrowUp', label: 'Edit your last question (question box empty)', whileTyping: true },
  { id: 'copyLast', mod: true, shift: true, key: 'c', label: 'Copy the last answer', whileTyping: true },
  { id: 'regenerate', mod: true, shift: true, key: 'g', label: 'Regenerate the last answer', whileTyping: true },
  { id: 'download', mod: true, shift: true, key: 'd', label: 'Download chat (PDF / Excel)', whileTyping: true },
  { id: 'mic', mod: true, key: 'm', label: 'Start / stop voice input', whileTyping: true },
  { id: 'sidebar', mod: true, key: 'b', label: 'Show / hide the sidebar', whileTyping: false },
  { id: 'help', mod: true, key: '/', label: 'Show keyboard shortcuts', whileTyping: true },
];
// Shown in the help window but handled by the question box itself.
export const TYPING_KEYS = [
  { keys: ['Enter'], label: 'Send the question' },
  { keys: ['Shift', 'Enter'], label: 'New line in the question' },
];

const NAMES = { Escape: 'Esc', ArrowUp: '↑', '/': '/' };

// The keys of a shortcut as display labels: ["Ctrl", "Shift", "O"] / ["⌘", "⇧", "O"].
export function keyParts(sc) {
  const parts = [];
  if (sc.mod) parts.push(IS_MAC ? '⌘' : 'Ctrl');
  if (sc.shift) parts.push(IS_MAC ? '⇧' : 'Shift');
  if (sc.alt) parts.push(IS_MAC ? '⌥' : 'Alt');
  parts.push(NAMES[sc.key] || (sc.key.length === 1 ? sc.key.toUpperCase() : sc.key));
  return parts;
}
export const keyLabel = (idOrSc) => {
  const sc = typeof idOrSc === 'string' ? SHORTCUTS.find((s) => s.id === idOrSc) : idOrSc;
  return sc ? keyParts(sc).join(IS_MAC ? '' : '+') : '';
};

// Does this keydown event match the shortcut?
export function matches(e, sc) {
  const mod = IS_MAC ? e.metaKey : e.ctrlKey;
  if (!!sc.mod !== mod) return false;
  if (!!sc.shift !== e.shiftKey) return false;
  if (!!sc.alt !== e.altKey) return false;
  if (!sc.mod && (e.ctrlKey || e.metaKey)) return false;
  const k = e.key && e.key.length === 1 ? e.key.toLowerCase() : e.key;
  // Ctrl + / arrives as "/" (or "?" with Shift on some layouts); letters may
  // arrive upper-cased with Shift held.
  return k === sc.key || (sc.key.length === 1 && e.code === `Key${sc.key.toUpperCase()}`);
}

export const isTyping = (target) => !!target && (/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable);
