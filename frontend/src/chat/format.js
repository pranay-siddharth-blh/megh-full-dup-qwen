/* Small formatting helpers shared by the chat components. */

export function nowTime() {
  return new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
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
