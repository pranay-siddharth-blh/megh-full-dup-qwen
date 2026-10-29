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
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app import db
from app.text_match import ANY, Alt, Gap, Matcher, Opt, Seq, W, tokens

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
                         block: "str | None" = None, year: "int | None" = None,
                         by_year: bool = False, years: "list[int] | None" = None) -> tuple[dict, list[str]]:
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
            if years:
                params.append([int(y) for y in years])
                where.append(f"year_key = ANY(${len(params)}::int[])")
            sql = _sql(view, "year_key" if by_year else (dcol if by_district else None), metrics, where)
            rows = [dict(r) for r in await db.fetch_rows(sql, params)]
            got = any(any(v for k, v in r.items() if k != "k") for r in rows)
            if got or attempt_bcol == _FP_LGD_BLOCK or not block or scheme != "Focus Plus":
                shown.append(sql)
                for r in rows:
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
                             S("job", W("card", "cards")), W("jobcard", "jobcards", "application", "applications",
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


# ── rank words at a place level (audit 2026-10-29, I-1 / I-3 / I-4 / I-14 / I-16 / I-18) ──
# "bottom 5 districts", "5 lowest districts", "which district has the lowest",
# "best 3 districts", "highest district", "rank districts by", "kis district me sabse
# jyada" were all answered as "which scheme is bigger statewide": only "top N
# districts", plural "which districts" and "districts with" read as a district
# ranking. A place level (singular or plural, a near-miss spelling) beside any rank
# word is a ranking at that level, never a scheme leader.
_HIGH_RANK = frozenset({"top", "highest", "most", "maximum", "max", "best", "leading", "largest", "biggest",
                        "greatest", "strongest"})
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


def plan(text: str, schemes: list, resolved: dict, display: "dict | None",
         scheme_matchers: dict) -> "Plan | None":
    """What to compute for a cross-scheme question, or None when its shape is not
    one this module answers (the D-062 model path takes it). `text` is the
    question with any excluded schemes masked out."""
    ask = rank_ask(text)
    drank = ask is not None and ask.level == "district"
    left_out = [s for s in (schemes or []) if s not in SUPPORTED]
    if left_out and not (drank and len([s for s in schemes if s in SUPPORTED]) >= 2):
        return None                      # CM Elevate / CM Elevate Legacy: the model path
    # I-13: "top 5 districts across all schemes" ranks the four coded schemes and
    # says CM Elevate is not in it, rather than leaving the coded path for a merge
    schemes = [s for s in SUPPORTED if s in schemes]
    if len(schemes) < 2:
        return None
    r = resolved or {}
    if any(r.get(k) for k in ("village_code", "village_code_list", "assembly_constituency", "block_list")):
        return None
    if _OTHER_MEASURE.search(text):
        return None                      # B-7: "person days" was answered with beneficiaries and money
    if ask is not None and ask.level != "district":
        return None                      # top / lowest villages, blocks: a list per scheme (model path)
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
    timed = bool(r.get("year_key_list"))
    if _YEARLY.search(text) or (drank and timed):
        return None                      # a district ranking per year: a list per scheme and year
    if not drank and _OTHER_PLACES.search(text):
        return None
    if timed and (_MONTHLY.search(text) or _DISTRICT_GRAIN.search(text)):
        return None
    if _top_n(text) and not (drank or _DISTRICT_GRAIN.search(text)):
        return None                      # a "top N" of anything but districts is a list
    districts = r.get("district_list") or ([r["district"]] if r.get("district") else None)
    block = r.get("block")
    if block and districts:
        districts = None                 # the block settles the place
    exclude = _excluded_places(text, districts or []) if drank else []
    if exclude:
        districts = [d for d in districts if d not in exclude] or None
    money, count, vill = bool(_MONEY.search(text)), bool(_COUNT.search(text)), bool(_VILLAGES.search(text))
    perf, summary, avg = bool(_PERFORMANCE.search(text)), bool(_SUMMARY.search(text)), bool(_AVG.search(text))
    by_district = drank or bool(_DISTRICT_GRAIN.search(text)) or bool(districts and len(districts) > 1)
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
             top_n=_top_n(text),
             rank_measures=bool(_RANK_MEASURES.search(text)) and not by_district,
             lead_all=perf or (count and money),
             both=bool(drank and ask.high and ask.low), nth=ask.nth if drank else None,
             exclude=exclude, left_out=left_out, better=better, years=list(r.get("year_key_list") or []) if timed else None)
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
    if p.block:
        p.place_label = f"{str(disp.get('block') or p.block).title()} block"
    elif p.districts and len(p.districts) == 1:
        p.place_label = f"{p.districts[0].title()} district"
    elif p.districts:
        p.place_label = ", ".join(d.title() for d in p.districts)
    if p.year is not None:
        p.period_label = f"FY {p.year}-{(p.year + 1) % 100:02d}"


# ── villages in both / either / only one scheme (G-8, I-5) ────────────────────
_VILLAGE_SET_FILTER = {"Focus Plus": "village_code > 0 AND entity_type <> 'Unresolved'",
                       "Focus Legacy": "village_code > 0 AND entity_type <> 'Unresolved'"}


async def village_sets(p: Plan) -> tuple[dict, list[str]]:
    """{scheme: {village_code, ...}} for the plan's place and year, and the SQL run."""
    out, shown = {}, []
    for s in p.schemes:
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
        sql = f"SELECT DISTINCT village_code AS v FROM {view} WHERE {' AND '.join(where)}"
        shown.append(sql)
        out[s] = {int(r["v"]) for r in await db.fetch_rows(sql, params) if r["v"] is not None}
    return out, shown


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


SHORT = {"MGNREGA": "MGNREGA", "PMAY-G": "PMAY-G", "Focus Plus": "Focus Plus", "Focus Legacy": "Focus Legacy"}
_BEN_NOUN = {"MGNREGA": "households given work", "PMAY-G": "houses sanctioned",
             "Focus Plus": "beneficiaries", "Focus Legacy": "members"}
_MONEY_VERB = {"MGNREGA": "spent", "PMAY-G": "released", "Focus Plus": "disbursed", "Focus Legacy": "disbursed"}


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
        return f"₹{indian(avg_value(f) or 0)} {_PER[s]}"
    if measure == "money":
        return rupees_crore(f.get("money", 0))
    if measure == "villages":
        return f"{indian(f.get('villages', 0))} villages"
    return f"{indian(f.get('ben', 0))} members" if s == "Focus Legacy" else indian(f.get("ben", 0))


# ── computing and writing the answer ──────────────────────────────────────────

async def answer(p: Plan) -> dict:
    """{'answer', 'rows', 'sql'} for a plan."""
    if p.op == "overlap":
        return await _overlap_answer(p)
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
        if p.op == "by_year" and p.years:
            held = await _years_held(s)
            missing = [y for y in p.years if y not in held]
            if len(missing) == len(p.years):
                gaps[s] = f"{s} has no data for {p.period_label}"
                continue
            if missing:
                gaps[s] = f"{s} has no data for " + ", ".join(f"FY {y}-{(y + 1) % 100:02d}" for y in missing)
        got, sql = await scheme_figures(s, by_district=p.by_district, districts=p.districts,
                                        block=p.block, year=p.year,
                                        by_year=p.op == "by_year", years=p.years or None)
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
    if p.op == "by_year":
        lines += _year_lines(p, figs, have)
    elif p.by_district:
        lines += _district_lines(p, figs, have, totals)
    else:
        lines += _state_lines(p, {s: figs[s].get(STATE, {}) for s in have}, have)
    if gaps:
        lines.append(" ".join(f"{g}." for g in gaps.values()))
    if p.left_out:
        lines.append(f"{' and '.join(p.left_out)} {'is' if len(p.left_out) == 1 else 'are'} not in this ranking: "
                     "they record applications and sanctions, not these figures; ask for their district "
                     "list on its own.")
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
            "totals": col_totals, "measure_notes": measure_notes(have)}


# G-9 / B-11 (audit 2026-10-29): every scheme's count sits in one `beneficiaries`
# column and its money in one `amount_crore` column, so the tiles, axes and table
# said "beneficiaries" for MGNREGA household-years and "amount" for money spent,
# released and disbursed alike. What each column means for each scheme goes with
# the answer (the rows keep their shape, user report 2026-10-27).
_COUNT_NOTE = {"MGNREGA": "household-years: households given work, counted once per year worked",
               "PMAY-G": "houses sanctioned", "Focus Plus": "distinct beneficiaries",
               "Focus Legacy": "producer-group members"}
_MONEY_NOTE = {"MGNREGA": "money spent", "PMAY-G": "money released", "Focus Plus": "money disbursed",
               "Focus Legacy": "money disbursed"}


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
            noun = {"count": _BEN_NOUN[s], "money": f"money {_MONEY_VERB[s]}", "villages": "villages covered"}[m]
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
        parts.append(money_text(s, f))
    if "villages" in p.measures:
        parts.append(villages_text(f, state and not (p.block or p.districts)))
    if p.avg and avg_value(f):
        parts.append(f"₹{indian(avg_value(f))} {_PER[s]}")
    return f"- **{SHORT[s]}:** " + ", ".join(parts)


def _state_lines(p: Plan, f: dict, have: list) -> list:
    # MGNREGA's household-year note is on its own line (_scheme_line), not a sentence of its own
    out = [_scheme_line(s, f[s], p, True) for s in have]
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
    if p.better:
        out.append("The schemes measure different things (" + ", ".join(f"{s} {_BEN_NOUN[s]}" for s in have)
                   + "), so neither is better on size alone. Ask for a measure to compare them on: "
                   "beneficiaries, money spent, villages covered or money per beneficiary.")
        return out
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
    if _ranks_combined(p, m):
        order = _rank_order(p, keys, lambda k: sum(value(figs[s].get(k, {}), m) for s in have))
        return {"": [ik for _l, part in _rank_parts(p, order) for ik in part]}
    return {s: [ik for _l, part in _rank_parts(p, _rank_order(p, keys, lambda k, s=s: value(figs[s].get(k, {}), m)))
                for ik in part] for s in have}


def _district_keys(p: Plan, figs: dict, have: list) -> list:
    keys = sorted({k for s in have for k in figs[s] if k != STATE})
    if p.districts:
        keys = [k for k in keys if k in {d.upper() for d in p.districts}]
    if p.exclude:
        keys = [k for k in keys if k not in {d.upper() for d in p.exclude}]
    return keys


def _district_lines(p: Plan, figs: dict, have: list, totals: "dict | None" = None) -> list:
    keys = _district_keys(p, figs, have)
    m = primary(p)
    out = []
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
                f"{s} {_MONEY_VERB[s]}" for s in have) + "), added because the question asks for the total.")
        n = p.top_n or len(order)
        if n < len(order) and not p.both and not p.nth:
            last = order[-1]
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
                parts.append(count_text(s, f, short=True, p=p))
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
    """The result table: one row per scheme (and district), the asked measures only.
    Every scheme's count is in the one `beneficiaries` column (what each counts is
    in the answer text), so a chart or the two-way card compares the asked measure
    for every scheme — never money in its place, never a missing column read as 0
    (user reports 2026-10-22, 2026-10-27)."""
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
                    r["amount_crore"] = round(f.get("money", 0.0), 2)
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
            if p.districts and p.by_district and k.upper() not in {d.upper() for d in p.districts}:
                continue
            if p.exclude and k.upper() in {d.upper() for d in p.exclude}:
                continue
            r = {"district": k.title()} if k != STATE else {}
            r["scheme"] = s
            if "count" in p.measures:
                r["beneficiaries"] = int(f.get("ben", 0))
                if s == "PMAY-G" and p.completed:
                    r["houses_completed"] = int(f.get("completed", 0))
                if s == "Focus Legacy" and p.pgs:
                    r["producer_groups"] = int(f.get("pgs", 0))
            if "money" in p.measures:
                r["amount_crore"] = round(f.get("money", 0.0), 2)
                if s == "PMAY-G":
                    r["sanctioned_crore"] = round(f.get("sanctioned", 0.0), 2)
            if "villages" in p.measures:
                r["villages"] = int(f.get("villages", 0))
            if p.avg and avg_value(f):
                r["rupees_per_beneficiary"] = round(avg_value(f))
            rows.append(r)
    return rows
