/* The live voice stage's chart cards, drawn on canvas (2026-11-02). Ported from
   Sakala Mitra's stage (D:/Sakala POC/mitra/web/stage.js, read-only source):
   extruded 3D bars on a perspective floor, a ranked bar race with depth, a
   ribbon line with a depth wall and a glowing head, a thick tilted ring, KPI
   tiles that count up, one big KPI, and a raised district map (Meghalaya here,
   Karnataka there). Each item starts hidden and grows for GROW[kind] ms from the
   moment it is revealed (the voice names it, or revealAll at the end of the
   turn), so the picture builds while the answer is spoken. A small camera leans
   with the pointer.

   Changes from Mitra: one factory over a given canvas (the React layer owns all
   DOM: no host, dock, kinds bar, composer, insight, FX particles, DOM legends or
   tooltips: legends, side list and tooltips are drawn on the canvas), always the
   light rendering (normal blending, soft shadows, no dark lenses) in Megh One
   AI's palette, several series on a line, null = "no data" (hatched, never 0),
   and the draw loop stops when nothing moves.

   Numbers: nothing here computes or formats a figure from the data. Every value
   on screen goes through spec.fmt; the only arithmetic on a value is the
   count-up while it grows (a whole number shows whole numbers, otherwise 2 dp),
   and geometry (bar heights, slice angles, colour ramp positions).
   No regex anywhere (D-046/D-047): string methods only. */

import { MEGH_DISTRICTS, MEGH_WORLD, MEGH_OUTLINE } from './meghMap.js';

export const GROW = { bars: 2000, race: 1600, line: 1300, donut: 1500, map: 1400, kpi: 1500, tiles: 1100 };
/* The spotlight (2026-11-10): the item the voice is naming right now. It lights at once (SPOT.attack ms), holds while
   it is being talked about, hands over to the next named item, and fades. A ring opens from it once (SPOT.ring ms).
   Items revealed at the end of the turn (revealAll) are never spotlit: they simply glide in. */
export const SPOT = { attack: 140, hold: 1500, fade: 900, handoff: 420, ring: 900 };

// ------------------------------------------------------------------ tokens (Megh One AI, light)
const T = {
  ink: '#1A1626', ink2: '#534B68', mute: '#857E96', grid: 'rgba(92,45,145,.07)', faint: 'rgba(92,45,145,.045)',
  line: 'rgba(92,45,145,.24)', surface: '#ffffff', land: '#EFEBF4', nodata: '#EEEBF2', border: 'rgba(92,45,145,.12)',
  shadow: 'rgba(74,35,128,.14)', brand: '#7C3FBF', deep: '#4A2380', tint1: '#E5D2F6', tint2: '#CFA8EE', ok: '#15803d',
};
export const CATEGORICAL = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];
const SCHEME = { MGNREGA: '#eb6834', 'PMAY-G': '#2a78d6', 'Focus Plus': '#1baf7a', 'CM Elevate': '#6250d6', 'Focus Legacy': '#008300', 'CM Elevate Legacy': '#d55181' };
const TONE = { bad: '#e34948', warn: '#c98a00', ok: '#15803d', good: '#15803d', brand: '#7C3FBF', info: '#2a78d6', muted: '#857E96', ...SCHEME };
const RAMP = ['#F4ECFB', '#CFA8EE', '#7C3FBF', '#4A2380'];
const FONT_FAMILY = 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
const TAU = Math.PI * 2;

// ------------------------------------------------------------------ pure helpers (tested)
export const ease = (k) => 1 - Math.pow(1 - Math.max(0, Math.min(1, k)), 3);
// a count-up of a whole number shows whole numbers (Mitra's grow)
export const grow = (v, p) => (Number.isInteger(v) ? Math.round(v * p) : +(v * p).toFixed(2));
export function nice(max, ticks = 4) {
  if (!(max > 0)) return { top: ticks, step: 1 };
  const raw = max / ticks; const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s * ticks >= max) || 10 * p;
  return { top: step * ticks, step };
}
// the tightest of 3, 4 or 5 nice ticks (Mitra used a fixed count, which can leave half the plot empty)
export function niceAxis(max) {
  let best = null;
  for (const t of [4, 3, 5]) { const a = nice(max, t); if (!best || a.top < best.top - 1e-9) best = { ...a, ticks: t }; }
  return best;
}
// Mitra's flush: however many items are left, the rest arrive within ~1.6 s
export const staggerFor = (stagger, remaining) => Math.min(stagger, 1600 / Math.max(1, remaining));
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
function rgbOf(h) {
  const s = String(h || '').trim();
  if (s.startsWith('rgb(') && s.endsWith(')')) {   // mix() and the ramp return rgb(r,g,b)
    const q = s.slice(4, -1).split(',').map((v) => Number(v.trim()));
    return q.length === 3 && q.every((v) => Number.isFinite(v)) ? q : null;
  }
  if (!s.startsWith('#')) return null;
  const x = s.length === 4 ? s[1] + s[1] + s[2] + s[2] + s[3] + s[3] : s.slice(1, 7);
  const n = parseInt(x, 16);
  return Number.isNaN(n) ? null : [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export const alpha = (h, a) => { const c = rgbOf(h); return c ? `rgba(${c[0]},${c[1]},${c[2]},${a})` : h; };
// k < 0 darkens towards black, k > 0 lightens towards white
export function mix(h, k) {
  const c = rgbOf(h); if (!c) return h;
  const f = (v) => Math.round(k < 0 ? v * (1 + k) : v + (255 - v) * k);
  return `rgb(${f(c[0])},${f(c[1])},${f(c[2])})`;
}
function lerpHex(a, b, t) { const x = rgbOf(a); const y = rgbOf(b); return `rgb(${[0, 1, 2].map((i) => Math.round(x[i] + (y[i] - x[i]) * t)).join(',')})`; }
// the sequential purple ramp, t in 0..1
export function rampColor(t) {
  const k = Math.max(0, Math.min(1, isNum(t) ? t : 0)) * (RAMP.length - 1); const i = Math.min(RAMP.length - 2, Math.floor(k));
  return lerpHex(RAMP[i], RAMP[i + 1], k - i);
}
// how 1-8 tiles share the canvas: the grid whose tiles come closest to a wide card shape
export function tileGrid(n, W, H, gap = 10) {
  if (n <= 0) return { cols: 0, rows: 0, tw: 0, th: 0 };
  let best = null;
  for (let cols = 1; cols <= n; cols++) {
    const rows = Math.ceil(n / cols);
    const tw = (W - gap * (cols - 1)) / cols; const th = Math.min(132, (H - gap * (rows - 1)) / rows);
    if (cols > 1 && tw < 104) continue;
    const score = Math.abs(Math.log(Math.max(.1, tw / Math.max(1, th)) / 1.6)) + (rows * cols - n) * .35 + (th < 64 ? 3 : 0);
    if (!best || score < best.score) best = { cols, rows, tw, th, score };
  }
  return best || { cols: 1, rows: n, tw: W, th: (H - gap * (n - 1)) / n };
}
const font = (size, weight = 600) => `${weight} ${size}px ${FONT_FAMILY}`;
const FT = new Map();
// the most figure tiles one card draws (2026-11-14: every scheme once; was 8)
export const TILE_MAX = 12;
// the label as it fits its slot: whole, or cut with an ellipsis (binary search, cached)
export function fitText(ctx, text, maxW, size = 12, weight = 600) {
  const s = String(text ?? '');
  const key = `${s}|${maxW | 0}|${size}|${weight}`;
  if (FT.has(key)) return FT.get(key);
  ctx.save(); ctx.font = font(size, weight);
  let out = s;
  if (maxW < 10) out = '';
  else if (ctx.measureText(s).width > maxW) {
    let lo = 0; let hi = s.length;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (ctx.measureText(s.slice(0, mid).trimEnd() + '…').width <= maxW) lo = mid; else hi = mid - 1; }
    out = lo > 0 ? s.slice(0, lo).trimEnd() + '…' : '…';
  }
  ctx.restore();
  if (FT.size > 1500) FT.clear();
  FT.set(key, out); return out;
}
/** A label over up to `maxLines` lines (2026-11-14): broken between words, never inside one; what does not fit ends
    the last line with an ellipsis after a whole word. A single word wider than the slot is cut (fitText). */
export function wrapText(ctx, text, maxW, size = 12, weight = 600, maxLines = 2) {
  const ws = String(text ?? '').split(' ').filter(Boolean);
  if (!ws.length || maxW < 10) return [];
  ctx.save(); ctx.font = font(size, weight);
  const fits = (t) => ctx.measureText(t).width <= maxW;
  const lines = []; let cur = ''; let i = 0;
  for (; i < ws.length; i++) {
    const next = cur ? cur + ' ' + ws[i] : ws[i];
    if (fits(next)) { cur = next; continue; }
    if (!cur) { cur = ws[i]; i++; }     // one word wider than the slot: it gets the line (cut below)
    lines.push(cur); cur = '';
    if (lines.length === maxLines) break;
    i--;
  }
  if (lines.length < maxLines && cur) { lines.push(cur); cur = ''; i = ws.length; }
  const more = i < ws.length;
  if (more && lines.length) {           // the rest does not fit: the last line ends on a whole word and an ellipsis
    let last = lines[lines.length - 1];
    while (last.includes(' ') && !fits(last + '…')) last = last.slice(0, last.lastIndexOf(' '));
    lines[lines.length - 1] = last + '…';
  }
  ctx.restore();
  return lines.map((l) => fitText(ctx, l, maxW, size, weight));
}
// a figure is never cut: its font shrinks until it fits (down to minSize)
export function fitSize(ctx, text, maxW, size, weight = 800, minSize = 9) {
  let s = size; ctx.save();
  while (s > minSize) { ctx.font = font(s, weight); if (ctx.measureText(String(text)).width <= maxW) break; s = Math.max(minSize, s - Math.max(.5, s * .06)); }
  ctx.restore(); return s;
}
const now_ = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

// ------------------------------------------------------------------ canvas helpers
function label(ctx, text, x, y, { size = 12, weight = 600, color = T.mute, align = 'center', base = 'middle' } = {}) {
  ctx.font = font(size, weight); ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = base; ctx.fillText(text, x, y);
}
function textW(ctx, text, size, weight) { ctx.font = font(size, weight); return ctx.measureText(String(text)).width; }
function rrect(ctx, x, y, w, h, r) {
  const k = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath(); ctx.moveTo(x + k, y); ctx.arcTo(x + w, y, x + w, y + h, k); ctx.arcTo(x + w, y + h, x, y + h, k);
  ctx.arcTo(x, y + h, x, y, k); ctx.arcTo(x, y, x + w, y, k); ctx.closePath();
}
let HATCH_SRC = null;
function hatch(card) {
  if (card.hp !== undefined) return card.hp;
  card.hp = null;
  try {
    if (!HATCH_SRC) {
      HATCH_SRC = document.createElement('canvas'); HATCH_SRC.width = HATCH_SRC.height = 8;
      const x = HATCH_SRC.getContext('2d'); x.strokeStyle = 'rgba(83,75,104,.30)'; x.lineWidth = 1.1;
      x.beginPath(); x.moveTo(-2, 10); x.lineTo(10, -2); x.moveTo(-2, 2); x.lineTo(2, -2); x.moveTo(6, 10); x.lineTo(10, 6); x.stroke();
    }
    card.hp = card.ctx.createPattern(HATCH_SRC, 'repeat');
  } catch (e) { card.hp = null; }
  return card.hp;
}
// a value that is not in the data: a hatched, dashed slot, never a zero
function noData(ctx, card, x, y, w, h, r = 6) {
  ctx.save(); rrect(ctx, x, y, w, h, r); ctx.fillStyle = T.nodata; ctx.fill();
  const hp = hatch(card); if (hp) { ctx.fillStyle = hp; ctx.fill(); }
  ctx.setLineDash([3, 3]); ctx.strokeStyle = T.line; ctx.lineWidth = 1; ctx.stroke(); ctx.restore();
}
// Mitra's perspective floor under the bars
function floorGrid(ctx, W, H, cam, y0) {
  ctx.save(); ctx.strokeStyle = T.faint; ctx.lineWidth = 1;
  const vx = W / 2 + cam.x * 120;
  for (let i = 0; i <= 10; i++) { const x = (W * i) / 10; ctx.beginPath(); ctx.moveTo(x, H); ctx.lineTo(vx + (x - vx) * .55, y0); ctx.stroke(); }
  for (let j = 0; j < 4; j++) { const k = j / 4; const y = y0 + (H - y0) * (k * k); ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }
  ctx.restore();
}
function sparks(ctx, x, y, col, t, seed) {
  const k = Math.min(1, t / 1100);
  for (let i = 0; i < 10; i++) {
    const a = (seed * 7 + i * 1.7) % TAU; const r = 10 + k * 42;
    ctx.fillStyle = alpha(col, (1 - k) * .75); ctx.beginPath(); ctx.arc(x + Math.cos(a) * r, y - 8 - Math.sin(a) * r - k * 26, 1.7, 0, TAU); ctx.fill();
  }
}
// the hover card: a title, rows of swatch · label · value, an optional foot line
function drawTip(ctx, card, x, y, title, rows, foot) {
  ctx.save();
  const maxW = Math.min(260, card.W - 12);
  let w = Math.min(maxW - 24, textW(ctx, title, 12.5, 800));
  for (const r of rows) w = Math.max(w, Math.min(maxW - 24, (r.color ? 14 : 0) + Math.min(150, textW(ctx, r.label || '', 11.5, 600)) + 18 + textW(ctx, r.value || '', 11.5, 800)));
  if (foot) w = Math.max(w, Math.min(maxW - 24, textW(ctx, foot, 10.5, 700)));
  w += 24; const h = 30 + rows.length * 19 + (foot ? 18 : 0) + 4;
  let tx = x + 16; let ty = y - h - 12;
  if (tx + w > card.W - 4) tx = x - w - 16;
  tx = Math.max(4, Math.min(card.W - w - 4, tx));
  if (ty < 4) ty = Math.min(card.H - h - 4, y + 18);
  ty = Math.max(4, ty);
  ctx.shadowColor = 'rgba(40,20,70,.18)'; ctx.shadowBlur = 24; ctx.shadowOffsetY = 10;
  rrect(ctx, tx, ty, w, h, 12); ctx.fillStyle = 'rgba(255,255,255,.98)'; ctx.fill();
  ctx.shadowColor = 'transparent'; ctx.strokeStyle = T.border; ctx.lineWidth = 1; ctx.stroke();
  label(ctx, fitText(ctx, title, w - 24, 12.5, 800), tx + 12, ty + 16, { size: 12.5, weight: 800, color: T.ink, align: 'left' });
  rows.forEach((r, i) => {
    const ry = ty + 36 + i * 19; let lx = tx + 12;
    if (r.color) { ctx.fillStyle = r.color; ctx.beginPath(); ctx.arc(lx + 4, ry, 4, 0, TAU); ctx.fill(); lx += 14; }
    const vw = textW(ctx, r.value || '', 11.5, 800);
    label(ctx, fitText(ctx, r.label || '', tx + w - 12 - vw - 12 - lx, 11.5, 600), lx, ry, { size: 11.5, color: T.ink2, align: 'left' });
    label(ctx, r.value || '', tx + w - 12, ry, { size: 11.5, weight: 800, color: r.muted ? T.mute : T.ink, align: 'right' });
  });
  if (foot) label(ctx, fitText(ctx, foot, w - 24, 10.5, 700), tx + 12, ty + h - 13, { size: 10.5, weight: 700, color: T.brand, align: 'left' });
  ctx.restore();
}
const colorOf = (it, i) => it.color || TONE[it.tone] || CATEGORICAL[i % CATEGORICAL.length];
const say = (card, v) => { try { return String(card.fmt(v)); } catch (e) { return String(v); } };
// 2026-11-14: a figure tile of a cross-scheme card carries its own unit (the planner's item.fmt: rupees in ₹ crore, a
// count in Indian grouping); the canvas used the card's unitless format, so "3,628.67" lost its "₹ … crore"
const sayItem = (card, it, v) => { if (typeof it.fmt !== 'function') return say(card, v); try { return String(it.fmt(v)); } catch (e) { return String(v); } };
const valueText = (card, it, p) => (isNum(it.value) ? sayItem(card, it, grow(it.value, p)) : 'no data');

// ------------------------------------------------------------------ the shared loop and the camera
const LIVE = new Set();
const CAM = { x: 0, y: 0, tx: 0, ty: 0 };
let RAF = 0; let LAST = 0; let camOn = false; let fontsHooked = false;
const onWinMove = (e) => {
  const w = window.innerWidth || 1; const h = window.innerHeight || 1;
  CAM.tx = (e.clientX / w - .5) * 2; CAM.ty = (e.clientY / h - .5) * 2; kick();
};
function kick() { if (!RAF && LIVE.size && typeof requestAnimationFrame === 'function') RAF = requestAnimationFrame(frame); }
function frame(now) {
  RAF = 0;
  const dt = Math.max(0, Math.min(64, now - (LAST || now))); LAST = now;
  const k = 1 - Math.exp(-dt / 220);
  CAM.x += (CAM.tx - CAM.x) * k; CAM.y += (CAM.ty - CAM.y) * k;
  const camMoving = Math.abs(CAM.tx - CAM.x) + Math.abs(CAM.ty - CAM.y) > .008;
  if (!camMoving) { CAM.x = CAM.tx; CAM.y = CAM.ty; }
  let again = camMoving && [...LIVE].some((c) => !c.reduced);
  for (const card of LIVE) {
    card.step(now, dt);
    const moving = card.moving(now);
    if (card.dirty || moving || (camMoving && !card.reduced)) { card.dirty = false; card.paint(now); }
    if (moving) again = true;
  }
  if (again) RAF = requestAnimationFrame(frame); else LAST = 0;
}
function hookFonts() {
  if (fontsHooked || typeof document === 'undefined' || !document.fonts) return;
  fontsHooked = true;
  const redraw = () => { FT.clear(); for (const c of LIVE) c.dirty = true; kick(); };
  try { document.fonts.ready.then(redraw); document.fonts.addEventListener('loadingdone', redraw); } catch (e) { /* fonts API missing */ }
}

// ------------------------------------------------------------------ renderers
function Bars(card) {
  return {
    draw(ctx, now, cam) {
      const { W, H, items } = card; const n = items.length;
      const vals = items.filter((i) => isNum(i.value)).map((i) => i.value);
      const ax = niceAxis(Math.max(0, ...vals) * 1.08 || 1); const ticks = Array.from({ length: ax.ticks + 1 }, (_, g) => say(card, ax.step * g));
      const padL = Math.max(34, Math.min(96, Math.max(...ticks.map((t) => textW(ctx, t, 10, 600))) + 16)); const padR = 14;
      const gw = (W - padL - padR) / Math.max(1, n); const tilt = n > 8 || gw < 64;
      const hasSub = !tilt && items.some((i) => i.sub);
      const tiltW = Math.min(118, Math.max(...items.map((i) => textW(ctx, i.label, 10.5, 700)), 20));
      const ang = gw < 40 ? 1.0 : .62; const tiltMax = gw < 40 ? 92 : 118;
      const padT = 34; const padB = tilt ? Math.min(100, 20 + Math.min(tiltW, tiltMax) * Math.sin(ang)) : hasSub ? 52 : 38;
      const base = H - padB; const plotH = Math.max(20, base - padT);
      floorGrid(ctx, W, H, cam, base);
      ticks.forEach((t, g) => {
        const y = base - plotH * g / ax.ticks;
        ctx.strokeStyle = g ? T.grid : T.line; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(padL, y + .5); ctx.lineTo(W - padR, y + .5); ctx.stroke();
        label(ctx, t, padL - 9, y, { size: 10, color: T.mute, align: 'right' });
      });
      if (card.unitWord) label(ctx, fitText(ctx, card.unitWord, W - 20, 10, 700), padL - 9, 12, { size: 10, weight: 700, color: T.mute, align: 'left' });
      const bw = Math.min(72, gw * .56); const depth = Math.min(16, bw * .3); const dx = -depth * (.5 + cam.x * .4); const dy = -depth * .55;
      const ls = tilt ? 10.5 : gw < 90 ? 11 : 12; card.hits = [];
      items.forEach((it, i) => {
        const col = colorOf(it, i); const x = padL + gw * i + (gw - bw) / 2; const p = card.pOf(it, now);
        const hot = card.hoverKey === it.key; const dim = card.highlight && card.highlight !== it.key && !hot;
        card.hits.push({ key: it.key, x: padL + gw * i, y: padT - 10, w: gw, h: H - padT });
        const name = (color, wt) => {
          if (!tilt) {
            label(ctx, fitText(ctx, it.label, gw - 8, ls, wt), x + bw / 2, base + 17, { size: ls, weight: wt, color });
            if (hasSub && it.sub) label(ctx, fitText(ctx, it.sub, gw - 8, 10, 600), x + bw / 2, base + 33, { size: 10, color: T.mute });
            return;
          }
          ctx.save(); ctx.translate(x + bw / 2 + 4, base + 12); ctx.rotate(-ang);
          label(ctx, fitText(ctx, it.label, tiltMax, ls, wt), 0, 0, { size: ls, weight: wt, color, align: 'right' }); ctx.restore();
        };
        if (!it.on) {
          ctx.save(); ctx.setLineDash([4, 5]); ctx.strokeStyle = T.line; rrect(ctx, x, base - 6, bw, 6, 2); ctx.stroke(); ctx.restore();
          name(T.mute, 600); return;
        }
        ctx.save(); ctx.globalAlpha = dim ? .5 : Math.min(1, p * 4);
        if (!isNum(it.value)) {
          const hh = Math.min(30, plotH * .22); noData(ctx, card, x, base - hh, bw, hh, 4);
          if (gw >= 50) label(ctx, 'no data', x + bw / 2, base - hh - 10, { size: 10, weight: 700, color: T.mute });
          else { ctx.save(); ctx.translate(x + bw / 2, base - hh - 6); ctx.rotate(-Math.PI / 2); label(ctx, 'no data', 0, 0, { size: 9.5, weight: 700, color: T.mute, align: 'left' }); ctx.restore(); }
          ctx.restore(); name(T.ink2, 700); return;
        }
        const h = Math.max(2, plotH * Math.max(0, it.value) / ax.top * p); const y = base - h;
        const sp = card.spotOf(it.key, now);
        if (sp > .01) {   // the spotlight: a soft column of light behind the bar being named
          const bg = ctx.createLinearGradient(0, padT - 18, 0, base); bg.addColorStop(0, alpha(col, 0)); bg.addColorStop(1, alpha(col, .15 * sp));
          ctx.fillStyle = bg; ctx.fillRect(x - bw * .3, padT - 18, bw * 1.6, base - padT + 18);
        }
        const fg = ctx.createRadialGradient(x + bw / 2, base + 4, 2, x + bw / 2, base + 4, bw * 1.1);
        fg.addColorStop(0, alpha(col, (.26 + .2 * sp) * p)); fg.addColorStop(1, alpha(col, 0)); ctx.fillStyle = fg; ctx.fillRect(x - bw * .6, base - 6, bw * 2.2, 28);
        ctx.fillStyle = mix(col, -.28); ctx.beginPath(); ctx.moveTo(x + bw, y); ctx.lineTo(x + bw - dx, y + dy); ctx.lineTo(x + bw - dx, base + dy); ctx.lineTo(x + bw, base); ctx.closePath(); ctx.fill();
        ctx.fillStyle = mix(col, .42); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - dx, y + dy); ctx.lineTo(x + bw - dx, y + dy); ctx.lineTo(x + bw, y); ctx.closePath(); ctx.fill();
        const g = ctx.createLinearGradient(0, y, 0, base); g.addColorStop(0, mix(col, .16)); g.addColorStop(1, mix(col, -.1));
        ctx.save(); ctx.shadowColor = alpha(col, hot ? .42 : .26 + .22 * sp); ctx.shadowBlur = hot ? 26 : 16 + 14 * sp; ctx.shadowOffsetY = 8; ctx.fillStyle = g; ctx.fillRect(x, y, bw, h); ctx.restore();
        ctx.fillStyle = 'rgba(255,255,255,.45)'; ctx.fillRect(x, y, 2.5, h);
        if (hot || card.highlight === it.key) { ctx.strokeStyle = mix(col, -.35); ctx.lineWidth = 1.5; ctx.strokeRect(x + .75, y + .75, bw - 1.5, h - 1.5); }
        const ra = card.ringOf(it.key, now);
        if (ra >= 0) {   // one ring opens from the top of the bar as it is named
          const k = ra / SPOT.ring; const rr = bw * (.36 + .7 * ease(k));
          ctx.globalAlpha = .7 * (1 - k); ctx.strokeStyle = mix(col, -.1); ctx.lineWidth = 2;
          ctx.beginPath(); ctx.ellipse(x + bw / 2 - dx / 2, y + dy / 2, rr, rr * .3, 0, 0, TAU); ctx.stroke();
        }
        ctx.restore();
        const vt = valueText(card, it, p); const vs = fitSize(ctx, vt, gw + 4, (gw < 56 ? 11 : gw < 90 ? 13 : 14.5) + 1.5 * sp, 800, 8.5);
        label(ctx, vt, x + bw / 2 - dx / 2, Math.max(10, y + dy - 12), { size: vs, weight: 800, color: dim ? T.ink2 : sp > .2 ? mix(col, -.45) : T.ink });
        name(hot || card.highlight === it.key || sp > .2 ? T.ink : T.ink2, sp > .2 ? 800 : 700);
        const age = now - it.t0;
        if (!card.reduced && age > GROW.bars - 300 && age < GROW.bars + 900) sparks(ctx, x + bw / 2, y, col, age - (GROW.bars - 300), i);
      });
    },
    tip(ctx) { return card.itemTip(ctx); },
  };
}

function Race(card) {
  return {
    draw(ctx, now, cam) {
      const { W, H, items } = card; const n = items.length;
      const max = Math.max(1e-9, ...items.filter((i) => isNum(i.value)).map((i) => i.value));
      const padT = card.unitWord ? 20 : 6; const rowH = Math.min(40, (H - padT - 6) / Math.max(1, n));
      const fs = rowH < 22 ? 10.5 : 12;
      const lw = Math.min(W * .32, 180, Math.max(40, ...items.map((i) => textW(ctx, i.label, fs, 700))) + 6);
      const valW = Math.max(44, ...items.map((i) => textW(ctx, isNum(i.value) ? say(card, i.value) : 'no data', fs + .5, 800))) + 12;
      const x0 = lw + 14; const x1 = W - valW - 6; const bh = Math.max(6, Math.min(16, rowH * .46)); const depth = Math.min(6, bh * .45);
      if (card.unitWord) label(ctx, fitText(ctx, card.unitWord, W - 20, 10, 700), x0, 10, { size: 10, weight: 700, color: T.mute, align: 'left' });
      card.hits = [];
      items.forEach((it, i) => {
        const y = padT + rowH * i + rowH / 2; const col = colorOf(it, i); const p = card.pOf(it, now);
        const sp = card.spotOf(it.key, now);
        const hot = card.hoverKey === it.key; const em = hot || card.highlight === it.key || sp > .3; const dim = card.highlight && !em;
        card.hits.push({ key: it.key, x: 0, y: y - rowH / 2, w: W, h: rowH });
        if (hot || sp > .01) { rrect(ctx, 2, y - rowH / 2 + 1, W - 4, rowH - 2, 8); ctx.fillStyle = `rgba(124,63,191,${(hot ? .05 : .075 * sp).toFixed(3)})`; ctx.fill(); }
        rrect(ctx, x0, y - bh / 2, x1 - x0, bh, bh / 2); ctx.fillStyle = T.faint; ctx.fill();
        label(ctx, fitText(ctx, it.label, lw, fs, em ? 800 : 700), x0 - 12, y, { size: fs, weight: em ? 800 : 700, color: it.on ? (dim ? T.mute : T.ink) : T.mute, align: 'right' });
        if (!it.on) return;
        ctx.save(); ctx.globalAlpha = dim ? .45 : Math.min(1, p * 3);
        if (!isNum(it.value)) {
          noData(ctx, card, x0, y - bh / 2, Math.min(x1 - x0, 90), bh, bh / 2);
          label(ctx, 'no data', x0 + Math.min(x1 - x0, 90) + 8, y, { size: fs, weight: 700, color: T.mute, align: 'left' });
          ctx.restore(); return;
        }
        const w = Math.max(bh, (x1 - x0) * Math.max(0, it.value) / max * p);
        rrect(ctx, x0 + depth * (.7 + cam.x * .3), y - bh / 2 + depth * .8, w, bh, bh / 2); ctx.fillStyle = alpha(mix(col, -.3), .32); ctx.fill();
        const g = ctx.createLinearGradient(x0, 0, x0 + w, 0); g.addColorStop(0, mix(col, -.06)); g.addColorStop(1, mix(col, .3));
        ctx.save(); ctx.shadowColor = alpha(col, em ? .45 : .22); ctx.shadowBlur = em ? 18 : 10; ctx.shadowOffsetY = 3;
        rrect(ctx, x0, y - bh / 2, w, bh, bh / 2); ctx.fillStyle = g; ctx.fill(); ctx.restore();
        ctx.fillStyle = 'rgba(255,255,255,.5)'; rrect(ctx, x0 + bh / 2, y - bh / 2 + 1.5, Math.max(0, w - bh), 1.6, .8); ctx.fill();
        if (sp > .01) {   // the head of the bar being named glows
          const hr = bh * 1.7; const hg = ctx.createRadialGradient(x0 + w - bh / 2, y, 0, x0 + w - bh / 2, y, hr);
          hg.addColorStop(0, `rgba(255,255,255,${(.85 * sp).toFixed(3)})`); hg.addColorStop(.4, alpha(col, .45 * sp)); hg.addColorStop(1, alpha(col, 0));
          ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(x0 + w - bh / 2, y, hr, 0, TAU); ctx.fill();
        }
        const vt = valueText(card, it, p);
        label(ctx, vt, x0 + w + 9, y, { size: fitSize(ctx, vt, W - (x0 + w + 9) - 2, fs + .5, 800, 8), weight: 800, color: T.ink, align: 'left' });
        ctx.restore();
      });
    },
    tip(ctx) { return card.itemTip(ctx); },
  };
}

function Line(card) {
  const L = card.line;
  return {
    draw(ctx, now, cam) {
      const { W, H } = card; const xs = card.x; const n = xs.length; const S = card.series;
      const all = []; S.forEach((s) => s.values.forEach((v) => { if (isNum(v)) all.push(v); }));
      const legend = S.length > 1;
      // the legend (several series) and the unit share the top rows
      const leg = []; let lx = 0; let ly = 11;
      if (legend) S.forEach((s) => { const t = fitText(ctx, s.name, 150, 11, 700); const w = textW(ctx, t, 11, 700) + 26; if (lx + w > W - 12 && lx > 0) { lx = 0; ly += 17; } leg.push({ s, t, x: lx, y: ly }); lx += w; });
      const uw = card.unit ? textW(ctx, card.unit, 10, 700) + 8 : 0;
      let unitAt = null;
      if (card.unit) { if (!legend) unitAt = { y: 10 }; else if (lx + uw < W - 16) unitAt = { y: ly, right: true }; else { ly += 16; unitAt = { y: ly }; } }
      const padT = (legend || card.unit ? ly + 14 : 14) + 6; const padR = 22; const padB = 36;
      const hi = all.length ? Math.max(...all) : 1; const lo = all.length ? Math.min(...all) : 0;
      const ax = niceAxis(Math.max(1e-9, hi - (lo >= 0 && lo < hi * .5 ? 0 : lo)) * 1.08);
      const min = lo >= 0 && lo < hi * .5 ? 0 : Math.floor(lo * .95 / ax.step) * ax.step; const max = min + ax.top;
      const ticks = Array.from({ length: ax.ticks + 1 }, (_, g) => say(card, min + ax.step * g));
      const padL = Math.max(34, Math.min(96, Math.max(...ticks.map((t) => textW(ctx, t, 10, 600))) + 16));
      const X = (i) => padL + (W - padL - padR) * (n > 1 ? i / (n - 1) : .5);
      const Y = (v) => H - padB - (H - padT - padB) * ((v - min) / Math.max(1e-9, max - min));
      floorGrid(ctx, W, H, cam, H - padB);
      ticks.forEach((t, g) => {
        const y = Y(min + ax.step * g); ctx.strokeStyle = g ? T.grid : T.line; ctx.beginPath(); ctx.moveTo(padL, y + .5); ctx.lineTo(W - padR, y + .5); ctx.stroke();
        label(ctx, t, padL - 9, y, { size: 10, color: T.mute, align: 'right' });
      });
      const lx0 = Math.min(padL - 9, 12);
      leg.forEach(({ s, t, x, y }) => {
        const em = !card.highlight || card.highlight === s.key;
        ctx.fillStyle = em ? s.color : alpha(s.color, .4); rrect(ctx, lx0 + x, y - 2, 12, 4, 2); ctx.fill();
        label(ctx, t, lx0 + x + 17, y, { size: 11, weight: 700, color: em ? T.ink2 : T.mute, align: 'left' });
      });
      if (unitAt) label(ctx, fitText(ctx, card.unit, W - 24, 10, 700), unitAt.right ? W - padR : lx0, unitAt.y, { size: 10, weight: 700, color: T.mute, align: unitAt.right ? 'right' : 'left' });
      const head = L.head; const upto = Math.max(0, Math.min(n - 1, head));
      const single = S.length === 1; const depth = 12 + cam.y * 5; const px = -6 - cam.x * 8;
      S.forEach((s, si) => {
        const col = s.color; const em = !card.highlight || card.highlight === s.key;
        const runs = []; let cur = null;   // runs of consecutive numbers; a null breaks the line
        s.values.forEach((v, i) => { if (isNum(v)) { if (!cur) { cur = []; runs.push(cur); } cur.push([i, v]); } else cur = null; });
        const pathOf = (run) => {
          const pts = [];
          for (const [i, v] of run) { if (i <= upto + 1e-6) pts.push([X(i), Y(v)]); else break; }
          const last = pts.length ? run[pts.length - 1] : null; const next = run[pts.length];
          if (last && next && next[0] - last[0] === 1 && upto > last[0]) {   // the head between two points
            const f = Math.min(1, upto - last[0]); pts.push([X(last[0]) + (X(next[0]) - X(last[0])) * f, Y(last[1]) + (Y(next[1]) - Y(last[1])) * f]);
          }
          return pts;
        };
        ctx.save(); ctx.globalAlpha = em ? 1 : .38;
        runs.forEach((run, ri) => {   // the dashed bridge over a gap, once the head has passed it
          const nx = runs[ri + 1]; if (!nx) return;
          const a = run[run.length - 1]; const b = nx[0]; if (upto + 1e-6 < b[0]) return;
          ctx.save(); ctx.setLineDash([4, 5]); ctx.strokeStyle = alpha(col, .45); ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(X(a[0]), Y(a[1])); ctx.lineTo(X(b[0]), Y(b[1])); ctx.stroke(); ctx.restore();
        });
        runs.forEach((run) => {
          const pts = pathOf(run); if (pts.length < 2) return;
          if (single) {
            ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); pts.forEach((q) => ctx.lineTo(q[0], q[1]));
            for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(pts[i][0] + px, pts[i][1] + depth);
            ctx.closePath(); ctx.fillStyle = alpha(col, .13); ctx.fill();
            ctx.beginPath(); ctx.moveTo(pts[0][0], H - padB); pts.forEach((q) => ctx.lineTo(q[0], q[1])); ctx.lineTo(pts[pts.length - 1][0], H - padB); ctx.closePath();
            const ag = ctx.createLinearGradient(0, padT, 0, H - padB); ag.addColorStop(0, alpha(col, .2)); ag.addColorStop(1, alpha(col, 0)); ctx.fillStyle = ag; ctx.fill();
          }
          ctx.save(); ctx.shadowColor = alpha(col, .35); ctx.shadowBlur = 10; ctx.shadowOffsetY = 4;
          ctx.strokeStyle = col; ctx.lineWidth = card.highlight === s.key ? 3.6 : single ? 3 : 2.4; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
          ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); pts.forEach((q) => ctx.lineTo(q[0], q[1])); ctx.stroke(); ctx.restore();
        });
        // points
        s.values.forEach((v, i) => {
          if (!isNum(v) || i > upto + 1e-6) return;
          const r = n > 24 ? 2.2 : (single ? 4 : 3.4) * (card.hoverIdx === i ? 1.35 : 1);
          ctx.fillStyle = '#fff'; ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(X(i), Y(v), r, 0, TAU); ctx.fill(); ctx.stroke();
        });
        // the glowing head while it travels
        if (!card.reduced && L.head < L.target - 1e-3 && L.head > 0) {
          const k = Math.floor(upto); const v0 = s.values[k]; const v1 = s.values[Math.min(n - 1, k + 1)];
          if (isNum(v0) && isNum(v1)) {
            const f = upto - k; const hx = X(k) + (X(k + 1) - X(k)) * f; const hy = Y(v0) + (Y(v1) - Y(v0)) * f;
            const hg = ctx.createRadialGradient(hx, hy, 0, hx, hy, 14); hg.addColorStop(0, 'rgba(255,255,255,.95)'); hg.addColorStop(.35, alpha(col, .55)); hg.addColorStop(1, alpha(col, 0));
            ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(hx, hy, 14, 0, TAU); ctx.fill();
          }
        }
        ctx.restore();
      });
      // the spotlight: the point being named gets a guide of light and a halo on every series
      card.items.forEach((it, i) => {
        const sp = card.spotOf(it.key, now); if (sp < .01 || i > upto + 1e-6) return;
        const x = X(i); const gg = ctx.createLinearGradient(0, padT, 0, H - padB);
        gg.addColorStop(0, 'rgba(124,63,191,0)'); gg.addColorStop(1, `rgba(124,63,191,${(.16 * sp).toFixed(3)})`);
        ctx.fillStyle = gg; ctx.fillRect(x - 9, padT, 18, H - padB - padT);
        const ra = card.ringOf(it.key, now);
        S.forEach((s) => {
          const v = s.values[i]; if (!isNum(v)) return;
          const y = Y(v); const hr = 10 + 8 * sp; const hg = ctx.createRadialGradient(x, y, 0, x, y, hr);
          hg.addColorStop(0, `rgba(255,255,255,${(.9 * sp).toFixed(3)})`); hg.addColorStop(.45, alpha(s.color, .5 * sp)); hg.addColorStop(1, alpha(s.color, 0));
          ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(x, y, hr, 0, TAU); ctx.fill();
          if (ra >= 0) { const k = ra / SPOT.ring; ctx.save(); ctx.globalAlpha = .7 * (1 - k); ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 6 + 18 * ease(k), 0, TAU); ctx.stroke(); ctx.restore(); }
        });
      });
      // 'no data': a hollow mark where a value is missing (on the dashed bridge, or on the floor before / after the
      // series), and the words once per gap
      const said = [];
      const noDataAt = (x, y) => {
        const w = textW(ctx, 'no data', 9.5, 700) + 6; let yy = y - 12;
        if (said.some((q) => Math.abs(q.x - x) < (q.w + w) / 2 && Math.abs(q.y - yy) < 12)) return;
        yy = Math.max(padT - 4, yy); said.push({ x, y: yy, w });
        label(ctx, 'no data', Math.max(padL + w / 2, Math.min(W - padR - w / 2 + 10, x)), yy, { size: 9.5, weight: 700, color: T.mute });
      };
      S.forEach((s) => {
        const v = s.values; let i = 0;
        while (i < n) {
          if (isNum(v[i])) { i++; continue; }
          let j = i; while (j + 1 < n && !isNum(v[j + 1])) j++;          // the gap is i..j
          const a = i - 1; const b = j + 1; const bridge = a >= 0 && b < n;
          for (let k = i; k <= j && k <= upto + 1e-6; k++) {
            const y = bridge ? Y(v[a]) + (Y(v[b]) - Y(v[a])) * ((k - a) / (b - a)) : H - padB - 6;
            if (bridge && upto + 1e-6 < b) continue;
            ctx.save(); ctx.globalAlpha = !card.highlight || card.highlight === s.key ? 1 : .4;
            ctx.fillStyle = '#fff'; ctx.strokeStyle = alpha(s.color, .75); ctx.lineWidth = 1.5; ctx.setLineDash([2, 2]);
            ctx.beginPath(); ctx.arc(X(k), y, 3.6, 0, TAU); ctx.fill(); ctx.stroke(); ctx.restore();
            if (k === Math.floor((i + j) / 2)) noDataAt(X(k), y);
          }
          i = j + 1;
        }
      });
      // x labels, thinned so they never collide
      const lblW = Math.max(10, ...xs.map((t) => textW(ctx, t, 11, 700)));
      const gap = (W - padL - padR) / Math.max(1, n - 1); const every = Math.max(1, Math.ceil((lblW + 10) / Math.max(1, gap)));
      xs.forEach((t, i) => {
        if (!(i % every === 0 || (i === n - 1 && (n - 1) % every >= every / 2))) return;
        const shown = i <= upto + 1e-6 && card.items[i].on; const lit = shown && card.spotOf(card.items[i].key, now) > .2;
        let x = X(i); const w = Math.min(lblW, gap * every - 6);
        const tt = fitText(ctx, t, Math.max(30, w), 11, 700); const tw = textW(ctx, tt, 11, 700);
        x = Math.max(tw / 2 + 2, Math.min(W - tw / 2 - 2, x));
        label(ctx, tt, x, H - padB + 17, { size: 11, weight: lit ? 800 : shown ? 700 : 600, color: lit ? T.deep : shown ? T.ink2 : T.mute });
      });
      // peak and low (one series, once fully drawn)
      if (single && L.head >= n - 1 - 1e-3 && all.length > 1) {
        const v = S[0].values; const nums = v.map((q, i) => [q, i]).filter((q) => isNum(q[0]));
        const pk = nums.reduce((a, b) => (b[0] > a[0] ? b : a)); const lw = nums.reduce((a, b) => (b[0] < a[0] ? b : a));
        if (pk[1] !== lw[1]) {
          [[pk, -15, T.ink], [lw, 17, T.ink2]].forEach(([q, off, c]) => {
            const t = say(card, q[0]); const tw = textW(ctx, t, 12, 800);
            const x = Math.max(padL + tw / 2 + 2, Math.min(W - tw / 2 - 4, X(q[1]))); const y = Math.max(padT - 8, Math.min(H - padB - 8, Y(q[0]) + off));
            ctx.fillStyle = 'rgba(255,255,255,.85)'; rrect(ctx, x - tw / 2 - 5, y - 9, tw + 10, 18, 9); ctx.fill();
            label(ctx, t, x, y, { size: 12, weight: 800, color: c });
          });
        }
      }
      // hover: a guide line at the nearest x
      card.hits = [];
      card.lineGeom = { X, padL, padR, padT, padB, n };
      if (isNum(card.hoverIdx) && card.hoverIdx <= upto + 1e-6) {
        const x = X(card.hoverIdx);
        ctx.save(); ctx.setLineDash([3, 4]); ctx.strokeStyle = 'rgba(124,63,191,.4)'; ctx.beginPath(); ctx.moveTo(x, padT - 6); ctx.lineTo(x, H - padB); ctx.stroke(); ctx.restore();
      }
    },
    hit(x, y) {
      const g = card.lineGeom; if (!g || x < g.padL - 20 || x > card.W - g.padR + 20) return null;
      const i = g.n > 1 ? Math.round((x - g.padL) / ((card.W - g.padL - g.padR) / (g.n - 1))) : 0;
      if (i < 0 || i >= g.n || !card.items[i].on || i > card.line.head + 1e-6) return null;
      card.hoverIdx = i; return card.x[i];
    },
    tip(ctx) {
      const i = card.hoverIdx; if (!isNum(i) || !card.ptr) return;
      drawTip(ctx, card, card.ptr.x, card.ptr.y, card.x[i], card.series.map((s) => ({ color: s.color, label: s.name, value: isNum(s.values[i]) ? say(card, s.values[i]) : 'no data', muted: !isNum(s.values[i]) })));
    },
  };
}

function Donut(card) {
  return {
    draw(ctx, now, cam) {
      const { W, H, items } = card; const n = items.length;
      const parts = items.map((it, i) => ({ it, i, col: colorOf(it, i) }));
      const tot = parts.reduce((a, q) => a + (isNum(q.it.value) ? Math.max(0, q.it.value) : 0), 0) || 1;
      const wide = W >= 420 && W > H * 1.2; const tilt = .6 + cam.y * .05;
      let cx; let cy; let R; let lx; let ly; let lcols = 1; let rowH = 22; let legW;
      if (wide) {
        legW = Math.min(280, Math.max(190, W * .42)); const ringW = W - legW - 24;
        R = Math.max(30, Math.min(165, ringW / 2 - 18, (H - 46) / (2 * tilt))); cx = ringW / 2 + 6; cy = H / 2 - 6;
        lx = W - legW - 4; rowH = Math.min(28, (H - 20) / Math.max(1, n)); ly = H / 2 - (rowH * n) / 2 + rowH / 2;
      } else {
        lcols = W >= 340 && n > 3 ? 2 : 1; rowH = 20; const lrows = Math.ceil(n / lcols); const legH = lrows * rowH + 10;
        const ringH = Math.max(80, H - legH - 4); R = Math.max(26, Math.min(W / 2 - 34, 130, (ringH - 34) / (2 * tilt))); cx = W / 2; cy = ringH / 2 - 4;
        lx = 8; legW = (W - 16) / lcols; ly = ringH + rowH / 2;
      }
      const th = Math.max(12, Math.min(30, R * .3)); const depth = Math.max(8, Math.min(18, R * .14));
      card.geom = { cx, cy, R, th, tilt };
      ctx.save(); ctx.shadowColor = 'rgba(74,35,128,.12)'; ctx.shadowBlur = 22; ctx.shadowOffsetY = depth + 8;
      ctx.beginPath(); ctx.ellipse(cx, cy, R, R * tilt, 0, 0, TAU); ctx.strokeStyle = T.faint; ctx.lineWidth = th; ctx.stroke(); ctx.restore();
      const segs = []; let a0 = -Math.PI / 2;
      parts.forEach((q) => {
        const v = isNum(q.it.value) ? Math.max(0, q.it.value) : 0; const full = TAU * v / tot;
        if (q.it.on && full > 0) segs.push({ ...q, a0, span: full * card.pOf(q.it, now), full });
        a0 += full;
      });
      const gapA = segs.length > 1 ? .014 : 0;
      // a slice pops out when hovered, highlighted, or named by the voice (by how lit it is)
      const off = (s) => { const em = card.hoverKey === s.it.key || card.highlight === s.it.key; const k = em ? 1 : card.spotOf(s.it.key, now); const m = s.a0 + s.full / 2; return k > .001 ? [Math.cos(m) * 7 * k, Math.sin(m) * 7 * tilt * k] : [0, 0]; };
      segs.forEach((s) => {   // the side first, all of them, then the tops
        const [ox, oy] = off(s);
        for (let d = depth; d > 0; d -= 2) {
          ctx.beginPath(); ctx.ellipse(cx + ox, cy + oy + d, R, R * tilt, 0, s.a0 + gapA, s.a0 + Math.max(gapA, s.span - gapA));
          ctx.strokeStyle = mix(s.col, -.16 - .2 * (d / depth)); ctx.lineWidth = th; ctx.stroke();
        }
      });
      segs.forEach((s) => {
        const [ox, oy] = off(s); const em = card.hoverKey === s.it.key || card.highlight === s.it.key;
        const dim = (card.hoverKey || card.highlight) && !em; const sp = em ? 1 : card.spotOf(s.it.key, now);
        ctx.save(); if (sp > .01) { ctx.shadowColor = alpha(s.col, .45 * sp); ctx.shadowBlur = 18 + (em ? 0 : 8 * sp); }
        ctx.globalAlpha = dim ? .55 : 1;
        ctx.beginPath(); ctx.ellipse(cx + ox, cy + oy, R, R * tilt, 0, s.a0 + gapA, s.a0 + Math.max(gapA, s.span - gapA));
        ctx.strokeStyle = s.col; ctx.lineWidth = th; ctx.stroke();
        ctx.beginPath(); ctx.ellipse(cx + ox, cy + oy - th * .32, R, R * tilt, 0, s.a0 + gapA, s.a0 + Math.max(gapA, s.span - gapA));
        ctx.strokeStyle = 'rgba(255,255,255,.28)'; ctx.lineWidth = 2; ctx.stroke(); ctx.restore();
      });
      // the centre: the hovered part, else the total the caller gave
      const inner = 2 * (R - th / 2) - 12; const hv = items.find((it) => it.key === card.hoverKey && it.on);
      if (hv) {
        const ht = valueText(card, hv, 1); const hs = fitSize(ctx, ht, inner * .86, Math.max(13, Math.min(24, R * .22)), 800, 10);
        label(ctx, ht, cx, cy - 6, { size: hs, weight: 800, color: T.ink });
        label(ctx, fitText(ctx, hv.label, inner, 10.5, 700), cx, cy + 14, { size: 10.5, weight: 700, color: T.mute });
      } else if (card.total !== undefined && card.total !== null) {
        const ps = items.filter((it) => it.on).map((it) => card.pOf(it, now)); const pAvg = items.length ? ps.reduce((a, b) => a + b, 0) / items.length : 0;
        const tv = isNum(card.total) ? say(card, grow(card.total, card.reduced ? 1 : pAvg)) : String(card.total);
        const fs = fitSize(ctx, tv, inner * .86, Math.max(14, Math.min(30, R * .24)), 800, 11);
        label(ctx, tv, cx, cy - 5, { size: fs, weight: 800, color: T.ink });
        label(ctx, fitText(ctx, card.unit || 'total', inner, 10, 700), cx, cy + fs * .55 + 4, { size: 10, weight: 700, color: T.mute });
      }
      // the legend, drawn here
      card.hits = [];
      parts.forEach((q, j) => {
        const c = wide ? 0 : j % lcols; const r = wide ? j : Math.floor(j / lcols);
        const x = lx + c * legW; const y = ly + r * rowH; const it = q.it; const sp = card.spotOf(it.key, now);
        const em = card.hoverKey === it.key || card.highlight === it.key || sp > .3;
        card.hits.push({ key: it.key, x: x - 4, y: y - rowH / 2, w: legW, h: rowH });
        if (em || sp > .01) { rrect(ctx, x - 4, y - rowH / 2 + 1, legW - 2, rowH - 2, 7); ctx.fillStyle = `rgba(124,63,191,${(card.hoverKey === it.key || card.highlight === it.key ? .06 : .08 * sp).toFixed(3)})`; ctx.fill(); }
        if (!isNum(it.value)) noData(ctx, card, x, y - 5, 10, 10, 3);
        else { ctx.fillStyle = it.on ? q.col : alpha(q.col, .28); rrect(ctx, x, y - 5, 10, 10, 3); ctx.fill(); }
        const vt = it.on ? valueText(card, it, card.pOf(it, now)) : ''; const vw = textW(ctx, vt, 11.5, 800);
        label(ctx, fitText(ctx, it.label, legW - vw - 30, 11.5, em ? 800 : 600), x + 17, y, { size: 11.5, weight: em ? 800 : 600, color: it.on ? T.ink2 : T.mute, align: 'left' });
        if (vt) label(ctx, vt, x + legW - 8, y, { size: 11.5, weight: 800, color: isNum(it.value) ? T.ink : T.mute, align: 'right' });
      });
    },
    hit(x, y) {
      const g = card.geom; if (!g) return null;
      const dx = x - g.cx; const dy = (y - g.cy) / g.tilt; const r = Math.hypot(dx, dy);
      if (Math.abs(r - g.R) > g.th / 2 + 6) return null;
      let a = Math.atan2(dy, dx) + Math.PI / 2; if (a < 0) a += TAU;
      const tot = card.items.reduce((s, it) => s + (isNum(it.value) ? Math.max(0, it.value) : 0), 0) || 1;
      let acc = 0;
      for (const it of card.items) { const f = TAU * (isNum(it.value) ? Math.max(0, it.value) : 0) / tot; if (a >= acc && a < acc + f) return it.on ? it.key : null; acc += f; }
      return null;
    },
    tip() { /* the centre and the legend row already show the hovered part */ },
  };
}

// a figure's text as [number, unit word]: "₹3,628.67 crore" -> ["₹3,628.67", "crore"], so the word can sit smaller
export function splitUnit(text) {
  const t = String(text ?? '');
  for (const w of [' crore', ' lakh']) if (t.endsWith(w)) return [t.slice(0, -w.length), w.trim()];
  return [t, ''];
}

/* The figure tiles (2026-11-14): eight schemes sit in a balanced grid (4 x 2 on a wide card), each in its scheme's hue;
   every figure is drawn at ONE size (the size the longest final figure fits at), so the largest number never
   dominates and nothing jumps while they count up; the unit word sits smaller beside the number; under it the tile
   says plainly what it counts, on up to two lines, broken between words. */
function Tiles(card) {
  let sized = { key: '', vfs: 0 };
  return {
    draw(ctx, now) {
      const { W, H, items } = card; const n = items.length; const gap = 10;
      const G = tileGrid(n, W - 4, H - 4, gap); const y0 = Math.max(2, (H - (G.th * G.rows + gap * (G.rows - 1))) / 2);
      const padX = Math.min(16, G.tw * .09); const inner = G.tw - padX * 2;
      const vs = Math.max(16, Math.min(34, G.th * .3, G.tw * .19));
      const subLines = G.th >= 104 ? 2 : G.th >= 78 ? 1 : 0;
      const key = `${W | 0}x${H | 0}|${typeof document !== 'undefined' && document.fonts ? document.fonts.status : ''}`;   // re-fit once the font has loaded
      if (sized.key !== key) {
        const finals = items.map((it) => (isNum(it.value) ? splitUnit(sayItem(card, it, it.value)) : ['no data', '']));
        const fitOne = ([num, word]) => {
          const ww = word ? textW(ctx, word, Math.max(10, vs * .42), 700) + 5 : 0;
          return fitSize(ctx, num, Math.max(20, inner - ww), vs, 800, 10);
        };
        sized = { key, vfs: Math.min(vs, ...finals.map(fitOne)) };
      }
      const vfs = sized.vfs; const ws = Math.max(10, Math.min(13, vfs * .42));
      card.hits = [];
      items.forEach((it, i) => {
        const r0 = Math.floor(i / G.cols); const inRow = Math.min(G.cols, n - r0 * G.cols);
        const rowX = 2 + (W - 4 - (G.tw * inRow + gap * (inRow - 1))) / 2;   // a short last row is centred
        const sp = card.spotOf(it.key, now);
        const x = rowX + (i % G.cols) * (G.tw + gap); const y = y0 + r0 * (G.th + gap) - 3 * sp;   // the named tile lifts
        const col = it.color || TONE[it.tone] || T.brand; const p = card.pOf(it, now); const em = card.hoverKey === it.key || card.highlight === it.key || sp > .3;
        card.hits.push({ key: it.key, x, y, w: G.tw, h: G.th });
        ctx.save(); ctx.shadowColor = em ? alpha(col, .22 + .1 * sp) : 'rgba(74,35,128,.09)'; ctx.shadowBlur = em ? 26 + 8 * sp : 18; ctx.shadowOffsetY = em ? 10 : 6;
        rrect(ctx, x, y, G.tw, G.th, 14); ctx.fillStyle = '#fff'; ctx.fill(); ctx.restore();
        if (sp > .01) { ctx.save(); rrect(ctx, x - 1.5, y - 1.5, G.tw + 3, G.th + 3, 15.5); ctx.strokeStyle = alpha(col, .4 * sp); ctx.lineWidth = 3; ctx.stroke(); ctx.restore(); }
        ctx.save(); rrect(ctx, x, y, G.tw, G.th, 14); ctx.clip();
        const wash = ctx.createLinearGradient(x, y, x + G.tw, y + G.th); wash.addColorStop(0, alpha(col, .05 + .06 * p)); wash.addColorStop(1, alpha(col, 0));
        ctx.fillStyle = wash; ctx.fillRect(x, y, G.tw, G.th);
        ctx.fillStyle = alpha(col, .1); ctx.fillRect(x, y + G.th - 4, G.tw, 4);
        ctx.fillStyle = col; ctx.fillRect(x, y + G.th - 4, G.tw * (it.on ? p : 0), 4);
        ctx.restore();
        rrect(ctx, x + .5, y + .5, G.tw - 1, G.th - 1, 14); ctx.strokeStyle = em ? alpha(col, .55) : T.border; ctx.lineWidth = 1; ctx.stroke();
        const ls = G.th < 80 ? 10.5 : 11.5;
        // the rows: the scheme, the figure, then what it counts (one or two lines) — spread over the tile's height
        const top = y + Math.max(10, G.th * .1); const bot = y + G.th - 4 - Math.max(8, G.th * .08);
        const ly = top + ls / 2;
        const ss = G.tw >= 200 && G.th >= 110 ? 11.5 : 10.5; const sl = ss + 3;   // what it counts: larger on a large tile
        const subH = subLines && it.sub ? sl * subLines : 0;
        const vy = subH ? ly + ls / 2 + (bot - subH - (ly + ls / 2)) / 2 + 1 : (ly + bot) / 2 + 2;
        ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x + padX + 3, ly, 3, 0, TAU); ctx.fill();
        // the scheme's name shrinks a little before it is ever cut ("CM Elevate Legacy" on a small tile)
        const lfs = fitSize(ctx, it.label, inner - 12, ls, 700, 9);
        label(ctx, fitText(ctx, it.label, inner - 12, lfs, 700), x + padX + 12, ly, { size: lfs, weight: 700, color: T.ink2, align: 'left' });
        const real = it.on && isNum(it.value);
        const [num, word] = it.on ? splitUnit(valueText(card, it, p)) : ['—', ''];
        const nfs = real || !it.on ? vfs : Math.min(vfs, 18);
        label(ctx, num, x + padX, vy, { size: nfs, weight: 800, color: real ? T.ink : T.mute, align: 'left' });
        if (word && real) label(ctx, word, x + padX + textW(ctx, num, nfs, 800) + 5, vy + nfs * .18, { size: ws, weight: 700, color: T.mute, align: 'left' });
        if (subH) {
          const lines = wrapText(ctx, it.sub, inner, ss, 600, subLines);
          const sy = bot - lines.length * sl + sl / 2;   // one line sits where the second would end: the tile stays balanced
          lines.forEach((l, k) => label(ctx, l, x + padX, sy + sl * k, { size: ss, weight: 600, color: T.mute, align: 'left' }));
        }
      });
    },
    tip(ctx) { return card.itemTip(ctx); },
  };
}

function Kpi(card) {
  return {
    draw(ctx, now) {
      const { W, H } = card; const it = card.items[0];
      if (!it) return;
      const col = it.color || TONE[it.tone] || T.brand; const p = card.pOf(it, now);
      const fs = Math.max(28, Math.min(72, H * .3, W * .16)); const cy = H / 2 - (it.sub ? 14 : 6);
      const glow = ctx.createRadialGradient(W / 2, cy, 0, W / 2, cy, Math.min(W, H) * .55);
      glow.addColorStop(0, alpha(col, (.1 + .1 * card.spotOf(it.key, now)) * (it.on ? p : .3))); glow.addColorStop(1, alpha(col, 0)); ctx.fillStyle = glow; ctx.fillRect(0, 0, W, H);
      const vt = it.on ? valueText(card, it, p) : '—'; const real = it.on && isNum(it.value);
      ctx.save(); if (real) { ctx.shadowColor = alpha(col, .25); ctx.shadowBlur = 24; ctx.shadowOffsetY = 8; }
      const vfs = fitSize(ctx, vt, W - 28, real ? fs : fs * .5, 800, 14);
      label(ctx, vt, W / 2, cy, { size: vfs, weight: 800, color: real ? T.ink : T.mute }); ctx.restore();
      const by = cy + vfs * .62 + 8;
      const bw = 56 * (it.on ? p : 0); rrect(ctx, W / 2 - 28, by, 56, 4, 2); ctx.fillStyle = alpha(col, .14); ctx.fill();
      if (bw > 1) { rrect(ctx, W / 2 - 28, by, bw, 4, 2); ctx.fillStyle = col; ctx.fill(); }
      label(ctx, fitText(ctx, it.label, W - 24, 13.5, 700), W / 2, by + 20, { size: 13.5, weight: 700, color: T.ink2 });
      if (it.sub) label(ctx, fitText(ctx, it.sub, W - 24, 11.5, 600), W / 2, by + 39, { size: 11.5, color: T.mute });
      card.hits = [{ key: it.key, x: 0, y: 0, w: W, h: H }];
    },
    tip() {},
  };
}

// the answer as a table (2026-11-11, the voice's "show it as a table"): a header of column titles, a row per answer row
// (its label, then each column's figure exactly as formatted by the planner), an inline bar behind the first figure
// column; rows glide in as they are revealed, the row being named is lit, the hovered row is lit
function Table(card) {
  return {
    draw(ctx, now) {
      const { W, H, items } = card; const n = items.length;
      const cols = card.columns.length ? card.columns : [{ title: '' }, { title: '' }];
      const nv = Math.max(1, cols.length - 1);
      const headH = 26; const rowH = Math.max(20, Math.min(38, (H - headH - 4) / Math.max(1, n)));
      const fs = rowH < 26 ? 11 : 12.5;
      const headOf = (j) => { const c = cols[j + 1] || {}; return String(c.title || '').toUpperCase() + (c.unit ? ` · ${c.unit}` : ''); };
      const cellW = (j) => Math.max(textW(ctx, headOf(j), 10, 800) + 6,
        ...items.map((it) => textW(ctx, (it.cells || [])[j] || '', fs, 800))) + 18;
      const widths = Array.from({ length: nv }, (_, j) => Math.min((W - 120) / nv, W * .34, cellW(j)));
      const valsW = widths.reduce((a, b) => a + b, 0);
      const lw = Math.max(60, W - valsW - 12);
      const xs = []; let x = lw; widths.forEach((w) => { x += w; xs.push(x); });   // right edges of the figure columns
      // the header
      ctx.save(); ctx.fillStyle = T.faint; rrect(ctx, 0, 0, W, headH - 4, 9); ctx.fill(); ctx.restore();
      label(ctx, fitText(ctx, String(cols[0].title || '').toUpperCase(), lw - 18, 10, 800), 12, (headH - 4) / 2, { size: 10, weight: 800, color: T.mute, align: 'left' });
      widths.forEach((w, j) => {
        label(ctx, fitText(ctx, headOf(j), w - 10, 10, 800), xs[j] - 8, (headH - 4) / 2, { size: 10, weight: 800, color: T.mute, align: 'right' });
      });
      const max = Math.max(1e-9, ...items.filter((i) => isNum(i.value)).map((i) => Math.abs(i.value)));
      card.hits = [];
      items.forEach((it, i) => {
        const y = headH + rowH * i; const cy = y + rowH / 2; const p = card.pOf(it, now);
        const sp = card.spotOf(it.key, now); const hot = card.hoverKey === it.key; const col = colorOf(it, i);
        card.hits.push({ key: it.key, x: 0, y, w: W, h: rowH });
        if (i % 2 === 1) { ctx.fillStyle = 'rgba(92,45,145,.025)'; ctx.fillRect(0, y, W, rowH); }
        if (hot || sp > .01) { rrect(ctx, 1, y + 1, W - 2, rowH - 2, 8); ctx.fillStyle = `rgba(124,63,191,${(hot ? .06 : .09 * sp).toFixed(3)})`; ctx.fill(); }
        ctx.save(); ctx.globalAlpha = it.on ? Math.min(1, .25 + p * 1.6) : .3;
        const shift = it.on ? (1 - Math.min(1, p * 1.4)) * 14 : 14;
        // the inline bar behind the first figure column: how big this row is beside the others
        if (it.on && isNum(it.value) && nv >= 1) {
          const bw = (widths[0] - 12) * Math.abs(it.value) / max * Math.min(1, p * 1.2);
          rrect(ctx, xs[0] - 6 - bw, cy + fs * .55, bw, 3, 1.5); ctx.fillStyle = alpha(col, .55); ctx.fill();
        }
        ctx.fillStyle = col; ctx.beginPath(); ctx.arc(14 + shift, cy, 3.4, 0, TAU); ctx.fill();
        label(ctx, fitText(ctx, it.label, lw - 34, fs, hot || sp > .3 ? 800 : 650), 26 + shift, cy, { size: fs, weight: hot || sp > .3 ? 800 : 650, color: T.ink, align: 'left' });
        widths.forEach((w, j) => {
          const t = it.on ? String((it.cells || [])[j] ?? '') : '';
          if (!t) return;
          const dash = t === '—';
          label(ctx, t, xs[j] - 8 + shift * .4, cy, { size: fitSize(ctx, t, w - 10, fs, 800, 8), weight: 800, color: dash ? T.mute : (j === 0 ? T.ink : T.ink2), align: 'right' });
        });
        ctx.restore();
        ctx.fillStyle = T.grid; ctx.fillRect(8, y + rowH - .5, W - 16, 1);
      });
    },
    tip(ctx) { return card.itemTip(ctx); },
  };
}

// ------------------------------------------------------------------ the district map
function worldBox(w, dists) {
  let b = null;
  if (Array.isArray(w) && w.length >= 4) b = { x: +w[0], y: +w[1], w: +w[2], h: +w[3] };
  else if (Array.isArray(w) && w.length === 2) b = { x: 0, y: 0, w: +w[0], h: +w[1] };
  else if (w && typeof w === 'object') b = { x: +(w.x ?? w.minX ?? 0), y: +(w.y ?? w.minY ?? 0), w: +(w.w ?? w.width), h: +(w.h ?? w.height) };
  else if (typeof w === 'string') { const q = w.trim().split(' ').join(',').split(',').filter((s) => s.length).map(Number); if (q.length >= 4) b = { x: q[0], y: q[1], w: q[2], h: q[3] }; }
  if (b && b.w > 0 && b.h > 0) return b;
  if (!dists.length) return { x: 0, y: 0, w: 1000, h: 600 };
  const r = (d) => Math.sqrt(Math.max(0, d.area || 0) / Math.PI) * 1.6;
  const x0 = Math.min(...dists.map((d) => d.cx - r(d))); const x1 = Math.max(...dists.map((d) => d.cx + r(d)));
  const y0 = Math.min(...dists.map((d) => d.cy - r(d))); const y1 = Math.max(...dists.map((d) => d.cy + r(d)));
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}
let HIT_CTX = null;
function hitCtx() { if (!HIT_CTX) { try { HIT_CTX = document.createElement('canvas').getContext('2d'); } catch (e) { HIT_CTX = null; } } return HIT_CTX; }

function MapR(card) {
  const list = Array.isArray(MEGH_DISTRICTS) ? MEGH_DISTRICTS : [];
  const D = [];
  for (const d of list) { try { D.push({ ...d, p2: new Path2D(d.d) }); } catch (e) { /* no Path2D */ } }
  D.sort((a, b) => a.cy - b.cy);                                   // north first, so the south's rise overlaps correctly
  const world = worldBox(MEGH_WORLD, D);
  const outline = [];
  for (const o of (Array.isArray(MEGH_OUTLINE) ? MEGH_OUTLINE : MEGH_OUTLINE ? [MEGH_OUTLINE] : [])) { try { outline.push(new Path2D(typeof o === 'string' ? o : o.d)); } catch (e) { /* skip */ } }
  const byKey = new Map(D.map((d) => [d.key, d]));
  const itemOf = new Map(card.items.map((it) => [it.key, it]));
  const leader = card.spec.mapMode === 'leader'; const leaders = card.spec.leaders || {};
  const ranked = card.items.filter((it) => isNum(it.value)).sort((a, b) => b.value - a.value);
  const rankOf = new Map(ranked.map((it, i) => [it.key, i + 1]));
  const vals = ranked.map((it) => it.value); const vmin = vals.length ? Math.min(...vals) : 0; const vmax = vals.length ? Math.max(...vals) : 1;
  const tOf = (v) => (vmax > vmin ? (v - vmin) / (vmax - vmin) : .7);
  const pulseKey = card.highlight && byKey.has(card.highlight) ? card.highlight : (ranked.find((it) => byKey.has(it.key)) || {}).key;
  const nameOf = (k) => (byKey.get(k) || {}).name || (itemOf.get(k) || {}).label || k;
  const shortOf = (k) => (byKey.get(k) || {}).short || nameOf(k);
  const fillOf = (k, it) => {
    if (leader) return (leaders[k] || {}).color || T.brand;
    return isNum(it.value) ? rampColor(.12 + .88 * tOf(it.value)) : null;
  };
  const legendLeaders = () => {
    const seen = new Map();
    for (const it of card.items) { const l = leaders[it.key]; if (l && l.label && !seen.has(l.label)) seen.set(l.label, l.color || T.brand); }
    return [...seen.entries()];
  };
  const M = { hovT: 0, prevHover: null, view: null, layout: null, pulse0: 0 };
  card.mapM = M;
  function layout(ctx, W, H) {
    const wide = W >= 640;
    const nrowsAll = Math.min(5, ranked.length || (leader ? card.items.length : 0));
    if (wide) { const pw = Math.min(260, Math.max(210, W * .3)); return { wide, map: { x: 0, y: 0, w: W - pw - 14, h: H }, panel: { x: W - pw, y: 4, w: pw - 4, h: H - 8 }, nrows: nrowsAll, cols: 1 }; }
    const cols = W >= 340 ? 2 : 1; let nrows = nrowsAll;
    const legH = leader ? 18 * Math.ceil(legendLeaders().length / (cols === 2 ? 3 : 2)) + 6 : 26;
    const listH = (n) => 22 + Math.ceil(n / cols) * 22 + legH;
    while (nrows > 2 && H - listH(nrows) < 130) nrows--;
    const lh = listH(nrows);
    // the map is as tall as the state needs at this width; map and list sit together in the middle
    const mh = Math.min(H - lh, world.h * ((W - 24) / world.w) + 40); const top = Math.max(0, (H - lh - mh) / 2);
    return { wide, map: { x: 0, y: top, w: W, h: mh }, panel: { x: 6, y: top + mh + 4, w: W - 12, h: lh - 6 }, nrows, cols };
  }
  return {
    draw(ctx, now, cam) {
      const { W, H } = card;
      if (!D.length) { label(ctx, 'map data not loaded', W / 2, H / 2, { color: T.mute }); return; }
      const Lo = layout(ctx, W, H); M.layout = Lo; const mb = Lo.map;
      const sc = Math.max(1e-6, Math.min((mb.w - 24) / world.w, (mb.h - 34) / world.h));
      const ox = mb.x + (mb.w - world.w * sc) / 2 - world.x * sc + (card.reduced ? 0 : cam.x * 6);
      const oy = mb.y + (mb.h - world.h * sc) / 2 - world.y * sc + 10 + (card.reduced ? 0 : cam.y * 4);
      M.view = { ox, oy, sc };
      const hovA = card.reduced ? 1 : ease((now - M.hovT) / 260);
      const hovOf = (k) => (k === card.hoverKey ? hovA : k === M.prevHover ? 1 - hovA : 0);
      // the state floats: a soft shadow under it
      ctx.save(); ctx.translate(ox, oy); ctx.scale(sc, sc);
      ctx.save(); ctx.shadowColor = 'rgba(74,35,128,.22)'; ctx.shadowBlur = 26; ctx.shadowOffsetY = 12; ctx.fillStyle = T.land;
      if (outline.length) outline.forEach((o) => ctx.fill(o)); else D.forEach((d) => ctx.fill(d.p2));
      ctx.restore();
      const rises = new Map();
      for (const d of D) {
        const it = itemOf.get(d.key); const p = it && it.on ? card.pOf(it, now) : 0; const hv = hovOf(d.key);
        const col = it ? fillOf(d.key, it) : null;
        const tv = it && isNum(it.value) ? tOf(it.value) : 0;
        const sp = it && it.on ? card.spotOf(d.key, now) : 0;
        const rise = (it ? (leader ? 6 + (isNum(it.value) ? 8 * tv : 0) : isNum(it.value) ? 4 + 13 * tv : 2) : 0) * p + hv * 4 + sp * 5;
        rises.set(d.key, rise);
        if (rise > .3) { ctx.save(); ctx.fillStyle = mix(col || T.land, col ? -.24 : -.1); ctx.globalAlpha = Math.min(1, p * 1.6 + hv); ctx.fill(d.p2); ctx.restore(); }
        ctx.save(); ctx.translate(0, -rise / sc);
        ctx.fillStyle = T.land; ctx.fill(d.p2);
        if (it && it.on) {
          ctx.globalAlpha = Math.min(1, p * 1.2);
          if (col) { ctx.fillStyle = col; ctx.fill(d.p2); } else {
            ctx.fillStyle = T.nodata; ctx.fill(d.p2);
            const hp = hatch(card); if (hp) { if (hp.setTransform && typeof DOMMatrix !== 'undefined') hp.setTransform(new DOMMatrix().scale(1 / sc)); ctx.fillStyle = hp; ctx.fill(d.p2); }
          }
          ctx.globalAlpha = 1;
        }
        if (hv > .02) { ctx.fillStyle = `rgba(255,255,255,${.22 * hv})`; ctx.fill(d.p2); }
        if (sp > .02) {   // the district being named: its edge lights up
          ctx.save(); ctx.shadowColor = alpha(col || T.brand, .55 * sp); ctx.shadowBlur = 16 * sp;
          ctx.strokeStyle = alpha(mix(col || T.brand, -.38), .9 * sp); ctx.lineWidth = (1.4 + 1.6 * sp) / sc; ctx.lineJoin = 'round'; ctx.stroke(d.p2); ctx.restore();
        } else { ctx.strokeStyle = hv > .3 ? T.deep : '#ffffff'; ctx.lineWidth = (hv > .3 ? 2 : 1.3) / sc; ctx.lineJoin = 'round'; ctx.stroke(d.p2); }
        ctx.restore();
      }
      // a ring opens from each district as the voice names it
      for (const d of D) {
        const ra = card.ringOf(d.key, now); if (ra < 0) continue;
        const it = itemOf.get(d.key); const col = (it && fillOf(d.key, it)) || T.brand; const k = ra / SPOT.ring;
        ctx.beginPath(); ctx.arc(d.cx, d.cy - (rises.get(d.key) || 0) / sc, (8 + 36 * ease(k)) / sc, 0, TAU);
        ctx.strokeStyle = alpha(mix(col, -.2), .75 * (1 - k)); ctx.lineWidth = 2.2 / sc; ctx.stroke();
      }
      // the leader breathes: a few rings once it has risen, then it rests (no endless redraw)
      const pk = pulseKey && byKey.get(pulseKey); const pit = pulseKey && itemOf.get(pulseKey);
      if (pk && pit && pit.on) {
        const col = fillOf(pulseKey, pit) || T.brand; const ry = pk.cy - (rises.get(pulseKey) || 0) / sc;
        if (card.reduced) { ctx.beginPath(); ctx.arc(pk.cx, ry, 16 / sc, 0, TAU); ctx.strokeStyle = alpha(mix(col, -.2), .6); ctx.lineWidth = 2 / sc; ctx.stroke(); } else {
          const t0 = pit.t0 + GROW.map; if (!M.pulse0 && now > t0) { M.pulse0 = now; card.busy(now + 3 * 1600 + 50); }
          if (M.pulse0 && now - M.pulse0 < 3 * 1600) {
            const ph = ((now - M.pulse0) / 1600) % 1;
            ctx.beginPath(); ctx.arc(pk.cx, ry, (10 + ph * 40) / sc, 0, TAU); ctx.strokeStyle = alpha(mix(col, -.15), .75 * (1 - ph)); ctx.lineWidth = 2.2 / sc; ctx.stroke();
          }
        }
      }
      ctx.restore();
      // labels: the top districts (fewer on a small map), never on top of each other
      const placed = []; const nLab = Lo.wide ? 5 : 3;
      const put = (ax, ay, text, col) => {
        const w = textW(ctx, text, 11, 800) + 22; const h = 22;
        const spots = [[0, -20], [0, 22], [w / 2 + 10, -6], [-(w / 2 + 10), -6], [0, -46], [0, 48], [w / 2 + 10, -32], [-(w / 2 + 10), -32], [w / 2 + 10, 22], [-(w / 2 + 10), 22], [0, -72]];
        const fitIn = (x, y) => [Math.max(mb.x + w / 2 + 2, Math.min(mb.x + mb.w - w / 2 - 2, x)), Math.max(mb.y + h / 2 + 2, Math.min(mb.y + mb.h - h / 2 - 2, y))];
        const free = (x, y) => !placed.some((q) => Math.abs(q.x - x) < (q.w + w) / 2 + 4 && Math.abs(q.y - y) < (q.h + h) / 2 + 3);
        let x; let y; let ok = false;
        for (const [dx, dy] of spots) { [x, y] = fitIn(ax + dx, ay + dy); if (free(x, y)) { ok = true; break; } }
        if (!ok) [x, y] = fitIn(ax, ay - 20);
        placed.push({ x, y, w, h });
        const ex = Math.max(x - w / 2, Math.min(x + w / 2, ax)); const ey = Math.max(y - h / 2, Math.min(y + h / 2, ay));
        if (Math.hypot(ex - ax, ey - ay) > 5) { ctx.strokeStyle = 'rgba(74,35,128,.45)'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(ex, ey); ctx.stroke(); }
        ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(ax, ay, 3.6, 0, TAU); ctx.fill(); ctx.fillStyle = T.deep; ctx.beginPath(); ctx.arc(ax, ay, 2, 0, TAU); ctx.fill();
        ctx.save(); ctx.shadowColor = 'rgba(40,20,70,.16)'; ctx.shadowBlur = 10; ctx.shadowOffsetY = 3;
        rrect(ctx, x - w / 2, y - h / 2, w, h, 11); ctx.fillStyle = 'rgba(255,255,255,.96)'; ctx.fill(); ctx.restore();
        ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x - w / 2 + 10, y, 3.4, 0, TAU); ctx.fill();
        label(ctx, text, x + 5, y + .5, { size: 11, weight: 800, color: T.ink });
      };
      const labelled = (ranked.length ? ranked : card.items).filter((it) => byKey.has(it.key) && it.on && card.pOf(it, now) > .35).slice(0, nLab);
      // the district being named is labelled too, even outside the top few
      const named = card.items.find((it) => byKey.has(it.key) && it.on && !labelled.includes(it) && card.spotOf(it.key, now) > .3);
      if (named) labelled.push(named);
      labelled.forEach((it) => {
        const d = byKey.get(it.key); const col = fillOf(it.key, it) || T.mute;
        const txt = isNum(it.value) ? `${shortOf(it.key)}  ${say(card, grow(it.value, card.pOf(it, now)))}` : leader && leaders[it.key] ? `${shortOf(it.key)} · ${leaders[it.key].label}` : shortOf(it.key);
        put(ox + d.cx * sc, oy + d.cy * sc - (rises.get(it.key) || 0), txt, col);
      });
      this.panel(ctx, now, Lo);
    },
    panel(ctx, now, Lo) {
      const P = Lo.panel; const wide = Lo.wide; card.hits = [];
      if (wide) {
        ctx.save(); ctx.shadowColor = 'rgba(74,35,128,.10)'; ctx.shadowBlur = 24; ctx.shadowOffsetY = 8;
        rrect(ctx, P.x, P.y, P.w, P.h, 16); ctx.fillStyle = 'rgba(255,255,255,.94)'; ctx.fill(); ctx.restore();
        rrect(ctx, P.x + .5, P.y + .5, P.w - 1, P.h - 1, 16); ctx.strokeStyle = T.border; ctx.stroke();
      }
      const px = P.x + (wide ? 16 : 4); const pw = P.w - (wide ? 32 : 8); let y = P.y + (wide ? 22 : 8);
      const rows = (ranked.length ? ranked : card.items).filter((it) => byKey.has(it.key) || itemOf.has(it.key)).slice(0, Lo.nrows);
      label(ctx, ranked.length ? (rows.length < ranked.length ? `Top ${rows.length} of ${ranked.length}` : 'Ranked') : 'Districts', px, y, { size: 10, weight: 800, color: T.mute, align: 'left' });
      if (card.unit) label(ctx, fitText(ctx, card.unit, pw * .55, 10, 700), px + pw, y, { size: 10, weight: 700, color: T.mute, align: 'right' });
      y += wide ? 22 : 16;
      const cw = pw / Lo.cols; const rh = wide ? Math.min(40, Math.max(30, (P.h - 120) / Math.max(1, rows.length))) : 22;
      rows.forEach((it, i) => {
        const c = i % Lo.cols; const r = Math.floor(i / Lo.cols); const x = px + c * cw; const ry = y + r * rh;
        const on = it.on; const p = on ? card.pOf(it, now) : 0; const col = fillOf(it.key, it) || T.mute; const em = card.hoverKey === it.key;
        const sp = on ? card.spotOf(it.key, now) : 0;
        card.hits.push({ key: it.key, x: x - 4, y: ry - rh / 2, w: cw, h: rh });
        if (em || sp > .01) { rrect(ctx, x - 6, ry - 11, cw - 4, wide ? rh - 6 : 21, 7); ctx.fillStyle = `rgba(124,63,191,${(em ? .07 : .09 * sp).toFixed(3)})`; ctx.fill(); }
        ctx.globalAlpha = on ? Math.min(1, .25 + p) : .35;
        label(ctx, String(rankOf.get(it.key) || i + 1), x + 5, ry, { size: 10, weight: 800, color: T.mute });
        if (!wide) { ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x + 18, ry, 3.5, 0, TAU); ctx.fill(); }
        const nx = x + (wide ? 16 : 26);
        const vt = on ? (isNum(it.value) ? say(card, grow(it.value, p)) : leader && leaders[it.key] ? leaders[it.key].label : 'no data') : '';
        const vw = Math.min(cw * .5, textW(ctx, vt, 11.5, 800));
        label(ctx, fitText(ctx, wide ? nameOf(it.key) : shortOf(it.key), x + cw - 16 - vw - nx, 11.5, 700), nx, ry, { size: 11.5, weight: 700, color: T.ink, align: 'left' });
        if (vt) label(ctx, fitText(ctx, vt, cw * .5, 11.5, 800), x + cw - 10, ry, { size: 11.5, weight: 800, color: isNum(it.value) ? T.ink : T.mute, align: 'right' });
        if (wide) {
          const bw = pw - 16; rrect(ctx, x + 16, ry + 10, bw, 4, 2); ctx.fillStyle = T.faint; ctx.fill();
          const f = isNum(it.value) && vmax > 0 ? Math.max(.04, it.value / vmax) : 0;
          if (f && on) { rrect(ctx, x + 16, ry + 10, Math.max(4, bw * f * p), 4, 2); ctx.fillStyle = col; ctx.fill(); }
        }
        ctx.globalAlpha = 1;
      });
      // the legend: the ramp with its ends, or the leaders
      let ly = wide ? P.y + P.h - (leader ? 14 + 18 * Math.ceil(legendLeaders().length / 2) : 34) : y + Math.ceil(rows.length / Lo.cols) * rh + 4;
      if (!leader) {
        if (vals.length) {
          const a = say(card, vmin); const b = say(card, vmax); const aw = textW(ctx, a, 10, 700); const bw2 = textW(ctx, b, 10, 700);
          const gx = px + aw + 8; const gw = Math.max(30, pw - aw - bw2 - 16 - (ranked.length < card.items.length ? 64 : 0));
          const g = ctx.createLinearGradient(gx, 0, gx + gw, 0); [0, .25, .5, .75, 1].forEach((t) => g.addColorStop(t, rampColor(.12 + .88 * t)));
          label(ctx, a, px, ly + 4, { size: 10, weight: 700, color: T.mute, align: 'left' });
          rrect(ctx, gx, ly, gw, 8, 4); ctx.fillStyle = g; ctx.fill();
          label(ctx, b, gx + gw + 6, ly + 4, { size: 10, weight: 700, color: T.mute, align: 'left' });
          if (ranked.length < card.items.length) {
            const nx = gx + gw + 6 + bw2 + 12; noData(ctx, card, nx, ly - 1, 12, 10, 3);
            label(ctx, 'no data', nx + 16, ly + 4, { size: 10, weight: 700, color: T.mute, align: 'left' });
          }
        }
      } else {
        const L = legendLeaders(); const per = wide ? 2 : Lo.cols === 2 ? 3 : 2; const cwl = pw / per;
        L.forEach(([name, col], i) => {
          const x = px + (i % per) * cwl; const yy = ly + Math.floor(i / per) * 18 + 4;
          ctx.fillStyle = col; rrect(ctx, x, yy - 5, 10, 10, 3); ctx.fill();
          label(ctx, fitText(ctx, name, cwl - 20, 10.5, 700), x + 15, yy, { size: 10.5, weight: 700, color: T.ink2, align: 'left' });
        });
      }
    },
    hit(x, y) {
      for (const h of card.hits || []) if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h.key;
      const v = M.view; const hc = hitCtx(); if (!v || !hc) return null;
      const wx = (x - v.ox) / v.sc; const wy = (y - v.oy) / v.sc;
      for (let i = D.length - 1; i >= 0; i--) if (hc.isPointInPath(D[i].p2, wx, wy)) return D[i].key;
      return null;
    },
    hover(k, now) { M.prevHover = card.hoverKey; M.hovT = now; },
    tip(ctx) {
      const k = card.hoverKey; if (!k || !card.ptr) return;
      const it = itemOf.get(k); const rows = [];
      if (!it) rows.push({ label: 'Not in this answer', value: '', muted: true });
      else if (!it.on) rows.push({ label: 'Not shown yet', value: '', muted: true });
      else {
        if (leader && leaders[k]) rows.push({ color: leaders[k].color || T.brand, label: 'Leads', value: leaders[k].label });
        if (isNum(it.value) || !leader) rows.push({ color: fillOf(k, it) || T.mute, label: card.unit || 'Value', value: isNum(it.value) ? say(card, it.value) : 'no data', muted: !isNum(it.value) });
        if (it.sub) rows.push({ label: it.sub, value: '' });
      }
      const r = it && it.on ? rankOf.get(k) : 0;
      drawTip(ctx, card, card.ptr.x, card.ptr.y, nameOf(k), rows, r ? `#${r} of ${ranked.length}` : '');
    },
  };
}

const RENDER = { bars: Bars, race: Race, line: Line, donut: Donut, tiles: Tiles, kpi: Kpi, map: MapR, table: Table };

// ------------------------------------------------------------------ the factory
export function createStageCard(canvas, spec, opts = {}) {
  const kind = RENDER[spec && spec.kind] ? spec.kind : 'bars';
  const reduced = !!opts.reduced;
  const ctx = canvas.getContext('2d');
  const fmt = typeof spec.fmt === 'function' ? spec.fmt : (v) => String(v);
  const mkItem = (it) => ({ key: String(it.key ?? it.label ?? ''), label: String(it.label ?? it.key ?? ''), value: isNum(it.value) ? it.value : null,
    color: it.color || '', sub: it.sub || '', note: it.note || '', tone: it.tone || '', on: reduced, t0: 0,
    fmt: typeof it.fmt === 'function' ? it.fmt : null,
    cells: Array.isArray(it.cells) ? it.cells.map((c) => String(c ?? '')) : null });
  const card = {
    kind, spec, canvas, ctx, fmt, reduced, unit: spec.unit || '', total: spec.total, highlight: spec.highlight ?? null,
    W: 10, H: 10, dpr: 1, dirty: true, busyUntil: 0, hits: [], timers: [], hoverKey: null, hoverIdx: null, ptr: null, destroyed: false,
  };
  if (kind === 'line') {
    card.x = (spec.x || []).map((t) => String(t));
    card.series = (spec.series || []).slice(0, 6).map((s, i) => ({ key: String(s.key ?? s.name ?? i), name: String(s.name ?? s.key ?? ''), color: s.color || CATEGORICAL[i % CATEGORICAL.length],
      values: card.x.map((_, j) => (isNum((s.values || [])[j]) ? s.values[j] : null)) }));
    card.items = card.x.map((t) => mkItem({ key: t, label: t, value: 0 }));
    card.line = { head: reduced ? card.x.length - 1 : -1, target: reduced ? card.x.length - 1 : -1 };
  } else {
    let items = (spec.items || []).map(mkItem);
    if (kind === 'kpi') items = items.slice(0, 1);
    if (kind === 'tiles') items = items.slice(0, TILE_MAX);
    if (kind === 'table') items = items.slice(0, 12);
    card.items = items;
    card.columns = Array.isArray(spec.columns) ? spec.columns : [];
  }
  // the unit word over a bar chart / ranking ("crore"): only when the figures do not say it themselves ("₹3,628.67 crore")
  card.unitWord = card.unit && !(card.items || []).some((it) => isNum(it.value) && say(card, it.value).includes(card.unit)) ? card.unit : '';
  card.pOf = (it, now) => (!it.on ? 0 : reduced ? 1 : ease(((now ?? now_()) - it.t0) / (GROW[kind] || 1500)));
  // the spotlight: 0..1 for the item being named now (see SPOT); the ring's age in ms, or -1
  card.spots = [];
  card.spotOf = (key, now) => {
    if (reduced) return 0;
    for (let i = card.spots.length - 1; i >= 0; i--) {
      const s = card.spots[i]; if (s.key !== key) continue;
      const age = now - s.t; if (age < 0) return 0;
      let a = Math.min(1, age / SPOT.attack);
      if (age > SPOT.hold) a *= Math.max(0, 1 - (age - SPOT.hold) / SPOT.fade);
      const nx = card.spots[i + 1]; if (nx) a *= Math.max(0, 1 - (now - nx.t) / SPOT.handoff);
      return a;
    }
    return 0;
  };
  card.ringOf = (key, now) => {
    if (reduced) return -1;
    const s = card.spots.find((q) => q.key === key); const age = s ? now - s.t : -1;
    return age >= 0 && age < SPOT.ring ? age : -1;
  };
  card.busy = (until) => { if (until > card.busyUntil) card.busyUntil = until; };
  card.itemTip = (c2) => {
    const it = card.items.find((q) => q.key === card.hoverKey); if (!it || !it.on || !card.ptr) return;
    const i = card.items.indexOf(it);
    if (kind === 'table') {     // a row of the table: each column's figure as shown
      drawTip(c2, card, card.ptr.x, card.ptr.y, it.label, card.columns.slice(1).map((c, j) => ({ label: c.title + (c.unit ? ` (${c.unit})` : ''),
        value: (it.cells || [])[j] || '—', muted: (it.cells || [])[j] === '—' })));
      return;
    }
    const rows = [{ color: kind === 'tiles' || kind === 'kpi' ? (it.color || TONE[it.tone] || T.brand) : colorOf(it, i), label: card.unit || 'Value', value: isNum(it.value) ? sayItem(card, it, it.value) : 'no data', muted: !isNum(it.value) }];
    if (it.note || it.sub) rows.push({ label: it.note || it.sub, value: '' });
    drawTip(c2, card, card.ptr.x, card.ptr.y, it.label, rows);
  };
  card.r = RENDER[kind](card);
  card.step = (now, dt) => {
    if (kind !== 'line') return;
    const L = card.line; if (L.head >= L.target) { L.head = L.target; return; }
    const n = Math.max(1, card.x.length - 1); const gap = L.target - L.head;
    const speed = (n + 1) / GROW.line * Math.max(.35, Math.min(1, gap * .9));   // a whole sweep in ~GROW.line, easing out at the end
    L.head = Math.min(L.target, L.head + dt * speed); if (L.target - L.head < .002) L.head = L.target;
  };
  card.moving = (now) => now < card.busyUntil || (kind === 'line' && card.line.head < card.line.target);
  card.paint = (now) => {
    const c = card.ctx; c.setTransform(card.dpr, 0, 0, card.dpr, 0, 0); c.clearRect(0, 0, card.W, card.H);
    const cam = reduced ? { x: 0, y: 0 } : CAM;
    try {
      if (!card.items.length && kind !== 'line') label(c, 'no data', card.W / 2, card.H / 2, { size: 12, weight: 700, color: T.mute });
      else if (kind === 'line' && !card.series.length) label(c, 'no data', card.W / 2, card.H / 2, { size: 12, weight: 700, color: T.mute });
      else { card.r.draw(c, now, cam); if (card.hoverKey !== null && card.r.tip) card.r.tip(c); }
    } catch (e) { if (typeof console !== 'undefined') console.error('stageCanvas draw', e); }
  };

  // sizing: the parent's content box, read by a ResizeObserver (never measured per frame)
  const apply = (w, h) => {
    w = Math.max(10, Math.round(w)); h = Math.round(h);
    if (h < 40) h = Math.max(200, Math.min(420, Math.round(w * .56)));
    const dpr = Math.min(2, (typeof window !== 'undefined' && window.devicePixelRatio) || 1);
    if (w === card.W && h === card.H && dpr === card.dpr) return;
    card.W = w; card.H = h; card.dpr = dpr;
    if (canvas.style) { canvas.style.display = 'block'; canvas.style.width = w + 'px'; canvas.style.height = h + 'px'; }
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    card.dirty = true; kick();
  };
  const measure = () => {
    const el = canvas.parentElement; if (!el) { apply(canvas.width || 300, canvas.height || 150); return; }
    let pl = 0; let pr = 0; let pt = 0; let pb = 0;
    try { const cs = getComputedStyle(el); pl = parseFloat(cs.paddingLeft) || 0; pr = parseFloat(cs.paddingRight) || 0; pt = parseFloat(cs.paddingTop) || 0; pb = parseFloat(cs.paddingBottom) || 0; } catch (e) { /* no styles */ }
    apply(el.clientWidth - pl - pr, el.clientHeight - pt - pb);
  };
  measure();
  if (typeof ResizeObserver !== 'undefined' && canvas.parentElement) {
    card.ro = new ResizeObserver((entries) => { const r = entries[0] && entries[0].contentRect; if (r) apply(r.width, r.height); else measure(); });
    card.ro.observe(canvas.parentElement);
  }

  // hover
  const setHover = (k) => {
    if (k === card.hoverKey) return;
    const now = now_();
    if (card.r.hover) card.r.hover(k, now);
    card.hoverKey = k; if (k === null) card.hoverIdx = null;
    card.busy(now + 320); card.dirty = true; kick();
    if (typeof opts.onHover === 'function') { try { opts.onHover(k); } catch (e) { /* the caller's */ } }
  };
  const hitTest = (x, y) => {
    if (card.r.hit) return card.r.hit(x, y);
    for (const h of card.hits) if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) { const it = card.items.find((q) => q.key === h.key); return it && it.on ? h.key : null; }
    return null;
  };
  const onMove = (e) => { card.ptr = { x: e.offsetX, y: e.offsetY }; const k = hitTest(card.ptr.x, card.ptr.y); if (k !== card.hoverKey) setHover(k); else if (k !== null) { card.dirty = true; kick(); } };
  const onLeave = () => { card.ptr = null; setHover(null); };
  if (canvas.addEventListener) { canvas.addEventListener('pointermove', onMove); canvas.addEventListener('pointerleave', onLeave); }

  LIVE.add(card);
  if (!reduced && !camOn && typeof window !== 'undefined' && window.addEventListener) { window.addEventListener('pointermove', onWinMove, { passive: true }); camOn = true; }
  hookFonts();
  kick();

  const revealIdx = (i, now) => {
    const it = card.items[i]; if (!it || it.on) return false;
    it.on = true; it.t0 = now; card.busy(now + (GROW[kind] || 1500) + (kind === 'bars' ? 1000 : 120));
    return true;
  };
  const revealOne = (key, spoken = false) => {
    if (card.destroyed || reduced) return false;
    const k = String(key); const i = card.items.findIndex((it) => it.key === k); if (i < 0) return false;
    const now = now_(); const was = !card.items[i].on;
    if (kind === 'line') {
      for (let j = 0; j <= i; j++) revealIdx(j, now);
      card.line.target = Math.max(card.line.target, i);
    } else revealIdx(i, now);
    // named by the voice: it is the one in the spotlight now
    if (spoken && was) { card.spots.push({ key: k, t: now }); if (card.spots.length > 24) card.spots.shift(); card.busy(now + SPOT.hold + SPOT.fade + 60); }
    card.dirty = true; kick();
    return was;
  };
  return {
    reveal: revealOne,
    revealAll(stagger = 260) {
      if (card.destroyed || reduced) return 0;
      const left = card.items.filter((it) => !it.on);
      const st = staggerFor(stagger, left.length);
      left.forEach((it, k) => { if (k === 0) revealOne(it.key); else card.timers.push(setTimeout(() => revealOne(it.key), k * st)); });
      return left.length;
    },
    state() {
      const now = now_();
      return {
        kind,
        items: card.items.map((it, i) => ({ key: it.key, on: it.on,
          p: +(kind === 'line' ? (it.on ? Math.max(0, Math.min(1, card.line.head - i + 1)) : 0) : card.pOf(it, now)).toFixed(3),
          shown: isNum(it.value) ? sayItem(card, it, it.value) : null })),   // the figure as the card draws it, grown
      };
    },
    resize() { measure(); card.dirty = true; kick(); },
    destroy() {
      if (card.destroyed) return;
      card.destroyed = true; card.timers.forEach(clearTimeout); card.timers = [];
      if (card.ro) card.ro.disconnect();
      if (canvas.removeEventListener) { canvas.removeEventListener('pointermove', onMove); canvas.removeEventListener('pointerleave', onLeave); }
      LIVE.delete(card);
      if (!LIVE.size) {
        if (RAF && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(RAF);
        RAF = 0; LAST = 0;
        if (camOn && typeof window !== 'undefined') { window.removeEventListener('pointermove', onWinMove); camOn = false; }
      }
    },
  };
}
