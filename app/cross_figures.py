"""
Cross-scheme figures worked out in code (D-066, 2026-10-22).

The 60 cross-scheme UAT cases (`raw_uc/cross_scheme.xlsx`, re-test 2026-10-22,
20/60) failed where the model-written per-scheme answer (D-062) had to add, rank or
compare across schemes: no combined total (T01.1, T04.2), no district ranking
(T15.x), no winner / second place per district (T07.1, T18.x), no "districts
where X > Y" (T03.3). It also dropped MGNREGA ("No MGNREGA figure could be worked
out", T14.x, T20.x), gave PMAY-G's SANCTIONED amount as its money (T12.1, T19.1),
FOCUS producer groups as its beneficiaries (T16.1), copied one scheme's average
onto another (T19.2) and cut FOCUS to its village-mapped rows (T20.1). Every
figure was right somewhere; the arithmetic and the choice of measure were not.

So for the questions whose shape is fully known (beneficiaries / money / village
coverage of MGNREGA, PMAY-G, Focus Plus and Focus Legacy, statewide, for a
district / districts / a block, per district, optionally for one financial year)
each scheme's figures come from a fixed, parameter-bound query, the combine step
(total, ranking, winner, second, condition, per beneficiary) runs here in Python,
and the answer is written here. Anything else (village or block lists, "top ten
villages", other measures, CM Elevate) stays on the D-062 model path.

Measures (docs/SCHEMES.md, the UAT sheet's definitions):
  MGNREGA   beneficiaries = households given work, every FY added (household-years);
            money = SUM(total_exp) lakh / 100 -> crore; villages = distinct village codes.
  PMAY-G    houses (every record); money = amount RELEASED (sanctioned alongside).
  Focus+    distinct beneficiaries; money = amount_disbursed.
  FOCUS     members = SUM(no_of_pg_members) with producer groups alongside; money =
            amount_disbursed. 'Unresolved' rows are left out of village counts ONLY —
            they are real payments and stay in every member / money total (T20.1).
Geography: Focus Plus by the SOURCE district / block name (district_name_raw /
block_name_raw — what its catalogue notes lead with, and what the source file
counts: West Garo Hills 35,059, not the LGD 35,039); every other scheme by the LGD
district / block. One column per scheme, every query (KI-393).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app import db
from app.text_match import Alt, Gap, Matcher, Opt, Seq, W, tokens

logger = logging.getLogger(__name__)

SUPPORTED = ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy")

# ── the per-scheme queries ────────────────────────────────────────────────────
# Each entry: (view, district column, block column, [(metric, SQL expression)]).
# The expressions are fixed strings; every value the user gave is a bound parameter.
_FP_VILL = "COUNT(DISTINCT village_code) FILTER (WHERE village_code > 0 AND entity_type <> 'Unresolved')"
_QUERIES: dict[str, list[tuple[str, str, str, list[tuple[str, str]]]]] = {
    "MGNREGA": [
        ("curated.v_employment", "UPPER(lgd_district)", "UPPER(lgd_block)",
         [("ben", "SUM(households_employed)"), ("villages", "COUNT(DISTINCT village_code)"),
          ("districts", "COUNT(DISTINCT lgd_district)"), ("blocks", "COUNT(DISTINCT lgd_block)")]),
        ("curated.v_expenditure", "UPPER(lgd_district)", "UPPER(lgd_block)",
         [("money", "SUM(total_exp) / 100.0")]),
    ],
    "PMAY-G": [
        ("curated.v_pmay", "UPPER(lgd_district)", "UPPER(lgd_block)",
         [("ben", "COUNT(*)"), ("completed", "COUNT(*) FILTER (WHERE is_completed)"),
          ("money", "SUM(amount_released) / 1e7"), ("sanctioned", "SUM(sanctioned_amount) / 1e7"),
          ("villages", "COUNT(DISTINCT village_code)"),
          ("districts", "COUNT(DISTINCT lgd_district)"), ("blocks", "COUNT(DISTINCT lgd_block)")]),
    ],
    "Focus Plus": [
        ("curated.v_focus_plus", "UPPER(district_name_raw)", "UPPER(block_name_raw)",
         [("ben", "COUNT(DISTINCT beneficiary_key)"), ("payments", "COUNT(*)"),
          ("money", "SUM(amount_disbursed) / 1e7"), ("villages", _FP_VILL),
          ("districts", "COUNT(DISTINCT UPPER(district_name_raw))"),
          ("blocks", "COUNT(DISTINCT UPPER(block_name_raw))")]),
    ],
    "Focus Legacy": [
        ("curated.v_focus_legacy", "UPPER(lgd_district)", "UPPER(lgd_block)",
         [("ben", "SUM(no_of_pg_members)"), ("pgs", "COUNT(DISTINCT pg_id)"), ("payments", "COUNT(*)"),
          ("money", "SUM(amount_disbursed) / 1e7"), ("villages", _FP_VILL),
          ("districts", "COUNT(DISTINCT lgd_district)"), ("blocks", "COUNT(DISTINCT lgd_block)")]),
    ],
}
# Focus Plus names a block another way than LGD for new / urban blocks: a block its
# source names never use is looked up by its LGD block instead.
_FP_LGD_BLOCK = "UPPER(lgd_block)"

STATE = "__state__"


def _sql(view: str, group: "str | None", metrics: list, where: list[str]) -> str:
    sel = ", ".join(f"({e})::float8 AS {m}" for m, e in metrics)
    key = f"{group} AS k" if group else "NULL::text AS k"
    tail = f" AND {group} IS NOT NULL GROUP BY 1" if group else ""
    return f"SELECT {key}, {sel} FROM {view} WHERE {' AND '.join(where) or 'TRUE'}{tail}"


async def _years_held(scheme: str) -> list[int]:
    if scheme not in _YEARS:
        view = _QUERIES[scheme][0][0]
        rows = await db.fetch_rows(f"SELECT DISTINCT year_key AS y FROM {view} WHERE year_key IS NOT NULL", [])
        _YEARS[scheme] = sorted(int(r["y"]) for r in rows)
    return _YEARS[scheme]


_YEARS: dict[str, list[int]] = {}


async def scheme_figures(scheme: str, *, by_district: bool, districts: "list[str] | None" = None,
                         block: "str | None" = None, year: "int | None" = None) -> tuple[dict, list[str]]:
    """{key: {metric: value}} for one scheme (key = STATE, or an upper-case district
    name when by_district), and the SQL run (shown to the user as the query)."""
    out: dict[str, dict] = {}
    shown: list[str] = []
    for view, dcol, bcol, metrics in _QUERIES[scheme]:
        for attempt_bcol in ([bcol, _FP_LGD_BLOCK] if scheme == "Focus Plus" and block else [bcol]):
            where, params = [], []
            if districts:
                params.append([d.upper() for d in districts])
                where.append(f"{dcol} = ANY(${len(params)}::text[])")
            if block:
                params.append(block.upper())
                where.append(f"{attempt_bcol} = ${len(params)}")
            if year is not None:
                params.append(int(year))
                where.append(f"year_key = ${len(params)}")
            sql = _sql(view, dcol if by_district else None, metrics, where)
            rows = [dict(r) for r in await db.fetch_rows(sql, params)]
            got = any(any(v for k, v in r.items() if k != "k") for r in rows)
            if got or attempt_bcol == _FP_LGD_BLOCK or not block or scheme != "Focus Plus":
                shown.append(sql)
                for r in rows:
                    key = STATE if not by_district else str(r["k"])
                    out.setdefault(key, {}).update({m: float(r[m] or 0.0) for m, _e in metrics})
                break
    return out, shown


# ── reading the question ──────────────────────────────────────────────────────

def S(*parts) -> Seq:
    return Seq(*parts, sep="space")


_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20}

_DISTRICT_GRAIN = Matcher(Alt(
    S(W("each", "every", "per", "by"), "district"),
    Seq(W("district"), W("wise", "wide")), W("districtwise"),
    S(W("across", "over", "among"), "districts"),
    S(W("which", "what"), "districts"),
    S("top", Opt(W(*_NUM_WORDS, prefix=False)), "districts"),
    Seq(W("top"), Gap(0, 1), W("districts")),
    S("districts", W("have", "has", "where", "with")),
    S(W("for", "in"), Opt("each"), "district", W("wise")),
))
_WHICH_DISTRICTS = Matcher(Alt(S(W("which", "what"), "districts"), Seq(W("top"), Gap(0, 1), W("districts")),
                               S("districts", W("have", "has", "where", "with"))))
# a grain this module does not answer: village / block lists, years. "Top ten
# highest villages in Mgnrega and pmay" is a village list (D-062's own case), not
# the village count "which scheme reaches the most villages" is.
_PLACES = ("village", "villages", "block", "blocks", "constituency", "constituencies")
_OTHER_GRAIN = Matcher(Alt(
    S(W("each", "every", "per", "by"), W("village", "block", "year", "constituency", "month")),
    Seq(W("village", "block", "year", "constituency"), W("wise")),
    S(W("which", "what"), W(*_PLACES, "years")),
    Seq(W("top", "bottom"), Gap(0, 3), W(*_PLACES)),
    Seq(W("highest", "lowest", "best", "worst", "leading", "largest", "biggest", "smallest", "poorest"),
        Gap(0, 1), W("villages", "blocks", "constituencies")),
    S(W("villages", "blocks", "constituencies"), W("with", "where", "having", "that", "which")),
    S(W("list", "name"), Opt("the"), W("villages", "blocks")),
    W("trend", "trends", "yearly", "annual", "annually"),
    S("over", "the", "years"), S("year", "on", "year"),
))
_MONEY = Matcher(Alt(
    W("money", "amount", "amounts", "spent", "expenditure", "paid", "fund", "funds", "funding", "crore",
      "crores", "lakh", "lakhs", "rupee", "rupees", "cost", "budget", "outlay", "financial", "finance",
      "assistance"),
    W("spend", "disburs", "releas", "invest", prefix=True),
))
_COUNT = Matcher(Alt(
    W("beneficiar", prefix=True),
    W("count", "counts", "people", "households", "household", "houses", "members", "numbers",
      "concentration", "bigger", "larger"),
    S("number", "of"), S("how", "many"), S("producer", "groups"),
))
# "coverage" / "widest" / villages — not the verb "cover" ("how many beneficiaries
# did … each cover in FY 2025-26?" asks for people)
_VILLAGES = Matcher(Alt(W("coverage", "widest", "footprint", "presence", "spread"), W("village", "villages")))
_PERFORMANCE = Matcher(W("performance", "performing", "doing", "perform", "performed"))
_SUMMARY = Matcher(Alt(W("overview"), W("compar", "summar", prefix=True)))
_AVG = Matcher(Alt(S("per", W("beneficiary", "beneficiaries", "head", "house", "member", "household", "person")),
                   W("average", "avg")))
_COMBINED = Matcher(Alt(
    W("combined", "together", "altogether", "aggregate"),
    S("in", "total"), S("grand", "total"), S("sum", "of"),
    Seq(W("total"), Gap(0, 4), W("across", "under")),
))
_RANK = Matcher(Alt(
    W("highest", "higher", "most", "more", "largest", "biggest", "bigger", "larger", "greater", "maximum",
      "leading", "lead", "leads", "top", "best", "widest", "lowest", "lower", "least", "fewest", "less", "fewer",
      "smallest", "smaller", "minimum"),
    W("rank", prefix=True),
    S(W("which", "what"), W("scheme", "one")), S("which", W("is", "has", "of", "reaches", "gave", "provided")),
))
_LOW = Matcher(W("lowest", "least", "fewest", "smallest", "minimum"))
_SECOND = Matcher(W("second", "runner"))
_THAN = Matcher(W("than"))
_MORE = Matcher(W("more", "higher", "greater", "bigger", "larger", "exceed", "exceeds", "outnumber"))
_LESS = Matcher(W("less", "fewer", "lower", "smaller"))
_RANK_MEASURES = Matcher(Alt(W("rank", prefix=True), S("overall", W("performance", "comparison"))))


@dataclass
class Plan:
    schemes: list
    by_district: bool
    districts: "list[str] | None"
    block: "str | None"
    year: "int | None"
    measures: list                       # of "count", "money", "villages"
    op: str                              # list / leader / winner / second / condition / rank_districts
    combined: bool = False
    avg: bool = False
    low: bool = False
    top_n: "int | None" = None
    cond: "tuple | None" = None          # (X, Y, more?) for "districts where X > Y"
    rank_measures: bool = False
    lead_all: bool = False               # a leader line for every measure, not only the first
    first: str = "count"                 # the measure a ranking / comparison is decided on
    place_label: str = "all of Meghalaya"
    period_label: str = "all financial years"
    notes: list = field(default_factory=list)


def _top_n(text: str) -> "int | None":
    toks = tokens(text)
    for i, t in enumerate(toks[:-1]):
        if t.low == "top":
            nxt = toks[i + 1].low
            if nxt.isdigit():
                return int(nxt)
            if nxt in _NUM_WORDS:
                return _NUM_WORDS[nxt]
    return None


def _first_pos(text: str, scheme: str, scheme_matchers: dict) -> int:
    hit = scheme_matchers[scheme].search(text)
    return hit.start() if hit else 10 ** 6


def plan(text: str, schemes: list, resolved: dict, display: "dict | None",
         scheme_matchers: dict) -> "Plan | None":
    """What to compute for a cross-scheme question, or None when its shape is not
    one this module answers (the D-062 model path takes it). `text` is the
    question with any excluded schemes masked out."""
    if any(s not in SUPPORTED for s in (schemes or [])):
        return None                      # CM Elevate / CM Elevate Legacy: the model path
    schemes = [s for s in SUPPORTED if s in schemes]
    if len(schemes) < 2:
        return None
    r = resolved or {}
    if any(r.get(k) for k in ("village_code", "village_code_list", "assembly_constituency", "block_list")):
        return None
    if r.get("year_key_list") or _OTHER_GRAIN.search(text):
        return None
    if _top_n(text) and not _DISTRICT_GRAIN.search(text):
        return None                      # a "top N" of anything but districts is a list
    districts = r.get("district_list") or ([r["district"]] if r.get("district") else None)
    block = r.get("block")
    if block and districts:
        districts = None                 # the block settles the place
    money, count, vill = bool(_MONEY.search(text)), bool(_COUNT.search(text)), bool(_VILLAGES.search(text))
    perf, summary, avg = bool(_PERFORMANCE.search(text)), bool(_SUMMARY.search(text)), bool(_AVG.search(text))
    by_district = bool(_DISTRICT_GRAIN.search(text)) or bool(districts and len(districts) > 1)
    explicit = money or count or vill
    want = {"count": count or avg or not explicit, "money": money or avg, "villages": vill}
    if perf and (money or vill or not explicit):
        # "performance" / "doing" reads as the scale and the money (T08, T14, T20.1)
        want["count"] = want["money"] = True
    if summary and not explicit:
        want["count"] = want["money"] = True
    if vill and (block or districts) and not by_district:
        # coverage of a named place reads with its scale: villages, people, money (T09)
        want["count"] = want["money"] = True
    measures = [m for m in ("count", "money", "villages") if want[m]]
    # the measure a ranking or comparison is decided on
    first = "villages" if vill else ("money" if money and not count and not avg else "count")
    ranked = bool(_RANK.search(text))
    op = "list"
    cond = None
    if by_district:
        if len(schemes) == 2 and _WHICH_DISTRICTS.search(text) and _THAN.search(text) \
                and (_MORE.search(text) or _LESS.search(text)):
            x, y = sorted(schemes, key=lambda s: _first_pos(text, s, scheme_matchers))
            cond, op = (x, y, not _LESS.search(text)), "condition"
        elif _SECOND.search(text):
            op = "second"
        elif _WHICH_DISTRICTS.search(text) and (ranked or _top_n(text)):
            op = "rank_districts"
        elif ranked:
            op = "winner"
    elif ranked or len(schemes) == 2 or perf or summary:
        op = "leader"
    year = r.get("year_key")
    p = Plan(schemes=schemes, by_district=by_district, districts=districts, block=block,
             year=int(year) if year else None, measures=measures, op=op, cond=cond, first=first,
             combined=bool(_COMBINED.search(text)) and op in ("list", "leader") and not ranked,
             avg=avg, low=bool(_LOW.search(text)), top_n=_top_n(text),
             rank_measures=bool(_RANK_MEASURES.search(text)) and not by_district,
             lead_all=perf or (count and money))
    disp = display or {}
    if block:
        p.place_label = f"{str(disp.get('block') or block).title()} block"
    elif districts and len(districts) == 1:
        p.place_label = f"{districts[0].title()} district"
    elif districts:
        p.place_label = ", ".join(d.title() for d in districts)
    if p.year is not None:
        p.period_label = f"FY {p.year}-{(p.year + 1) % 100:02d}"
    return p


# ── formatting ────────────────────────────────────────────────────────────────

def indian(n: float) -> str:
    """1873378 -> '18,73,378'."""
    neg, s = n < 0, str(int(round(abs(float(n or 0)))))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts + [tail])
    return ("-" if neg else "") + s


def rupees_crore(c: float) -> str:
    """₹ crore, or ₹ lakh below one crore (₹52.38 lakh, not ₹0.52 crore)."""
    if abs(c) < 1:
        return f"₹{c * 100:,.2f} lakh"
    whole, frac = f"{c:.2f}".split(".")
    return f"₹{indian(float(whole))}.{frac} crore"


SHORT = {"MGNREGA": "MGNREGA", "PMAY-G": "PMAY-G", "Focus Plus": "Focus Plus", "Focus Legacy": "Focus Legacy"}
_BEN_NOUN = {"MGNREGA": "households given work", "PMAY-G": "houses sanctioned",
             "Focus Plus": "beneficiaries", "Focus Legacy": "members"}
_MONEY_VERB = {"MGNREGA": "spent", "PMAY-G": "released", "Focus Plus": "disbursed", "Focus Legacy": "disbursed"}


def count_text(s: str, f: dict, short: bool = False) -> str:
    n = indian(f.get("ben", 0))
    if s == "PMAY-G":
        return n if short else f"{n} houses sanctioned ({indian(f.get('completed', 0))} completed)"
    if s == "Focus Legacy":
        return f"{n} members ({indian(f.get('pgs', 0))} PGs)" if short else \
            f"{n} members in {indian(f.get('pgs', 0))} producer groups"
    return n if short else f"{n} {_BEN_NOUN[s]}"


def money_text(s: str, f: dict, short: bool = False) -> str:
    m = rupees_crore(f.get("money", 0))
    if short:
        return m
    if s == "PMAY-G":
        return f"{m} released (sanctioned {rupees_crore(f.get('sanctioned', 0))})"
    return f"{m} {_MONEY_VERB[s]}"


def villages_text(f: dict, state: bool) -> str:
    v = f"{indian(f.get('villages', 0))} villages"
    if state:
        return f"{indian(f.get('districts', 0))} districts, {indian(f.get('blocks', 0))} blocks, {v}"
    return v


def avg_value(f: dict) -> "float | None":
    return f["money"] * 1e7 / f["ben"] if f.get("ben") and f.get("money") is not None else None


_PER = {"MGNREGA": "per household-year", "PMAY-G": "per house", "Focus Plus": "per beneficiary",
        "Focus Legacy": "per member"}


def primary(p: Plan) -> str:
    """The one measure a ranking or comparison is decided on."""
    return p.first if p.first in p.measures else p.measures[0]


def value(f: dict, measure: str) -> float:
    return float(f.get({"count": "ben", "money": "money", "villages": "villages"}[measure], 0.0) or 0.0)


def measure_noun(measure: str) -> str:
    return {"count": "beneficiaries", "money": "money", "villages": "villages covered"}[measure]


def fmt(s: str, f: dict, measure: str) -> str:
    if measure == "money":
        return rupees_crore(f.get("money", 0))
    if measure == "villages":
        return f"{indian(f.get('villages', 0))} villages"
    return f"{indian(f.get('ben', 0))} members" if s == "Focus Legacy" else indian(f.get("ben", 0))


# ── computing and writing the answer ──────────────────────────────────────────

async def answer(p: Plan) -> dict:
    """{'answer', 'rows', 'sql'} for a plan."""
    figs: dict[str, dict] = {}
    totals: dict[str, dict] = {}
    shown: list[str] = []
    gaps: dict[str, str] = {}
    for s in p.schemes:
        if p.year is not None:
            held = await _years_held(s)
            if p.year not in held:
                gaps[s] = (f"{s} has no data for {p.period_label} (its data covers FY "
                           f"{held[0]}-{(held[0] + 1) % 100:02d} to {held[-1]}-{(held[-1] + 1) % 100:02d})"
                           if held else f"{s} records no financial year")
                continue
        got, sql = await scheme_figures(s, by_district=p.by_district, districts=p.districts,
                                        block=p.block, year=p.year)
        figs[s], shown = got, shown + sql
        if p.by_district and got:
            # the statewide total, not the sum of the districts: a record with no
            # district (one Focus Plus beneficiary) still counts
            tot, sql_t = await scheme_figures(s, by_district=False, districts=p.districts, year=p.year)
            totals[s] = tot.get(STATE, {})
    have = [s for s in p.schemes if s in figs and figs[s]]
    for s in p.schemes:
        if s in figs and not figs[s]:
            gaps[s] = f"{s} has no records for {p.place_label}"
    lines = [_header(p)]
    if p.by_district:
        lines += _district_lines(p, figs, have, totals)
    else:
        lines += _state_lines(p, {s: figs[s].get(STATE, {}) for s in have}, have)
    if gaps:
        lines.append(" ".join(f"{g}." for g in gaps.values()))
    rows = _rows(p, figs, have)
    logger.info("cross figures (D-066): %s %s op=%s measures=%s by_district=%s", p.schemes, p.place_label,
                p.op, p.measures, p.by_district)
    return {"answer": "\n".join(ln for ln in lines if ln is not None), "rows": rows, "sql": "\n;\n".join(shown)}


def _header(p: Plan) -> str:
    return f"**{p.place_label[0].upper() + p.place_label[1:]}, {p.period_label}**"


def _scheme_line(s: str, f: dict, p: Plan, state: bool) -> str:
    parts = []
    if "count" in p.measures:
        parts.append(count_text(s, f))
    if "money" in p.measures:
        parts.append(money_text(s, f))
    if "villages" in p.measures:
        parts.append(villages_text(f, state and not (p.block or p.districts)))
    if p.avg and avg_value(f):
        parts.append(f"₹{indian(avg_value(f))} {_PER[s]}")
    return f"- **{SHORT[s]}:** " + ", ".join(parts)


def _state_lines(p: Plan, f: dict, have: list) -> list:
    out = [_scheme_line(s, f[s], p, True) for s in have]
    if "count" in p.measures and "MGNREGA" in have and p.year is None:
        out.append("MGNREGA counts a household once for each financial year it was given work (FY 2022-23 "
                   "to 2025-26 added).")
    if len(have) < 2:
        return out
    if p.combined:
        if "count" in p.measures:
            tot = sum(value(f[s], "count") for s in have)
            parts = " + ".join(f"{indian(value(f[s], 'count'))} {_BEN_NOUN[s]}" for s in have)
            out.append(f"**Combined: {indian(tot)}** ({parts}; these count different things, added "
                       "because the question asks for the total).")
        if "money" in p.measures:
            out.append(f"**Combined: {rupees_crore(sum(value(f[s], 'money') for s in have))}**.")
    if p.avg:
        avgs = {s: avg_value(f[s]) for s in have if avg_value(f[s])}
        if avgs:
            top = max(avgs, key=avgs.get) if not p.low else min(avgs, key=avgs.get)
            out.append(f"Most money per beneficiary: **{top}** (₹{indian(avgs[top])} {_PER[top]}). Order: "
                       + " > ".join(f"{s} ₹{indian(avgs[s])}" for s in sorted(avgs, key=avgs.get, reverse=True)) + ".")
    if p.op == "leader" or p.rank_measures:
        ms = p.measures if (p.rank_measures or p.lead_all) else [primary(p)]
        for m in ms:
            out.append(_leader_sentence(m, f, have, p.low and len(ms) == 1))
    return out


def _leader_sentence(m: str, f: dict, have: list, low: bool) -> str:
    order = sorted(have, key=lambda s: value(f[s], m), reverse=not low)
    lead, nxt = order[0], order[1]
    word = "lowest" if low else ("most " + measure_noun(m) if m != "money" else "most money")
    head = f"**{lead}** has the {word} ({fmt(lead, f[lead], m)})"
    if len(order) == 2:
        a, b = value(f[lead], m), value(f[nxt], m)
        diff = abs(a - b)
        d = rupees_crore(diff) if m == "money" else indian(diff)
        ratio = f", {a / b:.2f}x" if b and not low else ""
        return f"{head}, {d} more than {nxt} ({fmt(nxt, f[nxt], m)}{ratio})."
    return head + ". Order: " + " > ".join(f"{s} ({fmt(s, f[s], m)})" for s in order) + "."


def _district_lines(p: Plan, figs: dict, have: list, totals: "dict | None" = None) -> list:
    keys = sorted({k for s in have for k in figs[s] if k != STATE})
    if p.districts:
        keys = [k for k in keys if k in {d.upper() for d in p.districts}]
    m = primary(p)
    out = []
    if p.op == "condition":
        x, y, more = p.cond
        hits = [k for k in keys if (value(figs[x].get(k, {}), m) > value(figs[y].get(k, {}), m)) == more
                and value(figs[x].get(k, {}), m) != value(figs[y].get(k, {}), m)]
        rel = "more" if more else "fewer"
        noun = measure_noun(m) if m != "money" else "money"
        if hits:
            out.append(f"{x} has {rel} {noun} than {y} in **{len(hits)} of {len(keys)} districts**: "
                       + "; ".join(f"{k.title()} ({fmt(x, figs[x][k], m)} vs {fmt(y, figs[y].get(k, {}), m)})"
                                   for k in hits) + ".")
        else:
            out.append(f"{x} has {rel} {noun} than {y} in none of the {len(keys)} districts.")
        out.append("All districts:")
    elif p.op in ("winner", "second"):
        pos = 1 if p.op == "second" else 0
        tally: dict[str, int] = {}
        per = []
        for k in keys:
            order = sorted(have, key=lambda s: value(figs[s].get(k, {}), m), reverse=not p.low)
            if len(order) <= pos:
                continue
            w = order[pos]
            tally[w] = tally.get(w, 0) + 1
            nxt = order[pos + 1] if len(order) > pos + 1 else None
            per.append(f"- {k.title()}: **{w}** ({fmt(w, figs[w].get(k, {}), m)})"
                       + (f"; next {nxt} ({fmt(nxt, figs[nxt].get(k, {}), m)})" if nxt and p.op == "winner" else "")
                       + (f"; first {order[0]} ({fmt(order[0], figs[order[0]].get(k, {}), m)})" if pos else ""))
        place = "second" if pos else ("lowest" if p.low else "highest")
        if len(tally) == 1:
            w = next(iter(tally))
            out.append(f"**{w}** is {place} in all {sum(tally.values())} districts.")
        else:
            out.append(f"{'Second place' if pos else ('Lowest' if p.low else 'Highest')} by district: "
                       + ", ".join(f"**{w}** in {n} district{'s' if n > 1 else ''}"
                                   for w, n in sorted(tally.items(), key=lambda x: -x[1])) + ".")
        return out + per
    elif p.op == "rank_districts":
        tot = {k: sum(value(figs[s].get(k, {}), m) for s in have) for k in keys}
        order = sorted(keys, key=lambda k: tot[k], reverse=not p.low)
        grand = sum(tot.values()) or 1
        n = p.top_n or len(order)
        what = "money" if m == "money" else ("villages" if m == "villages" else "beneficiaries")
        out.append(f"{'Bottom' if p.low else 'Top'} {min(n, len(order))} districts by combined {what} "
                   f"({' + '.join(have)}):")
        for i, k in enumerate(order[:n], 1):
            t = rupees_crore(tot[k]) if m == "money" else indian(tot[k])
            out.append(f"{i}. **{k.title()}**: {t} ({tot[k] / grand * 100:.1f}%) — "
                       + ", ".join(f"{s} {fmt(s, figs[s].get(k, {}), m)}" for s in have))
        if m == "count":
            out.append("The combined figure adds different counts (" + ", ".join(
                f"{s} {_BEN_NOUN[s]}" for s in have) + ").")
        if n < len(order):
            last = order[-1] if not p.low else order[0]
            out.append(f"{'Highest' if p.low else 'Lowest'}: {last.title()} "
                       f"({rupees_crore(tot[last]) if m == 'money' else indian(tot[last])}).")
        return out
    # the per-district table
    for k in keys:
        cells = []
        for s in have:
            f = figs[s].get(k, {})
            parts = []
            if "count" in p.measures:
                parts.append(count_text(s, f, short=True))
            if "money" in p.measures:
                parts.append(money_text(s, f, short=True))
            if "villages" in p.measures:
                parts.append(f"{indian(f.get('villages', 0))} villages")
            cells.append(f"{SHORT[s]} {' / '.join(parts)}")
        line = f"- {k.title()}: " + " | ".join(cells)
        if "money" in p.measures and "count" not in p.measures:
            line += f" | Total {rupees_crore(sum(value(figs[s].get(k, {}), 'money') for s in have))}"
        if len(have) == 2 and p.op != "condition":
            order = sorted(have, key=lambda s: value(figs[s].get(k, {}), m), reverse=True)
            if value(figs[order[0]].get(k, {}), m) != value(figs[order[1]].get(k, {}), m):
                line += f" → {order[0]}"
        out.append(line)
    tot_parts = []
    for s in have:
        t = {mm: value((totals or {}).get(s) or {}, mm) if (totals or {}).get(s) else
             sum(value(figs[s].get(k, {}), mm) for k in keys) for mm in ("count", "money", "villages")}
        bits = []
        if "count" in p.measures:
            bits.append(indian(t["count"]))
        if "money" in p.measures:
            bits.append(rupees_crore(t["money"]))
        tot_parts.append(f"{SHORT[s]} {' / '.join(bits)}" if bits else None)
    tot_parts = [x for x in tot_parts if x]
    if tot_parts:
        label = "Total for these districts" if p.districts else "Total"
        out.append(f"**{label}:** " + " | ".join(tot_parts))
    if len(have) == 2 and p.op != "condition":
        lead = {s: 0 for s in have}
        for k in keys:
            a, b = (value(figs[s].get(k, {}), m) for s in have)
            if a != b:
                lead[have[0] if a > b else have[1]] += 1
        out.append(f"{have[0]} leads in {lead[have[0]]} district{'s' if lead[have[0]] != 1 else ''}, "
                   f"{have[1]} in {lead[have[1]]}.")
    if "count" in p.measures and "Focus Plus" in have and any(
            figs["Focus Plus"].get(k) for k in keys) and not p.districts:
        out.append("District = the district written in each scheme's own records (Focus Plus: its source "
                   "file's district names).")
    return out


def _rows(p: Plan, figs: dict, have: list) -> list[dict]:
    """The result table: one row per scheme (and district), the figures in clear columns."""
    rows = []
    for s in have:
        for k, f in sorted(figs[s].items()):
            if p.districts and p.by_district and k.upper() not in {d.upper() for d in p.districts}:
                continue
            r = {"district": k.title()} if k != STATE else {}
            r["scheme"] = s
            r[{"MGNREGA": "households_given_work", "PMAY-G": "houses_sanctioned", "Focus Plus": "beneficiaries",
               "Focus Legacy": "members"}[s]] = int(f.get("ben", 0))
            if s == "PMAY-G":
                r["houses_completed"] = int(f.get("completed", 0))
            if s == "Focus Legacy":
                r["producer_groups"] = int(f.get("pgs", 0))
            r["amount_crore"] = round(f.get("money", 0.0), 2)
            if s == "PMAY-G":
                r["sanctioned_crore"] = round(f.get("sanctioned", 0.0), 2)
            r["villages"] = int(f.get("villages", 0))
            rows.append(r)
    return rows
