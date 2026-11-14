/* The voice view's motion and layout math (2026-11-14, the smoothness pass). Pure: no React, no DOM, no regex (D-046).
   Every per-frame or per-pointer-move write of the stage goes through here, so it is measured once and written only
   when it changes what is seen:
   - levelText: the voice's level as written to --lvl (two decimals; a change under 0.02 is not a visible change)
   - parkOffset: where the orb glides when the stage comes up (Mitra: a 132 px orb at the top right; a phone: a 40 px badge)
   - leanVars: a card's lean and glint under the pointer, from a rect read ONCE when the pointer came in
   - spokenSentences: the sentences of the captions that are complete, for the screen reader's live region (the visual
     captions change word by word; announcing each word would be noise) */

const clamp01 = (v) => Math.max(0, Math.min(1, Number(v) || 0));

/** The level as the CSS reads it: 0..1, two decimals, snapped to 0.02 steps ("0.36"). */
export function levelText(v) {
  return (Math.round(clamp01(v) * 50) / 50).toFixed(2);
}

/** The orb's glide to its parked place: the offset and scale of a box centred at (cx, cy), `w` wide, inside a root
    `rootW` wide. Desktop: 132 px, its centre 28 px + 66 px from the right edge, 84 px + 66 px from the top. A phone
    (root 600 px or narrower): a 40 px badge, 12 px from the right, in the 56 px title row. */
export function parkOffset({ cx, cy, w, rootW }) {
  const phone = rootW <= 600;
  const size = phone ? 40 : 132;
  const tx = rootW - (phone ? 12 : 28) - size / 2;
  const ty = phone ? 56 + 4 + size / 2 : 84 + size / 2;
  return { dx: +(tx - cx).toFixed(1), dy: +(ty - cy).toFixed(1), scale: +(size / Math.max(1, w)).toFixed(3) };
}

/** The CSS transform string of a parkOffset. */
export const parkTransform = (o) => `translate(${o.dx}px, ${o.dy}px) scale(${o.scale})`;

/** A card's lean under the pointer: the glint's position (percent) and the tilt (deg), from the pointer and the card's
    rect at rest. Out-of-rect pointers are clamped to the edge (the card never over-tilts). */
export function leanVars(x, y, rect) {
  const w = Math.max(1, rect.width); const h = Math.max(1, rect.height);
  const fx = clamp01((x - rect.left) / w); const fy = clamp01((y - rect.top) / h);
  return {
    mx: (fx * 100).toFixed(1) + '%',
    my: (fy * 100).toFixed(1) + '%',
    rx: ((fy - 0.5) * -6).toFixed(2) + 'deg',
    ry: ((fx - 0.5) * 7).toFixed(2) + 'deg',
  };
}

const CLOSERS = '"\')”’';
const endsSentence = (w) => {
  let t = String(w || '');
  while (t && CLOSERS.includes(t[t.length - 1])) t = t.slice(0, -1);
  return !!t && '.?!'.includes(t[t.length - 1]);
};

/** The complete sentences of a caption. While it streams, the sentence still being said is left out (it is announced
    once it ends); a finished caption is all of it. Whitespace is collapsed; no regex. */
export function spokenSentences(text, streaming = false) {
  const ws = String(text || '').split('\n').join(' ').split('\t').join(' ').split(' ').map((w) => w.trim()).filter((w) => w.length > 0);
  const out = [];
  let cur = [];
  ws.forEach((w) => {
    cur.push(w);
    if (endsSentence(w)) { out.push(cur.join(' ')); cur = []; }
  });
  if (cur.length && !streaming) out.push(cur.join(' '));
  return out;
}
