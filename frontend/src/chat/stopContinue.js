/* "stop" while an answer runs, "continue" right after a stop (user request
   2026-10-18). The same words as the server's app/conversation_layer.py
   (_STOP_ASK / _CONTINUE_ASK), which also answers "continue" after a reload.
   Plain string methods only — no regular expressions (D-047). */

const POLITE = new Set(['ok', 'okay', 'yes', 'yeah', 'yep', 'sure', 'please', 'pls', 'plz', 'now', 'so', 'then', 'haan', 'ha']);
const STOP_HEAD = new Set(['stop', 'cancel', 'abort', 'halt', 'ruko', 'band']);
const STOP_TAIL = new Set(['it', 'this', 'that', 'now', 'please', 'pls', 'karo']);
// K-23 (audit 2026-10-29): "stop the query", "cancel the question", "रुको" did nothing
const STOP_OBJECT = new Set(['query', 'question', 'answer', 'request', 'search', 'answering', 'searching']);
const STOP_NATIVE = ['रुको', 'रुकिए', 'रोको', 'बंद करो', 'बस करो'];
const CONTINUE_PHRASES = [
  ['continue'], ['resume'], ['proceed'], ['contiue'], ['contnue'], ['continu'],
  ['go', 'on'], ['go', 'ahead'], ['carry', 'on'], ['keep', 'going'],
];
const CONTINUE_TAIL = new Set(['with', 'from', 'the', 'my', 'that', 'previous', 'last', 'stopped', 'earlier', 'same',
  'old', 'query', 'question', 'answer', 'one', 'request', 'search', 'where', 'you', 'left', 'off']);

const isWordCh = (c) => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');

// Lower-cased words, punctuation dropped.
function words(text) {
  const out = [];
  let cur = '';
  for (const c of String(text || '').toLowerCase()) {
    if (isWordCh(c)) cur += c;
    else if (cur) { out.push(cur); cur = ''; }
  }
  if (cur) out.push(cur);
  return out;
}

function trimPolite(ws) {
  let a = 0;
  let b = ws.length;
  while (a < b && POLITE.has(ws[a])) a += 1;
  while (b > a && POLITE.has(ws[b - 1])) b -= 1;
  return ws.slice(a, b);
}

export function isStopText(text) {
  const raw = String(text || '').trim().replaceAll('।', '').replaceAll('!', '').trim();
  if (STOP_NATIVE.includes(raw)) return true;
  const ws = trimPolite(words(text));
  if (ws.length >= 1 && ws.length <= 2 && STOP_HEAD.has(ws[0]) && (ws.length === 1 || STOP_TAIL.has(ws[1]))) return true;
  // "stop the query", "cancel this question", "stop answering"
  const rest = ws.slice(1).filter((w) => !['the', 'this', 'that', 'my'].includes(w));
  return ws.length >= 2 && ws.length <= 4 && STOP_HEAD.has(ws[0]) && rest.length === 1 && STOP_OBJECT.has(rest[0]);
}

export function isContinueText(text) {
  const ws = trimPolite(words(text));
  for (const p of CONTINUE_PHRASES) {
    if (ws.length >= p.length && p.every((w, i) => ws[i] === w)) {
      return ws.slice(p.length).every((w) => CONTINUE_TAIL.has(w)) && ws.length - p.length <= 6;
    }
  }
  return false;
}
