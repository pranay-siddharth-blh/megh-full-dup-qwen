/* Decides how a DATA answer's rows are shown: a KPI chart, a record card, a
   plain table, grouped / stacked bars, or up to three switchable charts plus the
   table. The rules are moved verbatim from buildAnalytics() in
   web/ai_query.html; the React components render the descriptor this returns. */

import { hasSegment, isDigit, isPlainNumber } from './text.js';

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

export function buildAnalytics(question, rawData, hintType) {
  if (!Array.isArray(rawData) || rawData.length === 0) return null;
  const data = rawData.slice();

  // One row of several figures: a bar (or the pie / donut asked for) per figure.
  const oneRowTypes = ['kpi_bar', 'bar', 'pie', 'doughnut'];
  if (data.length === 1 && oneRowTypes.includes(hintType)) {
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
      labels: keys.map((k) => k.replaceAll('_', ' ')),
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
  const isTime = mentionsAny(lc, ['month', 'period', 'year', 'date', 'trend'])
    || mentionsAny(question, ['year', 'month', 'trend']);
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
      title: `Grouped comparison by ${lc.replaceAll('_', ' ')}`,
      labels: data.map((r) => label18(r[lc])),
      fullLabels: data.map((r) => String(r[lc])),
      datasets: numCols.map((nc) => ({ label: nc.replaceAll('_', ' '), values: data.map((r) => toNumber(r[nc])) })),
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
      title: `${vKey.replaceAll('_', ' ')} by ${xKey.replaceAll('_', ' ')} & ${sKey.replaceAll('_', ' ')}`,
      labels, datasets, data, xKey, sKey, vKey,
    };
  }

  const charts = numCols.slice(0, 3).map((vc) => ({
    title: `${vc.replaceAll('_', ' ')} by ${lc.replaceAll('_', ' ')}`,
    labels: data.map((r) => label18(r[lc])),
    fullLabels: data.map((r) => String(r[lc])),
    values: data.map((r) => toNumber(r[vc])),
  }));
  return { kind: 'multi', charts, defType, data };
}
