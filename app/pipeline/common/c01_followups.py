# app/pipeline/common/c01_followups.py — imports, exceptions, follow-up detection, scheme swaps, measure-not-held gaps, follow-up rewriting.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.

"""
The whole NL -> SQL -> answer flow, as stage functions (`_turn_*_stage`,
`_data_*_stage`, `_execute_one_attempt`, ...). The LangGraph orchestrator in
app/pipeline_graph.py is the only driver: it runs these stages as graph nodes
(D-032, D-036). Behaviour lives here, in the stages, never in a graph node.
"""
import asyncio
import calendar
import datetime
import contextvars
import dataclasses
import itertools
import json
import functools
import logging
import numbers
from decimal import Decimal

import httpx
import sqlglot
from rapidfuzz import fuzz
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType

from app import annotations, auth, context_manager, edge, followups, llm, premise_check, prompt_builder, rag
from app import context_budget, context_policy, cross_figures, cross_scheme, guardrails, topic_memory
from app import scheme_registry, sql_ast, sql_examples, turn_trace
from app.config import settings
from app.db import UnsafeSQLError, fetch_rows, run_readonly
from app.db import DatabaseUnavailableError, is_connection_error as db_is_connection_error
from app.db import precheck_readonly as db_precheck_readonly
from app.entity_resolver import (
    Resolved,
    acronym_near_misses,
    all_districts,
    block_parent_district,
    canonical_names,
    collides_across_dimensions,
    collision_canonical_names,
    AC_CONTENTS_SOURCE,
    constituency_contents,
    detect_region,
    lookup_geo_term,
    named_places,
    resolve_cm_scheme,
    resolve_cm_scheme_group,
    resolve_cm_scheme_group_ambiguity,
    resolve_dimension,
    resolve_house_status,
    resolve_tranche_label,
    resolve_village,
    scan_dimension,
    scan_districts,
    fold,
    tranche_labels,
    village_names_exact,
)
from app.schema_context import SCHEME_CATALOG, available_metrics_text
from app.session_store import ConversationState, Session
from app.text_match import (
    Matcher, W, Pred, ANY, Seq, Alt, Opt, Rep, Gap, Joined, Cap, NotBefore, NotAfter,
    Before, After, START, END, Hit, collapse_ws, keep_chars, is_int,
)
from app.text_match import Node as _C01Node
from app.text_match import numbers as _c01_tm_numbers, words as _c01_tm_words, tokens as _c01_tm_tokens

logger = logging.getLogger(__name__)


# ── word-matching pieces for c01–c03 (D-047: app/text_match only) ──────────
# Words are matched with app/text_match.py. The pieces below cover the shapes
# it has no node for: a separator that must be whitespace (or a hyphen, or one
# comma), a stretch of text measured in characters, text-start / text-end
# anchors that allow only whitespace or given punctuation around the words, a
# check on the text just before a word ("not the "), a year pair ("FY 2023-24", "23-24").

def _c01_between(ctx, i: int) -> str:
    """The text between word i-1 (or the text start) and word i (or the text end)."""
    a = ctx.toks[i - 1].end if i > 0 else 0
    b = ctx.toks[i].start if i < len(ctx.toks) else len(ctx.text)
    return ctx.text[a:b]


def _c01_ws(g: str) -> bool:
    """One or more whitespace characters between two words."""
    return g != "" and g.strip() == ""


def _c01_ws0(g: str) -> bool:
    """Nothing, or only whitespace, between two words."""
    return g.strip() == ""


def _c01_opt1(g: str) -> bool:
    """Between two separate words: exactly one space or hyphen."""
    return len(g) == 1 and (g.isspace() or g == "-")


def _c01_wsdash(g: str) -> bool:
    """One or more spaces and/or hyphens between two words."""
    return g != "" and all(c.isspace() or c == "-" for c in g)


def _c01_dash(g: str) -> bool:
    """One "-", "–" or "/" between two numbers, spaces allowed around it."""
    return g.strip() in ("-", "–", "/")


class _C01Gap(_C01Node):
    """Zero-width: the separator before word i passes `fn` (always passes past the last word)."""

    def __init__(self, fn):
        self.fn = fn

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks) or self.fn(_c01_between(ctx, i)):
            yield i, caps


class _C01SpaceNext(_C01Node):
    """Zero-width: whitespace follows the previous word (the word, then its trailing space)."""

    def ends(self, ctx, i, caps):
        if _c01_between(ctx, i)[:1].isspace():
            yield i, caps


class _C01Begin(_C01Node):
    """Zero-width: the first word, with only whitespace before it (at text start), or
    one of `lead` ("#") once the whitespace is stripped."""

    def __init__(self, lead=("",)):
        self.lead = tuple(lead)

    def ends(self, ctx, i, caps):
        if i == 0 and _c01_between(ctx, 0).strip() in self.lead:
            yield i, caps


class _C01End(_C01Node):
    """Zero-width: past the last word, with only whitespace and `chars` after it
    (then the text ends)."""

    def __init__(self, chars: str = ""):
        self.chars = chars

    def ends(self, ctx, i, caps):
        if i == len(ctx.toks) and all(c in self.chars for c in _c01_between(ctx, i).strip()):
            yield i, caps


class _C01NotPreceded(_C01Node):
    """Zero-width: the text before word i does not end with any of `tails`
    (case-insensitive) — a check on the text just before it."""

    def __init__(self, *tails: str):
        self.tails = tuple(t.lower() for t in tails)

    def ends(self, ctx, i, caps):
        if i < len(ctx.toks) and ctx.text[:ctx.toks[i].start].lower().endswith(self.tails):
            return
        yield i, caps


class _C01NotNextWord(_C01Node):
    """Zero-width: word i is not one of `words` behind a separator passing `gap`
    — that whole next word must not follow."""

    def __init__(self, words, gap):
        self.words = frozenset(w.lower() for w in words)
        self.gap = gap

    def ends(self, ctx, i, caps):
        if i < len(ctx.toks) and ctx.toks[i].low in self.words and self.gap(_c01_between(ctx, i)):
            return
        yield i, caps


class _C01NextChar(_C01Node):
    """Zero-width: after optional whitespace, the text before word i starts with `ch`
    ("focus +")."""

    def __init__(self, ch: str):
        self.ch = ch

    def ends(self, ctx, i, caps):
        if _c01_between(ctx, i).lstrip().startswith(self.ch):
            yield i, caps


class _C01CharIn(_C01Node):
    """Zero-width: the non-word text before word i holds `ch` (a symbol such as '₹',
    which is never part of a word)."""

    def __init__(self, ch: str):
        self.ch = ch

    def ends(self, ctx, i, caps):
        if self.ch in _c01_between(ctx, i):
            yield i, caps


class _C01CharGap(_C01Node):
    """Zero or more words whose text, from the end of the previous word to the start
    of the next one, is at most `limit` characters and holds none of `forbid`
    (shortest first, always ending where a word starts)."""

    def __init__(self, limit: int, forbid: str = "\n"):
        self.limit, self.forbid = limit, forbid

    def ends(self, ctx, i, caps):
        start = ctx.toks[i - 1].end if i > 0 else 0
        for j in range(i, len(ctx.toks)):
            span = ctx.text[start:ctx.toks[j].start]
            if len(span) > self.limit or any(c in self.forbid for c in span):
                return
            yield j, caps


class _C01YearPair(_C01Node):
    """A pair of numbers '[FY] A <-|–|/> B' (FY 2023-24, fy2023/24, 23-24). A is
    group 1, B group 2; "FY" may stand apart or be glued to A ("FY2023")."""

    def __init__(self, first_ok, second_ok, bad_before: str = "", bad_after: str = ""):
        self.first_ok, self.second_ok = first_ok, second_ok
        self.bad_before, self.bad_after = bad_before, bad_after
        self.cap1, self.cap2 = Cap(ANY), Cap(ANY)
        self.parts = [self.cap1, self.cap2]

    def ends(self, ctx, i, caps):
        toks, text, n = ctx.toks, ctx.text, len(ctx.toks)
        if i >= n:
            return
        t = toks[i]
        cands = []
        if t.low == "fy" and i + 1 < n and _c01_ws(_c01_between(ctx, i + 1)) \
                and self.first_ok(toks[i + 1].raw):
            cands.append((i + 1, toks[i + 1].start, toks[i + 1].end))
        if t.low.startswith("fy") and self.first_ok(t.raw[2:]):
            cands.append((i, t.start + 2, t.end))
        if self.first_ok(t.raw):
            cands.append((i, t.start, t.end))
        if self.bad_before and t.start > 0 and text[t.start - 1] in self.bad_before:
            return
        for k, a0, a1 in cands:
            if k + 1 >= n or not _c01_dash(_c01_between(ctx, k + 1)):
                continue
            b = toks[k + 1]
            if not self.second_ok(b.raw):
                continue
            if self.bad_after and b.end < len(text) and text[b.end] in self.bad_after:
                continue
            yield k + 2, caps + ((self.cap1, a0, a1), (self.cap2, b.start, b.end))


class _C01Quick(Matcher):
    """A Matcher that first checks the lower-cased text holds one of `need`
    (strings any hit must contain) and skips the word scan when none is there.
    Same results, much cheaper for the scheme-name matchers run on every word."""

    def __init__(self, *pattern, need=(), **kw):
        super().__init__(*pattern, **kw)
        self.need = tuple(need)

    def _maybe(self, text) -> bool:
        low = (text or "").lower()
        return not self.need or any(s in low for s in self.need)

    def _scan(self, text, **kw):
        if self._maybe(text):
            yield from super()._scan(text, **kw)

    def finditer(self, text):
        if self._maybe(text):
            yield from super().finditer(text)


class _C01PlusMatcher(_C01Quick):
    """A Matcher whose hit on the bare word 'focus' also takes the '+' after it
    ("focus +" is Focus Plus), so .sub replaces the whole name."""

    def _hit(self, ctx, i, j, caps):
        h = super()._hit(ctx, i, j, caps)
        if h.group(0).lower() == "focus":
            k = h._end
            while k < len(ctx.text) and ctx.text[k].isspace():
                k += 1
            if k < len(ctx.text) and ctx.text[k] == "+":
                h._end = k + 1
        return h


_C01_GAP_KINDS = {
    # kind: (separator test between separate words, joiners when written as one word)
    "opt1": (_c01_opt1, ("",)),            # optional space or hyphen
    "opt1u": (_c01_opt1, ("", "_")),       # optional space, "_" or hyphen
    "ws*": (_c01_ws, ("",)),               # any whitespace, or none
    "ws+": (_c01_ws, ()),                  # one or more whitespace
    "wsu+": (_c01_ws, ("_",)),             # whitespace or "_"
    "wsd*": (_c01_wsdash, ("",)),          # spaces/hyphens, or none
    "wsd+": (_c01_wsdash, ()),             # one or more spaces/hyphens
}


def _c01_chain(parts, kinds):
    """Words written apart (separator of the given kind) or run together:
    _c01_chain(["job", ("card", "cards")], ["opt1u"]) = "job" then "card(s)", apart
    by one optional space, "_" or hyphen."""
    opts = [tuple(p) if isinstance(p, (tuple, list)) else (p,) for p in parts]
    variants = []
    for mask in range(2 ** (len(opts) - 1)):
        segs = [list(opts[0])]
        gaps = []
        ok = True
        for k in range(1, len(opts)):
            fn, joiners = _C01_GAP_KINDS[kinds[k - 1]]
            if mask >> (k - 1) & 1:
                if not joiners:
                    ok = False
                    break
                segs[-1] = [a + j + b for a in segs[-1] for j in joiners for b in opts[k]]
            else:
                gaps.append(fn)
                segs.append(list(opts[k]))
        if not ok:
            continue
        pieces = [W(*segs[0])]
        for fn, seg in zip(gaps, segs[1:]):
            pieces += [_C01Gap(fn), W(*seg)]
        variants.append(Seq(*pieces) if len(pieces) > 1 else pieces[0])
    return Alt(*variants) if len(variants) > 1 else variants[0]


def _c01_ph(*phrases):
    """Words / phrases with plain whitespace between their words (e.g. 'how many')."""
    nodes = [W(p) if " " not in p else Seq(*p.split(), sep="space") for p in phrases]
    return Alt(*nodes) if len(nodes) > 1 else nodes[0]


def _c01_tidy_space(s: str, before: str = ",?.", collapse: bool = True) -> str:
    """No whitespace before any of `before`; with `collapse`, runs of 2+
    whitespace become one space first (so "a  ,b" -> "a,b" and "a   b"
    -> "a b"). Not stripped."""
    out, i, n = [], 0, len(s or "")
    s = s or ""
    while i < n:
        if s[i].isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            if not (j < n and s[j] in before):
                out.append(" " if collapse and j - i > 1 else s[i:j])
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _c01_is_20dd(w: str) -> bool:
    return len(w) == 4 and w.startswith("20") and is_int(w)


def _c01_alpha_words(text: str) -> "list[str]":
    """Words of ASCII letters, apostrophes and hyphens that start with a letter
    ("ri-bhoi", "o'brien") — the old [a-z][a-z'-]* reading."""
    out, i, t = [], 0, text or ""
    n = len(t)
    while i < n:
        if t[i].isascii() and t[i].isalpha():
            j = i + 1
            while j < n and ((t[j].isascii() and t[j].isalpha()) or t[j] in "'-"):
                j += 1
            out.append(t[i:j])
            i = j
        else:
            i += 1
    return out


def _c01_is_alpha_word(w: str) -> bool:
    """`w` is exactly one _c01_alpha_words word."""
    return bool(w) and w[0].isascii() and w[0].isalpha() and all(
        (c.isascii() and c.isalpha()) or c in "'-" for c in w)


def _c01_underscored_employed(w: str) -> bool:
    """One word 'households_employed' / 'persons_were_employed' (a column name)."""
    ps = w.lower().split("_")
    return (len(ps) in (2, 3) and ps[-1] == "employed"
            and ps[0] in ("household", "households", "person", "persons", "people", "women",
                          "worker", "workers")
            and (len(ps) == 2 or ps[1] in ("were", "got")))


# The scheme names a scheme-swap fragment may end on. Focus Legacy, and a BARE
# "focus" — which names neither Focus scheme, so _scheme_swap_rewrite
# substitutes the word "Focus" and the normal "which Focus?" pause asks.
# Without these, "for focus" after a CM Elevate answer went to the LLM rewrite,
# which kept CM Elevate and re-answered it.
_C01_SWAP_SCHEME = Alt(
    W("mgnrega", "mnrega", "nrega", "awaa", "awaas", "awas"),
    _c01_chain(["pmay", "g"], ["opt1"]), W("pmay"),
    _c01_chain(["focus", "plus"], ["opt1"]),
    _c01_chain(["focus", "legacy"], ["opt1"]), W("focus"),
    _c01_chain(["cm", "elevate", "legacy"], ["opt1", "opt1"]),
    _c01_chain(["cm", "elevate"], ["opt1"]))
_C01_WS0 = _C01Gap(_c01_ws0)


class _C01SwapSep(_C01Node):
    """Zero-width, after the scheme / closing words of a scheme-swap fragment:
    whitespace before the next word, or only ?.! at the end. A '+' may follow a
    bare 'focus' ("focus +" = Focus Plus)."""

    def ends(self, ctx, i, caps):
        g = _c01_between(ctx, i)
        if i > 0 and ctx.toks[i - 1].low == "focus" and g.lstrip().startswith("+"):
            g = g.lstrip()[1:]
        if i < len(ctx.toks):
            if g.strip() == "":
                yield i, caps
        elif all(c in "?.!" for c in g.strip()):
            yield i, caps


_C01_SWAP_SEP = _C01SwapSep()
_C01_FILLER_PUNCT = ",.!?;:&+/-"


class _C01PlaceWords(_C01Node):
    """1-4 place words after "in"/"at" (group 1): each starts with a letter, is not
    a stop word, and may run on through ' . - ("ri-bhoi", "st. mary's"); only
    whitespace may separate two of them."""

    def __init__(self, stop, most: int = 4):
        self.stop = frozenset(stop)
        self.most = most
        self.cap = Cap(ANY)
        self.parts = [self.cap]

    def ends(self, ctx, i, caps):
        toks, n = ctx.toks, len(ctx.toks)
        k, count, last_end = i, 0, None
        while count < self.most and k < n:
            t = toks[k]
            if not (t.raw[0].isascii() and t.raw[0].isalpha()) or t.low in self.stop:
                break
            m = k
            while m + 1 < n:
                g = _c01_between(ctx, m + 1)
                if g and all(c in "'.-" for c in g):
                    m += 1
                else:
                    break
            tail = _c01_between(ctx, m + 1)
            j = 0
            while j < len(tail) and tail[j] in "'.-":
                j += 1
            last_end = toks[m].end + j
            count += 1
            k = m + 1
            if tail[j:].strip() != "":
                break
        if count:
            yield k, caps + ((self.cap, toks[i].start, last_end),)


def _c01_strip_answer_label(s: str) -> str:
    """'Rephrased question: …' / 'Question: …' / 'Answer: …' -> '…' (a label the
    rephraser model sometimes writes before its question)."""
    t = s.lstrip()
    low = t.lower()
    cand = None
    if low.startswith("rephrased"):
        rest = t[len("rephrased"):]
        r2 = rest.lstrip()
        if len(r2) < len(rest) and r2.lower().startswith("question"):
            cand = r2[len("question"):]
    if cand is None or not cand.lstrip().startswith(":"):
        if low.startswith("question"):
            cand = t[len("question"):]
        elif low.startswith("answer"):
            cand = t[len("answer"):]
    if cand is not None and cand.lstrip().startswith(":"):
        return cand.lstrip()[1:].lstrip()
    return s

# Words that make a question unambiguously a data (numbers) question — no model
# call needed to route it. Anything else with no strong signal is sent to the
# classifier, which decides DATA vs KNOWLEDGE.
_DATA_HINTS = Matcher(Alt(
    _c01_ph("how many", "count", "total", "sum", "average", "avg", "number of", "per capita",
            "compare", "comparison", "trend", "by district", "by block", "by village", "by year",
            "expenditure", "spend", "spent", "wage", "wages", "sanctioned amount",
            "amount released", "completion rate", "utilisation rate", "utilization rate",
            "success rate", "percent", "per cent", "percentage", "how much"),
    Seq("top", Pred(lambda w: len(w) == 1 and w.isdigit()), sep="space"),
    _c01_chain(["person", ("day", "days")], ["opt1"]),
    Seq("job", W("card", "cards"), sep="space"),
    Seq(W("house", "houses"), W("sanction", "complet", "released", "pending"), sep="space"),
    # Focus Plus / CM Elevate metric nouns — a bare "<scheme> beneficiaries?" /
    # "disbursements?" with no "how many" in front of it used to have no strong
    # signal either way and fell through to the LLM classifier, which guessed
    # KNOWLEDGE for "focus + beneficiaries?" and returned the glossary answer
    # instead of a count (confirmed live 2026-09-11). These are count/amount
    # nouns, not process words, so adding them carries the same low
    # misroute risk as "person-days"/"expenditure" above.
    W("beneficiar", "disburs", prefix=True),
    # EXISTENCE / NAME-LOOKUP questions. "Is there any Producer Group named as
    # Sakania PG?" is a lookup against stored records (the SME use-case bank
    # lists it as answer_route: sql, TC-13) but carries NO counting word, so it
    # matched no DATA cue above and fell through to the LLM classifier, which
    # called it KNOWLEDGE and answered from the reference docs — "no mention of
    # a specific Producer Group named ... in the provided reference material",
    # true of the prose and irrelevant to the question (reported 2026-09-22).
    # The naming word is what keeps these narrow: "is there any eligibility
    # criteria" names nothing and is still KNOWLEDGE.
    Seq(Seq(W("is", "are"), "there", W("any", "a", "an"), sep="space"), _C01CharGap(60, "?\n"),
        Alt(W("named", "called"), _c01_ph("by the name of"),
            Seq("with", Opt("the"), "name", sep="space"))),
    Seq(_c01_chain(["producer", ("group", "groups")], ["opt1"]), W("named", "called"), sep="space"),
    # Same lookup shape using the "PG" abbreviation, which is what users
    # actually type: "is there any pg group with name sakania?", "pg named X".
    # The optional "group" covers the redundant-but-common "pg group".
    Seq(W("pg", "pgs"), Opt("group"),
        Alt(W("named", "called"), Seq("with", Opt("the"), "name", sep="space")), sep="space"),
    Seq(Alt(W("find", "lookup"), _c01_ph("search for", "look up")), Opt(W("the", "a")),
        _c01_chain(["producer", "group"], ["opt1"]), sep="space"),
    # "How did people apply to CM Elevate?" asks for the recorded
    # application_mode breakdown (online vs cmconnectcenter — a real, answerable
    # count), not the application PROCESS ("how do I apply", "how to apply",
    # already a _KNOWLEDGE_HINTS cue). Third-person/past-tense phrasing is the
    # reliable signal that separates the two; the LLM classifier alone picked
    # KNOWLEDGE here and gave a plausible-sounding but unverifiable portal
    # description instead of the real online/cmconnectcenter split (confirmed
    # live 2026-09-11, this exact CM Elevate few-shot question).
    Seq("how", W("did", "do", "does"),
        Alt(W("people", "applicants", "users", "they"), Seq("most", "people", sep="space")),
        "apply", sep="space"),
    Pred(lambda w: w[:2].lower() == "fy" and _c01_is_20dd(w[2:])),
    Seq(W("fy"), _C01Gap(lambda g: g == " "), Pred(_c01_is_20dd)),
    Seq(Pred(_c01_is_20dd), _C01Gap(lambda g: g == "-"), Pred(lambda w: len(w) == 2 and is_int(w))),
    _c01_ph("crore", "lakh", "highest", "lowest", "most", "least"),
    # correlation / cross-metric comparison phrasing — "do districts with high X
    # also have high Y", "is A related to B by district". These are answered by
    # querying and comparing the figures, not from the reference docs.
    _c01_ph("relationship between", "linked to", "linked with", "go together", "hand in hand",
            "track each other", "track together", "move together", "versus"),
    W("correlat", "associat", prefix=True),
    Seq(W("district", "districts", "block", "blocks", "village", "villages"), "where", sep="space"),
    Seq("do", Opt("the"), W("district", "districts"), "with", sep="space"),
    Seq("does", Opt("the"), "district", "with", sep="space"),
    Seq("also", W("high", "low", "higher", "lower", "lead", "leads", "greater", "larger", "smaller",
                  "more", "less"), sep="space"),
))
_KNOWLEDGE_HINTS = Matcher(Alt(
    _c01_ph("what is", "what are", "who is eligible", "eligibility", "how do i", "how to apply",
            "document required", "documents required", "what documents", "explain", "define",
            "meaning of", "component of", "components of", "feature of", "features of",
            "objective", "purpose of", "difference between", "guideline", "guidelines",
            "rule for", "rules for"),
    Seq("when", "was", Rep(ANY, 1, None, lazy=True), "launched"),
))

# "What is the gender split of CM Elevate applicants?" / "what's the workflow
# level breakdown?" both open with the strong _KNOWLEDGE_HINTS cue "what is",
# which used to short-circuit straight to KNOWLEDGE before classify_intent's
# LLM call ever ran. Adding "split"/"breakdown"/"distribution" into _DATA_HINTS
# only removed that false shortcut — it still left the LLM to arbitrate, and it
# guessed KNOWLEDGE for "workflow level breakdown" too (confirmed live
# 2026-09-11: CM Elevate's own headline finding, "female-majority", and its
# online/cmconnectcenter split were both unreachable this way). A "breakdown /
# split / distribution" noun names a computed grouping over real records by
# construction — there is no scheme-mechanics reading of it — so it can force
# DATA outright, the same way _CROSS_SCHEME_SET_QUESTION does below.
_BREAKDOWN_CUE = Matcher(Cap(W("split", "breakdown", "distribution")))

# Same shape of bug as _BREAKDOWN_CUE above, different trigger word: "What is
# the average amount disbursed per beneficiary?" / "What is the total
# disbursed in West Garo Hills?" open with "what is" (a _KNOWLEDGE_HINTS cue)
# AND also match "average"/"total" (a _DATA_HINTS cue), so neither fast-path
# branch fires and it falls to the LLM classifier — which guessed KNOWLEDGE
# for a plain average-per-beneficiary question live (confirmed 2026-09-12: a
# Focus Plus "average disbursed per beneficiary" question got answered from
# the reference docs with a flat ₹5,000 rate instead of the real computed
# average). "What is the average/total/sum/count/number of X" is a computed
# aggregate by construction, never scheme-mechanics — force DATA the same way
# _BREAKDOWN_CUE does.
_METRIC_WHATIS_CUE = Matcher(Seq(
    Seq("what", W("is", "was", "are", "were"), sep="space"), _C01CharGap(40, "\n"),
    Cap(W("average", "avg", "mean", "total", "sum", "number", "count"))))

# The opposite collision: programme-design questions that happen to contain a
# DATA cue. "Who are the intended beneficiaries of CM-ELEVATE?" trips
# "beneficiar..." (any word starting so), and "What is the target number of entrepreneurs under
# CM-ELEVATE?" trips _METRIC_WHATIS_CUE ("what is … number"), so both went down
# the data path — one answered "the data doesn't cover the intended
# beneficiaries", the other asked "which area / year?" for a policy target and
# never stated it (CM Elevate Legacy use-case QA, TC-03 / TC-08, 2026-09-25).
# Who a scheme is FOR and what it AIMS at are design facts in the reference
# docs, never a computed figure — the qualifiers below are what keep this
# narrow ("how many beneficiaries" and "beneficiaries by district" stay DATA).
# KI-076 (CM Elevate reworded probe, 2026-09-27): "Applicants under Goat Farming
# and Warehouse in West Khasi Hills?" has no counting word and no knowledge word,
# so it fell to the LLM classifier, which read it as an eligibility question in 2
# of 3 runs and answered from the reference docs. An applicant/application noun
# scoped to a PLACE is a count over stored records: a capitalised place after
# in/at/from, or any "<name> district/block/village/hills". A knowledge word
# ("eligibility", "documents", "what is") still wins, as with _DATA_HINTS.
_APPLICANT_PLACE_CUE = Matcher(Seq(
    W("applicant", "applicants", "application", "applications", "registration", "registrations"),
    _C01CharGap(80, "?.\n"),
    Alt(
        # a capitalised place after in / at / from (case-sensitive capital)
        Seq(W("in", "at", "from"), Opt("the"),
            Pred(lambda w: len(w) >= 2 and "A" <= w[0] <= "Z" and w[1].isascii() and w[1].isalpha()),
            sep="space"),
        # or any "<name> district / block / village / hills"
        Seq(W("in", "at", "from"), Opt("the"),
            Rep(Pred(lambda w: w[0].isascii() and w[0].isalpha()), 1, 3),
            W("district", "block", "village", "hills"), sep="space"))))
_PROGRAMME_DESIGN_CUE = Matcher(Alt(
    Seq(W("intended", "target", "targeted", "eligible"),
        Alt(W("beneficiar", prefix=True), W("group", "groups", "entrepreneur", "entrepreneurs")),
        sep="space"),
    Seq(W("target", "targeted"), W("number", "figure", "count"), "of", sep="space"),
    Seq(W("entrepreneur", "employment", "job", "outreach"), _C01Gap(_c01_wsdash),
        Opt(Seq("reach", _C01Gap(_c01_ws))), W("target", "targets"))))

# KI-404 (live 2026-10-24): "How does MGNREGA job card registration work?" tripped the
# "job card" DATA cue, matched no knowledge cue, and went down the data path (year
# chips, then an area question). "How does / is <X> work / get issued / processed" and
# "the process / procedure / steps for" ask how the scheme WORKS — never a figure.
# classify_intent applies it only when the question counts nothing and names no year.
_PROCESS_QUESTION_CUE = Matcher(Alt(
    Seq("how", W("does", "do", "is", "are", "can"), _C01CharGap(70, "?.\n"),
        W("work", "works", "working", "processed", "issued", "registered", "verified", "approved",
          "handled", "done", "obtained", "renewed", "released", "paid", "calculated", "selected",
          "allotted", "sanctioned")),
    _c01_ph("what is the process", "what is the procedure", "process for", "process of",
            "procedure for", "procedure to", "steps to", "steps for", "step by step"),
))


class OutOfScope(Exception):
    """Raised when the question is about a place the assistant doesn't cover —
    a district or block that isn't in Meghalaya. The pipeline turns this into
    the standard 'I'm Megh One AI — I only cover Meghalaya's MGNREGA / PMAY-G'
    reply instead of dropping the filter and reporting a meaningless 0."""


class ClarificationNeeded(Exception):
    """Raised when the pipeline cannot safely proceed without one more detail
    from the user. `question` is the thing to ask; `options` (optional) is a
    list of {"label", "question"} the UI renders as one-click replies — each
    `question` is a fully-formed standalone question that resumes the flow.
    `rule` (optional) is a short tag for why we paused (shown in the UI).
    `village_hint` (optional) is the exact village-name text the user typed,
    set only for a village-ambiguity pause — see Session.pending_village_hint
    for why a free-text resume needs it re-supplied deterministically rather
    than trusting the LLM mention-extractor to re-tag it in the merged text."""

    def __init__(self, question: str, *, options: list[dict] | None = None,
                 rule: str | None = None, village_hint: str | None = None):
        super().__init__(question)
        self.question = question
        self.options = options or []
        self.rule = rule
        self.village_hint = village_hint


# ── Follow-up ("what about East Garo Hills?") rewriting ──────────────────────
# A cheap heuristic gates the one extra model call: only questions that read
# like a fragment referring back to the previous turn get rewritten.
# "show me for south garo hills district" / "give me for Ri Bhoi" (live 2026-10-21,
# harness F3): a request verb straight onto the preposition asks for the previous
# question in another scope, exactly as the scheme-swap _SUBSTITUTION_CUE reads it.
# Not a follow-up, it went to SQL with no measure; the 30B guessed an overview or
# dropped the year, three repairs failed and the KB fallback answered "application
# steps". "show me the expenditure for X" names its own measure and stays standalone.
_FOLLOWUP_LEAD = Matcher(Seq(_C01Begin(), Alt(
    _c01_ph("what about", "how about"),
    Seq(_c01_ph("and", "what of", "and for", "also", "ok and", "okay and", "same for", "what if",
                "now", "then"), _C01SpaceNext()),
    Seq(W("give", "show", "get", "fetch"), W("me", "us"), Opt("the"), Opt("same"),
        W("for", "in", "under"), sep="space"))))
_FOLLOWUP_PRONOUN = Matcher(Cap(Alt(
    Seq("this", "one", sep="space"),
    W("it", "its", "that", "those", "these", "them", "they", "there", "this"),
    _c01_ph("the same", "same one"))))
# Something that anchors the question on its own — if present, it's not a fragment.
# Deliberately excludes generic topic words like "documents?", "eligibility?",
# "what is", "who is", "explain": on their own (esp. as a short bare fragment)
# these don't name a scheme or a specific metric, so right after a scheme
# answer "Documents?" / "Eligibility?" reads as a follow-up about THAT scheme,
# not a fresh self-contained question — they used to trip this anchor and get
# judged standalone, which silently dropped the active scheme context.
# "scheme" IS kept as an anchor (unlike those): a fresh, contextless question
# like "Is there any government scheme that can help my family?" uses "that"
# as an ordinary relative pronoun, not a reference to a prior turn, but
# _CONTEXTLESS_REF can't tell the difference — without "scheme" anchoring it,
# this read as a fragment needing prior context and got the "I don't have an
# earlier answer to build on" reply instead of being answered directly (TC-008).
_STANDALONE_ANCHOR = Matcher(Alt(
    W("mgnrega", "mnrega", "nrega", "pmay", "awaas", "expenditure", "house", "houses", "wage", "wages",
      "sanction", "total", "list", "scheme"),
    _c01_chain(["person", ("day", "days")], ["opt1"]),
    Seq("job", W("card", "cards"), sep="space"),
    Seq("how", "many", sep="space")))
# A bare scheme-name fragment — "in MGNREGA?", "for PMAY-G", "and Focus Plus?",
# "what about MGNREGA" — is the canonical scheme-swap follow-up: it reuses the
# whole previous question and only changes the scheme. It trips _STANDALONE_ANCHOR
# (the scheme names are listed there), so without this it is mistaken for a
# self-contained question and the router reads it as "tell me about MGNREGA".
#
# Reported 2026-09-29: "give me for pmay" after "Total MGNREGA person-days in
# 2023-24" was answered with a PMAY-G scheme description (RAG). The request
# verb ahead of the preposition ("give me", "show us the same", "can you get
# me") was not an allowed opening, so the message read as a self-contained
# question naming PMAY-G. The verb carries no scope of its own. "tell me ABOUT
# pmay" still does not match ("about" is not an opening): that one asks what
# the scheme is.
_SCHEME_SWAP_FOLLOWUP = Matcher(Seq(
    _C01Begin(),
    Opt(Alt(Seq(W("ok", "okay"), _C01Gap(lambda g: g.strip() in ("", ","))), Seq("so", _C01_WS0))),
    # "now give me for cm elevate" (live 2026-10-19, KI-330): "now" / "and" ahead
    # of the request verb, not only after it
    Opt(Seq(W("and", "also", "now", "then"), _C01_WS0)),
    Opt(Alt(Seq(W("can", "could", "would", "will"), _C01_WS0, "you", _C01_WS0),
            Seq(W("please", "pls", "kindly"), _C01_WS0))),
    Opt(Seq(W("give", "show", "get", "tell", "fetch", "do"), _C01_WS0,
            Opt(Seq(W("me", "us"), _C01_WS0)), Opt(Seq("the", _C01_WS0)), Opt(Seq("same", _C01_WS0)),
            Opt(Seq(W("thing", "data", "number", "numbers", "figure", "figures", "result", "results"),
                    _C01_WS0)))),
    Opt(Seq(W("and", "also", "now", "then"), _C01_WS0)),
    Opt(Seq(Alt(W("in", "for", "under", "and", "also", "now", "then", "with"),
                Seq("what", _C01_WS0, "about"), Seq("how", _C01_WS0, "about"),
                Seq("what", _C01_WS0, "of"), Seq("same", _C01_WS0, "for"),
                Seq("switch", _C01_WS0, "to"), Seq("change", _C01_WS0, "to")), _C01_WS0)),
    _C01_SWAP_SCHEME, _C01_SWAP_SEP,
    Opt(Seq("scheme", _C01_SWAP_SEP)),
    Opt(Seq(Alt(W("instead", "now", "then", "scheme", "too", "also"), Seq("as", _C01_WS0, "well")),
            _C01_SWAP_SEP)),
    END))
# "same for the remaining schemes" / "give same like for other schemes" / "what
# about the rest of the schemes" — the previous question, asked of every scheme
# it did NOT name. "all schemes" asks it of every scheme. Left to the LLM
# rewrite, "remaining schemes" after a CM Elevate answer became "the remaining
# CM Elevate schemes" (its sub-schemes) and the same answer came back again.
_REST_OF_SCHEMES = Matcher(Alt(
    Seq(Alt(W("remaining", "other"), Seq("rest", "of", Opt("the"), sep="space")),
        W("scheme", "schemes"), sep="space"),
    W("remainingscheme", "remainingschemes", "otherscheme", "otherschemes"),
    Seq("all", Opt("the"), "other", W("scheme", "schemes"), sep="space"),
    Seq("all", Opt("the"), W("others", "remaining"), sep="space")))
_ALL_SCHEMES_FOLLOWUP = Matcher(Seq("all", Opt("the"), Opt(ANY), "schemes", sep="space"))


# A follow-up fragment ("and for 2024-25?", "how launched it?") only means
# something against a real scheme answer. Rewriting it against a greeting,
# off-topic reply, clarification pause or a denial produces a confident bogus
# query — e.g. "how launched it?" right after "what is elon musk?" was being
# turned into a data question. So the previous turn must be one of these.
_ANTECEDENT_ROUTES = ("data", "knowledge")


_SCOPELESS_MAX_WORDS = 8
_SCHEME_WORD = Matcher(W("scheme", "schemes"))


def is_scopeless_followup(question: str, prev: "object") -> bool:
    """A short question that asks only for a MEASURE ("How many beneficiaries
    were there?", "What was the total?") right after a DATA answer. It names no
    scheme, place or year of its own, so its scope can only be the previous
    turn's.

    looks_like_followup() reads "how many" / "total" as anchors of a standalone
    question, so these were answered as fresh, scope-less questions: a year
    pause, or statewide figures (live run 2026-09-26, Scenario A T3). Kept as a
    separate predicate, gated on a DATA antecedent, instead of loosening
    _STANDALONE_ANCHOR, which also decides caching for every question. The
    router's is_cacheable uses this too, so such a turn is never cached."""
    if prev is None or getattr(prev, "route", None) != "data":
        return False
    # A question that names a scheme is never scope-less, the chat's own scheme
    # included (D-061, 2026-10-22): "Which district has the highest beneficiaries
    # in MGNREGA?" after an East Khasi Hills FY 2022-23 MGNREGA answer was kept
    # in East Khasi Hills and 2022-23. It replaces the 2026-10-18 rule that read
    # "What is the total beneficiaries MGNREGA?" as a follow-up on the same scheme.
    return _is_measure_only(question)


def _is_measure_only(question: str, allow_year: bool = False) -> bool:
    """A short request for a measure and nothing else: no scheme, place, year
    or how-the-scheme-works wording ("How many beneficiaries were there?",
    "give me beneficiaries", "What was the total?"). allow_year=True also
    accepts a typed year ("How many in 2023-24?"), which stays in the question."""
    q = (question or "").strip()
    if not q or len(q.split()) > _SCOPELESS_MAX_WORDS:
        return False
    # "What is the total beneficiaries?" opens with the knowledge cue "what is"
    # but asks for a computed aggregate (_METRIC_WHATIS_CUE, the intent rule):
    # UI 2026-10-18, after "Total MGNREGA person-days in 2023-24" it was
    # answered for all six schemes, statewide, all years. A programme-design
    # question ("what is the target number of …") stays knowledge.
    _aggregate = bool(_METRIC_WHATIS_CUE.search(q)) and not _PROGRAMME_DESIGN_CUE.search(q)
    if _SCHEME_WORD.search(q) or _mentions_scheme(q) or (_KNOWLEDGE_HINTS.search(q) and not _aggregate):
        return False
    if _BARE_FOCUS_WORD.search(q):
        return False
    if named_places(q) or (context_policy.extract_year_keys(q) and not allow_year):
        return False
    return bool(context_policy.metric_families(q) or "total" in _c01_tm_words(q))


def _measure_after_knowledge(question: str, prev: "object", allow_year: bool = True) -> bool:
    """A measure-only request right after a KNOWLEDGE answer about one scheme
    ("what is CM Elevate Legacy" -> "give me beneficiaries"). Its only context
    is that scheme — a knowledge turn has no filters — so it needs no model
    rewrite. Live 2026-09-29 the rewrite paraphrased it into "What are the
    beneficiaries of the CM Elevate Legacy scheme?", which then routed to the
    reference docs and listed eligible applicant categories instead of a count.
    WI-2 (forward plan, 2026-10-16): a typed year is allowed — "Who is eligible
    for PMAY-G?" then "How many in 2023-24?" is "How many in 2023-24 under
    PMAY-G?"; it used to be rejected for its year and answered for the old
    topic (MGNREGA, East Khasi Hills)."""
    if not (prev is not None and getattr(prev, "route", None) == "knowledge"
            and len(getattr(prev, "schemes", None) or []) == 1
            and _is_measure_only(question, allow_year=allow_year)):
        return False
    # A measure only another scheme holds picks that scheme's thread instead:
    # "and person-days?" after a PMAY-G eligibility aside is MGNREGA (live
    # 2026-09-29, this shortcut answered "19,058 person-days" from a PMAY-G
    # house count).
    own = set(_infer_scheme_from_terms(question) or [])
    return not own or prev.schemes[0] in own


def _typed_intent(question: str) -> "str | None":
    """DATA / KNOWLEDGE when the user's own words decide it on the keyword fast
    path (the same matchers classify_intent uses), else None. For a follow-up,
    the typed words outrank the model rewrite's phrasing: "give me
    beneficiaries" is a count even when the rewrite reads "What are the
    beneficiaries of…" (a "what are" knowledge cue)."""
    q = question or ""
    if _DATA_HINTS.search(q) and not _KNOWLEDGE_HINTS.search(q):
        return "DATA"
    if _KNOWLEDGE_HINTS.search(q) and not _DATA_HINTS.search(q):
        return "KNOWLEDGE"
    return None
def _is_scheme_term_question(question: str) -> bool:
    """A self-contained "what is <scheme term>?" — "What is SECC?", "What is
    Gram Sabha?", "meaning of muster roll" — naming no scheme and pointing at
    nothing in the previous turn. It is a new question, not a follow-up: the
    rewrite turned "What is DBT?" after an MGNREGA count into a data question
    about MGNREGA bank details (user report 2026-10-14)."""
    q = question or ""
    # "What is the total job cards?" / "What is the total producer groups?"
    # after a data answer asks for a figure, not the meaning of a term (live
    # matrix 2026-10-18: read as a term question, it skipped the follow-up and
    # was answered statewide). An aggregate opener (_METRIC_WHATIS_CUE) is
    # never a definition; a programme-design question ("what is the target
    # number of …") still is.
    if _METRIC_WHATIS_CUE.search(q) and not _PROGRAMME_DESIGN_CUE.search(q):
        return False
    return bool(guardrails._SCHEME_TERM_QUESTION.search(guardrails._normalise(q))
                and not _named_schemes(q) and len(q.split()) <= 8
                and not _CONTEXTLESS_REF.search(q))


# An explicit pointer back to the previous turn's area inside a name lookup.
_NAME_LOOKUP_BACKREF = Matcher(Alt(
    Seq(W("in", "within", "from", "of", "under"), Alt(W("that", "this"), Seq("the", "same", sep="space")),
        W("block", "district", "village", "area", "constituency", "place"), sep="space"),
    Seq(Opt("in"), "there", _C01End("?.!"), sep="space"),
    Seq("same", W("block", "district", "village", "area"), sep="space")))
_CONTEXTLESS_REF = Matcher(Cap(Alt(
    Seq("this", "one", sep="space"),
    W("it", "its", "that", "those", "these", "them", "they", "this"))))
# "Households THAT completed 100 days of work in Ri Bhoi" — a relative "that"
# (a noun, then "that" + a verb) points at nothing earlier; it was answered "I
# don't have an earlier answer to build on" (hierarchy matrix run 2026-10-14).
_RELATIVE_THAT = Matcher(Seq(
    _C01Gap(_c01_ws),
    After(W("that", "which", "who"), Pred(lambda w: w[-1].isascii() and w[-1].isalpha())),
    _C01Gap(_c01_ws),
    Before(Seq(), Alt(
        W("have", "has", "had", "complete", "completed", "received", "got", "get", "are", "were", "is",
          "was", "did", "do", "does", "crossed", "took", "take", "applied"),
        W("start", "begin", "exceed", "show", "record", "hold", "benefit", "work", "fall", "lie",
          "belong", prefix=True)))))


def _mentions_scheme(question: str) -> bool:
    return any(p.search(question or "") for p in _SCHEME_NAME_MATCHER.values())


# ── Scheme substitution ─────────────────────────────────────────────────────
# "give me same for mgnrega" after "how many beneficiaries in Focus Plus ...":
# the SAME operation on another scheme. Reported live 2026-09-26: the message
# names a scheme, so looks_like_followup() declared it a self-contained question
# (the _mentions_scheme check below). _SCHEME_SWAP_FOLLOWUP only knew a fixed set
# of opening words, and "give me" was not one of them. The intent classifier
# then saw the bare words with no context, returned KNOWLEDGE, and the user got
# general MGNREGA information instead of the MGNREGA beneficiary count.
#
# Generic by construction: the schemes come from _SCHEME_NAME_MATCHER (the
# registry every other scheme check uses), and the continuation phrases are
# scheme-agnostic. A new scheme needs nothing here.
_SUBSTITUTION_CUE = Matcher(Alt(
    W("same", "repeat", "likewise", "similarly", "instead"),
    Seq("do", W("it", "this", "that"), sep="space"),
    Seq(W("what", "how"), "about", sep="space"),
    Seq("what", "of", sep="space"),
    Seq(W("now", "and", "also", "this", "then"), "for", sep="space"),
    Seq(W("switch", "change"), "to", sep="space"),
    # "give me for pmay please" (2026-09-29): a request verb straight onto the
    # preposition asks for the previous operation. Not "tell me about".
    Seq(W("give", "show", "get", "tell", "fetch"), W("me", "us"), Opt("the"), Opt("same"),
        W("for", "in", "under"), sep="space")))
# "same" is an explicit reference to the previous OPERATION. Only with it may a
# substitution also carry changes of its own ("same for MGNREGA in 2023-24").
# A weaker cue ("what about MGNREGA eligibility?") keeps today's reading.
_STRONG_SUBSTITUTION_CUE = Matcher(Alt(
    W("same", "repeat", "likewise", "similarly"),
    Seq("do", W("it", "this", "that"), sep="space")))
# Words that carry no scope of their own in a substitution request. If nothing
# but these, the cue and one scheme name remain, the message is a PURE
# substitution: every other part of the previous question stays as it was.
# The filler WORDS; the filler punctuation (,.!?;:&+/-) is _C01_FILLER_PUNCT.
_SUBSTITUTION_FILLER = Matcher(W(
    "give", "show", "tell", "get", "run", "do", "repeat", "me", "us", "the", "a", "an", "same", "thing",
    "things", "query", "question", "one", "it", "this", "that", "please", "pls", "kindly", "can",
    "could", "would", "you", "now", "and", "also", "then", "for", "in", "under", "of", "on", "what",
    "how", "about", "with", "instead", "likewise", "similarly", "switch", "change", "to", "scheme",
    "number", "numbers", "figure", "figures", "result", "results", "answer", "data", "info",
    "information", "details", "too", "as", "well", "again", "ok", "okay"))


def _scheme_substitution(question: str) -> "tuple[str | None, bool]":
    """(scheme, pure) when `question` asks for the previous operation on ONE
    named scheme, else (None, False). `pure` is True when nothing else is asked:
    no new metric, place, year or breakdown. The scheme is a
    _SCHEME_NAME_MATCHER key, or "Focus" for a bare "focus", which names
    neither Focus scheme and is left to the which-Focus pause, exactly as
    _scheme_swap_rewrite does."""
    q = (question or "").strip()
    if not q or len(q.split()) > 16 or not _SUBSTITUTION_CUE.search(q):
        return None, False
    named = sorted(_exact_schemes(q))
    residue = q
    for s in named:
        residue = _SCHEME_NAME_MATCHER[s].sub(" ", residue)
    if not named and _BARE_FOCUS_WORD.search(q):
        named, residue = ["Focus"], _BARE_FOCUS_WORD.sub(" ", residue)
    if len(named) != 1:
        return None, False
    return named[0], not keep_chars(_SUBSTITUTION_FILLER.sub(" ", residue),
                                 lambda c: c not in _C01_FILLER_PUNCT, " ").strip()


def is_scheme_substitution(question: str, prev: "object") -> bool:
    """True when `question` swaps the previous turn's scheme for another one
    and otherwise continues that turn: a pure substitution, or a "same"-cued
    one with changes of its own. Needs a data or knowledge antecedent. Naming
    the scheme the previous turn was already about is not a substitution.
    Used by the turn stages (to treat it as a follow-up) and by the router's
    is_cacheable (it only means something inside its own conversation)."""
    if prev is None or getattr(prev, "route", None) not in _ANTECEDENT_ROUTES:
        return False
    if _is_same_comparison_question(question):
        return False
    target, pure = _scheme_substitution(question)
    if not target or target in (getattr(prev, "schemes", None) or []):
        return False
    return pure or bool(_STRONG_SUBSTITUTION_CUE.search(question or ""))


# KI-301: "what is its role in PMAY-G?" right after "What is Gram Panchayat?".
# The question names a scheme, so looks_like_followup calls it self-anchoring,
# and the rephraser (which sees no previous turn) made it "the role of a
# government data assistant in PMAY-G". A referring pronoun beside a scheme name
# points at the TERM the previous knowledge question asked about.
_C01_REFERRING_PRONOUN = Matcher(W("it", "its", "they", "their", "them"))


def pronoun_refers_to_previous_term(question: str, prev: "object") -> bool:
    """A question naming a scheme whose it/its/they/their/them points back at the
    term of the previous KNOWLEDGE question, which named no scheme. Then it is a
    follow-up after all, and the rewrite resolves the pronoun against that term."""
    if prev is None or getattr(prev, "route", None) != "knowledge":
        return False
    if not _mentions_scheme(question or "") or not _C01_REFERRING_PRONOUN.search(question or ""):
        return False
    prev_q = getattr(prev, "raw_question", None) or getattr(prev, "question", "") or ""
    return bool(prev_q) and not _named_schemes(prev_q)


# Words that open a message without saying anything. "okay give me for East Khasi
# Hills" right after a PMAY-G answer was read as a new question and asked "which
# scheme?" (live 2026-10-18): the "okay" hid the "give me for …" lead.
_C01_OPENING_FILLERS = frozenset("ok okay k so hmm hm alright yes yeah yep sure fine please pls".split())


def _c01_strip_opening_fillers(q: str) -> str:
    words_ = q.split()
    while len(words_) > 1 and words_[0].lower().strip(",.!") in _C01_OPENING_FILLERS:
        words_ = words_[1:]
    return " ".join(words_)


def _is_same_comparison_question(question: str) -> bool:
    """"Same comparison for CM Elevate Legacy: beneficiaries and amount" — what
    _comparison_swap writes, and what the CM Elevate dataset chips carry. It names
    its scheme and its measures in full: a standalone question. Tapped as a chip it
    was read as a "same"-cued substitution and the model rewrote it back into a
    two-scheme comparison (live 2026-10-19 15:44)."""
    q = (question or "").strip()
    return q.lower().startswith("same comparison for ") and ":" in q


def looks_like_followup(question: str) -> bool:
    q = _c01_strip_opening_fillers(question.strip())
    if len(q.split()) > 12 or _is_same_comparison_question(q):
        return False
    # "in MGNREGA?" / "for PMAY-G" / "and Focus Plus?" — a scheme-swap fragment.
    # Checked before _STANDALONE_ANCHOR, which would otherwise veto it because it
    # names a scheme.
    if _SCHEME_SWAP_FOLLOWUP.match(q):
        return True
    # "give me same for mgnrega", "do the same for PMAY-G", "same thing for CM
    # Elevate Legacy": the same scheme swap with any continuation wording, not
    # only the openings _SCHEME_SWAP_FOLLOWUP lists. A pure substitution names
    # nothing but the scheme, so it cannot stand on its own either.
    if _scheme_substitution(q) != (None, False) and _scheme_substitution(q)[1]:
        return True
    # "same for the remaining schemes" — names no scheme of its own, so it
    # only means something against the previous question.
    if _REST_OF_SCHEMES.search(q) and not _mentions_scheme(q):
        return True
    # "pick any scheme and explain" — its answer depends on what THIS
    # conversation has already covered, so it must never be served from the
    # shared response cache (which skips follow-ups).
    if _is_scheme_pick_request(q):
        return True
    # A recommendation may draw the user's profile from earlier turns, and a
    # "why did you choose X?" is about the previous answer — both depend on
    # this conversation, so neither may be served from the shared cache.
    if _WHY_CHOICE.search(q) or _is_recommendation_request(q):
        return True
    if _FOLLOWUP_LEAD.search(q):
        return True
    # A question that names its own scheme outright is self-anchoring, same as
    # _STANDALONE_ANCHOR's "scheme"/"mgnrega"/"pmay" entries — but that matcher
    # predates Focus Plus/CM Elevate and was never extended to them, so "What
    # benefits will I get under this Focus Plus" tripped _FOLLOWUP_PRONOUN on
    # "this", found no anchor, and got rewritten against the PREVIOUS turn's
    # scheme (e.g. "...compared to PMAY-G?") even though it names its own
    # scheme in full. _mentions_scheme covers all four schemes without having
    # to keep two scheme-name lists in sync.
    if _mentions_scheme(q):
        return False
    # "is there any producer group named Sakania PG?" — a NAME LOOKUP is
    # self-contained: a group name identifies the group statewide. The "there"
    # of "is there" tripped _FOLLOWUP_PRONOUN, the rewrite glued on the previous
    # turn's place ("...named Sakania PG in Betasing block"), and the lookup
    # answered a false "no such group" for a group that exists in East Khasi
    # Hills (reported live 2026-09-25). Only an explicit pointer back ("in that
    # block", "...named X there?") keeps it a follow-up.
    if (_PG_NAMED_ENTITY.search(q) or _GROUP_NAME_LOOKUP.search(q)) \
            and not _NAME_LOOKUP_BACKREF.search(q):
        return False
    if _FOLLOWUP_PRONOUN.search(q) and not _STANDALONE_ANCHOR.search(q):
        return True
    # A bare fragment ("in East Garo Hills", "by block") with no anchor of its own.
    return len(q.split()) <= 6 and not _STANDALONE_ANCHOR.search(q)


def _scheme_swap_rewrite(prev_question: str, followup: str) -> "str | None":
    """Deterministic rewrite for a bare scheme-swap follow-up ("in MGNREGA?",
    "what about PMAY-G?"). Substitutes the follow-up's scheme for the one named
    in the previous question, so the intent ("same question, other scheme") is
    preserved exactly. The LLM rewrite tends to *append* the new scheme instead
    of replacing the old one ("... in Focus Plus ... in MGNREGA?"), which then
    reads as a cross-scheme question. Returns None if the fragment names no
    scheme or the previous question can't be adapted — the caller falls back to
    the LLM path."""
    if not (_SCHEME_SWAP_FOLLOWUP.match((followup or "").strip())
            or _scheme_substitution(followup)[1]):
        return None
    target = next((name for name, pat in _SCHEME_NAME_MATCHER.items()
                   if pat.search(followup)), None)
    # A bare "focus" names neither Focus scheme: carry the word itself into the
    # question, so the "which Focus?" pause (_is_ambiguous_focus) asks rather
    # than this rewrite guessing one.
    label = target or ("Focus" if _BARE_FOCUS_WORD.search(followup or "") else None)
    if not label or not prev_question:
        return None
    compared = _comparison_swap(prev_question, followup, target, label)
    if compared:
        logger.info("follow-up scheme-swap (comparison): %r + %r -> %r", prev_question, followup, compared)
        return compared
    out = prev_question
    replaced = False
    for name, pat in _SCHEME_NAME_MATCHER.items():
        if name == target:
            continue
        if pat.search(out):
            out = pat.sub(label, out)
            replaced = True
    if not replaced:
        if target and _SCHEME_NAME_MATCHER[target].search(out):
            return out  # previous question was already about the target scheme
        out = f"{out.rstrip(' ?.')} for {label}"
    out = _c01_tidy_space(out, ",", collapse=False).strip()
    logger.info("follow-up scheme-swap: %r + %r -> %r", prev_question, followup, out)
    return out


# ── A follow-up that is only a place ────────────────────────────────────────
# User report 2026-10-21: after "How much PMAY-G amount was released in East
# Garo Hills in FY 2023-24?", "in ambare ading" (a village, typed without the
# word "village") was declined as off-topic. Recognising the place fixed that,
# but the rewrite model then did what it liked with a bare name: "what about
# danak dopgre" became "... for the Danak Dopgre tranche" (Focus Plus, the
# district total answered again), "dangar dombah" became "Dargar Dombah", and
# "wapung" (an East Jaintia Hills block) came back as East Khasi Hills. A
# follow-up that names one place and nothing else means "the same question for
# that place": the previous question with its place swapped, written here. The
# level word goes in only when the name has exactly one level; a name that is a
# block AND a village (Mawlai, Rajabala) goes in bare, so the level pause asks.
_C01_PLACE_ONLY_WORDS = frozenset(
    "IN FOR AT OF FROM WITHIN WHAT ABOUT HOW AND NOW THEN OK OKAY ALSO SAME SO THE PLEASE "
    "SHOW GIVE TELL ME IT THIS VILLAGE BLOCK CONSTITUENCY AC DISTRICT".split())
_C01_LEVEL_WORD = {"village": "village", "block": "block", "assembly_constituency": "constituency"}
_C01_TYPED_LEVEL = {"VILLAGE": "village", "BLOCK": "block", "CONSTITUENCY": "constituency",
                    "AC": "constituency", "DISTRICT": "district"}
_C01_LEVEL_TAIL = ("village", "block", "district", "constituency", "ac")
_C01_STATEWIDE_PHRASES = (" for all of Meghalaya", " across all of Meghalaya", " in all of Meghalaya",
                          " across Meghalaya", " in Meghalaya", " for Meghalaya", " (statewide)",
                          " statewide", " across the state", " for the whole state")


# A breakdown no finer than the new place means nothing there: "How many PMAY-G
# houses were completed by district for FY 2019-20" + "give me for dalu" became
# "... completed by district in Dalu, West Garo Hills ..." (user, live
# 2026-10-21 18:18, KI-346). Longest first, so "by districts" is not left as "s".
# The verb the rewrite hangs on the breakdown goes with it, longest first: "…
# across all financial years, shown by block" lost only "by block" and asked
# "…, shown?" for a village (live 2026-10-21).
_C01_BREAKDOWN_LEAD = (", shown", ", broken down", ", split", " shown", " broken down", " split", "")
_C01_BREAKDOWN_AT = {
    level: tuple(lead + phrase for lead in _C01_BREAKDOWN_LEAD for phrase in phrases)
    for level, phrases in {
        "district": (" for each district", " in each district", " by districts", " by district",
                     " per district", " district-wise", " district wise", " districtwise"),
        "block": (" for each block", " in each block", " by blocks", " by block", " per block",
                  " block-wise", " block wise", " blockwise"),
    }.items()
}
_C01_BREAKDOWNS_DROPPED = {"block": ("district",), "assembly_constituency": ("district",),
                           "village": ("district", "block")}


_C01_CHIP_LEVEL_WORDS = ("assembly constituency", "constituency", "district", "village", "block")
_C01_CHIP_LEVEL_TAILS = tuple(
    f", the {w}, not {tail}" for w in _C01_CHIP_LEVEL_WORDS
    for tail in ("another area type", *(f"the {x}" for x in _C01_CHIP_LEVEL_WORDS if x != w)))


def _c01_strip_chip_level(text: str, keep_if_in: str = "") -> str:
    """`text` without a level chip's tail (", the block, not another area type",
    ", the village, not the block") unless `keep_if_in` holds it. That tail
    states the level of the place its chip was about; carried into the next
    question it re-labels a DIFFERENT place: "Total sanctioned amount in Rasong."
    after a Chokpot block chip became "... in Rasong for MGNREGA, the block, not
    another area type ..." (Rasong is a village; user, live 2026-10-21, KI-348)."""
    for tail in _C01_CHIP_LEVEL_TAILS:
        if _ci_find(keep_if_in or "", tail) >= 0:
            continue
        p0 = _ci_find(text, tail)
        while p0 >= 0:
            text = text[:p0] + text[p0 + len(tail):]
            p0 = _ci_find(text, tail)
    return text


def _c01_drop_coarser_breakdown(text: str, dim: str) -> str:
    for level in _C01_BREAKDOWNS_DROPPED.get(dim, ()):
        for phrase in _C01_BREAKDOWN_AT[level]:
            p0 = _ci_find(text, phrase)
            end = p0 + len(phrase)
            if p0 >= 0 and (end == len(text) or not text[end].isalnum()):
                text = text[:p0] + text[end:]
                break
    return text


def _c01_place_span(text: str, typed: str) -> "tuple[int, int] | None":
    """Span of "<prep> <name>" (or ", <name>") in `text`, with a following level
    word ("village", "block", …) taken too; None when the name is not there."""
    sp = _c07_place_phrase_span(text, typed, _C07_DROP_PREPS, word_end=True)
    if sp is None:
        p = _ci_find(text, typed)
        if p < 0:
            return None
        k = p
        while k > 0 and text[k - 1].isspace():
            k -= 1
        if k == 0 or text[k - 1] != ",":
            return None
        sp = (k - 1, p + len(typed))
    e = sp[1]
    j = _ws_run_end(text, e)
    for w in _C01_LEVEL_TAIL:
        if text[j:j + len(w)].lower() == w and (j + len(w) >= len(text) or not text[j + len(w)].isalnum()):
            e = j + len(w)
            break
    return sp[0], e


def _place_swap_rewrite(prev: "object", followup: str, force: bool = False,
                        district: bool = False) -> "str | None":
    """The previous DATA question asked again for the one place `followup`
    names (village, block or constituency; districts stay with the model
    rewrite, D-056), or None to fall back to it. See the note above.
    `force`: also a block inside the chat's district — used when the model's
    rewrite of it was rejected (KI-347). `district`: also a district — used when
    the model's rewrite kept the old, finer place (KI-358)."""
    from app.entity_resolver import place_levels, place_mentions, place_only, village_districts
    prev_q = getattr(prev, "question", "") or ""
    if not prev_q or getattr(prev, "route", None) != "data":
        return None
    only = place_only(followup, _C01_PLACE_ONLY_WORDS)
    if not only or (only[1] == "district" and not district):
        return None
    name, dim, typed = only
    # "What about Rongara block?" — the level word with its "?" is still the level
    # (RONGARA is a block AND a constituency; PMAY-G sheet run 2026-10-22)
    words = {w.strip("?.,!;:") for w in fold(followup).split()}
    stated = next((_C01_TYPED_LEVEL[w] for w in words if w in _C01_TYPED_LEVEL), None)
    levels = place_levels(typed)
    if stated:
        level = stated
    elif len(levels) == 1:
        level = _C01_LEVEL_WORD.get(next(iter(levels)))
    else:
        level = None                       # same name at 2+ levels: the gate asks
        # ...unless the chat's remembered block / district settles it, by the
        # gate's own rule (PLACE_GAZETTEER, D-059). After West Khasi Hills,
        # "what about Mawlai?" was swapped to "Mawlai, East Khasi Hills" (the
        # block's district) although the Mawlai village lies in West Khasi
        # Hills; after Shallang block the model rewrite wrote "Mawlai block"
        # although the Mawlai village lies in Shallang (2026-10-21).
        if settings.PLACE_GAZETTEER and "village" in levels:
            _readings = {lv: (name if lv != "village" else "") for lv in levels
                         if lv in ("block", "assembly_constituency", "village")}
            _settled = _c09_gazetteer_settle(
                typed, _readings, (getattr(prev, "schemes", None) or [""])[0],
                getattr(prev, "resolved_entities", None))
            if list(_settled) == ["village"]:
                level, dim = "village", "village"
    prev_district = str((getattr(prev, "resolved_entities", None) or {}).get("district") or "").upper()
    # A block inside the chat's district is left to the model rewrite, which
    # handles it (tests/test_context_semantic_state.py); one in another district
    # was rewritten back to the old district ("wapung").
    if dim == "block":
        _resolved = getattr(prev, "resolved_entities", None)
        _parent = block_parent_district(name)
        if _resolved is None or not _parent:
            return None
        if not force and (_parent == prev_district
                          or (not prev_district and (_resolved.get("block") or _resolved.get("village_code")))):
            return None
    keep_district = bool(prev_district) and (
        (level == "village" and prev_district in village_districts(typed))
        or (level == "block" and dim == "block" and block_parent_district(name) == prev_district))
    out, at = _c01_drop_coarser_breakdown(_c01_strip_chip_level(prev_q, followup), dim), None
    for pname, pdim in sorted(place_mentions(out).items(), key=lambda kv: kv[1] == "district"):
        if pdim == "district" and keep_district:
            continue
        sp = None
        for form in (pname, pname.title()):
            sp = _c01_place_span(out, form)
            if sp:
                break
        if sp is None:
            return None                    # cannot find the old place: let the model rewrite
        # EVERY copy goes: "... in Rasong village under PMAY-G in Rasong village in
        # Mawkynrew block ..." + "what about Chokpot?" kept the second Rasong and
        # answered it again (KI-348).
        while sp is not None:
            if at is None:
                at = sp[0]                 # the new place goes where the first old one was
            elif sp[0] < at:
                at -= sp[1] - sp[0]
            out = out[:sp[0]] + out[sp[1]:]
            sp = _c01_place_span(out, pname) or _c01_place_span(out, pname.title())
    phrase = f" in {_place_title(typed)}" + (f" {level}" if level else "")
    # Only a name that IS that block (one level, or stated) names the block's
    # district: "in Mawlai" (block, constituency AND village) became "Mawlai,
    # East Khasi Hills" and the West Khasi Hills village was answered under that
    # label instead of asking which Mawlai (KI-348).
    if dim == "block" and not keep_district and level == "block":
        # A block of another district names its own (KI-327: "Dambo Rongjeng
        # block, East Garo Hills" after a West Garo Hills village).
        phrase += f", {_place_title(block_parent_district(name))}"
    if at is None:
        # A statewide question narrows to the place: its "statewide" goes.
        for whole in _C01_STATEWIDE_PHRASES:
            p0 = _ci_find(out, whole)
            if p0 >= 0:
                out, at = out[:p0] + out[p0 + len(whole):], p0
                break
    if at is not None:
        out = out[:at] + phrase + out[at:]
    elif keep_district:
        sp = _c01_place_span(out, prev_district.title()) or _c01_place_span(out, prev_district)
        if sp is None:
            return None
        out = out[:sp[0]] + phrase + out[sp[0]:]
    else:
        stem = out.rstrip(" ?.")
        cut = next((i for i in (_ci_find(stem, " in FY"), _ci_find(stem, " for FY"),
                                _ci_find(stem, " during")) if i >= 0), len(stem))
        out = stem[:cut] + phrase + stem[cut:] + "?"
    out = _c01_tidy_space(_c07_double_comma(out), ",?.").strip()
    logger.info("follow-up place-swap: %r + %r -> %r", prev_q, followup, out)
    return out


# ── A scheme swap after a cross-scheme comparison ───────────────────────────
# Live 2026-10-19 15:08: "Compare PMAY-G and MGNREGA beneficiaries in a graph for
# Meghalaya (statewide), all financial years" then "now give me for cm elevate".
# The swap replaced EACH compared scheme with the new one — "Compare CM Elevate and
# CM Elevate beneficiaries ..." — the dataset chip then made both "CM Elevate
# applications", and the answer lost the comparison it came from. The compared
# schemes are one list: a swap replaces the whole list with the new scheme ("CM
# Elevate beneficiaries in a graph for ..."); "and X" / "X too" / "add X" adds X
# to the list instead.
_C01_LIST_JOINERS = frozenset("and & , vs vs. versus with or /".split())
_C01_ADD_CUES = frozenset("and also too add include including plus".split())
_C01_COMPARE_LEADS = ("compare ", "comparison of ", "comparing ")


def _comparison_swap(prev_question: str, followup: str, target: "str | None", label: str) -> "str | None":
    """The rewritten question when `prev_question` compares two or more schemes
    named as one list ("Compare PMAY-G and MGNREGA ..."), else None."""
    hits = sorted((h.start(), h.end(), name) for name, pat in _SCHEME_NAME_MATCHER.items()
                  for h in pat.finditer(prev_question))
    names = [n for _, _, n in hits]
    if len(set(names)) < 2 or len(names) != len(set(names)):
        return None
    # the names must sit side by side, joined only by "and" / "," / "vs" ...
    for (_, end, _), (start, _, _) in zip(hits, hits[1:]):
        gap = prev_question[end:start].replace(",", " , ").split()
        if any(w.lower() not in _C01_LIST_JOINERS for w in gap):
            return None
    lo, hi = hits[0][0], hits[-1][1]
    head, tail = prev_question[:lo], prev_question[hi:]
    # the cue words, read with the scheme names taken out ("Focus Plus" is no "plus")
    bare = followup or ""
    for pat in _SCHEME_NAME_MATCHER.values():
        bare = pat.sub(" ", bare)
    fwords = {w.strip(",.?!").lower() for w in bare.split()}
    # one of the compared schemes named again narrows the comparison to it
    if target not in names and (fwords & _C01_ADD_CUES or "as well" in bare.lower()):
        listed = [prev_question[s:e] for s, e, _ in hits] + [label]
        return _c01_tidy_space(f"{head}{', '.join(listed[:-1])} and {listed[-1]}{tail}", ",",
                               collapse=False).strip()
    low = head.lower()
    lead = next((c for c in _C01_COMPARE_LEADS if low.startswith(c)), None)
    if lead is not None:
        # "Same comparison for X: ..." is the comparison card for X alone
        # (cross_scheme.detect), in the comparison's own scope: every other path
        # re-asked what the comparison had settled ("which year?" for Focus Plus)
        # or paused on a measure the card simply marks as not recorded.
        rest = head[len(lead):]
        if rest.lower().startswith("both "):
            rest = rest[len("both "):]
        return _c01_tidy_space(f"Same comparison for {label}: {rest}{tail.lstrip()}", ",",
                               collapse=False).strip()
    if low.endswith("both "):
        head = head[:-len("both ")]
    return _c01_tidy_space(f"{head}{label}{tail}", ",", collapse=False).strip()


# ── CTX-07: two follow-ups the model rewrite got wrong, done deterministically ──
# KI-363 (live): "Break it down by district" after a statewide answer was rewritten
# "... for all districts in Meghalaya ..." and answered with the statewide total
# again. The chip the app itself offers after a statewide figure ("Break that down
# by district", c15 _c15_chips) went the same way. A message that asks ONLY for a
# breakdown of a statewide answer is that question by the dimension: the same stem
# the complaint path already builds ("why are you not giving it district-wise?",
# c15 _meta_question). A breakdown inside a place keeps the place, so it is left to
# the rewrite and its merge plan.
# KI-364 (live; reproduced offline 2026-10-29): "Compare the number of beneficiaries
# with Ri Bhoi" after an East Khasi Hills answer was not read as a follow-up (none of
# the follow-up detectors knows "compare ... with <place>", though turn_kind does) and
# was answered for Ri Bhoi alone. A comparison keeps the place the officer was on
# and adds the named one, in the previous question's own measure, scheme and year:
# "Compare how many PMAY-G beneficiaries are there in East Khasi Hills and Ri Bhoi in
# FY 2023-24?". Not a place SWAP, which D-056 leaves to the model ("what about Ri
# Bhoi?" replaces the place): only an explicit compare cue, exactly one new place at
# the previous place's own level, and nothing else changed (no scheme, year or other
# measure), so the D-056 swap path never sees one of these.

def _c01_ctx07_breakdown_question(raw_question: str, prev) -> "str | None":
    """"Break it down by district" / "district wise" right after a STATEWIDE data
    answer -> the previous question by that dimension, else None."""
    if getattr(prev, "route", None) != "data" or not getattr(prev, "question", None):
        return None
    resolved = getattr(prev, "resolved_entities", None) or {}
    if any(resolved.get(k) for k in ("district", "block", "village", "assembly_constituency")):
        return None
    dim = _c15_breakdown_dimension(raw_question or "")
    if not dim:
        return None
    stem = _c05_statewide_stem(prev.question)
    return f"{stem} by {dim}" if stem else None


def _c01_ctx07_compare_place_question(raw_question: str, prev) -> "str | None":
    """"Compare ... with Ri Bhoi" right after a data answer for another place at the
    same level -> the previous question for both places, else None."""
    from app.entity_resolver import place_mentions
    if getattr(prev, "route", None) != "data" or not getattr(prev, "question", None):
        return None
    q = raw_question or ""
    if not (_C15_COMPARE_CUES & set(_c15_words(q))):
        return None
    if context_policy.extract_year_keys(q):
        return None                                   # a new year too: left to the rewrite
    prev_schemes = set(getattr(prev, "schemes", None) or [])
    if set(_named_schemes(q)) - prev_schemes:
        return None                                   # another scheme: a scheme comparison
    places = place_mentions(q)
    if len(places) != 1:
        return None
    new, dim = next(iter(places.items()))
    resolved = getattr(prev, "resolved_entities", None) or {}
    old = resolved.get(dim) if dim in ("district", "block") else None
    if not old or str(old).upper() == new:
        return None
    # The measure, when named, must be the previous one.
    named_metric = context_manager.detect_metric(q)
    if named_metric and named_metric != context_manager.detect_metric(prev.question):
        return None
    own = context_policy.metric_families(q)
    if own and not own <= context_policy.metric_families(prev.question):
        return None
    pair = f"{str(old).title()} and {new.title()}" + (" blocks" if dim == "block" else "")
    # Through a placeholder: _c15_swap_place tries every form of the old name in
    # turn, and the pair still contains it ("Mawphlang block" -> "Mawphlang and
    # Mylliem blocks", then "Mawphlang" again).
    marker = "\x00"
    both = _c15_swap_place(prev.question, str(old), marker)
    if not both or marker not in both:
        return None
    both = both.replace(marker, pair)
    first = both.split(" ", 1)[0]
    if first[:1].isupper() and first[1:].islower():
        both = both[:1].lower() + both[1:]
    return f"Compare {both}"


# ── A scheme swap that carries a measure the new scheme does not hold ───────
# Reported 2026-09-29: "give me for pmay" after "Total MGNREGA person-days in
# 2023-24" rewrote, correctly, to "Total PMAY-G person-days in 2023-24". But
# PMAY-G records no person-days. The generator wrote four queries, the
# resolved-scope guard rejected all four, and the user got "couldn't build a
# working query". "wage expenditure" swapped to PMAY-G was answered as the
# amount released, a different measure, without saying so.
#
# The swap keeps the previous operation, and that is right when the new scheme
# has the measure. When the measure belongs to one scheme only, the answer is
# to say so and offer the new scheme's own measures for the same scope, one
# tap each. Never a guess at the "closest" measure. Scheme-specific measures
# only: money and counts exist in every scheme and are left to the generator.
# SCHEME_METRICS (schema_context) is the source for what each scheme holds.
_SCHEME_OWN_MEASURES: "dict[str, list[tuple[str, Matcher]]]" = {
    "MGNREGA": [
        ("person-days", Matcher(Alt(_c01_chain(["person", ("day", "days")], ["opt1"]),
                                    _c01_chain(["man", ("day", "days")], ["opt1"]),
                                    _c01_chain(["100", ("day", "days")], ["opt1"])))),
        ("job cards", Matcher(_c01_chain(["job", ("card", "cards")], ["opt1"]))),
        ("wage expenditure", Matcher(W("wage", "wages"))),
        ("material expenditure", Matcher(Seq("material", W("expenditure", "cost", "spend", prefix=True),
                                             sep="space"))),
        ("employment", Matcher(Alt(
            Seq(W("household", "households", "person", "persons", "people", "women"), Opt("were"),
                "employed", sep="space"),
            W("employment")))),
    ],
    "PMAY-G": [
        ("houses", Matcher(Alt(W("house", "houses", "plinth"),
                               Seq("housing", W("unit", "units"), sep="space"),
                               _c01_chain(["roof", "cast"], ["opt1"])))),
    ],
}
# What to offer instead, per scheme: (chip label, question with a {scope}
# slot). Each is a question the scheme's own use cases answer.
_SCHEME_HEADLINE_OFFERS: "dict[str, list[tuple[str, str]]]" = {
    "MGNREGA": [("Person-days", "Total MGNREGA person-days{scope}"),
                ("Households employed", "How many households were employed under MGNREGA{scope}?"),
                ("Total expenditure", "Total MGNREGA expenditure{scope}")],
    "PMAY-G": [("Houses sanctioned", "How many PMAY-G houses were sanctioned{scope}?"),
               ("Houses completed", "How many PMAY-G houses were completed{scope}?"),
               ("Amount released", "How much PMAY-G amount was released{scope}?")],
    "Focus Plus": [("Disbursements", "How many Focus Plus disbursements were made{scope}?"),
                   ("Amount disbursed", "How much was disbursed under Focus Plus{scope}?")],
    "Focus Legacy": [("Producer groups paid",
                      "How many producer groups were paid under Focus Legacy{scope}?"),
                     ("Amount disbursed", "How much was disbursed under Focus Legacy{scope}?")],
    "CM Elevate": [("Applications", "How many CM Elevate applications were received{scope}?"),
                   ("Valid applications",
                    "How many CM Elevate applications were verified Valid{scope}?")],
    "CM Elevate Legacy": [("Sanctioned amount",
                           "What is the total sanctioned amount under CM Elevate Legacy{scope}?"),
                          ("Total disbursed",
                           "What is the total amount disbursed under CM Elevate Legacy{scope}?")],
}
# CM Elevate (applications) records no financial year at all (SCHEME_METRICS),
# so a carried year is left out of its offers rather than paused on again.
_SCHEMES_WITHOUT_YEAR = {"CM Elevate"}


# ── A measure the chosen scheme does not record, however it was asked ──────
# Reported 2026-10-06: "Give me person days in Mawlwai for Focus Plus across
# all financial years" was answered "Mawlai block recorded 12 person days for
# Focus Plus". The SQL model wrote SELECT COUNT(*) AS person_days FROM
# curated.v_focus_plus: 12 PAYMENTS, renamed to the measure the user asked
# for. The verifier passed it (valid SQL, right block) and the composer wrote
# the alias as the measure. _swap_measure_gap covers one shape only (a scheme
# swap that CARRIED the measure over); a measure typed together with a scheme
# that does not hold it went straight to the generator.
#
# Two guards, every scheme, every turn shape:
#   1. _measure_not_held_gap, in _data_scheme_stage (before entities and SQL):
#      a measure no chosen scheme records -> say so, name the scheme(s) that
#      do record it, and offer the chosen scheme's own measures. Never a
#      different figure in its place.
#   2. _sql_measure_label_issue, in _execute_one_attempt: a result column whose
#      NAME claims a measure the scheme does not record is rejected for repair,
#      so a mislabelled count can never reach the composer.
# Holders are what the curated views actually carry (information_schema,
# 2026-10-06; SCHEME_METRICS). Money, gender and applications span several
# schemes and are gated only where no chosen scheme has them.
_ALL_SCHEMES = frozenset(scheme_registry.NAMES)   # E5, D-079
_MEASURE_HOLDERS: "list[tuple[str, Matcher, frozenset[str]]]" = [
    ("person-days", Matcher(Alt(
        _c01_chain(["person", ("day", "days")], ["opt1u"]),
        _c01_chain(["man", ("day", "days")], ["opt1u"]),
        Seq(W("day", "days"), "of", W("work", "employment"), sep="space"),
        Seq(_c01_chain(["100", ("day", "days")], ["opt1u"]), Opt("of"), W("work", "employment"),
            sep="space"),
        Seq("completed", _c01_chain(["100", ("day", "days")], ["opt1u"]), sep="space"))),
     frozenset({"MGNREGA"})),
    ("job cards", Matcher(_c01_chain(["job", ("card", "cards")], ["opt1u"])), frozenset({"MGNREGA"})),
    ("wage expenditure", Matcher(W("wage", "wages")), frozenset({"MGNREGA"})),
    ("material expenditure", Matcher(Alt(
        Seq("material", W("exp", "cost", "spend", prefix=True), sep="space"),
        W("material_exp", "material_cost", "material_spend", prefix=True))), frozenset({"MGNREGA"})),
    ("employment (households / persons employed)", Matcher(Alt(
        Seq(W("household", "households", "person", "persons", "people", "women", "worker", "workers"),
            Opt(W("were", "got")), "employed", sep="space"),
        Pred(_c01_underscored_employed),
        W("employment"))), frozenset({"MGNREGA"})),
    ("houses", Matcher(Alt(W("house", "houses", "housing", "plinth", "dwelling", "dwellings"),
                           _c01_chain(["roof", "cast"], ["opt1u"]))), frozenset({"PMAY-G"})),
    ("producer groups", Matcher(Alt(_c01_chain(["producer", ("group", "groups")], ["opt1u"]),
                                    W("pg", "pgs"))),
     frozenset({"Focus Legacy"})),
    ("subsidy", Matcher(W("subsidy", "subsidies")), frozenset({"CM Elevate Legacy"})),
    ("loans", Matcher(W("loan", "loans")), frozenset({"CM Elevate Legacy"})),
    ("applications", Matcher(W("application", "applications", "applicant", "applicants")),
     frozenset({"CM Elevate", "CM Elevate Legacy", "Focus Plus"})),
    # CM Elevate left the holders on 2026-10-16: its gender was only ever the
    # scheme_specific ->> 'gender_id' JSON key, and megh_readonly may not read
    # scheme_specific (ingestion team, CHATBOT_DB_CHANGES_2026-10-16).
    ("gender", Matcher(W("gender", "women", "female", "females", "male", "males", "men")),
     frozenset({"MGNREGA", "PMAY-G", "Focus Plus"})),
    # CM Elevate's Approved / Rejected decision lived only in scheme_specific ->>
    # 'file_status', now locked from the chatbot's role; current_file_status holds
    # forward / resubmit / sendback to vdv/citizen only, so a filter on it for
    # approved / rejected is a confident false 0. "pending" is NOT here: it stays
    # data_verified = 'On Hold' (user decision 2026-10-16, keeping the sheet rule).
    ("approval or rejection decisions", Matcher(W(
        "approved", "approve", "approval", "approvals", "rejected", "reject", "rejection", "rejections")),
     _ALL_SCHEMES - {"CM Elevate"}),
    ("rupee amounts", Matcher(Alt(
        W("amount", "amounts", "expenditure", "spend", "spent", "rupee", "rupees", "crore", "crores",
          "money", "fund", "funds", "paid_out"),
        W("disburs", "subsid", prefix=True),
        Seq("paid", _C01Gap(_c01_ws), "out"),
        _C01CharIn("₹"))),
     _ALL_SCHEMES - {"CM Elevate"}),
]

# The place and year a gap question carried, for its offers (" in Mawlwai
# across all financial years"). The most specific "in <place>" only.
_GAP_YEAR = Matcher(_C01YearPair(_c01_is_20dd, lambda w: (len(w) == 2 and is_int(w)) or _c01_is_20dd(w)))
_GAP_ALL_YEARS = Matcher(Seq(W("across", "for", "in", "over"), "all", Opt("the"), Opt("financial"), "years",
                             sep="space"))
_GAP_PLACE = Matcher(Seq(W("in", "at"), _C01Gap(_c01_ws), _C01PlaceWords((
    "for", "under", "across", "during", "in", "at", "of", "from", "with", "and", "by", "the", "not",
    "fy", "financial", "year", "years", "scheme", "all", "each", "every", "total", "statewide",
    "meghalaya"))))


# "the block, not the village": the level the user already settled, so an
# offer does not re-ask "block or village?". A negated level is not one.
_GAP_LEVEL = Matcher(Seq(_C01NotPreceded("not ", "not the "), Cap(W("block", "village", "district"))))


def _measure_gap_scope(question: str, with_year: bool = True) -> str:
    q = question or ""
    parts: list[str] = []
    for m in _GAP_PLACE.finditer(q):
        place = m.group(1).strip(" ,.?")
        if not place or _mentions_scheme(place) or _GAP_YEAR.search(place) \
                or any(word_matcher.search(place) for _, word_matcher, _h in _MEASURE_HOLDERS):
            continue
        words = place.split()
        # "at least 100 applications" / "at most": a quantity, not a place
        # (the offer read "Here is what CM Elevate does record in Least", 2026-10-16).
        if words[0].lower() in ("least", "most"):
            continue
        if words[-1].lower() in ("block", "village", "district"):
            level_word = words.pop().lower()
        else:
            level = _GAP_LEVEL.search(q)
            level_word = level.group(1).lower() if level else ""
        parts.append(f" in {' '.join(words).title()}" + (f" {level_word}" if level_word else ""))
        break
    if with_year and _GAP_ALL_YEARS.search(q):
        parts.append(" across all financial years")
    elif with_year and _GAP_YEAR.search(q):
        y = _GAP_YEAR.search(q)
        parts.append(f" in FY {y.group(1)}-{y.group(2)[-2:]}")
    return "".join(parts)


def _measures_not_held(text: str, schemes: "list[str]") -> "list[tuple[str, frozenset[str]]]":
    """(label, holders) for each measure `text` names that none of `schemes`
    records. Empty when every named measure is held (or none is named)."""
    chosen = set(schemes or [])
    if not chosen:
        return []
    return [(label, holders) for label, word_matcher, holders in _MEASURE_HOLDERS
            if word_matcher.search(text or "") and not (holders & chosen)]


def _swap_scheme_in_question(question: str, target: str) -> str:
    """The question with every scheme it names replaced by `target` (once). Any
    scheme, not only the chosen one: a bare "CM Elevate" re-pointed to CM
    Elevate Legacy must not survive beside the target."""
    out = question
    for pat in _SCHEME_NAME_MATCHER.values():
        out = pat.sub("\x00", out)
    if "\x00" in out:
        out = out.replace("\x00", target, 1).replace("\x00", "")
    else:
        out = f"{out.strip().rstrip(' ?.')} under {target}"
    return _c01_tidy_space(out, ",?.").strip()


def _measure_not_held_gap(question: str, schemes: "list[str]",
                          scan_text: "str | None" = None) -> "ClarificationNeeded | None":
    """The pause for a measure that no chosen scheme records ("person-days" for
    Focus Plus, "houses" for CM Elevate, "subsidy" for MGNREGA, ...), else None.
    It names the scheme(s) that do record it and offers the chosen scheme's own
    measures for the same place and year. `scan_text` is the question with
    place names masked (_mask_scheme_words_in_village_name)."""
    gaps = _measures_not_held(scan_text if scan_text is not None else question, schemes)
    if not gaps:
        return None
    # A stated Focus Plus amount ("loans of ₹5,000") has its own reviewed reply
    # (_focusplus_amount_not_held), which explains the two real payment sizes.
    if schemes == ["Focus Plus"] and premise_check.stated_amount_filters(question):
        gaps = [g for g in gaps if g[0] not in ("loans", "rupee amounts")]
        if not gaps:
            return None
    label, holders = gaps[0]
    named = " and ".join(schemes)
    verb = "doesn't" if len(schemes) == 1 else "don't"
    options: list[dict] = []
    owners = [s for s in SCHEME_CATALOG if s in holders] if len(holders) <= 2 else []
    for owner in owners:
        options.append({"label": f"{label[0].upper()}{label[1:]} under {owner}",
                        "question": _swap_scheme_in_question(question, owner)})
    own_scope = _measure_gap_scope(question, with_year=schemes[0] not in _SCHEMES_WITHOUT_YEAR)
    for lab, tmpl in _SCHEME_HEADLINE_OFFERS.get(schemes[0], []):
        options.append({"label": lab, "question": tmpl.format(scope=own_scope)})
    if owners:
        who = owners[0] if len(owners) == 1 else " and ".join(owners)
        head = f"{named} {verb} record {label} — only {who} {'does' if len(owners) == 1 else 'do'}."
    else:
        head = f"{named} {verb} record {label}."
    context_budget.log_decision("clarify", rule="measure-not-held", schemes=schemes, measure=label)
    logger.info("measure-not-held: %r asks %s, not recorded by %s", question, label, schemes)
    return ClarificationNeeded(
        f"{head} I won't answer with a different figure in its place. "
        f"Here is what {schemes[0]} does record{own_scope}. Which would you like? "
        "Tap one, or ask it in full.",
        options=options, rule="measure-not-held")


def _sql_column_aliases(sql: str) -> "list[str]":
    """Every result-column alias the query defines (outer SELECT, CTEs and
    subqueries), in reading order, from the parsed tree. Table and CTE aliases
    are not result columns and are not returned; nor is a word inside a string."""
    out: list[str] = []
    for tree in sql_ast.parse(sql):
        for node in tree.walk(bfs=False):
            if isinstance(node, exp.Alias) and node.alias and node.alias not in out:
                out.append(node.alias)
    return out


def _sql_measure_label_issue(schemes: "list[str]", sql: str) -> "str | None":
    """A repair message when a result column's NAME claims a measure that no
    scheme in `schemes` records (COUNT(*) AS person_days on Focus Plus), else
    None. The composer reads column names as meaning, so a mislabelled count
    becomes a wrong sentence."""
    for alias in _sql_column_aliases(sql or ""):
        gaps = _measures_not_held(alias.replace("_", " "), schemes)
        if gaps:
            label = gaps[0][0]
            return (f"the result column '{alias}' claims {label}, but "
                    f"{' and '.join(schemes)} records no {label} — no column in its views "
                    "holds it. Never rename another figure (a payment count, an amount) "
                    "to the measure the question asked for. Name every result column for "
                    "exactly what it computes (for example payments, amount_disbursed, "
                    "applications) and keep every other clause as it was.")
    return None


# curated.dim_year is the CALENDAR every scheme's year_key points into (1984-85
# onwards) and dim_geography the REGISTRY of every place in the state. Neither
# says what a scheme has data for: "financial years in MGNREGA" read from
# dim_year listed 42 years when MGNREGA holds four (2026-10-06). A query that
# reads only these, and none of the scheme's own views or facts, is rejected.
_SHARED_DIMENSIONS = frozenset({"curated.dim_year", "curated.dim_geography",
                                "curated.dim_geography_alias"})
def _sql_schema_tables(sql: str) -> "set[str]":
    """'curated.x' / 'semantic.x' for every schema-qualified table the query
    reads (FROM, JOIN, subqueries, CTE bodies), from the parsed tree."""
    return {t for t in sql_ast.tables(sql, qualified=True)
            if "." in t and t.split(".", 1)[0] in ("curated", "semantic")}


def _sql_dimension_only_issue(schemes: "list[str]", sql: str) -> "str | None":
    tables = _sql_schema_tables(sql or "")
    if not tables or not (tables & _SHARED_DIMENSIONS):
        return None
    if tables - _SHARED_DIMENSIONS - {"curated.dim_scheme"}:
        return None   # it reads a scheme's own view / fact as well
    named = " and ".join(schemes) if schemes else "the scheme"
    return (f"this query reads only {', '.join(sorted(tables & _SHARED_DIMENSIONS))} — shared "
            "calendar / place registries that list every possible year and place for all "
            f"schemes, not what {named} has data for. Read the values from {named}'s own "
            "view instead (for example SELECT DISTINCT financial_year_short FROM its view, or "
            "SELECT DISTINCT lgd_district FROM its view), so the answer lists only years and "
            "places that actually have records.")


def _swap_scope_phrase(state: "object", scheme: str, prev: "object" = None,
                       with_place: bool = True) -> str:
    """" in <place> in FY 2023-24" from the conversation state's committed
    scope (the previous turn's resolved filters when there is no state), for
    the offers of _swap_measure_gap. The most specific place only; the
    resolver finds its parents. `with_place=False`: the year only (the
    question names its own place)."""
    resolved = getattr(prev, "resolved_entities", None) or {}

    def _get(name: str, key: str):
        return getattr(state, name, None) if state is not None else resolved.get(key)

    parts: list[str] = []
    village = _get("village", "village") if with_place else None
    block = _get("block", "block") if with_place else None
    district = _get("district", "district") if with_place else None
    if village and str(village).isdigit():
        from app.entity_resolver import village_code_name
        village = village_code_name(village) or None
    if village:
        parts.append(f" in {str(village).title()} village"
                     + (f" in {str(block).title()} block" if block else ""))
    elif block:
        parts.append(f" in {str(block).title()} block")
    elif district:
        parts.append(f" in {str(district).title()}")
    if scheme not in _SCHEMES_WITHOUT_YEAR:
        year = _get("year", "year_key")
        if _get("year_all", "year_all"):
            parts.append(" across all financial years")
        elif isinstance(year, int):
            parts.append(f" in FY {year}-{(year + 1) % 100:02d}")
    return "".join(parts)


def _swap_measure_gap(followup: str, rewritten: str, prev: "object",
                      state: "object") -> "ClarificationNeeded | None":
    """The pause to raise when a scheme-swap follow-up ("for pmay", "give me
    for pmay", "same for PMAY-G") carried over a measure only another scheme
    holds, else None. Only after a DATA turn (a knowledge swap such as "how
    are wages paid?" -> "for pmay" is a question about the scheme, not a
    measure), only when the follow-up did not type the measure itself, and
    only when the rewrite names exactly one scheme."""
    if prev is None or getattr(prev, "route", None) != "data":
        return None
    if not (_SCHEME_SWAP_FOLLOWUP.match((followup or "").strip())
            or _scheme_substitution(followup)[0]):
        return None
    named = _exact_schemes(rewritten)
    if len(named) != 1:
        return None
    target = next(iter(named))
    for owner, measures in _SCHEME_OWN_MEASURES.items():
        if owner == target:
            continue
        for label, word_matcher in measures:
            if word_matcher.search(rewritten) and not word_matcher.search(followup or ""):
                scope = _swap_scope_phrase(state, target, prev)
                options = [{"label": lab, "question": tmpl.format(scope=scope)}
                           for lab, tmpl in _SCHEME_HEADLINE_OFFERS.get(target, [])]
                if not options:
                    return None
                example = options[0]["question"].rstrip("?")
                return ClarificationNeeded(
                    f"{target} doesn't record {label} — only {owner} does. "
                    f"Here is what {target} does hold{scope}. Which would you like? "
                    f"Tap one, or ask it in full, for example “{example}”.",
                    options=options, rule="swap-measure-unavailable")
    return None


def _rest_of_schemes_rewrite(prev: "object", followup: str) -> "str | None":
    """Deterministic rewrite for "same for the remaining / other / all schemes":
    the previous question with its scheme replaced by the list of schemes it
    asks about. None when the follow-up is not that shape, names a scheme
    itself, or the previous question named no scheme to swap out.

    On a KNOWLEDGE antecedent, schemes that share one knowledge base
    (rag.kb_scheme — CM Elevate and CM Elevate Legacy) count once: after a CM
    Elevate "how to apply", CM Elevate Legacy is not a "remaining" scheme with
    different material, and listing it would repeat the same answer."""
    f = (followup or "").strip()
    if not f or len(f.split()) > 12 or _mentions_scheme(f):
        return None
    rest = bool(_REST_OF_SCHEMES.search(f))
    every = not rest and bool(_ALL_SCHEMES_FOLLOWUP.search(f))
    if not (rest or every):
        return None
    prev_q = getattr(prev, "question", "") or ""
    prev_named = [s for s, pat in _SCHEME_NAME_MATCHER.items() if pat.search(prev_q)]
    if not prev_named:
        return None
    knowledge = getattr(prev, "route", "") == "knowledge"
    key = rag.kb_scheme if knowledge else (lambda s: s)
    done = {key(s) for s in prev_named} if rest else set()
    targets: list[str] = []
    for s in SCHEME_CATALOG:
        if key(s) in done:
            continue
        done.add(key(s))
        targets.append(s)
    if not targets:
        return None
    names = targets[0] if len(targets) == 1 else ", ".join(targets[:-1]) + " and " + targets[-1]
    # Mark every old scheme mention first, then put the list in at the first
    # mark only — substituting the list directly would let a later matcher
    # match a name INSIDE the list just inserted ("CM Elevate") and delete it.
    out = prev_q
    for s in prev_named:
        out = _SCHEME_NAME_MATCHER[s].sub("\x00", out)
    out = out.replace("\x00", names, 1).replace("\x00", "")
    out = _c01_tidy_space(out, ",?.").strip()
    logger.info("follow-up rest-of-schemes: %r + %r -> %r", prev_q, followup, out)
    return out


async def rewrite_followup(question: str, prev: "object", extra_context: str = "",
                          kind: "str | None" = None, cleared: "dict | None" = None) -> str:
    """Turn a fragment into a standalone question using the previous turn.
    Falls back to the original question on any failure — never raises.

    `extra_context` (optional): the context layer's token-budgeted structured
    state / summary / relevant-older-turns block (see
    context_manager.build_followup_context) — spliced into the prompt ahead
    of the previous turn, for a conversation where "the previous turn" alone
    has lost the thread (e.g. a KNOWLEDGE digression sits between the DATA
    answer being followed up on and this fragment). Blank by default, so
    every existing caller is unaffected."""
    if not settings.FOLLOWUP_REWRITE_ENABLED or prev is None:
        return question
    rest = _rest_of_schemes_rewrite(prev, question)
    if rest:
        return rest
    swap = _scheme_swap_rewrite(getattr(prev, "question", "") or "", question)
    if swap:
        return swap
    swap = _place_swap_rewrite(prev, question)
    if swap:
        return swap
    sections: list[tuple[str, str]] = []
    tiers: list[str] = []
    guard = "error"
    try:
        sections, tiers, provenance = _build_rewrite_prompt(question, prev, extra_context, kind,
                                                            cleared)
        out = await llm.call_rewriter("".join(text for _, text in sections))
        out = out.strip().strip('"').splitlines()[0].strip()
        if settings.PLACE_GAZETTEER:
            out = _c01_tidy_space(_c01_strip_chip_level(out, question), ",?.").strip()
        if 3 <= len(out) <= 300:
            violation = _rewrite_provenance_violation(out, **provenance)
            if violation == "village":
                _fixed = _restore_typed_village(question, out)
                if _fixed and not _rewrite_provenance_violation(_fixed, **provenance):
                    logger.info("follow-up rewrite: village respelt as typed (%r -> %r)", out, _fixed)
                    out, violation = _fixed, None
            if not violation and settings.PLACE_GAZETTEER and _c01_invented_level(question, out):
                violation = "level"
            if not violation and settings.PLACE_GAZETTEER and _c01_place_only_drift(question, prev, out):
                violation = "measure"
            if not violation and settings.PLACE_GAZETTEER and _c01_kept_finer_place(question, prev, out):
                violation = "place"
            guard = f"rejected:{violation}" if violation else "ok"
            if violation:
                # The model put a scheme/district/block into the question that
                # neither the user nor the previous turn's scope ever named.
                # Most often it was copied from earlier text. Answering that
                # question would give a confident figure for the wrong scope.
                # The original fragment goes on instead: inject_scheme_hint and
                # the prior_resolved carry still give it the previous turn's
                # scheme and filters, deterministically.
                # A place-only follow-up is better served by the deterministic
                # swap than by the bare fragment: "in DADENGGIRI" (rewritten
                # "Dadengiri", rejected) ran as "in DADENGGIRI under PMAY-G?",
                # lost "amount released" and answered an overview; the next two
                # turns built on that fragment (user, live 2026-10-21, KI-347).
                _forced = _place_swap_rewrite(prev, question, force=True, district=violation == "place")
                if _forced:
                    logger.warning("follow-up rewrite rejected (%s: %r -> %r) — deterministic place swap %r",
                                   violation, question, out, _forced)
                    return _forced
                logger.warning("follow-up rewrite introduced a %s no permitted source names "
                               "(%r -> %r) — using the original question", violation, question, out)
                return question
            logger.info("follow-up rewrite: %r -> %r", question, out)
            return out
        guard = "unusable"
    except Exception as e:  # noqa: BLE001
        logger.warning("follow-up rewrite failed (%s) — using original", e)
    finally:
        if sections:
            context_budget.log_prompt_context("rewrite", sections, tiers=tiers, guard=guard,
                                              followup_kind=kind)
    return question


_C01_DRIFT_FILLER = frozenset("WHAT WHICH IS WAS ARE WERE THE A AN OF IN FOR UNDER DURING TOTAL SCHEME FY "
                              "DISTRICT BLOCK VILLAGE CONSTITUENCY AC C RD HOW MUCH MANY".split())


def _c01_place_only_drift(question: str, prev: "object", rewritten: str) -> "list | None":
    """Content words a model rewrite of a PLACE-ONLY follow-up brought in that
    neither the previous question nor the follow-up holds, or None. "in dalu
    block" after "Total PMAY-G amount released …" came back "What is the fund
    utilization …" and answered a percentage (user, live 2026-10-21 18:37,
    KI-347): a place swap keeps the measure, so a new word is drift."""
    from app.entity_resolver import fold_words, place_mentions, place_only
    if not place_only(question, _C01_PLACE_ONLY_WORDS):
        return None
    allowed = set(fold_words(getattr(prev, "question", "") or "")) | set(fold_words(question)) \
        | _C01_DRIFT_FILLER | {w.upper() for w in _REPHRASE_VOCAB}
    for name in place_mentions(rewritten):
        allowed |= set(name.split())
    novel = [w for w in fold_words(rewritten)
             if w not in allowed and not any(c.isdigit() for c in w) and len(w) > 2]
    return novel or None


_C01_LEVEL_RANK = {"village": 0, "block": 1, "assembly_constituency": 1, "district": 2}


def _c01_kept_finer_place(question: str, prev: "object", rewritten: str) -> "list | None":
    """The previous question's finer places (village; block / constituency under a
    district) that a model rewrite of a PLACE-ONLY follow-up naming a coarser place
    kept, or None. "How many PMAY beneficiaries are there in Badimbari?" -> "how many
    of those houses are completed?" -> "What about Rongara block?" came back "How many
    of the 14 PMAY-G beneficiaries in Badimbari … are completed in the Rongara block?",
    answered the village again, and so did the district turn after it (PMAY-G sheet
    run 2026-10-22, 3 of 4 chats). The place the user names replaces the old one."""
    from app.entity_resolver import place_mentions, place_only
    only = place_only(question, _C01_PLACE_ONLY_WORDS)
    if not only or only[1] not in ("block", "district"):
        return None
    rank = _C01_LEVEL_RANK[only[1]]
    named = place_mentions(question)
    now = place_mentions(rewritten)
    kept = [p for p, d in place_mentions(getattr(prev, "question", "") or "").items()
            if _C01_LEVEL_RANK.get(d, 3) < rank and p not in named and p in now]
    return kept or None


_C01_LEVEL_AFTER = {"VILLAGE": "village", "BLOCK": "block", "CONSTITUENCY": "assembly_constituency"}


def _c01_invented_level(question: str, rewritten: str) -> "str | None":
    """"<NAME> <LEVEL>" when the rewrite put a level word after a place the user
    typed, the user did not type that word, and the database holds no such
    level for the name (PLACE_GAZETTEER, D-059); else None. "in dalu" came back
    "... in Dalu village ..." — DALU is a block and a constituency, and the
    village pause that followed offered DALUAGRE / DALUGAON (user, live
    2026-10-21 18:36, KI-347)."""
    from app.entity_resolver import fold_words, place_levels, place_mentions
    typed = set(fold_words(question))
    words = fold_words(rewritten)
    for name in place_mentions(question):
        nw = name.split()
        for i in range(len(words) - len(nw)):
            if words[i:i + len(nw)] != nw:
                continue
            nxt = words[i + len(nw)]
            lv = _C01_LEVEL_AFTER.get(nxt)
            if lv and nxt not in typed and lv not in place_levels(name):
                return f"{name} {nxt}"
    return None


def _restore_typed_village(question: str, rewritten: str) -> "str | None":
    """`rewritten` with a misspelt copy of a village the user typed put back as
    typed, or None. Live 2026-10-21: "in dangar dombah" came back "... in Dargar
    Dombah ..."; rejecting the rewrite sent the bare fragment on, which lost the
    measure. Only a window of the same word count scoring 80+ is replaced, and
    the caller re-runs the provenance check on the result."""
    from app.entity_resolver import fold_words, place_mentions
    words = rewritten.split()
    out = rewritten
    for name, dim in place_mentions(question).items():
        if dim != "village" or f" {name} " in f" {' '.join(fold_words(out))} ":
            continue
        n = len(name.split())
        best, best_i = 0.0, -1
        for i in range(len(words) - n + 1):
            window = " ".join(w.strip(".,?!;:") for w in words[i:i + n])
            score = fuzz.ratio(" ".join(fold_words(window)), name)
            if score > best:
                best, best_i = score, i
        if best < 80:
            return None
        tail = words[best_i + n - 1]
        punct = tail[len(tail.rstrip(".,?!;:")):]
        words = words[:best_i] + name.title().split()[:-1] + [name.title().split()[-1] + punct]             + words[best_i + n:]
        out = " ".join(words)
    return out if out != rewritten else None


# A follow-up that asks for every / the other schemes legitimately names schemes
# the previous turn didn't. The deterministic rewrites above catch the common
# phrasings, so this only keeps the provenance check from rejecting the rest.
_CROSS_SCHEME_FOLLOWUP = Matcher(Alt(
    Seq(W("all", "every", "each", "both", "other", "remaining", "across", "different"), Opt("the"),
        W("scheme", "schemes"), sep="space"),
    Seq("cross", _C01Gap(_c01_opt1), "scheme")))


def _build_rewrite_prompt(question: str, prev: "object", extra_context: str = "",
                          kind: "str | None" = None, cleared: "dict | None" = None
                          ) -> "tuple[list[tuple[str, str]], list[str], dict]":
    """The follow-up rewrite prompt as named sections (for the prompt_context
    log), the evidence tiers used, and the provenance sources the rewrite is
    checked against.

    The previous turn reaches this prompt as STRUCTURED evidence
    (context_manager.build_rewrite_evidence): its question, its filters and,
    only when the follow-up points into it, its result. It is no longer a fixed
    300-character slice of its answer, which carried names the follow-up never
    referred to and cut off anything further on."""
    ev = context_manager.build_rewrite_evidence(question, prev, kind)
    pointed = bool(ev["result"] or ev["answer"])
    instructions = (
        "Rewrite the FOLLOW-UP as a complete, standalone question by reusing "
        "context from the PREVIOUS question. Keep the user's intent; change only "
        "what the follow-up changes (e.g. a different district, year, or metric). "
        "Take every district, block, village, year, tranche, scheme, category or other "
        "filter ONLY from the FOLLOW-UP itself, the PREVIOUS question, the PREVIOUS "
        "filters, or the Known context below"
        + (" — and take a name from the PREVIOUS result or answer only for the item "
           "the FOLLOW-UP points at" if pointed else "")
        + ". When in doubt, leave it out rather than guess one. "
        "Return ONLY the rewritten question, nothing else.\n\n"
    )
    sections = [
        ("instructions", instructions),
        ("conversation_state", f"{extra_context}\n\n" if extra_context else ""),
        ("previous_question", f'PREVIOUS question: "{getattr(prev, "question", "") or ""}"\n'),
        ("previous_filters", f"{ev['filters']}\n" if ev["filters"] else ""),
        ("previous_result", f"{ev['result']}\n" if ev["result"] else ""),
        ("previous_answer_excerpt", f"{ev['answer']}\n" if ev["answer"] else ""),
        # Filters the follow-up REMOVES ("show it by district" after a one-district
        # turn). Without this line the model copied the district back from the
        # previous question (live run 2026-09-26, Scenario C) and the breakdown
        # came back filtered to that one district.
        ("removed_filters",
         "REMOVED by the follow-up (do NOT include these): "
         + "; ".join(f"{k}={v}" for k, v in cleared.items()) + "\n" if cleared else ""),
        ("current_question", f'FOLLOW-UP: "{question}"\n\n'),
        ("frame", "Standalone question:"),
    ]
    ctx = context_manager.split_followup_context(extra_context)
    allowed = [question, getattr(prev, "question", "") or "", ev["filters"], ctx["state"],
               ev["result"], ev["answer"]]
    # Text the rewrite must NOT take names from: the summary and older turns
    # without a back-reference, and the previous answer unless its excerpt was
    # sent. A name found only there is contamination (context_policy "name").
    denied = [] if ev["answer"] else [getattr(prev, "answer", "") or ""]
    if context_manager.references_history(question):
        allowed += [ctx["history"], ctx["summary"]]
    else:
        denied += [ctx["history"], ctx["summary"]]
    provenance = {
        "question": question,
        "allowed_text": "\n".join(a for a in allowed if a),
        "allowed_schemes": list(getattr(prev, "schemes", None) or []),
        "denied_text": "\n".join(d for d in denied if d),
        "cleared": dict(cleared or {}),
    }
    return sections, ev["tiers"], provenance


def _exact_schemes(text: str) -> set[str]:
    return {s for s, pattern in _SCHEME_NAME_MATCHER.items() if pattern.search(text or "")}


def _rewrite_provenance_violation(rewritten: str, *, question: str, allowed_text: str,
                                  allowed_schemes: "list[str]", denied_text: str = "",
                                  cleared: "dict | None" = None) -> "str | None":
    """The field ('scheme', 'district', 'block', 'year', 'metric', 'category'
    or 'name') that the rewritten follow-up names with no permitted source,
    else None. Each field has its own rule (context_policy.rewrite_violation,
    documented in AI_PIPELINE.md §5.4). Permitted sources are the follow-up
    itself, the previous question, the previous filters, the structured
    Known-context line, and, only when the follow-up points into them, the
    previous result or answer excerpt. The summary and older turns count only
    when the follow-up reaches back to them. Names are compared canonically,
    so "ekh" in the follow-up permits "East Khasi Hills". An explicit year
    change by the user is always allowed."""
    return context_policy.rewrite_violation(
        rewritten, question=question, allowed_text=allowed_text, denied_text=denied_text,
        allowed_schemes=allowed_schemes, cleared=cleared)


def _cleared_filters(plan, prev, state) -> dict:
    """{field: previous value} for every geography/year field the merge plan
    CLEARs and the previous turn actually had. Told to the rewrite, and
    enforced by the provenance check, so a removed filter can't come back
    through the rewritten text."""
    if plan is None:
        return {}
    resolved = getattr(prev, "resolved_entities", None) or {}
    values = {"district": resolved.get("district") or getattr(state, "district", None),
              "block": resolved.get("block") or getattr(state, "block", None),
              "year": resolved.get("year_key") if resolved.get("year_key") is not None
              else getattr(state, "year", None)}
    out = {}
    for name, value in values.items():
        if value is None or plan.action(name) != context_policy.CLEAR:
            continue
        out[name] = context_manager._fy_text(int(value)) if name == "year" else value
    return out


# ── Query rephraser (graph node `rephrase`, D-037) ──────────────────────────
# A NEW question typed in messy English ("manrega persondays ekh 23-24 how
# much"), Hinglish ("pmay mein kitne ghar sanction hue") or voice-to-text
# ("see em elevate") reached the intent / scheme classifiers, the entity
# extractor and the SQL generator exactly as typed. Only follow-ups were ever
# rewritten (rewrite_followup). The rephraser turns such a message into one
# clean English question before routing, so every later stage reads it.
#
# It changes WORDING only. The rewrite is thrown away and the original goes on
# whenever it adds, drops or changes a scheme, place, year, number, measure,
# category or any name the user typed (_rephrase_violation; the follow-up
# rewrite's own checker, context_policy.rewrite_violation, does half of it).
# It never pauses, never answers, and a slow or failed model call keeps the
# original question. A clean question skips the model call (_needs_rephrase).

# Hinglish words -> an English gloss. The gloss is appended to the original for
# the checks only, so "ghar" permits "houses" and "mahila" permits "women"; the
# model still sees exactly what the user typed.
_HINGLISH_GLOSS = {
    "kitne": "how many", "kitna": "how much", "kitni": "how many", "kya": "what",
    "kaun": "which", "kaunsa": "which", "kaunse": "which", "kahan": "where", "kab": "when",
    "mein": "in", "mai": "in", "ka": "of", "ki": "of", "ke": "of", "ko": "to", "se": "from",
    "aur": "and", "ya": "or", "hai": "is", "hain": "are", "tha": "was", "thi": "was",
    "batao": "tell", "bataiye": "tell", "bata": "tell", "dikhao": "show", "dikhaiye": "show",
    "dijiye": "give", "chahiye": "need", "hue": "", "hua": "", "hui": "", "gaye": "", "gaya": "",
    "ghar": "houses", "gharon": "houses", "makaan": "houses", "makan": "houses",
    "paisa": "money", "paise": "money", "rupaye": "rupees", "rupay": "rupees",
    "raashi": "amount", "rashi": "amount", "kharcha": "expenditure", "kharch": "expenditure",
    "mahila": "women", "mahilaon": "women", "mahilayen": "women", "aurat": "women",
    "aurton": "women", "purush": "men", "aadmi": "men", "log": "people", "logon": "people",
    "kaam": "work", "din": "days", "saal": "year", "sal": "year", "varsh": "year",
    "zila": "district", "jila": "district", "zile": "district", "jile": "district",
    "gaon": "village", "gaanv": "village", "gav": "village", "gaon-wise": "village-wise",
    "bane": "built", "bana": "built", "banaye": "built", "banne": "built",
    "mile": "received", "mila": "received", "mili": "received", "diye": "given", "diya": "given",
    "kul": "total", "sabhi": "all", "sab": "all", "har": "each", "pichle": "last", "pichhle": "last",
    "yojana": "scheme", "yojna": "scheme", "labharthi": "beneficiaries", "laabharthi": "beneficiaries",
    "aavedan": "applications", "avedan": "applications", "rozgar": "employment",
    "rojgar": "employment", "naukri": "jobs", "majdoori": "wages", "mazdoori": "wages",
    "parivar": "households", "pariwar": "households", "parivaron": "households",
    # "MGNREGA ka 2024-25 wala district-wise data batao" (D-061 addendum, 2026-10-22):
    # "wala" read as a dropped NAME, so the right rephrase was rejected and the raw
    # Hinglish failed SQL four times and fell back to the documents.
    "wala": "", "wali": "", "wale": "", "vala": "", "vali": "", "vale": "",
}
_HINGLISH_PHRASES = [
    (Matcher(Seq(W("kaam", "kam"), Opt("ke"), "din", sep="space")), "person-days"),
    (Matcher(Alt(W("jobcard"), Seq("job", "card", sep="space"))), "job cards"),
]
# Ordinary question words and this domain's vocabulary. A word outside it (and
# outside schemes, places, measures and Hinglish) is treated as a NAME or a typo:
# the rewrite must keep it verbatim, unless it was only a typo of a word here.
_REPHRASE_VOCAB = frozenset("""
a about above across after again against all also am among an and any are as at be been before
being below between both but by can could did do does doing done each either else ever every
for from get gets give given go got had has have having how however i if in into is it its
just last least less like list many me more most much my need needs no nor not now of off on
once one only or other our out over overall own per please same show should since so some
such tell than that the their them then there these they this those through till to too total
totals under until up upon us vs versus was we were what when where which while who whom whose
why will with within without would yes yet you your
amount amounts number numbers count counts sum average avg rate rates ratio share percentage
percent highest lowest top bottom most least maximum minimum max min compare comparison
breakdown wise district districts block blocks village villages state statewide meghalaya
region regions area areas place places year years financial fiscal fy month months date dates
data detail details figure figures value values record records report status statuses
scheme schemes house houses housing sanction sanctioned sanctions complete completed
completion progress pending released release releases disbursed disbursement disbursements
disburse payment payments paid pay money rupees rupee crore crores lakh lakhs expenditure
spent spend fund funds funding beneficiary beneficiaries applicant applicants application
applications applied received receive given employed employment household households person
persons people women woman men man female females male males gender worker workers work
works job jobs card cards wage wages material labour labor day days generated generate
provided provide installment installments instalment instalments tranche tranches batch
batches member members group groups producer producers verified verification valid invalid
rejected approved hold occupation farmer farmers category categories type types mode online
loan loans subsidy subsidies bank banks lender sector sectors constituency constituencies
assembly cumulative inception till date so far current previous latest new old
focus plus legacy elevate gramin awas awaas mgnrega mnrega nrega pmay
plz pls plzz kindly sir madam maam bro bhai yaar ji hii hello thanks thank thx okay
""".split())
_REPHRASE_START = Matcher(Seq(_C01Begin(), W(
    "how", "what", "which", "where", "when", "who", "whom", "whose", "why", "show", "list", "give", "tell",
    "compare", "total", "is", "are", "was", "were", "did", "does", "do", "can", "could", "count",
    "number", "name", "display", "get", "find")))
_SHORT_FY = Matcher(_C01YearPair(
    lambda w: len(w) == 2 and w[0] in "1234" and is_int(w),
    lambda w: len(w) == 2 and w[0] in "1234" and is_int(w),
    bad_before="0123456789/-", bad_after="0123456789/-"))
_QUESTION_SHAPE = Matcher(Alt(Seq("how", W("many", "much"), sep="space"), Seq("number", "of", sep="space"),
                              W("count", "total")))
