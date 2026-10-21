import { useEffect, useRef, useState } from 'react';
import { plainText } from './Markdown.jsx';
import { downloadBlob, fileName, headerLabel, toXLSXBook } from '../exporters.js';
import { keyLabel } from '../shortcuts.js';

/* "Download chat": the whole conversation in one file, from the top bar.

   PDF   — the browser's own print-to-PDF with a print stylesheet (chat.css
           @media print): no sidebar, composer or buttons; every question,
           answer, chart and table, full length, one after another. This is
           the one way that keeps charts sharp and tables complete on every
           device without a PDF library.
   Excel — one workbook: a "Conversation" sheet (each question with its
           answer as plain text) and one sheet per answer that has a table
           ("Q2 table", ...), its rows exactly as returned. */

const textOf = (m) => {
  if (m.kind === 'rich') return plainText((m.response && (m.response.answer || m.response.question)) || '');
  return String(m.text || '');
};

function workbook(messages) {
  const convo = [];
  const tables = [];
  let q = 0, pendingQ = null;
  for (const m of messages) {
    if (m.kind === 'user') {
      q += 1;
      pendingQ = { n: q, time: m.time || '', text: m.text || '' };
      continue;
    }
    if (m.kind !== 'rich' && m.kind !== 'bot') continue;
    const asked = pendingQ || { n: ++q, time: '', text: m.question || '' };
    pendingQ = null;
    const data = m.kind === 'rich' && Array.isArray(m.response && m.response.data) ? m.response.data : [];
    const sheet = data.length ? `Q${asked.n} table` : '';
    convo.push([asked.n, asked.time, asked.text, textOf(m), data.length || '', sheet]);
    if (data.length) {
      const cols = Object.keys(data[0]);
      tables.push({ name: sheet, header: cols.map(headerLabel), rows: data.map((r) => cols.map((c) => r[c])) });
    }
  }
  if (pendingQ) convo.push([pendingQ.n, pendingQ.time, pendingQ.text, '(no answer)', '', '']);
  return [{ name: 'Conversation', header: ['#', 'Time', 'Question', 'Answer', 'Rows', 'Table sheet'], rows: convo },
    ...tables];
}

export function ChatExport({ messages, title, openSignal = 0 }) {
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  // Ctrl + Shift + D (keyboard shortcut) opens the menu and focuses its first item.
  useEffect(() => {
    if (!openSignal) return;
    setOpen(true);
    setTimeout(() => { const b = box.current && box.current.querySelector('.dl-menu button'); if (b) b.focus(); }, 30);
  }, [openSignal]);
  const has = messages.some((m) => m.kind === 'user' || m.kind === 'rich');
  useEffect(() => {
    if (!open) return undefined;
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); } };
    document.addEventListener('mousedown', away);
    document.addEventListener('touchstart', away, { passive: true });
    document.addEventListener('keydown', esc, true);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('touchstart', away);
      document.removeEventListener('keydown', esc, true);
    };
  }, [open]);
  if (!has) return null;

  const name = title || 'Megh One AI chat';
  const savePdf = () => {
    setOpen(false);
    // The PDF's default file name comes from the page title while printing.
    const before = document.title;
    document.title = fileName(name, 'pdf').slice(0, -'.pdf'.length);   // fileName always ends in .pdf
    const restore = () => { document.title = before; window.removeEventListener('afterprint', restore); };
    window.addEventListener('afterprint', restore);
    // Let the menu close and the charts settle at print width first.
    setTimeout(() => { window.print(); setTimeout(restore, 1000); }, 150);
  };
  const saveXlsx = () => {
    setOpen(false);
    downloadBlob(toXLSXBook(workbook(messages)), fileName(name, 'xlsx'));
  };

  return (
    <div className="dl-wrap chat-export" ref={box}>
      <button type="button" className="chat-export-btn" aria-haspopup="menu" aria-expanded={open}
              title={`Download this chat (${keyLabel('download')})`} aria-label="Download this chat" onClick={() => setOpen((o) => !o)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3v12" /><polyline points="7 10 12 15 17 10" /><path d="M5 21h14" />
        </svg>
        <span className="chat-export-label">Download chat</span>
      </button>
      {open && (
        <div className="dl-menu" role="menu">
          <button type="button" role="menuitem" onClick={savePdf}>PDF — whole chat with charts</button>
          <button type="button" role="menuitem" onClick={saveXlsx}>Excel — every table + conversation</button>
        </div>
      )}
    </div>
  );
}
