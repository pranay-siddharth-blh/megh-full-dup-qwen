/* The Secretary view's chart cards (D-105): Mitra's card shell (it arcs in with a sheen and a scan line, leans with
   the pointer, a ghost of the previous picture fades as the new one turns in) around the canvas renderers of
   stageCanvas.js, and the speech-synced reveal across every card of a turn (Mitra's Stage.hear / flush). A card is
   memoised on its plan id and kind, so captions and the voice's level never redraw it; it is drawn once per answer. */
import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createStageCard } from './stageCanvas.js';
import { heardItem, norm } from './vizPlan.js';

// the reveal's clock (2026-11-10, tightened so the picture never trails the voice): the rest glide in this soon after
// the voice has named the last item it was going to name; a voice that never starts / names nothing on the cards
const REVEAL = { afterLast: 450, neverStarted: 6000, nothingNamed: 1800, safety: 60000, glide: 180 };
const KIND_NAME = { bars: 'Bars', race: 'Ranking', line: 'Line', donut: 'Donut', map: 'Map', tiles: 'Tiles', kpi: 'Figure', table: 'Table' };
const reduced = () => typeof window !== 'undefined' && window.matchMedia
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** One card, Mitra's .vcard shell (stage.js: `<div class="vcard k-{kind}"><div class="vh"><b>title</b><span>subtitle</span></div>
    <div class="vb"><canvas class="vcv"></canvas></div>`): the header, the canvas body, a quiet note line under it.
    `kind` given = controlled (the stage's "Show as" column drives it, Mitra's Stage.morph); not given = the card keeps
    its own kind and shows its own small switch (the desk's map). */
export const StageCard = memo(function StageCard({ spec, index, registry, onHover, still = false, kind: kindProp, className = '' }) {
  const cvRef = useRef(null);
  const [own, setOwn] = useState(spec.kind);
  useEffect(() => { setOwn(spec.kind); }, [spec.id, spec.kind]);
  const controlled = kindProp !== undefined && kindProp !== null;
  const kind = controlled ? kindProp : own;
  useEffect(() => {
    const cv = cvRef.current;
    if (!cv) return undefined;
    let h = null;
    try {
      h = createStageCard(cv, { ...spec, kind }, { reduced: still || reduced(), onHover });   // still: drawn finished (the desk)
    } catch (e) {
      h = null;
    }
    if (h && registry) registry.add(spec.id, h, kind !== spec.kind);
    return () => {
      if (registry) registry.remove(spec.id, h);
      try { if (h) h.destroy(); } catch (e) { /* gone */ }
    };
  }, [spec, kind, registry, onHover, still]);
  // the card leans under the pointer and a glint follows it (Mitra: hover tilt + .glint at --mx / --my)
  const lean = (e) => {
    const el = e.currentTarget; const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', (((e.clientX - r.left) / r.width) * 100).toFixed(1) + '%');
    el.style.setProperty('--my', (((e.clientY - r.top) / r.height) * 100).toFixed(1) + '%');
    el.style.setProperty('--rx', (((e.clientY - r.top) / r.height - 0.5) * -6).toFixed(2) + 'deg');
    el.style.setProperty('--ry', (((e.clientX - r.left) / r.width - 0.5) * 7).toFixed(2) + 'deg');
  };
  const rest = (e) => { e.currentTarget.style.setProperty('--rx', '0deg'); e.currentTarget.style.setProperty('--ry', '0deg'); };
  const ownKinds = !controlled && spec.allowed && spec.allowed.length > 1;
  return (
    <section className={`vc vcard k-${kind} vc-${kind}${spec.wide || kind === 'map' ? ' wide' : ''}${className ? ' ' + className : ''}`}
             style={{ '--i': index }}
             onPointerMove={lean} onPointerLeave={rest} data-kind={kind} data-card={spec.id}>
      <header className="vh vc-h">
        <h3 title={spec.title}>{spec.title}{spec.explain && <em className="vc-tag">explains the figure</em>}</h3>
        {spec.unitLabel && <span className="vc-unit">{spec.unitLabel}</span>}
        {ownKinds && (
          <div className="vc-kinds" role="group" aria-label="Show as">
            {spec.allowed.map((k) => (
              <button key={k} type="button" className={k === kind ? 'on' : ''} onClick={() => setOwn(k)}
                      aria-pressed={k === kind}>{KIND_NAME[k] || k}</button>
            ))}
          </div>
        )}
      </header>
      <div className="vb vc-body"><canvas className="vcv" ref={cvRef} aria-label={spec.title} /></div>
      {(spec.note || spec.more > 0) && (
        <footer className="vc-f">
          {spec.note && <span className="vc-note">{spec.note}</span>}
          {spec.more > 0 && <span className="vc-more">+{spec.more} more in the chat</span>}
        </footer>
      )}
      <i className="vc-sheen" aria-hidden="true" /><i className="vc-scan" aria-hidden="true" /><i className="vc-glint" aria-hidden="true" />
    </section>
  );
}, (a, b) => a.spec === b.spec && a.index === b.index && a.registry === b.registry && a.still === b.still
  && a.kind === b.kind && a.className === b.className);

export const KIND_LABEL = KIND_NAME;

/* The reveal of one turn's cards. Every item starts hidden; the item whose name the voice says comes in (on every card
   that holds it: the district on the ranking AND on the map); the voice's end of turn brings in the rest with Mitra's
   stagger; nothing named 3 s after the cards are up brings everything in (Mitra's rule); a safety net at 30 s.
   `active` false (an older answer pinned, the voice off): everything is drawn at once. */
export function useCardReveal(plan, planKey, active, spoken, turnOver, speaking = false, script = '') {
  const R = useRef(null);
  if (!R.current) R.current = { handles: new Map(), said: new Set(), all: false, timers: [], lastHit: 0, heard: ' ', key: null };
  const registry = useRef(null);
  if (!registry.current) {
    registry.current = {
      add: (id, h, morphed) => {
        const r = R.current;
        r.handles.set(id, h);
        if (r.all || morphed) { h.revealAll(0); return; }
        r.said.forEach((k) => h.reveal(k));
      },
      remove: (id, h) => { if (R.current.handles.get(id) === h) R.current.handles.delete(id); },
      // the stage's insight chip: told once everything is in (Mitra: insight() after the last item)
      onAll: null,
      isAll: () => R.current.all,
    };
    // headless tests only (?voicetest=1): each card's items and how far each has grown
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('voicetest') === '1') {
      window.__stageCards = () => [...R.current.handles.entries()].map(([id, h]) => { try { return { id, ...h.state() }; } catch (e) { return { id }; } });
    }
  }
  const log = (what) => { if (window.__meghVoice) (window.__revealLog = window.__revealLog || []).push({ t: Math.round(performance.now()), what, n: R.current.said.size }); };
  const revealAll = useCallback((why) => {
    const r = R.current;
    if (r.all) return;
    r.all = true;
    r.handles.forEach((h) => { try { h.revealAll(REVEAL.glide); } catch (e) { /* gone */ } });
    log(why);
    if (registry.current && registry.current.onAll) registry.current.onAll();
  }, []);
  // a layout effect: it runs before the cards' own (passive) effects create their canvases, so a new card never
  // registers against the previous turn's state
  useLayoutEffect(() => {
    const r = R.current;
    r.timers.forEach(clearTimeout);
    r.timers = []; r.said = new Set(); r.all = !active || !plan; r.lastHit = 0; r.heard = ' '; r.key = planKey;
    if (!plan) return undefined;
    if (!active) { r.handles.forEach((h) => h.revealAll(0)); return undefined; }
    r.spoke = false;
    // what the voice will read is known (the page built it, voiceSpeech.spokenForm): the items it names wait for
    // their name; the others come in when it has said the last of them, or at the end of the turn
    const said = norm(script);
    r.expect = new Set();
    plan.cards.forEach((c) => (c.items || []).forEach((it) => { if (script && heardItem(said, it)) r.expect.add(it.key); }));
    // a voice that never starts: everything after REVEAL.neverStarted
    r.timers.push(setTimeout(() => { if (!R.current.spoke && !R.current.lastHit) revealAll('the voice never started'); }, REVEAL.neverStarted));
    r.timers.push(setTimeout(() => revealAll('safety net'), REVEAL.safety));
    return () => r.timers.forEach(clearTimeout);
  }, [planKey, active]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const r = R.current;
    if (!plan || r.all || !spoken) return;
    const heard = norm(spoken);
    if (heard === r.heard) return;
    r.heard = heard;
    let hit = false;
    plan.cards.forEach((c) => (c.items || []).forEach((it) => {
      if (r.said.has(it.key) || !heardItem(heard, it)) return;
      r.said.add(it.key);
      hit = true;
      r.handles.forEach((h) => { try { h.reveal(it.key, true); } catch (e) { /* gone */ } });   // true: spotlit while it is said
    }));
    if (hit) {
      r.lastHit = performance.now(); log('named');
      if (r.expect.size && [...r.expect].every((k) => r.said.has(k))) {
        r.timers.push(setTimeout(() => revealAll('the voice named the last of them'), REVEAL.afterLast));
      }
    }
  }, [spoken, plan, revealAll]);
  useEffect(() => { if (turnOver && plan) revealAll('end of turn'); }, [turnOver, plan, revealAll]);
  // Mitra's rule, counted from the moment the voice starts reading this answer (not from when the cards are up: the
  // voice's opening sentence can take 4 s before it names anything): nothing named 3 s in -> everything comes in
  useEffect(() => {
    const r = R.current;
    if (!speaking || !plan || r.all || r.spoke) return;
    r.spoke = true;
    // Mitra's rule, from the moment the voice starts: a reading that names nothing on the cards brings everything
    // in after REVEAL.nothingNamed (one that names them waits for the names: the opening sentence can take 5 s)
    if (!r.expect.size) r.timers.push(setTimeout(() => { if (!R.current.lastHit) revealAll('nothing to name, 3 s'); }, REVEAL.nothingNamed));
  }, [speaking, plan, revealAll]);
  useEffect(() => () => R.current.timers.forEach(clearTimeout), []);
  return registry.current;
}
