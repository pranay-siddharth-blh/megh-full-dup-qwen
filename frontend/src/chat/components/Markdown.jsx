import { Fragment } from 'react';

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

const HEADING = /^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/;
const BULLET = /^(\s*)[-*•]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const ALL_BOLD = /^\s*\*\*([^*]+?)\*\*\s*:?\s*$/;
const SHORT_LABEL = /^\s*([A-Z][^.!?:]{0,40}):\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

const listItem = (line) => {
  let m = BULLET.exec(line);
  if (m) return { ordered: false, indent: m[1].length, text: m[2] };
  m = NUMBERED.exec(line);
  if (m) return { ordered: true, indent: m[1].length, value: Number(m[2]), text: m[3] };
  return null;
};

const isTableRow = (line) => /^\s*\|.*\|\s*$/.test(line);
const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

function nextNonBlank(lines, i) {
  for (let j = i; j < lines.length; j++) if (lines[j].trim()) return lines[j];
  return '';
}

// Text -> blocks: {type:'h', level, text} | {type:'p', lines} | {type:'list', ordered, items}
// | {type:'table', head, rows}. Exported for tests.
export function parseBlocks(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
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
    if (isTableRow(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      endPara(); endList();
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]));
      i--;
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    const h = HEADING.exec(line);
    if (h) { endPara(); endList(); blocks.push({ type: 'h', level: h[1].length, text: h[2] }); continue; }
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
    if (list && /^\s{2,}\S/.test(line)) {
      const last = list.items[list.items.length - 1];
      last.text += '\n' + line.trim();
      continue;
    }
    const nextIsList = !!listItem(nextNonBlank(lines, i + 1));
    const bold = ALL_BOLD.exec(line);
    const label = SHORT_LABEL.exec(line);
    if ((bold && bold[1].length <= 80) || (label && nextIsList && label[1].split(/\s+/).length <= 4)) {
      endPara(); endList();
      blocks.push({ type: 'h', level: 0, text: (bold ? bold[1] : label[1]).replace(/:$/, '') });
      continue;
    }
    endList();
    (para = para || []).push(line);
  }
  endPara(); endList();
  return blocks;
}

// **bold** and `code` inside one line.
function Inline({ text }) {
  const out = [];
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(m[1] != null ? <strong key={m.index}>{m[1]}</strong> : <code key={m.index}>{m[2]}</code>);
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.map((x, i) => <Fragment key={i}>{x}</Fragment>);
}

function Lines({ lines }) {
  return lines.map((l, i) => <Fragment key={i}>{i > 0 && <br />}<Inline text={l} /></Fragment>);
}

function List({ block }) {
  const Tag = block.ordered ? 'ol' : 'ul';
  return (
    <Tag className={block.ordered ? 'md-ol' : 'md-ul'}>
      {block.items.map((it, i) => (
        <li key={i} value={block.ordered ? it.value : undefined}>
          <Lines lines={it.text.split('\n')} />
          {it.sub && <List block={it.sub} />}
        </li>
      ))}
    </Tag>
  );
}

export function Markdown({ text }) {
  return parseBlocks(text).map((b, i) => {
    if (b.type === 'h') {
      // Inside a chat bubble every heading is a small section title.
      return <div key={i} className={'md-h' + (b.level === 1 ? ' md-h1' : '')} role="heading" aria-level={Math.min(Math.max(b.level, 3), 6)}><Inline text={b.text} /></div>;
    }
    if (b.type === 'list') return <List key={i} block={b} />;
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
    return <p key={i} className="md-p"><Lines lines={b.lines} /></p>;
  });
}

// The answer as plain text for Copy and Read aloud: no ** / ` / # markers,
// list markers kept as "- " / "1. " so a pasted answer still reads as a list.
export function plainText(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^(\s*)[*•]\s+/gm, '$1- ')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .trim();
}
