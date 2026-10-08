import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Chart from 'chart.js/auto';
import { pivotStacked } from '../analytics.js';

/* Chart.js rendering with the purple palette of web/ai_query.html. Each canvas
   owns its chart: created on mount, rebuilt when the type changes, destroyed on
   unmount, so replaying a thread never leaks or loses a chart.

   Every chart and table card has an Expand button (D-042): it opens the same
   data full screen. An expanded chart uses the full labels, and a bar chart
   with many categories turns horizontal and grows one row per category, so
   100+ villages stay readable. An expanded table can be searched and sorted. */

const PAL2 = ['#5C2D91', '#7C3FBF', '#9558CF', '#B27FE0', '#CFA8EE', '#E5D2F6', '#8bbff3', '#b8d8f8'];
const CHART_TOOLTIP = {
  backgroundColor: 'rgba(36,16,56,.96)', titleColor: '#F4EBFC', bodyColor: 'rgba(244,235,252,.9)',
  padding: 12, cornerRadius: 6, borderColor: 'rgba(255,255,255,.12)', borderWidth: 1,
  titleFont: { family: 'Inter', size: 12, weight: '700' }, bodyFont: { family: 'Inter', size: 12 },
  callbacks: { label: (ctx) => '  ' + Number(ctx.raw).toLocaleString('en-IN') },
};
const LOPT = {
  responsive: true, maintainAspectRatio: false,
  animation: { duration: 600, easing: 'easeOutQuart' },
  plugins: {
    legend: { labels: { font: { family: 'Inter', size: 12, weight: '500' }, padding: 16, usePointStyle: true, pointStyle: 'circle', color: '#1A1626' } },
    tooltip: CHART_TOOLTIP,
  },
};
const AXIS = {
  grid: { color: 'rgba(92,45,145,.06)', drawBorder: false },
  ticks: { font: { family: 'Inter', size: 11, weight: '500' }, color: '#857E96', padding: 8 },
  border: { display: false },
};
const AOPT = {
  responsive: true, maintainAspectRatio: false,
  animation: { duration: 600, easing: 'easeOutQuart' },
  plugins: { legend: { display: false }, tooltip: CHART_TOOLTIP },
  scales: { x: AXIS, y: AXIS },
};
const LEGEND_ON = { display: true, labels: { font: { family: 'Inter', size: 11, weight: '600' }, color: '#1A1626', padding: 14 } };

// An expanded bar chart with more categories than this turns horizontal.
const HORIZONTAL_FROM = 12;
const ROW_PX = 24;

// Horizontal bars: categories on the y axis, every label shown, values on x.
function horizontal(options) {
  return {
    ...options,
    indexAxis: 'y',
    scales: {
      x: { ...options.scales.x },
      y: { ...options.scales.y, ticks: { ...AXIS.ticks, autoSkip: false } },
    },
  };
}

function singleConfig(type, labels, values, expanded = false) {
  if (type === 'bar') {
    const flat = expanded && labels.length > HORIZONTAL_FROM;
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: flat ? '#7C3FBF' : (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 220);
            g.addColorStop(0, '#5C2D91'); g.addColorStop(1, '#9558CF');
            return g;
          },
          borderRadius: 5, borderWidth: 0,
        }],
      },
      options: flat ? horizontal(AOPT) : { ...AOPT },
    };
  }
  if (type === 'doughnut' || type === 'pie') {
    return {
      type,
      data: {
        labels,
        datasets: [{
          data: values, backgroundColor: labels.map((_, i) => PAL2[i % PAL2.length]),
          borderWidth: 2, borderColor: '#fff', ...(type === 'doughnut' ? { cutout: '65%' } : {}),
        }],
      },
      options: { ...LOPT, plugins: { ...LOPT.plugins, legend: { ...LOPT.plugins.legend, position: 'right' } } },
    };
  }
  return {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data: values, borderColor: '#5C2D91', borderWidth: 2.5, backgroundColor: 'rgba(92,45,145,.10)',
        tension: 0.4, fill: true, pointRadius: 4, pointBackgroundColor: '#fff', pointBorderColor: '#5C2D91', pointBorderWidth: 2,
      }],
    },
    options: { ...AOPT, plugins: { legend: { display: false }, tooltip: CHART_TOOLTIP } },
  };
}

function groupedConfig(labels, datasets, expanded = false) {
  const options = { ...AOPT, plugins: { ...AOPT.plugins, legend: LEGEND_ON } };
  return {
    type: 'bar',
    data: { labels, datasets: datasets.map((d, i) => ({ label: d.label, data: d.values, backgroundColor: PAL2[i % PAL2.length], borderRadius: 4, borderWidth: 0 })) },
    options: expanded && labels.length > HORIZONTAL_FROM ? horizontal(options) : options,
  };
}

function stackedConfig(labels, datasets, expanded = false) {
  let options = { ...AOPT, plugins: { ...AOPT.plugins, legend: LEGEND_ON } };
  if (expanded && labels.length > HORIZONTAL_FROM) options = horizontal(options);
  options = { ...options, scales: { x: { ...options.scales.x, stacked: true }, y: { ...options.scales.y, stacked: true } } };
  return {
    type: 'bar',
    data: { labels, datasets: datasets.map((d, i) => ({ label: d.label, data: d.data, backgroundColor: PAL2[i % PAL2.length], borderRadius: 3, borderWidth: 0 })) },
    options,
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

// A chart card with Bar / Pie / Donut (/ Line) toggles, like the original swDyn().
export function SwitchableChart({ title, labels, fullLabels, values, types, initial }) {
  const [type, setType] = useState(types.includes(initial) ? initial : types[0]);
  const [open, setOpen] = useState(false);
  const full = fullLabels || labels;
  const flat = type === 'bar' && full.length > HORIZONTAL_FROM;
  return (
    <div className="dyn-chart-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <div className="chd-right">
          <TypeToggles types={types} type={type} setType={setType} />
          <ExpandButton label="chart" onClick={() => setOpen(true)} />
        </div>
      </div>
      <div className="chw"><ChartCanvas build={() => singleConfig(type, labels, values)} deps={[type, labels, values]} /></div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <div className="xv-toolbar"><TypeToggles types={types} type={type} setType={setType} /></div>
          <ExpandedChart build={() => singleConfig(type, full, values, true)} deps={[type, full, values]}
                         rows={flat ? full.length : 0} />
        </ExpandModal>
      )}
    </div>
  );
}

export function GroupedChart({ title, labels, fullLabels, datasets }) {
  const [open, setOpen] = useState(false);
  const full = fullLabels || labels;
  return (
    <div className="dyn-chart-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <div className="chd-right">
          <span className="chd-pill">Grouped Bar</span>
          <ExpandButton label="chart" onClick={() => setOpen(true)} />
        </div>
      </div>
      <div className="chw" style={{ height: 280 }}><ChartCanvas build={() => groupedConfig(labels, datasets)} deps={[labels, datasets]} /></div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <ExpandedChart build={() => groupedConfig(full, datasets, true)} deps={[full, datasets]}
                         rows={full.length > HORIZONTAL_FROM ? full.length * Math.max(1, datasets.length * 0.6) : 0} />
        </ExpandModal>
      )}
    </div>
  );
}

export function StackedChart({ title, labels, datasets }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="dyn-chart-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <div className="chd-right">
          <span className="chd-pill">Stacked Bar</span>
          <ExpandButton label="chart" onClick={() => setOpen(true)} />
        </div>
      </div>
      <div className="chw" style={{ height: 320 }}><ChartCanvas build={() => stackedConfig(labels, datasets)} deps={[labels, datasets]} /></div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <ExpandedChart build={() => stackedConfig(labels, datasets, true)} deps={[labels, datasets]}
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
      <ExpandButton label={label} onClick={onExpand} />
    </div>
  );
}

function BigTable({ data, cols }) {
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
          <BigTable data={data} cols={cols} />
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
