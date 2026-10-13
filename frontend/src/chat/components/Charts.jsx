import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Chart from 'chart.js/auto';
import { pivotStacked } from '../analytics.js';
import {
  INK, PLUGINS, alpha, categorySchemeColors, chartAnimation, fmt, fmtCompact, insightFor, ordinalSteps,
  seriesColors, shade, themeFor, wrapLabel,
} from '../chartTheme.js';

/* Chart.js rendering. Each canvas owns its chart: created on mount, rebuilt
   when the type changes, destroyed on unmount, so replaying a thread never
   leaks or loses a chart.

   Look (D-043, chartTheme.js): every chart is drawn in its scheme's hue, the
   largest bar / slice in the full hue and the rest pale, values labelled at
   the bar tips and inside donut slices, the donut's total in its middle, the
   top category's axis label in a dark pill.

   Every chart and table card has an Expand button (D-042): it opens the same
   data full screen. An expanded chart uses the full labels, and a bar chart
   with many categories turns horizontal and grows one row per category, so
   100+ villages stay readable. An expanded table can be searched and sorted. */

const TOOLTIP = {
  backgroundColor: 'rgba(26,22,38,.96)', titleColor: '#ffffff', bodyColor: 'rgba(255,255,255,.88)',
  padding: { x: 12, y: 10 }, cornerRadius: 10, borderWidth: 0, boxPadding: 6, usePointStyle: true,
  titleFont: { family: 'Inter', size: 12, weight: '700' }, bodyFont: { family: 'Inter', size: 12, weight: '500' },
  callbacks: {
    label: (ctx) => {
      const v = ctx.raw != null && typeof ctx.raw === 'object' ? ctx.parsed[ctx.chart.options.indexAxis === 'y' ? 'x' : 'y'] : ctx.raw;
      return `${ctx.dataset.label ? ctx.dataset.label + ': ' : ''}${fmt(v)}`;
    },
  },
};
const ANIM = { duration: 650, easing: 'easeOutQuart' };
const AXIS = {
  grid: { color: INK.grid, drawTicks: false },
  ticks: { font: { family: 'Inter', size: 11, weight: '500' }, color: INK.muted, padding: 8 },
  border: { display: false },
};
const VALUE_AXIS = { ...AXIS, beginAtZero: true, ticks: { ...AXIS.ticks, callback: (v) => fmtCompact(v), maxTicksLimit: 6 } };
const CAT_AXIS = { ...AXIS, grid: { display: false } };
const LEGEND = {
  display: true, position: 'top', align: 'start',
  labels: { font: { family: 'Inter', size: 11.5, weight: '600' }, color: INK.secondary, padding: 14, usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 10, boxHeight: 10 },
};
const base = (extra = {}) => ({
  responsive: true, maintainAspectRatio: false, animation: chartAnimation(),
  layout: { padding: { top: 28, right: 8 } },
  interaction: { mode: 'index', intersect: false },
  ...extra,
});

// An expanded bar chart with more categories than this turns horizontal.
const HORIZONTAL_FROM = 12;
const ROW_PX = 24;
// Every bar is labelled up to this many; past it, only the largest.
const LABEL_ALL_UP_TO = 12;
// A pie / donut shows at most this many slices; the rest fold into "Other".
const MAX_SLICES = 8;

const argMax = (values) => values.reduce((best, v, i) => ((Number(v) || 0) > (Number(values[best]) || 0) ? i : best), 0);

// Horizontal bars: categories on the y axis, every label shown, values on x.
function horizontal(options) {
  return {
    ...options,
    indexAxis: 'y',
    layout: { padding: { top: 6, right: 48 } },
    scales: {
      x: { ...options.scales.y, position: 'top' },
      y: { ...options.scales.x, ticks: { ...CAT_AXIS.ticks, autoSkip: false } },
    },
  };
}

// The pale bars wear a soft vertical wash of the hue; the highlight the full hue.
// When the categories are schemes (`cat`), every bar wears its own scheme's
// hue instead, and the top one is marked by its label pill alone.
const barFill = (theme, hi, flat, cat) => (ctx) => {
  const isHi = ctx.dataIndex === hi;
  const area = ctx.chart.chartArea;
  if (cat) {
    const c = cat[ctx.dataIndex];
    if (!area || flat) return c;
    const g = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, c); g.addColorStop(1, shade(c, 0.22));
    return g;
  }
  if (!area || flat) return isHi ? theme.main : theme.soft;
  const g = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
  if (isHi) { g.addColorStop(0, theme.main); g.addColorStop(1, theme.deep); } else { g.addColorStop(0, theme.softEdge); g.addColorStop(1, theme.soft); }
  return g;
};

function foldSlices(labels, values) {
  if (labels.length <= MAX_SLICES) return { labels, values };
  const order = values.map((v, i) => [Number(v) || 0, i]).sort((a, b) => b[0] - a[0]);
  const keep = order.slice(0, MAX_SLICES - 1).map(([, i]) => i).sort((a, b) => a - b);
  const other = order.slice(MAX_SLICES - 1).reduce((s, [v]) => s + v, 0);
  return { labels: [...keep.map((i) => labels[i]), 'Other'], values: [...keep.map((i) => values[i]), other] };
}

function singleConfig(type, labels, values, theme, expanded = false) {
  if (type === 'bar') {
    const flat = expanded && labels.length > HORIZONTAL_FROM;
    const hi = argMax(values);
    const cat = categorySchemeColors(labels, theme);
    const options = base({
      plugins: {
        legend: { display: false }, tooltip: TOOLTIP,
        meghBarValues: { on: true, keep: hi, indices: labels.length <= LABEL_ALL_UP_TO || flat ? null : [hi] },
        meghHighlightTick: { on: labels.length > 1, index: hi },
        meghTickFit: { on: !flat },
      },
      scales: {
        x: {
          ...CAT_AXIS,
          ticks: {
            ...CAT_AXIS.ticks,
            color: (c) => (c.index === hi && labels.length > 1 ? 'transparent' : INK.muted),
            // Level, wrapped labels where there is room (meghTickFit decides).
            callback(value) { return wrapLabel(this.getLabelForValue(value)); },
          },
        },
        y: VALUE_AXIS,
      },
    });
    if (flat) {
      const h = horizontal(options);
      h.scales.y.ticks.color = (c) => (c.index === hi ? 'transparent' : INK.muted);
      delete h.scales.y.ticks.callback;   // one row per category: never wrapped
      return { type: 'bar', data: { labels, datasets: [{ data: values, backgroundColor: barFill(theme, hi, true, cat), borderRadius: 6, borderSkipped: 'start', maxBarThickness: 18 }] }, options: h, plugins: PLUGINS };
    }
    return {
      type: 'bar',
      data: { labels, datasets: [{ data: values, backgroundColor: barFill(theme, hi, false, cat), hoverBackgroundColor: (c) => (cat ? shade(cat[c.dataIndex], 0.3) : c.dataIndex === hi ? theme.deep : theme.hover), borderRadius: 10, borderSkipped: 'start', maxBarThickness: expanded ? 56 : 42, categoryPercentage: 0.78, barPercentage: 0.92 }] },
      options,
      plugins: PLUGINS,
    };
  }
  if (type === 'doughnut' || type === 'pie') {
    const f = foldSlices(labels, values);
    // Largest slice in the full hue, the rest stepping paler by size.
    const order = f.values.map((v, i) => [Number(v) || 0, i]).sort((a, b) => b[0] - a[0]).map(([, i]) => i);
    const steps = ordinalSteps(theme, f.values.length);
    const colors = new Array(f.values.length);
    order.forEach((i, rank) => { colors[i] = f.labels[i] === 'Other' ? '#D9D4E2' : steps[rank]; });
    // Slices that are schemes wear their scheme's hue, like their bars.
    const cat = categorySchemeColors(f.labels, theme);
    if (cat) f.labels.forEach((l, i) => { colors[i] = l === 'Other' ? '#D9D4E2' : cat[i]; });
    return {
      type,
      data: { labels: f.labels, datasets: [{ data: f.values, backgroundColor: colors, hoverBackgroundColor: colors, hoverOffset: 8, borderWidth: 3, borderColor: INK.surface, borderRadius: type === 'doughnut' ? 8 : 4, spacing: type === 'doughnut' ? 2 : 0 }] },
      options: base({
        layout: { padding: 8 },
        interaction: { mode: 'nearest', intersect: true },
        ...(type === 'doughnut' ? { cutout: '62%' } : {}),
        plugins: {
          legend: { ...LEGEND, position: 'right', align: 'center', labels: { ...LEGEND.labels, pointStyle: 'circle', padding: 12 } },
          // A donut names the slice under the pointer in its middle, so a
          // tooltip on top of it would only repeat it; a pie keeps its tooltip.
          tooltip: type === 'doughnut' ? { enabled: false } : TOOLTIP,
          meghSliceLabels: { on: true, centerTotal: type === 'doughnut' },
          meghLegendFit: { on: true },
        },
      }),
      plugins: PLUGINS,
    };
  }
  return {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values, borderColor: theme.main, borderWidth: 2.5, tension: 0.35, fill: 'origin',
        backgroundColor: (ctx) => {
          const area = ctx.chart.chartArea;
          if (!area) return alpha(theme.main, 0.12);
          const g = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
          g.addColorStop(0, alpha(theme.main, 0.28)); g.addColorStop(1, alpha(theme.main, 0.02));
          return g;
        },
        pointRadius: (c) => (c.dataIndex === values.length - 1 ? 5 : 0),
        pointHoverRadius: 6, pointBackgroundColor: theme.main, pointBorderColor: INK.surface, pointBorderWidth: 2,
      }],
    },
    options: base({
      plugins: { legend: { display: false }, tooltip: TOOLTIP, meghLineEnd: { on: true }, meghCrosshair: { on: true, color: theme.deep } },
      scales: { x: CAT_AXIS, y: VALUE_AXIS },
    }),
    plugins: PLUGINS,
  };
}

function groupedConfig(labels, datasets, theme, expanded = false) {
  const colors = seriesColors(datasets.map((d) => d.label), theme);
  const options = base({
    plugins: { legend: LEGEND, tooltip: TOOLTIP, meghBarValues: { on: labels.length * datasets.length <= 16 } },
    scales: { x: CAT_AXIS, y: VALUE_AXIS },
  });
  return {
    type: 'bar',
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        label: d.label, data: d.values, backgroundColor: colors[i],
        borderRadius: 6, borderSkipped: 'start', maxBarThickness: 26, categoryPercentage: 0.72, barPercentage: 0.86,
      })),
    },
    options: expanded && labels.length > HORIZONTAL_FROM ? horizontal(options) : options,
    plugins: PLUGINS,
  };
}

// A stack of years is ordered: shades of the scheme hue, oldest palest. Any
// other second label gets the categorical colours in their fixed order.
const isYearish = (label) => /^(?:FY\s*)?\d{4}(?:\s*-\s*\d{2,4})?$/i.test(String(label).trim());

function stackedConfig(labels, datasets, theme, expanded = false) {
  let options = base({
    plugins: { legend: LEGEND, tooltip: TOOLTIP, meghBarValues: { on: labels.length <= LABEL_ALL_UP_TO, stackTotals: true } },
    scales: { x: CAT_AXIS, y: VALUE_AXIS },
  });
  if (expanded && labels.length > HORIZONTAL_FROM) options = horizontal(options);
  options = { ...options, scales: { x: { ...options.scales.x, stacked: true }, y: { ...options.scales.y, stacked: true } } };
  const ordered = datasets.length > 1 && datasets.every((d) => isYearish(d.label));
  const colors = ordered ? ordinalSteps(theme, datasets.length).reverse() : seriesColors(datasets.map((d) => d.label), theme);
  return {
    type: 'bar',
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        label: d.label, data: d.data, backgroundColor: colors[i % colors.length],
        borderRadius: 4, borderSkipped: false, borderWidth: { top: 2 }, borderColor: INK.surface,
        maxBarThickness: 44, categoryPercentage: 0.78,
      })),
    },
    options,
    plugins: PLUGINS,
  };
}

// One canvas, one chart; `config` is rebuilt whenever `deps` change.
function ChartCanvas({ build, deps }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return undefined;
    let chart;
    try { chart = new Chart(ref.current, build()); } catch (e) { console.error('Chart init failed:', e); }
    return () => { try { chart && chart.destroy(); } catch (e) { /* ignore */ } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return <canvas ref={ref} />;
}

// ── Expand view ─────────────────────────────────────────────────────────────

function ExpandButton({ label, onClick }) {
  return (
    <button type="button" className="xv-btn" onClick={onClick} title={`Expand ${label}`} aria-label={`Expand ${label}`}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" />
        <line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
      </svg>
    </button>
  );
}

// Full-screen dialog: Esc or the backdrop closes it, focus returns to the
// button that opened it, and the page behind does not scroll.
function ExpandModal({ title, onClose, children }) {
  const closeRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  useEffect(() => {
    const opener = document.activeElement;
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); onCloseRef.current(); }
    };
    document.addEventListener('keydown', onKey, true);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    if (closeRef.current) closeRef.current.focus();
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.body.style.overflow = overflow;
      if (opener && typeof opener.focus === 'function') opener.focus();
    };
  }, []);
  return createPortal(
    <div className="xv-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onCloseRef.current(); }}>
      <div className="xv-panel" role="dialog" aria-modal="true" aria-label={title}>
        <div className="xv-head">
          <div className="xv-title">{title}</div>
          <button ref={closeRef} type="button" className="xv-close" onClick={() => onCloseRef.current()}
                  aria-label="Close" title="Close (Esc)">&times;</button>
        </div>
        <div className="xv-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

// An expanded chart: fills the panel, or grows one row per category when the
// chart is horizontal (the panel body scrolls).
function ExpandedChart({ build, deps, rows }) {
  const style = rows ? { height: Math.max(420, rows * ROW_PX + 60) } : { height: '100%', minHeight: 420 };
  return <div className="xv-chart" style={style}><ChartCanvas build={build} deps={deps} /></div>;
}

const TYPE_LABELS = { bar: 'Bar', pie: 'Pie', doughnut: 'Donut', line: 'Line' };

function TypeToggles({ types, type, setType }) {
  return (
    <div className="qctog">
      {types.map((t) => (
        <button key={t} type="button" className={'ctb' + (type === t ? ' on' : '')} onClick={() => setType(t)}>
          {TYPE_LABELS[t]}
        </button>
      ))}
    </div>
  );
}

const DEFAULT_THEME = themeFor([]);

// The card header: a dot in the chart's hue, the title, and the scheme name
// (so a scheme is never told by colour alone), then one line saying what to
// look at (insightFor).
function CardHead({ title, theme, insight, children }) {
  return (
    <>
      <div className="chd">
        <div className="chd-left">
          <span className="chd-dot" style={{ background: theme.main, boxShadow: `0 0 0 3px ${alpha(theme.main, 0.16)}` }} />
          <span className="chd-title">{title}</span>
          {theme.label && <span className="chd-scheme" title={theme.labelFull || theme.label}>{theme.label}</span>}
        </div>
        <div className="chd-right">{children}</div>
      </div>
      {insight && <div className="chd-insight">{insight}</div>}
    </>
  );
}

// The card's top edge carries the scheme hue (CSS: .dyn-chart-card::before).
const cardStyle = (theme) => ({ '--chart-accent': theme.main, '--chart-accent-2': theme.deep });

// A chart card with Bar / Pie / Donut (/ Line) toggles, like the original swDyn().
export function SwitchableChart({ title, labels, fullLabels, values, types, initial, theme = DEFAULT_THEME }) {
  const [type, setType] = useState(types.includes(initial) ? initial : types[0]);
  const [open, setOpen] = useState(false);
  const full = fullLabels || labels;
  const flat = type === 'bar' && full.length > HORIZONTAL_FROM;
  const insight = useMemo(() => insightFor(type, full, values), [type, full, values]);
  return (
    <div className="dyn-chart-card" style={cardStyle(theme)}>
      <CardHead title={title} theme={theme} insight={insight}>
        <TypeToggles types={types} type={type} setType={setType} />
        <ExpandButton label="chart" onClick={() => setOpen(true)} />
      </CardHead>
      <div className="chw"><ChartCanvas build={() => singleConfig(type, labels, values, theme)} deps={[type, labels, values, theme]} /></div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <div className="xv-toolbar"><TypeToggles types={types} type={type} setType={setType} /></div>
          <ExpandedChart build={() => singleConfig(type, full, values, theme, true)} deps={[type, full, values, theme]}
                         rows={flat ? full.length : 0} />
        </ExpandModal>
      )}
    </div>
  );
}

export function GroupedChart({ title, labels, fullLabels, datasets, theme = DEFAULT_THEME }) {
  const [open, setOpen] = useState(false);
  const full = fullLabels || labels;
  return (
    <div className="dyn-chart-card" style={cardStyle(theme)}>
      <CardHead title={title} theme={theme}>
        <span className="chd-pill">Grouped Bar</span>
        <ExpandButton label="chart" onClick={() => setOpen(true)} />
      </CardHead>
      <div className="chw" style={{ height: 300 }}><ChartCanvas build={() => groupedConfig(labels, datasets, theme)} deps={[labels, datasets, theme]} /></div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <ExpandedChart build={() => groupedConfig(full, datasets, theme, true)} deps={[full, datasets, theme]}
                         rows={full.length > HORIZONTAL_FROM ? full.length * Math.max(1, datasets.length * 0.6) : 0} />
        </ExpandModal>
      )}
    </div>
  );
}

export function StackedChart({ title, labels, datasets, theme = DEFAULT_THEME }) {
  const [open, setOpen] = useState(false);
  // The column with the largest total, the stack's headline.
  const insight = useMemo(() => {
    const totals = labels.map((_, j) => datasets.reduce((s, d) => s + (Number(d.data[j]) || 0), 0));
    return totals.length > 1 ? insightFor('bar', labels, totals).replace('Highest:', 'Highest total:') : '';
  }, [labels, datasets]);
  return (
    <div className="dyn-chart-card" style={cardStyle(theme)}>
      <CardHead title={title} theme={theme} insight={insight}>
        <span className="chd-pill">Stacked Bar</span>
        <ExpandButton label="chart" onClick={() => setOpen(true)} />
      </CardHead>
      <div className="chw" style={{ height: 340 }}><ChartCanvas build={() => stackedConfig(labels, datasets, theme)} deps={[labels, datasets, theme]} /></div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <ExpandedChart build={() => stackedConfig(labels, datasets, theme, true)} deps={[labels, datasets, theme]}
                         rows={labels.length > HORIZONTAL_FROM ? labels.length : 0} />
        </ExpandModal>
      )}
    </div>
  );
}

// ── Tables ──────────────────────────────────────────────────────────────────
// Every row the API returned is rendered; .rtwrap scrolls, so a long table
// costs height, not readability. Expand opens it full screen with search and
// sortable columns.

const NUMERIC = /^-?\d+(?:,\d{3})*(?:\.\d+)?$/;
const asNumber = (v) => (v !== null && v !== undefined && NUMERIC.test(String(v).trim())
  ? Number(String(v).replace(/,/g, '')) : null);

function compareCells(a, b) {
  const blankA = a === null || a === undefined || a === '';
  const blankB = b === null || b === undefined || b === '';
  if (blankA || blankB) return blankA === blankB ? 0 : (blankA ? 1 : -1);   // blanks last
  const na = asNumber(a);
  const nb = asNumber(b);
  if (na !== null && nb !== null) return na - nb;
  return String(a).localeCompare(String(b), 'en-IN', { numeric: true, sensitivity: 'base' });
}

const colLabel = (c) => c.replace(/_/g, ' ');

function TableBar({ count, label, onExpand }) {
  return (
    <div className="rt-bar">
      <span className="rt-count">{count.toLocaleString('en-IN')} {count === 1 ? 'row' : 'rows'}</span>
      <div className="rt-actions">
        {onExpand && <ExpandButton label={label} onClick={onExpand} />}
      </div>
    </div>
  );
}

function BigTable({ data, cols, title = 'Result table' }) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState({ col: null, dir: 1 });
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const out = needle
      ? data.filter((r) => cols.some((c) => String(r[c] ?? '').toLowerCase().includes(needle)))
      : data.slice();
    if (sort.col) out.sort((a, b) => compareCells(a[sort.col], b[sort.col]) * sort.dir);
    return out;
  }, [data, cols, query, sort]);
  const toggleSort = (c) => setSort((s) => (s.col === c ? { col: c, dir: -s.dir } : { col: c, dir: 1 }));
  return (
    <>
      <div className="xv-toolbar">
        <input className="xv-search" type="search" placeholder="Search this table…" value={query}
               onChange={(e) => setQuery(e.target.value)} aria-label="Search this table" />
        <span className="rt-count">
          {rows.length === data.length
            ? `${data.length.toLocaleString('en-IN')} rows`
            : `${rows.length.toLocaleString('en-IN')} of ${data.length.toLocaleString('en-IN')} rows`}
        </span>
      </div>
      <div className="rtwrap xv-table">
        <table className="rtbl">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c} aria-sort={sort.col === c ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" className="th-sort" onClick={() => toggleSort(c)} title="Sort">
                    {colLabel(c)}<span className="th-arrow">{sort.col === c ? (sort.dir === 1 ? '▲' : '▼') : '↕'}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? '—')}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="rtbl-note">No rows match “{query}”.</div>}
      </div>
    </>
  );
}

export function DynTable({ data, title = 'Result table' }) {
  const [open, setOpen] = useState(false);
  if (!data || !data.length) return null;
  const cols = Object.keys(data[0]);
  return (
    <div className="rt-block">
      <TableBar count={data.length} label="table" onExpand={() => setOpen(true)} />
      <div className="rtwrap">
        <table className="rtbl">
          <thead><tr>{cols.map((c) => <th key={c}>{colLabel(c)}</th>)}</tr></thead>
          <tbody>
            {data.map((r, i) => (
              <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? '—')}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && (
        <ExpandModal title={`${title} — ${data.length.toLocaleString('en-IN')} rows`} onClose={() => setOpen(false)}>
          <BigTable data={data} cols={cols} title={title} />
        </ExpandModal>
      )}
    </div>
  );
}

function PivotGrid({ data, xKey, sKey, vKey, expanded }) {
  const xVals = [...new Set(data.map((r) => r[xKey]))];
  const sVals = [...new Set(data.map((r) => r[sKey]))];
  const lookup = {};
  data.forEach((r) => { lookup[`${r[xKey]}||${r[sKey]}`] = r[vKey]; });
  const rowTotals = {};
  xVals.forEach((x) => { rowTotals[x] = sVals.reduce((s, sv) => s + (parseFloat(lookup[`${x}||${sv}`]) || 0), 0); });
  const colTotals = {};
  sVals.forEach((sv) => { colTotals[sv] = xVals.reduce((s, x) => s + (parseFloat(lookup[`${x}||${sv}`]) || 0), 0); });
  const grand = xVals.reduce((s, x) => s + rowTotals[x], 0);
  return (
    <div className={'rtwrap' + (expanded ? ' xv-table' : '')} style={{ overflowX: 'auto' }}>
      <table className="rtbl">
        <thead>
          <tr>
            <th>{colLabel(xKey)}</th>
            {sVals.map((sv) => <th key={sv}>{sv}</th>)}
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {xVals.map((x) => (
            <tr key={x}>
              <td><strong>{String(x)}</strong></td>
              {sVals.map((sv) => <td key={sv}>{String(lookup[`${x}||${sv}`] ?? '—')}</td>)}
              <td><strong>{rowTotals[x].toLocaleString('en-IN')}</strong></td>
            </tr>
          ))}
          <tr style={{ background: 'var(--p-50)', fontWeight: 600 }}>
            <td><strong>Total</strong></td>
            {sVals.map((sv) => <td key={sv}>{colTotals[sv].toLocaleString('en-IN')}</td>)}
            <td><strong>{grand.toLocaleString('en-IN')}</strong></td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function PivotTable({ data, xKey, sKey, vKey }) {
  const [open, setOpen] = useState(false);
  if (!data || !data.length) return null;
  const rows = new Set(data.map((r) => r[xKey])).size;
  return (
    <div className="rt-block">
      <TableBar count={rows} label="table" onExpand={() => setOpen(true)} />
      <PivotGrid data={data} xKey={xKey} sKey={sKey} vKey={vKey} />
      {open && (
        <ExpandModal title={`${colLabel(vKey)} by ${colLabel(xKey)} & ${colLabel(sKey)}`} onClose={() => setOpen(false)}>
          <PivotGrid data={data} xKey={xKey} sKey={sKey} vKey={vKey} expanded />
        </ExpandModal>
      )}
    </div>
  );
}

export function RecordCard({ row }) {
  const entries = Object.entries(row).filter(([, v]) => v !== null && v !== '' && String(v) !== 'None');
  if (!entries.length) return <DynTable data={[row]} />;
  return (
    <div className="rtwrap" style={{ maxHeight: 'none' }}>
      <table className="rtbl record-card">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}><th style={{ width: '42%' }}>{colLabel(k)}</th><td>{String(v)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export { pivotStacked };
