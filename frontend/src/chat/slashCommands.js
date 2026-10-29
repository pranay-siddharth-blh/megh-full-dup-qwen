import { LANGS } from './constants.js';
import { isSpace, runEnd } from './text.js';

/* Slash commands in the composer (#319). A question that starts with "/chart"
   or "/table" is asked as usual, and its answer shows the charts without their
   table, or the table alone. "/glossary [term]" opens the glossary (filtered
   to the term). "/lang <en|kha|gar>" switches the question language. The text is
   read with string methods only (project rule D-047). */
export const SLASH_COMMANDS = [
  { cmd: 'chart', desc: 'Answer as a chart', hint: 'your question' },
  { cmd: 'table', desc: 'Answer as a table', hint: 'your question' },
  { cmd: 'glossary', desc: 'Define a term', hint: 'term (optional)' },
  { cmd: 'lang', desc: 'Switch language', hint: 'en · kha · gar' },
];
const VIEW_COMMANDS = ['chart', 'table'];

/** "/chart job cards by district" -> { cmd: 'chart', rest: 'job cards by district',
    complete: true }. `complete` is true once a space follows the command, so
    the menu knows the command itself is no longer being typed. null when the
    text does not start with "/" or the command holds a space. */
export function parseSlash(text) {
  const t = String(text || '');
  const lead = runEnd(t, 0, isSpace);
  if (t[lead] !== '/') return null;
  const end = runEnd(t, lead + 1, (c) => !isSpace(c));
  const cmd = t.slice(lead + 1, end).toLowerCase();
  return { cmd, rest: t.slice(end).trim(), complete: end < t.length };
}

/** The view a question asks for: 'chart' | 'table' | null, and the question
    without the command. A view command with nothing after it asks nothing. */
export function viewRequest(text) {
  const p = parseSlash(text);
  if (!p || !VIEW_COMMANDS.includes(p.cmd) || !p.rest) return { view: null, question: text };
  return { view: p.cmd, question: p.rest };
}

/** The language a "/lang" argument names: "en", "kha", "gar", "English",
    "Khasi", "Garo" (any case) -> its code, or null. */
export function langFromArg(arg) {
  const a = String(arg || '').trim().toLowerCase();
  if (!a) return null;
  const hit = LANGS.find((l) => l.code === a || l.label.toLowerCase() === a || l.name.toLowerCase() === a);
  return hit ? hit.code : null;
}

/** What the menu lists for the text in the box: while the command is being
    typed, the commands it could be; after "/lang ", the languages. Each item:
    { key, label, desc, hint, apply: { cmd } | { lang } }. Empty when the menu
    should not show. */
export function slashMenuItems(text) {
  const p = parseSlash(text);
  if (!p) return [];
  if (!p.complete) {
    return SLASH_COMMANDS
      .filter((c) => c.cmd.startsWith(p.cmd))
      .map((c) => ({ key: c.cmd, label: '/' + c.cmd, desc: c.desc, hint: c.hint, apply: { cmd: c.cmd } }));
  }
  if (p.cmd === 'lang') {
    const arg = p.rest.toLowerCase();
    return LANGS
      .filter((l) => !arg || l.code.startsWith(arg) || l.name.toLowerCase().startsWith(arg))
      .map((l) => ({ key: 'lang-' + l.code, label: '/lang ' + l.code, desc: l.name, hint: '', apply: { lang: l.code } }));
  }
  return [];
}
