/* Where dictated words go in the prompt box (D-111, 2026-11-15). Pure; no regex (D-046/D-047).

   The selection when the mic was pressed is remembered (begin): the words replace that selection, or go at
   the caret. While speaking, the live words (stable + tentative) sit between what was before the caret
   (prefix) and what was after it (suffix); the final words replace them. Spacing and capitals follow the
   text around them:
     - a space is added between the words and the text on either side when there is none
       (never before a comma or a full stop);
     - at the start of the box or of a sentence the first letter is a capital; in the middle of a sentence
       the speech model's sentence capital is taken off ("show me the" + "Houses in Ri Bhoi" ->
       "show me the houses in Ri Bhoi"), names keep theirs;
     - a full stop the model put at the end is dropped when the words go into the middle of a sentence.
   Cancel puts back the text and the selection exactly as they were. */

const SENTENCE_END = '.?!';
const NO_SPACE_BEFORE = ',.?!;:)]}';
// words that keep their capital in the middle of a sentence (schemes, places, the state; "I")
const NAME_WORDS = new Set(['I', 'Ri', 'Bhoi', 'East', 'West', 'North', 'South', 'Eastern', 'Khasi', 'Garo',
  'Jaintia', 'Hills', 'Focus', 'Plus', 'Legacy', 'Elevate', 'Homestay', 'Meghalaya', 'Megh', 'Shillong',
  'Tura', 'Jowai', 'Nongpoh', 'Nongstoin', 'Mawkyrwat', 'Williamnagar', 'Resubelpara', 'Ampati', 'Baghmara',
  'Khliehriat', 'Mairang', 'Chief', 'Minister', 'January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December']);

const isSpace = (ch) => ch === ' ' || ch === '\n' || ch === '\t' || ch === '\r';
const isLetter = (ch) => !!ch && ch.toLowerCase() !== ch.toUpperCase();

export function begin(value, selStart, selEnd) {
  const v = String(value || '');
  const a = Math.max(0, Math.min(v.length, selStart == null ? v.length : selStart));
  const b = Math.max(a, Math.min(v.length, selEnd == null ? a : selEnd));
  return { original: v, selStart: a, selEnd: b, prefix: v.slice(0, a), suffix: v.slice(b) };
}

function lastNonSpace(s) {
  for (let i = s.length - 1; i >= 0; i--) if (!isSpace(s[i])) return s[i];
  return '';
}

function firstNonSpace(s) {
  for (let i = 0; i < s.length; i++) if (!isSpace(s[i])) return s[i];
  return '';
}

export function atSentenceStart(prefix) {
  const ch = lastNonSpace(prefix);
  return ch === '' || SENTENCE_END.includes(ch);
}

function firstWord(s) {
  let i = 0;
  while (i < s.length && !isSpace(s[i])) i++;
  return s.slice(0, i);
}

function lowerable(word) {
  let core = word;
  while (core && !isLetter(core[core.length - 1])) core = core.slice(0, -1);
  if (core.length < 2 || NAME_WORDS.has(core)) return false;
  if (core[0] !== core[0].toUpperCase() || !isLetter(core[0])) return false;
  const rest = core.slice(1);
  if (rest !== rest.toLowerCase()) return false;       // "PMAY-G", "MGNREGA", "CMSS" keep theirs
  for (const ch of rest) if (!isLetter(ch) && ch !== '\'' && ch !== '’') return false;
  return true;
}

/* The live words shaped for where they go. */
export function shape(live, prefix, suffix) {
  let t = String(live || '').trim();
  if (!t) return '';
  if (atSentenceStart(prefix)) {
    if (isLetter(t[0])) t = t[0].toUpperCase() + t.slice(1);
  } else if (lowerable(firstWord(t))) {
    t = t[0].toLowerCase() + t.slice(1);
  }
  const next = firstNonSpace(suffix);
  if (next && (isLetter(next) || (next >= '0' && next <= '9')) && t.endsWith('.') && !t.endsWith('..')) {
    t = t.slice(0, -1);
  }
  return t;
}

/* The box's text with the live words in place, and where they are:
   {value, start, stableEnd, end}: [start, stableEnd) is stable, [stableEnd, end) tentative. */
export function compose(ctx, stable, tentative) {
  const st = String(stable || '').trim();
  const te = String(tentative || '').trim();
  const joined = st && te ? st + ' ' + te : st || te;
  const live = shape(joined, ctx.prefix, ctx.suffix);
  const { prefix, suffix } = ctx;
  if (!live) return { value: ctx.original, start: ctx.selStart, stableEnd: ctx.selStart, end: ctx.selStart };
  const before = prefix && !isSpace(prefix[prefix.length - 1]) && !NO_SPACE_BEFORE.includes(live[0]) ? ' ' : '';
  const after = suffix && !isSpace(suffix[0]) && !NO_SPACE_BEFORE.includes(suffix[0]) ? ' ' : '';
  const start = prefix.length + before.length;
  const stableLen = st ? Math.min(live.length, st.length) : 0;
  return {
    value: prefix + before + live + after + suffix,
    start,
    stableEnd: start + stableLen,
    end: start + live.length,
  };
}

/* The text and selection to restore on cancel. */
export function restore(ctx) {
  return { value: ctx.original, selStart: ctx.selStart, selEnd: ctx.selEnd };
}
