/* The Secretary's desk (D-105): the home of the voice view. A replica of Sakala Mitra's Chief Secretary side columns
   (D:/Sakala POC/mitra/web/mitra.js UI.board + renderConvo, mitra.css .card / .kpis.k8 / .boardh / .bar / .minirow /
   .pstrip / .convo; read-only source), in Megh's purple.
   Left: card "Command view" = 8 command tiles (Mitra's k8, the hero tile dark), the years each scheme holds (in place of
   Mitra's 7-day clock), money by scheme (Mitra's .bar rows), the busiest districts (Mitra's .minirow), and Mitra's pulse
   strip re-purposed as MGNREGA person-days by district + the year sparkline.
   Right: card "On the map" (the Meghalaya map of one scheme's figure, chips switch the scheme) and card "Conversation"
   (Mitra's strip of exchanges; a tap shows that answer again).
   Every tile, bar, row, cell and chip asks its question by voice-text, so the answer comes from the pipeline like any
   other. The figures are /api/voice/board's (app/voice/board.py), read-only; nothing is ever added across schemes except
   money, the one unit they share, and even that is shown per scheme.
   Motion: the column's own entrance (VoiceStage) is the one entrance; inside it only one-shot transitions (count-up,
   cells, sparkline) run once, so no CSS animation starts on the desk and nothing loops. */
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { SCHEME_HUES, fmt } from '../chartTheme.js';
import { fmtFor } from './vizPlan.js';
import { StageCard } from './StageCards.jsx';
import '../../styles/voice-desk.css';

const titleCase = (s) => String(s).toLowerCase().split(' ').map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ');
const hue = (s) => (SCHEME_HUES[s] ? SCHEME_HUES[s].main : '#7C3FBF');
const reduced = () => typeof window !== 'undefined' && window.matchMedia
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// the eight command tiles (Mitra's k8): [scheme, measure key, the question the tile asks]; the first is the hero tile
const COMMAND = [['MGNREGA', 'person_days'], ['MGNREGA', 'expenditure'], ['PMAY-G', 'sanctioned'], ['PMAY-G', 'completed'],
  ['Focus Plus', 'amount'], ['Focus Legacy', 'groups'], ['CM Elevate', 'applications'], ['CM Elevate Legacy', 'disbursed']];
// money by scheme: the one unit the schemes share (Mitra's "Departments" bars)
const MONEY = [['MGNREGA', 'expenditure'], ['PMAY-G', 'released'], ['Focus Plus', 'amount'], ['CM Elevate Legacy', 'disbursed'],
  ['Focus Legacy', 'amount']];
// the map's measure per scheme
const MAP_MEASURE = { MGNREGA: 'person_days', 'PMAY-G': 'completed', 'Focus Plus': 'amount', 'Focus Legacy': 'groups',
  'CM Elevate': 'applications', 'CM Elevate Legacy': 'disbursed' };

// money keeps one unit while it counts up (crore, else lakh, else rupees), so the figure never jumps unit mid-count
function moneyUnit(total) {
  const a = Math.abs(Number(total) || 0);
  if (a >= 1e7) return { div: 1e7, word: 'crore' };
  if (a >= 1e5) return { div: 1e5, word: 'lakh' };
  return { div: 1, word: '' };
}
const round2 = (v) => Math.round(v * 100) / 100;
// a tile's figure as [number, unit word]: money in ₹ crore, counts in Indian grouping (vizPlan's fmtFor, whole)
function tileParts(m, v) {
  if (m.unit === 'rupees') {
    const u = moneyUnit(m.total);
    return [`₹${fmt(u.div === 1 ? Math.round(v) : round2(v / u.div))}`, u.word];
  }
  return [fmtFor(null)(Math.round(v)), ''];
}
const crore = (v) => fmt(round2((Number(v) || 0) / 1e7));
const fmtDate = (iso) => {
  const d = iso ? new Date(iso) : new Date();
  return (Number.isFinite(d.getTime()) ? d : new Date()).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
};
// the first sentence of an answer, plain (no markdown marks), for the conversation strip
function firstSentence(text) {
  const plain = String(text || '').split('**').join('').split('`').join('').split('__').join('');
  const line = plain.split('\n').map((l) => l.trim()).find((l) => l && !l.startsWith('|')) || '';
  let s = line;
  while (s.startsWith('#') || s.startsWith('-') || s.startsWith('*') || s.startsWith('>')) s = s.slice(1).trimStart();
  const stop = s.indexOf('. ');
  const cut = stop > 0 ? s.slice(0, stop + 1) : s;
  return cut.length > 180 ? `${cut.slice(0, 177).trimEnd()}…` : cut;
}

function years(board) {
  const all = new Set();
  const per = {};
  (board.schemes || []).forEach((s) => {
    const held = new Set();
    s.measures.forEach((m) => Object.keys(m.by_year || {}).forEach((y) => { held.add(y); all.add(y); }));
    per[s.name] = held;
  });
  return { cols: [...all].sort((a, b) => a.localeCompare(b)), per };
}

// Mitra's countUp: 700 ms, ease 1-(1-k)^3, from the value shown before (0 the first time)
function useCountUp(to) {
  const [v, setV] = useState(() => (reduced() ? to : 0));
  const prev = useRef(reduced() ? to : 0);
  useEffect(() => {
    const from = prev.current;
    prev.current = to;
    if (from === to || reduced()) { setV(to); return undefined; }
    const t0 = performance.now();
    let raf = 0;
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 700);
      setV(from + (to - from) * (1 - (1 - k) ** 3));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return v;
}

function Tile({ s, m, hero, onAsk }) {
  const v = useCountUp(Number(m.total) || 0);
  const [num, word] = tileParts(m, v);
  const [fin] = tileParts(m, Number(m.total) || 0);
  const label = m.label.toLowerCase().startsWith(s.toLowerCase()) ? m.label : `${s} · ${m.label}`;
  return (
    <button type="button" className={'sd-tile sdk-kpi' + (hero ? ' hero' : '')} style={{ '--c': hue(s), '--ch': fin.length + (word ? 2 : 0) }}
            onClick={() => onAsk(`${s} ${m.label.toLowerCase()} by district`)} title={`What this counts: ${m.counts}`}>
      <span className="v">{num}{word && <small>{word}</small>}</span>
      <span className="l">{label}</span>
    </button>
  );
}

function LeftDesk({ board, onAsk }) {
  const find = (s, k) => { const sc = (board?.schemes || []).find((x) => x.name === s); return sc ? sc.measures.find((m) => m.key === k) : null; };
  const tiles = useMemo(() => COMMAND.map(([s, k]) => ({ s, m: find(s, k) })).filter((x) => x.m), [board]); // eslint-disable-line react-hooks/exhaustive-deps
  const money = useMemo(() => MONEY.map(([s, k]) => ({ s, m: find(s, k) })).filter((x) => x.m && Number(x.m.total) > 0), [board]); // eslint-disable-line react-hooks/exhaustive-deps
  const pd = useMemo(() => find('MGNREGA', 'person_days'), [board]); // eslint-disable-line react-hooks/exhaustive-deps
  const yr = useMemo(() => (board ? years(board) : { cols: [], per: {} }), [board]);
  const schemes = (board?.schemes || []).map((s) => s.name);
  const districts = useMemo(() => (pd ? Object.entries(pd.by_district || {}).map(([d, v]) => ({ d, v: Number(v) || 0 }))
    .sort((a, b) => b.v - a.v) : []), [pd]);
  const dTotal = districts.reduce((a, x) => a + x.v, 0);
  const dMax = Math.max(1, ...districts.map((x) => x.v));
  const dMin = districts.length ? Math.min(...districts.map((x) => x.v)) : 0;
  const mMax = Math.max(1, ...money.map((x) => Number(x.m.total) || 0));
  const series = useMemo(() => (pd ? Object.entries(pd.by_year || {}).sort((a, b) => a[0].localeCompare(b[0])) : []), [pd]);
  const spark = useMemo(() => {
    if (series.length < 2) return '';
    const vs = series.map(([, v]) => Number(v) || 0);
    const mx = Math.max(...vs); const mn = Math.min(...vs);
    return vs.map((v, i) => `${(i / (vs.length - 1) * 100).toFixed(1)},${(28 - (v - mn) / Math.max(1, mx - mn) * 24).toFixed(1)}`).join(' ');
  }, [series]);
  // one-shot transitions (cells rise, sparkline draws) once the board is there: no CSS animation, nothing loops
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!board || ready) return undefined;
    let r2 = 0;
    const r1 = requestAnimationFrame(() => { r2 = requestAnimationFrame(() => setReady(true)); });
    return () => { cancelAnimationFrame(r1); cancelAnimationFrame(r2); };
  }, [board, ready]);
  if (!board) return <div className="sd-left sdk" />;
  return (
    <div className={'sd-left sdk' + (ready ? ' in' : '')}>
      <section className="sdk-card" aria-label="Command view">
        <h3>Command view <small>Meghalaya · live · {fmtDate(board.as_of)}</small></h3>
        <div className="sd-tiles sdk-k8">
          {tiles.map(({ s, m }, i) => <Tile key={s + m.key} s={s} m={m} hero={i === 0} onAsk={onAsk} />)}
        </div>

        {yr.cols.length > 0 && (
          <div className="sd-years" aria-label="The years each scheme holds">
            <div className="sdk-boardh"><span>Years held</span><span>a gap is no data</span></div>
            <div className="sd-yr-grid" style={{ '--n': yr.cols.length }}>
              <span />
              {yr.cols.map((y) => <span key={y} className="sd-yr-c">{y.length > 5 ? y.slice(2) : y}</span>)}
              {schemes.map((s) => [
                <span key={s} className="sd-yr-s" style={{ '--c': hue(s) }} title={s}>{s}</span>,
                ...yr.cols.map((y) => <i key={s + y} className={yr.per[s] && yr.per[s].has(y) ? 'on' : ''} style={{ '--c': hue(s) }}
                                         title={`${s} ${y}: ${yr.per[s] && yr.per[s].has(y) ? 'held' : 'no data'}`} />),
              ])}
            </div>
            {yr.per['CM Elevate'] && yr.per['CM Elevate'].size === 0 && <p className="sd-yr-n">CM Elevate applications carry no year.</p>}
          </div>
        )}

        {money.length > 0 && (
          <>
            <div className="sdk-boardh"><span>Money by scheme</span><span>₹ crore</span></div>
            <div className="sdk-bars">
              {money.map(({ s, m }) => (
                <button key={s + m.key} type="button" className="sdk-bar" onClick={() => onAsk(`${s} money by district`)}
                        title={`${s} · ${m.label}: ${fmtFor('rupees')(m.total)}`}>
                  <span className="t">{s}</span>
                  <span className="b"><i style={{ width: `${Math.round((Number(m.total) || 0) / mMax * 100)}%` }} /></span>
                  <span className="n">{crore(m.total)}</span>
                </button>
              ))}
            </div>
          </>
        )}

        {districts.length > 0 && (
          <>
            <div className="sdk-boardh"><span>Busiest districts</span><span>MGNREGA person-days</span></div>
            {districts.slice(0, 6).map((x) => (
              <button key={x.d} type="button" className="sdk-minirow" onClick={() => onAsk(`${titleCase(x.d)} — give me each scheme's figures`)}>
                <span>{titleCase(x.d)}</span>
                <span><b>{fmt(x.v)}</b> · {dTotal ? Math.round(x.v / dTotal * 100) : 0}%</span>
              </button>
            ))}

            <div className="sdk-pstrip">
              <div className="ph"><span>Person-days by district</span><span>{fmtFor(null)(dMin)} → {fmtFor(null)(dMax)}</span></div>
              <div className="cells" style={{ '--n': districts.length }}>
                {districts.map((x, i) => (
                  <button key={x.d} type="button" className={i === 0 ? 'top' : ''} style={{ '--h': (x.v / dMax).toFixed(2), '--i': i }}
                          title={`${titleCase(x.d)} · ${fmt(x.v)} person-days · rank ${i + 1}`} aria-label={`${titleCase(x.d)} MGNREGA person-days`}
                          onClick={() => onAsk(`${titleCase(x.d)} MGNREGA person-days`)} />
                ))}
              </div>
              {spark && (
                <>
                  <div className="ph"><span>MGNREGA person-days, {series[0][0]} → {series[series.length - 1][0]}</span>
                    <span>{fmtFor(null)(series[0][1])} → {fmtFor(null)(series[series.length - 1][1])}</span></div>
                  <svg className="spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
                    <polyline className="fill" points={`0,30 ${spark} 100,30`} />
                    <polyline className="ln" points={spark} />
                  </svg>
                </>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function RightDesk({ board, conversation, onPin }) {
  const [scheme, setScheme] = useState('MGNREGA');
  const schemes = (board?.schemes || []).map((s) => s.name).filter((s) => MAP_MEASURE[s]);
  const active = schemes.includes(scheme) ? scheme : schemes[0];
  const measure = useMemo(() => {
    const sc = (board?.schemes || []).find((x) => x.name === active);
    return sc ? sc.measures.find((m) => m.key === MAP_MEASURE[active]) : null;
  }, [board, active]);
  const mapSpec = useMemo(() => {
    if (!measure) return null;
    const unit = measure.unit === 'rupees' ? 'rupees' : null;
    return { id: `desk-${active}`, kind: 'map', mapMode: 'choropleth', title: `${active} · ${measure.label} by district`,
      unit, unitLabel: unit ? '₹' : '', fmt: fmtFor(unit), allowed: ['map', 'race'], wide: true,
      items: Object.entries(measure.by_district || {}).map(([d, v]) => ({ key: d, label: titleCase(d), value: v, color: hue(active) })),
      note: `What this counts: ${measure.counts}.` };
  }, [measure, active]);
  // the desk draws at once (no voice to sync with)
  const registry = useMemo(() => ({ add: (_id, h) => h.revealAll(0), remove: () => {} }), []);
  const list = (conversation || []).slice(-6);
  const n = (conversation || []).length;
  const strip = useRef(null);
  useEffect(() => { if (strip.current) strip.current.scrollTop = strip.current.scrollHeight; }, [n]);
  return (
    <div className="sd-right sdk">
      <section className="sdk-card sdk-map" aria-label="On the map">
        <h3>On the map <small>{measure ? `${active} · ${measure.label}` : 'Meghalaya'}</small></h3>
        <div className="sd-chips" role="group" aria-label="Scheme on the map">
          {schemes.map((s) => (
            <button key={s} type="button" className={s === active ? 'on' : ''} style={{ '--c': hue(s) }} onClick={() => setScheme(s)}>
              <i aria-hidden="true" />{s}
            </button>
          ))}
        </div>
        {mapSpec && <StageCard spec={mapSpec} index={0} registry={registry} still />}
        {measure && <p className="sdk-cap">What this counts: {measure.counts}.</p>}
      </section>

      <section className="sdk-card" aria-label="Conversation">
        <h3>Conversation <small>{n ? `${n} exchange${n === 1 ? '' : 's'}` : 'nothing asked yet'}</small></h3>
        {list.length ? (
          <div className="sdk-convo" ref={strip}>
            {list.map((m) => (
              <button key={m.id} type="button" className="sdk-ex" onClick={() => onPin && onPin(m.id)} title="Show this answer again">
                <span className="you"><span>{m.question}</span></span>
                {firstSentence(m.response && m.response.answer) && (
                  <span className="jv"><span>{firstSentence(m.response && m.response.answer)}</span></span>
                )}
              </button>
            ))}
          </div>
        ) : (
          <p className="sdk-empty">Say “give me the position”, or tap a tile, a bar or a district. Each exchange appears here, and a tap
            shows that answer again.</p>
        )}
      </section>
    </div>
  );
}

export const SecretaryDesk = memo(function SecretaryDesk({ board, onAsk, conversation, onPin, side }) {
  if (side === 'left') return <LeftDesk board={board} onAsk={onAsk} />;
  return <RightDesk board={board} conversation={conversation} onPin={onPin} />;
});
