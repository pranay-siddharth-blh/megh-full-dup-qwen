/* What the live voice reads aloud (full-duplex voice, 2026-11-02).

   The voice never writes an answer of its own. Every spoken question is
   answered by the unchanged chat path, and THIS turns that checked answer
   into the words the voice reads, word for word: the answer text with its
   markdown removed, a table read as its first rows, a clarification as its
   question and options. The numbers are never changed or rounded here — a
   long answer is cut only at a sentence end, and what is not read stays on
   the screen. String methods only (no regex, D-046 / D-047). */
import { inlineSpans, isSpace, speechText, unwrapSpans } from './text.js';

// ~20-25 s of speech with Indian figures read in full (measured on the real voice 2026-11-03: 560 characters took
// 45-65 s); the screen carries the rest, a voice agent says the gist
const MAX_SPOKEN = 320;
const TABLE_ROWS = 3;        // a table is read as its first rows
const LIST_ITEMS = 3;        // a list likewise: its first items, then how many more are on screen
const OPTIONS = 6;           // a clarification reads at most this many options

function stripLineMarks(line) {
  let t = line.trimStart();
  while (t.startsWith('#')) t = t.slice(1);
  if (t.startsWith('- ') || t.startsWith('* ') || t.startsWith('• ')) t = t.slice(2);
  return t.trim();
}

// "- x", "* x", "• x" or "12. x": an item of a list
function isListLine(line) {
  const t = line.trimStart();
  if (t.startsWith('- ') || t.startsWith('* ') || t.startsWith('• ')) return true;
  let i = 0;
  while (i < t.length && t[i] >= '0' && t[i] <= '9') i++;
  return i > 0 && i <= 3 && (t[i] === '.' || t[i] === ')') && t[i + 1] === ' ';
}

/* Markdown answer -> plain spoken text: no **, `, #, list marks; a table as its
   header and first rows ("and N more rows are on your screen"). */
// the greeting the voice says when the stage opens (the user, 2026-11-02: "Good morning, Secretary sir", by the hour)
export function partOfDay(d = new Date()) {
  const h = d.getHours();
  return h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening';
}
export const greetingHeading = (d = new Date()) => `Good ${partOfDay(d)}, Secretary sir`;
// 2026-11-14 (guardrail): the voice is synthetic, and says so once when the stage opens, before anything else it
// says (IT Rules amendment Feb 2026: AI-generated audio is labelled; the on-screen label is AI_VOICE_LABEL below)
export const AI_DISCLOSURE = 'I am Megh One AI, an AI voice assistant';
export const AI_VOICE_LABEL = 'AI-generated voice';
export const greetingLine = (d = new Date()) =>
  `${greetingHeading(d)}. ${AI_DISCLOSURE}. What would you like to look at today?`;

export function plainForSpeech(answer) {
  const lines = String(answer || '').split('\n');
  const out = [];
  let tableRows = 0;
  let tableExtra = 0;
  let listItems = 0;
  let listExtra = 0;
  const closeTable = () => {
    if (tableExtra > 0) out.push(`and ${tableExtra} more ${tableExtra === 1 ? 'row is' : 'rows are'} on your screen.`);
    tableRows = 0;
    tableExtra = 0;
  };
  const closeList = () => {
    if (listExtra > 0) out.push(`and ${listExtra} more ${listExtra === 1 ? 'is' : 'are'} on your screen.`);
    listItems = 0;
    listExtra = 0;
  };
  for (const raw of lines) {
    const t = raw.trim();
    if (t.startsWith('|')) {
      const spoken = speechText(t).trim();
      if (!spoken) continue;                       // the |---| rule line
      if (tableRows <= TABLE_ROWS) out.push(spoken);   // the header and the first rows
      else tableExtra += 1;
      tableRows += 1;
      continue;
    }
    closeTable();
    if (isListLine(raw)) {
      if (listItems < LIST_ITEMS) { const s = stripLineMarks(raw); if (s) out.push(s); } else listExtra += 1;
      listItems += 1;
      continue;
    }
    if (!t) continue;                              // a blank line does not end a list
    closeList();
    const s = stripLineMarks(raw);
    if (s) out.push(s);
  }
  closeTable();
  closeList();
  let text = out.join('\n');
  text = unwrapSpans(text, inlineSpans(text));
  text = unwrapSpans(text, inlineSpans(text, { bold: false, code: true }));
  return sayApproxOnce(text).split('≈').join('about ').split('  ').join(' ').trim();
}

/* "₹22,22,75,30,000 (≈ ₹2,222.75 crore)" -> "about ₹2,222.75 crore": the brain's own approximation is said once,
   the exact figure stays on the screen (an exact rupee figure read in full takes ten seconds). Only when the text
   before the bracket is a figure; anything else keeps its bracket (and its ≈ is said "about"). */
export function sayApproxOnce(text) {
  let s = String(text || '');
  let from = 0;
  for (;;) {
    const open = s.indexOf('(≈', from);
    if (open < 0) return s;
    const close = s.indexOf(')', open);
    if (close < 0) return s;
    let end = open;
    while (end > 0 && isSpace(s[end - 1])) end -= 1;
    let start = end;
    while (start > 0 && !isSpace(s[start - 1]) && s[start - 1] !== '(') start -= 1;
    const figure = s.slice(start, end);
    const isFigure = figure.length > 0 && Array.from(figure).some((c) => c >= '0' && c <= '9')
      && Array.from(figure).every((c) => (c >= '0' && c <= '9') || c === ',' || c === '.' || c === '₹');
    if (!isFigure) { from = close + 1; continue; }
    const approx = s.slice(open + 2, close).trim();
    s = s.slice(0, start) + 'about ' + approx + s.slice(close + 1);
    from = start + 6 + approx.length;
  }
}

/* Cut at a sentence end at or before `max` characters; never inside a number. */
export function cutAtSentence(text, max = MAX_SPOKEN) {
  const t = String(text || '').trim();
  if (t.length <= max) return { text: t, cut: false };
  let cut = -1;
  for (let i = max; i > max / 3; i--) {
    const c = t[i - 1];
    if ((c === '.' || c === '?' || c === '!' || c === '\n') && (i >= t.length || isSpace(t[i]))) { cut = i; break; }
  }
  if (cut < 0) {
    for (let i = max; i > max / 3; i--) { if (isSpace(t[i])) { cut = i; break; } }
  }
  if (cut < 0) cut = max;
  return { text: t.slice(0, cut).trim(), cut: true };
}

function optionLabels(response) {
  const c = (response && response.clarification) || {};
  const opts = Array.isArray(c.options) ? c.options : [];
  return opts.map((o) => String((o && (o.label || o.question)) || '').trim()).filter((x) => x.length > 0);
}

function joinOr(items) {
  if (items.length <= 1) return items.join('');
  return items.slice(0, -1).join(', ') + ' or ' + items[items.length - 1];
}

/* The chat's note under a local redraw ("Here is the same data as a bar chart. (Drawn here from the answer above; it is
   not saved with the chat.)") stays on screen; the voice never reads the bracket (2026-11-11). */
export function dropRedrawNote(text) {
  const s = String(text || '');
  const at = s.indexOf('(Drawn here from');
  if (at < 0) return s;
  const close = s.indexOf(')', at);
  return (s.slice(0, at).trimEnd() + (close < 0 ? '' : ' ' + s.slice(close + 1).trimStart())).trim();
}

/* The /api/query result -> what the voice gets back from ask_megh. */
export function spokenForm(response) {
  const r = response || {};
  const route = String(r.route || '').toLowerCase();
  if (route === 'clarification' || r.intent === 'CLARIFY' || r.needs_clarification) {
    const q = plainForSpeech(r.question || r.answer || 'Which one do you mean?');
    const labels = optionLabels(r);
    let speak = q;
    if (labels.length) {
      const shown = labels.slice(0, OPTIONS);
      speak += ` The options are ${joinOr(shown)}.`;
      if (labels.length > OPTIONS) speak += ` There are ${labels.length - OPTIONS} more on your screen.`;
    }
    return { speak, kind: 'clarification', read_exactly: true, on_screen: true };
  }
  const plain = plainForSpeech(dropRedrawNote(r.answer || ''));
  if (!plain) {
    return { speak: 'The answer is on your screen.', kind: route || 'answer', read_exactly: true, on_screen: true };
  }
  const { text, cut } = cutAtSentence(plain);
  return {
    speak: cut ? `${text} The rest of the answer is on your screen.` : text,
    kind: route || 'answer',
    read_exactly: true,
    on_screen: true,
  };
}

/* A plain chat note (Stopped, an error, a view redraw) -> the same shape. */
export function spokenNote(text) {
  const { text: t, cut } = cutAtSentence(plainForSpeech(dropRedrawNote(text)));
  return { speak: cut ? `${t} The rest is on your screen.` : (t || 'Done.'), kind: 'note', read_exactly: true, on_screen: true };
}
