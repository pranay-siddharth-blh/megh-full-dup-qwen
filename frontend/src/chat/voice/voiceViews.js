/* Chart switches by voice and the explaining breakdown (2026-11-11). Pure, string functions only (no regex,
   D-046 / D-047).

   The voice engine's question shaper turns a spoken chart switch into exactly one of seven sentences (CANONICAL). Such a
   sentence asks for nothing new: the picture of the answer on screen is drawn another way, at once, with no pipeline
   round trip. bar / line / pie / table go through the chat's own redraw (App.jsx viewOnlyRequest: the chat shows the
   redraw too); map / ranking / horizontal exist only on the voice stage (VoiceStage.jsx re-plans the answer with that
   view). Either way the planner (vizPlan.plan(response, question, view)) says which view the data allowed, and the
   voice says it in one short line (viewSpeech): "Here it is on the map, sir." / "This one isn't by district, so it
   can't go on the map. Here it is as a ranking instead."

   A single figure gets the breakdown that explains it (explainAsk): the same question by district, or, when a place is
   named, by financial year, asked in a throwaway session so the officer's conversation is never touched. */
import { DISTRICTS, norm } from './vizPlan.js';

/** The seven sentences of the shaper -> the view they ask for. */
export const CANONICAL = {
  'show it as a bar chart': 'bar',
  'show it as a line chart': 'line',
  'show it as a pie chart': 'pie',
  'show it as a table': 'table',
  'show it on the map': 'map',
  'show it as a ranking': 'ranking',
  'show it as horizontal bars': 'horizontal',
};
/** Views the chat can redraw (App.jsx viewOnlyRequest); the others are drawn on the voice stage only. */
export const CHAT_VIEWS = ['bar', 'line', 'pie', 'table'];

/** The view a sentence asks for when it is EXACTLY one of the seven (case, spaces and closing punctuation ignored). */
export function canonicalView(question) {
  let s = String(question || '').toLowerCase().trim();
  while (s && '.!?,;:'.includes(s[s.length - 1])) s = s.slice(0, -1).trim();
  s = s.split(' ').filter((w) => w.length > 0).join(' ');
  return Object.prototype.hasOwnProperty.call(CANONICAL, s) ? CANONICAL[s] : null;
}

// what each kind is called when it is said
const SAY_KIND = { bars: 'a bar chart', line: 'a line chart', donut: 'a pie chart', table: 'a table', map: 'the map', race: 'a ranking' };
const SAY_VIEW = { bar: 'a bar chart', bars: 'a bar chart', line: 'a line chart', pie: 'a pie chart', doughnut: 'a donut chart',
  donut: 'a pie chart', table: 'a table', map: 'the map', ranking: 'a ranking', race: 'a ranking', horizontal: 'horizontal bars',
  stacked: 'a stacked bar chart', chart: 'a chart' };
const REASON = {
  'not-district': "This one isn't by district, so it can't go on the map.",
  'not-time': "This one isn't over time, so a line wouldn't fit.",
  'not-parts': "These figures aren't parts of one whole, so a pie would mislead.",
  'too-many': 'There are too many parts for a pie.',
  series: 'This one is several lines over the years, so it stays a line chart.',
};
export const NO_PICTURE = "There's no chart on screen yet, sir. Ask me for one first.";

/* Navigation by voice (2026-11-11; Mitra's go_to / NAV_BACK / NAV_CHART). The engine's shaper turns "take me back to the
   dashboard", "close the chart", "go home", "bring the chart back", ... into exactly one of these sentences. It is
   never a question for the pipeline (it answered "I don't have information about that"): the stage acts and the
   voice says one short line. */
export const NAV = { 'go back to the dashboard': 'desk', 'bring the chart back': 'chart' };
export const NAV_SPEECH = {
  desk: "Here's the dashboard, sir.",
  already: "You're on the dashboard, sir.",
  chart: "Here's the chart again, sir.",
  nochart: "There's no chart to bring back yet, sir. Ask me for one first.",
};

/* Any wording of a navigation command (2026-11-15, user report: "Take me back to the dashboard." went to the chat
   pipeline, which answered "I can't apply, book, pay or contact anyone for you"; on Gemini Live there is no shaper to
   turn the words into one of NAV). A sentence is navigation only when EVERY word is in this closed vocabulary and it
   names where to go, so "dashboard of MGNREGA expenditure" or "show me PMAY-G houses by district" stay questions.
   The server reads the same vocabulary (app/ui_commands.py nav_command); keep the two in step. */
const NAV_FILLER = new Set(('please kindly can could would will you me us i we want wanna need to just ok okay now sir madam '
  + 'hey megh one ai let lets go take get bring put the a my our this that it show open return navigate display view see '
  + 'head jump switch over on onto up all way right away quickly instead there').split(' '));
const NAV_DESK = new Set(['dashboard', 'dashboards', 'desk', 'home', 'homepage', 'overview']);
const NAV_SCREEN = new Set(['screen', 'page', 'view']);
const NAV_MAIN = new Set(['main', 'front', 'start', 'first', 'landing']);
const NAV_CHART = new Set(['chart', 'charts', 'graph', 'graphs', 'picture', 'visual', 'visualisation', 'visualization', 'plot']);
const NAV_AGAIN = new Set(['back', 'again', 'previous', 'last', 'earlier']);
const NAV_CLOSE = new Set(['close', 'hide', 'exit', 'dismiss', 'remove', 'leave']);
const inNavVocab = (w) => NAV_FILLER.has(w) || NAV_DESK.has(w) || NAV_SCREEN.has(w) || NAV_MAIN.has(w)
  || NAV_CHART.has(w) || NAV_AGAIN.has(w) || NAV_CLOSE.has(w);

function navWords(text) {
  const low = String(text || '').toLowerCase().split('’').join('').split("'").join('');
  return Array.from(low).map((ch) => (ch >= 'a' && ch <= 'z' ? ch : ' ')).join('').split(' ').filter((w) => w.length > 0);
}

/** 'desk' | 'chart' when the whole sentence is a navigation command (one of NAV exactly, or any wording of one), else
    null. */
export function canonicalNav(question) {
  const raw = String(question || '');
  let s = raw.toLowerCase().trim();
  while (s && '.!?,;:'.includes(s[s.length - 1])) s = s.slice(0, -1).trim();
  s = s.split(' ').filter((w) => w.length > 0).join(' ');
  if (Object.prototype.hasOwnProperty.call(NAV, s)) return NAV[s];
  if (!raw.trim() || raw.length > 120 || Array.from(raw).some((c) => c >= '0' && c <= '9')) return null;
  const ws = navWords(raw);
  if (!ws.length || ws.length > 14 || !ws.every(inNavVocab)) return null;
  const has = (set) => ws.some((w) => set.has(w));
  if (has(NAV_CLOSE)) return has(NAV_CHART) || has(NAV_DESK) ? 'desk' : null;
  if (has(NAV_CHART)) return has(NAV_AGAIN) ? 'chart' : null;
  if (has(NAV_DESK)) return 'desk';
  if (has(NAV_MAIN) && has(NAV_SCREEN)) return 'desk';
  if (ws.includes('back') && ws.every((w) => w === 'back' || NAV_FILLER.has(w)) && !has(NAV_SCREEN)) return 'desk';
  return null;
}

const here = (kind, view) => {
  if (kind === 'map') return 'Here it is on the map, sir.';
  if (kind === 'race' && view === 'horizontal') return 'Here it is as horizontal bars.';
  return `Here it is as ${SAY_KIND[kind] || SAY_VIEW[view] || 'a chart'}.`;
};

/** The line the voice says for a switch to `view`, from the planner's `applied` ({ asked, want, drawn, reason }). */
export function viewSpeech(view, applied) {
  const v = String(view || '').toLowerCase();
  const named = SAY_VIEW[v] || 'that';
  if (!applied) return v === 'table' ? 'Here it is as a table.' : `This answer has no figures to draw as ${named}, sir.`;
  const { want, drawn, reason } = applied;
  if (drawn && drawn === want) return here(drawn, v);
  if (drawn) {
    const why = REASON[reason] || `This one can't be drawn as ${named}.`;
    const instead = drawn === 'map' ? 'Here it is on the map instead.' : `Here it is as ${SAY_KIND[drawn] || 'a chart'} instead.`;
    return `${why} ${instead}`;
  }
  if (reason === 'single') return `This answer is a single figure, so there's nothing to draw as ${named}, sir.`;
  return REASON[reason] || `This one can't be drawn as ${named}, sir.`;
}

// the chip under the stage title after a switch: what is drawn, and why it is not what was asked when the data did not
// allow it
const CHIP_KIND = { bars: 'Bar chart', line: 'Line chart', donut: 'Pie chart', table: 'Table', map: 'On the map', race: 'Ranking' };
const CHIP_VIEW = { bar: 'Bar chart', line: 'Line chart', pie: 'Pie chart', doughnut: 'Donut chart', table: 'Table', map: 'Map',
  ranking: 'Ranking', horizontal: 'Horizontal bars', stacked: 'Stacked bars' };
const CHIP_WHY = { 'not-district': 'Not by district', 'not-time': 'Not over time', 'not-parts': 'Not parts of one whole',
  'too-many': 'Too many parts for a pie', series: 'Several lines over the years', single: 'A single figure' };
export function viewChip(view, applied) {
  const v = String(view || '').toLowerCase();
  if (!applied || !applied.drawn) {
    return { title: `${CHIP_VIEW[v] || 'That view'} · not possible`, sub: CHIP_WHY[(applied || {}).reason] || 'Nothing to draw' };
  }
  const title = applied.drawn === 'race' && v === 'horizontal' ? 'Horizontal bars' : CHIP_KIND[applied.drawn] || 'Chart';
  if (applied.drawn === applied.want) return { title, sub: '' };
  return { title, sub: `${CHIP_VIEW[v] || 'That view'}: ${(CHIP_WHY[applied.reason] || 'not possible').toLowerCase()}` };
}

/** The chat's redraw note ("Here is the same data as a bar chart. (Drawn here from ...)") is the chat's, not the voice's. */
export const isRedraw = (m) => !!m && m.kind === 'rich' && !!m.local && !!m.view;

// ── the explaining breakdown ───────────────────────────────────────────────
const PLACE_WORDS = ['block', 'blocks', 'constituency', 'constituencies', 'village', 'villages', 'gp', 'panchayat', 'district',
  'ekh', 'wgh', 'egh', 'wkh', 'ribhoi', 'shillong', 'tura', 'jowai', 'nongpoh'];
const YEAR_WORDS = ['fy', 'year', 'years', 'yearly', 'month', 'months', 'monthly', 'annual', 'quarter', 'today', 'since'];
const PLACE_COLS = ['district', 'block', 'village', 'constituency', 'panchayat', 'gp'];
const PERIOD_COLS = ['year', 'fy', 'month', 'period', 'quarter', 'date'];
const colParts = (c) => String(c).toLowerCase().split('').map((ch) => ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') ? ch : ' ')).join('')
  .split(' ').filter(Boolean);
const isYearToken = (w) => w.length === 4 && (w.startsWith('20') || w.startsWith('19')) && Array.from(w).every((c) => c >= '0' && c <= '9');

/** The breakdown to ask for a single-figure answer: { q, by: 'district' | 'period' } or null (nothing to explain).
    The question as the pipeline understood it (`rewritten_question`, standalone) when it gave one. */
export function explainAsk(question, response) {
  const r = response || {};
  let base = String((typeof r.rewritten_question === 'string' && r.rewritten_question.trim()) || question || '').trim();
  while (base && '?.!,;: '.includes(base[base.length - 1])) base = base.slice(0, -1);
  if (!base) return null;
  const W = norm(base);
  const ws = W.trim().split(' ');
  const row = (Array.isArray(r.data) && r.data[0]) || {};
  const filled = (c) => row[c] !== null && row[c] !== undefined && String(row[c]).trim() !== '';
  const districtNamed = DISTRICTS.some((d) => {
    const n = norm(d);
    return W.includes(n) || (n.endsWith(' hills ') && W.includes(n.slice(0, -7) + ' '));
  });
  const placeNamed = districtNamed || ws.some((w) => PLACE_WORDS.includes(w))
    || Object.keys(row).some((c) => filled(c) && colParts(c).some((p) => PLACE_COLS.includes(p)) && Number.isNaN(Number(row[c])));
  const yearNamed = ws.some((w) => isYearToken(w) || YEAR_WORDS.includes(w))
    || Object.keys(row).some((c) => filled(c) && colParts(c).some((p) => PERIOD_COLS.includes(p)));
  if (!placeNamed) return { q: `${base} by district`, by: 'district' };
  if (!yearNamed) return { q: `${base} by financial year`, by: 'period' };
  return null;
}

/** A session id for one throwaway question (the explaining breakdown): never the chat's (api.generateSessionId would
    replace the tab's own), the server's pattern ^[A-Za-z0-9._:-]+$, 128 random bits. */
export function throwawaySessionId() {
  const buf = new Uint8Array(16);
  try { crypto.getRandomValues(buf); } catch (e) { for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256); }
  return `voice_explain_${Date.now()}_${Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}
