/* Keyboard shortcuts: ONE table read by both the key handler (App.jsx) and
   the help window (Ctrl + /), so the two can never disagree.

   Rules:
   - The browser's own keys are never taken: Ctrl + N / T / W / R / L and
     Ctrl + Shift + R (hard reload) stay the browser's. Our shortcuts use
     Ctrl + Shift + letter where a plain Ctrl + letter is the browser's.
   - "mod" is Ctrl on Windows / Linux and ⌘ on a Mac. `macCtrl` keeps the
     Control key on a Mac where ⌘ + key belongs to macOS itself (⌘M minimises
     the window and no page can take it).
   - `whileTyping: false` shortcuts never fire while the cursor is in a text
     box (plain keys like "/" would otherwise eat a typed character).
   - Nothing destructive (delete a chat) has a shortcut. */

// Apple keyboard? Any of the three platform signals may be blank or frozen
// (platform is deprecated; userAgentData is Chromium-only), so all are read.
export const IS_MAC = typeof navigator !== 'undefined'
  && ['mac', 'iphone', 'ipad', 'ipod'].some((w) => [
    navigator.userAgentData && navigator.userAgentData.platform, navigator.platform, navigator.userAgent,
  ].some((v) => String(v || '').toLowerCase().includes(w)));

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
  { id: 'mic', mod: true, macCtrl: true, key: 'm', label: 'Start / stop voice input', whileTyping: true },
  // D-113 (2026-11-15): the agent orb. Alt + V, not Ctrl + Shift + Space (Windows switches the keyboard layout with
  // it); on a Mac, where Option + V types a character, it is matched by e.code
  { id: 'talk', alt: true, key: 'v', label: 'Talk to Megh One AI (live voice)', whileTyping: true },
  // Works in the question box too: a plain text box has no bold, and the cursor
  // lives there nearly all the time.
  { id: 'sidebar', mod: true, key: 'b', label: 'Show / hide the sidebar', whileTyping: true },
  { id: 'help', mod: true, key: '/', label: 'Show keyboard shortcuts', whileTyping: true },
];
// Keys the browser or the OS keeps (never to be taken by SHORTCUTS; tests/shortcuts.test.js checks it): new window /
// tab, close, reload, address bar, the browser's Alt menus, history back / forward, Windows' layout switch.
export const RESERVED_KEYS = [
  { mod: true, key: 'n' }, { mod: true, key: 't' }, { mod: true, key: 'w' }, { mod: true, key: 'r' }, { mod: true, key: 'l' },
  { mod: true, shift: true, key: 'r' }, { mod: true, shift: true, key: 'n' }, { mod: true, shift: true, key: 't' },
  { mod: true, shift: true, key: ' ' }, { alt: true, key: 'f' }, { alt: true, key: 'e' }, { alt: true, key: 'd' },
  { alt: true, key: 'ArrowLeft' }, { alt: true, key: 'ArrowRight' }, { alt: true, key: 'Home' },
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
  if (sc.mod) parts.push(IS_MAC ? (sc.macCtrl ? '⌃' : '⌘') : 'Ctrl');
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
  const mod = !IS_MAC ? e.ctrlKey : (sc.macCtrl ? e.ctrlKey && !e.metaKey : e.metaKey);
  if (!!sc.mod !== mod) return false;
  if (!!sc.shift !== e.shiftKey) return false;
  if (!!sc.alt !== e.altKey) return false;
  if (!sc.mod && (e.ctrlKey || e.metaKey)) return false;
  const k = e.key && e.key.length === 1 ? e.key.toLowerCase() : e.key;
  // Ctrl + / arrives as "/" (or "?" with Shift on some layouts); letters may
  // arrive upper-cased with Shift held.
  return k === sc.key || (sc.key.length === 1 && e.code === `Key${sc.key.toUpperCase()}`);
}

export const isTyping = (target) => !!target && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable);

// Enter that only confirms a word in an input method (Hindi, Bengali, Chinese,
// Japanese … keyboards on every OS) must never send the question.
export const isComposing = (e) => !!((e.nativeEvent || e).isComposing || e.keyCode === 229);

// A touch-only device (phone, tablet without a keyboard and trackpad): its
// on-screen keyboard has no Shift + Enter, so Enter makes a new line there and
// the Send button sends — the way the ChatGPT and Claude apps behave. Read at
// key time, so plugging a keyboard into a tablet switches it at once.
const touchOnly = () => typeof window !== 'undefined' && !!window.matchMedia
  && window.matchMedia('(hover: none) and (pointer: coarse)').matches;

// Does this keydown in a question box mean "send"?
export const enterSends = (e) => e.key === 'Enter' && !e.shiftKey && !isComposing(e) && !touchOnly();
