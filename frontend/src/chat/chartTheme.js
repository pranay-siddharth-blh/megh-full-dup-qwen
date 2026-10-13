/* Chart look per scheme (D-043): which colours a DATA answer's charts use, and
   the small Chart.js plugins that draw the labels.

   Colour rules (checked with the data-viz validator, not by eye):
   - A one-scheme answer is drawn in that scheme's hue, so MGNREGA, PMAY-G, ...
     are told apart at a glance. Two scheme hues never share a chart, and the
     card names the scheme, so colour is never the only cue (validator: the six
     hues pass every adjacent check; some PAIRS are too close to sit together,
     e.g. CM Elevate vs PMAY-G, which is why they never do).
   - A cross-scheme answer, and any multi-series chart (grouped, stacked by a
     non-year label), uses CATEGORICAL in its fixed order, never cycled past 8.
   - Emphasis, not a value ramp: the largest bar / slice wears the full hue,
     the rest a pale step of the same hue, and every value is labelled.
   - Text never wears the data colour: labels use ink tokens; a label inside a
     filled slice picks white or ink by the fill's lightness. */

export const SCHEME_HUES = {
  MGNREGA: { main: '#eb6834', deep: '#b8461b' },
  'PMAY-G': { main: '#2a78d6', deep: '#1c4f95' },
  'Focus Plus': { main: '#1baf7a', deep: '#0f7a54' },
  'CM Elevate': { main: '#6250d6', deep: '#3f2f9e' },
  'Focus Legacy': { main: '#008300', deep: '#005a00' },
  'CM Elevate Legacy': { main: '#d55181', deep: '#9c2c56' },
};
// The console's own purple: cross-scheme and unknown answers.
const BRAND = { main: '#7C3FBF', deep: '#4A2380' };

// Fixed categorical order (validated: every adjacent pair clears the CVD and
// normal-vision floors on a white surface). Series 9+ fold, never generate.
export const CATEGORICAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];

export const INK = { primary: '#1A1626', secondary: '#534B68', muted: '#857E96', grid: 'rgba(92,45,145,.07)', surface: '#ffffff' };

// Names the backend uses for the same scheme ("FOCUS+", "Focus" ...).
const ALIASES = { 'FOCUS+': 'Focus Plus', FOCUS: 'Focus Legacy', 'Focus+': 'Focus Plus' };

const hexToRgb = (h) => {
  const n = parseInt(h.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const toHex = (rgb) => '#' + rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
// t = 0 -> the colour, t = 1 -> white.
export const tint = (hex, t) => toHex(hexToRgb(hex).map((v) => v + (255 - v) * t));
export const alpha = (hex, a) => { const [r, g, b] = hexToRgb(hex); return `rgba(${r},${g},${b},${a})`; };
// Relative luminance (WCAG); white text on fills darker than ~0.4.
const luminance = (hex) => {
  const c = hexToRgb(hex).map((v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
export const textOn = (hex) => (luminance(hex) < 0.4 ? '#ffffff' : INK.primary);

/** The theme for an answer's charts, from response.schemes. */
export function themeFor(schemes) {
  const names = [...new Set((Array.isArray(schemes) ? schemes : []).map((s) => ALIASES[s] || s))];
  const scheme = names.length === 1 && SCHEME_HUES[names[0]] ? names[0] : null;
  const hue = scheme ? SCHEME_HUES[scheme] : BRAND;
  return {
    scheme,                       // null for cross-scheme / unknown
    // A long list ("MGNREGA · PMAY-G · … · NRLM") crushed the title; past two
    // schemes the chip says how many, and its tooltip lists them (labelFull).
    label: scheme || (names.length > 2 ? `${names.length} schemes` : names.join(' · ')),
    labelFull: names.join(' · '),
    main: hue.main,
    deep: hue.deep,
    soft: tint(hue.main, 0.78),   // the non-highlighted bars
    softEdge: tint(hue.main, 0.62),
    hover: tint(hue.main, 0.42),  // a pale bar under the pointer
    series: CATEGORICAL,
  };
}

/** One line under a chart's title saying what to look at: the top category
    (and its share, for a pie / donut), or for a trend the latest value and the
    change since the first period. Empty when there is nothing to say. */
export function insightFor(type, labels, values) {
  const nums = (values || []).map((v) => Number(v) || 0);
  if (nums.length < 2) return '';
  if (type === 'line') {
    const first = nums[0];
    const last = nums[nums.length - 1];
    const lead = `Latest ${fmtCompact(last)} in ${labels[labels.length - 1]}`;
    if (!first) return lead;
    const pct = Math.round(((last - first) / Math.abs(first)) * 100);
    return `${lead} · ${pct === 0 ? 'flat' : `${pct > 0 ? 'up' : 'down'} ${Math.abs(pct)}%`} since ${labels[0]}`;
  }
  let hi = 0;
  nums.forEach((v, i) => { if (v > nums[hi]) hi = i; });
  const total = nums.reduce((s, v) => s + v, 0);
  const share = total > 0 && (type === 'pie' || type === 'doughnut') ? ` · ${Math.round((nums[hi] / total) * 1000) / 10}% of the total` : '';
  return `Highest: ${labels[hi]} · ${fmtCompact(nums[hi])}${share}`;
}

/** Entry animation: bars and points grow in one after another (a short
    stagger); none at all for readers who ask for reduced motion. */
export function chartAnimation() {
  try {
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
  } catch (e) { /* no matchMedia */ }
  return {
    duration: 700, easing: 'easeOutQuart',
    delay: (c) => (c.type === 'data' && c.mode === 'default' ? Math.min(c.dataIndex * 45, 450) : 0),
  };
}

// A series named after a scheme ("mgnrega spend cr", "PMAY-G houses") keeps
// that scheme's hue, so colour follows the entity across every chart.
// CM Elevate Legacy / Focus Legacy are tested before their parents.
const SERIES_SCHEME = [
  [/cm[\s_-]*elevate[\s_-]*legacy|(?:^|[^a-z])cmel(?![a-z])/i, 'CM Elevate Legacy'],
  [/cm[\s_-]*elevate|(?:^|[^a-z])cme(?![a-z])/i, 'CM Elevate'],
  [/focus[\s_-]*legacy/i, 'Focus Legacy'],
  [/focus[\s_-]*(?:plus|\+)|(?:^|[^a-z])fp(?![a-z])/i, 'Focus Plus'],
  [/pmay/i, 'PMAY-G'],
  [/mgnrega|nrega/i, 'MGNREGA'],
];
export const schemeOfSeries = (label) => {
  const hit = SERIES_SCHEME.find(([re]) => re.test(String(label)));
  return hit ? hit[1] : null;
};

/** One colour per series: its scheme's hue when the name says which scheme,
    otherwise the next categorical colour not already on the chart. */
export function seriesColors(labels, theme) {
  const used = new Set();
  const out = labels.map((l) => {
    const sch = schemeOfSeries(l);
    if (sch && !used.has(SCHEME_HUES[sch].main)) { used.add(SCHEME_HUES[sch].main); return SCHEME_HUES[sch].main; }
    return null;
  });
  const free = theme.series.filter((c) => !used.has(c));
  let k = 0;
  return out.map((c) => c || free[k++ % free.length]);
}

/** When a one-series chart's CATEGORIES are schemes ("Value by scheme":
    MGNREGA, PMAY-G, …), each bar / slice wears its scheme's hue, as everywhere
    else; a category that is no scheme of ours (NRLM) gets the next free
    categorical colour. Null when most categories are not schemes. */
export function categorySchemeColors(labels, theme) {
  if (!labels || labels.length < 2) return null;
  const hits = labels.filter((l) => schemeOfSeries(l)).length;
  if (hits < 2 || hits / labels.length < 0.6) return null;
  return seriesColors(labels, theme);
}

// t = 0 -> the colour, t = 1 -> black (the deep end of a bar's gradient).
export const shade = (hex, t) => toHex(hexToRgb(hex).map((v) => v * (1 - t)));

/** Category labels wrapped onto at most two lines (Chart.js draws an array as
    lines), so a level axis stays readable instead of slanting. */
export function wrapLabel(label, max = 14) {
  const words = String(label).split(/\s+/);
  const lines = [''];
  for (const w of words) {
    const cur = lines[lines.length - 1];
    if (!cur) lines[lines.length - 1] = w;
    else if ((cur + ' ' + w).length <= max) lines[lines.length - 1] = cur + ' ' + w;
    else lines.push(w);
  }
  if (lines.length > 2) lines.splice(1, lines.length - 1, lines.slice(1).join(' '));
  return lines.map((l) => (l.length > max + 4 ? l.slice(0, max + 2) + '…' : l));
}

/** Ordinal steps of one hue, darkest first (years in a stack, donut slices by size). */
export function ordinalSteps(theme, n) {
  if (n <= 1) return [theme.main];
  return Array.from({ length: n }, (_, i) => tint(theme.main, (i / (n - 1)) * 0.7));
}

// ── Number format: Indian grouping, compact on axes ─────────────────────────
const FULL = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });
const COMPACT = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 });
export const fmt = (v) => FULL.format(Number(v) || 0);
export const fmtCompact = (v) => (Math.abs(Number(v)) >= 1000 ? COMPACT.format(Number(v)) : fmt(v));

// ── Plugins ─────────────────────────────────────────────────────────────────
const FONT = (size, weight = 600) => `${weight} ${size}px Inter, system-ui, -apple-system, "Segoe UI", sans-serif`;

const roundRect = (ctx, x, y, w, h, r) => {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
};

/* Value labels at bar tips (columns: above the cap; horizontal: past the end).
   opts.indices: which bars to label (all when few, else the extreme only).
   opts.stackTotals: for a stack, one total above each column instead.
   Every plugin here draws only when its options say { on: true }: Chart.js
   hands each registered plugin an options object even when the chart sets
   none, so a missing switch must mean "off". */
export const barValueLabels = {
  id: 'meghBarValues',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.on) return;
    const { ctx } = chart;
    const horizontal = chart.options.indexAxis === 'y';
    ctx.save();
    ctx.font = FONT(11.5);
    ctx.fillStyle = INK.secondary;
    const area = chart.chartArea;
    const draw = (text, el) => {
      const w = ctx.measureText(text).width;
      if (horizontal) {
        const x = Math.min(el.x + 6, area.right - w);
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(text, x, el.y);
      } else {
        ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
        ctx.fillText(text, el.x, Math.max(el.y - 5, area.top + 12));
      }
    };
    if (opts.stackTotals) {
      const metas = chart.data.datasets.map((_, i) => chart.getDatasetMeta(i)).filter((m) => !m.hidden);
      if (!metas.length) { ctx.restore(); return; }
      chart.data.labels.forEach((_, j) => {
        if (opts.indices && !opts.indices.includes(j)) return;
        const total = chart.data.datasets.reduce((s, d) => s + (Number(d.data[j]) || 0), 0);
        // the outermost segment is the top of the stack
        const top = metas.map((m) => m.data[j]).reduce((a, b) => (horizontal ? (b.x > a.x ? b : a) : (b.y < a.y ? b : a)));
        draw(fmtCompact(total), top);
      });
    } else {
      chart.data.datasets.forEach((d, i) => {
        const meta = chart.getDatasetMeta(i);
        if (meta.hidden) return;
        meta.data.forEach((el, j) => {
          if (opts.indices && !opts.indices.includes(j)) return;
          const text = fmtCompact(d.data[j]);
          // A column label wider than its column would run into the next one
          // (narrow cards, many bars): skip it, except the highlighted bar.
          const keep = opts.keep != null && opts.keep === j;
          if (!horizontal && !keep && el.width && ctx.measureText(text).width > el.width + 10) return;
          draw(text, el);
        });
      });
    }
    ctx.restore();
  },
};

/* The highlighted category's axis label in a dark pill (the reference look). */
export const highlightTick = {
  id: 'meghHighlightTick',
  afterDraw(chart, _args, opts) {
    if (!opts || !opts.on || opts.index == null || opts.index < 0) return;
    const horizontal = chart.options.indexAxis === 'y';
    const scale = chart.scales[horizontal ? 'y' : 'x'];
    if (!scale) return;
    const tick = scale.ticks.findIndex((t) => t.value === opts.index);
    if (tick < 0) return;
    const text = String(chart.data.labels[opts.index]);
    const { ctx } = chart;
    ctx.save();
    ctx.font = FONT(11, 700);
    const w = ctx.measureText(text).width + 14;
    const h = 20;
    const pos = scale.getPixelForTick(tick);
    const rot = !horizontal && scale.labelRotation ? (scale.labelRotation * Math.PI) / 180 : 0;
    ctx.fillStyle = INK.primary;
    if (rot) {
      // Slanted category labels (narrow cards): the pill slants with them,
      // ending where the label ends, so it never covers its neighbours.
      ctx.translate(pos, scale.top + 8);
      ctx.rotate(-rot);
      roundRect(ctx, -w + 4, -h / 2, w, h, 6);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(text, -w / 2 + 4, 0.5);
      ctx.restore();
      return;
    }
    if (!horizontal) {
      // Level column labels may be wrapped onto two lines; the pill holds
      // the same lines, centred under the column.
      const lines = wrapLabel(text);
      const lw = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 14;
      const lh = 15;
      const ph = lines.length * lh + 6;
      const px = Math.max(2, Math.min(pos - lw / 2, chart.width - lw - 2));
      const py = scale.top + 5;
      roundRect(ctx, px, py, lw, ph, 6);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      lines.forEach((l, k) => ctx.fillText(l, px + lw / 2, py + 3 + lh * k + lh / 2 + 0.5));
      ctx.restore();
      return;
    }
    let x = scale.right - w - 4;
    const y = pos - h / 2;
    x = Math.max(2, Math.min(x, chart.width - w - 2));
    roundRect(ctx, x, y, w, h, 6);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, x + w / 2, y + h / 2 + 0.5);
    ctx.restore();
  },
};

/* Donut / pie: each slice's share inside it when it fits; the total in the
   middle of a donut. */
export const sliceLabels = {
  id: 'meghSliceLabels',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.on) return;
    const meta = chart.getDatasetMeta(0);
    const ds = chart.data.datasets[0];
    if (!meta || !ds) return;
    const values = ds.data.map((v) => Number(v) || 0);
    const total = values.reduce((s, v) => s + v, 0);
    if (total <= 0) return;
    const { ctx } = chart;
    ctx.save();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    meta.data.forEach((arc, i) => {
      const share = values[i] / total;
      const sweep = arc.endAngle - arc.startAngle;
      const thickness = arc.outerRadius - arc.innerRadius;
      if (share < 0.06 || sweep * ((arc.outerRadius + arc.innerRadius) / 2) < 30 || thickness < 18) return;
      const mid = (arc.startAngle + arc.endAngle) / 2;
      const r = arc.innerRadius + thickness * (arc.innerRadius ? 0.5 : 0.62);
      const fill = Array.isArray(ds.backgroundColor) ? ds.backgroundColor[i] : ds.backgroundColor;
      const text = `${Math.round(share * 1000) / 10}%`;
      ctx.font = FONT(11.5, 700);
      // Only inside the slice when it fits: a ring thinner than the text (a
      // small donut on a phone) leaves the share to the legend and tooltip.
      const tw = ctx.measureText(text).width;
      if (arc.innerRadius && tw > thickness + 6) return;
      const tx = arc.x + Math.cos(mid) * r;
      const ty = arc.y + Math.sin(mid) * r;
      if (tx - tw / 2 < 2 || tx + tw / 2 > chart.width - 2) return;
      ctx.fillStyle = textOn(typeof fill === 'string' ? fill : INK.primary);
      ctx.fillText(text, tx, ty);
    });
    if (opts.centerTotal && meta.data[0] && meta.data[0].innerRadius > 34) {
      const { x, y, innerRadius } = meta.data[0];
      // The slice under the pointer takes over the middle: its name and
      // value; otherwise the total.
      const active = chart.getActiveElements ? chart.getActiveElements()[0] : null;
      let label = opts.centerLabel || 'Total';
      let value = total;
      if (active && active.datasetIndex === 0) {
        label = String(chart.data.labels[active.index]);
        value = values[active.index];
      }
      const maxW = innerRadius * 1.6;
      ctx.fillStyle = INK.muted;
      ctx.font = FONT(Math.max(10, Math.min(12, innerRadius / 5)), 600);
      while (label.length > 4 && ctx.measureText(label).width > maxW) label = label.slice(0, -2).trimEnd() + '…';
      ctx.fillText(label, x, y - innerRadius * 0.2);
      ctx.fillStyle = INK.primary;
      ctx.font = FONT(Math.max(14, Math.min(26, innerRadius / 2.6)), 700);
      ctx.fillText(fmtCompact(value), x, y + innerRadius * 0.14);
    }
    ctx.restore();
  },
};

/* Line: the last value labelled beside its end-dot. */
export const lineEndLabel = {
  id: 'meghLineEnd',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.on) return;
    const meta = chart.getDatasetMeta(0);
    const ds = chart.data.datasets[0];
    if (!meta || !ds || !meta.data.length) return;
    const i = meta.data.length - 1;
    const el = meta.data[i];
    const { ctx } = chart;
    ctx.save();
    const text = fmtCompact(ds.data[i]);
    ctx.font = FONT(11, 700);
    const w = ctx.measureText(text).width + 12;
    const x = Math.min(el.x - w / 2, chart.chartArea.right - w);
    const y = Math.max(el.y - 30, chart.chartArea.top - 4);
    ctx.fillStyle = INK.primary;
    roundRect(ctx, x, y, w, 20, 6);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, x + w / 2, y + 10.5);
    ctx.restore();
  },
};

/* Pie / donut: the legend sits beside the ring on a wide card and below it on
   a narrow one (phones, a narrow chat column), so the ring keeps its size. */
// Set on the chart's own config (not the resolved options) before the first
// layout and on every resize: the legend plugin reads its position before any
// later hook could change it, and Chart.js re-lays out right after a resize.
const fitLegend = (chart, width) => {
  const legend = chart.config.options && chart.config.options.plugins && chart.config.options.plugins.legend;
  if (legend) legend.position = width && width < 460 ? 'bottom' : 'right';
};
export const legendFit = {
  id: 'meghLegendFit',
  beforeInit(chart, _args, opts) { if (opts && opts.on) fitLegend(chart, chart.width); },
  resize(chart, args, opts) { if (opts && opts.on) fitLegend(chart, args.size && args.size.width); },
};

/* Line: a thin vertical guide at the point under the pointer, so the tooltip's
   value is easy to place against the axis. */
export const crosshair = {
  id: 'meghCrosshair',
  afterDatasetsDraw(chart, _args, opts) {
    if (!opts || !opts.on) return;
    const active = chart.getActiveElements ? chart.getActiveElements()[0] : null;
    if (!active) return;
    const { ctx, chartArea } = chart;
    const x = active.element.x;
    ctx.save();
    ctx.strokeStyle = opts.color || INK.muted;
    ctx.globalAlpha = 0.45;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  },
};

/* Column charts: labels stay level (wrapped by wrapLabel) while each column
   has room for them, and slant only when the chart is too narrow (a phone,
   many categories). Set before layout and on every resize, like legendFit. */
const fitTicks = (chart, width) => {
  const x = chart.config.options && chart.config.options.scales && chart.config.options.scales.x;
  const n = (chart.data.labels || []).length;
  if (!x || !n || !width) return;
  x.ticks = x.ticks || {};
  const level = width / n >= 74;
  x.ticks.maxRotation = level ? 0 : 50;
  x.ticks.minRotation = 0;
};
export const tickFit = {
  id: 'meghTickFit',
  beforeInit(chart, _args, opts) { if (opts && opts.on) fitTicks(chart, chart.width); },
  resize(chart, args, opts) { if (opts && opts.on) fitTicks(chart, args.size && args.size.width); },
};

export const PLUGINS = [barValueLabels, highlightTick, sliceLabels, lineEndLabel, legendFit, crosshair, tickFit];
