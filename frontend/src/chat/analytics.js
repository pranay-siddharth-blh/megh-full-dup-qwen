/* Decides how a DATA answer's rows are shown: a KPI chart, a record card, a
   plain table, grouped / stacked bars, or up to three switchable charts plus the
   table. The rules are moved verbatim from buildAnalytics() in
   web/ai_query.html; the React components render the descriptor this returns. */

import { hasSegment, isAsciiLetter, isDigit, isPeriodLabel, isPlainNumber, isSpace, splitSpaces } from './text.js';

// At most this many series (schemes, districts) share one chart; past it the two
// label columns are joined into one axis label instead ("MGNREGA · 2023-24").
const MAX_SERIES = 8;
const PERIOD_WORDS = ['year', 'yr', 'fy', 'month', 'period', 'date', 'quarter'];

const label18 = (v) => (String(v).length > 18 ? String(v).slice(0, 16) + '…' : String(v));

// A column is a MEASURE only if every value is a plain number. parseFloat() is
// too lenient: parseFloat("2017-08-01") === 2017 would chart a date column.
const isNumeric = (v) => v !== null && v !== '' && v !== undefined
  && isPlainNumber(String(v).trim());
// Numbers that are labels, not measures: year_key 2024, an LGD code, an id.
// Kept in step with pipeline._CHART_LABEL_COL.
const LABEL_WORDS = ['year', 'yr', 'fy', 'code', 'id', 'lgd', 'pin', 'pincode', 'key', 'rank', 'sl', 'serial'];
const isLabelCol = (k) => hasSegment(k, LABEL_WORDS);   // one '_'-separated part of the name, any case
const toNumber = (v) => (isNumeric(v) ? Number(String(v).trim().replaceAll(',', '')) : 0);
// "2024", "2024-03" or "2024-03-15"
const isYearOrIsoDate = (s) => (s.length === 4 || s.length === 7 || s.length === 10)
  && Array.from(s).every((c, i) => ((i === 4 || i === 7) ? c === '-' : isDigit(c)));
const mentionsAny = (s, words) => { const low = String(s).toLowerCase(); return words.some((w) => low.includes(w)); };
// The chart types the backend can ask for (pipeline._chart_hint, D-042).
const SINGLE_TYPES = ['bar', 'pie', 'doughnut', 'line'];

/** The one-line verdict under a two-way comparison: who leads, by how much.
    { lead, trail, pct, diff, measure } or { equal: true, value, measure }.
    pct is null when the trailing value is 0 (nothing to divide by). */
export function compareVerdict(l1, v1, l2, v2, measure) {
  if (v1 === v2) return { equal: true, value: v1, measure };
  const [lead, lv, trail, tv] = v1 > v2 ? [l1, v1, l2, v2] : [l2, v2, l1, v1];
  const diff = lv - tv;
  const pct = tv > 0 ? Math.round((diff / tv) * 100) : null;
  return { lead, trail, pct, diff, measure };
}

// A column name as words for a chart title: "total_exp_lakh" -> "total expenditure
// (₹ lakh)", "lgd_district" -> "district". Codes in names are spelled out; the
// rest only loses its underscores.
const COL_WORDS = { lgd: '', exp: 'expenditure', amt: 'amount', cnt: 'count', qty: 'quantity', hh: 'households',
  lakh: '(₹ lakh)', lakhs: '(₹ lakh)', cr: '(₹ crore)', crore: '(₹ crore)', rupees: '(₹)', rs: '(₹)', fy: 'FY',
  pct: '%', perc: '%', avg: 'average', yr: 'year' };
export const humanCol = (c) => String(c).split('_').map((w) => (w.toLowerCase() in COL_WORDS ? COL_WORDS[w.toLowerCase()] : w))
  .filter(Boolean).join(' ') || String(c);

export function pivotStacked(data, xKey, sKey, vKey) {
  const xLabels = [...new Set(data.map((r) => r[xKey]))];
  const sLabels = [...new Set(data.map((r) => r[sKey]))];
  const datasets = sLabels.map((sl) => ({
    label: sl,
    data: xLabels.map((xl) => {
      const row = data.find((r) => r[xKey] === xl && r[sKey] === sl);
      return row ? toNumber(row[vKey]) : 0;
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
  const data = rawData.slice();
  if (isCrossSummary(data)) {
    const cs = crossSummaryCharts(data);
    if (cs) return cs;
  }

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

  const cols = Object.keys(data[0]);
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
      const vc = numCols[0];
      return {
        kind: 'compare',
        title: `${l1} vs ${l2}`,
        measure: humanCol(vc),
        a: { label: l1, value: toNumber(r1[vc]) },
        b: { label: l2, value: toNumber(r2[vc]) },
        verdict: compareVerdict(l1, toNumber(r1[vc]), l2, toNumber(r2[vc]), humanCol(vc)),
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
  // A trend reads left-to-right: sort ISO dates / plain years (the table follows).
  if (isTime && data.every((r) => isYearOrIsoDate(String(r[lc] ?? '').trim()))) {
    data.sort((a, b) => String(a[lc]).localeCompare(String(b[lc])));
  }
  const isFew = data.length <= 6;
  const defType = SINGLE_TYPES.includes(hintType)
    ? hintType : (isTime ? 'line' : isFew ? 'doughnut' : 'bar');

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
  }));
  return { kind: 'multi', charts, defType, data };
}
