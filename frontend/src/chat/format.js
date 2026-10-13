/* Small formatting helpers shared by the chat components. */

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
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) + ', ' + time;
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
  return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
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
    const parts = src.split(/\s+/);
    return ((parts[0][0] || '') + (parts.length > 1 ? parts[parts.length - 1][0] : (parts[0][1] || ''))).toUpperCase();
  }
  return (email || 'U').slice(0, 2).toUpperCase();
}

// "curated.fact_mgnrega_employment" -> "MGNREGA employment"
export function prettyName(s) {
  return String(s || '')
    .replace(/^curated\./i, '')
    .replace(/fact_mgnrega_/gi, 'MGNREGA ')
    .replace(/fact_pmay_/gi, 'PMAY-G ')
    .replace(/fact_focus_plus_/gi, 'FOCUS+ ')
    .replace(/v_focus_plus/gi, 'FOCUS+ disbursements')
    .replace(/v_cm_elevate_disbursement/gi, 'CM Elevate Legacy')
    .replace(/focus_plus/gi, 'FOCUS+')
    .replace(/^v_/i, '')
    .replace(/mgnrega/gi, 'MGNREGA')
    .replace(/pmay/gi, 'PMAY-G')
    .replace(/_/g, ' ')
    .trim();
}

export const humanKey = (k) => String(k).replace(/_/g, ' ');
