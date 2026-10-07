import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import { buildAnalytics } from '../analytics.js';
import { prettyName } from '../format.js';
import { DynTable, GroupedChart, PivotTable, RecordCard, StackedChart, SwitchableChart } from './Charts.jsx';

/* One chat message. A bot answer (`response` from /api/query) renders the same
   blocks as addBotRich() in web/ai_query.html: routing badge (off), answer text,
   analytics, the "SQL query used" disclosure, then the follow-up area (scheme
   picker, next steps and sources, a clarification, or starter suggestions). */

// Text with line breaks; a bot answer also turns **x** into bold.
function RichText({ text, bold }) {
  const lines = String(text || '').split('\n');
  return lines.map((line, i) => {
    const parts = bold ? line.split(/\*\*(.+?)\*\*/g) : [line];
    return (
      <Fragment key={i}>
        {i > 0 && <br />}
        {parts.map((p, j) => (j % 2 === 1 ? <strong key={j}>{p}</strong> : <Fragment key={j}>{p}</Fragment>))}
      </Fragment>
    );
  });
}

// ── Analytics ───────────────────────────────────────────────────────────────
function Analytics({ question, response }) {
  const a = useMemo(
    () => buildAnalytics(question, response.data, response.chart_type),
    [question, response],
  );
  if (!a) return null;
  if (a.kind === 'kpi') {
    return (
      <div className="analytics">
        <div className="dyn-grid single">
          <SwitchableChart title="Summary" labels={a.labels} values={a.values} types={['bar', 'doughnut']} initial="bar" />
        </div>
        <RecordCard row={a.row} />
      </div>
    );
  }
  if (a.kind === 'record') return <div className="analytics"><RecordCard row={a.row} /></div>;
  if (a.kind === 'table') return <div className="analytics"><DynTable data={a.data} /></div>;
  if (a.kind === 'grouped') {
    return (
      <div className="analytics">
        <div className="dyn-grid single"><GroupedChart title={a.title} labels={a.labels} datasets={a.datasets} /></div>
        <DynTable data={a.data} />
      </div>
    );
  }
  if (a.kind === 'stacked') {
    return (
      <div className="analytics">
        <div className="dyn-grid single"><StackedChart title={a.title} labels={a.labels} datasets={a.datasets} /></div>
        <PivotTable data={a.data} xKey={a.xKey} sKey={a.sKey} vKey={a.vKey} />
      </div>
    );
  }
  const single = a.charts.length === 1;
  return (
    <div className="analytics">
      <div className={'dyn-grid' + (single ? ' single' : '')}>
        {a.charts.map((c, i) => (
          <SwitchableChart key={i} title={c.title} labels={c.labels} values={c.values}
                           types={['bar', 'doughnut', 'line']} initial={a.defType} />
        ))}
      </div>
      <DynTable data={a.data} />
    </div>
  );
}

// ── Routing badge (developer detail; off, as in the original) ───────────────
const SHOW_ROUTE_BADGE = false;

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
        {a && a.query_type && <span className="rt-type">{String(a.query_type).replace(/_/g, ' ')}</span>}
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
const askProps = (onAsk, q) => ({
  style: { cursor: 'pointer' },
  onClick: (e) => { e.preventDefault(); e.stopPropagation(); onAsk(q); },
});

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

function Clarify({ response, onAsk }) {
  const c = response && response.clarification;
  if (!c) return null;
  const opts = (Array.isArray(c.options) ? c.options : [])
    .map((o) => ({ q: String((o && o.question) || '').trim(), label: String((o && o.label) || '').trim() }))
    .filter((o) => o.q && o.label);
  return (
    <div className="clarify-box">
      <div className="clarify-lbl">I need one detail first</div>
      {opts.length > 0 && (
        <div className="clarify-opts">
          {opts.map((o, i) => <button key={i} className="clarify-opt" {...askProps(onAsk, o.q)}>{o.label}</button>)}
        </div>
      )}
      {c.rule && <div className="clarify-rule">rule: {String(c.rule)}</div>}
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

function sourcesOf(sql) {
  let tableChip = '';
  const tableMatches = [...String(sql || '').matchAll(/(?:from|join)\s+["']?([a-z0-9_.]+)["']?/gi)];
  if (tableMatches.length) {
    const seen = [];
    for (const m of tableMatches) {
      // "IS DISTINCT FROM TRUE" is not a table.
      if (/^(true|false|null)$/i.test(m[1])) continue;
      const pretty = prettyName(m[1].replace(/["']/g, '').split('.').pop());
      if (pretty && !seen.includes(pretty)) seen.push(pretty);
    }
    const schemes = seen.filter((n) => ['FOCUS+', 'Focus', 'CM Elevate', 'CM Elevate Legacy'].includes(n));
    tableChip = (schemes.length ? schemes : seen).join(', ');
  }
  const groupMatch = String(sql || '').match(/group\s+by\s+([a-z0-9_.,\s"]+?)(?:order\s+by|limit|having|$)/i);
  const groupChip = groupMatch ? 'GROUP BY ' + groupMatch[1].replace(/["']/g, '').trim().split(/\s+/)[0].split('.').pop() : '';
  return { tableChip, groupChip };
}

function FollowUp({ response, onAsk }) {
  // An EDGE reply carries no follow-up, but may carry starter questions.
  if (!response || response.intent === 'EDGE') return <Suggestions response={response} onAsk={onAsk} />;
  // A clarification pause replaces the follow-up: the pending question IS the next step.
  if (response.intent === 'CLARIFY') return <Clarify response={response} onAsk={onAsk} />;
  const picker = <SchemePicker response={response} onAsk={onAsk} />;
  const suggestion = (response.follow_up || '').trim();
  if (!suggestion) return picker;

  const { tableChip, groupChip } = sourcesOf(response.sql_query || '');
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
      {(tableChip || groupChip) && (
        <div className="ans-sources">
          <span className="src-lbl">Sources:</span>
          {tableChip && <span className="src-chip">{tableChip}</span>}
          {groupChip && <span className="src-chip">{groupChip}</span>}
        </div>
      )}
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
};

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

// The answer as plain text: what Copy and Read aloud use (no ** markers).
export const plainAnswer = (text) => String(text || '').replace(/\*\*(.+?)\*\*/g, '$1').trim();

// ── Message shells ──────────────────────────────────────────────────────────
// A question the officer sent: Copy and Edit. Edit opens the text in place;
// sending it replaces this question (and what followed it) and asks it again.
function UserMessage({ text, time, onEdit, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
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
                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); save(); }
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

export function TextMessage({ id, role, text, time, onEdit, busy, speakingId, onSpeak }) {
  if (role === 'user') return <UserMessage text={text} time={time} onEdit={onEdit} busy={busy} />;
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
          </div>
        </div>
      </div>
    </div>
  );
}

export function TypingMessage() {
  return (
    <div className="msg bot">
      <div className="av">M</div>
      <div>
        <div className="bubble typing-bubble">
          <span className="dot" /><span className="dot" /><span className="dot" />
        </div>
      </div>
    </div>
  );
}

export function BotMessage({ id, question, response, time, onAsk, speakingId, onSpeak }) {
  const wantsAnalytics = response.intent !== 'EDGE' && Array.isArray(response.data) && response.data.length >= 1;
  // A CLARIFY pause fetched nothing, so a "0 results" meta line would mislead.
  const showMeta = response.intent && response.intent !== 'EDGE' && response.intent !== 'CLARIFY';
  const answer = plainAnswer(response.answer);
  return (
    <div className="msg bot">
      <div className="av">M</div>
      <div>
        <div className="bubble">
          <RouteBadge response={response} />
          {response.answer && <div className="answer-text"><RichText text={response.answer} bold /></div>}
          {wantsAnalytics && <Analytics question={question} response={response} />}
          <SqlDisclosure response={response} />
          <FollowUp response={response} onAsk={onAsk} />
        </div>
        <div className="msg-foot">
          <div className="mtime">
            {showMeta
              ? `${time} · ${response.row_count || 0} result${response.row_count === 1 ? '' : 's'} · ${response.execution_time_ms || 0}ms`
              : time}
          </div>
          {answer && (
            <div className="msg-actions">
              <CopyAction text={answer} label="Copy answer" />
              {onSpeak && <SpeakAction id={id} text={answer} speakingId={speakingId} onSpeak={onSpeak} />}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
