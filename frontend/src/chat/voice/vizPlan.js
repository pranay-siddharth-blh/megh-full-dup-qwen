/* The voice desk's picture planner (D-105). Pure and deterministic: an answer from the pipeline (its rows, columns,
   schemes, measure notes and the question) becomes the Secretary view's cards, in Mitra's card grammar (tiles, bars,
   race, line, donut, the Meghalaya map). Nothing is computed here that the rows do not hold: every figure on a card is
   a cell of the answer, every label a value of it. Cross-scheme first (user, 2026-11-02: "the whole point is to handle
   cross scheme"): a scheme keeps its own unit and is never added to another; its "what this counts" note rides on its
   tile; years a scheme does not hold are gaps, never zeros.

   plan(response, question, view) -> { cards: [card], insight, applied } | null
   `view` (a chart switch: the chat's redraw or the voice's "show it on the map") wins over the words of the question;
   `applied` = { asked, drawn, reason } says which view was asked for and which one the data allowed (2026-11-11).
   card = { id, kind, title, unit, note, items|series+x, fmt, allowed: [kinds], mapMode?, leaders?, wide? }
   Every item carries `say`: the spoken forms that reveal it as the voice names it (Mitra's Stage.hear). No regex
   (D-046 / D-047). */

import { SCHEME_HUES, CATEGORICAL, fmt as fmtFull, fmtUnit, insightFor, insightForSeries } from '../chartTheme.js';
import { colTitle, isBlank, isNumeric, measureName, nameParts, tableColumns, unitOf, withoutTwins, placeTitle,
  isAdditive, lowerIsBetter, canAdd } from '../columns.js';
import { isPeriodLabel } from '../text.js';
import { chartPreference } from '../analytics.js';
import VOICE_PACK from './meghVoicePack.js';   // generated from Megh's registries (2026-11-12: a new scheme = data, not code)

export const SCHEMES = VOICE_PACK.schemes;
export const DISTRICTS = VOICE_PACK.districts;
const BRAND = '#7C3FBF';
const DIRECTIONS = ['east', 'west', 'north', 'south', 'eastern'];

// how a scheme is said (the voice's own transcript: Gemini may spell an acronym out)
const SCHEME_SAY = VOICE_PACK.scheme_say;
// a spoken form that is the start of a longer name ("cm elevate" in "cm elevate legacy") does not reveal the shorter one
const SAY_NOT_BEFORE = VOICE_PACK.say_not_before;

/** ' west garo hills 2023 24 ' — lower-case letters and digits, single spaces, padded. */
export function norm(s) {
  let out = ' ';
  for (const ch of String(s || '').toLowerCase()) {
    const ok = (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9');
    if (ok) out += ch; else if (!out.endsWith(' ')) out += ' ';
  }
  return out.endsWith(' ') ? out : out + ' ';
}

/** The voice has said one of the item's spoken forms (whole words; not as the start of a longer name). */
export function heardItem(heard, item) {
  for (const s of item.say || []) {
    const n = norm(s);
    if (n.trim().length < 3) continue;
    let at = heard.indexOf(n);
    while (at >= 0) {
      const after = heard.slice(at + n.length).split(' ')[0];
      const before = heard.slice(0, at).trim().split(' ').pop();
      if (!(item.notBefore || []).includes(after) && !(item.place && DIRECTIONS.includes(before))) return true;
      at = heard.indexOf(n, at + 1);
    }
  }
  return false;
}

const titleCase = (s) => String(s).toLowerCase().split(' ').map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(' ');
const districtKey = (v) => {
  const k = String(v || '').trim().toUpperCase();
  return DISTRICTS.includes(k) ? k : null;
};
const schemeOf = (v) => SCHEMES.find((s) => s.toLowerCase() === String(v || '').trim().toLowerCase()) || null;
const hueOf = (scheme, i = 0) => (SCHEME_HUES[scheme] ? SCHEME_HUES[scheme].main : CATEGORICAL[i % CATEGORICAL.length]);
const num = (v) => (isBlank(v) || !isNumeric(v) ? null : Number(String(v).trim().replaceAll(',', '')));

// years said in words ("twenty twenty-three"): the voice reads 2023-24 that way
const ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
  'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen'];
const TENS = ['', '', 'twenty', 'thirty'];
const twoDigits = (n) => (n < 20 ? ONES[n] : TENS[Math.floor(n / 10)] + (n % 10 ? ' ' + ONES[n % 10] : ''));
function periodSay(label) {
  const s = String(label).trim();
  const y = Number(s.slice(0, 4));
  const out = [s, norm(s).trim()];
  if (y >= 2000 && y < 2040) {
    const hi = y % 100;
    out.push(`twenty ${hi < 10 ? 'oh ' + ONES[hi] : twoDigits(hi)}`);
    out.push(String(y));
  }
  return out;
}
const districtSay = (k) => {
  const name = titleCase(k);
  const out = [name];
  // the voice and the officers shorten them: "West Garo", "EKH" is not spoken back by the voice, so names only
  if (name.endsWith(' Hills')) out.push(name.slice(0, -6));
  return out;
};

// ── units and formatting ──────────────────────────────────────────────────
const MONEY_WORDS = ['amount', 'rupees', 'rs', 'inr', 'disbursed', 'disbursement', 'released', 'expenditure', 'exp'];
const COUNT_WORDS = ['houses', 'house', 'beneficiaries', 'payments', 'applications', 'groups', 'members', 'memberships',
  'days', 'households', 'persons', 'villages', 'records', 'count', 'number', 'cards'];
/** 'crore' | 'lakh' | 'rupees' | 'pct' | null (a count) for a measure column. */
export function unitFor(col) {
  const u = unitOf(col);
  if (u) return u;
  const p = nameParts(col);
  if (p.some((x) => COUNT_WORDS.includes(x))) return null;
  return p.some((x) => MONEY_WORDS.includes(x)) ? 'rupees' : null;
}
export function fmtFor(unit) {
  if (unit === 'crore' || unit === 'lakh' || unit === 'rupees' || unit === 'pct') return (v) => fmtUnit(v, unit);
  return (v) => (v === null || v === undefined ? '—' : fmtFull(v));
}
const unitLabel = (unit) => ({ crore: '₹ crore', lakh: '₹ lakh', rupees: '₹', pct: '%' }[unit] || '');
const TITLE_WORDS = VOICE_PACK.title_words;
const measureTitle = (col) => {
  const t = colTitle(measureName(col)).split(' ').map((w) => TITLE_WORDS[w.toLowerCase()] || w)
    .filter((w, i, a) => !(w === 'G' && a[i - 1] === 'PMAY-G')).join(' ');
  return t.charAt(0).toUpperCase() + t.slice(1);
};
// "MGNREGA · Person days", never "MGNREGA · MGNREGA person days"
const schemeTitle = (s, col) => {
  const m = measureTitle(col);
  const cut = m.toLowerCase().startsWith(s.toLowerCase() + ' ') ? m.slice(s.length + 1) : m;
  return `${s} · ${cut.charAt(0).toUpperCase()}${cut.slice(1)}`;
};
const noteFor = (notes, scheme, col) => {
  const n = notes && scheme && notes[scheme];
  if (!n) return '';
  if (n[col]) return n[col];
  const hit = Object.keys(n).find((k) => nameParts(k).join(' ') === nameParts(col).join(' '));
  return hit ? n[hit] : '';
};

// ── the columns of an answer ──────────────────────────────────────────────
const SCHEME_COLS = ['scheme', 'schemes', 'scheme_label'];
export function shapeOf(rows) {
  const cols = tableColumns(rows);
  const all = (c, pred) => rows.every((r) => isBlank(r[c]) || pred(r[c])) && rows.some((r) => !isBlank(r[c]));
  const scheme = cols.find((c) => SCHEME_COLS.includes(c.toLowerCase()) && all(c, (v) => !!schemeOf(v)))
    || cols.find((c) => all(c, (v) => !!schemeOf(v)) && !cols.some((x) => SCHEME_COLS.includes(x.toLowerCase())));
  const district = cols.find((c) => c !== scheme && all(c, (v) => !!districtKey(v)));
  const periodName = (c) => nameParts(c).some((x) => ['year', 'fy', 'period', 'month', 'quarter'].includes(x));
  const period = cols.find((c) => c !== scheme && c !== district && all(c, (v) => isPeriodLabel(v))
    && (periodName(c) || rows.every((r) => isBlank(r[c]) || String(r[c]).includes('-'))));
  const measures = cols.filter((c) => ![scheme, district, period].includes(c) && !nameParts(c).includes('code')
    && rows.some((r) => !isBlank(r[c])) && rows.every((r) => isBlank(r[c]) || isNumeric(r[c]))
    && !nameParts(c).every((p) => ['year', 'key', 'id', 'rank', 'lgd', 'sl', 'no'].includes(p)));
  const labels = cols.filter((c) => ![scheme, district, period].includes(c) && !measures.includes(c)
    && rows.some((r) => !isBlank(r[c])));
  return { cols, scheme, district, period, measures, labels, other: labels[0] || null };
}

let SEQ = 0;
const card = (kind, title, unit, extra) => ({ id: `c${++SEQ}`, kind, title, unit, unitLabel: unitLabel(unit),
  fmt: fmtFor(unit), allowed: [kind], ...extra });

function itemsBy(rows, labelCol, measure, opts = {}) {
  const out = [];
  rows.forEach((r) => {
    const raw = r[labelCol];
    if (isBlank(raw)) return;
    const dk = districtKey(raw);
    const sk = schemeOf(raw);
    const key = dk || sk || String(raw);
    if (out.some((x) => x.key === key)) return;
    const label = dk ? titleCase(dk) : sk || placeTitle(raw, labelCol);
    out.push({ key, label, col: measure, value: num(r[measure]), color: sk ? hueOf(sk) : (opts.color || BRAND),   // one measure, one hue
      say: dk ? districtSay(dk) : sk ? SCHEME_SAY[sk] : [label], notBefore: sk ? SAY_NOT_BEFORE[sk] : undefined, place: !!dk });
  });
  return out;
}

// a ranking card from (label, value) items: race when long, bars when short; the map beside it for districts
function rankCards(items, title, unit, { districts = false, color = BRAND, low = false, measureCol = '' } = {}) {
  const sorted = [...items].sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
  const shown = sorted.slice(0, 12);
  const additive = !measureCol || isAdditive(measureCol);
  // the donut is offered for up to 8 parts; asked for by name ("as a donut / pie") it is drawn up to 12 (plan())
  const allowed = ['race', 'bars', ...(additive && shown.length <= 8 ? ['donut'] : []), ...(districts ? ['map'] : [])];
  const asked = additive ? ['donut'] : [];
  const kind = shown.length > 6 ? 'race' : 'bars';
  const c = card(kind, title, unit, { items: shown.map((x) => ({ ...x, color: x.color || color })), allowed, asked,
    more: sorted.length > shown.length ? sorted.length - shown.length : 0 });
  c.insight = insightFor('bar', shown.map((x) => x.label), shown.map((x) => x.value), { unit, low,
    lowerBetter: measureCol ? lowerIsBetter(measureCol) : false, measure: title.toLowerCase() });
  return c;
}
const mapCard = (items, title, unit, extra = {}) => card('map', title, unit, { items, mapMode: 'choropleth',
  allowed: ['map', 'race', 'bars'], wide: true, ...extra });

// ── the shapes ────────────────────────────────────────────────────────────
// one row (or a few) per scheme, each with its own measures: tiles, one per scheme figure, never added up
function perScheme(rows, sh, notes) {
  const groups = new Map();
  rows.forEach((r) => { const s = schemeOf(r[sh.scheme]); if (s) { if (!groups.has(s)) groups.set(s, []); groups.get(s).push(r); } });
  const tiles = [];
  const cards = [];
  const tile = (s, r, m) => {
    const unit = unitFor(m);
    return { key: `${s}|${m}`, label: s, col: m, value: num(r[m]), color: hueOf(s), unit, fmt: fmtFor(unit),
      sub: `${measureTitle(m)}${noteFor(notes, s, m) ? ' · ' + noteFor(notes, s, m) : ''}`,
      say: SCHEME_SAY[s], notBefore: SAY_NOT_BEFORE[s] };
  };
  const rounds = [[], [], []];
  groups.forEach((rs, s) => {
    const ms = sh.measures.filter((m) => rs.some((r) => !isBlank(r[m])));
    if (rs.length === 1) ms.slice(0, 3).forEach((m, k) => rounds[k].push(tile(s, rs[0], m)));
    else if (ms.length) {                          // a scheme broken down (CM Elevate by its sub-schemes): its own card
      const m = ms[0];
      const by = sh.labels.find((c) => rs.every((r) => !isBlank(r[c])));
      if (!by) return;
      cards.push(rankCards(itemsBy(rs, by, m, { color: hueOf(s) }), `${schemeTitle(s, m)} by ${colTitle(by).toLowerCase()}`,
        unitFor(m), { color: hueOf(s), measureCol: m }));
    }
  });
  rounds.forEach((r) => r.forEach((x) => { if (tiles.length < 8) tiles.push(x); }));
  const out = [];
  if (tiles.length) {
    out.push(card('tiles', groups.size > 1 ? 'Each scheme, in its own unit' : `${[...groups.keys()][0]}`, null,
      { items: tiles.slice(0, 8), allowed: ['tiles'], wide: tiles.length > 4,
        note: groups.size > 1 ? 'Schemes count and spend different things, so their figures are never added together.' : '' }));
  }
  // money is the one unit schemes share: a bar of the money figures beside the tiles
  const moneyCol = sh.measures.find((m) => ['crore', 'lakh', 'rupees'].includes(unitFor(m))
    && [...groups.values()].filter((rs) => rs.length === 1 && !isBlank(rs[0][m])).length >= 3);
  if (moneyCol) {
    const items = [];
    groups.forEach((rs, s) => { if (rs.length === 1 && !isBlank(rs[0][moneyCol])) items.push({ key: s, label: s, col: moneyCol, value: num(rs[0][moneyCol]), color: hueOf(s), say: SCHEME_SAY[s], notBefore: SAY_NOT_BEFORE[s] }); });
    out.push(rankCards(items, `${measureTitle(moneyCol)} by scheme`, unitFor(moneyCol), { measureCol: moneyCol }));
  }
  return [...out, ...cards];
}

function byDistrict(rows, sh, notes, q) {
  const low = q.low;
  // with a scheme column: one district per row = the leader of each district; else one ranking per scheme
  if (sh.scheme) {
    const perD = new Map();
    rows.forEach((r) => { const d = districtKey(r[sh.district]); if (d) perD.set(d, (perD.get(d) || 0) + 1); });
    const leader = q.lead || ([...perD.values()].every((n) => n === 1)
      && new Set(rows.map((r) => schemeOf(r[sh.scheme]))).size > 1);
    const m = sh.measures[0];
    if (leader && m) {
      const unit = unitFor(m);
      const leaders = {};
      const items = [];
      rows.forEach((r) => {
        const d = districtKey(r[sh.district]); const s = schemeOf(r[sh.scheme]);
        if (!d || !s || leaders[d]) return;            // the answer lists the leader of a district first
        leaders[d] = { label: s, color: hueOf(s) };
        items.push({ key: d, label: titleCase(d), col: m, value: num(r[m]), color: hueOf(s), say: districtSay(d), sub: s, place: true });
      });
      const names = [...new Set(Object.values(leaders).map((x) => x.label))];
      return [
        mapCard(items, names.length === 1 ? `${names[0]} leads in every district` : 'The leading scheme in each district', unit,
          { mapMode: 'leader', leaders, note: noteFor(notes, names[0], m) ? `${measureTitle(m)}: ${noteFor(notes, names[0], m)}` : '' }),
        rankCards(items, `${measureTitle(m)} of the leading scheme`, unit, { low, measureCol: m }),
      ];
    }
    const out = [];
    const schemes = [...new Set(rows.map((r) => schemeOf(r[sh.scheme])).filter(Boolean))];
    schemes.slice(0, 5).forEach((s) => {
      const rs = rows.filter((r) => schemeOf(r[sh.scheme]) === s);
      const mm = sh.measures.find((x) => rs.some((r) => !isBlank(r[x])));
      if (!mm) return;
      const unit = unitFor(mm);
      const items = itemsBy(rs, sh.district, mm, { color: hueOf(s) }).map((x) => ({ ...x, color: hueOf(s) }));
      if (!out.length) out.push(mapCard(items, `${schemeTitle(s, mm)} by district`, unit, { note: noteFor(notes, s, mm) }));
      out.push(rankCards(items, schemeTitle(s, mm), unit, { color: hueOf(s), low, measureCol: mm }));
    });
    return out;
  }
  const ds = rows.filter((r) => districtKey(r[sh.district]));
  // two districts: a comparison, measure by measure
  if (ds.length === 2) {
    const tiles = [];
    sh.measures.slice(0, 4).forEach((m) => {
      const unit = unitFor(m);
      ds.forEach((r, i) => {
        const d = districtKey(r[sh.district]);
        tiles.push({ key: `${d}|${m}`, label: titleCase(d), col: m, value: num(r[m]), unit, fmt: fmtFor(unit),
          color: CATEGORICAL[i], sub: measureTitle(m), say: districtSay(d), place: true });
      });
    });
    const m = sh.measures[0];
    const unit = unitFor(m);
    return [
      card('tiles', 'Side by side', null, { items: tiles.slice(0, 8), allowed: ['tiles'], wide: tiles.length > 4 }),
      rankCards(itemsBy(ds, sh.district, m), measureTitle(m), unit, { districts: true, low, measureCol: m }),
      mapCard(itemsBy(ds, sh.district, m), `${measureTitle(m)} · the two districts`, unit),
    ];
  }
  const out = [];
  sh.measures.slice(0, 2).forEach((m, k) => {
    const unit = unitFor(m);
    const items = itemsBy(ds, sh.district, m);
    if (k === 0) out.push(mapCard(items, `${measureTitle(m)} by district`, unit));
    out.push(rankCards(items, measureTitle(m), unit, { districts: true, low, measureCol: m }));
  });
  return out;
}

const fyStart = (p) => { const s = String(p); const y = Number(s.slice(0, 4)); return s.length === 7 && s[4] === '-' && y > 1900 ? y : 0; };
const fyOf = (y) => `${y}-${String((y + 1) % 100).padStart(2, '0')}`;
/** The periods in order; for financial years ("2022-23") every year between the first and the last is on the axis, so a
    year a scheme does not hold is drawn as a gap, never as if the line ran straight through it. */
const sortPeriods = (ps) => {
  const out = [...new Set(ps.map((p) => String(p).trim()))].sort((a, b) => a.localeCompare(b));
  if (out.length < 2 || !out.every((p) => fyStart(p))) return out;
  const full = [];
  for (let y = fyStart(out[0]); y <= fyStart(out[out.length - 1]); y++) full.push(fyOf(y));
  return full;
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTH_SAY = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october',
  'november', 'december'];
/** '2021-03-01' -> 'Mar 2021' (a date that is the first of a month); anything else as it is. */
const monthOf = (p) => {
  const s = String(p);
  const m = Number(s.slice(5, 7));
  return s.length >= 7 && s[4] === '-' && m >= 1 && m <= 12 && (s.length === 7 || s.slice(8, 10) === '01') ? m : 0;
};
const periodLabel = (p) => (monthOf(p) ? `${MONTHS[monthOf(p) - 1]} ${String(p).slice(0, 4)}` : p);
function lineCard(title, x0, series, unit, extra = {}) {
  const months = x0.length && x0.every((p) => monthOf(p));
  const x = x0.map(periodLabel);
  if (months) title = title.split(' by year').join(' by month');
  const c = card('line', title, unit, { x, series, allowed: ['line', 'bars'], ...extra,
    items: x0.map((p, i) => ({ key: x[i], label: x[i], say: monthOf(p) ? [MONTH_SAY[monthOf(p) - 1], x[i]] : periodSay(p),
      ...(series.length === 1 ? { value: series[0].values[i], col: series[0].col, color: series[0].color } : {}) })) });
  if (series.length !== 1) c.allowed = ['line'];
  c.insight = series.length === 1
    ? insightFor('line', x, series[0].values, { unit })
    : insightForSeries(x, series.map((s) => ({ label: s.name, data: s.values })), true, { unit });
  return c;
}

function byPeriod(rows, sh) {
  if (sh.scheme) {
    // each scheme over the years: its own card (its own unit); a year a scheme does not hold is a gap
    const schemes = [...new Set(rows.map((r) => schemeOf(r[sh.scheme])).filter(Boolean))];
    const x = sortPeriods(rows.map((r) => r[sh.period]).filter((p) => !isBlank(p)));
    const money = sh.measures.length && sh.measures.every((m) => ['crore', 'lakh', 'rupees'].includes(unitFor(m)))
      && new Set(sh.measures.map(unitFor)).size === 1;
    const seriesOf = (s, m) => ({ key: s, name: s, col: m, color: hueOf(s),
      values: x.map((p) => { const r = rows.find((rr) => schemeOf(rr[sh.scheme]) === s && String(rr[sh.period]).trim() === p); return r ? num(r[m]) : null; }) });
    if (money) {
      const m = sh.measures[0];
      return [lineCard(`${measureTitle(m)} by year, each scheme`, x, schemes.map((s) => seriesOf(s, m)), unitFor(m),
        { wide: true, note: 'A gap is a year the scheme holds no data for, not a zero.' })];
    }
    return schemes.slice(0, 6).map((s) => {
      const rs = rows.filter((r) => schemeOf(r[sh.scheme]) === s);
      const m = sh.measures.find((mm) => rs.some((r) => !isBlank(r[mm])));
      return m ? lineCard(schemeTitle(s, m), x, [seriesOf(s, m)], unitFor(m)) : null;
    }).filter(Boolean);
  }
  const x = sortPeriods(rows.map((r) => r[sh.period]).filter((p) => !isBlank(p)));
  const byUnit = new Map();
  sh.measures.forEach((m) => { const u = unitFor(m) || 'n'; if (!byUnit.has(u)) byUnit.set(u, []); byUnit.get(u).push(m); });
  const out = [];
  byUnit.forEach((ms) => {
    const series = ms.slice(0, 4).map((m, i) => ({ key: m, name: measureTitle(m), col: m, color: i ? CATEGORICAL[i % CATEGORICAL.length] : BRAND,
      values: x.map((p) => { const r = rows.find((rr) => String(rr[sh.period]).trim() === p); return r ? num(r[m]) : null; }) }));
    out.push(lineCard(series.length === 1 ? `${series[0].name} by year` : `${series.map((s) => s.name).join(' and ')} by year`, x, series, unitFor(ms[0])));
  });
  return out.slice(0, 3);
}

function districtByPeriod(rows, sh, q) {
  // district × year: the latest year on the map and as a ranking, and the leading districts over the years
  const m = sh.measures[0];
  const unit = unitFor(m);
  const x = sortPeriods(rows.map((r) => r[sh.period]).filter((p) => !isBlank(p)));
  const last = x[x.length - 1];
  const latest = rows.filter((r) => String(r[sh.period]).trim() === last);
  const items = itemsBy(latest, sh.district, m);
  const top = [...items].sort((a, b) => (b.value ?? 0) - (a.value ?? 0)).slice(0, 5);
  const series = top.map((t, i) => ({ key: t.key, name: t.label, col: m, color: CATEGORICAL[i % CATEGORICAL.length],
    values: x.map((p) => { const r = rows.find((rr) => districtKey(rr[sh.district]) === t.key && String(rr[sh.period]).trim() === p); return r ? num(r[m]) : null; }) }));
  return [
    mapCard(items, `${measureTitle(m)} by district · ${last}`, unit),
    rankCards(items, `${measureTitle(m)} · ${last}`, unit, { districts: true, low: q.low, measureCol: m }),
    lineCard(`${measureTitle(m)} over the years · leading districts`, x, series, unit, { wide: true }),
  ];
}

function single(rows, sh) {
  const r = rows[0];
  const ms = sh.measures.filter((m) => !isBlank(r[m]));
  if (!ms.length) return [];
  if (ms.length === 1) {
    const unit = unitFor(ms[0]);
    return [card('kpi', measureTitle(ms[0]), unit, { single: true, items: [{ key: ms[0], label: measureTitle(ms[0]), col: ms[0], value: num(r[ms[0]]), color: BRAND, say: [] }] })];
  }
  return [card('tiles', 'The figures', null, { single: true, allowed: ['tiles'], wide: ms.length > 4,
    items: ms.slice(0, 8).map((m, i) => { const unit = unitFor(m); return { key: m, label: measureTitle(m), col: m, value: num(r[m]), unit, fmt: fmtFor(unit), color: i ? CATEGORICAL[i % CATEGORICAL.length] : BRAND, say: [] }; }) })];
}

const LOW_WORDS = ['lowest', 'least', 'fewest', 'smallest', 'bottom', 'worst', 'minimum'];
const MAP_WORDS = ['map', 'maps'];
const LEAD_WORDS = ['lead', 'leads', 'leading', 'leader', 'dominant', 'dominates', 'biggest', 'largest', 'top'];

// ── views (2026-11-11) ────────────────────────────────────────────────────
/** A view word (the chat's redraw views, the voice's canonical switch sentences) -> the card kind that draws it. */
export const VIEW_KIND = { bar: 'bars', bars: 'bars', column: 'bars', stacked: 'bars', pie: 'donut', doughnut: 'donut',
  donut: 'donut', line: 'line', map: 'map', race: 'race', ranking: 'race', horizontal: 'race', table: 'table' };
// the closest view when the one asked for does not fit the data, in order
const FALLBACK = { map: ['map', 'race', 'bars'], line: ['line', 'bars', 'race'], donut: ['donut', 'bars', 'race'],
  bars: ['bars', 'race', 'line'], race: ['race', 'bars', 'line'] };
const isFigureCard = (c) => c.kind === 'tiles' || c.kind === 'kpi' || c.kind === 'table';
const canDraw = (c, k) => (c.allowed || []).includes(k) || (c.asked || []).includes(k)
  // a one-series line (a figure per year) may also be ranked: its years, highest first
  || (k === 'race' && c.kind === 'line' && (c.series || []).length === 1);
const byValue = (items) => [...items].sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
const sameItems = (a, b) => (a.items || []).map((x) => x.key).sort().join('|') === (b.items || []).map((x) => x.key).sort().join('|');

/** The card `c` drawn as `k` (a copy: the plan's own card is never changed). A ranking is sorted, highest first; a line
    drawn as bars keeps its years in order. */
function drawnAs(c, k) {
  if (c.kind === k) return c;
  const next = { ...c, kind: k, allowed: c.allowed.includes(k) ? c.allowed : [...c.allowed, k] };
  if (k === 'race' || (k === 'bars' && c.kind !== 'line')) next.items = byValue(c.items || []);
  if (c.kind === 'line' && k !== 'line') delete next.series;
  return next;
}

/** `c` drawn as `k` leads the picture; a card that would now show the same thing twice goes. `afterFigures`: it leads
    the charts but the figure tiles stay first (a comparison's side-by-side tiles are its headline). */
function promote(cards, c, k, afterFigures = false) {
  const next = drawnAs(c, k);
  const rest = cards.filter((x) => x !== c && !(x.kind === k && sameItems(x, next)));
  if (!afterFigures) return [next, ...rest];
  const at = rest.findIndex((x) => !isFigureCard(x));
  return at < 0 ? [...rest, next] : [...rest.slice(0, at), next, ...rest.slice(at)];
}

// the answer as a table (the voice's "show it as a table"): its own rows and columns, at most 12 rows, nothing computed
const TABLE_ROWS = 12;
function labelText(v, col) {
  const dk = districtKey(v);
  if (dk) return titleCase(dk);
  const sk = schemeOf(v);
  if (sk) return sk;
  return isPeriodLabel(v) ? periodLabel(String(v).trim()) : placeTitle(v, col);
}
function tableCard(rows, sh) {
  const labels = [sh.district, sh.scheme, sh.period, sh.other].filter(Boolean).slice(0, 2);
  const ms = sh.measures.slice(0, labels.length ? 4 : 8);
  if (!ms.length || !rows.length) return null;
  const cellOf = (m, v) => (v === null ? '—' : fmtFor(unitFor(m))(v));
  let items;
  let columns;
  if (!labels.length && rows.length === 1) {          // one row: each figure is a row of the table
    const r = rows[0];
    items = ms.map((m, i) => ({ key: m, label: measureTitle(m), col: m, value: num(r[m]), fmt: fmtFor(unitFor(m)),
      cells: [cellOf(m, num(r[m]))], color: i ? CATEGORICAL[i % CATEGORICAL.length] : BRAND, say: [] }));
    columns = [{ title: 'Figure' }, { title: 'Value' }];
  } else {
    const seen = new Set();
    items = rows.slice(0, TABLE_ROWS).map((r, i) => {
      const label = labels.length ? labels.map((l) => (isBlank(r[l]) ? '—' : labelText(r[l], l))).join(' · ') : `Row ${i + 1}`;
      let key = label;
      while (seen.has(key)) key += ' ';
      seen.add(key);
      const dk = sh.district ? districtKey(r[sh.district]) : null;
      const sk = sh.scheme ? schemeOf(r[sh.scheme]) : null;
      return { key, label, col: ms[0], value: num(r[ms[0]]), fmt: fmtFor(unitFor(ms[0])), cells: ms.map((m) => cellOf(m, num(r[m]))),
        color: sk ? hueOf(sk) : BRAND, say: dk ? districtSay(dk) : sk ? SCHEME_SAY[sk] : [], notBefore: sk ? SAY_NOT_BEFORE[sk] : undefined,
        place: !!dk };
    });
    columns = [{ title: labels.length ? labels.map((l) => colTitle(l)).join(' · ') : '' },
      ...ms.map((m) => ({ title: measureTitle(m), unit: unitLabel(unitFor(m)) }))];
  }
  return card('table', 'The answer, as a table', null, { items, columns, allowed: ['table'], wide: true,
    more: rows.length > TABLE_ROWS ? rows.length - TABLE_ROWS : 0 });
}

/** Why the view asked for could not be drawn (the voice says it, voice/voiceViews.js). */
function reasonFor(want, cards) {
  const charts = cards.filter((c) => !isFigureCard(c));
  if (!charts.length) return 'single';
  if (want === 'map') return 'not-district';
  if (want === 'line') return 'not-time';
  if (want === 'donut') return charts.some((c) => (c.items || []).length > 12) ? 'too-many' : 'not-parts';
  return charts.every((c) => c.kind === 'line') ? 'series' : 'other';
}

/** The view `want` (a card kind) applied to the cards -> { cards, drawn, reason }. The first card that can draw it is
    drawn that way and leads (a card already drawn that way first; a map stays a map unless it is the only choice); a
    view the data cannot hold falls back to the closest one (FALLBACK) and says why. `named`: asked in words or by a
    switch, so figure tiles of one measure may be set side by side (they are never a split of one total). */
function applyView(cards, want, rows, sh) {
  if (want === 'table') {
    const t = tableCard(rows, sh);
    return t ? { cards: [t], drawn: 'table', reason: '' } : { cards, drawn: null, reason: 'single' };
  }
  const charts = cards.filter((c) => !isFigureCard(c));
  for (const k of FALLBACK[want] || [want]) {
    const pool = charts.filter((c) => canDraw(c, k));
    if (!pool.length) continue;
    const c = pool.find((x) => x.kind === k) || pool.find((x) => x.kind !== 'map') || pool[0];
    return { cards: promote(cards, c, k), drawn: k, reason: k === want ? '' : reasonFor(want, cards) };
  }
  // no chart can draw it: figure tiles of one measure (two or more) set side by side, as asked
  if (['bars', 'donut', 'race'].includes(want)) {
    const tiles = cards.find((c) => c.kind === 'tiles' && (c.items || []).length >= 2);
    if (tiles) {
      const byCol = new Map();
      tiles.items.forEach((x) => { if (x.col && x.value !== null) byCol.set(x.col, [...(byCol.get(x.col) || []), x]); });
      const best = [...byCol.values()].sort((a, b) => b.length - a.length)[0];
      if (best && best.length >= 2) {
        const unit = best[0].unit || null;
        const out = [...cards];
        out.splice(1, 0, card(want, `${measureTitle(best[0].col)}, side by side`, unit, {
          items: best.map((x) => ({ key: x.label, label: x.label, col: x.col, value: x.value, color: x.color, say: x.say, notBefore: x.notBefore })),
          allowed: ['bars', 'donut', 'race'],
          note: 'Drawn as asked. The schemes count different things, so this compares the figures side by side; it is not a split of one total.' }));
        return { cards: out, drawn: want, reason: '' };
      }
    }
  }
  return { cards, drawn: null, reason: reasonFor(want, cards) };
}

// ── the best picture when no chart is named (2026-11-11): words that say what the officer wants to SEE, honoured only
// when the data holds that picture (the planner's shapes decide what is possible; these only choose among them)
const RANK_SAY = ['top', 'highest', 'lowest', 'leading', 'rank', 'ranks', 'ranked', 'ranking', 'rankings', 'best', 'worst',
  'most', 'least', 'bottom', 'maximum', 'minimum', 'biggest', 'largest', 'smallest'];
const TREND_SAY = ['trend', 'trends', 'trending', 'growth', 'grew', 'grown', 'yearly', 'annual', 'annually', 'over the years',
  'year by year', 'year on year', 'by financial year', 'each financial year', 'every financial year', 'every year', 'each year',
  'by year', 'over time', 'per year'];
const SHARE_SAY = ['share', 'shares', 'split', 'distribution', 'proportion', 'proportions', 'breakdown', 'composition', 'break up', 'breakup'];
const COMPARE_SAY = ['compare', 'compared', 'comparing', 'comparison', 'versus', 'vs', 'against'];
const DISTRICT_SAY = ['by district', 'district wise', 'districtwise', 'across districts', 'across the districts',
  'across all districts', 'each district', 'every district', 'all districts', 'all the districts', 'where'];

function autoView(cards, sh, question) {
  const W = norm(question);
  const said = (list) => list.some((p) => W.includes(' ' + p + ' '));
  const charts = cards.filter((c) => !isFigureCard(c));
  if (!charts.length || cards[0].mapMode === 'leader') return cards;   // the leader map IS the picture
  const pick = (k) => charts.find((x) => x.kind !== 'map' && canDraw(x, k) && x.kind !== 'line') || charts.find((x) => canDraw(x, k));
  if (said(RANK_SAY)) { const c = pick('race'); if (c && c.kind !== 'line') return promote(cards, c, 'race'); }
  if (said(SHARE_SAY)) { const c = charts.find((x) => (x.allowed || []).includes('donut')); if (c) return promote(cards, c, 'donut'); }
  if (sh.period && said(TREND_SAY)) { const c = charts.find((x) => x.kind === 'line'); if (c) return promote(cards, c, 'line'); }
  // a comparison of many places is not forced into upright bars (2026-11-12 fix round: 12 districts' value labels
  // piled on each other); it keeps its ranking, which reads every name
  if (said(COMPARE_SAY)) { const c = pick('bars'); if (c && c.kind !== 'line' && (c.items || []).length <= 8) return promote(cards, c, 'bars', true); }
  if (sh.district && said(DISTRICT_SAY)) { const m = charts.find((x) => x.kind === 'map'); if (m) return promote(cards, m, 'map'); }
  return cards;
}

/** The cards for one answer, or null when the answer has no picture (text, a clarification, an error). */
export function plan(response, question = '', view = null) {
  if (!response || response.clarification || response.answer_failed || response.route === 'clarification') return null;
  const raw = Array.isArray(response.data) ? response.data.filter((r) => r && typeof r === 'object') : [];
  if (!raw.length) return null;
  const rows = withoutTwins(raw);
  const sh = shapeOf(rows);
  if (!sh.measures.length) return null;
  const qw = norm(question).split(' ');
  const q = { low: qw.some((w) => LOW_WORDS.includes(w)), lead: qw.some((w) => LEAD_WORDS.includes(w)) };
  const notes = response.measure_notes || null;
  let cards = [];
  if (sh.district && sh.period) cards = districtByPeriod(rows, sh, q);
  else if (sh.district) cards = byDistrict(rows, sh, notes, q);
  else if (sh.period) cards = byPeriod(rows, sh);
  else if (sh.scheme) cards = perScheme(rows, sh, notes);
  else if (rows.length === 1) cards = single(rows, sh);   // one row (the state, one place): its figures as tiles
  else if (sh.other) {
    cards = sh.measures.slice(0, 2).map((m) => rankCards(itemsBy(rows, sh.other, m), `${measureTitle(m)} by ${colTitle(sh.other).toLowerCase()}`,
      unitFor(m), { low: q.low, measureCol: m }));
  } else cards = single(rows, sh);
  cards = cards.filter((c) => c && ((c.items && c.items.length) || (c.series && c.series.length)));
  if (!cards.length) return null;
  // the view: a switch (the chat's redraw, the voice's "show it on the map") wins over everything, then a chart type
  // named in the question ("as a donut", "on the map", "horizontal"), then the words that say what to see
  let want = null;
  let asked = null;
  if (view) {
    asked = String(view).toLowerCase();
    want = VIEW_KIND[asked] || null;
  } else {
    const pref = chartPreference(question);
    want = qw.includes('horizontal') ? 'race' : qw.some((w) => MAP_WORDS.includes(w)) ? 'map'
      : { pie: 'donut', doughnut: 'donut', bar: 'bars', line: 'line', stacked: 'bars', table: 'table' }[pref] || null;
    asked = want;
  }
  let applied = null;
  if (want) {
    const v = applyView(cards, want, rows, sh);
    cards = v.cards;
    applied = { asked, want, drawn: v.drawn, reason: v.reason };
  } else if (!view) {
    cards = autoView(cards, sh, question);
  }
  return { cards: cards.slice(0, 6), insight: cards.find((c) => c.insight)?.insight || '', applied };
}

// ── the figure explained (2026-11-11) ─────────────────────────────────────
/** The breakdown that explains a single figure: the same measure by district (`by` 'district') or by financial year
    ('period'), from a second answer. Drawn only when its parts are the figure's own parts: the same measure, one row
    per district / year, a measure that may be added along that dimension (columns.canAdd) and parts that add up to the
    figure (within 0.5 % or one unit). Every figure is a cell of that answer. -> { card, sum } or { why }. */
export function explainCard(tile, response, by, opts = {}) {
  if (!tile || tile.value === null || tile.value === undefined || !tile.col) return { why: 'no figure' };
  const raw = Array.isArray(response && response.data) ? response.data.filter((r) => r && typeof r === 'object') : [];
  if (raw.length < 2) return { why: 'no breakdown rows' };
  const rows = withoutTwins(raw);
  const sh = shapeOf(rows);
  const dimCol = by === 'district' ? sh.district : sh.period;
  if (!dimCol) return { why: `not by ${by}` };
  if (sh.scheme && new Set(rows.map((r) => schemeOf(r[sh.scheme]))).size > 1) return { why: 'several schemes' };
  const parts = (c) => nameParts(c).join(' ');
  const col = sh.measures.find((m) => m === tile.col) || sh.measures.find((m) => parts(m) === parts(tile.col))
    || (opts.oneMeasure && sh.measures.length === 1 ? sh.measures[0] : null);
  if (!col) return { why: 'not the same measure' };
  if (!canAdd(col, by === 'district' ? 'place' : 'period') || !canAdd(tile.col, by === 'district' ? 'place' : 'period')) {
    return { why: 'the measure does not add up along ' + by };
  }
  const keyOf = (r) => (by === 'district' ? districtKey(r[dimCol]) : (isBlank(r[dimCol]) ? null : String(r[dimCol]).trim()));
  const counts = new Map();
  rows.forEach((r) => { const k = keyOf(r); if (k) counts.set(k, (counts.get(k) || 0) + 1); });
  if (counts.size < 2) return { why: 'fewer than two parts' };
  if ([...counts.values()].some((n) => n > 1)) return { why: `more than one row per ${by}` };
  let sum = 0;
  rows.forEach((r) => { const v = num(r[col]); if (keyOf(r) && v !== null) sum += v; });
  const total = Number(tile.value);
  const tol = Math.max(1, Math.abs(total) * 0.005);
  if (!Number.isFinite(sum) || Math.abs(sum - total) > tol) return { why: 'the parts do not add up to the figure', sum, total };
  const unit = unitFor(col);
  const f = fmtFor(unit);
  const exact = Math.abs(sum - total) < Math.max(1e-6, Math.abs(total) * 1e-9);
  const note = `They add up to ${f(total)}${exact ? '' : ', allowing for rounding'}.`;
  const color = tile.color || BRAND;
  let c;
  if (by === 'district') {
    const items = byValue(itemsBy(rows.filter((r) => keyOf(r)), dimCol, col, { color }).map((x) => ({ ...x, color })));
    c = card(items.length > 6 ? 'race' : 'bars', 'By district', unit, { items: items.slice(0, 12), allowed: [items.length > 6 ? 'race' : 'bars'],
      more: items.length > 12 ? items.length - 12 : 0, note, explain: 'district' });
  } else {
    const x = sortPeriods(rows.map((r) => r[dimCol]).filter((p) => !isBlank(p)));
    const items = x.map((p) => {
      const r = rows.find((rr) => String(rr[dimCol]).trim() === p);
      const lab = periodLabel(p);
      return { key: lab, label: lab, col, value: r ? num(r[col]) : null, color, say: monthOf(p) ? [MONTH_SAY[monthOf(p) - 1], lab] : periodSay(p) };
    });
    c = card('bars', 'By financial year', unit, { items, allowed: ['bars'], note, explain: 'period' });
  }
  return { card: c, sum, total, col, data: rows };
}

/** Every item of a plan with its spoken forms (for the speech-synced reveal), by card. */
export const revealIndex = (p) => (p ? p.cards.map((c) => ({ id: c.id, items: (c.items || []).filter((x) => x.say && x.say.length) })) : []);
