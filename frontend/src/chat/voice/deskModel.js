/* The Secretary's desk, derived from the board (2026-11-14). Pure: no React, no DOM, no regex (D-046).
   Before this the desk named six schemes by hand (eight command tiles over six schemes, a money list without CMSS, map
   chips for six); a scheme onboarded since (CMSS, Homestay) was simply missing. Now every list is the board's own
   schemes, in the voice pack's order (VOICE_PACK.schemes; a scheme the pack does not know yet goes last), so a ninth
   scheme appears with no code change.

   Rules (figures are never computed, rounded or added here; every number is a board total or a board cell):
   - a scheme's HEADLINE is the first measure that is not money (what the scheme counts: person-days, houses
     sanctioned, students paid, applications); a scheme that holds only money shows its money
   - MONEY is a scheme's first rupee measure with a total above zero; a scheme with none is named in a note ("records
     no money"), never drawn as ₹0
   - the MAP of a scheme draws its headline measure by district (or its first measure that has districts)
   - YEARS: the years each scheme holds; a scheme that holds none is named in a note */

const isMoney = (m) => !!m && m.unit === 'rupees';
const hasDistricts = (m) => !!m && m.by_district && Object.keys(m.by_district).length > 0;
const total = (m) => Number(m && m.total) || 0;

/** The board's schemes in the pack's order; schemes the pack does not list keep the board's order, after them. */
export function orderedSchemes(board, packOrder = []) {
  const list = (board && Array.isArray(board.schemes) ? board.schemes : []).filter((s) => s && s.name && Array.isArray(s.measures));
  const rank = (name) => { const i = packOrder.indexOf(name); return i < 0 ? packOrder.length : i; };
  return list.map((s, i) => ({ s, i })).sort((a, b) => rank(a.s.name) - rank(b.s.name) || a.i - b.i).map((x) => x.s);
}

/** What the scheme counts: its first measure that is not money (else its first measure). */
export function headlineMeasure(scheme) {
  const ms = (scheme && scheme.measures) || [];
  return ms.find((m) => !isMoney(m)) || ms[0] || null;
}

/** The scheme's money: its first rupee measure with a total above zero, or null (the scheme records no money). */
export function moneyMeasure(scheme) {
  return ((scheme && scheme.measures) || []).find((m) => isMoney(m) && total(m) > 0) || null;
}

/** The measure the desk's map draws for a scheme: the headline when it has districts, else the first that has. */
export function mapMeasure(scheme) {
  const h = headlineMeasure(scheme);
  if (hasDistricts(h)) return h;
  return ((scheme && scheme.measures) || []).find(hasDistricts) || null;
}

/** "A", "A and B", "A, B and C" */
export function andList(names) {
  const n = names.filter(Boolean);
  if (n.length <= 1) return n[0] || '';
  return `${n.slice(0, -1).join(', ')} and ${n[n.length - 1]}`;
}

/** The whole desk: { schemes, tiles, money, noMoney, maps, years, noYear, lead }. */
export function deskModel(board, packOrder = []) {
  const schemes = orderedSchemes(board, packOrder);
  const tiles = schemes.map((s) => ({ s: s.name, m: headlineMeasure(s) })).filter((x) => x.m);
  const money = schemes.map((s) => ({ s: s.name, m: moneyMeasure(s) })).filter((x) => x.m);
  const noMoney = schemes.filter((s) => !moneyMeasure(s)).map((s) => s.name);
  const maps = schemes.map((s) => ({ s: s.name, m: mapMeasure(s) })).filter((x) => x.m);
  const all = new Set();
  const per = {};
  schemes.forEach((s) => {
    const held = new Set();
    s.measures.forEach((m) => Object.keys(m.by_year || {}).forEach((y) => { held.add(y); all.add(y); }));
    per[s.name] = held;
  });
  const years = { cols: [...all].sort((a, b) => a.localeCompare(b)), per };
  const noYear = years.cols.length ? schemes.filter((s) => per[s.name].size === 0).map((s) => s.name) : [];
  // the busiest districts and the pulse strip follow the first scheme's headline (MGNREGA person-days today)
  const lead = maps[0] || null;
  return { schemes: schemes.map((s) => s.name), tiles, money, noMoney, maps, years, noYear, lead };
}
