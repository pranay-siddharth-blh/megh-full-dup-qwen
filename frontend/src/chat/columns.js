/* What each result column IS, decided once for the charts and the tables
   (user report 2026-10-28: "How have MGNREGA person-days changed over the last
   three years?" drew a 3×3 grid of dashes — year_key and financial_year read as
   two dimensions — with raw cells beside formatted totals and database names as
   headers). Presentation only: the rows themselves, and the Excel download, are
   never changed. Read on words and characters, no regex (D-047). */

import { hasSegment, isPeriodLabel, isPlainNumber, splitSpaces, isAsciiLetter, isDigit } from './text.js';

// A column is a MEASURE only if every value is a plain number. parseFloat() is
// too lenient: parseFloat("2017-08-01") === 2017 would chart a date column.
export const isNumeric = (v) => v !== null && v !== '' && v !== undefined
  && isPlainNumber(String(v).trim());
// Numbers that are labels, not measures: year_key 2024, an LGD code, an id.
// Kept in step with pipeline._CHART_LABEL_COL.
export const LABEL_WORDS = ['year', 'yr', 'fy', 'code', 'id', 'lgd', 'pin', 'pincode', 'key', 'rank', 'sl', 'serial'];
export const isLabelCol = (k) => hasSegment(k, LABEL_WORDS);   // one '_'-separated part of the name, any case
export const PERIOD_WORDS = ['year', 'yr', 'fy', 'month', 'period', 'date', 'quarter'];

/** Every column any row carries, in first-seen order. A cross-scheme figures
    table (app/cross_figures.py) can give a scheme a column the others lack, so
    the first row's keys alone would drop it from the table and the export (2026-10-22). */
export function tableColumns(data) {
  const cols = [];
  for (const r of data || []) for (const c of Object.keys(r || {})) if (!cols.includes(c)) cols.push(c);
  return cols;
}

const isBlank = (v) => {
  if (v === null || v === undefined) return true;
  const s = String(v).trim().toLowerCase();
  return s === '' || s === 'none' || s === 'null' || s === 'nan';
};

/** A measure column: not a label word, and every value it has is a plain number. */
export function isMeasureCol(data, c) {
  if (isLabelCol(c)) return false;
  let seen = false;
  for (const r of data || []) {
    const v = r ? r[c] : undefined;
    if (isBlank(v)) continue;
    if (!isNumeric(v)) return false;
    seen = true;
  }
  return seen;
}

// ── Twin columns ────────────────────────────────────────────────────────────
// Two label columns that are one thing written two ways: year_key 2023 and
// financial_year "2023-2024", a village name and its code. Merged ONLY when the
// data pairs their values one-to-one, and only for a period pair or a name /
// identifier pair — two names (block and district) are never merged, even when
// each block happens to sit in its own district.
const ID_WORDS = ['key', 'code', 'id', 'sl', 'serial'];
const isIntegerish = (v) => isNumeric(v) && !String(v).includes('.');
const allValues = (data, c) => data.map((r) => (r ? r[c] : undefined));
const isPeriodCol = (data, c) => hasSegment(c, PERIOD_WORDS) || allValues(data, c).every((v) => isPeriodLabel(v));
const isIdCol = (data, c) => hasSegment(c, ID_WORDS) || allValues(data, c).every(isIntegerish);

function oneToOne(data, a, b) {
  const ab = new Map();
  const ba = new Map();
  for (const r of data) {
    const x = String(r[a]);
    const y = String(r[b]);
    if (ab.has(x) && ab.get(x) !== y) return false;
    if (ba.has(y) && ba.get(y) !== x) return false;
    ab.set(x, y);
    ba.set(y, x);
  }
  return true;
}

/** { hiddenColumn: keptColumn } for every twin pair in the rows. The kept one is
    the readable one: text over a number, the shorter period form ("2023-24")
    over the longer. Empty for one row or none. */
export function twinColumns(data) {
  const out = {};
  if (!Array.isArray(data) || data.length < 2) return out;
  const cols = tableColumns(data).filter((c) => !isMeasureCol(data, c)
    && data.every((r) => r && !isBlank(r[c]))
    && new Set(allValues(data, c).map(String)).size >= 2);
  for (let i = 0; i < cols.length; i++) {
    for (let j = i + 1; j < cols.length; j++) {
      const a = cols[i];
      const b = cols[j];
      if (a in out || b in out || !oneToOne(data, a, b)) continue;
      const periods = isPeriodCol(data, a) && isPeriodCol(data, b);
      const idA = isIdCol(data, a);
      const idB = isIdCol(data, b);
      if (!periods && idA === idB) continue;                 // two names, or two ids: not twins
      let hide;
      if (idA !== idB) hide = idA ? a : b;                     // keep the name, hide the id
      else {
        const len = (c) => Math.max(...allValues(data, c).map((v) => String(v).length));
        hide = len(a) > len(b) ? a : b;                        // "2023-2024" hidden, "2023-24" kept
      }
      out[hide] = hide === a ? b : a;
    }
  }
  return out;
}

// ── One financial-year column (audit 2026-10-29, A-1 / A-8) ─────────────────
// Rows merged from several schemes name their year their own way (MGNREGA
// year_key 2023, PMAY-G financial_year_short "2023-24"), so no year column was in
// every row and the chart fell back to the scheme alone: a donut of "MGNREGA,
// MGNREGA, MGNREGA, PMAY-G …" with no year anywhere. A lone year_key showed as
// "2022, 2023" titled "Year key".

/** "2023-24" for a financial-year value (2023, "2023", "2023-2024", "FY 2023-24",
    "2023-24"); null when the value is not one. */
export function fyLabel(v) {
  if (v === null || v === undefined) return null;
  let s = String(v).trim();
  if (s.slice(0, 2).toLowerCase() === 'fy') s = s.slice(2).trim();
  const head = s.slice(0, 4);
  const rest = s.slice(4);
  if (head.length !== 4 || !Array.from(head).every(isDigit) || !['19', '20'].includes(head.slice(0, 2))) return null;
  const tail = rest.slice(1);
  if (rest !== '' && !(rest[0] === '-' && (tail.length === 2 || tail.length === 4) && Array.from(tail).every(isDigit))) return null;
  const y = Number(head);
  return `${y}-${String((y + 1) % 100).padStart(2, '0')}`;
}

const isFyCol = (c) => (hasSegment(c, ['year', 'yr', 'fy', 'financial']))
  && !hasSegment(c, ['month', 'date', 'quarter', 'week', 'day']);

/** The rows with every financial-year column folded into one `financial_year`
    ("2023-24") when rows carry different year columns, or the only one is a
    year_key; otherwise the rows as they are. */
export function unifyPeriods(data) {
  if (!Array.isArray(data) || !data.length) return data;
  const cols = tableColumns(data).filter((c) => isFyCol(c)
    && data.some((r) => r && !isBlank(r[c]))
    && data.every((r) => !r || isBlank(r[c]) || fyLabel(r[c]) !== null));
  if (!cols.length) return data;
  const differs = cols.length >= 2 && data.some((r) => cols.some((c) => !r || isBlank(r[c])));
  const keyOnly = cols.length === 1 && hasSegment(cols[0], ['key']);
  if (!differs && !keyOnly) return data;
  return data.map((r) => {
    const o = {};
    const fy = cols.map((c) => fyLabel(r && r[c])).find((x) => x) || null;
    for (const [k, v] of Object.entries(r || {})) {
      if (cols.includes(k)) {
        if (!('financial_year' in o)) o.financial_year = fy;
        continue;
      }
      o[k] = v;
    }
    if (!('financial_year' in o)) o.financial_year = fy;
    return o;
  });
}

/** The rows without their hidden twin columns (new objects; the input is untouched). */
export function withoutTwins(data) {
  const hidden = Object.keys(twinColumns(data));
  if (!hidden.length) return data;
  return data.map((r) => {
    const o = {};
    for (const [k, v] of Object.entries(r || {})) if (!hidden.includes(k)) o[k] = v;
    return o;
  });
}

// ── Names and units ─────────────────────────────────────────────────────────
// A column name as words: "total_exp_lakh" -> "total expenditure (₹ lakh)",
// "lgd_district" -> "district". Codes in names are spelled out; the rest only
// loses its underscores.
const COL_WORDS = { lgd: '', exp: 'expenditure', amt: 'amount', cnt: 'count', qty: 'quantity', hh: 'households',
  lakh: '(₹ lakh)', lakhs: '(₹ lakh)', cr: '(₹ crore)', crore: '(₹ crore)', rupees: '(₹)', rs: '(₹)', fy: 'FY',
  pct: '%', perc: '%', avg: 'average', yr: 'year' };
export const humanCol = (c) => String(c).split('_').map((w) => (w.toLowerCase() in COL_WORDS ? COL_WORDS[w.toLowerCase()] : w))
  .filter(Boolean).join(' ') || String(c);

/** A heading for a table or an axis: humanCol, without "raw", first letter capitalised. */
export function colTitle(c) {
  const words = humanCol(c).split(' ').filter((w) => w && w.toLowerCase() !== 'raw');
  const s = words.join(' ') || String(c);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** 'lakh' | 'crore' | 'pct' | null — from the column-name suffix, as the backend's _unit_suffix. */
export function unitOf(c) {
  if (hasSegment(c, ['lakh', 'lakhs'])) return 'lakh';
  if (hasSegment(c, ['cr', 'crore', 'crores'])) return 'crore';
  if (hasSegment(c, ['pct', 'percent', 'percentage', 'perc'])) return 'pct';
  return null;
}

// Measures that must not be added up across rows: shares, rates, averages, and a
// running stock (MGNREGA job cards are cumulative; adding years is wrong).
const NON_ADDITIVE = ['pct', 'percent', 'percentage', 'perc', 'share', 'rate', 'ratio', 'avg', 'average', 'mean',
  'median', 'per', 'cumulative', 'card', 'cards', 'min', 'max', 'minimum', 'maximum'];
export const isAdditive = (c) => !hasSegment(c, NON_ADDITIVE);

// ── Cell formatting ─────────────────────────────────────────────────────────
const NUM = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });

/** One table cell as shown: a measure with Indian grouping and at most 2
    decimals (27264054 -> 2,72,64,054; 119.73925 -> 119.74); a label — a year, a
    code, an id — exactly as it is (2023 never becomes 2,023); a missing value "—". */
export function formatCell(v, col) {
  if (isBlank(v)) return '—';
  if (isLabelCol(col) || !isNumeric(v)) return String(v);
  // An identifier written in digits is shown as stored: a leading zero ("0012")
  // or 13+ digits (an account / sanction number) is never a quantity.
  const s = String(v).trim();
  const digits = s.startsWith('-') ? s.slice(1) : s;
  if ((digits.length > 1 && digits[0] === '0' && digits[1] !== '.') || digits.split('.')[0].length >= 13) return s;
  const n = Number(s.replaceAll(',', ''));
  return Number.isFinite(n) ? NUM.format(n) : String(v);
}

const signed = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + NUM.format(Math.abs(n));

/** "Change from previous" for a period table: { column, values } or null.
    Only for one period column + one measure, periods already in time order,
    2+ rows — the figures come from the rows, nothing else. */
export function changeColumn(data) {
  if (!Array.isArray(data) || data.length < 2) return null;
  const cols = tableColumns(data);
  const measures = cols.filter((c) => isMeasureCol(data, c));
  const labels = cols.filter((c) => !measures.includes(c));
  if (measures.length !== 1 || labels.length !== 1) return null;
  const [m] = measures;
  const [p] = labels;
  if (!data.every((r) => isPeriodLabel(r[p]))) return null;
  for (let i = 1; i < data.length; i++) {
    if (String(data[i - 1][p]).localeCompare(String(data[i][p])) >= 0) return null;   // not in time order
  }
  const pct = unitOf(m) === 'pct';
  const values = data.map((r, i) => {
    if (i === 0 || !isNumeric(r[m]) || !isNumeric(data[i - 1][m])) return '';
    const cur = Number(String(r[m]).replaceAll(',', ''));
    const prev = Number(String(data[i - 1][m]).replaceAll(',', ''));
    const d = cur - prev;
    if (pct) return `${signed(d)} pts`;
    return prev ? `${signed(d)} (${signed(Math.round((d / prev) * 1000) / 10)}%)` : signed(d);
  });
  return { column: 'Change from previous', values };
}

// ── Question words ──────────────────────────────────────────────────────────
const words = (s) => splitSpaces(String(s || '').toLowerCase())
  .map((w) => w.split('').filter((c) => isAsciiLetter(c) || isDigit(c) || c === '-').join(''))
  .filter(Boolean);
const CHANGE_WORDS = ['change', 'changed', 'changes', 'changing', 'trend', 'trends', 'grow', 'grew', 'growth',
  'grown', 'rise', 'rose', 'risen', 'fall', 'fell', 'fallen', 'increase', 'increased', 'decrease', 'decreased',
  'decline', 'declined', 'yoy'];

/** The question asks how a figure moved over time ("how have … changed",
    "trend", "over the years", "year on year"). */
export function asksChange(question) {
  const w = words(question);
  if (w.some((x) => CHANGE_WORDS.includes(x))) return true;
  const has3 = (a, b, c) => w.some((x, i) => x === a && w[i + 1] === b && w[i + 2] === c);
  return has3('over', 'the', 'years') || has3('year', 'on', 'year') || w.includes('year-on-year');
}
