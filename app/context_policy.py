"""
Field-level rules for carrying conversation state into a follow-up.

context_manager decides WHAT the previous turn was about (structured state,
evidence tiers). This module decides, field by field, what a follow-up does
to that state, and checks what a model rewrite is allowed to add. Everything
here is deterministic: no model call, no DB round trip.

    plan_state_merge(question, state, prev)  -> MergePlan
        per field: KEEP | REPLACE | CLEAR | REQUIRE_CLARIFICATION, plus the
        follow-up KIND (METRIC_CHANGE, RESULT_REFERENCE, ...), which picks the
        context layers the rewrite gets (context_layers()).
    apply_merge_plan(prior_resolved, plan)   -> what resolve_entities may inherit
    record_provenance(state, ...)            -> where each committed value came from
    rewrite_violation(rewritten, ...)        -> the field a rewrite added with no source

Why per-field and not one rule: fields differ in whether they can be inherited
at all, whether a coarser change invalidates them, whether they can be
validated offline, and whether a changed value is the user's intent or a
contamination. FIELD_POLICIES records that per field (docs/AI_PIPELINE.md
§5.4 has the same table). The policy is keyed by FIELD, never by scheme:
adding a scheme to SCHEME_CATALOG / _SCHEME_NAME_MATCHER needs nothing here.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.text_match import (Alt, Cap, Gap, Joined, Matcher, Node, Opt, Pred, Seq, W,
                            is_int, tokens)

KEEP = "KEEP"
REPLACE = "REPLACE"
CLEAR = "CLEAR"
REQUIRE_CLARIFICATION = "REQUIRE_CLARIFICATION"

# Where a committed state value came from. Only model_inference is refused as an
# inheritance source (see merged_prior_resolved): a value no user turn, pause
# reply, resolved reference or validated lookup supplied is not carried forward.
PROVENANCE_SOURCES = ("current_user", "previous_user", "clarification_response",
                      "validated_database", "resolved_reference", "model_inference")
_CONFIDENCE = {"current_user": 1.0, "clarification_response": 1.0, "previous_user": 1.0,
               "resolved_reference": 0.9, "validated_database": 0.9, "model_inference": 0.5}

# Follow-up kinds, and the previous-turn context layers each one needs.
NEW_QUERY = "NEW_QUERY"
FILTER_CHANGE = "FILTER_CHANGE"
METRIC_CHANGE = "METRIC_CHANGE"
TIME_CHANGE = "TIME_CHANGE"
GEOGRAPHY_CHANGE = "GEOGRAPHY_CHANGE"
GROUP_BY_CHANGE = "GROUP_BY_CHANGE"
COMPARISON = "COMPARISON"
RESULT_REFERENCE = "RESULT_REFERENCE"
CLARIFICATION_RESPONSE = "CLARIFICATION_RESPONSE"
# "same for <another scheme>": the previous operation, with only the scheme
# swapped (pipeline._scheme_substitution). Its layers are the previous filters,
# so geography, year and grouping carry over, and the scheme's own values
# (tranche, sub-scheme) are still inherited only within their own scheme.
SCHEME_SUBSTITUTION = "SCHEME_SUBSTITUTION"

# Layer names match context_manager.build_rewrite_evidence's tiers. "filters" is
# the previous turn's structured scope; "result" its row summary (with the
# answer excerpt as the no-rows fallback). The conversation summary and older
# turns are added only on an explicit back-reference, for every kind
# (context_manager.references_history).
_LAYERS = {
    NEW_QUERY: (),
    RESULT_REFERENCE: ("filters", "result"),
}
_DEFAULT_LAYERS = ("filters",)


def context_layers(kind: str | None) -> tuple[str, ...]:
    """The previous-turn layers a follow-up of this kind is given."""
    return _LAYERS.get(kind or "", _DEFAULT_LAYERS)


@dataclass(frozen=True)
class FieldPolicy:
    """How one state field behaves across turns (see module docstring)."""
    name: str
    inheritable: bool            # can a follow-up that doesn't mention it inherit it?
    replaceable: bool            # can the current question change it?
    clearable: bool              # can the current question remove it ("all years")?
    clarify_when: str            # when the pipeline asks instead of guessing
    validation: str              # how a value is checked against project data
    resolved_keys: tuple[str, ...] = ()      # its keys in resolve_entities' `resolved`
    clears_on_replace: tuple[str, ...] = ()  # finer fields a new value invalidates


FIELD_POLICIES: dict[str, FieldPolicy] = {p.name: p for p in (
    FieldPolicy("scheme", True, True, False,
                "no scheme named and no scheme vocabulary (scheme-not-specified); a bare "
                "'Focus' (focus-scheme-ambiguous)",
                "scheme registry (_SCHEME_NAME_MATCHER / SCHEME_CATALOG)"),
    FieldPolicy("district", True, True, True,
                "a hill-range name covering several districts (region-needs-district)",
                "resolver catalogue (12 districts, acronyms)",
                ("district", "district_list", "district_list_region"), ("block", "village")),
    FieldPolicy("block", True, True, True,
                "a name that is also a village or constituency (level collision)",
                "resolver catalogue (all schemes' block lists)",
                ("block", "block_list", "block_list_districts"), ("village",)),
    FieldPolicy("village", True, True, True,
                "several villages share the name (entity-ambiguous)",
                "database (resolve_village / dim_geography); not checkable offline",
                ("village_code", "village_code_list")),
    FieldPolicy("year", True, True, True,
                "a relative year ('last year') with no known year; a scheme that needs "
                "a year and none is given (year-not-specified)",
                "per-scheme FY coverage (_SCHEME_DATA_YEARS, year-gap handling)",
                ("year_key",)),
    # financial_year is the display form of the same field ("FY 2024-25" <->
    # year_key 2024). One policy, so the two can never disagree.
    FieldPolicy("financial_year", True, True, True, "as year", "as year", ("year_key",)),
    FieldPolicy("category", True, True, True,
                "a sub-scheme family name covering several sub-schemes (CM Elevate group "
                "ambiguity); tranche not stated for Focus Plus",
                "catalogue (tranche_label, cm_scheme) + closed demographic vocabulary",
                ("tranche_label", "cm_scheme", "house_status")),
    FieldPolicy("metric", True, True, False,
                "never asked: an unknown metric is answered as 'not tracked'",
                "metric vocabulary (context_manager._METRIC_KEYWORDS)"),
    FieldPolicy("group_by", False, True, True,
                "never asked", "dimension vocabulary"),
)}


# ── Deterministic signals ───────────────────────────────────────────────────
# Word-level matchers (app/text_match.py, D-047). The _cp_* helpers
# below are shared with context_manager / conversation_layer /
# conversation_replies / topic_memory / followups for the few spots a word
# matcher must look at the characters between words.

def _cp_has(*subs: str) -> Pred:
    """One word containing any of `subs` anywhere inside it."""
    subs = tuple(s.lower() for s in subs)
    return Pred(lambda w: any(s in w.lower() for s in subs))


def _cp_ends(*subs: str) -> Pred:
    subs = tuple(s.lower() for s in subs)
    return Pred(lambda w: w.lower().endswith(subs))


def _cp_starts(*subs: str) -> Pred:
    subs = tuple(s.lower() for s in subs)
    return Pred(lambda w: w.lower().startswith(subs))


class _CpSep(Node):
    """Zero-width: the characters between the previous word and this one
    satisfy ok(gap)."""

    def __init__(self, ok):
        self.ok = ok

    def ends(self, ctx, i, caps):
        if 0 < i < len(ctx.toks) and self.ok(ctx.gap(i)):
            yield i, caps


class _CpStart(Node):
    """START, and the characters before the first word satisfy ok()."""

    def __init__(self, ok):
        self.ok = ok

    def ends(self, ctx, i, caps):
        if i == 0 and self.ok(ctx.text[:ctx.toks[0].start] if ctx.toks else ctx.text):
            yield i, caps


class _CpEnd(Node):
    """END, and the characters after the last word satisfy ok()."""

    def __init__(self, ok):
        self.ok = ok

    def ends(self, ctx, i, caps):
        if i == len(ctx.toks) and self.ok(ctx.text[ctx.toks[-1].end:] if ctx.toks else ctx.text):
            yield i, caps


class _CpNextChar(Node):
    """Zero-width, after a word: the text ends there or the next character
    satisfies ok(ch) (it looks ahead without consuming anything)."""

    def __init__(self, ok):
        self.ok = ok

    def ends(self, ctx, i, caps):
        if i == 0:
            return
        pos = ctx.toks[i - 1].end
        if pos >= len(ctx.text) or self.ok(ctx.text[pos]):
            yield i, caps


def _cp_ws(s: str) -> bool:
    """Only whitespace, possibly none."""
    return s.strip() == ""


def _cp_end_punct(s: str) -> bool:
    """Optional spaces, any run of '?' '.' '!', optional spaces, then the end."""
    return all(c in "?.!" for c in s.strip())


def _cp_gap_opt1(g: str) -> bool:
    """Nothing, or one whitespace character or '-', between two words that touch it."""
    return g == "-" or (len(g) == 1 and g.isspace())


def _cp_glued(a: str, b: str, gap=_cp_gap_opt1) -> Node:
    """`a<gap>b` anywhere in the text: one word containing a+b, or a word
    ending in `a`, a separator gap() accepts, and a word starting with `b`."""
    return Alt(_cp_has(a + b), Seq(_cp_ends(a), _CpSep(gap), _cp_starts(b)))


def _cp_has_term(low: str, term: str) -> bool:
    """`term` in `low` with no ASCII letter on either side (`low` is
    lower-cased text)."""
    if not term:
        return False
    start = low.find(term)
    while start != -1:
        end = start + len(term)
        before = low[start - 1] if start > 0 else ""
        after = low[end] if end < len(low) else ""
        if not (before and "a" <= before <= "z") and not (after and "a" <= after <= "z"):
            return True
        start = low.find(term, start + 1)
    return False


def _cp_y20(w: str) -> bool:
    return len(w) == 4 and w.startswith("20") and is_int(w)


# "2024" or "FY2024" (one word): the year is the word's last four characters.
_CP_FY_YEAR = Pred(lambda w: _cp_y20(w) or (w[:2].lower() == "fy" and _cp_y20(w[2:])))
_CP_YEAR_TAIL = Pred(lambda w: is_int(w) and (len(w) == 2 or _cp_y20(w)))

# "FY 2024-25", "2024/25", "2024 – 2025"; group(1) ends with the start year.
_YEAR_RANGE_MATCH = Matcher(Seq(Opt("fy"), Seq(Cap(_CP_FY_YEAR), _CP_YEAR_TAIL, sep="dash")))
_YEAR_BARE_MATCH = Matcher(Seq(Opt("fy"), Cap(_CP_FY_YEAR)))
_RELATIVE_YEAR_MATCH = Matcher(Alt(
    Seq(W("last", "previous", "prior", "next", "following", "preceding", "same", "this", "current"),
        Opt(W("financial", "fiscal")), W("year", "fy")),
    Seq("year", W("before", "after"))))
_ALL_YEARS_MATCH = Matcher(Alt(
    Seq("all", Opt("the"), Opt("financial"), "years"), "every year", Seq("across", Opt("all"), "years"),
    Joined("year", "wise"), "by year", "per year", "each year", "cumulative", Joined("all", "time")))
# ── The grouping reader (D-110, 2026-11-15): ONE for the whole app ───────────
# A breakdown the question asks for: "in each block", "block-wise", "per district", "by financial year", "district by
# district", "across all districts", "every block". grouping_dims() returns the dimensions (singular, lower case).
# Until D-110 two readers disagreed: c02's (_c02_breakdowns, which the catalogue, the SQL guard and every follow-up
# rule read) took "across all districts" as no grouping, asked_levels below took it as a district grouping; after
# "Show PMAY-G houses completed across all districts" a regroup kept the old words ("... across all districts by
# block") and "which is lowest" found no level. Both now read this one matcher; asked_levels adds only what is not a
# grouping (a ranking over a level, the statewide scope words).
GROUPING_DIM = W("district", "districts", "block", "blocks", "village", "villages", "panchayat", "panchayats",
                 "gp", "gps", "year", "years", "fy", "scheme", "schemes", "programme", "programmes", "program",
                 "programs", "tranche", "tranches", "batch", "batches", "month", "months", "lender", "lenders",
                 "bank", "banks", "product", "products", "category", "categories", "gender", "status", "type",
                 "types", "constituency", "constituencies")
GROUPING_DIM_WORDS = frozenset(w.rstrip("s") for w in (
    "district block village panchayat gp year fy scheme programme program tranche batch month lender "
    "bank product category categorie gender status type constituency constituencie").split())
# "all districts" / "every block" are groupings only for PLACE levels: "across all financial years" is the all-years
# scope the pipeline itself writes, "all schemes" a cross-scheme question.
_GROUPING_PLACE_PLURAL = W("districts", "blocks", "villages", "panchayats", "gps", "constituencies")
_GROUPING_PLACE_ONE = W("district", "block", "village", "panchayat", "gp", "constituency")
_GROUPING_TOTAL_WORDS = frozenset("total totals combined altogether overall sum aggregate cumulative together".split())
GROUPING_MATCH = Matcher(Alt(
    Seq(W("each"), Opt(W("financial", "fiscal", "calendar", "individual", "single")), Cap(GROUPING_DIM, "dim")),
    Seq(Cap(GROUPING_DIM, "dim"), "wise"),
    Pred(lambda w: w.lower().endswith("wise") and w.lower()[:-4].rstrip("s") in GROUPING_DIM_WORDS),
    Seq(W("by", "across"), Opt("the"), Opt(W("financial", "fiscal")), Cap(GROUPING_DIM, "dim")),
    Seq(Cap(GROUPING_DIM, "dim"), "by", GROUPING_DIM),
    Seq("all", Opt("the"), Cap(_GROUPING_PLACE_PLURAL, "dim")),
    Seq("every", Cap(_GROUPING_PLACE_ONE, "dim")),
))
# "per district" / "every year" are breakdowns too, but also "average per district" (one value) and "counting every
# financial year" (all years together), so they count only with include_per (the rephrase check, not the SQL guard).
GROUPING_PER_MATCH = Matcher(Seq(W("per", "every"), Opt(W("financial", "fiscal", "calendar")),
                                 Cap(GROUPING_DIM, "dim")))
_GROUPING_CANON = {"programme": "scheme", "program": "scheme", "fy": "year", "categorie": "category",
                   "constituencie": "constituency"}


def grouping_dims(text: str, include_per: bool = True) -> "set[str]":
    """The dimensions `text` breaks down by ("district", "block", "year", "scheme", ...). include_per=False leaves
    out "per <dim>" / "every <dim>" (except "every <place>"), which may also be one value."""
    out = set()
    hits = list(GROUPING_MATCH.finditer(text or ""))
    if include_per:
        hits += list(GROUPING_PER_MATCH.finditer(text or ""))
    # review 2026-11-15: "all / every <place>" with a TOTAL word is the sum over those places, one figure ("total PMAY-G
    # houses completed in all districts combined", "total job cards issued in every district"); it had become a
    # district list, and the SQL guard rejected the right one-row total
    totalled = bool(_GROUPING_TOTAL_WORDS & {w.lower() for w in (text or "").replace("-", " ").split()})
    for hit in hits:
        if totalled and hit.group(0).lower().split()[0] in ("all", "every"):
            continue
        word = (hit.group("dim") or hit.group(0)).lower()
        if word.endswith("wise"):
            word = word[:-4]
        word = word.rstrip("s") or word
        out.add(_GROUPING_CANON.get(word, word))
    return out


_ALL_GEO_MATCH = {
    "district": Matcher(Alt(
        Seq("all", Opt("the"), "districts"), "every district", Joined("district", "wise"),
        Seq(W("by", "per", "each"), "district"), Joined("state", "wide"), "all of meghalaya",
        Seq(W("whole", "entire"), W("state", "meghalaya")), Seq("across", Opt("the"), "state"))),
    "block": Matcher(Alt(
        Seq("all", Opt("the"), "blocks"), "every block", Joined("block", "wise"),
        Seq(W("by", "per", "each"), "block"))),
    "village": Matcher(Alt(
        Seq("all", Opt("the"), "villages"), "every village", Joined("village", "wise"),
        Seq(W("by", "per", "each"), "village"))),
}
# A question that RANKS a level ("which block has the highest number of
# households?", "top 5 villages", "blocks with the lowest expenditure") asks
# across every place at that level, so the chat's own place at that level is
# dropped (the coarser one is kept: D-056 "by block keeps the district").
# Reported 2026-10-22: after a Demdema block answer, "Which block has highest
# number of households?" kept block DEMDEMA and answered Demdema's single row.
_CP_SUPERLATIVE = W("highest", "lowest", "most", "least", "maximum", "minimum", "max", "min", "largest",
                    "smallest", "biggest", "best", "worst", "top", "bottom", "greatest", "fewest")
_RANK_OVER_GEO_MATCH = {
    dim: Matcher(Alt(
        Seq(W("which", "what"), W(dim, dim + "s"), Gap(8), _CP_SUPERLATIVE),
        Seq(W("top", "bottom"), Opt(Pred(str.isdigit)), W(dim, dim + "s")),
        Seq(W(dim, dim + "s"), W("with", "having", "that", "where"), Gap(4), _CP_SUPERLATIVE),
        Seq(W("rank", "ranking", "ranked"), Opt("the"), W(dim + "s")),
        Seq(_CP_SUPERLATIVE, W(dim, dim + "s")),
        Seq(_CP_SUPERLATIVE, Gap(6), W("in", "of", "for", "by"), W("which", "what"), W(dim, dim + "s"))))
    for dim in ("district", "block", "village")
}
_CP_BY_DIMS = ("district", "block", "village", "year", "tranche", "scheme", "gender", "category",
               "month", "status")
_GROUP_BY_MATCH = Matcher(Alt(
    Seq(W("by", "per", "each", "across"), Opt("the"),
        Alt(W(*_CP_BY_DIMS, *(d + "s" for d in _CP_BY_DIMS)), Joined("sub", ("scheme", "schemes")))),
    Joined(_CP_BY_DIMS, "wise"),
    Seq("break", Opt(W("it", "that", "this", "them")), "down"), W("breakdown", "split")))
_COMPARE_MATCH = Matcher(W("compare", "comparison", "versus", "vs", "between"))
_ALL_CATEGORY_MATCH = Matcher(Alt(
    Seq("all", Opt("the"), Alt(W("categories", "tranches", "genders"), Joined("sub", "schemes"))),
    "everyone", "all beneficiaries", "regardless of"))
_DEMOGRAPHIC_MATCH = Matcher(Cap(Alt(
    W("women", "woman", "female", "females", "men", "male", "males", "gender", "girl", "girls", "boy",
      "boys", "farmer", "farmers", "widow", "widows", "youth", "disabled", "pwd", "divyang", "minority",
      "minorities", "bpl", "sc", "st", "obc", "pvtg"),
    Seq("scheduled", W("caste", "castes", "tribe", "tribes")), "general category")))


def _cp_tranche_numbers(text: str) -> list[str]:
    """The digit of every "tranche 2" / "tranche-2" / "tranch #3" / "tranche2"
    ("tranch"/"tranche" at a word start, optional spaces, an optional '-' or '#',
    optional spaces, then one digit ending the word)."""
    toks = tokens(text)
    t = text or ""
    out = []
    for k, tok in enumerate(toks):
        if tok.low in ("tranche", "tranch"):
            if k + 1 < len(toks):
                nxt = toks[k + 1]
                if (t[tok.end:nxt.start].strip() in ("", "-", "#") and len(nxt.raw) == 1
                        and is_int(nxt.raw)):
                    out.append(nxt.raw)
            continue
        for stem in ("tranche", "tranch"):
            rest = tok.low[len(stem):]
            if tok.low.startswith(stem) and len(rest) == 1 and is_int(rest):
                out.append(rest)
                break
    return out


# The tranche cue as a word matcher ("tranche 2", "tranche2"); the digits
# themselves come from _cp_tranche_numbers.
_TRANCHE_MATCH = Matcher(Alt(
    Seq(W("tranche", "tranch"), Pred(lambda w: len(w) == 1 and is_int(w))),
    Pred(lambda w: any(w.lower().startswith(s) and len(w) == len(s) + 1 and is_int(w[-1])
                       for s in ("tranche", "tranch")))))
# "all of them combined", "in total", "both together": every value of the
# dimension the conversation was just varying, not a filter on the last one.
_ALL_OF_THEM_MATCH = Matcher(Alt(
    Seq("all", Opt("of"), W("them", "these", "those", "three", "two", "four")),
    W("both", "together", "combined", "altogether", "overall"), "in total"))
_AMBIGUOUS_REF_MATCH = Matcher(Alt(Seq(Opt("the"), "other", "one"), "the former", "the latter"))

# Metric FAMILIES for the rewrite check. Finer than "is there a metric", coarser
# than the labels context_manager tracks, so that a paraphrase ("how much" ->
# "amount disbursed") is the same family and only a genuinely new measure
# (money -> beneficiary count) is a change.
_METRIC_FAMILIES: dict[str, Matcher] = {
    "money": Matcher(Alt(
        "how much", W("amount", "spend", "spent", "cost", "lakh", "crore", prefix=True),
        _cp_has("disburs", "expenditure", "releas", "rupee"),
        W("paid", "payment", "payments", "fund", "funds", "wage", "wages", "rs"))),
    "count": Matcher(Alt(
        "how many", "number of", W("count", "houses", "pg", "pgs"),
        _cp_has("beneficiar", "applica", "household", "registration", "members", "farmers", "groups"),
        _cp_glued("job", "card", gap=_cp_ws))),
    "days": Matcher(Alt(*(_cp_glued(a, "day") for a in ("person", "man", "work", "100")))),
    "completion": Matcher(_cp_has("complet")),
}

# Words a rewrite may capitalise without them being names (sentence starts,
# units, the state itself). Kept small on purpose; the name check only fires
# for a capitalised word that ALSO appears in text the rewrite was not allowed
# to draw from.
_NAME_STOPWORDS = {
    "what", "how", "which", "who", "when", "where", "show", "list", "give", "tell", "total",
    "the", "for", "under", "in", "and", "of", "was", "were", "is", "are", "did", "does",
    "fy", "financial", "year", "years", "meghalaya", "district", "districts", "block",
    "blocks", "village", "villages", "scheme", "schemes", "tranche", "tranch", "amount",
    "number", "all", "each", "by", "compare", "between", "during", "from", "to", "with",
    "rs", "inr", "lakh", "crore", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
}
# A capitalised ASCII word of 3+ letters, a whole word (case-sensitive).
_CAP_WORD_MATCH = Matcher(Pred(lambda w: len(w) >= 3 and w.isascii() and w.isalpha() and w[0].isupper()))


def extract_year_keys(text: str) -> set[int]:
    """Financial-year start years named in the text: "FY 2024-25", "2024-25",
    "2024/25" -> 2024; a bare "2024" -> 2024; the short forms of
    short_fy_tokens ("FY 25" -> 2024, "FY 23-24" / "in 23-24" -> 2023)."""
    t = text or ""
    years = {int(m.group(1)[-4:]) for m in _YEAR_RANGE_MATCH.finditer(t)}
    stripped = _YEAR_RANGE_MATCH.sub(" ", t)
    years |= {int(m.group(1)[-4:]) for m in _YEAR_BARE_MATCH.finditer(stripped)}
    years |= {y for _s, _tok, y in short_fy_tokens(t)}
    return years


# ── Short financial-year forms: ONE reader for every caller (2026-10-26) ────────
# "FY 25", "FY25", "FY'25" (the year ENDING March 2025 = FY 2024-25, D-068), "FY 23-24"
# and a two-digit range after a time word ("in 23-24" = FY 2023-24). Four year readers
# each knew a different subset, so a year the extractor dropped was lost in some
# places only: a follow-up "FY20?" was rewritten to the previous turn's FY 2022-23 and
# the rewrite check, reading no year in "FY20?", let it through (FY sweep 2026-10-26).
# extract_year_keys, the pipeline's year-gap guard and its year back-fill all read this.
_CP_SHORT_FY_LEAD = frozenset(("in", "for", "during", "of", "year"))


def _cp_two_digits(s: str) -> bool:
    return len(s) == 2 and s.isdecimal()


def short_fy_tokens(text: str) -> list[tuple[int, str, int]]:
    """(start, raw token, FY start year) for each short FY form, left to right."""
    t = text or ""
    toks = tokens(t)
    out: list[tuple[int, str, int]] = []

    def _range_end(k: int) -> int:
        # "FY 23-24": the token after toks[k] is "-NN" / "/NN", the next year
        if k + 1 < len(toks) and t[toks[k].end:toks[k + 1].start].strip() in ("-", "/") \
                and _cp_two_digits(toks[k + 1].raw) \
                and int(toks[k + 1].raw) == (int(toks[k].raw[-2:]) + 1) % 100:
            return toks[k + 1].end
        return toks[k].end

    def _add(start: int, digits_k: int, digits: str) -> None:
        end = _range_end(digits_k)
        yy = int(digits)
        # a range starts in its first year; a single "FY 25" ends in 2025
        out.append((start, t[start:end], 2000 + yy if end != toks[digits_k].end else 2000 + yy - 1))

    k = 0
    while k < len(toks):
        tk = toks[k]
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        if tk.low == "fy" and nxt is not None and _cp_two_digits(nxt.raw) \
                and t[tk.end:nxt.start].strip() in ("", "'"):
            _add(tk.start, k + 1, nxt.raw)
        elif len(tk.low) == 4 and tk.low.startswith("fy") and _cp_two_digits(tk.raw[2:]):
            _add(tk.start, k, tk.raw[2:])
        elif _cp_two_digits(tk.raw) and k and toks[k - 1].low in _CP_SHORT_FY_LEAD \
                and 10 <= int(tk.raw) <= 39 and _range_end(k) != tk.end \
                and t[tk.start - 1:tk.start] not in ("-", "/"):
            _add(tk.start, k, tk.raw)
        else:
            k += 1
            continue
        while k < len(toks) and toks[k].start < out[-1][0] + len(out[-1][1]):
            k += 1
    return out


# "How many households received employment in Meghalaya in FY23?" (Excel sheet run
# 2026-10-27, KI-431): the year was resolved right (FY 2022-23), but the SQL model read
# "FY 23" as year_key = 2023 and kept it through every repair. The SQL and repair prompts
# get each short form written out in full, the same reading short_fy_tokens gives.
def expand_short_fy(text: str) -> str:
    """`text` with each short FY form written as "FY YYYY-YY" ("FY23" -> "FY 2022-23")."""
    t = text or ""
    out, last = [], 0
    for start, raw, y in short_fy_tokens(t):
        out.append(t[last:start])
        out.append(f"FY {y}-{(y + 1) % 100:02d}")
        last = start + len(raw)
    out.append(t[last:])
    return "".join(out)


_CP_HOW_MUCH = Matcher(Seq("how", "much"))


def metric_families(text: str) -> set[str]:
    return {name for name, word_matcher in _METRIC_FAMILIES.items() if word_matcher.search(text or "")}


def category_terms(text: str) -> set[str]:
    """Closed-vocabulary category values in the text, normalised: demographic
    words, Focus Plus tranche numbers, and every CM Elevate sub-scheme name
    any catalogue holds."""
    t = text or ""
    out = {m.group(1).lower().rstrip("s") for m in _DEMOGRAPHIC_MATCH.finditer(t)}
    out |= {f"tranche {d}" for d in _cp_tranche_numbers(t)}
    low = t.lower()
    for form, canonical in _catalog_category_forms():
        if _cp_has_term(low, form):
            out.add(canonical)
    return out


def _catalog_category_forms() -> list[tuple[str, str]]:
    """(lower-case name form, lower-case canonical) for every sub-scheme the
    catalogues hold, canonical name and aliases alike, so "Piggery" and
    "Meghalaya Piggery Development Scheme" are the same category. Forms under
    5 characters ("pig") are skipped as too likely to occur by accident."""
    try:
        from app import entity_resolver as er
        forms: set[tuple[str, str]] = set()
        for dims in er._catalog.values():
            for v in dims.get("cm_scheme") or []:
                canonical = str(v.get("canonical") or "").lower()
                for f in [canonical, *(v.get("aliases") or [])]:
                    f = str(f).lower().strip()
                    if canonical and len(f) >= 5:
                        forms.add((f, canonical))
        return sorted(forms, key=lambda x: -len(x[0]))
    except Exception:  # noqa: BLE001 — no catalogue loaded: demographic words only
        return []


def _places(text: str) -> dict[str, str]:
    try:
        from app.entity_resolver import named_places
        return named_places(text)
    except Exception:  # noqa: BLE001
        return {}


def _any_place(text: str) -> dict[str, str]:
    """_places plus assembly constituencies and villages (entity_resolver.
    place_mentions). Only the continuation signal uses it: the merge plan
    below keeps reading districts and blocks alone."""
    try:
        from app.entity_resolver import place_mentions
        return place_mentions(text)
    except Exception:  # noqa: BLE001
        return _places(text)


def _schemes_named(text: str) -> set[str]:
    try:
        from app import pipeline as _p
        return set(_p._named_schemes(text)) | set(_p._infer_scheme_from_terms(text) or [])
    except Exception:  # noqa: BLE001
        return set()


# ── Does the message continue the conversation at all? ─────────────────────
# Reported 2026-09-29, after a Focus Plus answer: "who is harshit", then "he is
# my collik remember", were both answered with Focus Plus reference material,
# and "now give me five thousand loan for me i am in crisis" became a Focus Plus
# DATA question that paused for the year. looks_like_followup() reads any short
# message with no anchor word as a fragment, and edge.detect_edge_case skips its
# off-topic whitelist whenever a previous answer exists, so the previous scheme
# was inherited by messages that share nothing with it.
#
# A message may continue the previous turn only when it carries something that
# can: scheme or measure vocabulary, a place, a year, a grouping or comparison,
# a reference into the previous answer, or a question about how a scheme works.
# Deterministic; a message with none of these is a NEW query, and routes as one.
_REFERENCE_MATCH = Matcher(W(
    "it", "its", "that", "those", "these", "them", "they", "there", "this", "same", "one", "ones",
    "former", "latter", "other", "both", "each", "either", "neither", "rest", "remaining", "previous",
    "above", "earlier", "again", "instead",
    # meta: "what did I ask before?", "you said 5,000"
    "before", "asked", "said", "told", "answer", "answered", "question"))
_RANK_MATCH = Matcher(W(
    "top", "bottom", "first", "second", "third", "last", "next", "highest", "lowest", "largest",
    "smallest", "biggest", "most", "least", "more", "less", "fewer", "higher", "lower", "bigger",
    "smaller", "greater", "max", "maximum", "min", "minimum", "average", "mean", "sum", "total",
    "count", "rank", "ranking", "sort", "order", "percent", "percentage", "share", "ratio", "rate",
    "difference", "change", "growth", "trend", "increase", "decrease"))
# How-the-scheme-works vocabulary: the knowledge follow-ups ("Documents?",
# "who can apply?", "when was it launched?") that name no scheme of their own.
_SCHEME_TOPIC_MATCH = Matcher(Alt(
    W("benefit", "benefits", "document", "documents", "apply", "applying", "application", "applicant",
      "applicants", "criteria", "start", "started", "objective", "objectives", "purpose", "aim", "aims",
      "goal", "goals", "component", "components", "rule", "rules", "guideline", "guidelines",
      "procedure", "process", "step", "steps", "grant", "grants", "loan", "loans", "interest", "amount",
      "payment", "payments", "status", "agency", "agencies", "department", "ministry", "officer",
      "nodal", "budget", "covered", "coverage", "helpline", "contact", "portal", "website", "office",
      "deadline", "age", "income", "land", "farmer", "farmers", "women", "men", "gender", "sector",
      "sectors", "programme", "programmes", "program", "programs", "detail", "details", "more",
      "explain", "elaborate", "why", "how"),
    W("eligib", "launch", "entitle", "subsid", "tranch", "batch", "implement", "fund", "register",
      "enrol", "categor", prefix=True),
    # instal+ments?
    Pred(lambda w: w.lower().rstrip("s").startswith("instal")
         and w.lower().rstrip("s")[len("instal"):].lstrip("l") == "ment"),
    Joined("sub", ("scheme", "schemes"))))
# "what about …", "what of …", "and …", "also …" at the very start.
_LEAD_MATCH = Matcher(Seq(_CpStart(_cp_ws), Alt(Seq(W("what", "how"), "about"), "what of",
                                             W("and", "also", "same", "then"))))



def continuation_signals(question: str) -> list[str]:
    """Why `question` may continue the previous turn, as a list of signal
    names (empty = it shares nothing with a scheme conversation). Read by
    pipeline._turn_context_stage before the edge check and the follow-up rewrite,
    and logged, so "why did this turn inherit the scheme?" has an answer."""
    q = (question or "").strip()
    if not q:
        return []
    out: list[str] = []
    try:
        from app import edge
        if edge.has_domain_vocabulary(q):
            out.append("domain")
    except Exception:  # noqa: BLE001 — no edge vocabulary: the other signals still count
        pass
    if _schemes_named(q):
        out.append("scheme")
    # Any level: "in ambare ading" (a village, no "village" word) continues a
    # PMAY-G answer as surely as "in East Garo Hills" (user report 2026-10-21).
    if _any_place(q):
        out.append("place")
    if extract_year_keys(q) or _RELATIVE_YEAR_MATCH.search(q) or _ALL_YEARS_MATCH.search(q):
        out.append("year")
    if metric_families(q):
        out.append("metric")
    if category_terms(q):
        out.append("category")
    if _GROUP_BY_MATCH.search(q) or any(word_matcher.search(q) for word_matcher in _ALL_GEO_MATCH.values()):
        out.append("group_by")
    if _COMPARE_MATCH.search(q):
        out.append("compare")
    if _REFERENCE_MATCH.search(q) or _AMBIGUOUS_REF_MATCH.search(q):
        out.append("reference")
    if _RANK_MATCH.search(q):
        out.append("rank")
    if _SCHEME_TOPIC_MATCH.search(q):
        out.append("scheme_topic")
    # "what about Mawlai?" / "and Nongpoh?": an explicit continuation lead with
    # a short remainder. Villages are not catalogued offline, so the remainder
    # cannot be checked here; the lead itself is the user saying "continue".
    if _LEAD_MATCH.search(q) and len(q.split()) <= 6:
        out.append("lead")
    # Khasi / Garo / Bengali / Hindi script: none of the English vocabularies
    # above can read it, and edge.detect_edge_case lets it through for the model
    # to read (its step 5). Unknown is not "unrelated", so it keeps its context.
    if sum(1 for c in q if ord(c) > 127) >= 3:
        out.append("non_english")
    return out


# "Which one?" / "that one?" / "which of them?" with nothing else: a pointer
# with no predicate. What it points at cannot be read from the previous result
# (which one of what, by what measure?), so the answer is a question back, not
# a rewrite the model has to guess.
def _cp_comma_gap(g: str) -> bool:
    """Only whitespace and at most one comma."""
    return g.strip() in ("", ",")


_CP_WHICH_ONE = Seq(W("which", "what", "that", "this", "the"), W("one", "ones"),
                    Opt(W("then", "now", "exactly", "again")), sep="space")
_BARE_REFERENCE_MATCH = Matcher(Alt(
    Seq(_CpStart(_cp_ws), W("and", "so", "ok", "okay", "then"), _CpSep(_cp_comma_gap), _CP_WHICH_ONE,
        _CpEnd(_cp_end_punct)),
    Seq(_CpStart(_cp_comma_gap), _CP_WHICH_ONE, _CpEnd(_cp_end_punct)),
    Seq(_CpStart(_cp_ws), Seq(Opt("and"), "which", "of", W("them", "these", "those"), sep="space"),
        _CpEnd(_cp_end_punct))))



def is_bare_reference(question: str) -> bool:
    return bool(_BARE_REFERENCE_MATCH.match(question or ""))


# ── Standalone or follow-up? (D-061, user addendum 2026-10-22) ──────────────
# "Context Memory: New Question = New Answer". After "MGNREGA person-days in
# East Khasi Hills in 2022-23", "Which district has the highest beneficiaries
# in MGNREGA?" was answered inside East Khasi Hills and FY 2022-23: naming the
# chat's own scheme read as a follow-up (is_scopeless_followup), and a new
# question inherited the chat's place and year anyway (D-056). The rule now:
# the question wins; memory only fills the gaps a question leaves on purpose.
#
#   FOLLOWUP    a reference cue ("it", "there", "same", "compare this", "what
#               about", "and ...") or a fragment with no measure of its own
#               ("2023-24?", "Mawphlang?", "Which block is highest?"):
#               inherits only what it leaves out.
#   STANDALONE  the stranger test: its own scheme (named, or pinned by its
#               measure) AND its own measure, and no reference cue. Inherits
#               NOTHING; the year comes from the question or the default rule.
#   VAGUE       a measure with no scheme and no cue ("how many
#               beneficiaries?"): one open topic -> that topic; several -> ask.
#
# Out-of-scope, reset, correction and "go back to ..." are decided before
# this (edge, conversation_layer, topic_memory) and never reach it. Naming the
# chat's own scheme is never by itself a reason to inherit.
TURN_FOLLOWUP = "followup"
TURN_STANDALONE = "standalone"
TURN_VAGUE = "vague"

# Pointers into the conversation. "this"/"that"/"there" have ordinary uses
# too ("this year", "households that got work", "are there"), filtered below.
_TK_ALWAYS_REF = frozenset((
    "it", "its", "those", "these", "them", "their", "they", "same", "above", "previous",
    "instead", "former", "latter", "aforementioned", "here", "again", "earlier",
    # Hinglish pointers ("wahi figure dobara", "uska total", "pehle wala"); "wala"
    # alone is not one ("MGNREGA ka 2024-25 wala data" is a question of its own)
    "dobara", "dubara", "phir", "wapas", "vapas", "pehle", "pichla", "pichle", "wahi", "wohi",
    "wahan", "waha", "usi", "uska", "uski", "iska", "iski"))
_TK_LEADS = frozenset(("and", "also"))
_TK_TIME_NOUNS = frozenset(("year", "years", "fy", "financial", "month", "week", "quarter", "time",
                            "season", "session"))
# "that" points back when it closes the question or follows one of these
# ("compare that", "of that", "is that"), or names a thing ("that district").
_TK_THAT_AFTER = frozenset(("of", "for", "in", "with", "is", "was", "compare", "about", "than", "to",
                            "from", "on", "under", "and", "at", "show", "give", "repeat", "explain"))
_TK_THAT_BEFORE = frozenset(("district", "block", "village", "scheme", "figure", "number", "one", "place",
                             "area", "data", "answer", "result", "amount", "total", "list", "constituency",
                             "period", "query", "question"))
_TK_EXISTENTIAL = frozenset(("is", "are", "was", "were", "be", "been", "any"))
_TK_MULTI_REF = frozenset(("both", "either", "neither", "other", "rest", "remaining"))
_TK_COMPARE = frozenset(("compare", "comparison", "versus", "vs", "vs."))
# A request for the data itself names no measure but is still complete:
# "MGNREGA ka 2024-25 wala district-wise data batao".
_TK_DATA_NOUNS = frozenset(("data", "details", "detail", "figures", "figure", "numbers", "statistics",
                            "stats", "summary", "overview", "report", "performance", "progress"))


@dataclass(frozen=True)
class TurnKind:
    kind: str
    reasons: tuple = ()
    asked: tuple = ()          # place levels the question asks ABOUT (asked_levels)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "reasons": list(self.reasons), "asked": list(self.asked)}


def _tk_reference_cues(q: str, n_schemes: int) -> list[str]:
    ws = [w for w in (t.low for t in tokens(q))]
    out: list[str] = []
    if ws and ws[0] in _TK_LEADS:
        out.append("lead:" + ws[0])
    if _LEAD_MATCH.search(q):
        out.append("lead")
    for i, w in enumerate(ws):
        nxt = ws[i + 1] if i + 1 < len(ws) else ""
        before = ws[i - 1] if i else ""
        if w in _TK_ALWAYS_REF:
            out.append(w)
        elif w == "this" and nxt not in _TK_TIME_NOUNS:
            out.append(w)
        elif w == "that" and nxt not in _TK_TIME_NOUNS and (
                not nxt or before in _TK_THAT_AFTER or nxt in _TK_THAT_BEFORE):
            out.append(w)
        elif w == "there" and before not in _TK_EXISTENTIAL:
            out.append(w)
        elif w in _TK_MULTI_REF and n_schemes < 2:
            out.append(w)
    # "compare with PMAY-G": one side is named, the other is the conversation.
    if set(ws) & _TK_COMPARE:
        sides = n_schemes + len(extract_year_keys(q)) + len(_places(q))
        if sides < 2:
            out.append("compare-one-side")
    return list(dict.fromkeys(out))


def _tk_named_schemes(q: str) -> bool:
    """The question names a scheme in words (not only through its measure),
    a bare "Focus" / "CM Elevate" included — those are asked, never guessed."""
    try:
        from app import pipeline as _p
        return bool(_p._named_schemes(q) or _p._mentions_scheme(q) or _p._names_bare_focus_scheme(q))
    except Exception:  # noqa: BLE001
        return False


def asked_levels(question: str) -> tuple:
    """The place levels a question asks ABOUT rather than filters BY: "which
    district …", "top 5 villages", "district-wise", "by block", "each
    village". The chat's place at that level and below cannot be its filter
    (filtering by what you are ranking answers one row), the level above it
    can. Coarsest first."""
    q = question or ""
    ws = [t.low for t in tokens(q)]
    out = []
    grouped = grouping_dims(q)                    # D-110: the one grouping reader, as the catalogue / rules read it
    for dim in ("district", "block", "village"):
        hit = _RANK_OVER_GEO_MATCH[dim].search(q) or _ALL_GEO_MATCH[dim].search(q) or dim in grouped
        if not hit:
            hit = any(w == "which" and i + 1 < len(ws) and ws[i + 1] in (dim, dim + "s")
                      for i, w in enumerate(ws))
        if hit:
            out.append(dim)
    return tuple(out)


def turn_kind(question: str) -> TurnKind:
    """FOLLOWUP / STANDALONE / VAGUE for an in-scope message (see the block
    comment above). Deterministic, offline; the chat's own state is never read,
    so the same words get the same verdict in every conversation."""
    q = (question or "").strip()
    schemes = _schemes_named(q)
    cues = _tk_reference_cues(q, len(schemes))
    asked = asked_levels(q)
    if not q:
        return TurnKind(TURN_FOLLOWUP, ("empty",), asked)
    if cues:
        return TurnKind(TURN_FOLLOWUP, tuple("cue:" + c for c in cues), asked)
    ws = set(t.low for t in tokens(q))
    measure = sorted(metric_families(q)) + sorted(ws & _TK_DATA_NOUNS)
    named = _tk_named_schemes(q)
    # A scheme pinned only by its measure ("how many job cards?") is the short,
    # vague step 6 of the addendum, like "how many beneficiaries?": it stands on
    # its own only with a scope of its own ("person-days in 2023-24").
    own_scope = bool(extract_year_keys(q) or _RELATIVE_YEAR_MATCH.search(q) or _ALL_YEARS_MATCH.search(q)
                     or set(_any_place(q)) - {"MEGHALAYA"})
    if measure and (named or (schemes and own_scope)):
        return TurnKind(TURN_STANDALONE, ("scheme:" + "+".join(sorted(schemes)),
                                          "named" if named else "pinned-by-measure",
                                          "measure:" + "+".join(measure)), asked)
    if measure:
        return TurnKind(TURN_VAGUE, ("measure:" + "+".join(measure), "no-scheme"), asked)
    return TurnKind(TURN_FOLLOWUP, ("fragment",) + (("scheme:" + "+".join(sorted(schemes)),) if schemes else ()),
                    asked)


# ── Merge plan ──────────────────────────────────────────────────────────────
@dataclass
class MergePlan:
    actions: dict[str, str] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    kind: str = FILTER_CHANGE

    def action(self, name: str) -> str:
        return self.actions.get(name, KEEP)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "actions": dict(self.actions)}


def plan_state_merge(question: str, state=None, *, prev=None, is_followup: bool = True,
                     clarification_response: bool = False) -> MergePlan:
    """Field-by-field effect of `question` on the conversation state.

    Only what the question itself says counts, as read by deterministic
    scanners (scheme registry, resolver catalogue, year/metric/category
    vocabularies). A field the question says nothing about is KEEP; a named
    new value is REPLACE (and clears the finer geography under it); an "all
    X" / "by X" is CLEAR; a reference that cannot be pinned is
    REQUIRE_CLARIFICATION. Never guesses a value."""
    q = question or ""
    plan = MergePlan()
    act, why = plan.actions, plan.reasons

    def set_(name, action, reason):
        act[name] = action
        why[name] = reason

    for name in ("scheme", "district", "block", "village", "year", "category", "metric",
                 "group_by"):
        act[name] = KEEP

    prev_schemes = set(getattr(prev, "schemes", None) or [])
    state_scheme = getattr(state, "scheme", None)
    current = prev_schemes | ({state_scheme} if state_scheme else set())
    named = _schemes_named(q)
    if named and named != current:
        set_("scheme", REPLACE, f"names {sorted(named)}")

    places = _places(q)
    districts = [n for n, d in places.items() if d == "district"]
    blocks = [n for n, d in places.items() if d == "block"]
    if districts:
        set_("district", REPLACE, f"names {districts}")
    if blocks:
        set_("block", REPLACE, f"names {blocks}")
    for dim, word_matcher in _ALL_GEO_MATCH.items():
        if word_matcher.search(q) and act[dim] != REPLACE:
            set_(dim, CLEAR, "all / by " + dim)
    for dim, rank_matcher in _RANK_OVER_GEO_MATCH.items():
        if rank_matcher.search(q) and act[dim] == KEEP:
            set_(dim, CLEAR, "ranks the " + dim + "s")
    # A coarser geography change invalidates the finer levels under it, unless
    # the question names them too ("Dalu block in West Garo Hills").
    for coarse in ("district", "block"):
        if act[coarse] in (REPLACE, CLEAR):
            for fine in FIELD_POLICIES[coarse].clears_on_replace:
                if act[fine] == KEEP:
                    set_(fine, CLEAR, f"{coarse} changed")

    years = extract_year_keys(q)
    if years:
        set_("year", REPLACE, f"names {sorted(years)}")
    elif _RELATIVE_YEAR_MATCH.search(q):
        known = getattr(state, "year", None)
        prev_year = (getattr(prev, "resolved_entities", None) or {}).get("year_key")
        if known is None and prev_year is None:
            set_("year", REQUIRE_CLARIFICATION, "relative year with no known year")
        else:
            set_("year", REPLACE, "relative year")
    if _ALL_YEARS_MATCH.search(q) and act["year"] != REPLACE:
        set_("year", CLEAR, "all years / by year")
    # "and all of them combined?" after "what about 2025-26?": the dimension the
    # user was just varying (live 2026-09-29: it kept FY 2025-26 and repeated 137
    # instead of both years together). Only when the question names no value of
    # its own; with no varied dimension on record the model rewrite decides.
    _last = getattr(state, "last_dimension", None)
    if (_ALL_OF_THEM_MATCH.search(q) and _last in ("year", "district", "block")
            and act.get(_last) == KEEP and not places and not years):
        set_(_last, CLEAR, f"'all of them' = every {_last} just compared")
        for fine in FIELD_POLICIES[_last].clears_on_replace if _last != "year" else ():
            if act[fine] == KEEP:
                set_(fine, CLEAR, f"{_last} changed")

    if metric_families(q):
        set_("metric", REPLACE, f"names {sorted(metric_families(q))}")
    cats = category_terms(q)
    if cats:
        set_("category", REPLACE, f"names {sorted(cats)}")
    elif _ALL_CATEGORY_MATCH.search(q):
        set_("category", CLEAR, "all categories")

    group = _GROUP_BY_MATCH.search(q)
    if group:
        set_("group_by", REPLACE, group.group(0))

    if _AMBIGUOUS_REF_MATCH.search(q):
        ents = list(getattr(state, "comparison_entities", None) or [])
        if len(ents) != 2:
            set_("reference", REQUIRE_CLARIFICATION,
                 f"'other one/former/latter' with {len(ents)} candidates")
    elif is_bare_reference(q):
        set_("reference", REQUIRE_CLARIFICATION, "a bare 'which one?' with nothing to pick by")

    plan.kind = _kind(plan, q, is_followup=is_followup,
                      clarification_response=clarification_response)
    return plan


def _kind(plan: MergePlan, q: str, *, is_followup: bool, clarification_response: bool) -> str:
    from app.context_manager import references_previous_result
    if clarification_response:
        return CLARIFICATION_RESPONSE
    if not is_followup:
        return NEW_QUERY
    if plan.action("scheme") == REPLACE:
        from app import pipeline as _p
        if _p._scheme_substitution(q)[0]:
            return SCHEME_SUBSTITUTION
    if references_previous_result(q):
        return RESULT_REFERENCE
    if _COMPARE_MATCH.search(q):
        return COMPARISON
    if plan.action("group_by") == REPLACE:
        return GROUP_BY_CHANGE
    changed = {n for n in ("district", "block", "village", "year", "metric", "category", "scheme")
               if plan.action(n) in (REPLACE, CLEAR)}
    geo = {"district", "block", "village"}
    if not changed:
        return FILTER_CHANGE
    if changed <= geo:
        return GEOGRAPHY_CHANGE
    if changed == {"year"}:
        return TIME_CHANGE
    if changed == {"metric"}:
        return METRIC_CHANGE
    return FILTER_CHANGE


def apply_merge_plan(prior_resolved: dict | None, plan: MergePlan | None) -> dict:
    """What resolve_entities may inherit, given the plan. A field the question
    REPLACEs, CLEARs or can't pin is removed from the fallback: the question
    supplies it, removed it, or the existing gate must ask. KEEP leaves it.
    Only ever removes keys; never adds or rewrites a value."""
    out = dict(prior_resolved or {})
    if plan is None:
        return out
    for name, policy in FIELD_POLICIES.items():
        if plan.action(name) in (REPLACE, CLEAR, REQUIRE_CLARIFICATION):
            for key in policy.resolved_keys:
                out.pop(key, None)
            if name == "category" and plan.action(name) == CLEAR:
                out.pop("tranche_all_combined", None)
    return out


# ── Provenance ──────────────────────────────────────────────────────────────
def _value_named_in(field_name: str, value, text: str) -> bool:
    if value is None or not text:
        return False
    if field_name in ("district", "block"):
        return str(value).upper() in _places(text)
    if field_name == "year":
        try:
            return int(value) in extract_year_keys(text)
        except (TypeError, ValueError):
            return False
    if field_name == "scheme":
        return value in _schemes_named(text)
    if field_name == "metric":
        from app.context_manager import detect_metric
        return detect_metric(text) == value
    return str(value).lower() in text.lower()


def provenance_for(field_name: str, value, *, raw_question: str, substituted_question: str,
                   prior_value, prior_record: dict | None, clarification_reply: str | None,
                   previous_question: str, validated: bool) -> dict:
    """{"value", "source", "confidence"} for one committed value. Checked in
    order of strength: the pause reply, the user's own words, a deterministic
    reference substitution, the previous turn, a validated lookup, and only
    then model inference."""
    if clarification_reply and _value_named_in(field_name, value, clarification_reply):
        source = "clarification_response"
    elif _value_named_in(field_name, value, raw_question):
        source = "current_user"
    elif substituted_question != raw_question and _value_named_in(field_name, value,
                                                                   substituted_question):
        source = "resolved_reference"
    elif prior_value is not None and str(prior_value) == str(value):
        prior_source = (prior_record or {}).get("source")
        source = "model_inference" if prior_source == "model_inference" else "previous_user"
    elif _value_named_in(field_name, value, previous_question):
        source = "previous_user"
    elif validated:
        source = "validated_database"
    else:
        source = "model_inference"
    return {"value": value, "source": source, "confidence": _CONFIDENCE[source]}


# ── Rewrite checks ──────────────────────────────────────────────────────────
def rewrite_violation(rewritten: str, *, question: str, allowed_text: str, denied_text: str,
                      allowed_schemes: list[str], state_year: int | None = None,
                      cleared: dict | None = None) -> str | None:
    """The field ('scheme' | 'district' | 'block' | 'year' | 'metric' |
    'category' | 'name') that a rewritten follow-up names with no permitted
    source, else None. Each field has its own rule:

      scheme / district / block  must appear, canonically, in a permitted source.
      year      may be any year a permitted source names, or +-1 of one when
                the follow-up uses a relative year ("last year"), so an
                explicit year change by the user is always allowed.
      metric    compared by family (money / count / days / completion), so a
                paraphrase passes and a new measure from nowhere does not.
      category  closed vocabulary (demographics, tranche numbers, sub-schemes).
      name      any capitalised word that appears in text the rewrite was NOT
                allowed to use (the previous answer, the summary and older
                turns without a back-reference) and in no permitted source.
                This is how villages are covered offline: a village name can
                only leak from text the model saw.
    """
    from app import pipeline as _p

    # A filter the follow-up REMOVED ("show it by district") must not come back
    # through the rewrite, even though the previous question (a permitted
    # source) names it.
    for fld, value in (cleared or {}).items():
        if fld in ("district", "block") and str(value).upper() in _places(rewritten):
            return f"cleared:{fld}"
        if fld == "year" and extract_year_keys(str(value)) & extract_year_keys(rewritten):
            return "cleared:year"

    if not _p._CROSS_SCHEME_FOLLOWUP.search(question or ""):
        ok = (set(allowed_schemes) | _p._exact_schemes(allowed_text) | _schemes_named(question))
        if _p._exact_schemes(rewritten) - ok:
            return "scheme"
    permitted = _places(allowed_text)
    for name, dim in _places(rewritten).items():
        if name not in permitted:
            return dim
    # A village the user typed must come through letter for letter (its key is
    # the folded text as typed; districts, blocks and constituencies are compared
    # canonically above). Live 2026-10-21: "in dangar dombah" was rewritten "... in Dargar
    # Dombah ...", which matched no village exactly and paused on a fuzzy
    # DANGAR DOMBAH / DOMBAH choice for a name the user had spelt right.
    try:
        from app.entity_resolver import fold_words as _fold_words
        _rw = f" {' '.join(_fold_words(rewritten))} "
        _rw_places = _any_place(rewritten)
        for name, dim in _any_place(question).items():
            if dim == "village" and f" {name} " not in _rw:
                return dim
            # Any level: a bare "wapung" (an East Jaintia Hills block) after an
            # East Khasi Hills answer was rewritten back to East Khasi Hills —
            # the block dropped, the wrong place answered (live 2026-10-21).
            if dim != "village" and name not in _rw_places:
                return f"dropped:{dim}"
    except Exception:  # noqa: BLE001 — no index: the checks above still hold
        pass
    new_years = extract_year_keys(rewritten)
    if new_years:
        ok_years = extract_year_keys(allowed_text) | ({state_year} if state_year else set())
        if _RELATIVE_YEAR_MATCH.search(question or ""):
            ok_years |= {y + d for y in set(ok_years) for d in (-1, 1)}
        if new_years - ok_years:
            return "year"
    # The follow-up's OWN year must survive the rewrite. "FY20?" after an FY 2022-23
    # answer was rewritten "… in FY 2022-23 …": the state's year is a permitted source,
    # so the check above passed while the year the user typed was gone (FY sweep
    # 2026-10-26). A second year may still be added ("compare FY 25 with that").
    own_years = extract_year_keys(question or "")
    if own_years and not own_years <= new_years:
        return "year"
    if metric_families(rewritten) - metric_families(allowed_text):
        return "metric"
    # The follow-up's OWN measure must survive the rewrite. Live 2026-09-29:
    # "give me beneficiaries" became "What is the disbursement for Focus Plus…"
    # — money was allowed (the state line said metric=disbursement), so the
    # check above passed while the count the user asked for was gone. "how
    # much" is left out: it is money or quantity depending on the noun.
    own = metric_families(_CP_HOW_MUCH.sub(" ", question or ""))
    if own - metric_families(rewritten):
        return "metric"
    if category_terms(rewritten) - category_terms(allowed_text):
        return "category"
    if denied_text:
        allowed_low = (allowed_text or "").lower()
        denied_low = denied_text.lower()
        for w in _CAP_WORD_MATCH.findall(rewritten):
            lw = w.lower()
            if lw in _NAME_STOPWORDS:
                continue
            in_denied = _cp_has_term(denied_low, lw)
            in_allowed = _cp_has_term(allowed_low, lw)
            if in_denied and not in_allowed:
                return "name"
    return None
