import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { buildAnalytics, chartPreference, humanCol, withoutChartPhrase } from '../analytics.js';
import { answerKey, fullStamp } from '../format.js';
import { rowsAsTsv } from '../exporters.js';
import { CompareCard, DynTable, GroupedChart, PivotTable, RecordCard, StackedChart, SwitchableChart, TwoDimChart } from './Charts.jsx';
import { Markdown, plainText } from './Markdown.jsx';
import { useReveal } from '../reveal.js';
import { themeFor } from '../chartTheme.js';
import { sendFeedbackApi } from '../api.js';
import { inlineSpans } from '../text.js';
import { enterSends } from '../shortcuts.js';

/* One chat message. A bot answer (`response` from /api/query) renders the same
   blocks as addBotRich() in web/ai_query.html: routing badge (off), answer text,
   analytics, the "SQL query used" disclosure, then the follow-up area (scheme
   picker, next steps and sources, a clarification, or starter suggestions). */

// "a **b** c" -> ["a ", "b", " c"]: the text between bold spans, and the bold
// text at odd indexes.
function splitBold(line) {
  const parts = [];
  let last = 0;
  for (const m of inlineSpans(line)) {
    parts.push(line.slice(last, m.start), m.inner);
    last = m.end;
  }
  parts.push(line.slice(last));
  return parts;
}

// Text with line breaks; a bot answer also turns **x** into bold.
function RichText({ text, bold }) {
  const lines = String(text || '').split('\n');
  return lines.map((line, i) => {
    const parts = bold ? splitBold(line) : [line];
    return (
      <Fragment key={i}>
        {i > 0 && <br />}
        {parts.map((p, j) => (j % 2 === 1 ? <strong key={j}>{p}</strong> : <Fragment key={j}>{p}</Fragment>))}
      </Fragment>
    );
  });
}

// ── Analytics ───────────────────────────────────────────────────────────────
function Analytics({ question, response, view, onAsk }) {
  // What the officer asked to see: "/chart" / "/table", or the words of the
  // question ("in graph", "as a pie chart", "show it as a table").
  // The standalone question first: "why are you giving a line chart?" is answered
  // as "... as a pie chart" (rewritten by the backend); its own words name the
  // wrong type.
  const asked = view || chartPreference(response.rewritten_question) || chartPreference(question);
  const prefer = asked === 'chart' || (asked && asked !== 'table') ? asked : null;
  const a = useMemo(
    () => buildAnalytics(question, response.data, response.chart_type, prefer),
    [question, response, prefer],
  );
  // The answer's scheme picks the charts' hue (chartTheme.js, D-043).
  const theme = useMemo(() => themeFor(response.schemes), [response.schemes]);
  if (!a) return null;
  // "/table" or "as a table" shows the rows as a table whatever the charts
  // would have been; a chart asked for shows the charts without their table.
  if (asked === 'table') return <div className="analytics"><DynTable data={response.data} /></div>;
  const withTables = !prefer && !a.noTable;
  // A named type ("pie chart", "bar graph", "line chart") is that chart ONLY —
  // no Bar / Pie / Donut / Line switcher. A plain "chart" / "graph", or nothing
  // asked, keeps every type on offer (user, 2026-10-19).
  // A type the rows cannot honestly be drawn as (a donut of overlapping counts,
  // a stack of schemes) was refused by buildAnalytics: bars, with its note.
  const named = prefer && prefer !== 'chart' && !a.refused;
  const only = named ? (prefer === 'stacked' ? 'bar' : prefer) : null;
  const only2d = named ? prefer : null;
  const note = a.note ? <div className="chart-note"><p>{a.note}</p></div> : null;
  const typesOr = (all) => (only ? [only] : all);
  // A chart was asked for but the answer is one figure: say so, and offer the
  // breakdowns that can be drawn, instead of silently showing the number again.
  if (prefer && a.kind === 'record') {
    const base = withoutChartPhrase(response.rewritten_question || question);
    return (
      <div className="analytics">
        <div className="chart-note">
          <p>This is a single figure, so there is nothing to draw as a chart. I can chart it broken down:</p>
          {onAsk && base && (
            <div className="clarify-opts">
              {['by district', 'for each financial year'].map((tail) => (
                <button key={tail} type="button" className="clarify-opt" {...askProps(onAsk, `${base} ${tail} as a chart`)}>
                  {tail[0].toUpperCase() + tail.slice(1)}
                </button>
              ))}
            </div>
          )}
        </div>
        <RecordCard row={a.row} />
      </div>
    );
  }
  if (a.kind === 'kpi') {
    return (
      <div className="analytics">
        <div className="dyn-grid single">
          <SwitchableChart title="Summary" labels={a.labels} values={a.values} types={typesOr(['bar', 'pie', 'doughnut'])} initial={only || a.defType} theme={theme} />
        </div>
        {withTables && <RecordCard row={a.row} />}
      </div>
    );
  }
  if (a.kind === 'record') return <div className="analytics"><RecordCard row={a.row} /></div>;
  if (a.kind === 'compare') {
    // G-9 / B-11: what the figure is for each scheme ("household-years", "money released")
    const said = (side) => (response.measure_notes && response.measure_notes[side.label]
      && response.measure_notes[side.label][a.vKey]) || side.detail;
    return (
      <div className="analytics">
        <CompareCard title={a.title} measure={a.measure} a={{ ...a.a, detail: said(a.a) }} b={{ ...a.b, detail: said(a.b) }}
                     verdict={a.verdict} unit={a.unit} />
        {(a.more || []).map((c) => (
          <CompareCard key={c.vKey} title={a.title} measure={c.measure} unit={c.unit} verdict={c.verdict}
                       a={{ ...c.a, detail: (response.measure_notes && response.measure_notes[c.a.label] && response.measure_notes[c.a.label][c.vKey]) || c.a.detail }}
                       b={{ ...c.b, detail: (response.measure_notes && response.measure_notes[c.b.label] && response.measure_notes[c.b.label][c.vKey]) || c.b.detail }} />
        ))}
        {withTables && a.extra && <DynTable data={a.data} />}
      </div>
    );
  }
  if (a.kind === 'table') {
    return (
      <div className="analytics">{note}
        {a.pivot ? <PivotTable data={a.data} xKey={a.pivot.xKey} sKey={a.pivot.sKey} vKey={a.pivot.vKey} /> : <DynTable data={a.data} />}
      </div>
    );
  }
  // A chart type was asked for: answers whose card has no type switch (grouped,
  // stacked) are drawn by the cards that have one, so the asked type is used.
  if (prefer && a.kind === 'stacked') {
    return (
      <div className="analytics">
        <div className="dyn-grid single">
          <TwoDimChart title={a.title} labels={a.labels.map(String)} datasets={a.datasets} xKey={a.xKey} sKey={a.sKey}
                       initial={only2d || 'stacked'} types={only2d ? [only2d] : undefined} theme={theme} />
        </div>
      </div>
    );
  }
  if (prefer && a.kind === 'grouped' && prefer !== 'chart' && prefer !== 'bar') {
    return (
      <div className="analytics">
        <div className={'dyn-grid' + (a.datasets.length === 1 ? ' single' : '')}>
          {a.datasets.map((d) => (
            <SwitchableChart key={d.label} title={d.label} labels={a.labels} fullLabels={a.fullLabels} values={d.values}
                             types={typesOr(['bar', 'pie', 'doughnut', 'line'])} initial={only || 'bar'} theme={theme} />
          ))}
        </div>
      </div>
    );
  }
  // A chart was asked for but the rows hold no numbers: say so plainly.
  if (prefer && a.kind === 'table') {
    return (
      <div className="analytics">
        <div className="chart-note"><p>These results are names and labels with no numbers, so there is nothing to chart. Here they are as a table.</p></div>
        <DynTable data={a.data} />
      </div>
    );
  }
  if (a.kind === 'grouped') {
    return (
      <div className="analytics">
        <div className="dyn-grid single"><GroupedChart title={a.title} labels={a.labels} fullLabels={a.fullLabels} datasets={a.datasets} theme={theme} /></div>
        {withTables && <DynTable data={a.data} />}
      </div>
    );
  }
  if (a.kind === 'stacked') {
    return (
      <div className="analytics">
        <div className="dyn-grid single"><StackedChart title={a.title} labels={a.labels} datasets={a.datasets} theme={theme} /></div>
        {withTables && <PivotTable data={a.data} xKey={a.xKey} sKey={a.sKey} vKey={a.vKey} />}
      </div>
    );
  }
  if (a.kind === 'twoDim') {
    return (
      <div className="analytics">
        {note}
        <div className="dyn-grid single">
          <TwoDimChart title={a.title} labels={a.labels} datasets={a.datasets} xKey={a.xKey} sKey={a.sKey}
                       periods={a.periods} initial={only2d || a.defType} types={only2d ? [only2d] : a.types} theme={theme}
                       axisInfo={a.axes} />
          {(a.more || []).map((m) => (
            <TwoDimChart key={m.vKey} title={m.title} labels={m.labels} datasets={m.datasets} xKey={a.xKey} sKey={a.sKey}
                         periods={a.periods} initial={only2d || a.defType} types={only2d ? [only2d] : a.types} theme={theme}
                         axisInfo={m.axes} />
          ))}
        </div>
        {withTables && (a.extra ? <DynTable data={a.data} />
          : <PivotTable data={a.data} xKey={a.xKey} sKey={a.sKey} vKey={a.vKey} totals={response.column_totals} />)}
      </div>
    );
  }
  const single = a.charts.length === 1;
  // G-9 / B-11: a scheme's bar tooltip says what its figure is
  const notes = response.measure_notes || {};
  const tip = (c, i) => {
    const vk = Object.keys((notes[c.fullLabels[i]] || {})).find((k) => c.title.toLowerCase().startsWith(humanCol(k).toLowerCase()));
    return vk ? `${c.fullLabels[i]} — ${notes[c.fullLabels[i]][vk]}` : c.fullLabels[i];
  };
  return (
    <div className="analytics">
      {note}
      <div className={'dyn-grid' + (single ? ' single' : '')}>
        {a.charts.map((c, i) => (
          <SwitchableChart key={i} title={c.title} labels={c.labels} fullLabels={c.fullLabels.map((_, j) => tip(c, j))} values={c.values}
                           types={typesOr(a.types || ['bar', 'pie', 'doughnut', 'line'])} initial={only || a.defType} theme={theme}
                           axes={c.axes} />
        ))}
      </div>
      {withTables && <DynTable data={a.data} change={!!a.change} rank={!!a.ranked} />}
      {!withTables && !a.noTable && (
        // X-15: an asked-for chart keeps its figures one tap away (and for screen readers)
        <details className="chart-figures"><summary>Show the figures as a table</summary><DynTable data={a.data} rank={!!a.ranked} /></details>
      )}
    </div>
  );
}

// ── Routing badge (developer detail; off, as in the original) ───────────────
const SHOW_ROUTE_BADGE = false;

/* The scope a data answer actually used ("MGNREGA · East Khasi Hills · FY
   2022-23"), built server-side from the SQL's own entities
   (pipeline._attach_scope_banner), so a wrongly remembered scheme, place or
   year is visible at a glance. */
function ScopeBanner({ response }) {
  const text = String((response && response.scope_banner) || '').trim();
  if (!text) return null;
  return (
    <div className="scope-banner" title="The scheme, place and year this answer used">
      <span className="sb-lbl">Answered for</span>
      <span className="sb-pill">{text}</span>
    </div>
  );
}

/* After an idle expiry the first reply offers to pick the old topic back up
   (conversation_layer.attach_continue_offer). Tapping sends the chip's text,
   which the server recognises and restores. */
function ContinueOffer({ response, onAsk }) {
  const text = String((response && response.continue_offer) || '').trim();
  if (!text || !onAsk) return null;
  return (
    <div className="continue-offer">
      <span className="co-lbl">Earlier</span>
      <div className="suggest-item" {...askProps(onAsk, text)}>{text}</div>
    </div>
  );
}

function RouteBadge({ response }) {
  const [open, setOpen] = useState(false);
  if (!SHOW_ROUTE_BADGE) return null;
  const s = response && response.scope;
  if (!s || typeof s !== 'object' || s.in_scope === false) return null;
  const schemes = Array.isArray(s.schemes) ? s.schemes : [];
  const conf = typeof s.confidence === 'number' ? s.confidence : null;
  const confCls = conf === null ? '' : (conf >= 0.85 ? 'hi' : (conf >= 0.6 ? 'mid' : 'lo'));
  const srcMap = { llm: 'classified', shortcut: 'named', fallback: 'rule-based' };
  const a = (response && response.analysis) || null;
  const e = (a && a.entities) || {};
  const named = [].concat(e.districts || [], e.regions || [], e.blocks || [], e.villages || [],
    e.banks || [], e.verticals || [], e.ids || [], e.persons || []);
  const reason = String(s.reason || '').trim();
  const rows = [];
  if (reason) rows.push(['Why', reason]);
  if (a) {
    if (a.intent_summary) rows.push(['Intent', a.intent_summary]);
    if (a.metric) rows.push(['Metric', a.metric]);
    if (a.granularity) rows.push(['Group by', <><code>{a.granularity}</code>{a.limit ? ` · limit ${a.limit}` : ''}</>]);
    if (named.length) rows.push(['Entities', named.map((n, i) => <Fragment key={i}><code>{String(n)}</code> </Fragment>)]);
    if (a.time_scope) rows.push(['Time', String(a.time_scope)]);
    if (Array.isArray(a.ambiguous) && a.ambiguous.length) {
      rows.push(['Gaps', a.ambiguous.map((t, i) => (
        <span key={i} className="qa-gap" title={String(t.why || '')}>{String(t.term || '')} ({String(t.kind || '')})</span>
      ))]);
    }
  }
  return (
    <>
      <div className="route-badge" onClick={() => setOpen(!open)}>
        <span className="rt-lbl">Routed to</span>
        {!schemes.length ? <span className="rt-scheme">from previous turn</span>
          : schemes.length === 3 ? <span className="rt-scheme all">All 3 schemes</span>
            : schemes.map((n) => <span key={n} className="rt-scheme">{n}</span>)}
        {a && a.query_type && <span className="rt-type">{String(a.query_type).replaceAll('_', ' ')}</span>}
        {conf !== null && <span className={'rt-conf ' + confCls}>{Math.round(conf * 100)}%</span>}
        {s.source && <span className="rt-src">{srcMap[s.source] || s.source}</span>}
        {s.is_followup && <span className="rt-flag">follow-up</span>}
      </div>
      {rows.length > 0 && (
        <div className={'route-reason' + (open ? ' open' : '')}>
          <div className="qa-grid">
            {rows.map(([k, v]) => <Fragment key={k}><div className="qa-k">{k}</div><div className="qa-v">{v}</div></Fragment>)}
          </div>
        </div>
      )}
    </>
  );
}

// ── SQL disclosure ──────────────────────────────────────────────────────────
function fallbackCopy(text, done) {
  try {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    done && done();
  } catch (e) { console.error('copy failed', e); }
}

// Copy `text` to the clipboard; `done` runs once it is there.
export function copyText(text, done) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function SqlDisclosure({ response }) {
  const sql = ((response && (response.sql_query || response.sql)) || '').trim();
  const [copied, setCopied] = useState(false);
  if (!sql) return null;
  const copy = (e) => {
    e.preventDefault(); e.stopPropagation();
    copyText(sql, () => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  };
  return (
    <details className="sql-disc">
      <summary>SQL query used</summary>
      <div className="sql-disc-body">
        <button className={'sql-copy' + (copied ? ' copied' : '')} type="button" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
        <pre>{sql}</pre>
      </div>
    </details>
  );
}

// ── Follow-up area ──────────────────────────────────────────────────────────
// Every chip runs its question exactly like anything the user types.
// X-9 / F-5 (audit 2026-10-29): "Next steps", "Try asking" and "Earlier" chips were
// mouse-only; every chip is reachable with Tab and taps with Enter or Space.
const askProps = (onAsk, q) => ({
  style: { cursor: 'pointer' },
  role: 'button',
  tabIndex: 0,
  onClick: (e) => { e.preventDefault(); e.stopPropagation(); onAsk(q); },
  onKeyDown: (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); onAsk(q); }
  },
});

// F-3 / F-4 (audit 2026-10-29): a data answer that failed looked like any other
// ("0 results", no retry), and one with no rows offered nothing to try next.
function AnswerState({ response, question, onAsk }) {
  if (response.route !== 'data' || response.intent === 'CLARIFY' || response.denied) return null;
  const rows = Array.isArray(response.data) ? response.data.length : 0;
  const q = String(question || '').trim();
  if (response.answer_failed || (response.confidence === 'low' && !rows)) {
    return (
      <div className="chart-note answer-failed" role="status">
        <p>Could not get the figures for this question. Try again, or ask it in other words.</p>
        {onAsk && q && <div className="clarify-opts"><button type="button" className="clarify-opt" {...askProps(onAsk, q)}>Try again</button></div>}
      </div>
    );
  }
  if (rows || !q) return null;
  const low = q.toLowerCase();
  return (
    <div className="chart-note" role="status">
      <p>No records for this question.</p>
      {onAsk && (
        <div className="clarify-opts">
          {!low.includes('all financial years') && (
            <button type="button" className="clarify-opt" {...askProps(onAsk, `${stripEnd(q)} across all financial years`)}>For all financial years</button>
          )}
          {!low.includes('all of meghalaya') && (
            <button type="button" className="clarify-opt" {...askProps(onAsk, `${stripEnd(q)} for all of Meghalaya`)}>For all of Meghalaya</button>
          )}
        </div>
      )}
    </div>
  );
}
const stripEnd = (q) => { let t = String(q).trim(); while (t && '?.!'.includes(t[t.length - 1])) t = t.slice(0, -1); return t; };

function SchemePicker({ response, onAsk }) {
  const opts = ((response && response.scheme_options) || [])
    .map((o) => ({ q: String((o && o.question) || '').trim(), label: String((o && o.label) || '').trim() }))
    .filter((o) => o.q && o.label);
  if (!opts.length) return null;
  return (
    <div className="scheme-pick">
      <div className="scheme-pick-label">Focus on one scheme</div>
      <div className="scheme-pick-row">
        {opts.map((o, i) => <button key={i} className="scheme-chip" {...askProps(onAsk, o.q)}>{o.label}</button>)}
      </div>
    </div>
  );
}

// Clarifying question (#281): the question is the answer text above; under it,
// each possible reply is a tappable pill that asks the full question for the
// officer, so nothing is guessed. The pause rule is a debugging detail and
// shows only with the route badge.
// Design #11 "Plain card · Pill chips" (user, 2026-10-21): a divider, a
// "Choose a …" line that names what is being asked (scheme / financial year /
// district / place), a search box when the list is long enough to need one,
// then pills — the first few shown and a "+N more" pill for the rest. An
// "All …" reply (all years, all of Meghalaya) is the outlined pill at the end;
// the pill the officer tapped stays filled.
const SCHEME_NAMES = ['MGNREGA', 'PMAY-G', 'Focus Plus', 'CM Elevate', 'Focus Legacy', 'CM Elevate Legacy']
  // Longest name first, so "CM Elevate Legacy (…)" is not read as "CM Elevate".
  .sort((a, b) => b.length - a.length);
// F-1 (audit 2026-10-29): "MGNREGA vs PMAY-G" is a pair, not MGNREGA — shown in full
const schemeOf = (label) => (String(label).includes(' vs ') ? null : SCHEME_NAMES.find((n) => label === n || (label.startsWith(n) && !isAsciiLetterOrDigit(label[n.length]))) || null);
const isAsciiLetterOrDigit = (c) => typeof c === 'string' && c.length === 1
  && ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'));

// Replies the product no longer offers (removed 2026-10-18 at the user's
// request). Older turns replayed from the conversation store still carry them,
// so they are dropped here as well as at the backend.
const RETIRED_OPTIONS = ['compare across schemes'];
const isRetiredOption = (label) => RETIRED_OPTIONS.some((r) => label.toLowerCase().startsWith(r));

// What each kind of pause asks for. `search`: always show the search box
// ('auto' = only when the list is longer than `limit`). `limit`: pills shown
// before "+N more" (0 = all). `all`: the short label for its "All …" reply.
const CLARIFY_KINDS = {
  scheme: { head: 'Choose a scheme', search: 'Search schemes', always: true, limit: 8 },
  year: { head: 'Choose a financial year', limit: 0, all: 'All years' },
  district: { head: 'Choose a district', search: 'Search districts', always: true, limit: 8 },
  place: { head: 'Choose a place', search: 'Search places', limit: 8 },
  tranche: { head: 'Choose a tranche', limit: 0 },
  other: { head: 'Choose one to continue', search: 'Search options', limit: 10 },
};
// The backend's pause rule (ClarificationNeeded.rule) says what is asked; the
// labels decide when the rule is missing (older turns) or generic.
const RULE_KIND = {
  'scheme-not-specified': 'scheme', 'focus-scheme-ambiguous': 'scheme', 'cm-scheme-group-ambiguous': 'scheme',
  'cm-elevate-dataset': 'scheme', 'scheme-not-available': 'scheme', 'scheme-comparison-not-specified': 'scheme',
  'bank-scheme-not-specified': 'scheme',
  'year-not-specified': 'year', 'year-out-of-range': 'year',
  'scope-not-specified': 'district', 'region-needs-district': 'district',
  'entity-ambiguous': 'place', 'village-or-outside-place': 'place',
  'tranche-not-specified': 'tranche',
};
const isAllOption = (label) => label.toLowerCase().startsWith('all ');
const isYearLabel = (label) => label.startsWith('FY ');

function clarifyKind(rule, opts) {
  const named = opts.filter((o) => !isAllOption(o.label));
  if (named.length >= 2 && named.filter((o) => isYearLabel(o.label)).length >= named.length / 2) return 'year';
  if (named.filter((o) => schemeOf(o.label)).length >= 2) return 'scheme';
  return RULE_KIND[String(rule || '')] || 'other';
}

function Clarify({ response, onAsk }) {
  const c = response && response.clarification;
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [picked, setPicked] = useState(null);
  if (!c) return null;
  const opts = (Array.isArray(c.options) ? c.options : [])
    .map((o) => ({ q: String((o && o.question) || '').trim(), label: String((o && o.label) || '').trim() }))
    .filter((o) => o.q && o.label && !isRetiredOption(o.label));
  if (!opts.length && !(SHOW_ROUTE_BADGE && c.rule)) return null;
  const kind = clarifyKind(c.rule, opts);
  const cfg = CLARIFY_KINDS[kind];
  // The named replies first, the "All …" ones last (outlined).
  const named = opts.filter((o) => !isAllOption(o.label));
  const alls = opts.filter((o) => isAllOption(o.label));
  const showSearch = !!cfg.search && (cfg.always || (cfg.limit > 0 && named.length > cfg.limit));
  const needle = query.trim().toLowerCase();
  const matches = needle ? named.filter((o) => o.label.toLowerCase().includes(needle)) : named;
  const capped = !needle && !expanded && cfg.limit > 0 && matches.length > cfg.limit;
  const visible = capped ? matches.slice(0, cfg.limit) : matches;
  const ask = (o) => { setPicked(o.q); onAsk(o.q); };
  // A scheme pill shows the bare name; its "(rural housing)" note stays in the tooltip.
  const pill = (o, extra, label) => (
    <button key={o.q} type="button" title={kind === 'scheme' && schemeOf(o.label) ? o.label : o.q}
      className={'clarify-opt' + (extra ? ' ' + extra : '') + (picked === o.q ? ' picked' : '')}
      aria-pressed={picked === o.q}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); ask(o); }}>
      {label || (kind === 'scheme' && schemeOf(o.label)) || o.label}
    </button>
  );
  return (
    <div className={'clarify-box clarify-' + kind}>
      {opts.length > 0 && <div className="clarify-head">{cfg.head}</div>}
      {showSearch && (
        <label className="clarify-search">
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
            <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <input type="search" value={query} placeholder={cfg.search} aria-label={cfg.search}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation();
              // Enter on a search that leaves one pill picks it.
              if (e.key === 'Enter') { e.preventDefault(); if (matches.length === 1) ask(matches[0]); }
            }} />
        </label>
      )}
      {opts.length > 0 && (
        <div className="clarify-opts" role="group" aria-label={cfg.head}>
          {visible.map((o) => pill(o))}
          {needle && !matches.length && <span className="clarify-none">No match. Type it in the chat box instead.</span>}
          {capped && (
            <button type="button" className="clarify-opt clarify-all clarify-more"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(true); }}>
              +{matches.length - cfg.limit} more
            </button>
          )}
          {!needle && alls.map((o) => pill(o, 'clarify-all', alls.length === 1 && cfg.all ? cfg.all : null))}
        </div>
      )}
      {SHOW_ROUTE_BADGE && c.rule && <div className="clarify-rule">rule: {String(c.rule)}</div>}
    </div>
  );
}

function Suggestions({ response, onAsk }) {
  const list = ((response && response.suggestions) || []).map((s) => String(s || '').trim()).filter(Boolean);
  if (!list.length) return null;
  return (
    <div className="suggest-box">
      <div className="suggest-label">Try asking</div>
      {list.map((q, i) => <div key={i} className="suggest-item" {...askProps(onAsk, q)}>{q}</div>)}
    </div>
  );
}

function FollowUp({ response, onAsk }) {
  // An EDGE reply carries no follow-up, but may carry starter questions.
  if (!response || response.intent === 'EDGE') return <Suggestions response={response} onAsk={onAsk} />;
  // A clarification pause replaces the follow-up: the pending question IS the next step.
  if (response.intent === 'CLARIFY') return <Clarify response={response} onAsk={onAsk} />;
  const picker = <SchemePicker response={response} onAsk={onAsk} />;
  const suggestion = (response.follow_up || '').trim();
  if (!suggestion) return picker;

  // Preferred shape: [{label, question}]; older responses carry plain strings.
  const opts = (Array.isArray(response.follow_up_options) && response.follow_up_options.length)
    ? response.follow_up_options
    : ((Array.isArray(response.follow_ups) && response.follow_ups.length) ? response.follow_ups : [suggestion])
      .filter(Boolean).map((s) => ({ label: s, question: s }));
  const items = opts.filter((o) => o && (o.question || o.label));
  return (
    <>
      {picker}
      <div className="next-step-group">
        <div className="next-step-label">Next steps</div>
        {items.map((o, i) => (
          <div key={i} className="next-step-item" {...askProps(onAsk, o.question || o.label)}>
            <span className="next-step-arrow" aria-hidden="true">&rsaquo;</span>
            <span className="next-step-copy">{o.label || o.question}</span>
          </div>
        ))}
      </div>
    </>
  );
}

// ── Message actions (copy / edit / read aloud) ─────────────────────────────
const ICONS = {
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" /></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12" /></svg>,
  edit: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z" /></svg>,
  speak: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.5 8.5a5 5 0 010 7" /><path d="M19 5a10 10 0 010 14" /></svg>,
  stop: <svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>,
  more: <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>,
  regen: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36" /><polyline points="21 3 21 9 15 9" /></svg>,
  up: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M7 10v11H4a1 1 0 01-1-1v-9a1 1 0 011-1h3z" /><path d="M7 10l4-8a2.5 2.5 0 012.5 2.5V8h5.3a2 2 0 012 2.3l-1.2 8A2 2 0 0117.6 20H7" /></svg>,
  down: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 14V3h3a1 1 0 011 1v9a1 1 0 01-1 1h-3z" /><path d="M17 14l-4 8a2.5 2.5 0 01-2.5-2.5V16H5.2a2 2 0 01-2-2.3l1.2-8A2 2 0 016.4 4H17" /></svg>,
};

// ── 👍 / 👎 (RAG upgrade Phase 6) ──────────────────────────────────────────
// One vote per officer per answer: a click sets it, the same thumb again takes
// it back, the other thumb changes it. A 👎 also offers an optional "what was
// wrong?" note. The vote is remembered in this tab (sessionStorage) so a
// re-render keeps the highlighted thumb.
const FEEDBACK_REASONS = ['Wrong', 'Incomplete', 'Not what I asked', 'Out of date'];
const fbKey = (sessionId, id) => `megh_fb:${sessionId || ''}:${id}`;
function readVote(key) { try { return Number(sessionStorage.getItem(key)) || 0; } catch (e) { return 0; } }
function saveVote(key, v) { try { if (v) sessionStorage.setItem(key, String(v)); else sessionStorage.removeItem(key); } catch (e) { /* ignore */ } }

function FeedbackActions({ sessionId, question, response, answer }) {
  const id = answerKey(question, answer);
  const key = fbKey(sessionId, id);
  const [vote, setVote] = useState(() => readVote(key));
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState('');
  const [reason, setReason] = useState('');
  const [state, setState] = useState('');       // '' | 'sent' | 'error'
  const send = (rating, comment) => sendFeedbackApi({
    message_key: `${sessionId || 'nosession'}:${id}`, rating, question: question || '(no question)',
    answer: answer || '', session_id: sessionId || null, route: response.route || null,
    schemes: Array.isArray(response.schemes) ? response.schemes : [],
    citations: Array.isArray(response.citations) ? response.citations : [],
    comment: comment || null,
  });
  const choose = (rating) => {
    const next = vote === rating ? 0 : rating;
    const prev = vote;
    setVote(next); saveVote(key, next); setState('');
    setAsking(next === -1);
    send(next).catch(() => { setVote(prev); saveVote(key, prev); setAsking(false); setState('error'); });
  };
  const submitNote = () => {
    // K-37: the reason and the note together stay inside the server's 1,000 characters
    const comment = [reason, note.trim()].filter(Boolean).join(' — ').slice(0, 1000);
    setAsking(false);
    if (!comment) return;
    send(-1, comment).then(() => setState('sent')).catch(() => setState('error'));
  };
  return (
    <>
      <button type="button" className={'msg-act fb-up' + (vote === 1 ? ' on' : '')}
              title={vote === 1 ? 'You found this helpful (click to undo)' : 'Helpful'}
              aria-label="Helpful" aria-pressed={vote === 1}
              onClick={(e) => { e.stopPropagation(); choose(1); }}>{ICONS.up}</button>
      <button type="button" className={'msg-act fb-down' + (vote === -1 ? ' on' : '')}
              title={vote === -1 ? 'You marked this as not helpful (click to undo)' : 'Not helpful'}
              aria-label="Not helpful" aria-pressed={vote === -1}
              onClick={(e) => { e.stopPropagation(); choose(-1); }}>{ICONS.down}</button>
      {state === 'sent' && <span className="fb-thanks" role="status">Thanks — noted</span>}
      {state === 'error' && <span className="fb-thanks err" role="status">Couldn't save — try again</span>}
      {asking && <span className="fb-break" aria-hidden="true" />}
      {asking && (
        <div className="fb-box" role="group" aria-label="What was wrong?" onClick={(e) => e.stopPropagation()}>
          <div className="fb-q">What was wrong? <span className="fb-opt">(optional)</span></div>
          <div className="fb-reasons">
            {FEEDBACK_REASONS.map((r) => (
              <button key={r} type="button" className={'fb-reason' + (reason === r ? ' on' : '')}
                      aria-pressed={reason === r} onClick={() => setReason(reason === r ? '' : r)}>{r}</button>
            ))}
          </div>
          <textarea className="fb-note" rows={2} maxLength={1000} value={note} placeholder="Tell us more (optional)"
                    onChange={(e) => setNote(e.target.value)}
                    onKeyDown={(e) => { if (enterSends(e)) { e.preventDefault(); submitNote(); } }} />
          <div className="fb-btns">
            <button type="button" className="fb-skip" onClick={() => setAsking(false)}>Skip</button>
            <button type="button" className="fb-send" onClick={submitNote} disabled={!reason && !note.trim()}>Send</button>
          </div>
        </div>
      )}
    </>
  );
}

// "Source: PMAY-G FAQ › What documents…" under a knowledge answer (Phase 6).
function Citations({ response }) {
  const list = Array.isArray(response.citations) ? response.citations.filter((c) => c && c.title) : [];
  if (response.route !== 'knowledge' || !list.length) return null;
  return (
    <div className="ans-cite">
      <span className="src-lbl">{list.length > 1 ? 'Sources:' : 'Source:'}</span>
      {list.map((c, i) => (
        <span key={i} className="cite-item" title={c.section ? `${c.title} › ${c.section}` : c.title}>
          <span className="cite-doc">{c.title}</span>
          {c.section && <span className="cite-sec"> › {c.section}</span>}
        </span>
      ))}
    </div>
  );
}

function CopyAction({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className={'msg-act' + (done ? ' done' : '')} title={done ? 'Copied' : label} aria-label={label}
            onClick={(e) => { e.stopPropagation(); copyText(text, () => { setDone(true); setTimeout(() => setDone(false), 1500); }); }}>
      {done ? ICONS.check : ICONS.copy}
    </button>
  );
}

// Read an answer aloud with the browser's own speech engine (no server call).
function SpeakAction({ id, text, speakingId, onSpeak }) {
  if (!('speechSynthesis' in window) || !text) return null;
  const on = speakingId === id;
  return (
    <button type="button" className={'msg-act' + (on ? ' active' : '')} title={on ? 'Stop reading' : 'Read aloud'}
            aria-label={on ? 'Stop reading' : 'Read aloud'} onClick={(e) => { e.stopPropagation(); onSpeak(id, text); }}>
      {on ? ICONS.stop : ICONS.speak}
    </button>
  );
}

// The answer as plain text: what Copy and Read aloud use (no ** / # markers).
export const plainAnswer = plainText;

// ── Message shells ──────────────────────────────────────────────────────────
// A question the officer sent: Copy and Edit. Edit opens the text in place;
// sending it replaces this question (and what followed it) and asks it again.
function UserMessage({ text, time, onEdit, busy, editRequest = 0 }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  // ↑ in an empty question box (keyboard shortcut) opens the last question for editing.
  useEffect(() => {
    if (editRequest && !busy) { setDraft(text); setEditing(true); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editRequest]);
  const ref = useRef(null);
  useEffect(() => {
    if (!editing || !ref.current) return;
    const t = ref.current;
    t.focus();
    t.setSelectionRange(t.value.length, t.value.length);
  }, [editing]);
  useEffect(() => {
    if (!editing || !ref.current) return;
    ref.current.style.height = 'auto';
    ref.current.style.height = Math.min(ref.current.scrollHeight, 220) + 'px';
    ref.current.style.overflowY = ref.current.scrollHeight > 220 ? 'auto' : 'hidden';
  }, [draft, editing]);

  const cancel = () => { setEditing(false); setDraft(text); };
  const save = () => {
    const q = draft.trim();
    if (!q || busy) return;
    setEditing(false);
    onEdit(q);
  };

  return (
    <div className="msg user">
      <div className="av">U</div>
      <div>
        {editing ? (
          <div className="msg-edit">
            <textarea ref={ref} rows={1} value={draft} onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (enterSends(e)) { e.preventDefault(); save(); }
                        if (e.key === 'Escape') { e.stopPropagation(); cancel(); }
                      }} />
            <div className="msg-edit-bar">
              <button type="button" onClick={cancel}>Cancel</button>
              <button type="button" className="primary" onClick={save} disabled={!draft.trim() || busy}>Send</button>
            </div>
            <div className="msg-edit-note">Sending replaces this question and the answers after it.</div>
          </div>
        ) : (
          <div className="bubble"><RichText text={text} /></div>
        )}
        {!editing && (
          <div className="msg-foot">
            <div className="mtime">{time}</div>
            <div className="msg-actions">
              <CopyAction text={text} label="Copy question" />
              {onEdit && (
                <button type="button" className="msg-act" title={busy ? 'Wait for the current answer' : 'Edit question'}
                        aria-label="Edit question" disabled={busy}
                        onClick={(e) => { e.stopPropagation(); setDraft(text); setEditing(true); }}>
                  {ICONS.edit}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function TextMessage({ id, role, text, time, at, onEdit, busy, speakingId, onSpeak, onRetry, editRequest }) {
  if (role === 'user') return <UserMessage text={text} time={time} onEdit={onEdit} busy={busy} editRequest={editRequest} />;
  return (
    <div className="msg bot">
      <div className="av">M</div>
      <div>
        <div className="bubble"><RichText text={text} /></div>
        <div className="msg-foot">
          <div className="mtime">{time}</div>
          <div className="msg-actions">
            <CopyAction text={text} label="Copy answer" />
            {onSpeak && <SpeakAction id={id} text={text} speakingId={speakingId} onSpeak={onSpeak} />}
            {onRetry && <RegenerateAction onRegenerate={onRetry} label="Try again" />}
            <MoreAction at={at} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── An answer in flight ─────────────────────────────────────────────────────
// What the officer sees while waiting: the steps the pipeline has reached (from
// the LangGraph nodes as they start, /api/query/stream) and, once the composer
// writes, its text as it arrives. The draft is replaced by the checked answer.
const STEP_LABELS = {
  context: 'Understanding your question', edge: 'Understanding your question',
  followup: 'Understanding your question', rephrase: 'Understanding your question',
  route: 'Understanding your question',
  knowledge: 'Searching the scheme documents',
  data_context: 'Identifying the scheme', scope_scheme: 'Identifying the scheme',
  entities: 'Finding the district, block or village', clarification_gate: 'Finding the district, block or village',
  deterministic: 'Building the database query', sql_generate: 'Building the database query',
  authorize: 'Checking access',
  execute_attempt: 'Querying the database', repair: 'Fixing the query and retrying',
  post_rows: 'Reading the results',
  compose: 'Writing the answer',
  guarantees: 'Checking the figures', assemble: 'Checking the figures',
  finalize: 'Checking the figures', context_update: 'Checking the figures',
};

// Node names -> the distinct labels, in the order first reached.
export function stepTrail(nodes) {
  const out = [];
  for (const n of nodes || []) {
    const label = STEP_LABELS[n];
    if (label && out[out.length - 1] !== label) {
      const seen = out.indexOf(label);
      if (seen >= 0) out.splice(seen, 1);   // a repair loop returns to "Querying"
      out.push(label);
    }
  }
  return out;
}

// The status pill (#073): names the activity ("Thinking…", "Searching the scheme
// documents…") instead of showing dots, because a specific status is more
// reassuring than an anonymous wait. Before the first pipeline step it says
// "Thinking…"; then it follows the current step; while the draft is being
// written it says "Writing the answer…".
function StatusPill({ label }) {
  return (
    <div className="typing-bubble status-pill" role="status" aria-live="polite">
      <span className="pill-spark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c.6 4.8 3.2 8.4 10 10-6.8 1.6-9.4 5.2-10 10-.6-4.8-3.2-8.4-10-10 6.8-1.6 9.4-5.2 10-10z" /></svg>
      </span>
      <span className="pill-text">{label}…</span>
    </div>
  );
}

// Only the current step is shown (the pill); the steps already passed are not
// listed (removed at the user's request, 2026-10-19).
export function TypingMessage({ steps, draft, streamKey }) {
  const trail = stepTrail(steps);
  const [shownDraft] = useReveal(draft, streamKey);
  const current = draft ? 'Writing the answer' : (trail[trail.length - 1] || 'Thinking');
  return (
    <div className="msg bot">
      <div className="av">M</div>
      <div>
        <StatusPill label={current} />
        {draft && (
          <div className="bubble pending-bubble">
            <div className="answer-text md draft-text">
              <Markdown text={shownDraft} /><span className="draft-cursor" aria-hidden="true" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// "⋯" under an answer: a small menu with when it was given ("Today, 11:34 AM").
// Closes on a click outside it or Esc.
function MoreAction({ at }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); } };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey, true);
    return () => { document.removeEventListener('pointerdown', onDown); document.removeEventListener('keydown', onKey, true); };
  }, [open]);
  const stamp = fullStamp(at);
  if (!stamp) return null;
  return (
    <span className="msg-more" ref={ref}>
      <button type="button" className={'msg-act' + (open ? ' active' : '')} title="More" aria-label="More"
              aria-haspopup="true" aria-expanded={open} onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>
        {ICONS.more}
      </button>
      {open && (
        <div className="msg-menu" role="menu">
          <div className="msg-menu-stamp">{stamp}</div>
        </div>
      )}
    </span>
  );
}

function RegenerateAction({ onRegenerate, label = 'Regenerate answer' }) {
  return (
    <button type="button" className="msg-act" title={label} aria-label={label}
            onClick={(e) => { e.stopPropagation(); onRegenerate(); }}>
      {ICONS.regen}
    </button>
  );
}

export function BotMessage({ id, question, response, time, at, onAsk, speakingId, onSpeak, onRegenerate, animate, streamKey, sessionId, view }) {
  // A fresh answer is revealed word by word (reveal.js); the charts, SQL and
  // chips follow once the text is all there. A replayed one shows at once.
  const [shown, revealed] = useReveal(response.answer, streamKey, !!animate);
  // A cross-scheme comparison (app/cross_scheme.py) writes its per-scheme table
  // into the answer text; its rows are charted one measure per chart
  // (analytics.js crossSummaryCharts), never pivoted into a second table.
  const wantsAnalytics = response.intent !== 'EDGE'
    && Array.isArray(response.data) && response.data.length >= 1;
  // A CLARIFY pause fetched nothing, so a "0 results" meta line would mislead.
  const showMeta = response.intent && response.intent !== 'EDGE' && response.intent !== 'CLARIFY';
  const answer = plainAnswer(response.answer);
  return (
    <div className="msg bot">
      <div className="av">M</div>
      <div>
        <div className="bubble">
          <RouteBadge response={response} />
          {response.translated_from && response.rewritten_question && (
            // K-17 (audit 2026-10-29): a Khasi / Garo question is answered in English; say how it was read
            <div className="understood-as">Understood as: “{response.rewritten_question}”</div>
          )}
          <ScopeBanner response={response} />
          {response.answer && (
            <div className="answer-text md">
              <Markdown text={shown} />{!revealed && <span className="draft-cursor" aria-hidden="true" />}
            </div>
          )}
          {revealed && (
            <div className="answer-extras">
              <Citations response={response} />
              {wantsAnalytics && (
                // "give me a wide frame": the backend sets chart_wide, the charts are drawn taller
                <div className={response.chart_wide ? 'chart-wide' : undefined}>
                  <Analytics question={question} response={response} view={view} onAsk={onAsk} />
                </div>
              )}
              <AnswerState response={response} question={question} onAsk={onAsk} />
              <SqlDisclosure response={response} />
              <FollowUp response={response} onAsk={onAsk} />
              <ContinueOffer response={response} onAsk={onAsk} />
            </div>
          )}
        </div>
        <div className="msg-foot">
          <div className="mtime">
            {/* K-33: the result count only under a data answer */}
            {showMeta && response.route === 'data'
              ? `${time} · ${response.row_count || 0} result${response.row_count === 1 ? '' : 's'}${response.execution_time_ms ? ` · ${response.execution_time_ms}ms` : ''}`
              : time}
          </div>
          {answer && (
            <div className="msg-actions">
              <CopyAction text={Array.isArray(response.data) && response.data.length ? `${answer}\n\n${rowsAsTsv(response.data)}` : answer}
                          label="Copy answer" />
              {onSpeak && <SpeakAction id={id} text={answer} speakingId={speakingId} onSpeak={onSpeak} />}
              {onRegenerate && <RegenerateAction onRegenerate={onRegenerate} />}
              {response.intent !== 'EDGE' && response.intent !== 'CLARIFY' && (
                <FeedbackActions id={id} sessionId={sessionId} question={question} response={response} answer={answer} />
              )}
              <MoreAction at={at} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
