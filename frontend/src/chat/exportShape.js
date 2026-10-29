// H-9 (chat UI audit 2026-10-29): "Download chat -> Excel" wrote the raw long rows
// ("MGNREGA, 2022-23", "PMAY-G, 2022-23" …) while the screen showed a districts ×
// years grid, a two-way card or a "Change from previous" column. The table sheet
// now has the shape on screen; ChatExport keeps the raw rows on a "data" sheet.
import { buildAnalytics, pivotStacked } from './analytics.js';
import { changeColumn, unifyPeriods, withoutTwins } from './columns.js';

/** The rows of the table an answer shows on screen, as objects (one per line). */
export function screenRows(question, data, chartType) {
  const flat = withoutTwins(unifyPeriods(data));
  let a = null;
  try { a = buildAnalytics(question || '', data, chartType || null); } catch (e) { a = null; }
  if (!a) return flat;
  const grid = (xKey, labels, datasets) => labels.map((l, i) => {
    const row = { [xKey]: l };
    for (const d of datasets) row[String(d.label)] = d.data[i];
    return row;
  });
  if (a.kind === 'twoDim' && Array.isArray(a.labels) && Array.isArray(a.datasets)) {
    return grid(a.xKey, a.labels, a.datasets);
  }
  if (a.kind === 'table' && a.pivot) {
    const p = pivotStacked(a.data, a.pivot.xKey, a.pivot.sKey, a.pivot.vKey);
    return grid(a.pivot.xKey, p.labels, p.datasets);
  }
  if (a.kind === 'compare' && a.a && a.b) {
    const both = a.a.value !== null && a.b.value !== null;
    return [
      { compared: a.a.label, [a.vKey]: a.a.value },
      { compared: a.b.label, [a.vKey]: a.b.value },
      ...(both ? [{ compared: `Difference (${a.a.label} − ${a.b.label})`, [a.vKey]: a.a.value - a.b.value }] : []),
    ];
  }
  if (a.change) {
    const ch = changeColumn(flat);
    if (ch) return flat.map((r, i) => ({ ...r, [ch.column]: ch.values[i] }));
  }
  return flat;
}
