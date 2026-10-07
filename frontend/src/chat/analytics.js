/* Decides how a DATA answer's rows are shown: a KPI chart, a record card, a
   plain table, grouped / stacked bars, or up to three switchable charts plus the
   table. The rules are moved verbatim from buildAnalytics() in
   web/ai_query.html; the React components render the descriptor this returns. */

const label18 = (v) => (String(v).length > 18 ? String(v).slice(0, 16) + '…' : String(v));

// A column is a MEASURE only if every value is a plain number. parseFloat() is
// too lenient: parseFloat("2017-08-01") === 2017 would chart a date column.
const isNumeric = (v) => v !== null && v !== '' && v !== undefined
  && /^-?\d+(?:,\d{3})*(?:\.\d+)?$/.test(String(v).trim());

export function pivotStacked(data, xKey, sKey, vKey) {
  const xLabels = [...new Set(data.map((r) => r[xKey]))];
  const sLabels = [...new Set(data.map((r) => r[sKey]))];
  const datasets = sLabels.map((sl) => ({
    label: sl,
    data: xLabels.map((xl) => {
      const row = data.find((r) => r[xKey] === xl && r[sKey] === sl);
      return row ? Number(row[vKey]) : 0;
    }),
  }));
  return { labels: xLabels, datasets };
}

export function buildAnalytics(question, rawData, hintType) {
  if (!Array.isArray(rawData) || rawData.length === 0) return null;
  const data = rawData.slice();

  if (data.length === 1 && hintType === 'kpi_bar') {
    const row = data[0];
    // Chart the compared parts only: when the row carries a derived total equal
    // to the sum of the parts, its bar would dwarf the comparison. The record
    // card below still shows every column.
    let keys = Object.keys(row);
    const isTotalKey = (k) => /(^|_)(total|overall|sum)(_|$)/i.test(k);
    const totalKeys = keys.filter(isTotalKey);
    if (keys.length >= 3 && totalKeys.length === 1) {
      const parts = keys.filter((k) => k !== totalKeys[0]);
      const tv = parseFloat(row[totalKeys[0]]);
      const psum = parts.reduce((s, k) => s + (parseFloat(row[k]) || 0), 0);
      if (isFinite(tv) && psum > 0 && Math.abs(tv - psum) <= Math.max(1, Math.abs(tv) * 0.001)) keys = parts;
    }
    return {
      kind: 'kpi',
      labels: keys.map((k) => k.replace(/_/g, ' ')),
      values: keys.map((k) => parseFloat(row[k]) || 0),
      row,
    };
  }

  if (data.length === 1) return { kind: 'record', row: data[0] };

  const cols = Object.keys(data[0]);
  const numCols = cols.filter((c) => {
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
  const isTime = /month|period|year|date|trend/i.test(lc) || /year|month|trend/i.test(question);
  // A trend reads left-to-right: sort ISO dates / plain years (the table follows).
  if (isTime && data.every((r) => /^\d{4}(-\d{2}(-\d{2})?)?$/.test(String(r[lc] ?? '').trim()))) {
    data.sort((a, b) => String(a[lc]).localeCompare(String(b[lc])));
  }
  const isFew = data.length <= 6;
  const defType = (hintType === 'bar' || hintType === 'doughnut' || hintType === 'line')
    ? hintType : (isTime ? 'line' : isFew ? 'doughnut' : 'bar');

  if (hintType === 'grouped_bar') {
    return {
      kind: 'grouped',
      title: `Grouped comparison by ${lc.replace(/_/g, ' ')}`,
      labels: data.map((r) => label18(r[lc])),
      datasets: numCols.map((nc) => ({ label: nc.replace(/_/g, ' '), values: data.map((r) => parseFloat(r[nc]) || 0) })),
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
      title: `${vKey.replace(/_/g, ' ')} by ${xKey.replace(/_/g, ' ')} & ${sKey.replace(/_/g, ' ')}`,
      labels, datasets, data, xKey, sKey, vKey,
    };
  }

  const charts = numCols.slice(0, 3).map((vc) => ({
    title: `${vc.replace(/_/g, ' ')} by ${lc.replace(/_/g, ' ')}`,
    labels: data.map((r) => label18(r[lc])),
    values: data.map((r) => parseFloat(r[vc]) || 0),
  }));
  return { kind: 'multi', charts, defType, data };
}
