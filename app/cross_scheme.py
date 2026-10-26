"""
Cross-scheme questions: recognising them and settling their places.

"Compare Focus+, FOCUS and CM-ELEVATE in East Khasi Hills", "which scheme has the
highest beneficiary count in each district?", "top ten villages in MGNREGA and
PMAY-G" (Cross Scheme Test Cases sheet, 2026-10-13; user report 2026-10-22).

`detect` says a question compares schemes. The answer itself is NOT built here:
since D-062 (2026-10-22) each scheme gets its own SQL from the model (its own
prompt, few-shots, guards, verifier and repairs: c13 `_per_scheme_generate` /
`_data_per_scheme_rows`) and the composer writes one answer from the rows, each
row tagged with its scheme. Until then this module answered from a fixed table
template (D-044), which could only show per-scheme totals, per district or per
block: "top ten highest villages in Mgnrega and pmay" got the statewide totals
card, the same card as "compare MGNREGA and PMAY-G spending" (user report
2026-10-22).

What stays here is what the template's place handling learnt: a block some other
scheme spells longer (`refine_block`), a constituency only the registry knows
(`refine_constituency`), "FY2022-23" written without a space (`years_in_text`)
and twin villages that both hold records (`villages_with_records`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app import db
from app.text_match import Alt, Matcher, Node, Opt, Seq, W, fy_spans

logger = logging.getLogger(__name__)

ORDER = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CM Elevate Legacy"]


@dataclass(frozen=True)
class SchemeSpec:
    """Where a scheme's village-level records live (`villages_with_records`)."""
    name: str
    count_view: str
    base_where: str = "TRUE"
    village_where: str = "village_code IS NOT NULL"


SPECS: dict[str, SchemeSpec] = {
    "MGNREGA": SchemeSpec("MGNREGA", "curated.v_employment"),
    "PMAY-G": SchemeSpec("PMAY-G", "curated.v_pmay", base_where="NOT is_placeholder"),
    "Focus Plus": SchemeSpec("Focus Plus", "curated.v_focus_plus", village_where="village_code > 0"),
    "Focus Legacy": SchemeSpec(
        "Focus Legacy", "curated.v_focus_legacy",
        village_where="village_code > 0 AND entity_type <> 'Unresolved'"),
    "CM Elevate": SchemeSpec(
        "CM Elevate", "curated.v_cm_elevate",
        village_where="village_code IS NOT NULL AND entity_type <> 'Unresolved'"),
    "CM Elevate Legacy": SchemeSpec(
        "CM Elevate Legacy", "curated.v_cm_elevate_disbursement",
        village_where="village_code > 0 AND entity_type <> 'Unresolved'"),
}

# ── detection ────────────────────────────────────────────────────────────────

def _xs_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def S(*parts) -> Seq:
    """Words in a row with only whitespace (one or more spaces) between them."""
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
# "compare …", "summary …", "performance", "district-wise": a comparison is asked
_XS_COMPARISON = Matcher(Alt(W("compar", "summar", prefix=True), W("performance", "wise")))
_SAME_COMPARISON = Matcher(S("same", W("comparison", "comparisons")))
# "all / other / six / each …": the question reaches past the one scheme it names
_XS_BEYOND_ONE = Matcher(W("all", "other", "six", "6", "every", "each", "different", "various"))


def bare_focus_is_legacy(question: str, named: list[str]) -> bool:
    return "Focus Plus" in named and "Focus Legacy" not in named and bool(_BARE_FOCUS.search(question or ""))


def other_measure(text: str) -> bool:
    return bool(_OTHER_MEASURE.search(text or ""))


def asks_money_only(question: str) -> bool:
    """The question asks for money and for no count or coverage ("which scheme
    spent the most?"), so a scheme with no money (CM Elevate) has nothing to give."""
    q = question or ""
    return bool(_MONEY.search(q)) and not (_COUNT.search(q) or _COVERAGE.search(q))


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
    # "Same comparison for CM Elevate: beneficiaries ..." — the follow-up rewrite of
    # "now give me for cm elevate" after a comparison (c01 _comparison_swap): the
    # same card for that one scheme, in the comparison's scope
    if len(named) == 1 and _SAME_COMPARISON.search(q):
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


# ── places ───────────────────────────────────────────────────────────────────

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


def _xs_name_chunk(c: str) -> bool:
    """One word of a place name as typed: an ASCII letter, then letters, digits,
    '_', '.', "'", '(', ')' or '-'."""
    return c[:1].isascii() and c[:1].isalpha() and all(_xs_is_word_char(ch) or ch in ".'()-" for ch in c)


def _xs_ends_with_word(c: str, words: tuple) -> bool:
    return any(c.endswith(w) and (len(c) == len(w) or not _xs_is_word_char(c[-len(w) - 1])) for w in words)


def _xs_starts_with_word(c: str, words: tuple) -> bool:
    return any(c.startswith(w) and (len(c) == len(w) or not _xs_is_word_char(c[len(w)])) for w in words)


def names_a_place(question: str) -> bool:
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
PLACE_KEYS = ("district", "district_list", "block", "block_list", "village_code", "village_code_list",
               "assembly_constituency")


async def refine_constituency(text: str, resolved: dict) -> None:
    """Only MGNREGA carries a constituency catalogue, and the four Shillong
    constituencies have no MGNREGA rows — so "… in East Shillong constituency"
    resolved to nothing and was answered with STATEWIDE figures (cross-scheme run
    2026-10-13). A constituency the geography registry knows, named with the word
    "constituency", is that constituency."""
    global _AC_NAMES
    if any(resolved.get(k) for k in PLACE_KEYS):
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
