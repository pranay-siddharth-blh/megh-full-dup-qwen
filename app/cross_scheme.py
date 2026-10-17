"""
Cross-scheme comparisons, answered deterministically.

"Compare Focus+, FOCUS and CM-ELEVATE in East Khasi Hills", "which scheme has the
highest beneficiary count in each district?", "district-wise summary of MGNREGA,
PMAY-G, Focus+, FOCUS and CM-ELEVATE" (Cross Scheme Test Cases sheet, 2026-10-13).

Before this, such a question went to the SQL generator with every named scheme's
schema at once. On the testers' 20 cases it paused 18 times (a nine-year FY list
merged across schemes, "which area?", "which scheme?") and the two answers it did
give were wrong: "(no label)" rows, and one "total across all schemes" that added
MGNREGA expenditure to PMAY-G releases.

Here each scheme's figure is computed with exactly the rule its own single-scheme
answer uses (the rules the six scheme sheets were passed on), one query per scheme,
and the answer is built from the rows, never composed by a model. Figures of
different kinds (persons employed vs houses vs applications; expenditure vs
releases vs disbursements) are shown side by side with what each one counts and
are never added together.

Measures (single-scheme answers, verified live 2026-10-13):
  MGNREGA            persons employed, SUM(persons_employed) over the years asked;
                     money = SUM(total_exp) (lakh)
  PMAY-G             houses sanctioned, COUNT(*) WHERE NOT is_placeholder;
                     money = SUM(amount_released)
  Focus Plus         beneficiaries, COUNT(DISTINCT beneficiary_key); money = SUM(amount_disbursed)
  Focus Legacy       memberships paid, SUM(no_of_pg_members) (+ producer groups,
                     COUNT(DISTINCT pg_id)); money = SUM(amount_disbursed)
  CM Elevate         applications, COUNT(DISTINCT request_id); no money, no year
  CM Elevate Legacy  sanctioned applicants, COUNT(*); money = SUM(total_disbursement)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app import db
from app.text_match import ANY, Alt, Matcher, Node, Opt, Pred, Seq, W, fy_spans

logger = logging.getLogger(__name__)

ORDER = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CM Elevate Legacy"]


@dataclass(frozen=True)
class SchemeSpec:
    name: str
    count_view: str
    count_expr: str
    count_label: str
    money_view: str | None
    money_expr: str | None          # in RUPEES
    money_label: str | None
    base_where: str = "TRUE"
    village_where: str = "village_code IS NOT NULL"
    has_year: bool = True
    # how an assembly constituency filters this scheme: "column" (v_employment's own
    # column), "geo" (dim_geography.ac_name on geography_key) or None (not recorded)
    ac_count: str | None = None
    ac_money: str | None = None
    extra_count: tuple = field(default_factory=tuple)   # (expr, label) shown beside the count


SPECS: dict[str, SchemeSpec] = {
    "MGNREGA": SchemeSpec(
        "MGNREGA", "curated.v_employment", "SUM(persons_employed)", "persons employed",
        "curated.v_expenditure", "SUM(total_exp) * 100000", "expenditure incurred",
        ac_count="column"),
    "PMAY-G": SchemeSpec(
        "PMAY-G", "curated.v_pmay", "COUNT(*)", "houses sanctioned",
        "curated.v_pmay", "SUM(amount_released)", "amount released",
        base_where="NOT is_placeholder"),
    "Focus Plus": SchemeSpec(
        "Focus Plus", "curated.v_focus_plus", "COUNT(DISTINCT beneficiary_key)", "beneficiaries",
        "curated.v_focus_plus", "SUM(amount_disbursed)", "amount disbursed to farmers",
        village_where="village_code > 0"),
    "Focus Legacy": SchemeSpec(
        "Focus Legacy", "curated.v_focus_legacy", "SUM(no_of_pg_members)",
        "producer-group memberships paid",
        "curated.v_focus_legacy", "SUM(amount_disbursed)", "amount remitted to producer groups",
        village_where="village_code > 0 AND entity_type <> 'Unresolved'",
        ac_count="geo", ac_money="geo",
        extra_count=(("COUNT(DISTINCT pg_id)", "producer groups"),)),
    "CM Elevate": SchemeSpec(
        "CM Elevate", "curated.v_cm_elevate", "COUNT(DISTINCT request_id)", "applications",
        None, None, None,
        village_where="village_code IS NOT NULL AND entity_type <> 'Unresolved'", has_year=False),
    "CM Elevate Legacy": SchemeSpec(
        "CM Elevate Legacy", "curated.v_cm_elevate_disbursement", "COUNT(*)", "sanctioned applicants",
        "curated.v_cm_elevate_disbursement", "SUM(total_disbursement)",
        "subsidy and loan disbursed",
        village_where="village_code > 0 AND entity_type <> 'Unresolved'",
        ac_count="geo", ac_money="geo"),
}

DISPLAY = {"MGNREGA": "MGNREGA", "PMAY-G": "PMAY-G", "Focus Plus": "Focus Plus",
           "Focus Legacy": "Focus Legacy (FOCUS)", "CM Elevate": "CM Elevate (applications)",
           "CM Elevate Legacy": "CM Elevate Legacy (CM-ELEVATE)"}

# ── detection ────────────────────────────────────────────────────────────────

def _xs_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def S(*parts) -> Seq:
    """Words in a row with only whitespace between them (a regex `a\s+b`)."""
    return Seq(*parts, sep="space")


class _XsGlued(Node):
    """Words written together as typed, matched on the characters: `parts` are
    tuples of spellings (case-insensitive, tried in order) and gap kinds between
    them — "?" at most one space or hyphen, "+" one or more, "*" any number,
    "s+" one or more spaces. The match starts and ends on word boundaries, so
    "person_days" (an identifier) is not "person days"."""

    def __init__(self, *parts):
        self.parts = parts

    def _ends(self, text, k, pos):
        if k == len(self.parts):
            yield pos
            return
        part = self.parts[k]
        if isinstance(part, tuple):
            for o in part:
                if text[pos:pos + len(o)].lower() == o:
                    yield from self._ends(text, k + 1, pos + len(o))
            return
        run = pos
        while run < len(text) and (text[run].isspace() or (text[run] == "-" and part != "s+")):
            run += 1
        run -= pos
        lo = 1 if part in ("+", "s+") else 0
        hi = min(run, 1) if part == "?" else run
        for n in range(hi, lo - 1, -1):
            yield from self._ends(text, k + 1, pos + n)

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks):
            return
        for pos in self._ends(ctx.text, 0, ctx.toks[i].start):
            for j in range(i, len(ctx.toks)):
                if ctx.toks[j].end == pos:
                    yield j + 1, caps
                    break
                if ctx.toks[j].end > pos:
                    break


G = _XsGlued


class _XsBareFocus(Node):
    """The word "focus", not written as "legacy focus" / "old focus" (exactly one
    space between), and not followed — across spaces and hyphens — by "+",
    "plus", "legacy" or "pg"."""

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks) or ctx.toks[i].low != "focus":
            return
        tok, text = ctx.toks[i], ctx.text
        if text[:tok.start].lower().endswith(("legacy ", "old ")):
            return
        j = tok.end
        while j < len(text) and (text[j].isspace() or text[j] == "-"):
            j += 1
        if text.startswith("+", j):
            return
        if i + 1 < len(ctx.toks) and ctx.toks[i + 1].start == j \
                and ctx.toks[i + 1].low in ("plus", "legacy", "pg"):
            return
        yield i + 1, caps


class _XsWorkNearby(Node):
    """The word "work" starting at most 40 characters after the previous word,
    with no "?" in between (the "how does … work" knowledge question)."""

    def ends(self, ctx, i, caps):
        if i == 0:
            return
        base = ctx.toks[i - 1].end
        for k in range(i, len(ctx.toks)):
            t = ctx.toks[k]
            if t.start - base > 40 or "?" in ctx.text[base:t.start]:
                return
            if t.low == "work":
                yield k + 1, caps


# A bare "FOCUS" written beside "Focus+" is the other Focus — the testers' sheets
# call Focus Legacy "FOCUS" and Focus Plus "Focus +". Alone, a bare "Focus" stays
# the two-way ask (docs/SCHEMES.md "Name collisions").
_BARE_FOCUS = Matcher(_XsBareFocus())

_XS_ALL_THE = S("all", Opt("the"))

# The question asks across schemes without naming them: "which scheme …",
# "each scheme", "across the schemes", "all schemes", "scheme-wise".
_ALL_SCHEMES_CUE = Matcher(Alt(
    S(W("which", "what"), W("scheme", "schemes")),
    S(W("each", "every", "per"), "scheme"),
    S(W("across", "among", "between", "over"),
        Opt(Alt("the", _XS_ALL_THE, "different", "various")), "schemes"),
    S("all", Opt("the"), Opt(W("six", "6")), "schemes"),
    G(("scheme",), "?", ("wise",)),
    S("by", "scheme"),
    S(W("six", "6", "different", "various", "other"), "schemes"),
    G(("cross",), "?", ("scheme",)),
    S("compare", Opt(Alt("the", _XS_ALL_THE)), "schemes"),
))

# Words that ask for a figure this module does not compute (each scheme's own
# measures, statuses, cohorts …). Such a question keeps the normal path.
_OTHER_MEASURE = Matcher(Alt(
    G(("person",), "?", ("days", "day")), G(("job",), "?", ("cards", "card")), G(("100",), "?", ("days", "day")),
    W("women", "wage", "wages", "material", "completed", "completion"),
    G(("in",), "?", ("progress",)),
    W("instalment", "instalments", "installment", "installments"),
    W("tranch", "batch", prefix=True),
    W("gender", "female", "male", "status", "pending", "rejected"),
    G(("on",), "?", ("hold",)),
    W("verif", "withdraw", prefix=True),
    W("loan", "loans", "subsidy", "subsidies", "lender", "lenders"),
    S("sanctioned", "amount"),
    W("bank", "banks", "ifsc", "occupation", "farmer", "farmers", "piggery", "poultry", "dairy", "goat",
      "sericulture"),
    S("green", "taxi"),
    W("warehouse", "product", "products"),
    W("commodit", "eligib", prefix=True),
    W("apply", "document", "documents", "objective", "objectives"),
    S("benefits", "of"),
    W("month", prefix=True),
    Seq(S("how", W("does", "do")), _XsWorkNearby()),
    # "what is MGNREGA and PMAY-G?" is a knowledge question; "what is the
    # beneficiary count across …" / "what is the performance of …" is not
    S("what", W("is", "are"), Opt("the"),
        Alt(W("mgnrega", "nrega", "scheme", "schemes"), W("pmay", "focus", "cm", prefix=True))),
    W("overlap", prefix=True),
    S("both", "schemes", "operate"),
    W("common", "convergence", "name", "names"),
    S("list", Opt("the"), "villages"),
))

_MONEY = Matcher(Alt(
    W("money", "amount", "amounts", "spent", "expenditure", "paid", "payment", "payments",
      "fund", "funds", "funding", "crore", "crores", "lakh", "lakhs", "rupee", "rupees", "cost", "budget",
      "outlay", "financial", "finance", "assistance", "support"),
    W("spend", "disburs", "releas", "invest", prefix=True),
))
_COUNT = Matcher(Alt(
    W("beneficiar", "applica", "reach", prefix=True),
    W("applicant", "applicants", "count", "counts"),
    S("number", "of"), S("how", "many"),
    W("people", "person", "persons", "household", "households", "house", "houses", "scale",
      "concentration", "record", "records", "cases"),
))
_COVERAGE = Matcher(W("coverage", "cover", "covers", "covered", "covering", "widest", "spread", "footprint",
                      "presence", "reach"))
_RANK = Matcher(Alt(
    S(W("which", "what"), W("one", "scheme")),
    W("highest", "higher", "lowest", "lower", "most", "more", "less", "least", "widest", "largest",
      "biggest", "bigger", "larger", "greater", "smaller", "maximum", "minimum", "leading", "lead", "leads",
      "top", "best"),
    W("rank", prefix=True),
))
_XS_EACH = Alt(W("each", "every", "per"), _XS_ALL_THE)
_BY_DISTRICT = Matcher(Alt(
    G(("district",), "?", ("wise",)),
    S(_XS_EACH, W("district", "districts")),
    S("by", W("district", "districts")),
    S("across", Opt(Alt("the", _XS_ALL_THE)), "districts"),
    S("in", Opt("the"), "districts"),
    S("districts", W("of", "in"), "meghalaya"),
    S("which", W("district", "districts")),
    S("district", "level"),
    S("for", "each", "district"),
    G(("district",), "?", ("by",), "?", ("district",)),
))
_BY_BLOCK = Matcher(Alt(
    G(("block",), "?", ("wise",)),
    S(_XS_EACH, W("block", "blocks")),
    S("by", W("block", "blocks")),
    S("across", Opt(Alt("the", _XS_ALL_THE)), "blocks"),
    S("which", W("block", "blocks")),
))
_WHICH_DISTRICTS = Matcher(Alt(
    S(W("which", "what"), W("district", "districts")),
    S("top", Opt(Pred(str.isdecimal)), W("district", "districts")),
    W("concentration"),
))
_LEADER_PER_DISTRICT = Matcher(Alt(
    S(W("which", "what"), "scheme"),
    S("which", "of"),
    S("leading", "scheme"),
    S("scheme", Opt("that"), "leads"),
    W("identify"),
))
# "compare …", "summary …", "performance", "district-wise": a comparison is asked
_XS_COMPARISON = Matcher(Alt(W("compar", "summar", prefix=True), W("performance", "wise")))
# "all / other / six / each …": the question reaches past the one scheme it names
_XS_BEYOND_ONE = Matcher(W("all", "other", "six", "6", "every", "each", "different", "various"))


def bare_focus_is_legacy(question: str, named: list[str]) -> bool:
    return "Focus Plus" in named and "Focus Legacy" not in named and bool(_BARE_FOCUS.search(question or ""))


def other_measure(text: str) -> bool:
    return bool(_OTHER_MEASURE.search(text or ""))


def detect(question: str, named: list[str], measure_text: str | None = None) -> list[str] | None:
    """The schemes of a cross-scheme comparison this module answers, or None.

    `named` = the schemes the question names (pipeline._SCHEME_NAME_MATCHER, after
    the CM Elevate pin). Two or more named schemes are a comparison; none named plus
    an all-schemes cue ("which scheme …", "each scheme") means all six.
    `measure_text` = the question with its village name masked, for the other-
    measure check: "BIJASIK WAGE APAL village" is not a wages question."""
    q = question or ""
    if _OTHER_MEASURE.search(measure_text if measure_text is not None else q):
        return None
    named = [s for s in ORDER if s in named]
    if bare_focus_is_legacy(q, named):
        named = [s for s in ORDER if s in named or s == "Focus Legacy"]
    if len(named) >= 2:
        return named
    if not _ALL_SCHEMES_CUE.search(q):
        return None
    # "What schemes are available?" lists the schemes; only a figure, a ranking
    # or a comparison across them is ours
    if not (_MONEY.search(q) or _COUNT.search(q) or _COVERAGE.search(q) or _RANK.search(q)
            or _XS_COMPARISON.search(q)):
        return None
    if len(named) == 1 and named[0] in ("CM Elevate", "CM Elevate Legacy"):
        # "which scheme" inside CM Elevate means one of its 15 programmes
        return None
    if len(named) == 1 and not _XS_BEYOND_ONE.search(q):
        return None
    return list(ORDER)


# "How many blocks / villages / schemes …", "block count": a count of places or
# schemes, not of beneficiaries — not ours to answer per scheme.
_PLACE_COUNT = Matcher(Alt(
    S(Alt(S("how", "many"), S("number", "of"), S("count", "of"), "total", "list", "all"), Opt("the"), Opt(ANY),
        Alt(W("blocks", "villages", "districts", "schemes", "programmes", "years"),
            W("constituenc", prefix=True))),
    S(W("block", "blocks", "village", "villages", "district", "districts", "scheme", "schemes"),
        W("count", "name", "names", "list", "code", "codes")),
    W("onboard", prefix=True),
))
# "total block count", "how many villages": answered as each scheme's coverage
_GEO_COUNT = Matcher(Alt(
    S(Alt(S("how", "many"), S("number", "of"), S("count", "of"), "total"), Opt(ANY), W("blocks", "villages", "districts")),
    S(W("block", "blocks", "village", "villages", "district", "districts"), "count"),
))
_APPLICATION_WORDS = Matcher(Alt(W("applica", prefix=True), W("applicant", "applicants")))


def unnamed_schemes(question: str) -> list[str] | None:
    """A data question that names no scheme and that the "which scheme?" pause
    would stop: the schemes that record what it asks for, answered side by side
    (ANSWER_DEFAULTS_ENABLED, 2026-10-14) — or None to keep the pause."""
    q = question or ""
    if _OTHER_MEASURE.search(q):
        return None
    if _GEO_COUNT.search(q):
        return list(ORDER)
    if _PLACE_COUNT.search(q):
        return None
    if _APPLICATION_WORDS.search(q):
        return ["CM Elevate", "CM Elevate Legacy"]
    if _MONEY.search(q):
        return [s for s in ORDER if SPECS[s].money_view]
    if _COUNT.search(q) or _COVERAGE.search(q):
        return list(ORDER)
    return None


@dataclass
class Plan:
    schemes: list[str]
    count: bool
    money: bool
    coverage: bool
    rank: bool
    group: str | None          # None | "district" | "block"
    leader_per_group: bool
    top_districts: bool


# Scheme names are masked before the measure words are read: "CM Elevate
# applicants" names a dataset, it does not ask for a count (a "summary comparing
# MGNREGA vs CM Elevate applicants" lost its money column, run 2026-10-13).
_XS_CM_ELEVATE = (("cm",), "?", ("elevate",))
_XS_CM_SUFFIX = ("*", ("legacy", "disbursements", "disbursement"))
_XS_CM_APPLICANTS = ("s+", ("applicants", "applicant", "applications", "application"))
_SCHEME_WORDS = Matcher(Alt(
    G(*_XS_CM_ELEVATE, *_XS_CM_SUFFIX, *_XS_CM_APPLICANTS),
    G(*_XS_CM_ELEVATE, *_XS_CM_SUFFIX),
    G(*_XS_CM_ELEVATE, *_XS_CM_APPLICANTS),
    G(*_XS_CM_ELEVATE),
    G(("legacy",), "+", *_XS_CM_ELEVATE),
    W("mrega", "mnrega", "mgnrega"),
    G(("pmay",), "?", ("g",)), W("pmay"),
    G(("focus",), "?", ("plus", "legacy")), W("focus", prefix=True),
    G(("legacy",), "?", ("focus",)),
))


def years_in_text(text: str) -> list[int]:
    # "FY2022-23" (no space) is not read by the resolver; "2022-2023", "FY 22-23" are.
    out, last_end = [], -1
    t = text or ""
    for start, end, y, e2 in fy_spans(t):
        if start < last_end or "—" in t[start:end]:
            continue   # spans never overlap; an em dash is not a year separator here
        last_end = end
        if e2 == (y + 1) % 100:
            out.append(y)
    return sorted(set(out))


_XS_WIDEST_ACROSS = Matcher(Alt("widest", S("across", Opt("the"), "districts")))
_XS_PER_DISTRICT = Matcher(Alt(S(W("each", "every", "per"), "district"), G(("district",), "?", ("wise",))))


def plan(question: str, schemes: list[str], resolved: dict) -> Plan:
    q = _SCHEME_WORDS.sub(" ", question or "")
    money = bool(_MONEY.search(q))
    count = bool(_COUNT.search(q))
    coverage = bool(_COVERAGE.search(q) or _GEO_COUNT.search(q))
    # "performance" / "summary" / a bare "compare" with no measure named = both
    # figures; a measure the question names ("performance … based on beneficiary
    # counts", "coverage and financial performance") is what it gets.
    if not (money or count or coverage):
        money = count = True
    if coverage:
        count = True
    places = any(resolved.get(k) for k in ("block", "block_list", "village_code", "village_code_list",
                                            "assembly_constituency"))
    group = None
    if _BY_BLOCK.search(q) and not places:
        group = "block"
    elif _BY_DISTRICT.search(q) and not places and not resolved.get("district"):
        group = "district"
    elif resolved.get("district_list") and len(resolved["district_list"]) > 1:
        group = "district"
    rank = bool(_RANK.search(q))
    leader = bool(group and _LEADER_PER_DISTRICT.search(q) and rank)
    top_districts = bool(_WHICH_DISTRICTS.search(q)) and not resolved.get("district")
    if top_districts and group is None:
        group = "district"
    if coverage and group == "district" and _XS_WIDEST_ACROSS.search(q) \
            and not _XS_PER_DISTRICT.search(q):
        # "widest coverage across districts" = districts / blocks / villages reached per scheme
        group, leader, top_districts = None, False, False
    return Plan(schemes, count, money, coverage, rank, group, leader, top_districts)


# ── SQL ──────────────────────────────────────────────────────────────────────

_FP_RAW_BLOCKS: set[str] | None = None


async def _fp_raw_blocks() -> set[str]:
    global _FP_RAW_BLOCKS
    if _FP_RAW_BLOCKS is None:
        rows = await db.fetch_rows("SELECT DISTINCT UPPER(block_name_raw) b FROM curated.v_focus_plus "
                                   "WHERE block_name_raw IS NOT NULL")
        _FP_RAW_BLOCKS = {r["b"] for r in rows}
    return _FP_RAW_BLOCKS


_ALL_BLOCKS: set[str] | None = None


async def _all_blocks() -> set[str]:
    """Every block any of the six schemes records (LGD names, plus Focus Plus's
    own spellings)."""
    global _ALL_BLOCKS
    if _ALL_BLOCKS is None:
        rows = await db.fetch_rows(" UNION ".join(
            f"SELECT DISTINCT UPPER(lgd_block) b FROM {v} WHERE lgd_block IS NOT NULL"
            for v in sorted({s.count_view for s in SPECS.values()})))
        _ALL_BLOCKS = {r["b"] for r in rows} | await _fp_raw_blocks()
    return _ALL_BLOCKS


def _norm(s: str) -> str:
    return " ".join(str(s).upper().replace("-", " ").split())


def _canon_block(b: str) -> str:
    # "TURA MUNICIPAL BOARD-MUNICIPAL BOARD" (CM Elevate, Focus Plus) and "TURA
    # MUNICIPAL BOARD" (CM Elevate Legacy) are one block spelled two ways
    s = _norm(b)
    for ph in ("MUNICIPAL BOARD", "TOWN COMMITTEE"):
        unit, t, reps = " " + ph, s, 0
        while t.endswith(unit):
            t, reps = t[:-len(unit)], reps + 1
        # s == t + unit * reps; keep only the first of the trailing repeats
        if reps and t.endswith(ph) and (len(t) == len(ph) or not _xs_is_word_char(t[-len(ph) - 1])):
            return t
        if reps >= 2:
            return t + unit
    return s


def _xs_name_chunk(c: str) -> bool:
    """One word of a place name as typed: an ASCII letter, then letters, digits,
    '_', '.', "'", '(', ')' or '-'."""
    return c[:1].isascii() and c[:1].isalpha() and all(_xs_is_word_char(ch) or ch in ".'()-" for ch in c)


def _xs_ends_with_word(c: str, words: tuple) -> bool:
    return any(c.endswith(w) and (len(c) == len(w) or not _xs_is_word_char(c[-len(w) - 1])) for w in words)


def _xs_starts_with_word(c: str, words: tuple) -> bool:
    return any(c.startswith(w) and (len(c) == len(w) or not _xs_is_word_char(c[len(w)])) for w in words)


def _xs_names_a_place(question: str) -> bool:
    """"in / of / for / at", one to five name words, then "block" / "village" /
    "constituency": the question names a place ("… in Baghmara-Municipal Board block")."""
    chunks = question.split()
    low = [c.lower() for c in chunks]
    for i, c in enumerate(low):
        if not _xs_ends_with_word(c, ("in", "of", "for", "at")):
            continue
        for n in range(1, 6):
            if i + n + 1 >= len(chunks) or not _xs_name_chunk(chunks[i + n]):
                break
            if _xs_starts_with_word(low[i + n + 1], ("block", "village", "constituency")):
                return True
    return False


async def refine_block(text: str, resolved: dict) -> None:
    """The resolver reads a block against the named schemes' catalogues, and
    MGNREGA / PMAY-G / CM Elevate Legacy have no urban blocks — so "Baghmara-
    Municipal Board block" snapped to the rural BAGHMARA block and was answered
    with its figures (cross-scheme run 2026-10-13, CROSS-9). When the user's own
    words name a longer block that some scheme records, that block is meant."""
    if not resolved.get("block") or resolved.get("block_list"):
        return
    t = f" {_norm(text)} "
    names = [b for b in await _all_blocks() if f" {_norm(b)} " in t]
    if not names:
        return
    best = max(names, key=lambda b: len(_norm(b)))
    if len(_norm(best)) > len(_norm(resolved["block"])):
        logger.info("cross-scheme block %r -> %r (named in the question)", resolved["block"], best)
        resolved["block"] = best


_AC_NAMES: set[str] | None = None
# case-sensitive, as before: "constituency" / "assembly" / "AC"
_XS_AC_WORD = Matcher(W("constituency", "constituencies", "assembly", "AC", case=True))
_PLACE_KEYS = ("district", "district_list", "block", "block_list", "village_code", "village_code_list",
               "assembly_constituency")


async def refine_constituency(text: str, resolved: dict) -> None:
    """Only MGNREGA carries a constituency catalogue, and the four Shillong
    constituencies have no MGNREGA rows — so "… in East Shillong constituency"
    resolved to nothing and was answered with STATEWIDE figures (cross-scheme run
    2026-10-13). A constituency the geography registry knows, named with the word
    "constituency", is that constituency."""
    global _AC_NAMES
    if any(resolved.get(k) for k in _PLACE_KEYS):
        return
    if not _XS_AC_WORD.search(text or ""):
        return
    if _AC_NAMES is None:
        rows = await db.fetch_rows("SELECT DISTINCT ac_name a FROM curated.dim_geography WHERE ac_name IS NOT NULL")
        _AC_NAMES = {r["a"] for r in rows}
    t = f" {_norm(text)} "
    names = [a for a in _AC_NAMES if f" {_norm(a)} " in t]
    if names:
        best = max(names, key=lambda a: len(_norm(a)))
        logger.info("cross-scheme constituency %r named in %r", best, text)
        resolved["assembly_constituency"] = best.upper()


async def villages_with_records(schemes: list[str], codes: list[int]) -> set[int]:
    """The village codes among `codes` that any of the schemes holds records for."""
    parts = []
    for s in schemes:
        spec = SPECS[s]
        parts.append(f"SELECT DISTINCT village_code FROM {spec.count_view} WHERE {spec.base_where} "
                     f"AND {spec.village_where} AND village_code = ANY($1::bigint[])")
    rows = await db.fetch_rows(" UNION ".join(parts), [[int(c) for c in codes]])
    return {int(r["village_code"]) for r in rows}


async def _block_variants(blocks: list[str]) -> list[str]:
    allb = await _all_blocks()
    want = {_canon_block(b) for b in blocks}
    return sorted({b.upper() for b in blocks} | {b for b in allb if _canon_block(b) in want})


class _Q:
    def __init__(self):
        self.params: list = []

    def p(self, v) -> str:
        self.params.append(v)
        return f"${len(self.params)}"


async def _where(spec: SchemeSpec, kind: str, resolved: dict, q: _Q) -> str | None:
    """WHERE for one scheme and measure kind ("count" / "money"); None = this
    scheme does not record the place asked for (a constituency)."""
    w = [spec.base_where]
    districts = resolved.get("district_list") or ([resolved["district"]] if resolved.get("district") else [])
    if districts:
        w.append(f"UPPER(lgd_district) = ANY({q.p([str(x).upper() for x in districts])}::text[])")
    blocks = resolved.get("block_list") or ([resolved["block"]] if resolved.get("block") else [])
    if blocks:
        blocks = await _block_variants([str(b) for b in blocks])
        if spec.name == "Focus Plus":
            raw = await _fp_raw_blocks()
            in_raw = [b for b in blocks if b in raw]
            lgd_only = [b for b in blocks if b not in raw]
            parts = []
            if in_raw:
                parts.append(f"UPPER(block_name_raw) = ANY({q.p(in_raw)}::text[])")
            if lgd_only:
                parts.append(f"UPPER(lgd_block) = ANY({q.p(lgd_only)}::text[])")
            w.append("(" + " OR ".join(parts) + ")")
        else:
            w.append(f"UPPER(lgd_block) = ANY({q.p(blocks)}::text[])")
    villages = resolved.get("village_code_list") or ([resolved["village_code"]] if resolved.get("village_code") else [])
    if villages:
        w.append(spec.village_where)
        w.append(f"village_code = ANY({q.p([int(v) for v in villages])}::bigint[])")
    ac = resolved.get("assembly_constituency")
    if ac:
        how = spec.ac_count if kind == "count" else spec.ac_money
        if how == "column":
            w.append(f"UPPER(assembly_constituency_name) = {q.p(str(ac).upper())}")
        elif how == "geo":
            w.append("geography_key IN (SELECT geography_key FROM curated.dim_geography "
                     f"WHERE UPPER(ac_name) = {q.p(str(ac).upper())})")
        else:
            return None
    years = resolved.get("year_key_list") or ([resolved["year_key"]] if resolved.get("year_key") else [])
    if years and spec.has_year:
        w.append(f"year_key = ANY({q.p([int(y) for y in years])}::int[])")
    return " AND ".join(w)


def _group_col(spec: SchemeSpec, group: str) -> str:
    if group == "district":
        return "lgd_district"
    if spec.name == "Focus Plus":
        return "COALESCE(lgd_block, UPPER(block_name_raw))"
    return "lgd_block"


async def _scheme_figures(spec: SchemeSpec, p: Plan, resolved: dict) -> dict:
    """{'count': {group_key: n} | None, 'money': {...} | None, 'extra': {...},
    'reach': {...}, 'no_place': bool, 'no_year': bool}. group_key '' = no grouping."""
    out: dict = {"count": None, "money": None, "extra": {}, "reach": None,
                 "no_place": False, "no_year": False, "sql": []}
    years = resolved.get("year_key_list") or ([resolved["year_key"]] if resolved.get("year_key") else [])
    if years and not spec.has_year:
        out["no_year"] = True
    g = _group_col(spec, p.group) if p.group else None
    sel_g = f"{g} AS k, " if g else "'' AS k, "
    grp = f" AND {g} IS NOT NULL GROUP BY 1" if g else ""

    async def run(sql: str, params: list) -> list[dict]:
        out["sql"].append((sql, list(params)))
        return await db.fetch_rows(sql, params)

    if p.count:
        q = _Q()
        where = await _where(spec, "count", resolved, q)
        if where is None:
            out["no_place"] = True
        else:
            extras = "".join(f", ({e})::float8 AS x{i}" for i, (e, _) in enumerate(spec.extra_count))
            reach = ""
            if p.coverage:
                reach = (", COUNT(DISTINCT lgd_district)::float8 AS r_d, COUNT(DISTINCT lgd_block)::float8 AS r_b, "
                         f"COUNT(DISTINCT village_code) FILTER (WHERE {spec.village_where})::float8 AS r_v")
            rows = await run(f"SELECT {sel_g}COALESCE({spec.count_expr}, 0)::float8 AS n{extras}{reach} "
                             f"FROM {spec.count_view} WHERE {where}{grp}", q.params)
            out["count"] = {r["k"]: r["n"] for r in rows}
            for i, (_, label) in enumerate(spec.extra_count):
                out["extra"][label] = {r["k"]: r[f"x{i}"] for r in rows}
            if p.coverage:
                out["reach"] = {r["k"]: (r["r_d"], r["r_b"], r["r_v"]) for r in rows}
    if p.money and spec.money_view:
        q = _Q()
        where = await _where(spec, "money", resolved, q)
        if where is None:
            out["no_place"] = True
        else:
            rows = await run(f"SELECT {sel_g}COALESCE({spec.money_expr}, 0)::float8 AS a "
                             f"FROM {spec.money_view} WHERE {where}{grp}", q.params)
            out["money"] = {r["k"]: r["a"] for r in rows}
    return out


# ── answer ───────────────────────────────────────────────────────────────────

def _n(v) -> str:
    return f"{int(round(v)):,}"


def _cr(v) -> str:
    """Rupees in the unit that keeps the figure readable: a village's ₹5,000 is
    not "₹0.00 crore"."""
    if abs(v) >= 1e7:
        return f"₹{v / 1e7:,.2f} crore"
    if abs(v) >= 1e5:
        return f"₹{v / 1e5:,.2f} lakh"
    return f"₹{v:,.0f}"


def _table_unit(values) -> tuple[str, float]:
    top = max([abs(v) for v in values if v] or [0.0])
    if top >= 1e7:
        return "₹ crore", 1e7
    if top >= 1e5:
        return "₹ lakh", 1e5
    return "₹", 1.0


def _years_text(scheme_years: dict, s: str) -> str:
    ys = scheme_years.get(s) or []
    if not ys:
        return "no financial year recorded"
    starts = [int(str(y)[:4]) for y in ys]
    if len(ys) > 1 and starts == list(range(starts[0], starts[0] + len(starts))):
        return f"FY {ys[0]} to FY {ys[-1]}"
    return ("FY " + ", ".join(ys[:-1]) + " and " + ys[-1]) if len(ys) > 1 else f"FY {ys[0]}"


def _place_text(display: dict, resolved: dict) -> str:
    for k in ("village", "block", "assembly_constituency", "district"):
        if display.get(k):
            v = str(display[k])
            if k == "block":
                return f"{v.title()} block"
            if k == "assembly_constituency":
                return f"{v.title()} constituency"
            if k == "village":
                return f"{v} village"
            return v
    return "Meghalaya (statewide)"


async def answer(question: str, schemes: list[str], entity_result: dict, scheme_years: dict) -> dict:
    resolved = dict(entity_result.get("resolved") or {})
    display = dict(entity_result.get("display") or {})
    await refine_block(question, resolved)
    if resolved.get("block"):
        display["block"] = resolved["block"]
    await refine_constituency(question, resolved)
    if resolved.get("assembly_constituency"):
        display["assembly_constituency"] = resolved["assembly_constituency"]
    if not resolved.get("year_key") and not resolved.get("year_key_list"):
        ys = years_in_text(question)
        if ys:
            resolved["year_key_list" if len(ys) > 1 else "year_key"] = ys if len(ys) > 1 else ys[0]
            display.pop("year", None)
    p = plan(question, schemes, resolved)
    figs = await asyncio.gather(*[_scheme_figures(SPECS[s], p, resolved) for s in schemes])
    F = dict(zip(schemes, figs))
    years = resolved.get("year_key_list") or ([resolved["year_key"]] if resolved.get("year_key") else [])
    year_txt = display.get("year") or ("FY " + ", ".join(f"{y}-{str(y + 1)[2:]}" for y in years) if years else "")
    place = _place_text(display, resolved)
    title_bits = [place] + ([year_txt] if year_txt else ["all financial years"])
    lines: list[str] = []
    rows: list[dict] = []

    def year_gap(s: str) -> str | None:
        if F[s]["no_year"]:
            return "not recorded by financial year"
        if years and SPECS[s].has_year:
            have = {int(str(x)[:4]) for x in (scheme_years.get(s) or [])}
            if have and not (set(years) & have):
                return f"no data for {year_txt} (data covers {_years_text(scheme_years, s)})"
        return None

    def cell_count(s: str, k: str = "") -> str:
        f = F[s]
        if year_gap(s):
            return "—"
        if f["count"] is None:
            return "not recorded" if f["no_place"] else "—"
        v = f["count"].get(k, 0.0)
        if not v:
            return "no records"
        txt = f"{_n(v)} {SPECS[s].count_label}"
        for label, m in f["extra"].items():
            txt += f" ({_n(m.get(k, 0.0))} {label})"
        return txt

    def cell_money(s: str, k: str = "") -> str:
        f = F[s]
        if not SPECS[s].money_view:
            return "no money recorded"
        if year_gap(s):
            return "—"
        if f["money"] is None:
            return "not recorded"
        v = f["money"].get(k, 0.0)
        return f"{_cr(v)} ({SPECS[s].money_label})" if v else "no records"

    if not any(resolved.get(k) for k in _PLACE_KEYS) and \
            _xs_names_a_place(question or ""):
        # never present statewide figures as if they were the named place's
        lines.append("_The place named in the question was not recognised, so the figures below "
                     "are statewide._\n")
    if p.group is None:
        lines.append(f"**Cross-scheme comparison — {', '.join(title_bits)}**\n")
        hdr = ["Scheme"]
        if p.count:
            hdr.append("Beneficiaries / applications")
        if p.coverage:
            hdr += ["Districts", "Blocks", "Villages"]
        if p.money:
            hdr.append("Amount")
        lines.append("| " + " | ".join(hdr) + " |")
        lines.append("|" + "---|" * len(hdr))
        for s in schemes:
            gap = year_gap(s)
            cells = [f"**{DISPLAY[s]}**"]
            row = {"scheme": s}
            if p.count:
                cells.append(gap or cell_count(s))
                row["count"] = (F[s]["count"] or {}).get("", None) if not gap else None
                row["count_measure"] = SPECS[s].count_label
                for label, m in F[s]["extra"].items():
                    row[label.replace(" ", "_")] = m.get("")
            if p.coverage:
                r = (F[s]["reach"] or {}).get("") if not gap else None
                cells += [_n(x) if r else "—" for x in (r or (0, 0, 0))]
                if r:
                    row.update(districts=r[0], blocks=r[1], villages=r[2])
            if p.money:
                cells.append(cell_money(s) if not gap or not SPECS[s].money_view else gap)
                row["amount_rupees"] = (F[s]["money"] or {}).get("") if F[s]["money"] is not None and not gap else None
                row["money_measure"] = SPECS[s].money_label
            lines.append("| " + " | ".join(cells) + " |")
            rows.append(row)
        # ranking sentences
        if p.rank or p.coverage:
            if p.coverage:
                rc = [(s, (F[s]["reach"] or {}).get("")) for s in schemes if (F[s]["reach"] or {}).get("")]
                rc.sort(key=lambda t: (t[1][0], t[1][2]), reverse=True)
                if rc:
                    top = rc[0]
                    lines.append(f"\n**Widest coverage:** {DISPLAY[top[0]]} — {_n(top[1][0])} districts, "
                                 f"{_n(top[1][1])} blocks and {_n(top[1][2])} villages.")
            if p.money:
                mc = [(s, (F[s]["money"] or {}).get("", 0.0)) for s in schemes
                      if F[s]["money"] is not None and not year_gap(s)]
                mc = [t for t in mc if t[1]]
                mc.sort(key=lambda t: t[1], reverse=True)
                if mc:
                    lines.append(f"\n**Highest amount:** {DISPLAY[mc[0][0]]} at {_cr(mc[0][1])}"
                                 + (f", then " + ", ".join(f"{DISPLAY[s]} {_cr(v)}" for s, v in mc[1:]) if len(mc) > 1 else "")
                                 + ".")
            if p.count and not p.coverage:
                cc = [(s, (F[s]["count"] or {}).get("", 0.0)) for s in schemes
                      if F[s]["count"] is not None and not year_gap(s)]
                cc = [t for t in cc if t[1]]
                cc.sort(key=lambda t: t[1], reverse=True)
                if cc:
                    lines.append(f"\n**Highest count:** {DISPLAY[cc[0][0]]} with {_n(cc[0][1])} "
                                 f"{SPECS[cc[0][0]].count_label}.")
    else:
        unit = "district" if p.group == "district" else "block"
        keys: set = set()
        for s in schemes:
            for part in ("count", "money"):
                keys |= set((F[s][part] or {}).keys())
        if resolved.get("district_list") and p.group == "district":
            keys = {str(x).upper() for x in resolved["district_list"]}
        keys = sorted(k for k in keys if k)
        lines.append(f"**Cross-scheme comparison by {unit} — {', '.join(title_bits)}**\n")
        measures = ([("count", "Beneficiaries / applications")] if p.count else []) + \
                   ([("money", "Amount")] if p.money else [])
        for part, heading in measures:
            cols = [s for s in schemes if not (part == "money" and not SPECS[s].money_view)]
            div = 1.0
            if part == "money":
                unit_txt, div = _table_unit([v for s in cols for v in (F[s]["money"] or {}).values()
                                             if not year_gap(s)])
                heading = f"Amount ({unit_txt})"
            lines.append(f"\n**{heading}**\n")
            hdr = [unit.title()] + [DISPLAY[s] for s in cols]
            if p.leader_per_group and part == "count":
                hdr.append("Leading scheme")
            lines.append("| " + " | ".join(hdr) + " |")
            lines.append("|" + "---|" * len(hdr))
            for k in keys:
                cells = [k.title()]
                best = None
                for s in cols:
                    gap = year_gap(s)
                    m = F[s][part]
                    if gap or m is None:
                        cells.append("—")
                        continue
                    v = m.get(k, 0.0)
                    cells.append(_n(v) if part == "count" else
                                 (f"{v / div:,.2f}" if div > 1 else f"{v:,.0f}"))
                    if v and (best is None or v > best[1]):
                        best = (s, v)
                if p.leader_per_group and part == "count":
                    cells.append(DISPLAY[best[0]] if best else "—")
                lines.append("| " + " | ".join(cells) + " |")
            if part == "count":
                lines.append("\nCounted as: " + "; ".join(f"{DISPLAY[s]} = {SPECS[s].count_label}" for s in cols) + ".")
            else:
                lines.append("\nAmounts: " + "; ".join(f"{DISPLAY[s]} = {SPECS[s].money_label}" for s in cols) + ".")
            for k in keys:
                for s in cols:
                    m = F[s][part]
                    if m is not None and not year_gap(s):
                        rows.append({unit: k, "scheme": s, part: m.get(k, 0.0)})
        if p.top_districts and p.count:
            tops = []
            for s in schemes:
                m = F[s]["count"]
                if m and not year_gap(s):
                    k, v = max(m.items(), key=lambda t: t[1])
                    tops.append(f"{DISPLAY[s]}: **{k.title()}** ({_n(v)} {SPECS[s].count_label})")
            if tops:
                lines.append(f"\n**Highest {unit} per scheme:** " + "; ".join(tops) + ".")
        if p.top_districts and p.money and not p.count:
            tops = []
            for s in schemes:
                m = F[s]["money"]
                if m and not year_gap(s):
                    k, v = max(m.items(), key=lambda t: t[1])
                    tops.append(f"{DISPLAY[s]}: **{k.title()}** ({_cr(v)})")
            if tops:
                lines.append(f"\n**Highest {unit} per scheme:** " + "; ".join(tops) + ".")
        if p.leader_per_group:
            lines.append("\nThe leading scheme is the one with the largest raw count in that "
                         f"{unit}; the schemes count different things, so read it as indicative.")

    # notes
    notes = []
    for s in schemes:
        gap = year_gap(s)
        if gap:
            notes.append(f"{DISPLAY[s]}: {gap}.")
        if F[s]["no_place"]:
            notes.append(f"{DISPLAY[s]}: its data is not recorded by assembly constituency.")
    if p.money and "MGNREGA" in schemes and resolved.get("assembly_constituency"):
        pass
    if not years:
        notes.append("Years covered: " + "; ".join(
            f"{DISPLAY[s]} {_years_text(scheme_years, s)}" for s in schemes if SPECS[s].has_year)
            + ("; CM Elevate (applications) has no financial year" if "CM Elevate" in schemes else "") + ".")
    if p.count and "MGNREGA" in schemes:
        notes.append("MGNREGA persons employed are summed over the years shown; a person employed in "
                     "two years is counted in each.")
    if p.money and "CM Elevate" in schemes:
        notes.append("CM Elevate (applications) records no payment of any kind, so it has no amount.")
    if len([s for s in schemes if SPECS[s].money_view]) > 1 and p.money:
        notes.append("Amounts are different kinds of money (expenditure, releases, disbursements) and are "
                     "not added together.")
    if p.count and len(schemes) > 1:
        notes.append("Each scheme counts a different thing, so compare the counts as indicative, "
                     "not like-for-like.")
    if notes:
        lines.append("\n" + "\n".join(f"- {n}" for n in notes))
    pairs = [x for s in schemes for x in F[s]["sql"]]
    sql = "\n;\n".join(x for x, _ in pairs)
    return {
        "route": "data", "intent": "DATA", "confidence": "high",
        "schemes": schemes, "resolved_entities": resolved,
        "sql": sql, "sql_query": sql, "row_count": len(rows), "rows": rows, "data": rows,
        "answer": "\n".join(lines), "cross_scheme": True, "sql_pairs": pairs,
    }
