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

import { isAsciiLetter, isPeriodLabel, isSpace, runEnd, splitSpaces } from './text.js';

export const SCHEME_HUES = {
  MGNREGA: { main: '#eb6834', deep: '#b8461b' },
  'PMAY-G': { main: '#2a78d6', deep: '#1c4f95' },
  'Focus Plus': { main: '#1baf7a', deep: '#0f7a54' },
  'CM Elevate': { main: '#6250d6', deep: '#3f2f9e' },
  'Focus Legacy': { main: '#008300', deep: '#005a00' },
  'CM Elevate Legacy': { main: '#d55181', deep: '#9c2c56' },
  "CMSS": { main: '#4a90e2', deep: '#2c5f99' },
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

const isFiniteValue = (v) => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));

// Month and quarter labels are periods too (C-4 / C-9): "Apr", "April", "Q1".
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
const MONTH_NAMES = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
  'november', 'december', 'sept'];
/** "Apr", "April", "Apr 2024", "April-2024" — never a place that starts like one ("Marngar"). */
export const isMonthLabel = (l) => {
  const parts = String(l ?? '').trim().toLowerCase().split('').map((c) => (c === '-' ? ' ' : c)).join('').split(' ')
    .filter(Boolean);
  if (!parts.length || parts.length > 2) return false;
  if (!MONTHS.includes(parts[0]) && !MONTH_NAMES.includes(parts[0])) return false;
  return parts.length === 1 || (parts[1].length === 4 && Array.from(parts[1]).every((c) => c >= '0' && c <= '9'));
};
/** Financial-year order of a month label: Apr = 0 … Mar = 11; -1 when not a month. */
export const fyMonthIndex = (l) => {
  if (!isMonthLabel(l)) return -1;
  return (MONTHS.indexOf(String(l).trim().toLowerCase().slice(0, 3)) + 9) % 12;
};
export const isQuarterLabel = (l) => {
  const s = String(l ?? '').trim().toLowerCase();
  return s.length === 2 && s[0] === 'q' && '1234'.includes(s[1]);
};
const isTimeLabel = (l) => isPeriodLabel(l) || isMonthLabel(l) || isQuarterLabel(l);
const isDay = (l) => String(l ?? '').trim().length === 10 && isPeriodLabel(l);

/** A figure in its column's unit (X-1: "1.2L" under a ₹ lakh chart read as 1.2 lakh
    rupees, 10,000× too small): ₹ lakh / crore figures in ₹ lakh or crore (never
    0: below 0.01 of the unit the smaller one, X-13), a % with its sign. */
export function fmtUnit(v, unit) {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  if (unit === 'pct') return `${fmt(n)}%`;
  const rupees = unit === 'crore' ? n * 1e7 : unit === 'lakh' ? n * 1e5 : unit === 'rupees' ? n : null;
  if (rupees === null) return fmtCompact(n);
  const a = Math.abs(rupees);
  if (a >= 1e7) return `₹${fmt(Math.round((rupees / 1e7) * 100) / 100)} crore`;
  if (a >= 1e5) return `₹${fmt(Math.round((rupees / 1e5) * 100) / 100)} lakh`;
  return `₹${fmt(Math.round(rupees))}`;
}

/** One line under a chart's title saying what to look at: the top category
    (and its share, for a pie / donut), or for a trend the latest value and the
    change since the first period. Empty when there is nothing to say.
    opts: { unit, lowerBetter, measure } — the figures in their unit; a % trend in
    points (D-9); the largest of a lower-is-better measure named as such (D-12). */
export function insightFor(type, labels, values, opts = {}) {
  const show = (v) => (opts.unit ? fmtUnit(v, opts.unit) : fmtCompact(v));
  // Only the points that have a value: a gap (null) is not a 0 (E11).
  const keep = (values || []).map((v, i) => i).filter((i) => isFiniteValue(values[i]));
  const nums = keep.map((i) => Number(values[i]));
  labels = keep.map((i) => labels[i]);
  if (nums.length < 2) return '';
  // "up 1530484561% since MGNREGA" (2026-10-19): a change over time only makes
  // sense when the x-axis IS time; over categories the line reads like a bar.
  const overTime = isTimeLabel(labels[0]) && isTimeLabel(labels[labels.length - 1]);
  if (overTime && (isDay(labels[0]) || nums.length > 12) && opts.unit !== 'pct') {
    // C-15: a noisy daily series — first-vs-last is not a trend; the total and the peak
    let pk = 0;
    nums.forEach((v, i) => { if (v > nums[pk]) pk = i; });
    return `Total ${show(nums.reduce((s, v) => s + v, 0))} · peak ${show(nums[pk])} on ${labels[pk]}`;
  }
  if (type === 'line' && overTime) {
    const first = nums[0];
    const last = nums[nums.length - 1];
    const lead = `Latest ${show(last)} in ${labels[labels.length - 1]}`;
    if (opts.unit === 'pct') {
      const pts = Math.round((last - first) * 10) / 10;
      return `${lead} · ${pts === 0 ? 'flat' : `${pts > 0 ? 'up' : 'down'} ${fmt(Math.abs(pts))} points`} since ${labels[0]}`;
    }
    if (!first) return lead;
    const pct = Math.round(((last - first) / Math.abs(first)) * 100);
    return `${lead} · ${pct === 0 ? 'flat' : `${pct > 0 ? 'up' : 'down'} ${Math.abs(pct)}%`} since ${labels[0]}`;
  }
  let hi = 0;
  nums.forEach((v, i) => { if (v > nums[hi]) hi = i; });
  if (opts.low) {
    // I-10 / J-7: the question asks for the low end
    let lo = 0;
    nums.forEach((v, i) => { if (v < nums[lo]) lo = i; });
    return `Lowest: ${labels[lo]} · ${show(nums[lo])}`;
  }
  const total = nums.reduce((s, v) => s + v, 0);
  const share = total > 0 && (type === 'pie' || type === 'doughnut') ? ` · ${Math.round((nums[hi] / total) * 1000) / 10}% of the total` : '';
  if (opts.lowerBetter) return `Most ${opts.measure || 'of it'} (lower is better): ${labels[hi]} · ${show(nums[hi])}${share}`;
  return `Highest: ${labels[hi]} · ${show(nums[hi])}${share}`;
}

/** The headline for a multi-series chart (scheme × year, district × year):
    over periods, each series' latest value at the last period; otherwise the
    single highest cell and which series / category it belongs to. */
export function insightForSeries(labels, datasets, periods, opts = {}) {
  if (!labels || !labels.length || !datasets || !datasets.length) return '';
  const fmtCompact = (v) => (opts.unit ? fmtUnit(v, opts.unit) : fmtCompactRaw(v));
  if (periods) {
    const last = labels.length - 1;
    // A-13 (audit 2026-10-29): each scheme holds its own years. "Latest (2025-26):
    // PMAY-G 0" read a year PMAY-G does not hold; each series is headlined at
    // its own latest year with a figure.
    const lastHeld = (d) => { for (let j = d.data.length - 1; j >= 0; j--) if (isFiniteValue(d.data[j])) return j; return -1; };
    if (datasets.length >= 2 && datasets.some((d) => lastHeld(d) !== last)) {
      const parts = datasets.filter((d) => lastHeld(d) >= 0)
        .map((d) => `${d.label} ${fmtCompact(d.data[lastHeld(d)])} (${labels[lastHeld(d)]})`);
      return parts.length ? `Latest: ${parts.join(' · ')}` : '';
    }
    const parts = datasets.map((d) => `${d.label} ${isFiniteValue(d.data[last]) ? fmtCompact(d.data[last]) : '—'}`);
    return `Latest (${labels[last]}): ${parts.join(' · ')}`;
  }
  let best = { v: -Infinity, s: '', l: '' };
  datasets.forEach((d) => d.data.forEach((v, j) => { if (isFiniteValue(v) && Number(v) > best.v) best = { v: Number(v), s: d.label, l: labels[j] }; }));
  return best.v > -Infinity ? `Highest: ${best.s} in ${best.l} · ${fmtCompact(best.v)}` : '';
}

// The one-line verdict under a two-way comparison (CompareCard).
/** The verdict as plain words (also what the tests read). */
export function verdictText(v, unit = null) {
  if (!v) return '';
  const val = (x) => (unit ? fmtUnit(x, unit) : fmt(x));
  if (v.unlike) return 'Each scheme measures this differently, so the two are not ranked.';
  if (v.equal) return `Both record ${val(v.value)} ${v.measure}.`;
  if (v.change) {
    // C-1: a change over time, from the earlier period
    const gap = v.points ? `${fmt(Math.abs(v.diff))} points` : `${v.pct === null ? '' : `${v.pct}% `}`;
    const sign = v.diff > 0 ? '+' : '−';
    return v.points
      ? `${v.change === 'rose' ? 'Rose' : 'Fell'} ${gap} from ${v.from} to ${v.to} on ${v.measure}.`
      : `${v.change === 'rose' ? 'Rose' : 'Fell'} ${gap}from ${v.from} to ${v.to} (${sign}${val(Math.abs(v.diff))}) on ${v.measure}.`;
  }
  if (v.points) return `${v.lead} is ${fmt(v.diff)} points ahead on ${v.measure}.`;      // D-4
  if (v.lowerBetter) return `${v.lead} has ${val(v.diff)} fewer ${v.measure} (lower is better).`;  // D-5
  if (v.diffFirst) {                                                                         // B-15
    return `The difference is ${val(v.diff)} ${v.measure}: ${v.lead} has more${v.pct === null ? '' : ` (${v.pct}% ahead)`}.`;
  }
  return v.pct === null ? `${v.lead} is ${val(v.diff)} more on ${v.measure}.`
    : `${v.lead} is ${v.pct}% ahead (${val(v.diff)} more) on ${v.measure}.`;
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
// Words may be joined by spaces, '_' or '-' ("cm_elevate", "focus-plus", "focus+");
// a short form (cmel, cme, fp) counts only when no letter touches it.
const isJoiner = (c) => isSpace(c) || c === '_' || c === '-';
const isLetter = (c) => isAsciiLetter(c);
function hasJoined(low, parts) {
  for (let i = low.indexOf(parts[0]); i !== -1; i = low.indexOf(parts[0], i + 1)) {
    let j = i + parts[0].length;
    let ok = true;
    for (const alts of parts.slice(1)) {
      j = runEnd(low, j, isJoiner);
      const hit = [].concat(alts).find((a) => low.startsWith(a, j));
      if (hit === undefined) { ok = false; break; }
      j += hit.length;
    }
    if (ok) return true;
  }
  return false;
}
function hasAlone(low, word) {
  for (let i = low.indexOf(word); i !== -1; i = low.indexOf(word, i + 1)) {
    if (!isLetter(low[i - 1]) && !isLetter(low[i + word.length])) return true;
  }
  return false;
}
const SERIES_SCHEME = [
  [(l) => hasJoined(l, ['cm', 'elevate', 'legacy']) || hasAlone(l, 'cmel'), 'CM Elevate Legacy'],
  [(l) => hasJoined(l, ['cm', 'elevate']) || hasAlone(l, 'cme'), 'CM Elevate'],
  [(l) => hasJoined(l, ['focus', 'legacy']), 'Focus Legacy'],
  [(l) => hasJoined(l, ['focus', ['plus', '+']]) || hasAlone(l, 'fp'), 'Focus Plus'],
  [(l) => l.includes('pmay'), 'PMAY-G'],
  [(l) => l.includes('nrega'), 'MGNREGA'],
  [(l) => hasAlone(l, 'cmss'), 'CMSS'],          // also "mgnrega"
];
export const schemeOfSeries = (label) => {
  const low = String(label).toLowerCase();
  const hit = SERIES_SCHEME.find(([test]) => test(low));
  return hit ? hit[1] : null;
};

/** One colour per series. A series named after a scheme wears that scheme's
    hue. Several series of ONE scheme ("PMAY-G · 2017-18", "PMAY-G · 2018-19":
    its years, its districts) are shades of that hue — palest first, the last
    (latest) in the full hue — never a different colour each, so one scheme is
    always one colour family. In a ONE-scheme answer (theme.scheme set) every
    series is that scheme's — its years, its districts — so series that name no
    scheme are shades of the answer's hue too. Only a cross-scheme answer hands
    an unnamed series the next categorical colour not already on the chart. */
export function seriesColors(labels, theme) {
  const schemes = labels.map((l) => schemeOfSeries(l));
  const count = {};
  schemes.forEach((s) => { if (s) count[s] = (count[s] || 0) + 1; });
  const unnamed = schemes.filter((s) => !s).length;
  const used = new Set(Object.keys(count).map((s) => SCHEME_HUES[s].main));
  const free = theme.series.filter((c) => !used.has(c));
  const seen = {};
  let k = 0;
  return labels.map((l, i) => {
    const s = schemes[i];
    if (!s) {
      if (!theme.scheme) return free[k++ % free.length];
      const j = k++;
      return unnamed === 1 ? theme.main : tint(theme.main, ((unnamed - 1 - j) / (unnamed - 1)) * 0.65);
    }
    const n = count[s];
    const j = seen[s] || 0;
    seen[s] = j + 1;
    return n === 1 ? SCHEME_HUES[s].main : tint(SCHEME_HUES[s].main, ((n - 1 - j) / (n - 1)) * 0.6);
  });
}

/** When a one-series chart's CATEGORIES are different schemes ("Value by
    scheme": MGNREGA, PMAY-G, …), each bar / slice wears its scheme's hue, as
    everywhere else; a category that is no scheme of ours (NRLM) gets the next
    free categorical colour. Null when most categories are not schemes, and
    null when they all belong to ONE scheme (its years, its districts): that is
    one scheme's breakdown, drawn in that scheme's hue by the caller. */
export function categorySchemeColors(labels, theme) {
  if (!labels || labels.length < 2) return null;
  const found = labels.map((l) => schemeOfSeries(l)).filter(Boolean);
  if (found.length < 2 || found.length / labels.length < 0.6 || new Set(found).size < 2) return null;
  return seriesColors(labels, theme);
}

// t = 0 -> the colour, t = 1 -> black (the deep end of a bar's gradient).
export const shade = (hex, t) => toHex(hexToRgb(hex).map((v) => v * (1 - t)));

/** Category labels wrapped onto at most two lines (Chart.js draws an array as
    lines), so a level axis stays readable instead of slanting. */
export function wrapLabel(label, max = 14) {
  const words = splitSpaces(String(label));
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
export const fmt = (v) => FULL.format(Number(v) || 0);
// Compact in Indian units only: below 1 lakh the full figure ("3,629"), then
// lakh ("1.7L") and crore ("2,185Cr"). Intl's compact mixed in thousands —
// "3.6K", and "2.2KCr" for 2,185 crore (user report 2026-10-19).
const UNIT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 });
const UNIT_BIG = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const inUnit = (x) => (Math.abs(x) < 100 ? UNIT : UNIT_BIG).format(x);
const fmtCompactRaw = (v) => fmtCompact(v);
export const fmtCompact = (v) => {
  const n = Number(v) || 0;
  const a = Math.abs(n);
  if (a >= 1e7) return `${inUnit(n / 1e7)}Cr`;
  if (a >= 1e5) return `${inUnit(n / 1e5)}L`;
  return fmt(n);
};

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
    // Zoomed into an earlier stretch: the last point is off the chart.
    if (!el || el.x > chart.chartArea.right + 1 || el.x < chart.chartArea.left - 1) return;
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
