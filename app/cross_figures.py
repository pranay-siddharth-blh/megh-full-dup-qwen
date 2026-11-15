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
  FOCUS     members = SUM(no_of_pg_members) (producer groups alongside when asked); money =
            amount_disbursed. 'Unresolved' rows are left out of village counts ONLY —
            they are real payments and stay in every member / money total (T20.1).
Only what was asked is shown (user report 2026-10-27: "Compare beneficiaries in mgnrega
and PMAY-G" also showed money, villages, sanctioned amounts and completed houses, and
the comparison card compared money): the table carries the asked measures' columns,
the count in ONE `beneficiaries` column for every scheme, and PMAY-G's completed
houses / FOCUS's producer groups only when asked or for a broad overview.
Geography: Focus Plus by the SOURCE district / block name (district_name_raw /
block_name_raw — what its catalogue notes lead with, and what the source file
counts: West Garo Hills 35,059, not the LGD 35,039); every other scheme by the LGD
district / block. One column per scheme, every query (KI-393).

D-097 (2026-10-30, Cross Scheme Test Cases sheet re-run): CM Elevate and CM Elevate
Legacy are on this path too, and so are a village and an assembly constituency.
Every combination with either CM Elevate dataset (41 of the 57) and every village /
constituency question went to the model path, where the same question timed out
(84-121 s), lost MGNREGA, gave PMAY-G's sanctioned amount, added village counts
across schemes ("97 villages across all schemes") or said "24 districts".
  CM Elevate         applications = COUNT(DISTINCT request_id); no money, no financial
                     year (said, never 0); villages = distinct codes, 'Unresolved' out.
  CM Elevate Legacy  applicants sanctioned = records with a sanctioned amount (2,820,
                     the scheme's own rule, KI-166); money = total_disbursement
                     (subsidy + loan); villages as above.
  Constituency       MGNREGA assembly_constituency_name; PMAY-G, Focus Legacy and CM
                     Elevate Legacy ac_name (D-096); Focus Plus and CM Elevate do not
                     record one (c13 _CROSS_AC_RECORDED says so, Plan.gaps).
  Village            village_code, with each scheme's own village filter
                     (cross_scheme.SPECS).
A combined total or a combined district ranking leaves CM Elevate out (its
applications are not beneficiaries; chat UI audit I-13) and says so.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app import cross_registry, cross_scheme, db
from app.config import settings
from app.text_match import ANY, Alt, Gap, Matcher, Opt, Seq, W, tokens

logger = logging.getLogger(__name__)

# Every per-scheme table below is BUILT from data/cross_scheme.yaml (app/cross_registry.py, 2026-11-14): the
# queries, the nouns and money verbs, which schemes hold no money / no year / no constituency, the village filters.
# Onboarding a scheme is one entry there; nothing in this module names a scheme for those roles.
#
# the four main schemes: what an exclusion leaves ("leaving out MGNREGA, which
# scheme …" compares the other three, D-066)
MAIN = cross_registry.main()
SUPPORTED = cross_registry.ORDER
# records no money / no financial year at all (said plainly, never shown as 0). A scheme with no money declares
# `money: null` and has no "money" metric (2026-11-14: Homestay records no money and counts applications, but the
# hand-kept sets still named only CM Elevate, and an all-schemes money / per-year question raised KeyError).
NO_YEAR = cross_registry.no_year()
# the schemes a constituency filter can read (the others do not record one); the
# column is per view: MGNREGA employment carries its own assembly_constituency_name
# (the column its scheme answers use), every other view the geography's ac_name
_AC_COL = cross_registry.ac_col()
_AC_VIEW_COL = cross_registry.ac_view_col()

# ── the per-scheme queries ────────────────────────────────────────────────────
# Each entry: (view, district column, block column, [(metric, SQL expression)]).
# The expressions are fixed strings; every value the user gave is a bound parameter.
_QUERIES: dict[str, list[tuple[str, str, str, list[tuple[str, str]]]]] = cross_registry.queries()
# Focus Plus names a block another way than LGD for new / urban blocks: a block its
# source names never use is looked up by its LGD block instead (`block_fallback`)
_BLOCK_FALLBACK = cross_registry.block_fallback()

STATE = "__state__"


def _block_names(block: str) -> list[str]:
    """The stored spellings of one block. The Tura urban body is stored twice —
    'TURA MUNICIPAL BOARD' (CM Elevate 28 applications, CM Elevate Legacy) and
    'TURA MUNICIPAL BOARD-MUNICIPAL BOARD' (CM Elevate 77, Focus Plus) — and both
    are the one block (KI-275; cross-scheme run 2026-10-13 counted both, 105)."""
    b = block.upper()
    base = b[:-len("-MUNICIPAL BOARD")] if b.endswith("-MUNICIPAL BOARD") else b
    if base == "TURA MUNICIPAL BOARD":
        return [base, base + "-MUNICIPAL BOARD"]
    return [b]

# a scheme whose specs hold no "money" expression records no money (CM Elevate, Homestay)
NO_MONEY = cross_registry.no_money()


def has_measure(scheme: str, measure: str) -> bool:
    """Whether a scheme records the measure at all (CM Elevate: no money)."""
    return not (measure in ("money", "avg") and scheme in NO_MONEY)


def _sql(view: str, group: "str | None", metrics: list, where: list[str]) -> str:
    sel = ", ".join(f"({e})::float8 AS {m}" for m, e in metrics)
    key = f"{group} AS k" if group else "NULL::text AS k"
    tail = f" AND {group} IS NOT NULL GROUP BY 1" if group else ""
    return f"SELECT {key}, {sel} FROM {view} WHERE {' AND '.join(where) or 'TRUE'}{tail}"


async def _years_held(scheme: str) -> list[int]:
    if scheme in NO_YEAR:
        return []
    if scheme not in _YEARS:
        view = _QUERIES[scheme][0][0]
        rows = await db.fetch_rows(f"SELECT DISTINCT year_key AS y FROM {view} WHERE year_key IS NOT NULL", [])
        _YEARS[scheme] = sorted(int(r["y"]) for r in rows)
    return _YEARS[scheme]


_YEARS: dict[str, list[int]] = {}


async def scheme_figures(scheme: str, *, by_district: bool, districts: "list[str] | None" = None,
                         block: "str | None" = None, year: "int | None" = None,
                         by_year: bool = False, years: "list[int] | None" = None,
                         village: "int | None" = None, ac: "str | None" = None,
                         grain: str = "district", specs: "list | None" = None) -> tuple[dict, list[str]]:
    """{key: {metric: value}} for one scheme (key = STATE, or an upper-case district
    name when by_district), and the SQL run (shown to the user as the query).
    `village` = one LGD village code (each scheme's own village filter applies);
    `ac` = an assembly constituency name (a scheme that records none gives {});
    `specs` = other queries in the _QUERIES shape (the headline figure), else the scheme's own."""
    out: dict[str, dict] = {}
    shown: list[str] = []
    if ac and scheme not in _AC_COL:
        return out, shown
    fallback = _BLOCK_FALLBACK.get(scheme)
    for view, dcol, bcol, metrics in (_QUERIES[scheme] if specs is None else specs):
        tries = [bcol, fallback] if fallback and block else [bcol]
        for attempt, attempt_bcol in enumerate(tries):
            where, params = [], []
            if districts:
                params.append([d.upper() for d in districts])
                where.append(f"{dcol} = ANY(${len(params)}::text[])")
            if block:
                params.append(_block_names(block))
                where.append(f"{attempt_bcol} = ANY(${len(params)}::text[])")
            if village is not None:
                params.append(int(village))
                where.append(f"village_code = ${len(params)}")
                where.append(cross_scheme.SPECS[scheme].village_where)
            if ac:
                params.append(str(ac).upper())
                where.append(f"{_AC_VIEW_COL.get(view, _AC_COL[scheme])} = ${len(params)}")
            if year is not None:
                params.append(int(year))
                where.append(f"year_key = ${len(params)}")
            if years:
                params.append([int(y) for y in years])
                where.append(f"year_key = ANY(${len(params)}::int[])")
            gcol = (bcol if grain == "block" else dcol) if by_district else None
            sql = _sql(view, "year_key" if by_year else gcol, metrics, where)
            rows = [dict(r) for r in await db.fetch_rows(sql, params)]
            got = any(any(v for k, v in r.items() if k != "k") for r in rows)
            if got or attempt == len(tries) - 1:
                shown.append(sql)
                for r in rows:
                    if by_year and r["k"] is None:
                        continue             # CM Elevate Legacy: 395 records carry no year (c06)
                    key = str(int(r["k"])) if by_year else (STATE if not by_district else str(r["k"]))
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
# "widest coverage across (the) districts of Meghalaya" asks how many districts each
# scheme spans — the statewide reach, not a per-district winner (Cross Scheme sheet
# CROSS-13, re-run 2026-10-30). "each / per district", "district-wise" still group.
_ACROSS_DISTRICTS = Matcher(S(W("across", "over", "among"), Opt(Alt("the", "all")), "districts"))
_PER_DISTRICT = Matcher(Alt(S(W("each", "every", "per", "by"), "district"), Seq(W("district"), W("wise", "wide")),
                            W("districtwise")))
# "block-wise", "each block", "per block": one row per block (of the named district,
# or of the state) — the same table as per district (D-097, Cross Scheme sheet BW cases)
_BLOCK_GRAIN = Matcher(Alt(
    S(W("each", "every", "per", "by"), "block"), Seq(W("block"), W("wise")), W("blockwise"),
    S(W("across", "over", "among"), "blocks"), S(W("for", "in"), Opt("each"), "block", W("wise")),
))
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
# the place-list part of _OTHER_GRAIN (everything but the time words)
_OTHER_PLACES = Matcher(Alt(
    S(W("each", "every", "per", "by"), W("village", "block", "constituency")),
    Seq(W("village", "block", "constituency"), W("wise")),
    S(W("which", "what"), W(*_PLACES)),
    Seq(W("top", "bottom"), Gap(0, 3), W(*_PLACES)),
    Seq(W("highest", "lowest", "best", "worst", "leading", "largest", "biggest", "smallest", "poorest"),
        Gap(0, 1), W("villages", "blocks", "constituencies")),
    S(W("villages", "blocks", "constituencies"), W("with", "where", "having", "that", "which")),
    S(W("list", "name"), Opt("the"), W("villages", "blocks")),
))
# G-8 / I-5 (audit 2026-10-29): "villages where both schemes are present", "how many
# villages are covered by MGNREGA or PMAY-G", "which villages have only PMAY-G": the
# union and the overlap of the villages, never the per-scheme counts added up.
_OVERLAP = Matcher(Alt(
    W("both", "either", "overlap", "overlapping", "common", "shared", "union"),
    S("only", W("in", "under", "by")), S(W("covered", "reached", "served"), "by", ANY, "or"),
    Seq(W("in", "under"), W("all"), W("of", "the", "four", "three")),
))
_LIST_VILLAGES = Matcher(Alt(S(W("which", "what", "list", "name", "show"), Opt("the"), W("villages", "village")),
                             S("villages", W("where", "that", "which", "with", "having")),
                             Seq(W("where", "with", "having", "have", "has"), Gap(0, 2), W("both", "all"))))
_MONTHLY = Matcher(Alt(S(W("each", "every", "per", "by"), W("month", "quarter")), Seq(W("month"), W("wise")),
                       W("monthly", "quarterly")))
# the time words of _OTHER_GRAIN: a district ranking "year wise" is still a per-year question
_YEARLY = Matcher(Alt(
    S(W("each", "every", "per", "by"), W("year", "month")), Seq(W("year"), W("wise")),
    S(W("which", "what"), "years"), W("trend", "trends", "yearly", "annual", "annually"),
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
    # "beneficiary / application count": CM Elevate's count is its applications
    # (D-097, 2026-10-30; they were B-7's "other measure" while it was off this path)
    W("application", "applications", "applicant", "applicants"),
    S("number", "of"), S("how", "many"), S("producer", "groups"),
))
# "coverage" / "widest" / villages — not the verb "cover" ("how many beneficiaries
# did … each cover in FY 2025-26?" asks for people)
_VILLAGES = Matcher(Alt(W("coverage", "widest", "footprint", "presence", "spread"), W("village", "villages")))
_PERFORMANCE = Matcher(W("performance", "performing", "doing", "perform", "performed"))
# a scheme's own detail beside its count: PMAY-G completed houses, FOCUS producer groups
_COMPLETED = Matcher(W("complet", prefix=True))
_PGS = Matcher(Alt(S("producer", W("group", "groups")), W("pg", "pgs")))
# B-14 (audit 2026-10-29): "vs", "versus" and "difference" ask what "compare" asks
_SUMMARY = Matcher(Alt(W("overview", "vs", "versus", "difference"), W("compar", "summar", prefix=True)))
# B-8: "which is better / worse" names no measure a scheme could be ranked on
_BETTER = Matcher(W("better", "worse", "best", "worst", "good", "bad", "superior", "effective"))
# B-7: measures this module does not compute (person days, job cards, applications …):
# the per-scheme path answers them, and each scheme says what it records
_OTHER_MEASURE = Matcher(Alt(S("person", W("day", "days")), W("persondays", "mandays", "manday"),
                             S("job", W("card", "cards")), W("jobcard", "jobcards",
                                                              "wage", "wages", "instalment", "instalments",
                                                              "installment", "installments", "tranche", "tranches")))
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
# "headline figures", "key statistics", "a snapshot of every scheme" with no measure word: each scheme's own lead
# figure (op "headline"); "numbers" stays a count (_COUNT), "overview" / "summary" stay count + money (_SUMMARY)
_HEADLINE = Matcher(W("headline", "headlines", "figure", "figures", "statistics", "stats", "snapshot", "glance",
                      "kpi", "kpis"))


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
    completed: bool = False              # PMAY-G completed houses beside its count
    pgs: bool = False                    # FOCUS producer groups beside its members
    place_label: str = "all of Meghalaya"
    period_label: str = "all financial years"
    notes: list = field(default_factory=list)
    both: bool = False                   # "top 5 and bottom 5 districts" (I-12)
    nth: "int | None" = None             # "second highest district"
    exclude: list = field(default_factory=list)   # districts left out ("excluding …", I-19)
    left_out: list = field(default_factory=list)  # named schemes this module cannot rank (I-13)
    years: "list | None" = None          # op by_year: the years asked ([] = every year held)
    list_villages: bool = False          # op overlap: name the villages, not only count them
    better: bool = False                 # "which is better": figures side by side, no winner (B-8)
    village: "int | None" = None         # one LGD village code (D-097)
    ac: "str | None" = None              # an assembly constituency, upper case (D-097)
    # {scheme: why it has no figure here} from c13 _cross_scheme_gaps (a constituency
    # it does not record, a year it has no data for, money for CM Elevate): said,
    # never queried (D-097)
    gaps: dict = field(default_factory=dict)
    grain: str = "district"              # by_district rows are per district, or per block (D-097)
    # a name shared by 2-3 villages (c09 village_twins, D-096 / KI-630): {code: label};
    # one row per village and scheme, never summed (grain "village")
    villages: dict = field(default_factory=dict)


# ── rank words at a place level (audit 2026-10-29, I-1 / I-3 / I-4 / I-14 / I-16 / I-18) ──
# "bottom 5 districts", "5 lowest districts", "which district has the lowest",
# "best 3 districts", "highest district", "rank districts by", "kis district me sabse
# jyada" were all answered as "which scheme is bigger statewide": only "top N
# districts", plural "which districts" and "districts with" read as a district
# ranking. A place level (singular or plural, a near-miss spelling) beside any rank
# word is a ranking at that level, never a scheme leader.
_HIGH_RANK = frozenset({"top", "highest", "most", "maximum", "max", "best", "leading", "leads", "lead", "largest",
                        "biggest", "greatest", "strongest"})  # "leads": the question bank's A10 (2026-11-15)
_LOW_RANK = frozenset({"bottom", "lowest", "least", "fewest", "minimum", "min", "worst", "poorest", "weakest",
                       "smallest", "lagging"})
# Hinglish: "sabse jyada" (most), "sabse kam" (least); "kis / kaun sa district" (which district)
_HINGLISH_HIGH = frozenset({"jyada", "zyada", "jada", "zada", "jiyada", "adhik"})
_WHICH = frozenset({"which", "what", "kis", "kaun", "kaunsa", "konsa", "kon"})
# between a rank word and its level: "top 5 districts", "least performing blocks"
_RANK_FILLER = frozenset({"performing", "perform", "performance", "scoring", "ranked", "most"})
_AMOUNT_RANK = frozenset({"most", "least", "fewest", "maximum", "minimum", "max", "min"})
_ORDINALS = {"second": 2, "2nd": 2, "third": 3, "3rd": 3}
_LEVEL_FORMS = {"district": ("district", "districts", "distt"), "block": ("block", "blocks"),
                "village": ("village", "villages"), "constituency": ("constituency", "constituencies")}


def _edit1(a: str, b: str) -> bool:
    """a and b differ by at most one inserted, deleted or changed letter."""
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i:] == b[i + 1:] or a[i + 1:] == b[i:]


def _level(word: str) -> "str | None":
    """'district' / 'block' / 'village' / 'constituency' for a level word, singular,
    plural or one letter off ("districs", "distric", "vilages"); else None."""
    for level, forms in _LEVEL_FORMS.items():
        if word in forms:
            return level
    if len(word) >= 7:
        for level in ("district", "village"):
            if _edit1(word, level) or _edit1(word, level + "s"):
                return level
    return None


def _rank_dir(words: list, i: int) -> "str | None":
    """'high' / 'low' when words[i] is a rank word ("sabse jyada" / "sabse kam" read
    at their second word)."""
    w = words[i]
    if w in _HIGH_RANK:
        return "high"
    if w in _LOW_RANK:
        return "low"
    if i and words[i - 1] == "sabse":
        return "high" if w in _HINGLISH_HIGH else ("low" if w == "kam" else None)
    return None


@dataclass
class RankAsk:
    level: str                      # district / block / village / constituency
    high: bool
    low: bool
    nth: "int | None" = None        # "second highest district"


def rank_ask(text: str) -> "RankAsk | None":
    """The ranking a question asks at a place level, or None. Every rank word
    in the question sets the direction, so "top 5 and bottom 5 districts" is both."""
    w = [t.low for t in tokens(text)]
    dirs = {_rank_dir(w, i) for i in range(len(w))} - {None}
    if not dirs and not any(x in ("rank", "ranked", "ranking", "rankwise") for x in w):
        return None
    level, nth = None, None
    for i in range(len(w)):
        d = _rank_dir(w, i)
        if d:
            # a rank word, then numbers / "performing", then the level word:
            # "top 5 districts", "5 lowest districts", "least performing blocks"
            j = i + 1
            while j < len(w) and (w[j].isdigit() or w[j] in _NUM_WORDS or w[j] in _RANK_FILLER):
                j += 1
            # "the most villages" / "fewest districts" is the villages / districts
            # MEASURE ("which scheme reaches the most villages"), not a ranking of them
            amount = j == i + 1 and j < len(w) and w[i] in _AMOUNT_RANK and w[j].endswith("s")
            if j < len(w) and _level(w[j]) and not amount:
                level = level or _level(w[j])
                if i and w[i - 1] in _ORDINALS:
                    nth = _ORDINALS[w[i - 1]]
        lv = _level(w[i])
        if lv and i and w[i - 1] in _WHICH and any(_rank_dir(w, k) for k in range(i + 1, len(w))):
            level = level or lv              # "which district has the lowest …", "kis district me sabse jyada"
        if lv and i + 1 < len(w) and w[i + 1] in ("with", "having", "has", "have", "got", "ranked", "by") \
                and any(_rank_dir(w, k) for k in range(i + 1, min(len(w), i + 5))):
            level = level or lv              # "district having highest …", "districts with the most …"
        if lv and i + 1 < len(w) and w[i + 1] in ("ranked", "rankwise"):
            level = level or lv              # "districts ranked by villages"
        if lv and i and (w[i - 1] in ("rank", "ranking") or (i > 1 and w[i - 1] in ("all", "the")
                                                             and w[i - 2] in ("rank", "ranking"))):
            level = level or lv              # "rank (all) districts by …"
    if level is None:
        return None
    return RankAsk(level=level, high="high" in dirs or not dirs, low="low" in dirs, nth=nth)


def _one_place_asked(text: str, level: str) -> bool:
    """The ranked level is said in the SINGULAR with no number: "which district leads in each scheme", "top district
    for every scheme" ask for the one leader per scheme, not every district in order (question bank A10, 2026-11-15).
    "Which districts …", "rank the districts …" and "top 5 districts" stay full / N rankings."""
    w = [t.low for t in tokens(text)]
    return level in w and (level + "s") not in w and _top_n(text) is None


def _top_n(text: str) -> "int | None":
    """N beside a rank word, before or after it: "top 5", "bottom ten", "5 lowest",
    "best 3", "least 5" (I-1: only "top N" was read)."""
    w = [t.low for t in tokens(text)]
    num = (lambda x: int(x) if x.isdigit() and 0 < int(x) < 1000 else _NUM_WORDS.get(x))
    for i in range(len(w)):
        if _rank_dir(w, i):
            if i + 1 < len(w) and num(w[i + 1]):
                return num(w[i + 1])
            if i and num(w[i - 1]):
                return num(w[i - 1])
    return None


# "excluding East Khasi Hills": a place the ranking leaves out (I-19)
_EXCLUDE_WORDS = ("excluding", "except", "exclude", "excluded", "without", "barring")
_EXCLUDE_PAIRS = (("other", "than"), ("apart", "from"), ("leaving", "out"), ("not", "including"))


def _excluded_places(text: str, names: list) -> list:
    """The resolved place names (upper case) that the question names after an
    exclusion word."""
    low = " ".join(t.low for t in tokens(text))
    cut = -1
    for wd in _EXCLUDE_WORDS:
        k = f" {low} ".find(f" {wd} ")
        if k >= 0:
            cut = k if cut < 0 else min(cut, k)
    for a, b in _EXCLUDE_PAIRS:
        k = f" {low} ".find(f" {a} {b} ")
        if k >= 0:
            cut = k if cut < 0 else min(cut, k)
    if cut < 0:
        return []
    tail = f" {low[cut:]} "
    return [n for n in names if f" {' '.join(t.low for t in tokens(n))} " in tail]


def _first_pos(text: str, scheme: str, scheme_matchers: dict) -> int:
    hit = scheme_matchers[scheme].search(text)
    return hit.start() if hit else 10 ** 6


def _without_dataset_words(text: str) -> str:
    """"CM Elevate applicants" / "cm-elevate applications" / "CM Elevate (applications)"
    name the applications DATASET; the application word is not a measure of the
    question ("How much was disbursed under CM Elevate applicants and Legacy CM
    Elevate" asks money only; "pmay-g vs cm elevate applicants performance" is a
    broad ask). Cross Scheme sheet re-run 2026-10-30."""
    out = []
    words = text.split()
    for i, w in enumerate(words):
        core = w.strip("()?.,").lower()
        prev = [x.strip("()?.,-").lower() for x in words[max(0, i - 3):i]]
        # "cm elevate applicants", "CM Elevate Legacy applicants" (the pin's rewrite of
        # a FY question), "Legacy CM Elevate applications"
        if core in ("applicants", "applicant", "applications", "application") and (
                prev[-2:] == ["cm", "elevate"] or prev[-3:] == ["cm", "elevate", "legacy"]
                or prev[-3:] == ["legacy", "cm", "elevate"]):
            continue
        if core in ("applicants", "applicant", "applications", "application") and i >= 1 \
                and words[i - 1].strip("()?.,").lower() in ("cm-elevate", "cmelevate"):
            continue
        out.append(w)
    return " ".join(out)


def plan(text: str, schemes: list, resolved: dict, display: "dict | None",
         scheme_matchers: dict) -> "Plan | None":
    """What to compute for a cross-scheme question, or None when its shape is not
    one this module answers (the D-062 model path takes it). `text` is the
    question with any excluded schemes masked out."""
    text = _without_dataset_words(text)
    ask = rank_ask(text)
    drank = ask is not None and ask.level == "district"
    left_out = [s for s in (schemes or []) if s not in SUPPORTED]
    schemes = [s for s in SUPPORTED if s in schemes]
    if len(schemes) < 2:
        return None
    r = resolved or {}
    twins = {int(k): str(v) for k, v in (r.get("village_twins") or {}).items()} if r.get("village_twins") else {}
    if r.get("block_list") or (r.get("village_code_list") and not twins):
        return None                      # several villages / blocks at once: a list per scheme
    # D-097: one village or one constituency is a place like a block (its figures per
    # scheme); a list of villages (village_code_list) is not — unless it is the 2-3
    # same-named villages of KI-630, answered one row each
    village = r.get("village_code") if not isinstance(r.get("village_code"), (list, tuple)) else None
    ac = str(r["assembly_constituency"]).upper() if r.get("assembly_constituency") else None
    if r.get("village_code") and village is None and not twins:
        return None
    if twins:
        village = None
    if _OTHER_MEASURE.search(text):
        return None                      # B-7: "person days" was answered with beneficiaries and money
    if ask is not None and ask.level != "district":
        return None                      # top / lowest villages, blocks: a list per scheme (model path)
    if (village or ac or twins) and drank:
        return None                      # a district ranking inside one village makes no sense
    # "top 5 districts by villages covered" is a district ranking on the villages
    # measure, not a village list (I-11): with a district ranking only the time
    # words of _OTHER_GRAIN send the question on
    # A-16 (audit 2026-10-29): a per-year question ("each year", a span, "2023-24 vs
    # 2024-25") over these measures is answered here, one fixed query per scheme
    # grouped by year_key, in one row shape. It went to one model-written query per
    # scheme, whose year columns were each named their own way (A-1).
    # "Each year" / "year wise" wordings are turned into one question per scheme
    # before the pipeline (conversation_layer.per_year_plan); here a stated list or
    # span of years is.
    if _VILLAGES.search(text) and _OVERLAP.search(text) and not drank and not r.get("year_key_list") \
            and not _YEARLY.search(text):
        districts0 = r.get("district_list") or ([r["district"]] if r.get("district") else None)
        p = Plan(schemes=schemes, by_district=False, districts=None if r.get("block") else districts0,
                 block=r.get("block"), year=int(r["year_key"]) if r.get("year_key") else None,
                 measures=["villages"], op="overlap", first="villages",
                 list_villages=bool(_LIST_VILLAGES.search(text)))
        _labels(p, display)
        return p
    # A-16 (chat UI audit 2026-10-29): "each year / year wise / annually" over the
    # coded measures is one fixed query per scheme grouped by year (every year held),
    # like a stated span; a place level or ranking per year stays a list per scheme
    yearly = bool(_YEARLY.search(text)) and not _MONTHLY.search(text)
    timed = bool(r.get("year_key_list")) or yearly
    if drank and timed:
        return None                      # a district ranking per year: a list per scheme and year
    block_grain = bool(_BLOCK_GRAIN.search(text)) and not drank and not (village or ac) \
        and not (ask is not None) and not _top_n(text)
    if not drank and not block_grain and _OTHER_PLACES.search(text):
        return None
    if timed and (_MONTHLY.search(text) or _DISTRICT_GRAIN.search(text)):
        return None
    if _top_n(text) and not (drank or _DISTRICT_GRAIN.search(text)):
        return None                      # a "top N" of anything but districts is a list
    districts = r.get("district_list") or ([r["district"]] if r.get("district") else None)
    block = r.get("block")
    if block and districts:
        districts = None                 # the block settles the place
    if village or ac or twins:
        districts, block = None, None    # the village / constituency settles the place
    exclude = _excluded_places(text, districts or []) if drank else []
    if exclude:
        districts = [d for d in districts if d not in exclude] or None
    money, count, vill = bool(_MONEY.search(text)), bool(_COUNT.search(text)), bool(_VILLAGES.search(text))
    if village or twins:
        # "… in Apalgre village": the word names the place; a village has no villages count
        vill = False
    perf, summary, avg = bool(_PERFORMANCE.search(text)), bool(_SUMMARY.search(text)), bool(_AVG.search(text))
    grain_cue = bool(_DISTRICT_GRAIN.search(text))
    if grain_cue and vill and not (money or count) and _ACROSS_DISTRICTS.search(text) \
            and not _PER_DISTRICT.search(text) and not _WHICH_DISTRICTS.search(text):
        grain_cue = False                # coverage "across districts": the statewide reach
    by_district = ((drank or block_grain or grain_cue
                    or bool(districts and len(districts) > 1)) and not (village or ac)) or bool(twins)
    if block_grain and block:
        block = None                     # "block-wise in Mylliem block" reads as the district's blocks
    if timed and by_district:
        return None
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
        elif drank:
            op = "rank_districts"
        elif _SECOND.search(text):
            op = "second"
        elif _WHICH_DISTRICTS.search(text) and (ranked or _top_n(text)):
            op = "rank_districts"
        elif ranked:
            op = "winner"
    elif ranked or len(schemes) == 2 or perf or summary:
        op = "leader"
    better = op == "leader" and bool(_BETTER.search(text)) and not explicit
    if timed:
        op = "by_year"
    elif not by_district and not explicit and not (perf or summary or avg or ranked) and _HEADLINE.search(text):
        # "the headline figures across all schemes": each scheme's OWN lead figure, the one its overview card
        # shows first (data/cross_scheme.yaml `headline`, the same SQL as the card), never added up
        op, measures, first = "headline", ["headline"], "headline"
        better = False
    if op == "rank_districts" and avg:
        first = "avg"                    # "per beneficiary money": ranked on money per head (I-21)
    year = r.get("year_key")
    combined = bool(_COMBINED.search(text))
    p = Plan(schemes=schemes, by_district=by_district, districts=districts, block=block,
             year=int(year) if year else None, measures=measures, op=op, cond=cond, first=first,
             # a district ranking adds the schemes only when the question says so
             # ("combined", "together", "in total"); otherwise one list per scheme (I-6)
             combined=combined and (op == "rank_districts" or (op in ("list", "leader") and not ranked)),
             avg=avg, low=(ask.low and not ask.high) if drank else bool(_LOW.search(text)),
             top_n=_top_n(text) or (1 if drank and not ask.nth and not (ask.high and ask.low)
                                     and _one_place_asked(text, ask.level) else None),
             rank_measures=bool(_RANK_MEASURES.search(text)) and not by_district,
             lead_all=perf or (count and money),
             both=bool(drank and ask.high and ask.low), nth=ask.nth if drank else None,
             exclude=exclude, left_out=left_out, better=better, years=list(r.get("year_key_list") or []) if timed else None,
             village=int(village) if village else None, ac=ac,
             grain="village" if twins else ("block" if block_grain else "district"), villages=twins)
    if drank and not exclude and any(w in _EXCLUDE_WORDS for w in (t.low for t in tokens(text))):
        p.notes.append("The place after the exclusion word was not recognised, so no district was left out")
    # a broad ask ("performance", "overview" with no measure) reads with the detail
    broad = perf or (summary and not explicit)
    p.completed = broad or bool(_COMPLETED.search(text))
    p.pgs = broad or bool(_PGS.search(text))
    _labels(p, display)
    if p.year is not None:
        p.period_label = f"FY {p.year}-{(p.year + 1) % 100:02d}"
    if p.op == "by_year":
        # A-18: the years used, in the first line
        ys = sorted(p.years or [])
        fy = (lambda y: f"FY {y}-{(y + 1) % 100:02d}")
        if not ys:
            p.period_label = "each financial year each scheme holds"
        elif ys == list(range(ys[0], ys[-1] + 1)):
            p.period_label = f"{fy(ys[0])} to {fy(ys[-1])} ({len(ys)} years)"
        else:
            p.period_label = ", ".join(fy(y) for y in ys[:-1]) + f" and {fy(ys[-1])}"
    return p


def _labels(p: Plan, display: "dict | None") -> None:
    disp = display or {}
    if p.villages:
        name = next(iter(p.villages.values())).split(" (")[0]
        p.place_label = f"{name} village ({len(p.villages)} villages share the name)"
    elif p.village:
        name = str(disp.get("village") or f"LGD {p.village}")
        p.place_label = f"{name if name.startswith('LGD') else name.title()} village" \
            + (f" ({str(disp['block']).title()} block)" if disp.get("block") else "")
    elif p.ac:
        p.place_label = f"{str(disp.get('assembly_constituency') or p.ac).title()} constituency"
    elif p.block:
        p.place_label = f"{str(disp.get('block') or p.block).title()} block"
    elif p.districts and len(p.districts) == 1:
        p.place_label = f"{p.districts[0].title()} district"
    elif p.districts:
        p.place_label = ", ".join(d.title() for d in p.districts)
    if p.year is not None:
        p.period_label = f"FY {p.year}-{(p.year + 1) % 100:02d}"


# ── villages in both / either / only one scheme (G-8, I-5) ────────────────────
_VILLAGE_SET_FILTER = cross_registry.village_set_filter()


async def village_sets(p: Plan) -> tuple[dict, list[str]]:
    """{scheme: {village_code, ...}} for the plan's place and year, and the SQL run. The schemes are read
    concurrently (fan_out); an overlap needs every scheme's set, so any failure fails the answer."""
    async def one(s: str) -> "tuple[str, set]":
        sql, params = _village_set_sql(p, s)
        return sql, {int(r["v"]) for r in await db.fetch_rows(sql, params) if r["v"] is not None}

    got, failed = await fan_out(list(p.schemes), one)
    if failed:
        raise next(iter(failed.values()))
    return {s: got[s][1] for s in p.schemes}, [got[s][0] for s in p.schemes]


def _village_set_sql(p: Plan, s: str) -> "tuple[str, list]":
    """One scheme's villages-in-the-set statement and its bound values."""
    view, dcol, bcol, _m = _QUERIES[s][0]
    where, params = ["village_code IS NOT NULL", _VILLAGE_SET_FILTER.get(s, "TRUE")], []
    if p.districts:
        params.append([d.upper() for d in p.districts])
        where.append(f"{dcol} = ANY(${len(params)}::text[])")
    if p.block:
        params.append(p.block.upper())
        where.append(f"{bcol} = ${len(params)}")
    if p.year is not None:
        params.append(int(p.year))
        where.append(f"year_key = ${len(params)}")
    return f"SELECT DISTINCT village_code AS v FROM {view} WHERE {' AND '.join(where)}", params


async def _overlap_answer(p: Plan) -> dict:
    """The union and the overlap of the schemes' villages: each village once."""
    sets, shown = await village_sets(p)
    have = [s for s in p.schemes if sets.get(s)]
    union = set().union(*sets.values()) if sets else set()
    every = set.intersection(*(sets[s] for s in have)) if len(have) >= 2 else set()
    lines = [_header(p), f"**{indian(len(union))} villages** have at least one of {', '.join(p.schemes)}."]
    rows: list = []
    if len(have) >= 2:
        both = "both" if len(have) == 2 else f"all {len(have)}"
        lines.append(f"- In {both}: **{indian(len(every))}**")
        rows.append({"coverage": "Both" if len(have) == 2 else f"All {len(have)} schemes", "villages": len(every)})
        for s in have:
            only = sets[s] - set().union(*(sets[o] for o in have if o != s))
            lines.append(f"- {s} only: **{indian(len(only))}**")
            rows.append({"coverage": f"{s} only", "villages": len(only)})
        if len(have) > 2:
            rest = len(union) - sum(r["villages"] for r in rows)
            lines.append(f"- In some but not all: **{indian(rest)}**")
            rows.append({"coverage": "Some, not all", "villages": rest})
    for s in p.schemes:
        if not sets.get(s):
            lines.append(f"{s} has no village records for {p.place_label}.")
    lines.append("Each village is counted once, however many schemes reach it.")
    if p.list_villages and every:
        named = await db.fetch_rows(
            "SELECT village_code, lgd_village_name, lgd_block, lgd_district FROM curated.dim_geography "
            "WHERE village_code = ANY($1::bigint[]) ORDER BY lgd_district, lgd_block, lgd_village_name LIMIT 1000",
            [sorted(every)])
        rows = [{"village": str(r["lgd_village_name"]).title(), "block": str(r["lgd_block"]).title(),
                 "district": str(r["lgd_district"]).title(), "village_code": r["village_code"]} for r in named]
        more = " (the first 1,000)" if len(every) > 1000 else ""
        lines.append(f"The villages in {'both' if len(have) == 2 else 'every scheme'} are in the table{more}.")
    return {"answer": "\n".join(lines), "rows": rows, "sql": "\n;\n".join(shown)}


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


SHORT = {s: s for s in SUPPORTED}
_BEN_NOUN = cross_registry.ben_noun()
_MONEY_VERB = cross_registry.money_verb()
# schemes whose count is applications, not beneficiaries: kept apart in a combined total / ranking (I-13)
_APART_IN_COMBINED = cross_registry.apart_in_combined()


def _money_verb(s: str) -> str:
    """The scheme's money verb; a scheme with no money entry never raises (it is answered "no money recorded")."""
    return _MONEY_VERB.get(s, "recorded")


def _per(s: str) -> str:
    return _PER.get(s, "per beneficiary")


def count_text(s: str, f: dict, short: bool = False, p: "Plan | None" = None) -> str:
    """`p`: the plan, whose `completed` / `pgs` say whether the scheme's detail is
    shown; without one the detail is shown."""
    n = indian(f.get("ben", 0))
    if s == "PMAY-G":
        if short or (p is not None and not p.completed):
            return n if short else f"{n} houses sanctioned"
        return f"{n} houses sanctioned ({indian(f.get('completed', 0))} completed)"
    if s == "Focus Legacy":
        if p is not None and not p.pgs:
            return f"{n} members"
        return f"{n} members ({indian(f.get('pgs', 0))} PGs)" if short else \
            f"{n} members in {indian(f.get('pgs', 0))} producer groups"
    return n if short else f"{n} {_BEN_NOUN[s]}"


def money_text(s: str, f: dict, short: bool = False) -> str:
    m = rupees_crore(f.get("money", 0))
    if short:
        return m
    if s == "PMAY-G":
        return f"{m} released (sanctioned {rupees_crore(f.get('sanctioned', 0))})"
    return f"{m} {_money_verb(s)}"


def villages_text(f: dict, state: bool) -> str:
    v = f"{indian(f.get('villages', 0))} villages"
    if state:
        return f"{indian(f.get('districts', 0))} districts, {indian(f.get('blocks', 0))} blocks, {v}"
    return v


def avg_value(f: dict) -> "float | None":
    return f["money"] * 1e7 / f["ben"] if f.get("ben") and f.get("money") is not None else None


_PER = cross_registry.per()


def primary(p: Plan) -> str:
    """The one measure a ranking or comparison is decided on."""
    if p.first == "avg":
        return "avg"
    return p.first if p.first in p.measures else p.measures[0]


def value(f: dict, measure: str) -> float:
    if measure == "avg":
        return float(avg_value(f) or 0.0)
    return float(f.get({"count": "ben", "money": "money", "villages": "villages"}[measure], 0.0) or 0.0)


def measure_noun(measure: str) -> str:
    return {"count": "beneficiaries", "money": "money", "villages": "villages covered",
            "avg": "money per beneficiary"}[measure]


def fmt(s: str, f: dict, measure: str) -> str:
    if measure == "avg":
        return f"₹{indian(avg_value(f) or 0)} {_per(s)}"
    if measure == "money":
        return rupees_crore(f.get("money", 0))
    if measure == "villages":
        return f"{indian(f.get('villages', 0))} villages"
    return f"{indian(f.get('ben', 0))} members" if s == "Focus Legacy" else indian(f.get("ben", 0))


# ── computing and writing the answer ──────────────────────────────────────────

# ── fan-out: one question's per-scheme queries run concurrently ─────────────────
# They ran one scheme after another (8 schemes x 1-3 statements each, plus the statewide totals of a per-district
# answer); now each scheme is one task, at most CROSS_SCHEME_CONCURRENCY at a time (the app pool is shared), each
# given CROSS_SCHEME_TIMEOUT_SECONDS. A scheme that fails is named in the answer and the others are still answered;
# only when every scheme fails does the error reach the caller (as before).

async def fan_out(schemes: list, work) -> "tuple[dict, dict]":
    """({scheme: result of `work(scheme)`}, {scheme: the exception it raised}), in `schemes` order."""
    sem = asyncio.Semaphore(max(1, int(settings.CROSS_SCHEME_CONCURRENCY)))
    limit = float(settings.CROSS_SCHEME_TIMEOUT_SECONDS)

    async def one(s):
        async with sem:                  # waiting for a slot is not the scheme's own time
            return await asyncio.wait_for(work(s), limit)

    got = await asyncio.gather(*(one(s) for s in schemes), return_exceptions=True)
    ok, failed = {}, {}
    for s, r in zip(schemes, got):
        if isinstance(r, asyncio.CancelledError):
            raise r
        if isinstance(r, BaseException):
            failed[s] = r
        else:
            ok[s] = r
    for s, e in failed.items():
        logger.warning("cross figures: %s failed (%s: %s)", s, type(e).__name__, e)
    if failed and not ok:
        raise next(iter(failed.values()))
    return ok, failed


def failed_text(s: str, e: BaseException) -> str:
    """The partial answer's line for a scheme whose query failed."""
    why = "its figures took too long to read" if isinstance(e, (asyncio.TimeoutError, TimeoutError)) \
        else "its figures could not be read just now"
    return f"{s} is not in this answer: {why}; ask again to include it"


async def _scheme_part(p: Plan, s: str) -> dict:
    """One scheme's share of a plan: {"gap": why it has no figure (or a partial one), "figs", "total", "sql"}."""
    out: dict = {"gap": None, "figs": None, "total": None, "sql": []}
    if p.year is not None:
        held = await _years_held(s)
        if s in NO_YEAR:
            out["gap"] = f"{s} records no financial year, so it has no figure for {p.period_label}"
            return out
        if p.year not in held:
            out["gap"] = (f"{s} has no data for {p.period_label} (its data covers FY "
                          f"{held[0]}-{(held[0] + 1) % 100:02d} to {held[-1]}-{(held[-1] + 1) % 100:02d})"
                          if held else f"{s} records no financial year")
            return out
    if p.op == "by_year":
        held = await _years_held(s)
        if s in NO_YEAR:
            out["gap"] = f"{s} records no financial year"
            return out
        missing = [y for y in (p.years or []) if y not in held]
        if p.years and len(missing) == len(p.years):
            out["gap"] = f"{s} has no data for {p.period_label}"
            return out
        if missing:
            out["gap"] = f"{s} has no data for " + ", ".join(f"FY {y}-{(y + 1) % 100:02d}" for y in missing)
    if p.ac and s not in _AC_COL:
        out["gap"] = f"{s} does not record assembly constituency, so it has no figure for {p.place_label}"
        return out
    head = [cross_registry.headline_query(s)] if p.op == "headline" else None
    if p.villages:
        got = {}
        for code, label in p.villages.items():
            one, sql = await scheme_figures(s, by_district=False, village=code, year=p.year, specs=head)
            out["sql"] += sql
            if one.get(STATE) and any(v for v in one[STATE].values()):
                got[label] = one[STATE]
        out["figs"] = got
        return out
    if head is not None:
        got, sql = await scheme_figures(s, by_district=False, districts=p.districts, block=p.block, year=p.year,
                                        village=p.village, ac=p.ac, specs=head)
        out["figs"], out["sql"] = got, sql
        return out
    got, sql = await scheme_figures(s, by_district=p.by_district, districts=p.districts,
                                    block=p.block, year=p.year,
                                    by_year=p.op == "by_year", years=p.years or None,
                                    village=p.village, ac=p.ac, grain=p.grain)
    out["figs"], out["sql"] = got, sql
    if p.by_district and got:
        # the statewide total, not the sum of the districts: a record with no
        # district (one Focus Plus beneficiary) still counts
        tot, _sql_t = await scheme_figures(s, by_district=False, districts=p.districts, year=p.year)
        out["total"] = tot.get(STATE, {})
    return out


async def answer(p: Plan) -> dict:
    """{'answer', 'rows', 'sql'} for a plan."""
    if p.op == "overlap":
        return await _overlap_answer(p)
    figs: dict[str, dict] = {}
    totals: dict[str, dict] = {}
    shown: list[str] = []
    gaps: dict[str, str] = dict(p.gaps or {})
    # said by c13 (constituency / year / money not held): never queried
    todo = [s for s in p.schemes if s not in gaps]
    parts, failed = await fan_out(todo, lambda s: _scheme_part(p, s))
    for s in todo:                       # merged in the plan's order, whatever order they finished in
        if s in failed:
            gaps[s] = failed_text(s, failed[s])
            continue
        r = parts[s]
        shown += r["sql"]
        if r["gap"]:
            gaps[s] = r["gap"]
        if r["figs"] is not None:
            figs[s] = r["figs"]
        if r["total"] is not None:
            totals[s] = r["total"]
    have = [s for s in p.schemes if s in figs and figs[s]]
    for s in p.schemes:
        if s in figs and not figs[s]:
            gaps[s] = f"{s} has no records for {p.place_label}"
    lines = [_header(p)]
    if p.op == "headline":
        lines += _headline_lines(p, figs, have)
    elif p.op == "by_year":
        lines += _year_lines(p, figs, have)
    elif p.by_district:
        lines += _district_lines(p, figs, have, totals)
    else:
        lines += _state_lines(p, {s: figs[s].get(STATE, {}) for s in have}, have)
    if p.measures == ["money"] and any(s in NO_MONEY for s in have):
        for s in have:
            if s in NO_MONEY:
                gaps.setdefault(s, f"{s} records applications only, no money, so it has no amount to compare")
    if gaps:
        lines.append(" ".join(f"{g}." for g in gaps.values()))
    lines += [f"{n}." for n in p.notes]
    rows = _rows(p, figs, have)
    # G-12: a per-district table's Total is each scheme's statewide figure (it counts
    # records with no district and each Focus Plus beneficiary once), the same the
    # text gives, never the sum of the district rows the UI has
    col_totals = None
    if p.by_district and p.op in ("list", "winner", "second", "condition") and totals:
        col_totals = {s: _total_cells(p, totals.get(s) or {}) for s in have if totals.get(s)}
    logger.info("cross figures (D-066): %s %s op=%s measures=%s by_district=%s", p.schemes, p.place_label,
                p.op, p.measures, p.by_district)
    return {"answer": "\n".join(ln for ln in lines if ln is not None), "rows": rows, "sql": "\n;\n".join(shown),
            "totals": col_totals, "measure_notes": {} if p.op == "headline" else measure_notes(have),
            "schemes_with_data": have, "schemes_failed": [s for s in todo if s in failed],
            "schemes_apart": {}}


# G-9 / B-11 (audit 2026-10-29): every scheme's count sits in one `beneficiaries`
# column and its money in one `amount_crore` column, so the tiles, axes and table
# said "beneficiaries" for MGNREGA household-years and "amount" for money spent,
# released and disbursed alike. What each column means for each scheme goes with
# the answer (the rows keep their shape, user report 2026-10-27).
_COUNT_NOTE = cross_registry.count_note()
_MONEY_NOTE = cross_registry.money_note()


def measure_notes(schemes: list) -> dict:
    """{scheme: {column: what it holds for that scheme}}."""
    return {s: {"beneficiaries": _COUNT_NOTE[s], "amount_crore": _MONEY_NOTE[s]} for s in schemes if s in _COUNT_NOTE}


def _total_cells(p: Plan, f: dict) -> dict:
    out = {}
    if "count" in p.measures:
        out["beneficiaries"] = int(f.get("ben", 0))
    if "money" in p.measures:
        out["amount_crore"] = round(f.get("money", 0.0), 2)
    if "villages" in p.measures:
        out["villages"] = int(f.get("villages", 0))
    return out


def _fy(y) -> str:
    y = int(y)
    return f"{y}-{(y + 1) % 100:02d}"


def _year_lines(p: Plan, figs: dict, have: list) -> list:
    """One line per scheme and measure: the figure in each year it holds. Each scheme
    holds its own years; a year it does not hold is said, never shown as 0 (A-13)."""
    out = []
    for s in have:
        for m in p.measures:
            if not has_measure(s, m):
                out.append(f"- **{SHORT[s]}**: no money recorded")
                continue
            noun = {"count": _BEN_NOUN[s], "money": f"money {_money_verb(s)}", "villages": "villages covered"}[m]
            out.append(f"- **{SHORT[s]}** ({noun}): " + "; ".join(
                f"FY {_fy(k)} {fmt(s, figs[s][k], m)}" for k in sorted(figs[s], key=int)))
    if len(have) >= 2 and "count" in p.measures:
        out.append("Each scheme counts its own thing (" + ", ".join(f"{s} {_BEN_NOUN[s]}" for s in have)
                   + "), so the figures are not added.")
    return out


def _header(p: Plan) -> str:
    left = f", excluding {', '.join(d.title() for d in p.exclude)}" if p.exclude else ""
    return f"**{p.place_label[0].upper() + p.place_label[1:]}{left}, {p.period_label}**"


def _scheme_line(s: str, f: dict, p: Plan, state: bool) -> str:
    parts = []
    if "count" in p.measures:
        n = count_text(s, f, p=p)
        if s == "MGNREGA" and state and p.year is None:
            # all years added: the same household is in it once per year it worked
            n += " (counted once per financial year, FY 2022-23 to 2025-26)"
        parts.append(n)
    if "money" in p.measures:
        parts.append(money_text(s, f) if has_measure(s, "money") else "no money recorded")
    if "villages" in p.measures:
        parts.append(villages_text(f, state and not (p.block or p.districts or p.village or p.ac)))
    if p.avg and has_measure(s, "avg") and avg_value(f):
        parts.append(f"₹{indian(avg_value(f))} {_per(s)}")
    return f"- **{SHORT[s]}:** " + ", ".join(parts)


def _state_lines(p: Plan, f: dict, have: list) -> list:
    # MGNREGA's household-year note is on its own line (_scheme_line), not a sentence of its own
    out = [_scheme_line(s, f[s], p, True) for s in have]
    if len(have) < 2:
        return out
    if p.combined:
        if "count" in p.measures:
            inc = [s for s in have if s not in _APART_IN_COMBINED]
            tot = sum(value(f[s], "count") for s in inc)
            parts = " + ".join(f"{indian(value(f[s], 'count'))} {_BEN_NOUN[s]}" for s in inc)
            out.append(f"**Combined: {indian(tot)}** ({parts}; these count different things, added "
                       "because the question asks for the total)."
                       + "".join(f" {s} counts applications, not beneficiaries, so it is not in the combined figure."
                                 for s in have if s in _APART_IN_COMBINED))
        if "money" in p.measures:
            out.append(f"**Combined: {rupees_crore(sum(value(f[s], 'money') for s in have if has_measure(s, 'money')))}**.")
    if p.avg:
        avgs = {s: avg_value(f[s]) for s in have if has_measure(s, "avg") and avg_value(f[s])}
        if avgs:
            top = max(avgs, key=avgs.get) if not p.low else min(avgs, key=avgs.get)
            out.append(f"Most money per beneficiary: **{top}** (₹{indian(avgs[top])} {_per(top)}). Order: "
                       + " > ".join(f"{s} ₹{indian(avgs[s])}" for s in sorted(avgs, key=avgs.get, reverse=True)) + ".")
    if p.better:
        out.append("The schemes measure different things (" + ", ".join(f"{s} {_BEN_NOUN[s]}" for s in have)
                   + "), so neither is better on size alone. Ask for a measure to compare them on: "
                   "beneficiaries, money spent, villages covered or money per beneficiary.")
        return out
    if p.op == "leader" or p.rank_measures:
        ms = p.measures if (p.rank_measures or p.lead_all) else [primary(p)]
        for m in ms:
            line = _leader_sentence(m, f, have, p.low and len(ms) == 1)
            if line:
                out.append(line)
    return out


def _leader_sentence(m: str, f: dict, have: list, low: bool) -> str:
    have = [s for s in have if has_measure(s, m)]
    if len(have) < 2:
        return ""                        # one scheme with the measure: nothing to rank
    order = sorted(have, key=lambda s: value(f[s], m), reverse=not low)
    lead, nxt = order[0], order[1]
    word = "lowest" if low else ("most " + measure_noun(m) if m != "money" else "most money")
    head = f"**{lead}** has the {word} ({fmt(lead, f[lead], m)})"
    if len(order) == 2:
        a, b = value(f[lead], m), value(f[nxt], m)
        diff = abs(a - b)
        d = rupees_crore(diff) if m == "money" else indian(diff)
        ratio = f", {a / b:.2f}x" if b and not low else ""
        more = ("less" if m == "money" else "fewer") if low else "more"
        return f"{head}, {d} {more} than {nxt} ({fmt(nxt, f[nxt], m)}{ratio})."
    return head + ". Order: " + " > ".join(f"{s} ({fmt(s, f[s], m)})" for s in order) + "."


def _ranks_combined(p: Plan, m: str) -> bool:
    """A district ranking adds the schemes only when asked ("combined", "in total"),
    and never for villages (shared between schemes) or money per head (G-6, I-21)."""
    return p.combined and m not in ("villages", "avg")


def _rank_order(p: Plan, keys: list, key) -> list:
    """Districts in rank order: highest first, or lowest first for a low ranking.
    Districts with no figure for the measure are left out of a low ranking: "lowest
    5" is not five districts the scheme does not reach."""
    keys = [k for k in keys if not p.low or key(k) > 0]
    return sorted(keys, key=lambda k: (key(k), k), reverse=not p.low)


def _rank_parts(p: Plan, order: list) -> list:
    """[(heading, [(rank, district), ...]), ...]: the top N, the bottom N too when
    both ends are asked (I-12), or the one place asked ("second highest")."""
    n = min(p.top_n or len(order), len(order))
    if p.nth:
        if len(order) < p.nth:
            return []
        word = {2: "Second", 3: "Third"}.get(p.nth, f"#{p.nth}")
        return [(f"{word} {'lowest' if p.low else 'highest'} district", [(p.nth, order[p.nth - 1])])]
    top = (f"{'Bottom' if p.low else 'Top'} {n} district{'s' if n != 1 else ''}", list(enumerate(order[:n], 1)))
    if not p.both:
        return [top]
    bottom = list(reversed(list(enumerate(order, 1))[-n:]))
    return [top, (f"Bottom {n} district{'s' if n != 1 else ''}", bottom)]


def ranked_districts(p: Plan, figs: dict, have: list) -> "dict[str, list] | None":
    """{scheme or '': [(rank, district), ...]} — the districts a ranking shows, in
    rank order ('' for a combined ranking); None when the plan ranks nothing."""
    if p.op != "rank_districts":
        return None
    keys = _district_keys(p, figs, have)
    m = primary(p)
    have = ranked_schemes(p, have, m)
    if _ranks_combined(p, m):
        order = _rank_order(p, keys, lambda k: sum(value(figs[s].get(k, {}), m) for s in have))
        return {"": [ik for _l, part in _rank_parts(p, order) for ik in part]}
    return {s: [ik for _l, part in _rank_parts(p, _rank_order(p, keys, lambda k, s=s: value(figs[s].get(k, {}), m)))
                for ik in part] for s in have}


def ranked_schemes(p: Plan, have: list, m: str) -> list:
    """The schemes a ranking on measure `m` can hold: those that record it, and - in
    a combined count - not CM Elevate (applications are not beneficiaries, I-13)."""
    out = [s for s in have if has_measure(s, m)]
    if _ranks_combined(p, m) and m == "count":
        out = [s for s in out if s not in _APART_IN_COMBINED]
    return out


def _district_keys(p: Plan, figs: dict, have: list) -> list:
    keys = sorted({k for s in have for k in figs[s] if k != STATE})
    if p.districts and p.grain == "district":
        # block-wise rows of a district are block names: never filtered by the district list
        keys = [k for k in keys if k in {d.upper() for d in p.districts}]
    if p.exclude:
        keys = [k for k in keys if k not in {d.upper() for d in p.exclude}]
    return keys


def _district_lines(p: Plan, figs: dict, have: list, totals: "dict | None" = None) -> list:
    keys = _district_keys(p, figs, have)
    m = primary(p)
    out = []
    shown_all = have
    apart = [s for s in have if s not in ranked_schemes(p, have, m)]
    if p.op in ("winner", "second", "rank_districts", "condition"):
        have = ranked_schemes(p, have, m)
        if len(have) < 2:
            # one scheme holds the measure: the per-district table, no ranking
            p = Plan(**{**p.__dict__, "op": "list"})
            have = shown_all
    if p.op == "condition":
        x, y, more = p.cond
        hits = [k for k in keys if (value(figs[x].get(k, {}), m) > value(figs[y].get(k, {}), m)) == more
                and value(figs[x].get(k, {}), m) != value(figs[y].get(k, {}), m)]
        rel = "more" if more else "fewer"
        noun = measure_noun(m) if m != "money" else "money"
        shown = hits
        if p.top_n and len(hits) > p.top_n:
            # "top 5 districts where X is more than Y": the 5 with the widest gap (I-20)
            gap = (lambda k: abs(value(figs[x].get(k, {}), m) - value(figs[y].get(k, {}), m)))
            shown = sorted(hits, key=gap, reverse=True)[:p.top_n]
        if hits:
            lead = (f"{x} has {rel} {noun} than {y} in **{len(hits)} of {len(keys)} districts**"
                    + (f"; the {len(shown)} with the widest gap" if shown is not hits else ""))
            out.append(lead + ": " + "; ".join(
                f"{k.title()} ({fmt(x, figs[x][k], m)} vs {fmt(y, figs[y].get(k, {}), m)})" for k in shown) + ".")
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
        for s in apart:
            out.append(f"{s} is not in this ranking: it records "
                       + ("applications only, no money" if m in ("money", "avg") else "applications, not beneficiaries")
                       + "; its figures are in the table.")
        return out + per
    elif p.op == "rank_districts":
        what = {"money": "money", "villages": "villages covered", "avg": "money per beneficiary"}.get(m, "beneficiaries")
        if not _ranks_combined(p, m):
            # One ranked list per scheme (I-6): the schemes count different things,
            # and the same village is in several schemes, so they are not added.
            if p.combined and m in ("villages", "avg"):
                out.append("Village counts are not added across schemes (one village can be reached by "
                           "several schemes), so each scheme is ranked on its own." if m == "villages" else
                           "Money per beneficiary is each scheme's own figure, so each scheme is ranked on its own.")
            for s in have:
                order = _rank_order(p, keys, lambda k, s=s: value(figs[s].get(k, {}), m))
                noun = _BEN_NOUN[s] if m == "count" else what
                for label, part in _rank_parts(p, order):
                    if len(part) == 1 and not p.nth:
                        # the one leader per scheme ("which district leads in each scheme"): no "Top 1 … 1."
                        _i, k = part[0]
                        val = fmt(s, figs[s].get(k, {}), m)
                        if val.endswith(" " + str(noun)):
                            val = val[: -len(str(noun)) - 1]          # "21,867 members": the noun is said once
                        out.append(f"**{SHORT[s]}**: {k.title()} has the {'fewest' if p.low else 'most'} {noun} "
                                   f"({val}).")
                        continue
                    out.append(f"**{SHORT[s]}** — {label} by {noun}: " + "; ".join(
                        f"{i}. {k.title()} {fmt(s, figs[s].get(k, {}), m)}" for i, k in part) + ".")
            return out
        tot = {k: sum(value(figs[s].get(k, {}), m) for s in have) for k in keys}
        order = _rank_order(p, keys, lambda k: tot[k])
        for label, part in _rank_parts(p, order):
            out.append(f"{label} by combined {what} ({' + '.join(have)}):")
            for i, k in part:
                t = rupees_crore(tot[k]) if m == "money" else indian(tot[k])
                out.append(f"{i}. **{k.title()}**: {t} — "
                           + ", ".join(f"{s} {fmt(s, figs[s].get(k, {}), m)}" for s in have))
        if m == "count":
            out.append("The combined figure adds different counts (" + ", ".join(
                f"{s} {_BEN_NOUN[s]}" for s in have) + "), added because the question asks for the total.")
        if m == "money":
            # G-11: the money kinds differ as the counts do
            out.append("The combined figure adds different kinds of money (" + ", ".join(
                f"{s} {_money_verb(s)}" for s in have if has_measure(s, "money")) + "), added because the question asks for the total.")
        for s in apart:
            out.append(f"{s} is not in the combined figure: it records "
                       + ("applications only, no money." if m in ("money", "avg") else "applications, not beneficiaries."))
        n = p.top_n or len(order)
        if n < len(order) and not p.both and not p.nth:
            last = order[-1]
            out.append(f"{'Highest' if p.low else 'Lowest'}: {last.title()} "
                       f"({rupees_crore(tot[last]) if m == 'money' else indian(tot[last])}).")
        return out
    # the per-district table
    # 3+ schemes: a summary, then one block of points per district (user report 2026-11-03:
    # five schemes ran together on one wrapped line per district, "MGNREGA 1,06,136 /
    # ₹321.79 crore | PMAY-G …"). Two schemes keep the lines below.
    tabled = len(have) >= 3 and p.grain != "village" and p.op == "list"
    if tabled:
        out += _district_tables(p, figs, have, keys, totals)
    for k in ([] if tabled else keys):
        cells = []
        for s in have:
            f = figs[s].get(k, {})
            parts = []
            if "count" in p.measures:
                parts.append(count_text(s, f, short=True, p=p))
            if "money" in p.measures:
                parts.append(money_text(s, f, short=True) if has_measure(s, "money") else "no money")
            if "villages" in p.measures:
                parts.append(f"{indian(f.get('villages', 0))} villages")
            cells.append(f"{SHORT[s]} {' / '.join(parts)}")
        line = f"- {k if p.grain == 'village' else k.title()}: " + " | ".join(cells)
        if "money" in p.measures and "count" not in p.measures:
            line += f" | Total {rupees_crore(sum(value(figs[s].get(k, {}), 'money') for s in have if has_measure(s, 'money')))}"
        if len(have) == 2 and p.op != "condition" and all(has_measure(s, m) for s in have):
            order = sorted(have, key=lambda s: value(figs[s].get(k, {}), m), reverse=True)
            if value(figs[order[0]].get(k, {}), m) != value(figs[order[1]].get(k, {}), m):
                line += f" → {order[0]}"
        out.append(line)
    tot_parts = []
    if p.grain == "village":
        # same-named villages are different places: one row each, never added (KI-630)
        out.append("These are different villages that share a name; their figures are not added.")
        have = []
    for s in ([] if tabled else have):      # the blocks carry their own Total
        t = _scheme_total(s, figs, keys, totals)
        bits = []
        if "count" in p.measures:
            bits.append(indian(t["count"]))
        if "money" in p.measures:
            bits.append(rupees_crore(t["money"]) if has_measure(s, "money") else "no money")
        tot_parts.append(f"{SHORT[s]} {' / '.join(bits)}" if bits else None)
    tot_parts = [x for x in tot_parts if x]
    if tot_parts:
        label = ("Total for these districts" if p.grain == "district" else
                 f"Total for {p.place_label}") if p.districts else "Total"
        out.append(f"**{label}:** " + " | ".join(tot_parts))
    if len(have) == 2 and p.op != "condition" and all(has_measure(s, m) for s in have):
        lead = {s: 0 for s in have}
        for k in keys:
            a, b = (value(figs[s].get(k, {}), m) for s in have)
            if a != b:
                lead[have[0] if a > b else have[1]] += 1
        out.append(f"{have[0]} leads in {lead[have[0]]} {p.grain}{'s' if lead[have[0]] != 1 else ''}, "
                   f"{have[1]} in {lead[have[1]]}.")
    if "count" in p.measures and "Focus Plus" in have and any(
            figs["Focus Plus"].get(k) for k in keys) and not p.districts:
        out.append(f"{p.grain.title()} = the {p.grain} written in each scheme's own records (Focus Plus: its "
                   f"source file's {p.grain} names).")
    return out


def _scheme_total(s: str, figs: dict, keys: list, totals: "dict | None") -> dict:
    """One scheme's Total per measure: its statewide figure when fetched (G-12: records
    with no district still count), else the sum of the district rows."""
    return {mm: value((totals or {}).get(s) or {}, mm) if (totals or {}).get(s) else
            sum(value(figs[s].get(k, {}), mm) for k in keys) for mm in ("count", "money", "villages")}


def _district_tables(p: Plan, figs: dict, have: list, keys: list, totals: "dict | None") -> list:
    """The per-district figures of 3+ schemes, point-wise (user report 2026-11-03: the
    one-line-per-district form ran five schemes together; then "give it in points, with
    space below each, and a crisp summary"): a **Summary** (each scheme's top district,
    said once when one district tops them all), the **Total** block, then one block per
    district, a point per scheme, a blank line after each block. Every figure is the same
    text the line form wrote (count_text / money_text / villages, the Total line's
    statewide figures, and the money-only per-district cross-scheme total)."""
    paid = [s for s in have if has_measure(s, "money")]
    asked = [x for x in ("count", "money", "villages") if x in p.measures]
    money_alone = "money" in p.measures and "count" not in p.measures

    def figures(s: str, f: dict, total: "dict | None" = None) -> str:
        bits = []
        for mm in asked:
            if mm == "count":
                bits.append(indian(total["count"]) if total else count_text(s, f, short=True, p=p))
            elif mm == "money":
                bits.append(("no money" if not has_measure(s, "money") else
                             rupees_crore(total["money"]) if total else money_text(s, f, short=True)))
            else:
                bits.append(f"{indian(total['villages'] if total else f.get('villages', 0))} villages")
        return " · ".join(bits)

    def block(title: str, points: list) -> list:
        return [f"**{title}**"] + [f"- {x}" for x in points] + [""]

    # the summary: each scheme's top place per asked measure
    found = {}
    for s in have:
        for mm in [x for x in ("count", "money") if x in p.measures and has_measure(s, x)]:
            vals = {k: value(figs[s].get(k, {}), mm) for k in keys}
            best = max(vals.values(), default=0)
            if best > 0:
                top = [k for k in keys if vals[k] == best]
                found[(s, mm)] = (" and ".join(k.title() for k in top), fmt(s, figs[s].get(top[0], {}), mm))
    summary = []
    places = {n for n, _v in found.values()}
    word = " and ".join("beneficiaries" if mm == "count" else "money"
                        for mm in ("count", "money") if any(m == mm for _s, m in found))
    # one sentence only when every scheme has a top place on every asked measure (CM Elevate
    # records no money, so "on beneficiaries and money" would not hold for it)
    every = all((s, mm) in found for s in have for mm in ("count", "money") if mm in p.measures)
    if len(keys) > 1 and len(places) == 1 and every:
        summary.append(f"{next(iter(places))} is the top {p.grain} in every scheme, on {word}.")
    else:
        for s in have:
            mine = [(mm, found[(s, mm)]) for mm in ("count", "money") if (s, mm) in found]
            if len(mine) == 2 and mine[0][1][0] == mine[1][1][0]:
                summary.append(f"{SHORT[s]}: top {p.grain} {mine[0][1][0]} ({mine[0][1][1]} · {mine[1][1][1]}).")
            elif mine:
                summary.append(f"{SHORT[s]}: " + "; ".join(
                    f"most {'money' if mm == 'money' else 'beneficiaries'} in {n} ({v})" for mm, (n, v) in mine) + ".")
    out: list = []
    if summary and len(keys) > 1:
        out += block("Summary", summary)
    label = ("Total for these districts" if p.grain == "district" else
             f"Total for {p.place_label}") if p.districts else "Total"
    tot = [f"{SHORT[s]}: {figures(s, {}, _scheme_total(s, figs, keys, totals))}" for s in have]
    if money_alone:
        tot.append(f"All schemes: {rupees_crore(sum(_scheme_total(s, figs, keys, totals)['money'] for s in paid))}")
    out += block(label, tot)
    for k in keys:
        pts = [f"{SHORT[s]}: {figures(s, figs[s].get(k, {}))}" for s in have]
        if money_alone:
            pts.append(f"All schemes: {rupees_crore(sum(value(figs[s].get(k, {}), 'money') for s in paid))}")
        out += block(k.title(), pts)
    return out


def _headline_count(s: str, f: dict, p: Plan) -> str:
    """The scheme's count beside its lead figure, when that is another figure (MGNREGA households beside its
    person-days); '' when the lead figure IS the count (PMAY-G houses sanctioned)."""
    if "ben" not in f:
        return ""
    e = cross_registry.BY_NAME[s]
    tail = ", counted once per year worked" if e.summed_over_years and p.year is None else ""
    return f" ({indian(f['ben'])} {e.noun}{tail})"


def _headline_lines(p: Plan, figs: dict, have: list) -> list:
    """Each scheme's own lead figure (data/cross_scheme.yaml `headline`: the figure its overview card shows first,
    by the same SQL), in its own unit, with its count when that is another figure. They count different things,
    so they are never added."""
    out = ["Each scheme's headline figure (the figure its overview card leads with):"]
    for s in have:
        h = cross_registry.BY_NAME[s].headline
        for k, f in figs[s].items():
            where = "" if k == STATE else f", {k}"
            out.append(f"- **{SHORT[s]}**{where}: {indian(f.get('headline', 0))} {h.noun}{_headline_count(s, f, p)}")
    if len(have) >= 2:
        out.append("Each scheme counts its own thing, so these figures are not added.")
    return out


def _headline_rows(p: Plan, figs: dict, have: list) -> list[dict]:
    """One row per scheme: its lead figure (`measure`, `value`) and, in the shared `beneficiaries` column, its count."""
    rows = []
    for s in have:
        h = cross_registry.BY_NAME[s].headline
        for k, f in figs[s].items():
            r = {} if k == STATE else {"village": k}
            lead = int(round(f.get("headline", 0.0)))
            rows.append({**r, "scheme": s, "measure": h.label, "value": lead,
                         "beneficiaries": int(round(f["ben"])) if "ben" in f else lead})
    return rows


def _rows(p: Plan, figs: dict, have: list) -> list[dict]:
    """The result table: one row per scheme (and district), the asked measures only.
    Every scheme's count is in the one `beneficiaries` column (what each counts is
    in the answer text), so a chart or the two-way card compares the asked measure
    for every scheme — never money in its place, never a missing column read as 0
    (user reports 2026-10-22, 2026-10-27)."""
    if p.op == "headline":
        return _headline_rows(p, figs, have)
    rows = []
    if p.op == "by_year":
        # one row shape for every scheme: scheme, financial_year ("2023-24"), the measures
        for s in have:
            for k in sorted(figs[s], key=int):
                f = figs[s][k]
                r = {"scheme": s, "financial_year": _fy(k)}
                if "count" in p.measures:
                    r["beneficiaries"] = int(f.get("ben", 0))
                if "money" in p.measures:
                    r["amount_crore"] = round(f.get("money", 0.0), 2) if has_measure(s, "money") else None
                if "villages" in p.measures:
                    r["villages"] = int(f.get("villages", 0))
                rows.append(r)
        return rows
    ranked = ranked_districts(p, figs, have)
    if ranked is not None:
        # A ranking's table is the ranked districts only, in rank order (I-7): it
        # was every district, alphabetical, under a "top 5" answer.
        m = primary(p)
        col = {"count": "beneficiaries", "money": "amount_crore", "villages": "villages",
               "avg": "rupees_per_beneficiary"}[m]
        have = ranked_schemes(p, have, m)
        for s in have:
            for i, k in ranked.get(s, ranked.get("")):
                v = value(figs[s].get(k, {}), m)
                rows.append({"rank": i, "district": k.title(), "scheme": s,
                             col: round(v, 2) if m in ("money", "avg") else int(v)})
        if "" in ranked:
            # a combined ranking: district by district in rank order, each scheme's figure
            pos = {k: n for n, (_i, k) in enumerate(ranked[""])}
            rows.sort(key=lambda r: (pos[r["district"].upper()], have.index(r["scheme"])))
        return rows
    for s in have:
        for k, f in sorted(figs[s].items()):
            if p.districts and p.by_district and p.grain == "district" \
                    and k.upper() not in {d.upper() for d in p.districts}:
                continue
            if p.exclude and k.upper() in {d.upper() for d in p.exclude}:
                continue
            r = {p.grain: (k if p.grain == "village" else k.title())} if k != STATE else {}
            if p.grain == "village" and k in {v: c for c, v in p.villages.items()}:
                r["village_code"] = {v: c for c, v in p.villages.items()}[k]
            r["scheme"] = s
            if "count" in p.measures:
                r["beneficiaries"] = int(f.get("ben", 0))
                if s == "PMAY-G" and p.completed:
                    r["houses_completed"] = int(f.get("completed", 0))
                if s == "Focus Legacy" and p.pgs:
                    r["producer_groups"] = int(f.get("pgs", 0))
            if "money" in p.measures:
                # a scheme with no money keeps the column, as null (the UI shows a dash, never 0)
                r["amount_crore"] = round(f.get("money", 0.0), 2) if has_measure(s, "money") else None
                if s == "PMAY-G":
                    r["sanctioned_crore"] = round(f.get("sanctioned", 0.0), 2)
            if "villages" in p.measures:
                r["villages"] = int(f.get("villages", 0))
            if p.avg and has_measure(s, "avg") and avg_value(f):
                r["rupees_per_beneficiary"] = round(avg_value(f))
            rows.append(r)
    return rows
