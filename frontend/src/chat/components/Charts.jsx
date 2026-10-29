import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Chart from 'chart.js/auto';
import { pivotStacked, tableColumns } from '../analytics.js';
import { canAdd, changeColumn, colTitle, dimOf, formatCell, isAdditive, isMeasureCol, withoutTwins } from '../columns.js';
import { isPeriodLabel, isPlainNumber } from '../text.js';
import {
  INK, PLUGINS, alpha, categorySchemeColors, chartAnimation, fmt, fmtCompact, fmtUnit, insightFor, insightForSeries, verdictText,
  ordinalSteps, seriesColors, shade, themeFor, wrapLabel,
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

// Axis titles and units (2026-10-28): the value axis says what it counts
// ("Person days", "Total expenditure (₹ lakh)") and the category axis what the
// bars are ("Financial year", "District"). A column already in lakh / crore is
// never abbreviated again ("8,996" on a ₹ lakh axis, not "9K" / "0.1L"); a % axis
// reads "45%". `axes` = { x, y, unit } from analytics.js; no `axes`, no change.
const AXIS_TITLE = { display: true, color: INK.muted, font: { family: 'Inter', size: 11, weight: '600' }, padding: 4 };
const UNIT_TEXT = { pct: (v) => `${fmt(v)}%`, lakh: (v) => `${fmt(v)} lakh`, crore: (v) => `${fmt(v)} crore` };

function withAxes(config, axes) {
  const sc = config && config.options && config.options.scales;
  if (!axes || !sc || config.type === 'doughnut' || config.type === 'pie') return config;
  const valKey = config.options.indexAxis === 'y' ? 'x' : 'y';
  const catKey = valKey === 'y' ? 'x' : 'y';
  const scales = { ...sc };
  if (sc[catKey] && axes.x) scales[catKey] = { ...sc[catKey], title: { ...AXIS_TITLE, text: axes.x } };
  if (sc[valKey] && axes.y) {
    const tick = axes.unit === 'pct' ? UNIT_TEXT.pct : (axes.unit === 'lakh' || axes.unit === 'crore') ? (v) => fmt(v) : null;
    scales[valKey] = { ...sc[valKey], title: { ...AXIS_TITLE, text: axes.y },
      ...(tick ? { ticks: { ...sc[valKey].ticks, callback: tick } } : {}) };
  }
  let { plugins } = config.options;
  const unit = UNIT_TEXT[axes.unit];
  if (unit && plugins && plugins.tooltip && plugins.tooltip.callbacks) {
    plugins = { ...plugins, tooltip: { ...plugins.tooltip, callbacks: { ...plugins.tooltip.callbacks,
      label: (ctx) => {
        const v = ctx.raw != null && typeof ctx.raw === 'object' ? ctx.parsed[valKey] : ctx.raw;
        return `${ctx.dataset.label ? ctx.dataset.label + ': ' : ''}${unit(v)}`;
      } } } };
  }
  return { ...config, options: { ...config.options, scales, plugins } };
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
const isYearish = isPeriodLabel;

// One line per series (scheme × year, district × year): each in its own colour
// with a legend, no fill (two washes would hide each other), the pointer's
// period read across every line (interaction mode index + crosshair).
function multiLineConfig(labels, datasets, theme) {
  const colors = seriesColors(datasets.map((d) => d.label), theme);
  return {
    type: 'line',
    data: {
      labels,
      datasets: datasets.map((d, i) => ({
        label: d.label, data: d.data, borderColor: colors[i], backgroundColor: colors[i],
        borderWidth: 2.5, tension: 0.3, fill: false,
        pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: colors[i], pointBorderColor: INK.surface, pointBorderWidth: 1.5,
      })),
    },
    options: base({
      plugins: { legend: LEGEND, tooltip: TOOLTIP, meghCrosshair: { on: true, color: theme.deep } },
      scales: { x: CAT_AXIS, y: VALUE_AXIS },
    }),
    plugins: PLUGINS,
  };
}

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

// ── Zoom (line charts) ──────────────────────────────────────────────────────
/* A line chart can be zoomed into a stretch of its x-axis and panned along it:
   drag across it with the mouse, Ctrl / ⌘ + scroll, or pinch (trackpad or
   touch screen) to zoom; Shift + drag, a sideways trackpad swipe or a
   one-finger sideways swipe to pan; double-click or Reset to see it all.
   A plain scroll wheel and a vertical swipe still scroll the chat. The view
   is a fractional index range [lo, hi] so wheel and pinch zoom smoothly; the
   axis shows the whole points inside it. */
const ZOOM_FROM = 6;        // fewer points than this: nothing to zoom into
const ZOOM_MIN_SPAN = 2;    // the tightest zoom still shows 3 points

function clampView(lo, hi, n) {
  const last = n - 1;
  const span = Math.max(ZOOM_MIN_SPAN, Math.min(last, hi - lo));
  let a = Math.max(0, Math.min(lo, last - span));
  if (a + span > last) a = last - span;
  return span >= last ? null : [a, a + span];   // null = the whole line
}
// The whole points a view shows: its start and its width rounded (not each
// end), so panning keeps the same number of points on screen.
function shownRange(view, n) {
  const span = Math.round(view[1] - view[0]);
  const lo = Math.max(0, Math.min(n - 1 - span, Math.round(view[0])));
  return [lo, lo + span];
}

function useLineZoom(canvasRef, chartRef, n, on) {
  const [view, setView] = useState(null);
  const viewRef = useRef(null);
  const brushRef = useRef(null);
  viewRef.current = view;
  const zoomable = on && n >= ZOOM_FROM;

  // Apply the view to the chart's x-axis (whole labels, so the axis reads well).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !chart.options.scales || !chart.options.scales.x) return;
    const labels = chart.data.labels || [];
    const x = chart.options.scales.x;
    if (view) { const [lo, hi] = shownRange(view, n); x.min = labels[lo]; x.max = labels[hi]; }
    else { delete x.min; delete x.max; }
    chart.update('none');
  }, [view, n, chartRef]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!zoomable || !canvas) return undefined;
    const area = () => chartRef.current && chartRef.current.chartArea;
    const whole = () => viewRef.current || [0, n - 1];
    // The (fractional) index under a client x, within the current view.
    const indexAt = (clientX) => {
      const a = area(); if (!a) return null;
      const r = canvas.getBoundingClientRect();
      const f = Math.max(0, Math.min(1, (clientX - r.left - a.left) / (a.right - a.left)));
      const [lo, hi] = whole();
      return lo + f * (hi - lo);
    };
    const zoomAt = (clientX, factor) => {
      const [lo, hi] = whole();
      const c = indexAt(clientX); if (c == null) return;
      setView(clampView(c - (c - lo) * factor, c + (hi - c) * factor, n));
    };
    const panBy = (dxPx) => {
      const a = area(); const v = viewRef.current; if (!a || !v) return;
      const shift = (dxPx / (a.right - a.left)) * (v[1] - v[0]);
      setView(clampView(v[0] - shift, v[1] - shift, n));
    };

    const onWheel = (e) => {
      if (e.ctrlKey || e.metaKey) {           // Ctrl/⌘ + wheel, and trackpad pinch
        e.preventDefault();
        zoomAt(e.clientX, Math.exp(e.deltaY * 0.004));
      } else if (viewRef.current && Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();                   // sideways trackpad swipe pans a zoomed line
        panBy(-e.deltaX);
      }
    };

    // Pointers: mouse drag = select a stretch to zoom into (Shift + drag pans);
    // touch: two fingers pinch, one finger swipes sideways to pan.
    const pts = new Map();
    let mode = null; let startX = 0; let lastX = 0; let pinch = null;
    const box = () => brushRef.current;
    const showBrush = (x0, x1) => {
      const b = box(); const a = area(); if (!b || !a) return;
      const r = canvas.getBoundingClientRect();
      const L = Math.max(a.left, Math.min(x0, x1) - r.left); const R = Math.min(a.right, Math.max(x0, x1) - r.left);
      Object.assign(b.style, { display: 'block', left: L + 'px', width: Math.max(0, R - L) + 'px', top: a.top + 'px', height: (a.bottom - a.top) + 'px' });
    };
    const hideBrush = () => { const b = box(); if (b) b.style.display = 'none'; };
    const down = (e) => {
      pts.set(e.pointerId, e.clientX);
      if (e.pointerType === 'mouse') {
        if (e.button !== 0) return;
        mode = e.shiftKey && viewRef.current ? 'pan' : 'brush';
        startX = lastX = e.clientX;
        canvas.setPointerCapture(e.pointerId);
      } else if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        pinch = { d: Math.abs(a - b) || 1, view: whole(), mid: (a + b) / 2 };
        mode = 'pinch';
      } else if (pts.size === 1) {
        mode = viewRef.current ? 'pan' : null; lastX = e.clientX;
      }
    };
    const move = (e) => {
      if (!pts.has(e.pointerId)) return;
      pts.set(e.pointerId, e.clientX);
      if (mode === 'brush') { if (Math.abs(e.clientX - startX) > 4) showBrush(startX, e.clientX); }
      else if (mode === 'pan') { panBy(e.clientX - lastX); lastX = e.clientX; }
      else if (mode === 'pinch' && pts.size === 2) {
        const [a, b] = [...pts.values()];
        const factor = pinch.d / (Math.abs(a - b) || 1);
        const [lo, hi] = pinch.view;
        const rr = canvas.getBoundingClientRect(); const ar = area(); if (!ar) return;
        const f = Math.max(0, Math.min(1, (pinch.mid - rr.left - ar.left) / (ar.right - ar.left)));
        const c = lo + f * (hi - lo);
        setView(clampView(c - (c - lo) * factor, c + (hi - c) * factor, n));
      }
    };
    const up = (e) => {
      pts.delete(e.pointerId);
      if (mode === 'brush') {
        hideBrush();
        if (Math.abs(e.clientX - startX) > 8) {
          const a = indexAt(Math.min(startX, e.clientX)); const b = indexAt(Math.max(startX, e.clientX));
          if (a != null && b != null) setView(clampView(Math.floor(a), Math.ceil(b), n));
        }
      }
      if (pts.size < 2 && mode === 'pinch') { mode = pts.size === 1 && viewRef.current ? 'pan' : null; lastX = [...pts.values()][0] || 0; return; }
      if (!pts.size) mode = null;
    };
    const dbl = () => setView(null);

    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('pointerdown', down);
    canvas.addEventListener('pointermove', move);
    canvas.addEventListener('pointerup', up);
    canvas.addEventListener('pointercancel', up);
    canvas.addEventListener('dblclick', dbl);
    return () => {
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('pointerdown', down);
      canvas.removeEventListener('pointermove', move);
      canvas.removeEventListener('pointerup', up);
      canvas.removeEventListener('pointercancel', up);
      canvas.removeEventListener('dblclick', dbl);
    };
  }, [zoomable, n, canvasRef, chartRef]);

  const step = (factor) => {
    const [lo, hi] = viewRef.current || [0, n - 1];
    const c = (lo + hi) / 2;
    setView(clampView(c - (c - lo) * factor, c + (hi - c) * factor, n));
  };
  return {
    zoomable, view, brushRef, setView,
    zoomIn: () => step(0.6), zoomOut: () => step(1 / 0.6), reset: () => setView(null),
  };
}

function ZoomBar({ zoom, labels }) {
  if (!zoom.zoomable) return null;
  const v = zoom.view;
  const shown = v ? shownRange(v, labels.length) : null;
  const range = shown ? `${labels[shown[0]]} – ${labels[shown[1]]}` : '';
  const atMin = shown && shown[1] - shown[0] <= ZOOM_MIN_SPAN;
  return (
    <div className="zoom-bar">
      <div className="zoom-btns" role="group" aria-label="Zoom the chart">
        <button type="button" onClick={zoom.zoomOut} disabled={!v} title="Zoom out" aria-label="Zoom out">−</button>
        <button type="button" onClick={zoom.zoomIn} disabled={atMin} title="Zoom in" aria-label="Zoom in">+</button>
        {v && <button type="button" className="zoom-reset" onClick={zoom.reset} title="Show the whole line (double-click the chart)">Reset</button>}
      </div>
      <span className="zoom-hint">
        {v ? <><span className="zoom-word">Showing </span><b>{range}</b><span className="zoom-pan"> · swipe or Shift + drag to move</span></>
          : <><span className="zoom-fine">Drag across the line to zoom in</span><span className="zoom-coarse">Pinch the line to zoom in</span></>}
      </span>
    </div>
  );
}

// One canvas, one chart; `config` is rebuilt whenever `deps` change. With
// `zoom`, a line chart gets the zoom controls below it (useLineZoom).
function ChartCanvas({ build, deps, zoom = false, label = '' }) {
  const ref = useRef(null);
  const chartRef = useRef(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!ref.current) return undefined;
    let chart;
    try { chart = new Chart(ref.current, build()); } catch (e) { console.error('Chart init failed:', e); }
    chartRef.current = chart || null;
    // The drawn chart, readable from the canvas (the headless UI checks assert on
    // its labels and series; not a global).
    if (ref.current) ref.current.__chart = chart || null;
    setN(chart && chart.config.type === 'line' ? (chart.data.labels || []).length : 0);
    return () => { chartRef.current = null; try { chart && chart.destroy(); } catch (e) { /* ignore */ } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  const z = useLineZoom(ref, chartRef, n, zoom);
  // A rebuilt chart (new type or data) starts with the whole line.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { z.setView(null); }, deps);
  if (!z.zoomable) return <canvas ref={ref} role="img" aria-label={label || 'Chart'} />;
  const labels = (chartRef.current && chartRef.current.data.labels) || [];
  return (
    <>
      <canvas ref={ref} className="zoomable" role="img" aria-label={label || 'Chart'} />
      <div ref={z.brushRef} className="zoom-brush" aria-hidden="true" />
      <ZoomBar zoom={z} labels={labels} />
    </>
  );
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
function ExpandedChart({ build, deps, rows, zoom = false }) {
  const style = rows ? { height: Math.max(420, rows * ROW_PX + 60) } : { height: '100%', minHeight: 420 };
  return <div className="xv-chart" style={style}><ChartCanvas build={build} deps={deps} zoom={zoom} /></div>;
}

const TYPE_LABELS = { bar: 'Bar', stacked: 'Stacked', pie: 'Pie', doughnut: 'Donut', line: 'Line' };

// No switcher when only one type is offered: a chart TYPE the officer named
// ("pie chart", "bar graph") is shown alone (user, 2026-10-19).
function TypeToggles({ types, type, setType }) {
  if (!types || types.length <= 1) return null;
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
const WARN = { main: '#C2410C', deep: '#9A3412', hover: '#FDBA74' };

export function SwitchableChart({ title, labels, fullLabels, values, types, initial, theme = DEFAULT_THEME, axes = null }) {
  const [type, setType] = useState(types.includes(initial) ? initial : types[0]);
  const [open, setOpen] = useState(false);
  const full = fullLabels || labels;
  const flat = type === 'bar' && full.length > HORIZONTAL_FROM;
  const insight = useMemo(() => insightFor(type, full, values, axes || {}), [type, full, values, axes]);
  // D-12: the largest of a lower-is-better measure (pending works) is a warning, not a win
  if (axes && axes.lowerBetter) theme = { ...theme, main: WARN.main, deep: WARN.deep, hover: WARN.hover };
  return (
    <div className="dyn-chart-card" style={cardStyle(theme)}>
      <CardHead title={title} theme={theme} insight={insight}>
        <TypeToggles types={types} type={type} setType={setType} />
        <ExpandButton label="chart" onClick={() => setOpen(true)} />
      </CardHead>
      <div className={'chw' + (type === 'pie' || type === 'doughnut' ? ' round' : '')}>
        <ChartCanvas build={() => withAxes(singleConfig(type, labels, values, theme), axes)} deps={[type, labels, values, theme, axes]} zoom={type === 'line'}
                     label={`${title}. ${insight}`} />
      </div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <div className="xv-toolbar"><TypeToggles types={types} type={type} setType={setType} /></div>
          <ExpandedChart build={() => withAxes(singleConfig(type, full, values, theme, true), axes)} deps={[type, full, values, theme, axes]}
                         rows={flat ? full.length : 0} zoom={type === 'line'} />
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

// Two dimensions and a measure (scheme × financial year, district × year …):
// the x-axis carries one dimension, the legend the other, so both are always
// visible. Bar = grouped columns per period, Stacked = one column per period,
// Line = one line per series, Donut = one slice per cell ("MGNREGA · 2023-24",
// or just "2023-24" when there is a single series).
const TWO_DIM_TYPES = ['bar', 'stacked', 'line', 'doughnut'];

function twoDimConfig(type, labels, datasets, theme, expanded = false) {
  if (type === 'line') return multiLineConfig(labels, datasets, theme);
  if (type === 'stacked') return stackedConfig(labels, datasets, theme, expanded);
  if (type === 'doughnut' || type === 'pie') {
    // One series (one scheme's years): the slices are the periods alone — the
    // card's title and chip already name the scheme, so it is not repeated on
    // every row of the legend. Several series keep "series · period".
    const cells = [];
    const one = datasets.length === 1;
    datasets.forEach((d) => labels.forEach((l, j) => {
      if (Number(d.data[j])) cells.push([one ? String(l) : `${d.label} · ${l}`, Number(d.data[j])]);
    }));
    return singleConfig(type, cells.map((c) => c[0]), cells.map((c) => c[1]), theme, expanded);
  }
  return groupedConfig(labels, datasets.map((d) => ({ label: d.label, values: d.data })), theme, expanded);
}

export function TwoDimChart({ title, labels, datasets, xKey, sKey, periods, initial, types = TWO_DIM_TYPES, theme = DEFAULT_THEME, axisInfo = null }) {
  const [type, setType] = useState(types.includes(initial) ? initial : (types.length === 1 ? types[0] : (periods ? 'line' : 'bar')));
  const [open, setOpen] = useState(false);
  const insight = useMemo(() => insightForSeries(labels, datasets, periods, axisInfo || {}), [labels, datasets, periods, axisInfo]);
  // C-16: say what the axis and the colours are ("Financial year by district" read backwards)
  const axes = `${type === 'line' ? 'Lines' : 'X-axis'}: ${colLabel(String(xKey)).toLowerCase()} · Colours: ${colLabel(String(sKey)).toLowerCase()}`;
  return (
    <div className="dyn-chart-card" style={cardStyle(theme)}>
      <CardHead title={title} theme={theme} insight={insight}>
        <TypeToggles types={types} type={type} setType={setType} />
        <ExpandButton label="chart" onClick={() => setOpen(true)} />
      </CardHead>
      <div className={'chw tall' + (type === 'doughnut' || type === 'pie' ? ' round' : '')}>
        <ChartCanvas build={() => withAxes(twoDimConfig(type, labels, datasets, theme), axisInfo)} deps={[type, labels, datasets, theme, axisInfo]} zoom={type === 'line'}
                     label={`${title}. ${insight}`} />
      </div>
      <div className="chd-axes" aria-label="What the axes show">{axes}</div>
      {open && (
        <ExpandModal title={title} onClose={() => setOpen(false)}>
          <div className="xv-toolbar"><TypeToggles types={types} type={type} setType={setType} /></div>
          <ExpandedChart build={() => withAxes(twoDimConfig(type, labels, datasets, theme, true), axisInfo)} deps={[type, labels, datasets, theme, axisInfo]}
                         rows={type !== 'line' && type !== 'doughnut' && type !== 'pie' && labels.length > HORIZONTAL_FROM ? labels.length * Math.max(1, datasets.length * 0.6) : 0}
                         zoom={type === 'line'} />
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

const asNumber = (v) => (v !== null && v !== undefined && isPlainNumber(String(v).trim())
  ? Number(String(v).replaceAll(',', '')) : null);

function compareCells(a, b) {
  const blankA = a === null || a === undefined || a === '';
  const blankB = b === null || b === undefined || b === '';
  if (blankA || blankB) return blankA === blankB ? 0 : (blankA ? 1 : -1);   // blanks last
  const na = asNumber(a);
  const nb = asNumber(b);
  if (na !== null && nb !== null) return na - nb;
  return String(a).localeCompare(String(b), 'en-IN', { numeric: true, sensitivity: 'base' });
}

// A heading in words: "total_exp_lakh" -> "Total expenditure (₹ lakh)" (columns.js).
const colLabel = (c) => colTitle(c);
// Measure cells read right-aligned, like a ledger (2026-10-28).
const numClass = (isNum) => (isNum ? 'num' : undefined);

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
  const nums = useMemo(() => new Set(cols.filter((c) => isMeasureCol(data, c))), [data, cols]);
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    // the search finds a figure as stored (27264054) or as shown (2,72,64,054)
    const out = needle
      ? data.filter((r) => cols.some((c) => String(r[c] ?? '').toLowerCase().includes(needle)
        || formatCell(r[c], c).toLowerCase().includes(needle)))
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
                <th key={c} className={numClass(nums.has(c))} aria-sort={sort.col === c ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" className="th-sort" onClick={() => toggleSort(c)} title="Sort">
                    {colLabel(c)}<span className="th-arrow">{sort.col === c ? (sort.dir === 1 ? '▲' : '▼') : '↕'}</span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{cols.map((c) => <td key={c} className={numClass(nums.has(c))}>{formatCell(r[c], c)}</td>)}</tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="rtbl-note">No rows match “{query}”.</div>}
      </div>
    </>
  );
}

// `change`: the question asked how a figure moved over time; a one-period,
// one-measure table then adds "Change from previous" (columns.changeColumn).
// E-3: the rows the query would return without the 1,000-row cap (server count)
export const RowTotal = createContext(null);

export function DynTable({ data: raw, title = 'Result table', change = false, rank = false }) {
  const [open, setOpen] = useState(false);
  const total = useContext(RowTotal);
  if (!raw || !raw.length) return null;
  // A twin column (year_key beside financial_year) is the same thing twice: shown
  // once. The Excel download keeps every column (ChatExport reads the raw rows).
  const data = withoutTwins(raw);
  const cols = tableColumns(data);
  const nums = new Set(cols.filter((c) => isMeasureCol(data, c)));
  const delta = change ? changeColumn(data) : null;
  return (
    <div className="rt-block">
      <TableBar count={data.length} label="table" onExpand={() => setOpen(true)} />
      {data.length >= 1000 && (
        // E-3 (audit 2026-10-29): the result stops at 1,000 rows (the query cap)
        <p className="rt-capped">{total > data.length
          ? `The first ${data.length.toLocaleString('en-IN')} of ${Number(total).toLocaleString('en-IN')} rows are shown.`
          : 'The first 1,000 rows are shown; there may be more.'} Narrow the question (a district or a year) to see the rest.</p>
      )}
      <div className="rtwrap">
        <table className="rtbl">
          <thead>
            <tr>
              {rank && <th className="num">#</th>}
              {cols.map((c) => <th key={c} className={numClass(nums.has(c))}>{colLabel(c)}</th>)}
              {delta && <th className="num">{delta.column}</th>}
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => (
              <tr key={i}>
                {rank && <td className="num">{i + 1}</td>}
                {cols.map((c) => <td key={c} className={numClass(nums.has(c))}>{formatCell(r[c], c)}</td>)}
                {delta && <td className="num delta">{delta.values[i]}</td>}
              </tr>
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

function PivotGrid({ data, xKey, sKey, vKey, expanded, totals = null }) {
  const xVals = [...new Set(data.map((r) => r[xKey]))];
  const sVals = [...new Set(data.map((r) => r[sKey]))];
  const lookup = {};
  data.forEach((r) => { lookup[`${r[xKey]}||${r[sKey]}`] = r[vKey]; });
  const rowTotals = {};
  xVals.forEach((x) => { rowTotals[x] = sVals.reduce((s, sv) => s + (parseFloat(lookup[`${x}||${sv}`]) || 0), 0); });
  const colTotals = {};
  sVals.forEach((sv) => { colTotals[sv] = xVals.reduce((s, x) => s + (parseFloat(lookup[`${x}||${sv}`]) || 0), 0); });
  // G-12 (audit 2026-10-29): the backend's own total per series (a scheme's
  // statewide figure, which counts records with no district) when it sends one:
  // the screen and the answer text then give the same Total.
  const given = totals && sVals.every((sv) => totals[sv] && totals[sv][vKey] !== undefined);
  if (given) sVals.forEach((sv) => { colTotals[sv] = Number(totals[sv][vKey]); });
  const grand = xVals.reduce((s, x) => s + rowTotals[x], 0);
  // Totals only where they mean something: a measure that adds up (never a %,
  // a rate or an average), across 2+ values, and only along a dimension it adds
  // along (audit 2026-10-29, G-3 / G-4 / B-3): villages and beneficiaries add down
  // the districts but not across schemes or years; nothing adds across schemes.
  const additive = isAdditive(vKey);
  const rowTot = additive && sVals.length >= 2 && canAdd(vKey, dimOf(sKey, data));
  const colTot = additive && xVals.length >= 2 && canAdd(vKey, dimOf(xKey, data));
  const total = (n) => formatCell(n, vKey);
  return (
    <div className={'rtwrap' + (expanded ? ' xv-table' : '')} style={{ overflowX: 'auto' }}>
      <table className="rtbl">
        <thead>
          <tr>
            <th>{colLabel(xKey)}</th>
            {sVals.map((sv) => <th key={sv} className="num">{sv}</th>)}
            {rowTot && <th className="num">Total</th>}
          </tr>
        </thead>
        <tbody>
          {xVals.map((x) => (
            <tr key={x}>
              <td><strong>{String(x)}</strong></td>
              {sVals.map((sv) => <td key={sv} className="num">{formatCell(lookup[`${x}||${sv}`], vKey)}</td>)}
              {rowTot && <td className="num"><strong>{total(rowTotals[x])}</strong></td>}
            </tr>
          ))}
          {colTot && (
            <tr style={{ background: 'var(--p-50)', fontWeight: 600 }}>
              <td title={given ? 'Includes records with no district' : undefined}>
                <strong>{given ? 'Total (all records)' : 'Total'}</strong>
              </td>
              {sVals.map((sv) => <td key={sv} className="num">{total(colTotals[sv])}</td>)}
              {rowTot && <td className="num"><strong>{total(grand)}</strong></td>}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function PivotTable({ data, xKey, sKey, vKey, totals = null }) {
  const [open, setOpen] = useState(false);
  if (!data || !data.length) return null;
  const rows = new Set(data.map((r) => r[xKey])).size;
  return (
    <div className="rt-block">
      <TableBar count={rows} label="table" onExpand={() => setOpen(true)} />
      <PivotGrid data={data} xKey={xKey} sKey={sKey} vKey={vKey} totals={totals} />
      {open && (
        <ExpandModal title={`${colLabel(vKey)} by ${colLabel(xKey)} & ${colLabel(sKey)}`} onClose={() => setOpen(false)}>
          <PivotGrid data={data} xKey={xKey} sKey={sKey} vKey={vKey} totals={totals} expanded />
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
            <tr key={k}><th style={{ width: '42%' }}>{colLabel(k)}</th><td>{formatCell(v, k)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export { pivotStacked };

// ── Two-way comparison (#397) ───────────────────────────────────────────────
// "A vs B": two stat tiles with the measure's value for each, "vs" between
// them, and one line saying who is ahead and by how much. The values use the
// font's proportional figures (a stat tile is not a column).
const compactValue = (v) => (Number.isFinite(v) ? v.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—');

function CompareVerdict({ v, unit }) {
  if (!v) return null;
  // Two schemes count and spend different things: show both, rank neither (E11).
  return <p className="cmp-verdict">{verdictText(v, unit)}</p>;
}

export function CompareCard({ title, measure, a, b, verdict, unit = null }) {
  // D-10 / D-11: the value in its unit ("80.5%", "₹9,000 lakh"); a side with no figure says so
  const tileValue = (v) => (Number.isFinite(v) ? (unit ? fmtUnit(v, unit) : compactValue(v)) : 'no figure');
  return (
    <div className="dyn-chart-card compare-card">
      <div className="chd">
        <div className="chd-left"><span className="chd-dot" /><span className="chd-title">{title}</span></div>
        <div className="chd-right"><span className="chd-pill">{measure}</span></div>
      </div>
      <div className="cmp-tiles">
        <div className="cmp-tile">
          <div className="cmp-label">{a.label}</div>
          <div className="cmp-value">{tileValue(a.value)}</div>
          {a.detail && <div className="cmp-sub">{a.detail}</div>}
        </div>
        <div className="cmp-vs" aria-hidden="true">vs</div>
        <div className="cmp-tile">
          <div className="cmp-label">{b.label}</div>
          <div className="cmp-value">{tileValue(b.value)}</div>
          {b.detail && <div className="cmp-sub">{b.detail}</div>}
        </div>
      </div>
      <CompareVerdict v={verdict} unit={unit} />
    </div>
  );
}
