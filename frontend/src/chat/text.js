/* Plain-string text helpers for the UI.

   Project rule (D-047): text is handled with loops and string methods only.
   "Space" is exactly the characters String.prototype.trim removes, a digit is
   ASCII 0-9, a word character is ASCII A-Z / a-z / 0-9 / _, and a line
   terminator is newline, carriage return, U+2028 or U+2029. */

export const isSpace = (c) => typeof c === 'string' && c.length === 1 && c.trim() === '';
export const isDigit = (c) => typeof c === 'string' && c.length === 1 && c >= '0' && c <= '9';
export const isAsciiLetter = (c) => typeof c === 'string' && c.length === 1
  && ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'));
export const isWordChar = (c) => isAsciiLetter(c) || isDigit(c) || c === '_';
export const isLowerAlnum = (c) => isDigit(c) || (typeof c === 'string' && c.length === 1 && c >= 'a' && c <= 'z');
export const isLineEnd = (c) => c === '\n' || c === '\r' || c === ' ' || c === ' ';

/** Index just past the run of characters from `i` that satisfy `pred`. */
export function runEnd(s, i, pred) {
  let j = i;
  while (j < s.length && pred(s[j])) j++;
  return j;
}

/** s split at every run of characters that satisfy `pred`: a leading or
    trailing run gives an empty first / last piece, as split did. */
export function splitRuns(s, pred) {
  const out = [];
  let start = 0;
  let i = 0;
  while (i < s.length) {
    if (pred(s[i])) {
      const j = runEnd(s, i, pred);
      out.push(s.slice(start, i));
      start = j;
      i = j;
    } else i++;
  }
  out.push(s.slice(start));
  return out;
}

/** s split at every run of spaces. */
export const splitSpaces = (s) => splitRuns(s, isSpace);

/** Every run of characters that satisfy `pred` replaced by one `rep`. */
export function replaceRuns(s, pred, rep) {
  let out = '';
  let i = 0;
  while (i < s.length) {
    if (pred(s[i])) {
      out += rep;
      i = runEnd(s, i, pred);
    } else out += s[i++];
  }
  return out;
}

/** Number of runs of non-space characters. */
export function countWords(s) {
  let n = 0;
  let i = 0;
  while (i < s.length) {
    if (isSpace(s[i])) i++;
    else { n++; i = runEnd(s, i, (c) => !isSpace(c)); }
  }
  return n;
}

/** Every occurrence of `find` (any case) replaced by `rep`, left to right. */
export function replaceAllCI(s, find, rep) {
  const f = find.toLowerCase();
  let out = '';
  let i = 0;
  while (i < s.length) {
    if (s.slice(i, i + f.length).toLowerCase() === f) { out += rep; i += f.length; } else out += s[i++];
  }
  return out;
}

/** s without one leading `prefix` (any case). */
export const dropPrefixCI = (s, prefix) => (s.slice(0, prefix.length).toLowerCase() === prefix.toLowerCase()
  ? s.slice(prefix.length) : s);

/** The first letter of every word upper-cased (a word char after a non-word char). */
export function capitalizeWords(s) {
  let out = '';
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    out += isWordChar(c) && !isWordChar(s[i - 1]) ? c.toUpperCase() : c;
  }
  return out;
}

/** A plain number: an optional '-', digits, then groups of `lo`..`hi` digits
    after commas, then an
    optional fraction: a '.' and at least one digit. */
export function isPlainNumber(s, lo = 3, hi = 3) {
  let t = s.startsWith('-') ? s.slice(1) : s;
  const dot = t.indexOf('.');
  if (dot !== -1) {
    const frac = t.slice(dot + 1);
    if (!frac.length || runEnd(frac, 0, isDigit) !== frac.length) return false;
    t = t.slice(0, dot);
  }
  const groups = t.split(',');
  if (!groups[0].length || runEnd(groups[0], 0, isDigit) !== groups[0].length) return false;
  return groups.slice(1).every((g) => g.length >= lo && g.length <= hi && runEnd(g, 0, isDigit) === g.length);
}

/* Key figures in an answer (#265): the numbers an officer is looking for, so
   the UI can bold them. A figure is a standalone number ("1,23,456", "12.5",
   "1.2"), with any currency mark before it ("₹", "Rs.", "Rs", "INR") and a "%"
   or a scale word after it ("1.2 lakh", "3 crore", "45%"). Not a figure: a
   year ("2025", "2025-26"), anything glued to letters or to - / : . , (dates,
   times, codes like PMAY-G 2.0), or a number inside a longer token. Spans never
   overlap and are returned left to right: [{ start, end }]. */
const SCALE_WORDS = ['lakh', 'lakhs', 'crore', 'crores', 'cr', 'thousand', 'million', 'billion', 'mn', 'bn'];
const CURRENCY_WORDS = ['Rs.', 'Rs', 'INR'];
const FIG_OPENERS = '([{"\'“‘~≈';
const FIG_GLUE = '-/:.,_';

const figureLeftOk = (text, p) => p === 0 || isSpace(text[p - 1]) || FIG_OPENERS.includes(text[p - 1]);

// The digits, commas and one decimal point from `p`: the index just past them.
function numberEnd(text, p) {
  let q = runEnd(text, p, isDigit);
  while ((text[q] === ',' || text[q] === '.') && isDigit(text[q + 1])) q = runEnd(text, q + 1, isDigit);
  return q;
}

const isYear = (num) => num.length === 4 && runEnd(num, 0, isDigit) === 4 && Number(num) >= 1900 && Number(num) <= 2100;

// Comma groups the Indian ("1,23,456") or Western ("1,234,567") way: the last
// group has 3 digits, the earlier ones 2 or 3. "12,34" is not a number.
function groupedOk(num) {
  const intPart = num.split('.')[0];
  const groups = intPart.split(',');
  if (groups.length === 1) return true;
  if (groups[groups.length - 1].length !== 3) return false;
  return groups.slice(1, -1).every((g) => g.length === 2 || g.length === 3);
}

export function figureSpans(text) {
  const out = [];
  let p = 0;
  while (p < text.length) {
    if (!figureLeftOk(text, p)) { p++; continue; }
    // Optional currency mark, then at most one space, then the number.
    let numStart = p;
    let hasCurrency = false;
    if (text[p] === '₹') { numStart = p + 1; hasCurrency = true; }
    else {
      const w = CURRENCY_WORDS.find((c) => text.startsWith(c, p));
      if (w) { numStart = p + w.length; hasCurrency = true; }
    }
    if (hasCurrency && isSpace(text[numStart])) numStart++;
    if (!isDigit(text[numStart])) { p++; continue; }
    const numEnd = numberEnd(text, numStart);
    const num = text.slice(numStart, numEnd);
    const after = text[numEnd];
    if ((after !== undefined && (isWordChar(after) || FIG_GLUE.includes(after))) || !isPlainNumber(num, 2, 3) || !groupedOk(num) || (!hasCurrency && isYear(num))) {
      p = numEnd;                              // not a figure: skip past the whole token
      continue;
    }
    let end = numEnd;
    if (text[end] === '%') end++;
    else {
      // "1.2 lakh": one space, a scale word, then a non-word character or the end.
      const wStart = isSpace(text[end]) ? end + 1 : end;
      const wEnd = runEnd(text, wStart, isAsciiLetter);
      const word = text.slice(wStart, wEnd).toLowerCase();
      if (wEnd > wStart && SCALE_WORDS.includes(word) && !isWordChar(text[wEnd])) end = wEnd;
    }
    out.push({ start: p, end });
    p = end;
  }
  return out;
}

/** Does the '_'-separated name hold one of `words` as a whole segment, any case? */
export const hasSegment = (name, words) => String(name).toLowerCase().split('_').some((w) => words.includes(w));

/* A label that names a period: "2024", "FY 2024", "2023-24", "FY2023 - 2024",
   "2024-03" or "2024-03-15" (any case). Charts put such labels on the x-axis and
   read a line left-to-right as a trend; anything else is a category. */
export function isPeriodLabel(label) {
  let s = String(label ?? '').trim();
  if (s.slice(0, 2).toLowerCase() === 'fy') s = s.slice(runEnd(s, 2, isSpace));
  if (runEnd(s, 0, isDigit) !== 4) return false;
  if (s.length === 4) return true;
  let i = runEnd(s, 4, isSpace);
  if (s[i] !== '-') return false;
  i = runEnd(s, i + 1, isSpace);
  const tail = s.length - i;
  if (tail >= 2 && tail <= 4 && runEnd(s, i, isDigit) === s.length) return true;   // 2023-24, 2023-2024
  // ISO month / date: 2024-03, 2024-03-15
  return (s.length === 7 || s.length === 10)
    && Array.from(s).every((c, k) => ((k === 4 || k === 7) ? c === '-' : isDigit(c)));
}

/** Scan for **bold** spans and, with `code`, for `code` spans (left to right,
    bold tried first at each position):
    [{ start, end, inner, code }]. Bold text is at least one character and never
    crosses a line end; code text is at least one character. */
export function inlineSpans(text, { bold = true, code = false } = {}) {
  const out = [];
  let p = 0;
  while (p < text.length) {
    if (bold && text.startsWith('**', p)) {
      const q = text.indexOf('**', p + 3);
      if (q !== -1 && !Array.from(text.slice(p + 2, q)).some(isLineEnd)) {
        out.push({ start: p, end: q + 2, inner: text.slice(p + 2, q), code: false });
        p = q + 2;
        continue;
      }
    }
    if (code && text[p] === '`') {
      const q = text.indexOf('`', p + 1);
      if (q > p + 1) {
        out.push({ start: p, end: q + 1, inner: text.slice(p + 1, q), code: true });
        p = q + 1;
        continue;
      }
    }
    p++;
  }
  return out;
}

/** Each span from inlineSpans replaced by its inner text. */
export function unwrapSpans(text, spans) {
  let out = '';
  let last = 0;
  for (const s of spans) { out += text.slice(last, s.start) + s.inner; last = s.end; }
  return out + text.slice(last);
}
