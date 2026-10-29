/* Decides how a DATA answer's rows are shown: a KPI chart, a record card, a
   plain table, grouped / stacked bars, or up to three switchable charts plus the
   table. The rules are moved verbatim from buildAnalytics() in
   web/ai_query.html; the React components render the descriptor this returns. */

import { hasSegment, isAsciiLetter, isDigit, isPeriodLabel, isSpace, splitSpaces } from './text.js';
import {
  PERIOD_WORDS, asksChange, colTitle, humanCol, isAdditive, isLabelCol, isNumeric, tableColumns, unitOf, withoutTwins,
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

/** The one-line verdict under a two-way comparison: who leads, by how much.
    { lead, trail, pct, diff, measure } or { equal: true, value, measure };
    { unlike: true, measure } when the two sides measure different things
    (`unlike`); null when a side has no value. pct is null when the trailing
    value is 0 (nothing to divide by). */
export function compareVerdict(l1, v1, l2, v2, measure, unlike = false) {
  if (unlike) return { unlike: true, measure };
  if (!Number.isFinite(v1) || !Number.isFinite(v2)) return null;
  if (v1 === v2) return { equal: true, value: v1, measure };
  const [lead, lv, trail, tv] = v1 > v2 ? [l1, v1, l2, v2] : [l2, v2, l1, v1];
  const diff = lv - tv;
  const pct = tv > 0 ? Math.round((diff / tv) * 100) : null;
  return { lead, trail, pct, diff, measure };
}

export function pivotStacked(data, xKey, sKey, vKey) {
  const xLabels = [...new Set(data.map((r) => r[xKey]))];
  const sLabels = [...new Set(data.map((r) => r[sKey]))];
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

// A cross-scheme summary (app/cross_scheme.py): one row per scheme with a count,
// what it counts, an amount in rupees and what kind of money. Each measure is its
// own chart — never one axis, since persons employed and houses sanctioned (or
// expenditure and releases) are different things.
const isCrossSummary = (data) => data.length >= 2 && data.every((r) => r && r.scheme !== undefined)
  && ['amount_rupees', 'count_measure', 'money_measure'].some((k) => k in data[0]);

function crossSummaryCharts(data) {
  const charts = [];
  const schemes = data.map((r) => String(r.scheme));
  const withAmount = data.filter((r) => isNumeric(r.amount_rupees));
  if (withAmount.length >= 2) {
    charts.push({
      title: 'Amount (₹ crore) by scheme',
      labels: withAmount.map((r) => label18(r.scheme)),
      fullLabels: withAmount.map((r) => (r.money_measure ? `${r.scheme} — ${r.money_measure}` : String(r.scheme))),
      values: withAmount.map((r) => Math.round(toNumber(r.amount_rupees) / 1e5) / 100),
    });
  }
  const withCount = data.filter((r) => isNumeric(r.count));
  if (withCount.length >= 2) {
    charts.push({
      title: 'Count by scheme',
      labels: withCount.map((r) => label18(r.scheme)),
      fullLabels: withCount.map((r) => (r.count_measure ? `${r.scheme} — ${r.count_measure}` : String(r.scheme))),
      values: withCount.map((r) => toNumber(r.count)),
    });
  }
  return charts.length ? { kind: 'multi', charts, defType: 'bar', data, schemes, noTable: true } : null;
}

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
const colParts = (c) => String(c).toLowerCase().split('_').filter(Boolean);

/** The numeric column whose name matches the one kind of measure (money, or a
    count of people / houses) the question names; null when it names neither,
    both, or no column matches — the caller keeps its first column then. */
export function askedMeasureCol(question, numCols) {
  const w = words(question);
  const money = hasStem(w, MONEY_STEMS);
  const count = hasStem(w, COUNT_STEMS);
  if (money === count) return null;
  const stems = money ? MONEY_COL_STEMS : COUNT_STEMS;
  return numCols.find((c) => hasStem(colParts(c), stems)) || null;
}

/** `prefer` is chartPreference(question) (or 'chart' for /chart): a chart the
    officer asked for. It picks the first chart type, draws a one-row answer
    with several figures as a chart, and skips the two-tile card. */
export function buildAnalytics(question, rawData, hintType, prefer = null) {
  const a = buildAnalyticsCore(question, rawData, hintType, prefer);
  if (!a || !prefer || prefer === 'chart' || prefer === 'table') return a;
  if (a.kind === 'twoDim') return { ...a, defType: prefer === 'pie' ? 'doughnut' : prefer };
  if (a.kind === 'multi' || a.kind === 'kpi') return { ...a, defType: prefer === 'stacked' ? 'bar' : prefer };
  return a;
}

function buildAnalyticsCore(question, rawData, hintType, prefer) {
  if (!Array.isArray(rawData) || rawData.length === 0) return null;
  if (isCrossSummary(rawData)) {
    const cs = crossSummaryCharts(rawData.slice());
    if (cs) return cs;
  }
  // One thing written two ways (year_key 2023 and financial_year "2023-2024") is
  // ONE dimension: read as two, it drew a diagonal grid of dashes (user report
  // 2026-10-28). The readable twin stays; the download keeps every column.
  const data = withoutTwins(rawData).slice();

  // One row of several figures: a bar (or the pie / donut asked for) per figure.
  const oneRowTypes = ['kpi_bar', 'bar', 'pie', 'doughnut'];
  if (data.length === 1 && (oneRowTypes.includes(hintType) || (prefer && prefer !== 'table'))) {
    const row = data[0];
    // Chart the compared parts only: when the row carries a derived total equal
    // to the sum of the parts, its bar would dwarf the comparison. The record
    // card below still shows every column.
    let keys = Object.keys(row).filter((k) => isNumeric(row[k]) && !isLabelCol(k));
    if (keys.length < 2) return { kind: 'record', row };
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
      if (v === null || v === '' || v === undefined) continue;
      if (!isNumeric(v)) return false;
      seen = true;
    }
    return seen;
  });
  const lblCols = cols.filter((c) => !numCols.includes(c));

  if (!numCols.length) return { kind: 'table', data };

  const lc = lblCols[0] || cols[0];

  // Two things side by side (#397): "East Khasi Hills vs West Garo Hills". Two
  // rows, one label column, a measure -> two stat tiles and a one-line verdict
  // instead of a two-slice chart. Extra measures stay in the table below.
  if (data.length === 2 && lblCols.length === 1 && numCols.length <= 3 && !(prefer && prefer !== 'table')) {
    const [r1, r2] = data;
    const l1 = String(r1[lc] ?? '').trim();
    const l2 = String(r2[lc] ?? '').trim();
    if (l1 && l2 && l1 !== l2) {
      const vc = askedMeasureCol(question, numCols) || numCols[0];
      return {
        kind: 'compare',
        title: `${l1} vs ${l2}`,
        measure: humanCol(vc),
        a: { label: l1, value: toNumber(r1[vc]) },
        b: { label: l2, value: toNumber(r2[vc]) },
        verdict: compareVerdict(l1, toNumber(r1[vc]), l2, toNumber(r2[vc]), humanCol(vc), isSchemeCol(lc)),
        data,
        extra: numCols.length > 1,
      };
    }
  }
  // Two label columns and a measure — scheme × financial year, district × year,
  // block × scheme … (user report 2026-10-19: "Expenditure by scheme" drew one
  // line over MGNREGA, MGNREGA, MGNREGA, PMAY-G, … and the year was nowhere to be
  // seen). The period column goes on the x-axis and the other label becomes one
  // coloured series per value, so both dimensions are always visible; with no
  // period column the label with more values is the axis and the other the series.
  if (lblCols.length >= 2 && hintType !== 'grouped_bar' && hintType !== 'stacked') {
    const distinct = (k) => new Set(data.map((r) => String(r[k] ?? ''))).size;
    const isPeriodCol = (c) => hasSegment(c, PERIOD_WORDS)
      || data.every((r) => isPeriodLabel(r[c]));
    const two = lblCols.slice(0, 2);
    let xKey = two.find(isPeriodCol) || null;
    let sKey = xKey ? two.find((c) => c !== xKey) : null;
    if (!xKey) [xKey, sKey] = distinct(two[0]) >= distinct(two[1]) ? two : [two[1], two[0]];
    if (distinct(sKey) > MAX_SERIES && distinct(xKey) <= MAX_SERIES) [xKey, sKey] = [sKey, xKey];
    const vKey = numCols[0];
    if (distinct(sKey) <= MAX_SERIES && distinct(xKey) > 1) {
      if (data.every((r) => isPeriodLabel(r[xKey]))) data.sort((a, b) => String(a[xKey]).localeCompare(String(b[xKey])));
      const { labels, datasets } = pivotStacked(data, xKey, sKey, vKey);
      const periods = labels.every((l) => isPeriodLabel(l));
      return {
        kind: 'twoDim',
        title: `${humanCol(vKey)} by ${humanCol(xKey)} and ${humanCol(sKey)}`,
        xKey, sKey, vKey, labels: labels.map(String), datasets, periods,
        defType: SINGLE_TYPES.includes(hintType) && hintType !== 'pie' ? hintType : (periods ? 'line' : 'bar'),
        data, extra: numCols.length > 1,
        axes: { x: colTitle(xKey), y: colTitle(vKey), unit: unitOf(vKey) },
      };
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
  const isTime = mentionsAny(lc, ['month', 'period', 'year', 'date', 'trend'])
    || data.every((r) => isPeriodLabel(r[lc]) || isYearOrIsoDate(String(r[lc] ?? '').trim()));
  // A trend reads left-to-right: sort ISO dates / plain years / financial years
  // ("2023-24", "FY 2023-24" — these sort as text too); the table follows.
  if (isTime && data.every((r) => isYearOrIsoDate(String(r[lc] ?? '').trim()) || isPeriodLabel(r[lc]))) {
    data.sort((a, b) => String(a[lc]).localeCompare(String(b[lc])));
  }
  const isFew = data.length <= 6;
  // A share, rate or average is not part of a whole: no pie / donut at all.
  const partOfWhole = isAdditive(numCols[0]);
  const noSlices = !partOfWhole || asksRanking(question);
  const hinted = SINGLE_TYPES.includes(hintType) && !(noSlices && (hintType === 'pie' || hintType === 'doughnut'))
    ? hintType : null;
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

  const charts = numCols.slice(0, 3).map((vc) => ({
    title: `${humanCol(vc)} by ${humanCol(lc)}`,
    labels: data.map((r) => label18(r[lc])),
    fullLabels: data.map((r) => String(r[lc])),
    values: data.map((r) => toNumber(r[vc])),
    axes: { x: colTitle(lc), y: colTitle(vc), unit: unitOf(vc) },
  }));
  // "How have … changed": the table adds the change from the previous period
  // (only when the question asks how a figure moved — never by default).
  return {
    kind: 'multi', charts, defType, data, change: isTime && asksChange(question),
    ...(partOfWhole ? {} : { types: ['bar', 'line'] }),
  };
}
