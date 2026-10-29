/* Decides how a DATA answer's rows are shown: a KPI chart, a record card, a
   plain table, grouped / stacked bars, or up to three switchable charts plus the
   table. The rules are moved verbatim from buildAnalytics() in
   web/ai_query.html; the React components render the descriptor this returns. */

import { hasSegment, isAsciiLetter, isDigit, isPeriodLabel, isSpace, splitSpaces } from './text.js';
import { fyMonthIndex, isMonthLabel, isQuarterLabel } from './chartTheme.js';
import {
  PERIOD_WORDS, asksChange, canAdd, colTitle, dimOf, fractionPct, measureKind as measureKindOf, humanCol, isAdditive, isBlank, isLabelCol, isNumeric,
  lowerIsBetter, measureName, nameParts, placeTitle, tableColumns, unifyPeriods, unitOf, withoutTwins,
} from './columns.js';

// The column rules live in columns.js (2026-10-28); re-exported for the callers
// and tests that import them from here.
export { humanCol, tableColumns };

// At most this many series (schemes, districts) share one chart; past it the two
// label columns are joined into one axis label instead ("MGNREGA · 2023-24").
const MAX_SERIES = 8;

const label18 = (v) => (String(v).length > 18 ? String(v).slice(0, 16) + '…' : String(v));

// A missing value (SQL NULL, '') stays null: Chart.js leaves a gap there and a
// tile shows "—". Read as 0 it drew "X vs 0" tiles and lines that dropped to
// zero in years with no data (audit 2026-10-23, E11).
export const toNumber = (v) => (isNumeric(v) ? Number(String(v).trim().replaceAll(',', '')) : null);
// "2024", "2024-03" or "2024-03-15"
const isYearOrIsoDate = (s) => (s.length === 4 || s.length === 7 || s.length === 10)
  && Array.from(s).every((c, i) => ((i === 4 || i === 7) ? c === '-' : isDigit(c)));
const mentionsAny = (s, words) => { const low = String(s).toLowerCase(); return words.some((w) => low.includes(w)); };
// The chart types the backend can ask for (pipeline._chart_hint, D-042).
const SINGLE_TYPES = ['bar', 'pie', 'doughnut', 'line'];

// C-16: a title in words: "Person days by district and financial year", not
// "person days by district name and financial year".
const titleCol = (c) => {
  const w = humanCol(c).split(' ').filter((x) => x && !['name', 'short', 'raw'].includes(x.toLowerCase()));
  const s = w.join(' ') || String(c);
  return s.charAt(0).toUpperCase() + s.slice(1);
};

// ── C-13: financial years with no row are gaps on the axis ───────────────────
const fyStart = (l) => {
  const s = String(l ?? '').trim();
  return s.length === 7 && s[4] === '-' && isPeriodLabel(s) ? Number(s.slice(0, 4)) : null;
};
const fyText = (y) => `${y}-${String((y + 1) % 100).padStart(2, '0')}`;

/** The rows of a financial-year chart with a null in place of every year inside
    the span that has no row; `gapLabels[i]` names the missing year. */
function withYearGaps(data, col) {
  const ys = data.map((r) => fyStart(r[col]));
  const out = data.slice();
  out.gapLabels = data.map(() => null);
  if (data.length < 2 || ys.some((y) => y === null)) return out;
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  if (hi - lo + 1 === data.length || hi - lo > 30) return out;
  const at = new Map(ys.map((y, i) => [y, data[i]]));
  const full = [];
  full.gapLabels = [];
  for (let y = lo; y <= hi; y++) {
    full.push(at.get(y) || null);
    full.gapLabels.push(at.has(y) ? null : fyText(y));
  }
  return full;
}

function fillYearGaps(labels, datasets) {
  const ys = labels.map(fyStart);
  if (labels.length < 2 || ys.some((y) => y === null)) return { labels, datasets };
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  if (hi - lo + 1 === labels.length || hi - lo > 30) return { labels, datasets };
  const all = [];
  for (let y = lo; y <= hi; y++) all.push(fyText(y));
  return {
    labels: all,
    datasets: datasets.map((d) => ({ ...d, data: all.map((l) => { const i = labels.indexOf(l); return i < 0 ? null : d.data[i]; }) })),
  };
}

// I-10 / J-7: the question asks for the low end ("lowest 5", "least", "bottom")
const LOW_WORDS = ['lowest', 'least', 'bottom', 'fewest', 'minimum', 'min', 'worst', 'poorest', 'weakest', 'smallest'];
export const asksLow = (question) => words(question).some((w) => LOW_WORDS.includes(w));

/** The one-line verdict under a two-way comparison: who leads, by how much.
    { lead, trail, pct, diff, measure } or { equal: true, value, measure };
    { unlike: true, measure } when the two sides measure different things
    (`unlike`); null when a side has no value. pct is null when the trailing
    value is 0 (nothing to divide by). */
export function compareVerdict(l1, v1, l2, v2, measure, unlike = false, opts = {}) {
  if (unlike) return { unlike: true, measure };
  if (!Number.isFinite(v1) || !Number.isFinite(v2)) return null;
  if (v1 === v2) return { equal: true, value: v1, measure };
  const points = opts.unit === 'pct';
  if (opts.periods) {
    // C-1 (audit 2026-10-29): two periods are a change over time, measured from the
    // earlier one ("2023-24 is 15% ahead" was a 13% fall from 2023-24 to 2024-25)
    const [from, fv, to, tv] = String(l1).localeCompare(String(l2)) <= 0 ? [l1, v1, l2, v2] : [l2, v2, l1, v1];
    const diff = tv - fv;
    const pct = !points && fv ? Math.round((Math.abs(diff) / Math.abs(fv)) * 100) : null;
    return { change: diff > 0 ? 'rose' : 'fell', from, to, diff, pct, points, measure };
  }
  // D-5: for a lower-is-better measure (pending, delays, unpaid) the lower side leads
  const lowFirst = !!opts.lowerBetter;
  const [lead, lv, trail, tv] = (v1 > v2) !== lowFirst ? [l1, v1, l2, v2] : [l2, v2, l1, v1];
  const diff = Math.abs(lv - tv);
  // D-4: two percentages differ by points, not by a relative %
  const pct = points ? null : (tv > 0 && !lowFirst ? Math.round((diff / tv) * 100) : null);
  return { lead, trail, pct, diff, measure, ...(points ? { points: true } : {}),
    ...(lowFirst ? { lowerBetter: true } : {}), ...(opts.diffFirst ? { diffFirst: true } : {}) };
}

export function pivotStacked(data, xKey, sKey, vKey) {
  const xLabels = [...new Set(data.map((r) => r[xKey]))];
  const sLabels = [...new Set(data.map((r) => r[sKey]))];
  // C-11: series that are periods are drawn (and shaded) oldest to newest
  if (sLabels.every((l) => isPeriodLabel(l))) sLabels.sort((a, b) => String(a).localeCompare(String(b)));
  else if (sLabels.every((l) => isMonthLabel(l))) sLabels.sort((a, b) => fyMonthIndex(a) - fyMonthIndex(b));
  const datasets = sLabels.map((sl) => ({
    label: sl,
    data: xLabels.map((xl) => {
      const row = data.find((r) => r[xKey] === xl && r[sKey] === sl);
      return row ? toNumber(row[vKey]) : null;   // no row: a gap, not a 0
    }),
  }));
  return { labels: xLabels, datasets };
}

// ── What the officer asked to SEE (user report 2026-10-19: "So I want comparison
// in graph." came back as the same table). Read on words, no regex (D-047).
const CHART_NOUNS = ['graph', 'graphs', 'chart', 'charts', 'plot', 'plots', 'diagram', 'visual', 'visuals',
  'visualise', 'visualize', 'visualisation', 'visualization', 'graphically', 'graphical', 'pictorial', 'plotted'];
const TABLE_NOUNS = ['table', 'tables', 'tabular', 'tabulate', 'tabulated'];
const TYPE_WORDS = { pie: 'pie', donut: 'doughnut', doughnut: 'doughnut', line: 'line', bar: 'bar', bars: 'bar',
  column: 'bar', columns: 'bar', stacked: 'stacked', trend: 'line' };
// Written as one word: "I want only in Barchart" (user, 2026-10-19).
const JOINED_TYPES = Object.fromEntries(['pie', 'donut', 'doughnut', 'line', 'bar', 'column']
  .flatMap((t) => ['chart', 'charts', 'graph', 'graphs'].map((n) => [t + n, TYPE_WORDS[t]])));
const LEAD_WORDS = ['a', 'an', 'the', 'in', 'as', 'on', 'with', 'using', 'into', 'via', 'by', 'through', 'form', 'of'];

const words = (s) => splitSpaces(String(s || '').toLowerCase())
  .map((w) => w.split('').filter((c) => isAsciiLetter(c) || isDigit(c) || c === '-').join(''))
  .filter(Boolean);

/** 'chart' | 'bar' | 'pie' | 'doughnut' | 'line' | 'stacked' | 'table' | null:
    the view the question asks for. A chart noun ("graph", "chart", "plot",
    "visualise") asks for a chart; a type word before it picks the type
    ("pie chart", "line graph"). "pie" / "donut" alone are enough; "line" and
    "bar" need the noun ("bar chart"), as they mean other things on their own. */
export function chartPreference(question) {
  const w = words(question);
  const noun = w.findIndex((x) => CHART_NOUNS.includes(x));
  const typed = (i) => (i >= 0 ? TYPE_WORDS[w[i]] : undefined);
  const joined = w.find((x) => JOINED_TYPES[x]);
  if (joined && (noun < 0 || w.indexOf(joined) < noun)) return JOINED_TYPES[joined];
  if (noun >= 0) return (w.includes('stacked') ? 'stacked' : null) || typed(noun - 1) || typed(noun - 2) || 'chart';
  if (w.some((x) => x === 'pie')) return 'pie';
  if (w.some((x) => x === 'donut' || x === 'doughnut')) return 'doughnut';
  if (w.some((x) => TABLE_NOUNS.includes(x))) return 'table';
  return null;
}

// Words that carry no question of their own around a view request
// ("I want a bar chart", "can you show this as a pie chart please").
const VIEW_FILLER = ['i', 'we', 'want', 'wanted', 'need', 'would', 'like', 'please', 'pls', 'plz', 'kindly', 'can', 'could',
  'you', 'u', 'show', 'give', 'me', 'us', 'it', 'its', 'this', 'that', 'these', 'those', 'same', 'data', 'figures', 'numbers',
  'now', 'make', 'convert', 'change', 'draw', 'display', 'generate', 'create', 'render', 'view', 'see', 'instead', 'also',
  'again', 'comparison', 'compare', 'result', 'results', 'answer', 'above', 'previous', 'last', 'type', 'format', 'so', 'ok',
  'okay', 'just', 'one', 'let', 'to', 'and', 'for', 'is', 'there', 'any', 'what', 'about', 'how', 'version', 'it\'s',
  'represent', 'represented', 'representation', 'shown', 'put', 'into', 'get', 'better', 'do', 'not', 'yes',
  'but', 'only', 'query'];

/** The view a message asks for when it asks for NOTHING else ("bar chart",
    "I want a pie chart", "show this as a table please"): that view, else null.
    Such a message re-draws the last answer's data (App.jsx), any answer. */
export function viewOnlyRequest(question) {
  const pref = chartPreference(question);
  if (!pref) return null;
  const rest = words(question).filter((x) => !CHART_NOUNS.includes(x) && !TABLE_NOUNS.includes(x)
    && !TYPE_WORDS[x] && !JOINED_TYPES[x] && !LEAD_WORDS.includes(x) && !VIEW_FILLER.includes(x));
  return rest.length ? null : pref;
}

export const VIEW_NAMES = { chart: 'a chart', bar: 'a bar chart', pie: 'a pie chart', doughnut: 'a donut chart',
  line: 'a line chart', stacked: 'a stacked bar chart', table: 'a table' };

/** The question without its "as a pie chart" / "in graph" phrase, for the
    "by district" / "each year" offers under a single figure. */
export function withoutChartPhrase(question) {
  const raw = splitSpaces(String(question || '').trim());
  const low = raw.map((x) => words(x)[0] || '');
  const noun = low.findIndex((x) => CHART_NOUNS.includes(x));
  if (noun < 0) return String(question || '').trim();
  let start = noun;
  while (start > 0 && (TYPE_WORDS[low[start - 1]] || LEAD_WORDS.includes(low[start - 1]))) start--;
  let out = [...raw.slice(0, start), ...raw.slice(noun + 1)].join(' ').trim();
  while (out && (isSpace(out[out.length - 1]) || ',.;:!?'.includes(out[out.length - 1]))) out = out.slice(0, -1);
  return out;
}

// A ranking ("top 5 districts", "which block has the most …"): a bar chart, not
// a donut. A donut of the top 5 shows each as a share of those 5 only, which
// reads as a share of the whole (audit 2026-10-23, E11).
const RANK_WORDS = ['top', 'bottom', 'highest', 'lowest', 'best', 'worst', 'most', 'least', 'rank', 'ranks', 'ranked',
  'ranking', 'rankings', 'leading', 'lagging', 'maximum', 'minimum', 'max', 'min', 'largest', 'smallest', 'biggest'];
export const asksRanking = (question) => words(question).some((w) => RANK_WORDS.includes(w));

// The two sides of a comparison are different schemes: each counts its own
// thing (MGNREGA households, PMAY-G houses) and spends its own kind of money
// (expenditure, releases), so neither is "ahead" (audit 2026-10-23: "MGNREGA is
// 66% ahead on amount" put money spent against money released; E11).
const isSchemeCol = (c) => hasSegment(c, ['scheme', 'schemes']);

// The measure a question asks to compare, so the two-way card shows THAT figure
// and not whichever column came first (user report 2026-10-27: "Compare
// beneficiaries in mgnrega and PMAY-G" drew a card of the amount in ₹ crore).
// Word stems, read on whole words of the question and on the '_' parts of a
// column name; no regex (D-047).
const MONEY_STEMS = ['amount', 'money', 'spen', 'expend', 'disburs', 'releas', 'crore', 'lakh', 'rupee',
  'fund', 'cost', 'budget', 'wage', 'paid'];
// a column may also be "total_exp"; a question word "exp…" is often "explain"
const MONEY_COL_STEMS = [...MONEY_STEMS, 'exp'];
const COUNT_STEMS = ['beneficiar', 'household', 'people', 'person', 'house', 'member', 'count', 'worker',
  'farmer', 'application', 'job'];
const hasStem = (parts, stems) => parts.some((w) => stems.some((s) => w.startsWith(s)));
const colParts = (c) => nameParts(c);   // '_', spaces and brackets (J-9: "amount sanctioned (Rs)")

/** The numeric column whose name matches the one kind of measure (money, or a
    count of people / houses) the question names; null when it names neither,
    both, or no column matches — the caller keeps its first column then. */
export function askedMeasureCol(question, numCols) {
  const w = words(question);
  // B-10: "money per beneficiary" asks the per-head figure, not either total
  if (w.includes('per')) {
    const per = numCols.find((c) => colParts(c).includes('per'));
    if (per) return per;
  }
  const money = hasStem(w, MONEY_STEMS);
  const count = hasStem(w, COUNT_STEMS);
  if (money === count) return null;
  const stems = money ? MONEY_COL_STEMS : COUNT_STEMS;
  return numCols.find((c) => hasStem(colParts(c), stems)) || null;
}

// ── Label columns: dimensions, fixed values and details (audit 2026-10-29) ──
// C-2: a column with one value in every row ("EKH") was drawn as a one-item legend
// and a one-column pivot; it belongs in the title. E-1 / J-6 / G-9 / B-11: a column
// fully set by another (a block's district, a village's block, what each scheme
// counts or spends) was drawn as a second dimension — mostly-empty grouped bars, a
// stack coloured by block, a table full of "—". It is a detail: in the table and
// the tooltip, never a series. A rank / serial number is a detail too (E-2).
const RANK_WORDS_COL = ['rank', 'sl', 'serial'];
function functional(data, a, b) {
  const m = new Map();
  for (const r of data) {
    const x = String(r[a] ?? '');
    const y = String(r[b] ?? '');
    if (m.has(x) && m.get(x) !== y) return false;
    m.set(x, y);
  }
  return true;
}

/** { dims, fixed, details } of these rows' label columns. `ranking`: the rows are a
    ranked list of one kind of place, so the coarser of two place columns is its
    detail even when names repeat (E-7: two villages called "Mawlai"). */
export function splitLabels(data, lbl, ranking = false) {
  const distinct = (k) => new Set(data.map((r) => String(r[k] ?? ''))).size;
  const isPeriod = (c) => dimOf(c, data) === 'period';
  const details = lbl.filter((c) => hasSegment(c, RANK_WORDS_COL));
  let rest = lbl.filter((c) => !details.includes(c));
  const fixed = data.length > 1 ? rest.filter((c) => distinct(c) === 1) : [];
  if (fixed.length < rest.length) rest = rest.filter((c) => !fixed.includes(c));
  else fixed.length = 0;   // every label is constant: keep them as they are
  for (const b of [...rest]) {
    if (rest.length < 2 || isPeriod(b) || dimOf(b, data) === 'scheme') continue;
    const pairsUnique = (a) => new Set(data.map((r) => `${r[a]}||${r[b]}`)).size === data.length;
    const by = rest.find((a) => a !== b && (functional(data, a, b) || (ranking && rest.length === 2
      && dimOf(a, data) === 'place' && pairsUnique(a)))
      && (distinct(a) > distinct(b) || (distinct(a) === distinct(b) && (dimOf(a, data) === 'scheme'
        || rest.indexOf(a) < rest.indexOf(b)))));
    if (by) {
      details.push(b);
      rest = rest.filter((c) => c !== b);
    }
  }
  return { dims: rest, fixed, details };
}

/** B-4 / A-6 (audit 2026-10-29): every measure column the question names, the
    asked one first ("beneficiaries and amount" -> both); [] when it names none. */
export function askedMeasureCols(question, numCols) {
  const w = words(question);
  const out = [];
  if (w.includes('per')) { const c = numCols.find((x) => colParts(x).includes('per')); if (c) out.push(c); }
  if (hasStem(w, COUNT_STEMS)) { const c = numCols.find((x) => !out.includes(x) && hasStem(colParts(x), COUNT_STEMS)); if (c) out.push(c); }
  if (hasStem(w, MONEY_STEMS)) { const c = numCols.find((x) => !out.includes(x) && hasStem(colParts(x), MONEY_COL_STEMS)); if (c) out.push(c); }
  return out;
}

/** `prefer` is chartPreference(question) (or 'chart' for /chart): a chart the
    officer asked for. It picks the first chart type, draws a one-row answer
    with several figures as a chart, and skips the two-tile card. */
export function buildAnalytics(question, rawData, hintType, prefer = null) {
  const a = buildAnalyticsCore(question, rawData, hintType, prefer);
  if (!a || !prefer || prefer === 'chart' || prefer === 'table') return a;
  const asked = a.kind === 'twoDim' ? (prefer === 'pie' ? 'doughnut' : prefer) : (prefer === 'stacked' ? 'bar' : prefer);
  // A-7 / G-1 (audit 2026-10-29): a pie, donut or stack of figures that must not be
  // added up (overlapping villages, different schemes, rates) would show a total
  // and shares that do not exist. Bars instead, with a one-line note.
  if ((a.kind === 'twoDim' || a.kind === 'multi') && a.types && !a.types.includes(asked)) {
    return { ...a, defType: 'bar', refused: prefer, note: refusalNote(prefer, a.noAddWhy) };
  }
  if (a.kind === 'twoDim') return { ...a, defType: asked };
  if (a.kind === 'multi' || a.kind === 'kpi') return { ...a, defType: asked };
  return a;
}

const VIEW_WORD = { pie: 'A pie chart', doughnut: 'A donut chart', stacked: 'A stacked chart', line: 'A line chart' };
const NO_ADD_WHY = {
  scheme: 'the schemes count and spend different things',
  overlap: 'the same villages, households or beneficiaries are counted again in each year or scheme',
  rate: 'a rate or an average does not add up',
  negative: 'some values are below zero',
  category: 'a line only joins periods in time',
};
function refusalNote(prefer, why) {
  return `${VIEW_WORD[prefer] || 'That chart'} would add these figures up, but ${NO_ADD_WHY[why] || NO_ADD_WHY.overlap}, `
    + 'so they are shown as bars.';
}

/** Why measure `vc` may not be added along label `col` of these rows, or null. */
function noAddReason(vc, col, data) {
  const dim = dimOf(col, data);
  if (dim === 'scheme') return 'scheme';
  if (!isAdditive(vc)) return 'rate';
  if (!canAdd(vc, dim)) return 'overlap';
  if (data.some((r) => toNumber(r[vc]) !== null && toNumber(r[vc]) < 0)) return 'negative';
  return null;
}

function buildAnalyticsCore(question, rawData, hintType, prefer) {
  if (!Array.isArray(rawData) || rawData.length === 0) return null;
  // B-5 (audit 2026-10-29, decided): the old cross_scheme.py summary shape is no longer
  // sent (cross_figures rows go through the normal path), so its special case is gone
  // One thing written two ways (year_key 2023 and financial_year "2023-2024") is
  // ONE dimension: read as two, it drew a diagonal grid of dashes (user report
  // 2026-10-28). The readable twin stays; the download keeps every column. Year
  // columns that differ from scheme to scheme become one financial_year (A-1).
  const data = withoutTwins(unifyPeriods(rawData)).slice();

  // One row of several figures: a bar (or the pie / donut asked for) per figure.
  const oneRowTypes = ['kpi_bar', 'bar', 'pie', 'doughnut'];
  if (data.length === 1 && (oneRowTypes.includes(hintType) || (prefer && prefer !== 'table'))) {
    const row = data[0];
    // Chart the compared parts only: when the row carries a derived total equal
    // to the sum of the parts, its bar would dwarf the comparison. The record
    // card below still shows every column.
    let keys = Object.keys(row).filter((k) => isNumeric(row[k]) && !isLabelCol(k));
    if (keys.length < 2) return { kind: 'record', row };
    // X-3 (audit 2026-10-29): person days, ₹ lakh and households on one axis compare
    // nothing — figures in different units stay a record card
    if (new Set(keys.map((k) => unitOf(k) || measureKindOf(k))).size > 1 && !(prefer && prefer !== 'table')) {
      return { kind: 'record', row };
    }
    const isTotalKey = (k) => hasSegment(k, ['total', 'overall', 'sum']);
    const totalKeys = keys.filter(isTotalKey);
    if (keys.length >= 3 && totalKeys.length === 1) {
      const parts = keys.filter((k) => k !== totalKeys[0]);
      const tv = parseFloat(row[totalKeys[0]]);
      const psum = parts.reduce((s, k) => s + (parseFloat(row[k]) || 0), 0);
      if (isFinite(tv) && psum > 0 && Math.abs(tv - psum) <= Math.max(1, Math.abs(tv) * 0.001)) keys = parts;
    }
    return {
      kind: 'kpi',
      labels: keys.map((k) => humanCol(k)),
      values: keys.map((k) => toNumber(row[k])),
      defType: hintType === 'kpi_bar' ? 'bar' : hintType,
      row,
    };
  }

  if (data.length === 1) return { kind: 'record', row: data[0] };

  // Only the columns every row carries are charted. A column some row lacks is a
  // figure that row's scheme does not have (MGNREGA households given work against
  // PMAY-G): read as 0 it drew "MGNREGA 14,94,437 vs PMAY-G 0" (user report
  // 2026-10-22). A SQL NULL keeps its key and is unaffected.
  const cols = Object.keys(data[0]).filter((c) => data.every((r) => r && c in r));
  const numCols = cols.filter((c) => {
    if (isLabelCol(c)) return false;
    let seen = false;
    for (const r of data) {
      const v = r[c];
      if (isBlank(v)) continue;            // X-6: "N/A", "-" are blanks
      if (!isNumeric(v)) return false;
      seen = true;
    }
    return seen;
  });
  const allLbl = cols.filter((c) => !numCols.includes(c));

  if (!numCols.length) {
    // E-5: a column with no figure in any row (not recorded that year) is said, not a bare list of names
    const empty = cols.filter((c) => !isLabelCol(c) && data.every((r) => isBlank(r[c])));
    return empty.length
      ? { kind: 'table', data, note: `None of these ${data.length} rows has a figure for ${humanCol(empty[0])}, so there is nothing to ${asksRanking(question) ? 'rank' : 'chart'}.` }
      : { kind: 'table', data };
  }

  const { dims: lblCols, fixed, details } = splitLabels(data, allLbl, asksRanking(question));
  const where = fixed.length ? ` in ${fixed.map((c) => String(data[0][c])).join(', ')}` : '';
  const say = details.filter((c) => !hasSegment(c, RANK_WORDS_COL));
  const lc = lblCols[0] || cols[0];
  // the label with its details: "Umling (Ri Bhoi)"; on the axis only when names repeat (E-7)
  // C-5 (live run): chart labels and headlines read place names in Title Case, like the table
  const full = (r, c) => (say.length ? `${placeTitle(r[c], c)} (${say.map((d) => placeTitle(r[d], d)).join(', ')})`
    : placeTitle(r[c], c));
  const repeats = new Set(data.map((r) => String(r[lc]))).size < data.length;

  // I-8: each scheme's own top / bottom list, merged: one ranked chart per scheme
  // (small multiples) and a table Rank · MGNREGA district · value · PMAY-G … — not
  // one chart over the union of names, most bars holding one scheme.
  const sCol = lblCols.find((c) => dimOf(c, data) === 'scheme');
  const oCol = lblCols.find((c) => c !== sCol && dimOf(c, data) !== 'period');
  if (sCol && oCol && lblCols.length === 2 && (allLbl.some((c) => hasSegment(c, RANK_WORDS_COL)) || asksRanking(question))) {
    const schemes = [...new Set(data.map((r) => String(r[sCol])))];
    const sets = schemes.map((s) => new Set(data.filter((r) => String(r[sCol]) === s).map((r) => String(r[oCol]))));
    const same = sets.every((st) => st.size === sets[0].size && [...st].every((x) => sets[0].has(x)));
    if (schemes.length >= 2 && !same) {
      const vc = askedMeasureCol(question, numCols) || numCols[0];
      const per = schemes.map((s) => data.filter((r) => String(r[sCol]) === s));
      const charts = per.map((rs, i) => ({
        scheme: schemes[i],     // browser run: each card wears its own scheme, not "6 schemes"
        title: `${schemes[i]}: ${humanCol(vc)} by ${humanCol(oCol)}${where}`,
        labels: rs.map((r) => label18(r[oCol])), fullLabels: rs.map((r) => full(r, oCol)),
        values: rs.map((r) => toNumber(r[vc])),
        axes: { x: colTitle(oCol), y: colTitle(vc), unit: unitOf(vc) },
      }));
      const n = Math.max(...per.map((rs) => rs.length));
      const wide = Array.from({ length: n }, (_, i) => {
        const o = { rank: i + 1 };
        per.forEach((rs, k) => {
          o[`${schemes[k]} ${colTitle(oCol).toLowerCase()}`] = rs[i] ? rs[i][oCol] : null;
          o[`${schemes[k]} ${humanCol(vc)}`] = rs[i] ? rs[i][vc] : null;
        });
        return o;
      });
      return { kind: 'multi', charts, defType: 'bar', types: ['bar'], data: wide, perScheme: true };
    }
  }

  // Two things side by side (#397): "East Khasi Hills vs West Garo Hills". Two
  // rows, one label column, a measure -> two stat tiles and a one-line verdict
  // instead of a two-slice chart. Extra measures stay in the table below.
  if (data.length === 2 && lblCols.length === 1 && !(prefer && prefer !== 'table')) {
    const [r1, r2] = data;
    const l1 = String(r1[lc] ?? '').trim();
    const l2 = String(r2[lc] ?? '').trim();
    if (l1 && l2 && l1 !== l2) {
      const asked = askedMeasureCols(question, numCols);
      const vc = askedMeasureCol(question, numCols) || asked[0] || numCols[0];
      const sub = (r) => (say.length ? say.map((d) => r[d]).filter((x) => x !== null && x !== '').join(' · ') : null);
      return {
        kind: 'compare',
        vKey: vc,
        title: `${l1} vs ${l2}${where}`,
        measure: measureName(vc),
        a: { label: l1, value: toNumber(r1[vc]), detail: sub(r1) },
        b: { label: l2, value: toNumber(r2[vc]), detail: sub(r2) },
        unit: unitOf(vc),
        verdict: compareVerdict(l1, toNumber(r1[vc]), l2, toNumber(r2[vc]), measureName(vc), isSchemeCol(lc), {
          periods: [l1, l2].every((l) => isPeriodLabel(l) || isMonthLabel(l) || isQuarterLabel(l)),
          unit: unitOf(vc), lowerBetter: lowerIsBetter(vc),
          diffFirst: words(question).some((w) => ['difference', 'gap', 'differ', 'diff'].includes(w)),
        }),
        data,
        extra: numCols.length > 1,
        // B-4: a second asked measure is a second row of tiles, never only in the table
        more: asked.filter((c) => c !== vc).map((c) => ({
          vKey: c, measure: measureName(c), unit: unitOf(c),
          a: { label: l1, value: toNumber(r1[c]), detail: sub(r1) }, b: { label: l2, value: toNumber(r2[c]), detail: sub(r2) },
          verdict: compareVerdict(l1, toNumber(r1[c]), l2, toNumber(r2[c]), measureName(c), isSchemeCol(lc), {
            periods: [l1, l2].every((l) => isPeriodLabel(l) || isMonthLabel(l) || isQuarterLabel(l)),
            unit: unitOf(c), lowerBetter: lowerIsBetter(c) }),
        })),
      };
    }
  }
  // Two label columns and a measure — scheme × financial year, district × year,
  // block × scheme … (user report 2026-10-19: "Expenditure by scheme" drew one
  // line over MGNREGA, MGNREGA, MGNREGA, PMAY-G, … and the year was nowhere to be
  // seen). The period column goes on the x-axis and the other label becomes one
  // coloured series per value, so both dimensions are always visible; with no
  // period column the label with more values is the axis and the other the series.
  // A-5: with two label columns the two-dimension chart is used whatever the hint
  // ("side by side" -> grouped_bar with one measure fell to the one-label chart,
  // which dropped the second label). Only a grouped hint over 2+ measures, or a
  // stacked hint the measure allows, keeps its own card.
  const stackOk = lblCols.length >= 2 && !noAddReason(numCols[0], lblCols[1], data);
  if (lblCols.length >= 2 && !(hintType === 'grouped_bar' && numCols.length >= 2) && !(hintType === 'stacked' && stackOk)) {
    const distinct = (k) => new Set(data.map((r) => String(r[k] ?? ''))).size;
    const isPeriodCol = (c) => hasSegment(c, PERIOD_WORDS)
      || data.every((r) => isPeriodLabel(r[c]));
    const two = lblCols.slice(0, 2);
    // C-3: two periods (month and year): the finer one on the x-axis, the coarser
    // one as the series ("Month-wise for 2023-24 and 2024-25" put 2 years on the axis
    // and 12 months in the legend)
    const grain = (c) => ['date', 'day', 'week', 'month', 'quarter', 'year', 'yr', 'fy']
      .findIndex((w) => hasSegment(c, [w]) || (w === 'year' && hasSegment(c, ['financial'])));
    if (two.every(isPeriodCol)) two.sort((p, q) => (grain(p) < 0 ? 99 : grain(p)) - (grain(q) < 0 ? 99 : grain(q)));
    let xKey = two.find(isPeriodCol) || null;
    let sKey = xKey ? two.find((c) => c !== xKey) : null;
    if (!xKey) [xKey, sKey] = distinct(two[0]) >= distinct(two[1]) ? two : [two[1], two[0]];
    if (distinct(sKey) > MAX_SERIES && distinct(xKey) <= MAX_SERIES) [xKey, sKey] = [sKey, xKey];
    const order = [...askedMeasureCols(question, numCols), ...numCols.filter((c) => !askedMeasureCols(question, numCols).includes(c))];
    const vKey = order[0];
    if (distinct(sKey) <= MAX_SERIES && distinct(xKey) > 1) {
      if (data.every((r) => isPeriodLabel(r[xKey]))) data.sort((a, b) => String(a[xKey]).localeCompare(String(b[xKey])));
      const piv = pivotStacked(data, xKey, sKey, vKey);
      const { labels, datasets } = fillYearGaps(piv.labels, piv.datasets);
      const periods = labels.every((l) => isPeriodLabel(l) || isMonthLabel(l));
      // G-3 / G-4 / B-3: a stack adds the series, a donut adds every cell — only
      // when the measure adds along that dimension (never across schemes)
      const whyS = noAddReason(vKey, sKey, data);
      const whyX = noAddReason(vKey, xKey, data);
      const types = ['bar', ...(periods ? ['line'] : []), ...(whyS ? [] : ['stacked']),
        ...(whyS || whyX ? [] : ['doughnut'])];
      const hinted = hintType === 'stacked' ? 'stacked' : hintType;
      // A-13 (audit 2026-10-29): a year a scheme does not hold is a gap, never 0; the
      // gaps are named so they do not read as a fall to nothing
      const gaps = periods ? datasets.map((d) => {
        const missing = labels.filter((_, i) => d.data[i] === null || d.data[i] === undefined);
        return missing.length && missing.length < labels.length ? `${d.label} (${missing.join(', ')})` : null;
      }).filter(Boolean) : [];
      return {
        kind: 'twoDim',
        ...(gaps.length ? { note: `Gaps are years with no data: ${gaps.join('; ')}.` } : {}),
        title: `${titleCol(vKey)} by ${titleCol(xKey).toLowerCase()} and ${titleCol(sKey).toLowerCase()}${where}`,
        xKey, sKey, vKey, labels: labels.map((l) => placeTitle(l, xKey)),
        datasets: datasets.map((d) => ({ ...d, label: placeTitle(d.label, sKey) })), periods, types, noAddWhy: whyS || whyX,
        defType: types.includes(hinted) ? hinted : (periods ? 'line' : 'bar'),
        data, extra: numCols.length > 1,
        axes: { x: colTitle(xKey), y: colTitle(vKey), unit: unitOf(vKey) },
        // A-6: the other measures get their own chart (at most 3 in all), never dropped
        more: order.slice(1, 3).map((m) => {
          const pm = pivotStacked(data, xKey, sKey, m);
          const f = fillYearGaps(pm.labels, pm.datasets);
          return { title: `${titleCol(m)} by ${titleCol(xKey).toLowerCase()} and ${titleCol(sKey).toLowerCase()}${where}`,
            labels: f.labels.map(String), datasets: f.datasets, vKey: m, axes: { x: colTitle(xKey), y: colTitle(m), unit: unitOf(m) } };
        }),
      };
    }
    // C-12 (audit 2026-10-29): 12 districts × 12 months drew 144 bars named
    // "East Garo Hills · Apr" in a small card. Both dimensions large: a table with
    // one dimension down and the other across.
    if (distinct(xKey) > MAX_SERIES && distinct(sKey) > MAX_SERIES) {
      return { kind: 'table', data, pivot: { xKey: isPeriodCol(xKey) ? sKey : xKey, sKey: isPeriodCol(xKey) ? xKey : sKey, vKey },
        note: `${distinct(xKey)} × ${distinct(sKey)} figures are too many for one chart, so they are shown as a table.` };
    }
    // Too many series for one legend: one axis label carrying both dimensions.
    const joined = data.map((r) => two.map((c) => String(r[c] ?? '')).join(' · '));
    const charts = numCols.slice(0, 3).map((vc) => ({
      title: `${humanCol(vc)} by ${two.map((c) => humanCol(c)).join(' and ')}`,
      labels: joined.map(label18), fullLabels: joined, values: data.map((r) => toNumber(r[vc])),
    }));
    return { kind: 'multi', charts, defType: SINGLE_TYPES.includes(hintType) ? hintType : 'bar', data };
  }

  // Time only when the label column IS a period. "across all financial years ... by
  // district" names a year but its rows are districts: it was drawn as a line over
  // district names (user report 2026-10-19 16:01).
  // C-4 / C-9 / C-10: month names and quarters are periods too, in financial-year
  // order (Apr -> Mar; Q1 -> Q4), not the order the SQL happened to return
  const months = data.every((r) => isMonthLabel(r[lc]));
  const quarters = data.every((r) => isQuarterLabel(r[lc]));
  if (months) data.sort((a, b) => fyMonthIndex(a[lc]) - fyMonthIndex(b[lc]));
  if (quarters) data.sort((a, b) => String(a[lc]).localeCompare(String(b[lc])));
  const isTime = mentionsAny(lc, ['month', 'period', 'year', 'date', 'trend', 'quarter']) || months || quarters
    || data.every((r) => isPeriodLabel(r[lc]) || isYearOrIsoDate(String(r[lc] ?? '').trim()));
  // A trend reads left-to-right: sort ISO dates / plain years / financial years
  // ("2023-24", "FY 2023-24" — these sort as text too); the table follows.
  if (isTime && data.every((r) => isYearOrIsoDate(String(r[lc] ?? '').trim()) || isPeriodLabel(r[lc]))) {
    data.sort((a, b) => String(a[lc]).localeCompare(String(b[lc])));
  }
  const isFew = data.length <= 6;
  // A share, rate or average is not part of a whole: no pie / donut at all; nor
  // are schemes (they count different things) or overlapping counts by year
  // (G-1 / G-2 / G-5 / B-2 / D-8: a donut's "Total" and "% of the total").
  const whyNot = noAddReason(numCols[0], lc, data);
  const partOfWhole = !whyNot;
  const noSlices = !partOfWhole || asksRanking(question);
  // X-4 (audit 2026-10-29): a line across districts or schemes means nothing; Line
  // is offered only when the x-axis is a period
  const hinted = SINGLE_TYPES.includes(hintType) && !(noSlices && (hintType === 'pie' || hintType === 'doughnut'))
    && !(hintType === 'line' && !isTime) ? hintType : null;
  const defType = hinted || (isTime ? 'line' : isFew && !noSlices ? 'doughnut' : 'bar');

  if (hintType === 'grouped_bar' && numCols.length >= 2) {
    return {
      kind: 'grouped',
      title: `Grouped comparison by ${humanCol(lc)}`,
      labels: data.map((r) => label18(r[lc])),
      fullLabels: data.map((r) => String(r[lc])),
      datasets: numCols.map((nc) => ({ label: humanCol(nc), values: data.map((r) => toNumber(r[nc])) })),
      data,
    };
  }

  if (hintType === 'stacked' && lblCols.length >= 2 && numCols.length >= 1) {
    const xKey = lblCols[0];
    const sKey = lblCols[1];
    const vKey = numCols[0];
    const { labels, datasets } = pivotStacked(data, xKey, sKey, vKey);
    return {
      kind: 'stacked',
      title: `${humanCol(vKey)} by ${humanCol(xKey)} & ${humanCol(sKey)}`,
      labels, datasets, data, xKey, sKey, vKey,
    };
  }

  // E-5 (audit 2026-10-29): in a ranking, places with no figure are left out of the
  // chart (they opened it as empty bars) and the answer says how many had none
  let ranked = data;
  let unranked = 0;
  if (asksRanking(question) && !isTime) {
    ranked = data.filter((r) => toNumber(r[numCols[0]]) !== null);
    unranked = data.length - ranked.length;
    if (!ranked.length) {
      return { kind: 'table', data, note: `None of these ${data.length} rows has a figure for ${humanCol(numCols[0])}, so there is nothing to rank.` };
    }
  }
  const low = asksLow(question);
  // X-2: 300 bars in one card are unreadable — the top (or bottom) 15 are drawn and
  // the note says the full list is in the table
  let many = 0;
  if (!isTime && ranked.length > 25) {
    many = ranked.length;
    const m0 = askedMeasureCol(question, numCols) || numCols[0];
    ranked = ranked.slice().sort((p, q) => ((toNumber(q[m0]) ?? -Infinity) - (toNumber(p[m0]) ?? -Infinity)) * (low ? -1 : 1))
      .slice(0, 15);
  }
  // C-13: a financial year a scheme does not hold is a gap, not two years drawn adjacent
  const rowsAt = withYearGaps(ranked, lc);
  // E-6: a ranking charts its ranking measure only; the others stay in the table
  const chartCols = asksRanking(question) && !isTime ? [askedMeasureCol(question, numCols) || numCols[0]] : numCols.slice(0, 3);
  const charts = chartCols.map((vc) => {
    const raw = rowsAt.map((r) => (r ? toNumber(r[vc]) : null));
    const scale = fractionPct(vc, raw) ? 100 : 1;          // D-6: 0.753 -> 75.3%
    return {
      title: `${titleCol(vc)} by ${titleCol(lc).toLowerCase()}${where}`,
      labels: rowsAt.map((r, i) => (r ? label18(repeats ? full(r, lc) : placeTitle(r[lc], lc)) : rowsAt.gapLabels[i])),
      fullLabels: rowsAt.map((r, i) => (r ? full(r, lc) : `${rowsAt.gapLabels[i]} (no data)`)),
      values: raw.map((v) => (v === null ? null : v * scale)),
      axes: { x: colTitle(lc), y: colTitle(vc), unit: unitOf(vc), lowerBetter: lowerIsBetter(vc),
        measure: humanCol(vc), low },
    };
  });
  // "How have … changed": the table adds the change from the previous period
  // (only when the question asks how a figure moved — never by default).
  return {
    kind: 'multi', charts, defType, data, change: isTime && asksChange(question),
    ranked: asksRanking(question) && !isTime && !allLbl.some((c) => hasSegment(c, RANK_WORDS_COL)),
    ...(many ? { note: `${low ? 'Bottom' : 'Top'} 15 of ${many} shown; the full list is in the table.` } : {}),
    ...(unranked ? { note: `${unranked} of ${data.length} ${unranked === 1 ? 'has' : 'have'} no figure for ${humanCol(numCols[0])} and ${unranked === 1 ? 'is' : 'are'} left out of the ranking (they are in the table).` } : {}),
    ...(partOfWhole ? { types: ['bar', 'pie', 'doughnut', ...(isTime ? ['line'] : [])] }
      : { types: whyNot === 'scheme' || !isTime ? ['bar'] : ['bar', 'line'], noAddWhy: whyNot }),
  };
}
