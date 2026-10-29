import { Fragment } from 'react';
import { figureSpans, inlineSpans, isDigit, isLineEnd, isSpace, runEnd, splitSpaces, unwrapSpans } from '../text.js';

/* Answer text as a small, safe subset of Markdown: headings, bullet and
   numbered lists (one level of nesting), simple tables, paragraphs with their
   line breaks, **bold** and `code`. Built as React elements only (never
   innerHTML), so nothing in a model's text can become markup.

   The words and numbers are never changed: a numbered item keeps the number
   the answer wrote (li value), so "1. 2. 5." stays exactly that.

   Knowledge answers arrive without "#" headings (app/rag.py strips them and
   the prompts forbid them), so a LABEL line also reads as a heading: a line
   that is all bold ("**Eligibility**"), or a short "Documents required:"
   right before a list. */

const hasLineEnd = (s) => Array.from(s).some(isLineEnd);
const isHash = (c) => c === '#';

// "## Title ##": up to 3 leading spaces, 1-6 '#', at least one space, the title,
// then optional closing '#'s and spaces. -> { level, text } or null.
function heading(line) {
  const lead = runEnd(line, 0, isSpace);
  if (lead > 3) return null;
  const hashEnd = runEnd(line, lead, isHash);
  const level = hashEnd - lead;
  if (level < 1 || level > 6) return null;
  const spaceEnd = runEnd(line, hashEnd, isSpace);
  if (spaceEnd === hashEnd) return null;
  // Where the closing run (spaces, '#'s, spaces) starts.
  let close = line.length;
  while (close > 0 && isSpace(line[close - 1])) close--;
  while (close > 0 && line[close - 1] === '#') close--;
  while (close > 0 && isSpace(line[close - 1])) close--;
  // The title is as short as possible and starts after as many spaces as possible.
  for (let start = spaceEnd; start > hashEnd; start--) {
    const end = Math.max(start + 1, close);
    if (end <= line.length && !hasLineEnd(line.slice(start, end))) return { level, text: line.slice(start, end) };
  }
  return null;
}

// "- item" / "* item" / "• item" -> { indent, text }; the text runs to the line's end.
function bulletItem(line) {
  const indent = runEnd(line, 0, isSpace);
  if (!['-', '*', '•'].includes(line[indent])) return null;
  const textStart = runEnd(line, indent + 1, isSpace);
  if (textStart === indent + 1 || hasLineEnd(line.slice(textStart))) return null;
  return { indent, text: line.slice(textStart) };
}

// "12. item" / "3) item" (1-3 digits) -> { indent, value, text }.
function numberedItem(line) {
  const indent = runEnd(line, 0, isSpace);
  const digitsEnd = runEnd(line, indent, isDigit);
  const nd = digitsEnd - indent;
  if (nd < 1 || nd > 3 || (line[digitsEnd] !== '.' && line[digitsEnd] !== ')')) return null;
  const textStart = runEnd(line, digitsEnd + 1, isSpace);
  if (textStart === digitsEnd + 1 || hasLineEnd(line.slice(textStart))) return null;
  return { indent, value: Number(line.slice(indent, digitsEnd)), text: line.slice(textStart) };
}

// A line that is all bold: "**Eligibility**" or "**Eligibility**:" -> the bold text.
function allBold(line) {
  const s = line.slice(runEnd(line, 0, isSpace));
  if (!s.startsWith('**')) return null;
  const star = s.indexOf('*', 2);
  if (star <= 2 || !s.startsWith('**', star)) return null;
  const rest = s.slice(star + 2).trim();
  return rest === '' || rest === ':' ? s.slice(2, star) : null;
}

// A short label line: a capital letter, at most 40 more characters (no . ! ? :),
// then ':' and nothing else. -> the label without the ':'.
function shortLabel(line) {
  const s = line.slice(runEnd(line, 0, isSpace));
  if (!(s[0] >= 'A' && s[0] <= 'Z')) return null;
  let k = 1;
  while (k < s.length && !'.!?:'.includes(s[k])) k++;
  if (s[k] !== ':' || k - 1 > 40 || s.slice(k + 1).trim() !== '') return null;
  return s.slice(0, k);
}

// A table's |---|:--:| separator row: cells of 2+ dashes, optionally ':'-ended.
function isTableSep(line) {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|')) t = t.slice(0, -1);
  return t.split('|').every((cell) => {
    let c = cell.trim();
    if (c.startsWith(':')) c = c.slice(1);
    if (c.endsWith(':')) c = c.slice(0, -1);
    return c.length >= 2 && runEnd(c, 0, (ch) => ch === '-') === c.length;
  });
}

const listItem = (line) => {
  const b = bulletItem(line);
  if (b) return { ordered: false, indent: b.indent, text: b.text };
  const n = numberedItem(line);
  if (n) return { ordered: true, indent: n.indent, value: n.value, text: n.text };
  return null;
};

// K-36 (audit 2026-10-29): a row with no closing pipe showed as raw text, and an
// escaped pipe ("\|") inside a cell split it and shifted the columns. The header
// still needs a leading pipe; a body row needs only an unescaped pipe somewhere.
const isTableRow = (line) => {
  const t = line.trim();
  return t.length >= 2 && t.startsWith('|') && !hasLineEnd(t.slice(1));
};
const isBodyRow = (line) => isTableRow(line) || (line.trim().length > 0 && splitCells(line.trim()).length > 1);
function splitCells(t) {
  const out = [];
  let cur = '';
  for (let k = 0; k < t.length; k++) {
    if (t[k] === '\\' && t[k + 1] === '|') { cur += '|'; k++; continue; }
    if (t[k] === '|') { out.push(cur); cur = ''; continue; }
    cur += t[k];
  }
  out.push(cur);
  return out;
}
const cells = (line) => {
  let t = line.trim();
  if (t.startsWith('|')) t = t.slice(1);
  if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
  return splitCells(t).map((c) => c.trim());
};
// Every body row has the header's number of cells: short rows are padded, extra
// cells are kept in the last one
const fitRow = (row, n) => (row.length >= n
  ? [...row.slice(0, n - 1), row.slice(n - 1).join(' | ')]
  : [...row, ...Array(n - row.length).fill('')]);
const normalizeNewlines = (s) => s.replaceAll('\r\n', '\n').replaceAll('\r', '\n');

function nextNonBlank(lines, i) {
  for (let j = i; j < lines.length; j++) if (lines[j].trim()) return lines[j];
  return '';
}

// Text -> blocks: {type:'h', level, text} | {type:'p', lines} | {type:'list', ordered, items}
// | {type:'table', head, rows}. Exported for tests.
export function parseBlocks(text) {
  const lines = normalizeNewlines(String(text || '')).split('\n');
  const blocks = [];
  let para = null;
  let list = null;
  const endPara = () => { if (para) { blocks.push({ type: 'p', lines: para }); para = null; } };
  const endList = () => { if (list) { blocks.push(list); list = null; } };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) {
      endPara();
      // A blank line between two items of the same list keeps the list going.
      const next = listItem(nextNonBlank(lines, i + 1));
      if (list && !(next && next.ordered === list.ordered)) endList();
      continue;
    }
    // Table: a header row followed by a |---| separator row.
    if (isTableRow(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      endPara(); endList();
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && isBodyRow(lines[i])) rows.push(fitRow(cells(lines[i++]), head.length));
      i--;
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    const h = heading(line);
    if (h) { endPara(); endList(); blocks.push({ type: 'h', level: h.level, text: h.text }); continue; }
    const item = listItem(line);
    if (item) {
      endPara();
      if (list && item.indent >= 2 && list.items.length) {
        // One level of nesting: an indented item belongs to the item above.
        const parent = list.items[list.items.length - 1];
        if (!parent.sub || parent.sub.ordered !== item.ordered) parent.sub = { type: 'list', ordered: item.ordered, items: [] };
        parent.sub.items.push({ text: item.text, value: item.value });
        continue;
      }
      if (list && list.ordered !== item.ordered) endList();
      if (!list) list = { type: 'list', ordered: item.ordered, items: [] };
      list.items.push({ text: item.text, value: item.value });
      continue;
    }
    // An indented line under a list item continues that item.
    const indent = runEnd(line, 0, isSpace);
    if (list && indent >= 2 && indent < line.length) {
      const last = list.items[list.items.length - 1];
      last.text += '\n' + line.trim();
      continue;
    }
    const nextIsList = !!listItem(nextNonBlank(lines, i + 1));
    const bold = allBold(line);
    const label = shortLabel(line);
    if ((bold !== null && bold.length <= 80) || (label !== null && nextIsList && splitSpaces(label).length <= 4)) {
      endPara(); endList();
      const title = bold !== null ? bold : label;
      blocks.push({ type: 'h', level: 0, text: title.endsWith(':') ? title.slice(0, -1) : title });
      continue;
    }
    endList();
    (para = para || []).push(line);
  }
  endPara(); endList();
  return blocks;
}

// Key figures (#265) in a run of plain text: each number the officer may be
// looking for becomes <strong class="fig">, so it is found at a glance. The
// characters are not changed; only the weight is.
function Figures({ text }) {
  const out = [];
  let last = 0;
  for (const f of figureSpans(text)) {
    if (f.start > last) out.push(text.slice(last, f.start));
    out.push(<strong key={f.start} className="fig">{text.slice(f.start, f.end)}</strong>);
    last = f.end;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.map((x, i) => <Fragment key={i}>{x}</Fragment>);
}

// **bold** and `code` inside one line; with `figures`, the key numbers in the
// plain text between them are bold too (never inside code or explicit bold).
function Inline({ text, figures = false }) {
  const out = [];
  let last = 0;
  const plain = (s) => (figures ? <Figures text={s} /> : s);
  for (const m of inlineSpans(text, { code: true })) {
    if (m.start > last) out.push(plain(text.slice(last, m.start)));
    out.push(m.code ? <code key={m.start}>{m.inner}</code> : <strong key={m.start}>{m.inner}</strong>);
    last = m.end;
  }
  if (last < text.length) out.push(plain(text.slice(last)));
  return out.map((x, i) => <Fragment key={i}>{x}</Fragment>);
}

function Lines({ lines, figures }) {
  return lines.map((l, i) => <Fragment key={i}>{i > 0 && <br />}<Inline text={l} figures={figures} /></Fragment>);
}

function List({ block, figures }) {
  const Tag = block.ordered ? 'ol' : 'ul';
  return (
    <Tag className={block.ordered ? 'md-ol' : 'md-ul'}>
      {block.items.map((it, i) => (
        <li key={i} value={block.ordered ? it.value : undefined}>
          <Lines lines={it.text.split('\n')} figures={figures} />
          {it.sub && <List block={it.sub} figures={figures} />}
        </li>
      ))}
    </Tag>
  );
}

// `figures` (default on): bold the key numbers in paragraphs and list items.
// Headings and table cells are left alone: a table is already all numbers.
export function Markdown({ text, figures = true }) {
  return parseBlocks(text).map((b, i) => {
    if (b.type === 'h') {
      // Inside a chat bubble every heading is a small section title.
      return <div key={i} className={'md-h' + (b.level === 1 ? ' md-h1' : '')} role="heading" aria-level={Math.min(Math.max(b.level, 3), 6)}><Inline text={b.text} /></div>;
    }
    if (b.type === 'list') return <List key={i} block={b} figures={figures} />;
    if (b.type === 'table') {
      return (
        <div key={i} className="md-table-wrap">
          <table className="md-table">
            <thead><tr>{b.head.map((c, j) => <th key={j}><Inline text={c} /></th>)}</tr></thead>
            <tbody>{b.rows.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}><Inline text={c} /></td>)}</tr>)}</tbody>
          </table>
        </div>
      );
    }
    return <p key={i} className="md-p"><Lines lines={b.lines} figures={figures} /></p>;
  });
}

// The answer as plain text for Copy and Read aloud: no ** / ` / # markers,
// list markers kept as "- " / "1. " so a pasted answer still reads as a list.
export function plainText(text) {
  let t = normalizeNewlines(String(text || ''));
  t = dropHeadingMarks(t);
  t = dashBullets(t);
  t = unwrapSpans(t, inlineSpans(t));
  t = unwrapSpans(t, inlineSpans(t, { bold: false, code: true }));
  return t.trim();
}

const isLineStart = (t, p) => p === 0 || isLineEnd(t[p - 1]);

// At each line start: up to 3 spaces, 1-6 '#' and the spaces after them go.
// (Spaces include line breaks, so a marker may swallow the blank lines after it.)
function dropHeadingMarks(t) {
  let out = '';
  let last = 0;
  let p = 0;
  while (p < t.length) {
    if (isLineStart(t, p)) {
      const lead = runEnd(t, p, isSpace);
      const hashEnd = runEnd(t, lead, isHash);
      const n = hashEnd - lead;
      const spaceEnd = runEnd(t, hashEnd, isSpace);
      if (lead - p <= 3 && n >= 1 && n <= 6 && spaceEnd > hashEnd) {
        out += t.slice(last, p);
        last = p = spaceEnd;
        continue;
      }
    }
    p++;
  }
  return out + t.slice(last);
}

// At each line start: a '*' or '•' bullet (and the spaces after it) becomes "- ",
// keeping the indent.
function dashBullets(t) {
  let out = '';
  let last = 0;
  let p = 0;
  while (p < t.length) {
    if (isLineStart(t, p)) {
      const lead = runEnd(t, p, isSpace);
      const spaceEnd = runEnd(t, lead + 1, isSpace);
      if ((t[lead] === '*' || t[lead] === '•') && spaceEnd > lead + 1) {
        out += t.slice(last, lead) + '- ';
        last = p = spaceEnd;
        continue;
      }
    }
    p++;
  }
  return out + t.slice(last);
}
