/* Downloads for answers: a table as Excel (.xlsx) or CSV, a chart as PNG.

   No dependency: the .xlsx is a minimal Office Open XML workbook written here
   (one sheet, bold header, column widths, numbers as real numbers so Excel
   can sum them) inside a stored (uncompressed) zip. CSV carries a UTF-8 BOM so
   Excel opens ₹ and place names correctly. A chart PNG is drawn on white with
   its title above, so it pastes cleanly into a report. */

import { capitalizeWords, isDigit, isLowerAlnum, isPlainNumber, isSpace, replaceRuns } from './text.js';

// ── File names ──────────────────────────────────────────────────────────────

function stamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

export function fileName(title, ext) {
  const lower = String(title || 'megh-one')
    .toLowerCase();
  const slug = trimDashes(replaceRuns(lower, (c) => !isLowerAlnum(c), '-')).slice(0, 60) || 'megh-one';
  return `${slug}_${stamp()}.${ext}`;
}

export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); a.remove();
  // Safari and Firefox read the blob after click() returns; a big PDF on a slow
  // phone needs well over a second, so the URL is kept for a minute.
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

// ── Cells ───────────────────────────────────────────────────────────────────

// Leading / trailing '-' off a slug.
function trimDashes(s) {
  let a = 0;
  let b = s.length;
  while (a < b && s[a] === '-') a++;
  while (b > a && s[b - 1] === '-') b--;
  return s.slice(a, b);
}
// "12,000" / "1,71,107" / "131.54" -> a number; codes with a leading zero stay text.
function asNumber(v) {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  const unsigned = s.startsWith('-') ? s.slice(1) : s;
  if (!isPlainNumber(s, 2, 3) || (unsigned[0] === '0' && isDigit(unsigned[1]))) return null;
  const n = Number(s.replaceAll(',', ''));
  return Number.isFinite(n) ? n : null;
}
const cellText = (v) => (v === null || v === undefined ? '' : String(v));
export const headerLabel = (c) => capitalizeWords(String(c).replaceAll('_', ' '));

// ── CSV ─────────────────────────────────────────────────────────────────────

export function toCSV(header, rows) {
  const esc = (v) => {
    const s = cellText(v);
    const quote = ['"', ',', '\r', '\n'].some((ch) => s.includes(ch)) || isSpace(s[0]) || isSpace(s[s.length - 1]);
    return quote ? `"${s.replaceAll('"', '""')}"` : s;
  };
  const lines = [header.map(esc).join(','), ...rows.map((r) => r.map((v) => {
    const n = asNumber(v);
    return n !== null ? String(n) : esc(v);
  }).join(','))];
  return new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
}

// ── XLSX ────────────────────────────────────────────────────────────────────

// Control characters XML 1.0 forbids (all below U+0020 except tab, LF and CR) are dropped.
const xmlAllowed = (ch) => { const c = ch.charCodeAt(0); return c > 0x1f || c === 0x09 || c === 0x0a || c === 0x0d; };
const xmlEsc = (s) => Array.from(cellText(s)).filter(xmlAllowed).join('')
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

function colName(i) {
  let s = '';
  for (let n = i + 1; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s;
  return s;
}

function sheetXml(header, rows) {
  const all = [header, ...rows];
  const widths = header.map((_, c) => Math.min(60, Math.max(8, ...all.map((r) => cellText(r[c]).length + 2))));
  const cols = widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join('');
  const row = (r, ri, isHead) => `<row r="${ri + 1}">${r.map((v, ci) => {
    const ref = `${colName(ci)}${ri + 1}`;
    const n = isHead ? null : asNumber(v);
    if (n !== null) return `<c r="${ref}"${Number.isInteger(n) ? ' s="2"' : ' s="3"'}><v>${n}</v></c>`;
    // Long text (an answer) wraps in its cell; Excel holds at most 32,767 chars per cell.
    const text = cellText(v).slice(0, 32000);
    const style = isHead ? ' s="1"' : (text.length > 60 ? ' s="4"' : '');
    return `<c r="${ref}" t="inlineStr"${style}><is><t xml:space="preserve">${xmlEsc(text)}</t></is></c>`;
  }).join('')}</row>`;
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    + '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    + '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
    + `<cols>${cols}</cols><sheetData>${all.map((r, i) => row(r, i, i === 0)).join('')}</sheetData></worksheet>`;
}

const STYLES = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
  + '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
  + '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
  + '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
  + '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
  + '<fill><patternFill patternType="solid"><fgColor rgb="FF5C2D91"/><bgColor indexed="64"/></patternFill></fill></fills>'
  + '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
  + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
  + '<cellXfs count="5"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
  + '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
  + '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
  + '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
  + '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs>'
  + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';

export function toXLSX(sheetName, header, rows) {
  return toXLSXBook([{ name: sheetName, header, rows }]);
}

// Several sheets in one workbook: [{ name, header, rows }]. Sheet names are
// cleaned to Excel's rules (31 chars, no \ / ? * [ ] :) and made unique.
export function toXLSXBook(sheets) {
  const used = new Set();
  const names = sheets.map((sh, i) => {
    let base = Array.from(String(sh.name || `Sheet${i + 1}`)).map((ch) => ('\\/?*[]:'.includes(ch) ? ' ' : ch)).join('')
      .trim().slice(0, 31) || `Sheet${i + 1}`;
    let n = base, k = 2;
    while (used.has(n.toLowerCase())) { const suf = ` (${k++})`; n = base.slice(0, 31 - suf.length) + suf; }
    used.add(n.toLowerCase());
    return xmlEsc(n);
  });
  const N = sheets.length;
  const idx = [...Array(N).keys()];
  const files = [
    ['[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      + '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      + '<Default Extension="xml" ContentType="application/xml"/>'
      + '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
      + idx.map((i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('')
      + '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
      + '</Types>'],
    ['_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
      + '</Relationships>'],
    ['xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
      + `<sheets>${idx.map((i) => `<sheet name="${names[i]}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('')}</sheets></workbook>`],
    ['xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      + idx.map((i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('')
      + `<Relationship Id="rId${N + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>`
      + '</Relationships>'],
    ['xl/styles.xml', STYLES],
    ...idx.map((i) => [`xl/worksheets/sheet${i + 1}.xml`, sheetXml(sheets[i].header, sheets[i].rows)]),
  ];
  return new Blob([zipStore(files)], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}

// A zip with STORED entries (no compression): enough for a small workbook.
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(bytes) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
function zipStore(files) {
  const enc = new TextEncoder();
  const parts = [], central = [];
  let offset = 0;
  for (const [path, text] of files) {
    const name = enc.encode(path), data = enc.encode(text), crc = crc32(data);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
    local.setUint16(8, 0, true); local.setUint32(14, crc, true);
    local.setUint32(18, data.length, true); local.setUint32(22, data.length, true); local.setUint16(26, name.length, true);
    parts.push(new Uint8Array(local.buffer), name, data);
    const cen = new DataView(new ArrayBuffer(46));
    cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
    cen.setUint32(16, crc, true); cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
    cen.setUint16(28, name.length, true); cen.setUint32(42, offset, true);
    central.push(new Uint8Array(cen.buffer), name);
    offset += 30 + name.length + data.length;
  }
  const cenSize = central.reduce((s, a) => s + a.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
  end.setUint32(12, cenSize, true); end.setUint32(16, offset, true);
  return new Blob([...parts, ...central, new Uint8Array(end.buffer)]);
}

// ── Chart → PNG ─────────────────────────────────────────────────────────────

export function chartPNG(chart, title, subtitle) {
  if (!chart || !chart.canvas) return;
  const src = chart.canvas;
  const ratio = src.width / Math.max(1, src.clientWidth || src.width);
  const pad = Math.round(24 * ratio), head = Math.round((subtitle ? 56 : 40) * ratio);
  const out = document.createElement('canvas');
  out.width = src.width + pad * 2;
  out.height = src.height + head + pad * 2;
  const g = out.getContext('2d');
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, out.width, out.height);
  g.fillStyle = '#1A1626'; g.textBaseline = 'top';
  g.font = `700 ${Math.round(16 * ratio)}px Inter, Segoe UI, Arial, sans-serif`;
  // Title Case, as the card shows it (.chd-title is text-transform: capitalize)
  g.fillText(capitalizeWords(String(title || 'Chart')), pad, pad);
  if (subtitle) {
    g.fillStyle = '#6B6478';
    g.font = `500 ${Math.round(12 * ratio)}px Inter, Segoe UI, Arial, sans-serif`;
    g.fillText(subtitle, pad, pad + Math.round(22 * ratio));
  }
  g.drawImage(src, pad, pad + head);
  out.toBlob((b) => b && downloadBlob(b, fileName(title, 'png')), 'image/png');
}
