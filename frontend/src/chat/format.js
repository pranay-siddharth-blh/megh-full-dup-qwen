/* Small formatting helpers shared by the chat components. */

import { dropPrefixCI, replaceAllCI, splitSpaces } from './text.js';

export function nowTime() {
  return new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

// The time a message was asked / answered, for messages replayed from history.
// Today: "06:29 pm"; an earlier day also names the date: "06 Oct, 06:29 pm".
export function stampTime(date) {
  const d = date instanceof Date ? date : new Date(date);
  if (isNaN(d.getTime())) return nowTime();
  const time = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === new Date().toDateString()) return time;
  const yr = d.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' } : {};   // K-38
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', ...yr }) + ', ' + time;
}

// The full time of a message, for its "⋯" menu: "Today, 11:34 AM",
// "Yesterday, 4:10 PM", "Tue, 6 Oct, 4:10 PM" (with the year when not this year).
export function fullStamp(date) {
  const d = date instanceof Date ? date : new Date(date);
  if (!date || isNaN(d.getTime())) return '';
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  const today = new Date();
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return `Today, ${time}`;
  if (d.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;
  const weekday = d.toLocaleDateString('en-GB', { weekday: 'short' });
  const month = d.toLocaleDateString('en-GB', { month: 'short' });
  const year = d.getFullYear() !== today.getFullYear() ? ` ${d.getFullYear()}` : '';
  return `${weekday}, ${d.getDate()} ${month}${year}, ${time}`;
}

export function todayLabel() {
  return new Date().toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
}

export function histAgo(iso) {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + 'm ago';
  if (s < 86400) return Math.floor(s / 3600) + 'h ago';
  if (s < 604800) return Math.floor(s / 86400) + 'd ago';
  const d = new Date(iso);
  // K-38 (audit 2026-10-29): a chat from last year said "24 Sept" with no year
  const yr = d.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' } : {};
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', ...yr });
}

// Coarse bucket for the "Today / Yesterday / Earlier" separators.
export function histBucket(iso) {
  const d = new Date(iso);
  const now = new Date();
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = (day(now) - day(d)) / 86400000;
  if (diff <= 0) return 'Today';
  if (diff === 1) return 'Yesterday';
  if (diff <= 7) return 'Previous 7 days';
  return 'Earlier';
}

// Sidebar initials, e.g. "Ada Lovelace" -> "AL".
export function initialsFor(name, email) {
  const src = (name || '').trim();
  if (src) {
    const parts = splitSpaces(src);
    return ((parts[0][0] || '') + (parts.length > 1 ? parts[parts.length - 1][0] : (parts[0][1] || ''))).toUpperCase();
  }
  return (email || 'U').slice(0, 2).toUpperCase();
}

// "curated.fact_mgnrega_employment" -> "MGNREGA employment"
export function prettyName(s) {
  let t = dropPrefixCI(String(s || ''), 'curated.');
  // Applied in this order, any case, every occurrence.
  for (const [find, rep] of [['fact_mgnrega_', 'MGNREGA '], ['fact_pmay_', 'PMAY-G '], ['fact_focus_plus_', 'FOCUS+ '],
    ['v_focus_plus', 'FOCUS+ disbursements'], ['v_cm_elevate_disbursement', 'CM Elevate Legacy'],
    ['focus_plus', 'FOCUS+'],
    ['v_cmss', 'CMSS'], ['curated.v_cmss', 'CMSS']]) t = replaceAllCI(t, find, rep);
  t = dropPrefixCI(t, 'v_');
  t = replaceAllCI(t, 'mgnrega', 'MGNREGA');
  t = replaceAllCI(t, 'pmay', 'PMAY-G');
  return t.replaceAll('_', ' ').trim();
}

export const humanKey = (k) => String(k).replaceAll('_', ' ');

// K-4 (audit 2026-10-29): the key was a page counter, which differs between a live
// chat and the same chat reopened, so after a reload answer 3 showed answer 2's
// thumb and a vote overwrote answer 2's stored feedback. The key is the answer's
// own content (its question and text), the same however the chat was opened.
export function answerKey(question, answer) {
  let h = 0x811c9dc5;
  const s = `${question || ''}
${answer || ''}`;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
  return `a${h.toString(36)}${s.length.toString(36)}`;
}
