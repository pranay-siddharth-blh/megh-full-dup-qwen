/* The live voice's orb (2026-11-02). Copied from Sakala Mitra's core
   (D:/Sakala POC/mitra/web/orb.js, read-only source): a 3D particle sphere
   (fibonacci lattice, perspective projection) that breathes when idle, swells
   with the officer's voice, swirls while the answer is being worked out and
   pulses with its own voice; a frequency halo is driven by the live microphone
   or the voice's audio. Touchable: hover and the particles lean towards the
   pointer; drag to spin it (with momentum); press and pull and it stretches like
   jelly and springs back; a tap calls onTap.

   Changes from Mitra: a factory over a given canvas (no page globals), always the
   light rendering (Megh One AI is light-only), and Megh's palette. Two analysers:
   the microphone while listening, the voice's output while speaking. */

// Megh's tokens (styles/chat.css): Mitra's palette mapped to purple (emerald -> purple, cyan -> lavender,
// orange accent -> soft magenta); amber kept for thinking (Mitra's orange state), inks for muted
const PAL = {
  idle:       [[149, 88, 207], [92, 45, 145]],      // --p-500, --p-700
  standby:    [[207, 168, 238], [178, 127, 224]],    // --p-300, --p-400
  connecting: [[178, 127, 224], [124, 63, 191]],
  listening:  [[178, 127, 224], [149, 88, 207]],     // Mitra cyan + emerald -> lavender --p-400, --p-500
  thinking:   [[154, 103, 0], [178, 127, 224]],      // --amber, --p-400
  speaking:   [[124, 63, 191], [213, 81, 129]],      // Mitra emerald + orange -> --p-600, soft magenta
  muted:      [[133, 126, 150], [83, 75, 104]],      // --ink-3, --ink-2
};
const BURST = [[124, 63, 191], [213, 81, 129]];

export function createOrb(cv, { onLevel } = {}) {
  const ctx = cv.getContext('2d');
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  let state = 'idle'; let level = 0; let smooth = 0; let an = null; let fbuf = null; const t0 = performance.now();
  let rotY = 0; let rotX = 0.35; let spin = 0.12; let wake = 0; let alive = true; let half = false; let skip = 0;
  const col = PAL.idle.map((c) => c.slice());
  const N = 1500; const pts = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2; const r = Math.sqrt(1 - y * y); const th = Math.PI * (3 - Math.sqrt(5)) * i;
    pts.push({ x: Math.cos(th) * r, y, z: Math.sin(th) * r, s: Math.random(), k: Math.random() * 6.28 });
  }
  const sparks = Array.from({ length: 60 }, () => ({ a: Math.random() * 6.28, r: 1.25 + Math.random() * 0.9, v: 0.1 + Math.random() * 0.4, y: (Math.random() - 0.5) * 0.8, s: Math.random() }));
  const bursts = [];

  // the canvas is sized from its layout box, once per change (never measured per frame). 2026-11-14: the LAYOUT size
  // (clientWidth / the observer's contentRect), not getBoundingClientRect: the parked orb is scaled down by a transform,
  // and a resize while parked sized the buffer to the small box, so the orb came back soft; whole device pixels
  const apply = (w, h) => {
    const W = Math.max(10, Math.round(w * dpr)); const H = Math.max(10, Math.round(h * dpr));
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  };
  const size = () => apply(cv.clientWidth, cv.clientHeight);
  const ro = typeof ResizeObserver !== 'undefined'
    ? new ResizeObserver((es) => { const r = es[0] && es[0].contentRect; if (r) apply(r.width, r.height); else size(); }) : null;
  if (ro) ro.observe(cv); else window.addEventListener('resize', size);
  size();

  const lerp = (a, b, k) => a + (b - a) * k;
  const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
  const deep = (c) => [c[0] * 0.86, c[1] * 0.86, c[2] * 0.86];       // on a light page the particles are inked, not lit
  const NB_A = 8; const batch = Array.from({ length: 2 * NB_A }, () => []);

  // ---- pointer: hover lean, drag-to-spin with momentum, pull-and-release spring, tap
  const P = { over: false, down: false, drag: false, x: 0, y: 0, lx: 0, ly: 0, dx: 0, dy: 0, vy: 0, vx: 0, t: 0,
    pullX: 0, pullY: 0, pvx: 0, pvy: 0, tx: 0, ty: 0, squash: 0, grab: 0 };
  let onTap = null;
  // the pointer in the canvas's own (untransformed) pixels: offsetX / offsetY need no layout read and stay right while
  // the orb is parked under a scale transform
  const pos = (e) => {
    if (typeof e.offsetX === 'number' && e.target === cv) { P.x = e.offsetX * dpr; P.y = e.offsetY * dpr; return; }
    const r = cv.getBoundingClientRect(); const sx = cv.clientWidth ? r.width / cv.clientWidth : 1; const sy = cv.clientHeight ? r.height / cv.clientHeight : 1;
    P.x = ((e.clientX - r.left) / (sx || 1)) * dpr; P.y = ((e.clientY - r.top) / (sy || 1)) * dpr;
  };
  const onEnter = (e) => { P.over = true; pos(e); };
  const onLeave = () => { P.over = false; if (!P.down) { P.tx = 0; P.ty = 0; } };
  const onDown = (e) => {
    e.preventDefault(); try { cv.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    pos(e); P.down = true; P.drag = false; P.lx = P.x; P.ly = P.y; P.t = performance.now(); P.vx = 0; P.vy = 0; P.dx = 0; P.dy = 0; P.grab = 1;
  };
  const onMove = (e) => {
    pos(e); if (!P.down) return;
    const mx = P.x - P.lx; const my = P.y - P.ly; P.lx = P.x; P.ly = P.y;
    P.dx += mx; P.dy += my;
    if (!P.drag && Math.hypot(P.dx, P.dy) > 6 * dpr) P.drag = true;
    if (P.drag) {
      const W = cv.width; const R = Math.min(W, cv.height) * 0.25;
      P.vy = lerp(P.vy, (mx / R) * 2.2, 0.5); P.vx = lerp(P.vx, (my / R) * 1.4, 0.5);
      rotY += P.vy / 6; rotX = Math.max(-1.2, Math.min(1.2, rotX + P.vx / 6));
      const cx = W / 2; const cy = cv.height / 2;
      P.tx = Math.max(-0.6, Math.min(0.6, ((P.x - cx) / R) * 0.32)); P.ty = Math.max(-0.6, Math.min(0.6, ((P.y - cy) / R) * 0.32));
    }
  };
  const release = (e) => {
    if (!P.down) return; P.down = false; P.grab = 0;
    try { cv.releasePointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    if (!P.drag && performance.now() - P.t < 450) { wake = Math.max(wake, 0.8); if (onTap) onTap(); }
    P.drag = false; P.tx = 0; P.ty = 0;
  };
  cv.addEventListener('pointerenter', onEnter); cv.addEventListener('pointerleave', onLeave);
  cv.addEventListener('pointerdown', onDown); cv.addEventListener('pointermove', onMove);
  cv.addEventListener('pointerup', release); cv.addEventListener('pointercancel', release);

  let lastLvl = -1; let cursor = '';
  function frame() {
    if (!alive) return;
    if (document.hidden || (half && !P.down && (skip ^= 1))) { requestAnimationFrame(frame); return; }   // parked: 30 fps
    const t = (performance.now() - t0) / 1000;
    const W = cv.width; const H = cv.height; const cx = W / 2; const cy = H / 2; const R = Math.min(W, H) * 0.25;
    let bands = null;
    if (an) {
      if (!fbuf || fbuf.length !== an.frequencyBinCount) fbuf = new Uint8Array(an.frequencyBinCount);
      an.getByteFrequencyData(fbuf); bands = fbuf;
      let s = 0; const top = Math.min(64, fbuf.length); for (let i = 2; i < top; i++) s += fbuf[i];
      level = Math.max(level * 0.9, (s / Math.max(1, top - 2) / 255) * 1.6);
    }
    smooth += (level - smooth) * (level > smooth ? 0.3 : 0.06);
    wake *= 0.94;
    const target = PAL[state] || PAL.idle;
    for (let j = 0; j < 2; j++) for (let k = 0; k < 3; k++) col[j][k] = lerp(col[j][k], target[j][k], 0.06);
    const spinT = state === 'thinking' ? 0.9 : state === 'speaking' ? 0.35 : state === 'listening' ? 0.22 : (state === 'muted' || state === 'standby') ? 0.04 : 0.1;
    spin = lerp(spin, spinT, 0.03);
    if (!P.drag) {
      rotY += spin / 60 + P.vy / 6; rotX = lerp(rotX, 0.35 + Math.sin(t * 0.3) * 0.12, 0.02) + P.vx / 6;
      P.vy *= 0.955; P.vx *= 0.955;
    }
    const kx = P.tx - P.pullX; const ky = P.ty - P.pullY;
    P.pvx = (P.pvx + kx * 0.16) * 0.78; P.pvy = (P.pvy + ky * 0.16) * 0.78;
    P.pullX += P.pvx; P.pullY += P.pvy;
    const pullLen = Math.hypot(P.pullX, P.pullY); const ux = pullLen > 1e-4 ? P.pullX / pullLen : 0; const uy = pullLen > 1e-4 ? P.pullY / pullLen : 0;
    P.squash = lerp(P.squash, P.grab * 0.08, 0.12);
    const hov = P.over && !P.down ? Math.max(0, 1 - Math.hypot(P.x - cx, P.y - cy) / (R * 1.6)) : 0;

    ctx.clearRect(0, 0, W, H);
    const gx = cx + P.pullX * R * 0.6; const gy = cy + P.pullY * R * 0.6;
    // the glow always fades to nothing inside the canvas: a radius past its edge drew a square box (user, 2026-11-02)
    const edge = Math.max(R * 1.2, Math.min(gx, gy, W - gx, H - gy) - 2);
    const gl = ctx.createRadialGradient(gx, gy, R * 0.2, gx, gy, Math.min(edge, R * (2.4 + smooth * 1.2 + wake + hov * 0.3)));
    gl.addColorStop(0, rgba(col[0], (0.3 + smooth * 0.3 + wake * 0.3 + hov * 0.08) * 0.5));
    gl.addColorStop(0.5, rgba(col[1], (0.08 + smooth * 0.08) * 0.5)); gl.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = gl; ctx.fillRect(0, 0, W, H);

    const amp = state === 'idle' || state === 'standby' ? 0.035 + Math.sin(t * 1.3) * 0.015 : state === 'thinking' ? 0.08 : 0.05 + smooth * 0.42;
    const sy = Math.sin(rotY); const cyy = Math.cos(rotY); const sx = Math.sin(rotX); const cxx = Math.cos(rotX);
    const f = 2.6; const hovR = R * 0.5;
    for (const b of batch) b.length = 0;
    for (const p of pts) {
      const n = Math.sin(p.x * 3.1 + t * 1.4 + p.k) * 0.5 + Math.sin(p.y * 4.3 - t * 1.1) * 0.3 + Math.sin(p.z * 5.7 + t * 2.3) * 0.2;
      let d = 1 + n * amp + (state === 'thinking' ? Math.sin(p.y * 10 + t * 6) * 0.025 : 0);
      if (bands && (state === 'speaking' || state === 'listening')) d += (bands[4 + ((p.s * 60) | 0)] / 255) * 0.22 * (0.5 + p.s);
      const x = p.x * d; const y = p.y * d; const z = p.z * d;
      const x1 = x * cyy - z * sy; const z1 = x * sy + z * cyy;
      let y1 = y * cxx - z1 * sx; const z2 = y * sx + z1 * cxx;
      let xx = x1;
      if (pullLen > 1e-3) {
        const side = xx * ux + y1 * uy; const w = 0.35 + (0.65 * (side + 1)) / 2;
        xx += P.pullX * w * 1.1; y1 += P.pullY * w * 1.1;
        const perp = -xx * uy + y1 * ux;
        xx -= -uy * perp * pullLen * 0.35; y1 -= ux * perp * pullLen * 0.35;
      }
      if (P.squash > 1e-3) { xx *= 1 + P.squash; y1 *= 1 - P.squash * 0.6; }
      const sc = f / (f + z2);
      let px = cx + xx * R * sc; let py = cy + y1 * R * sc;
      const depth = (1 - z2) / 2;
      let a = (0.1 + depth * 0.75) * (0.6 + smooth * 0.6); let lift = 0;
      if (hov > 0 && depth > 0.4) {
        const ddx = P.x - px; const ddy = P.y - py; const dd = Math.hypot(ddx, ddy);
        if (dd < hovR) { lift = (1 - dd / hovR) * hov; px += (ddx / (dd + 1)) * lift * R * 0.18; py += (ddy / (dd + 1)) * lift * R * 0.18; a += lift * 0.5; }
      }
      const sz = (0.7 + depth * 1.9 + p.s * 0.6 + lift * 1.4) * dpr * 1.08;
      const al = Math.min(1, a * 1.05 + 0.05);
      batch[(depth > 0.55 ? 0 : NB_A) + Math.min(NB_A - 1, (al * NB_A) | 0)].push(px - sz / 2, py - sz / 2, sz);
    }
    for (let bi = 0; bi < batch.length; bi++) {
      const b = batch[bi]; if (!b.length) continue;
      ctx.fillStyle = rgba(deep(bi < NB_A ? col[0] : col[1]), ((bi % NB_A) + 0.5) / NB_A);
      ctx.beginPath();
      for (let i = 0; i < b.length; i += 3) ctx.rect(b[i], b[i + 1], b[i + 2], b[i + 2]);
      ctx.fill();
    }
    const ccx = cx + P.pullX * R * 0.9; const ccy = cy + P.pullY * R * 0.9;
    const core = ctx.createRadialGradient(ccx - R * 0.2, ccy - R * 0.25, 0, ccx, ccy, R * (0.95 + smooth * 0.25 + hov * 0.1));
    core.addColorStop(0, rgba(col[0], 0.1 + smooth * 0.16 + hov * 0.05)); core.addColorStop(0.35, rgba(col[0], (0.1 + smooth * 0.12) * 0.7)); core.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = core; ctx.beginPath(); ctx.arc(ccx, ccy, R * 1.25, 0, 6.29); ctx.fill();

    const NB = 120; const r0 = R * 1.42;
    for (let i = 0; i < NB; i++) {
      const ang = (i / NB) * 6.283 - 1.5708 + rotY * 0.15;
      let v = bands ? bands[3 + (((i < NB / 2 ? i : NB - i) * 1.2) | 0)] / 255 : 0;
      v = Math.max(v, (state === 'idle' || state === 'standby' ? 0.03 + (Math.sin(t * 2 + i * 0.3) + 1) * 0.015 : state === 'thinking' ? (Math.sin(t * 8 - i * 0.4) + 1) * 0.06 : 0.02));
      const len = R * (0.04 + v * 0.55);
      ctx.strokeStyle = rgba(deep(i % 2 ? col[0] : col[1]), 0.25 + v * 0.7); ctx.lineWidth = 1.6 * dpr;
      ctx.beginPath(); ctx.moveTo(cx + Math.cos(ang) * r0, cy + Math.sin(ang) * r0);
      ctx.lineTo(cx + Math.cos(ang) * (r0 + len), cy + Math.sin(ang) * (r0 + len)); ctx.stroke();
    }
    for (let k = 0; k < 3; k++) {
      ctx.strokeStyle = rgba(deep(col[k % 2]), 0.16 + (state === 'thinking' ? 0.2 : 0) + smooth * 0.1 + hov * 0.06); ctx.lineWidth = 1 * dpr;
      ctx.beginPath(); ctx.ellipse(cx, cy, R * (1.75 + k * 0.22), R * (0.42 + k * 0.1), rotY * (k % 2 ? -1 : 1) * 0.4 + k, 0, 6.29); ctx.stroke();
    }
    if (state === 'thinking') {
      for (let k = 0; k < 3; k++) {
        const a0 = t * (2 + k * 0.7) + k * 2.1;
        ctx.strokeStyle = rgba(deep(col[k % 2]), 0.85); ctx.lineWidth = 2.2 * dpr;
        ctx.beginPath(); ctx.arc(cx, cy, R * (1.3 + k * 0.06), a0, a0 + 1.1); ctx.stroke();
      }
    }
    for (const s of sparks) {
      s.a += (s.v * (state === 'thinking' ? 2.4 : 1)) / 60;
      const rr = R * s.r * (1 + smooth * 0.2); const x = cx + Math.cos(s.a) * rr; const y = cy + Math.sin(s.a) * rr * 0.45 + s.y * R;
      ctx.fillStyle = rgba(deep(col[s.s > 0.5 ? 0 : 1]), 0.35 + s.s * 0.4); ctx.fillRect(x, y, 1.6 * dpr, 1.6 * dpr);
    }
    for (let i = bursts.length - 1; i >= 0; i--) {
      const b = bursts[i]; b.life -= 0.016; if (b.life <= 0) { bursts.splice(i, 1); continue; }
      b.r += b.v; const x = cx + Math.cos(b.a) * b.r * R; const y = cy + Math.sin(b.a) * b.r * R * 0.7;
      ctx.fillStyle = rgba(b.c, b.life * 0.9); const z = (1 + b.life * 2) * dpr; ctx.fillRect(x, y, z, z);
    }
    if (wake > 0.02) { ctx.strokeStyle = rgba(deep(col[0]), wake * 0.7); ctx.lineWidth = 3 * dpr; ctx.beginPath(); ctx.arc(cx, cy, R * (1.1 + (1 - wake) * 1.3), 0, 6.29); ctx.stroke(); }

    if (onLevel && Math.abs(smooth - lastLvl) > 0.006) { lastLvl = smooth; onLevel(smooth); }   // only a visible change
    const cur = P.down ? 'grabbing' : hov > 0.05 ? 'grab' : 'pointer';
    if (cur !== cursor) { cursor = cur; cv.style.cursor = cur; }      // a style write only when it changes
    if (!an) level *= 0.92;
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  return {
    setState(s) { state = s; },
    setSource(analyser) { an = analyser || null; },
    setHalf(on) { half = !!on; },
    pulse() { wake = 1; },
    burst(n = 80) {
      wake = Math.max(wake, 0.9);
      for (let i = 0; i < n; i++) bursts.push({ a: Math.random() * 6.283, r: 1 + Math.random() * 0.2, v: 0.012 + Math.random() * 0.03, life: 0.6 + Math.random() * 0.7, c: BURST[Math.random() < 0.7 ? 0 : 1] });
    },
    set onTap(fn) { onTap = fn; },
    destroy() {
      alive = false;
      if (ro) ro.disconnect(); else window.removeEventListener('resize', size);
      cv.removeEventListener('pointerenter', onEnter); cv.removeEventListener('pointerleave', onLeave);
      cv.removeEventListener('pointerdown', onDown); cv.removeEventListener('pointermove', onMove);
      cv.removeEventListener('pointerup', release); cv.removeEventListener('pointercancel', release);
    },
  };
}
