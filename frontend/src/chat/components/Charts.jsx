import { useEffect, useRef, useState } from 'react';
import Chart from 'chart.js/auto';
import { pivotStacked } from '../analytics.js';

/* Chart.js rendering with the purple palette of web/ai_query.html. Each canvas
   owns its chart: created on mount, rebuilt when the type changes, destroyed on
   unmount, so replaying a thread never leaks or loses a chart. */

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

function singleConfig(type, labels, values) {
  if (type === 'bar') {
    return {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: (ctx) => {
            const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 220);
            g.addColorStop(0, '#5C2D91'); g.addColorStop(1, '#9558CF');
            return g;
          },
          borderRadius: 5, borderWidth: 0,
        }],
      },
      options: { ...AOPT },
    };
  }
  if (type === 'doughnut') {
    return {
      type: 'doughnut',
      data: { labels, datasets: [{ data: values, backgroundColor: PAL2, borderWidth: 2, borderColor: '#fff', cutout: '65%' }] },
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

function groupedConfig(labels, datasets) {
  return {
    type: 'bar',
    data: { labels, datasets: datasets.map((d, i) => ({ label: d.label, data: d.values, backgroundColor: PAL2[i % PAL2.length], borderRadius: 4, borderWidth: 0 })) },
    options: { ...AOPT, plugins: { ...AOPT.plugins, legend: LEGEND_ON } },
  };
}

function stackedConfig(labels, datasets) {
  return {
    type: 'bar',
    data: { labels, datasets: datasets.map((d, i) => ({ label: d.label, data: d.data, backgroundColor: PAL2[i % PAL2.length], borderRadius: 3, borderWidth: 0 })) },
    options: {
      ...AOPT,
      plugins: { ...AOPT.plugins, legend: LEGEND_ON },
      scales: { x: { ...AOPT.scales.x, stacked: true }, y: { ...AOPT.scales.y, stacked: true } },
    },
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

const TYPE_LABELS = { bar: 'Bar', doughnut: 'Donut', line: 'Line' };

// A chart card with Bar / Donut (/ Line) toggles, like the original swDyn().
export function SwitchableChart({ title, labels, values, types, initial }) {
  const [type, setType] = useState(initial);
  return (
    <div className="dyn-chart-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <div className="qctog">
          {types.map((t) => (
            <button key={t} type="button" className={'ctb' + (type === t ? ' on' : '')} onClick={() => setType(t)}>
              {TYPE_LABELS[t]}
            </button>
          ))}
        </div>
      </div>
      <div className="chw"><ChartCanvas build={() => singleConfig(type, labels, values)} deps={[type, labels, values]} /></div>
    </div>
  );
}

export function GroupedChart({ title, labels, datasets }) {
  return (
    <div className="dyn-chart-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <span className="chd-pill">Grouped Bar</span>
      </div>
      <div className="chw" style={{ height: 280 }}><ChartCanvas build={() => groupedConfig(labels, datasets)} deps={[labels, datasets]} /></div>
    </div>
  );
}

export function StackedChart({ title, labels, datasets }) {
  return (
    <div className="dyn-chart-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <span className="chd-pill">Stacked Bar</span>
      </div>
      <div className="chw" style={{ height: 320 }}><ChartCanvas build={() => stackedConfig(labels, datasets)} deps={[labels, datasets]} /></div>
    </div>
  );
}

// ── Tables ──────────────────────────────────────────────────────────────────
// Every row the API returned is rendered; .rtwrap scrolls, so a long table
// costs height, not readability.
export function DynTable({ data }) {
  if (!data || !data.length) return null;
  const cols = Object.keys(data[0]);
  return (
    <div className="rtwrap">
      <table className="rtbl">
        <thead><tr>{cols.map((c) => <th key={c}>{c.replace(/_/g, ' ')}</th>)}</tr></thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? '—')}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PivotTable({ data, xKey, sKey, vKey }) {
  if (!data || !data.length) return null;
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
    <div className="rtwrap" style={{ overflowX: 'auto' }}>
      <table className="rtbl">
        <thead>
          <tr>
            <th>{xKey.replace(/_/g, ' ')}</th>
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

export function RecordCard({ row }) {
  const entries = Object.entries(row).filter(([, v]) => v !== null && v !== '' && String(v) !== 'None');
  if (!entries.length) return <DynTable data={[row]} />;
  return (
    <div className="rtwrap" style={{ maxHeight: 'none' }}>
      <table className="rtbl record-card">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}><th style={{ width: '42%' }}>{k.replace(/_/g, ' ')}</th><td>{String(v)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export { pivotStacked };
