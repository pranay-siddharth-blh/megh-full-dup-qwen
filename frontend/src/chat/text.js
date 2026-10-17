/* Plain-string text helpers for the UI.

   Project rule (D-047): no regular expressions anywhere in the codebase. These
   loops and string methods do what the UI's old patterns did, with the same
   JavaScript meanings: "space" is what \s matched (exactly the characters
   String.prototype.trim removes), a digit is ASCII 0-9 (\d), a word character
   is ASCII A-Z / a-z / 0-9 / _ (\w), and a line terminator is what "." refused
   to match (\n, \r, U+2028, U+2029). */

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

/** Does the '_'-separated name hold one of `words` as a whole segment, any case? */
export const hasSegment = (name, words) => String(name).toLowerCase().split('_').some((w) => words.includes(w));

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
