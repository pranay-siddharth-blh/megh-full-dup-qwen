"""
The whole NL -> SQL -> answer flow as one plain sequential function. No graph
framework: each step is an ordinary `await`, branches are ordinary `if`. This
is deliberately simpler than the LangGraph design in the GrantThornton
proposal — appropriate at 2 schemes and 20-40 concurrent users; revisit if
either grows a lot.
"""
import asyncio
import hashlib
import itertools
import json
import logging
import numbers
import re
from dataclasses import dataclass

import httpx
from rapidfuzz import fuzz

from app.core import auth
from app.conversation import context_manager
from app.nlu import edge
from app.response import followups
from app.clients import llm
from app.nlu import premise_check
from app.sql import prompt_builder
from app.knowledge import rag
from app.response import chart_spec
from app.nlu import clarification_engine, defaults_engine
from app.response import findings
from app.sql import join_graph
from app.core import pii_guard
from app.response import answer_format
from app.response import answer_stream
from app.sql import dedup
from app.sql import sql_templates
from app.core import request_trace
from app.nlu import query_analyzer
from app.nlu import clarify_rules, frame_merge, understand
from app.sql import schema_retrieval
from app.sql import sql_join_validator
from app.core.config import settings
from app.database.db import UnsafeSQLError, fetch_rows, run_readonly
from app.nlu.entity_resolver import (
    all_districts,
    canonical_names,
    resolve_cm_scheme,
    collides_across_dimensions,
    collision_canonical_names,
    constituency_contents,
    detect_region,
    lookup_geo_term,
    resolve_dimension,
    resolve_house_status,
    resolve_tranche_label,
    resolve_village,
    scan_dimension,
    tranche_labels,
)
from app.sql.schema_context import SCHEME_CATALOG, available_metrics_text
from app.conversation.session_store import Session

logger = logging.getLogger(__name__)

# Words that make a question unambiguously a data (numbers) question — no model
# call needed to route it. Anything else with no strong signal is sent to the
# classifier, which decides DATA vs KNOWLEDGE.
_DATA_HINTS = re.compile(
    r"\b(how many|count|total|sum|average|avg|number of|top \d|per capita|"
    r"compare|comparison|trend|by district|by block|by village|by year|"
    r"person[\s-]?days?|expenditure|spend|spent|wage|wages|job cards?|"
    r"houses? (sanction|complet|released|pending)|sanctioned amount|amount released|"
    r"completion rate|utili[sz]ation rate|success rate|per ?cent|percentage|how much|"
    # Focus Plus / CM Elevate metric nouns — a bare "<scheme> beneficiaries?" /
    # "disbursements?" with no "how many" in front of it used to have no strong
    # signal either way and fell through to the LLM classifier, which guessed
    # KNOWLEDGE for "focus + beneficiaries?" and returned the glossary answer
    # instead of a count (confirmed live 2026-09-11). These are count/amount
    # nouns, not process words, so adding them carries the same low
    # misroute risk as "person-days"/"expenditure" above.
    r"beneficiar\w*|disburs\w*|"
    r"\bfy ?20\d\d|20\d\d-\d\d|crore|lakh|highest|lowest|most|least|"
    # correlation / cross-metric comparison phrasing — "do districts with high X
    # also have high Y", "is A related to B by district". These are answered by
    # querying and comparing the figures, not from the reference docs.
    r"relationship between|correlat\w*|associat\w*|linked to|linked with|"
    r"go together|hand in hand|track (?:each other|together)|move together|"
    r"districts? where|blocks? where|villages? where|"
    r"do (?:the )?districts? with|does (?:the )?district with|"
    r"also (?:high|low|higher|lower|lead|leads|greater|larger|smaller|more|less)|"
    r"versus|"
    # Result-shape and record-state words — "gender split", "breakdown",
    # "district x status cross-tab", "where are applications sitting in the
    # workflow", "approval status of Tranche 4", "verification rate". Computed
    # from the data, never in the reference docs, but they carried no data
    # signal and went to the document route, which then said it had nothing
    # (2026-09-23 KPI sweep: C2-01, C4-01, C4-02, F2-09, DC-04, C2-08).
    r"split|breakdown|distribution|cross[\s-]?tab|matrix|proportion|fraction|"
    r"share of|status of|statuses|workflow|pipeline|current[_\s]level|sitting|stuck|"
    r"verification|incomplete|missing)\b",
    re.IGNORECASE,
)
_KNOWLEDGE_HINTS = re.compile(
    r"\b(what is|what are|who is eligible|eligibility|how do i|how to apply|"
    r"documents? required|what documents|explain|define|meaning of|"
    r"components? of|features? of|objective|purpose of|when was .* launched|"
    r"difference between|guidelines?|rules? for)\b",
    re.IGNORECASE,
)


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
    set only for a village-ambiguity pause — see
    ConversationState.pending_village_hint for why a free-text resume needs
    it re-supplied deterministically rather
    than trusting the LLM mention-extractor to re-tag it in the merged text."""

    def __init__(self, question: str, *, options: list[dict] | None = None,
                 rule: str | None = None, village_hint: str | None = None,
                 graph_resumable: bool = False, resolved_so_far: dict | None = None):
        super().__init__(question)
        self.question = question
        self.options = options or []
        self.rule = rule
        self.village_hint = village_hint
        # Everything resolve_entities had ALREADY pinned when it hit this pause
        # (district/block/village_code/year_key/…). Stashed on
        # ConversationState.pending_resolved by whichever resume mechanism owns
        # the pause, and handed back to the resumed turn as `prior_resolved`.
        #
        # Without it, a question that needs TWO rounds of clarification (the
        # live case this was added for: an ambiguous village name AND a bare
        # "2023") re-derives every dimension from the merged text on every
        # round — so the village pinned in round 1 survives only as long as the
        # LLM mention-extractor keeps re-tagging it correctly out of the
        # resumed sentence, which is precisely what it does not reliably do
        # (see pending_village_hint's own doc-comment for the narrow, village-
        # only patch this generalises).
        self.resolved_so_far = dict(resolved_so_far) if resolved_so_far else {}
        # openspec/changes/multi-tenant-rls-scheme-scaleout task 5.4: True only
        # when this pause came from app.orchestration.pipeline_graph.answer_data_via_graph_compat
        # called with an explicit, session-scoped thread_id — meaning its
        # checkpoint was deliberately left alive (not cleaned up as an orphan,
        # see pipeline_graph.py's own cleanup comment) because a REAL resume
        # via LangGraph's own resume_via_graph is possible next turn. Tells
        # app/api/routers/query.py's except-ClarificationNeeded handler to skip
        # storing session.state.pending_frame (the frame slot-filling resume
        # signal) — this pause's resume state already lives
        # durably in the graph's checkpointer instead, exactly the same
        # reasoning app/orchestration/langgraph_followup.py's own pause branch already
        # documents for its own, separate checkpointer.
        self.graph_resumable = graph_resumable


# The ClarificationNeeded rules that are a PAUSE (the turn resumes next
# request, with the user's answer folded back in) rather than a terminal
# refusal ("column-not-held", "pii-column-blocked", … — re-raised, never
# resumed). Three separate resume mechanisms key off this exact set:
# app/api/routers/query.py's bespoke pending_scope_q stash, app/orchestration/langgraph_followup.py
# and app/orchestration/pipeline_graph.py's checkpointed interrupt(). It lives here, in the
# one module all three already import, because it used to be hand-copied into
# all three — and a rule added to only some of them pauses in the UI but can
# never be resumed (which is how "year-ambiguous" below would have behaved:
# the chips render, and answering one starts a brand-new question that has
# forgotten everything the pause was holding).
RESUMABLE_CLARIFICATION_RULES = frozenset({
    "scope-not-specified", "year-not-specified", "year-ambiguous", "entity-ambiguous",
})


class SQLAuthorizationDenied(Exception):
    """Raised inside execute_with_repair() when a candidate query — the
    original or a repaired one — fails auth.authorize(). Deliberately NOT
    caught by the repair loop's generic except clause: a denial ends the
    request, it does not spend a repair attempt trying a different query
    shape (see Phase 1 security hardening / sql-repair-authorization)."""

    def __init__(self, decision: "auth.AuthDecision"):
        super().__init__(decision.reason)
        self.decision = decision


# ── Follow-up ("what about East Garo Hills?") detection ─────────────────────
# Whether a message continues the previous turn is the Understand node's call
# (frame.is_followup — app/nlu/frame_merge.py). looks_like_followup() stays as
# the router's cheap pre-pipeline check: a fragment only means something in its
# own conversation, so it is never served from the shared response caches.
_FOLLOWUP_LEAD = re.compile(
    r"^\s*(what about|how about|and |what of |and for |also |ok(ay)? and |"
    r"same for |what if |now |then )", re.IGNORECASE,
)
_FOLLOWUP_PRONOUN = re.compile(
    r"\b(it|its|that|those|these|them|they|there|this(?:\s+one)?|the same|same one)\b", re.IGNORECASE,
)
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
# the pronoun check can't tell the difference — without "scheme" anchoring it,
# this read as a fragment needing prior context and got the "I don't have an
# earlier answer to build on" reply instead of being answered directly (TC-008).
_STANDALONE_ANCHOR = re.compile(
    r"\b(mgnrega|mnrega|nrega|pmay|awaas|person[\s-]?days?|expenditure|houses?|"
    r"job cards?|wages?|sanction|how many|total|list|scheme)\b", re.IGNORECASE,
)
# A bare scheme-name fragment — "in MGNREGA?", "for PMAY-G", "and Focus Plus?",
# "what about MGNREGA" — is the canonical scheme-swap follow-up: it reuses the
# whole previous question and only changes the scheme. It trips _STANDALONE_ANCHOR
# (the scheme names are listed there), so without this it is mistaken for a
# self-contained question and the router reads it as "tell me about MGNREGA".
_SCHEME_SWAP_FOLLOWUP = re.compile(
    r"^\s*(?:in|for|and|also|now|then|what about|how about|what of|same for|"
    r"switch to|change to|with)?\s*"
    r"(?:mgnrega|mnrega|nrega|pmay[\s-]?g?|awaas?|awas|"
    r"focus[\s-]?plus|focus\s*\+|focusplus|"
    r"cm[\s-]?elevate|cmelevate)"
    r"\s*(?:instead|now|then|scheme)?\s*[?.!]*\s*$",
    re.IGNORECASE,
)


# A follow-up fragment ("and for 2024-25?", "how launched it?") only means
# something against a real scheme answer. Rewriting it against a greeting,
# off-topic reply, clarification pause or a denial produces a confident bogus
# query — e.g. "how launched it?" right after "what is elon musk?" was being
# turned into a data question. So the previous turn must be one of these.
_ANTECEDENT_ROUTES = ("data", "knowledge")


def _mentions_scheme(question: str) -> bool:
    return any(p.search(question or "") for p in _SCHEME_NAME_PATTERN.values())


def looks_like_followup(question: str) -> bool:
    q = question.strip()
    if len(q.split()) > 12:
        return False
    # "in MGNREGA?" / "for PMAY-G" / "and Focus Plus?" — a scheme-swap fragment.
    # Checked before _STANDALONE_ANCHOR, which would otherwise veto it because it
    # names a scheme.
    if _SCHEME_SWAP_FOLLOWUP.match(q):
        return True
    if _FOLLOWUP_LEAD.search(q):
        return True
    # A question that names its own scheme outright is self-anchoring, same as
    # _STANDALONE_ANCHOR's "scheme"/"mgnrega"/"pmay" entries — but that regex
    # predates Focus Plus/CM Elevate and was never extended to them, so "What
    # benefits will I get under this Focus Plus" tripped _FOLLOWUP_PRONOUN on
    # "this", found no anchor, and got rewritten against the PREVIOUS turn's
    # scheme (e.g. "...compared to PMAY-G?") even though it names its own
    # scheme in full. _mentions_scheme covers all four schemes without having
    # to keep two scheme-name lists in sync.
    if _mentions_scheme(q):
        return False
    if _FOLLOWUP_PRONOUN.search(q) and not _STANDALONE_ANCHOR.search(q):
        return True
    # A bare fragment ("in East Garo Hills", "by block") with no anchor of its own.
    return len(q.split()) <= 6 and not _STANDALONE_ANCHOR.search(q)


# ── Guided-decoding schemas ──────────────────────────────────────────────────
# Passed to the classifier/SQL model so it can only emit tokens that fit the
# shape. The _extract_json / _extract_sql parsers below still run, so these are
# a reliability + speed win with no hard dependency on the gateway honouring
# them. Kept next to the prompts they constrain.
_SCHEMES_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "schemes": {
            "type": "array",
            "items": {"type": "string", "enum": list(SCHEME_CATALOG)},
            "minItems": 1,
        }
    },
    "required": ["schemes"],
}
# All optional strings — no null-union type (some xgrammar builds reject it) and
# no `required` (the model emits only the keys it actually finds). The parser in
# extract_entity_mentions already tolerates a partial or empty object.
_ENTITY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "district": {"type": "string"},
        "block": {"type": "string"},
        "village": {"type": "string"},
        "year": {"type": "string"},
        "assembly_constituency": {"type": "string"},
        # Plural — ONLY when the question names two-or-more blocks to compare
        # against each other ("compare X and Y"). Kept separate from "block"
        # rather than making "block" a string-or-array union (some xgrammar
        # builds reject union types, per the note above).
        "blocks": {"type": "array", "items": {"type": "string"}},
        # Same idea, for districts ("compare X and Y between district A and B").
        "districts": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}
_INTENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": ["DATA", "KNOWLEDGE"]}},
    "required": ["intent"],
}
# No `required: ["issue"]` — the verifier only needs to emit "issue" when
# ok is false; a passing query should cost the fewest tokens possible.
_SQL_VERIFY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issue": {"type": "string"},
    },
    "required": ["ok"],
}
# Force the SQL completion to open on a bare SELECT/WITH (optionally after
# whitespace). Body is unconstrained — this enforces statement shape, not a SQL
# grammar, so it can't catch a wrong join, only a prose preamble or a ```fence.
_SQL_SHAPE_REGEX = r"\s*(SELECT|WITH|select|with)[\s\S]*"


def _extract_json(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _extract_sql(raw: str) -> str:
    # Strip a ```sql fence if the model added one despite being told not to.
    cleaned = re.sub(r"```(?:sql)?", "", raw).strip()
    cleaned = cleaned.rstrip(";").strip()
    # The generator sometimes copies a worked example that ends its outer query
    # with ';' and then appends its own trailing "LIMIT n" AFTER that ';'
    # ("... ) d;\nLIMIT 1"). That is one statement, not two — fold the stray
    # terminator away so it isn't rejected as "multiple statements". Only a bare
    # trailing LIMIT/OFFSET/FETCH tail is spliced back; anything else after a ';'
    # is left for the multi-statement guard to reject.
    m = re.search(
        r";\s*((?:LIMIT|OFFSET|FETCH)\b[\s\S]*)$", cleaned, re.IGNORECASE)
    if m:
        cleaned = (cleaned[: m.start()] + "\n" + m.group(1)).strip()
    return cleaned


_SCHEME_NAME_PATTERN = {
    "MGNREGA": re.compile(r"\bmgnrega\b|\bmnrega\b|\bnrega\b", re.IGNORECASE),
    "PMAY-G": re.compile(r"\bpmay[\s-]?g?\b|\bawa+s?\b", re.IGNORECASE),
    "Focus Plus": re.compile(r"\bfocus[\s-]?plus\b|\bfocus\s*\+|\bfocusplus\b", re.IGNORECASE),
    "CM Elevate": re.compile(r"\bcm[\s-]?elevate\b|\bcmelevate\b", re.IGNORECASE),
}
# Fuzzy fallback for a scheme name the exact regex above misses because it's
# misspelled ("manrega", "pamay") — mirrors the RapidFuzz tolerance
# entity_resolver.py already gives district/block names. Kept separate from
# _SCHEME_NAME_PATTERN (exact match stays the fast, zero-false-positive path;
# this only runs when nothing named matches outright).
_SCHEME_FUZZY_ALIASES = {
    "MGNREGA": ["mgnrega", "mnrega", "nrega"],
    "PMAY-G": ["pmay", "pmayg", "awaas", "awas"],
    # "focus" alone, not just "focusplus" — a typo of the short form ("facus",
    # "focas", "fokus") is 5 chars against a 9-char target and never clears
    # the 80% ratio bar without it (fuzz.ratio("facus","focusplus") == 57 vs
    # fuzz.ratio("facus","focus") == 80), so "what facus+" fell through to the
    # generic capability blurb instead of routing to Focus Plus.
    "Focus Plus": ["focus", "focusplus"],
    "CM Elevate": ["cmelevate"],
}
_FUZZY_SCHEME_ACCEPT = 80


def _fuzzy_named_schemes(question: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", question or "") if len(w) >= 5]
    if not words:
        return []
    hits: list[str] = []
    for scheme, aliases in _SCHEME_FUZZY_ALIASES.items():
        if any(fuzz.ratio(w, a) >= _FUZZY_SCHEME_ACCEPT for w in words for a in aliases):
            hits.append(scheme)
    return hits


_SCHEME_CANONICAL_SPELLING = {
    "MGNREGA": "MGNREGA", "PMAY-G": "PMAY-G",
    "Focus Plus": "Focus Plus", "CM Elevate": "CM Elevate",
}


def _correct_scheme_spelling(question: str) -> str:
    """Fix an obviously misspelled scheme name in the question text itself
    ("manrega" -> "MGNREGA", "pamay" -> "PMAY-G") before routing. Without this,
    a typo'd scheme name only ever gets caught on the DATA path (via
    _fuzzy_named_schemes) — the KNOWLEDGE/RAG path embeds the raw text
    verbatim, so the typo silently tanks vector-search relevance against the
    scheme's own reference docs and the question comes back "not covered".
    Conservative by construction: a word only gets corrected when it does NOT
    already exactly match a scheme alias (nothing to fix) and DOES fuzzy-match
    one closely enough — so it can't mangle an unrelated word."""
    if not question:
        return question

    # A scheme already named correctly elsewhere in the question (exact match,
    # e.g. "CM ELEVATE") must not also be "corrected" word-by-word below — the
    # lone word "Elevate" fuzzy-matches the "cmelevate" alias on its own
    # (fuzz.ratio("elevate", "cmelevate") ~= 87.5, over the 80 threshold), so
    # without this guard "CM ELEVATE" gets the already-present "CM" duplicated
    # into "CM CM Elevate" (and worse on a second pass, e.g. a resumed
    # clarification chip, into "CM CM CM Elevate").
    #
    # Restored from the pre-LangGraph codebase, where it was present and
    # working: this rewrite kept only the trailing-duplicate collapse below,
    # which cannot cover this case — the duplication here is LEADING ("CM CM
    # Elevate"), not trailing ("Focus Plus plus"). The two fixes are
    # complementary, not alternatives: this guard skips a scheme that is
    # already spelled correctly, the collapse below repairs a genuine
    # misspelling that landed next to a real word. Every correctly-spelled
    # "CM Elevate" question was mangled without this.
    # See tests/unit/test_scheme_spelling_no_duplication.py.
    _already_named = {s for s, pat in _SCHEME_NAME_PATTERN.items() if pat.search(question)}

    def _sub(m: "re.Match") -> str:
        word = m.group(0)
        if len(word) < 5:
            return word
        wl = word.lower()
        for scheme, aliases in _SCHEME_FUZZY_ALIASES.items():
            if scheme in _already_named:
                continue
            if wl in aliases:
                return word
            if any(fuzz.ratio(wl, a) >= _FUZZY_SCHEME_ACCEPT for a in aliases):
                return _SCHEME_CANONICAL_SPELLING[scheme]
        return word

    corrected = re.sub(r"[A-Za-z]+", _sub, question)
    # A single-word misspelling of a multi-word canonical name ("facus" ->
    # "Focus Plus") can land directly next to the text's own real occurrence
    # of that name's trailing word ("facus plus" -> "Focus Plus plus") —
    # found during a 5.1 end-to-end verification pass, reproducible, not
    # hypothetical. Collapse the accidental duplicate rather than leave a
    # doubled word in text this function's own purpose is to clean up for
    # vector-search relevance.
    for canon in _SCHEME_CANONICAL_SPELLING.values():
        if " " in canon:
            trailing = canon.rsplit(" ", 1)[1]
            corrected = re.sub(
                rf"\b{re.escape(canon)}\s+{re.escape(trailing)}\b",
                canon, corrected, flags=re.IGNORECASE)
    return corrected


# The user explicitly wants a cross-scheme answer — honour it, don't ask.
_EXPLICIT_BOTH = re.compile(
    r"\b(both schemes?|all schemes?|each scheme|per scheme|by scheme|across schemes?|"
    r"every scheme|either scheme|the two schemes|scheme[\s-]?wise)\b",
    re.IGNORECASE,
)
# A breakdown over CM Elevate's own sub-schemes ("by scheme", "each scheme",
# "scheme-wise") — see _shortcut_scheme. Not "both/all/across schemes", which
# genuinely compare the four programmes.
_SUB_SCHEME_BREAKDOWN = re.compile(
    r"\b(each scheme|per scheme|by scheme|every scheme|scheme[\s-]?wise|"
    r"(?:which|what) scheme)\b",
    re.IGNORECASE,
)
# Vocabulary that only makes sense for ONE scheme, so we can infer it without
# asking even when the scheme is not named. Kept deliberately narrow — a term
# that both schemes use (e.g. "beneficiaries", "paid", "pending", "amount")
# must NOT appear here, or an ambiguous question gets silently mis-routed.
_MGNREGA_ONLY_TERMS = re.compile(
    r"\b(person[\s-]?days?|job cards?|100[\s-]?days?|hundred days?|muster|"
    # "households/persons [were/are/have been] employed" — the naive adjacent
    # phrase ("households? employed") missed the common "persons WERE employed"
    # wording (TC-024: a plain past-tense employment question with no scheme
    # named kept falling through to the scheme-clarification prompt).
    r"households?\s+(?:were\s+|are\s+|have\s+been\s+|has\s+been\s+)?employed|"
    r"persons?\s+(?:were\s+|are\s+|have\s+been\s+|has\s+been\s+)?employed|"
    # "received employment" is as common a phrasing as "were employed" — same
    # gap as above, just a different verb (DATA-004 used exactly this).
    r"(?:households?|persons?)\s+receiv\w*\s+employment|"
    # "women [were/are] provided/given employment" / "women employed" — same
    # missing-verb-phrasing gap as above (DATA-008 used exactly this; there
    # was no women-employment pattern here at all before, only in edge.py's
    # unrelated domain whitelist).
    r"women\s+(?:were\s+|are\s+)?(?:provided|given)\s+employment|"
    r"women\s+employ\w*|"
    # assembly_constituency data exists ONLY in mgnrega_employment (see
    # entity_resolver's assembly_constituency handling) — naming a constituency
    # pins the scheme on its own even with no other MGNREGA word present.
    r"assembly constituenc\w*|\bAC\s*\d+\b|"
    # unskilled/semi-skilled wage(s) — "wage" without the "s?" only matched the
    # singular; "unskilled wages" (the common plural phrasing, DATA-010) never
    # matched because \b after "wage" can't land inside "wages".
    r"unskilled wages?|semi[\s-]?skilled|"
    r"labour budget|works? demanded|wage employment|employment guarantee)\b",
    re.IGNORECASE,
)
_PMAY_ONLY_TERMS = re.compile(
    r"\b(house|houses|housing|dwelling units?|pucca house|kutcha house|"
    r"sanctioned houses?|instal{1,2}ments?|geotag|"
    # "tranche"/"tranch" is deliberately NOT here, even though PMAY-G also has
    # an installments_paid column. Focus Plus's own vocabulary IS "tranche"
    # (its stored column is literally tranche_label); PMAY-G's own vocabulary
    # is "installment" (instal?ments? above already covers it). A bare
    # "tranche 1 vs tranche 2" with no scheme named should default to Focus
    # Plus, not pause — see _FOCUSPLUS_ONLY_TERMS below, which is where
    # "tranche" is claimed.
    r"completion certificate|house status|awaas|awas|"
    # "sanctioned"/"released"/"pending" amount phrasing is PMAY-specific — MGNREGA
    # never "sanctions" anything (it has expenditure), CM Elevate has no money
    # column at all, and Focus Plus vocabulary is "disbursement"/"payment", not
    # "sanctioned". Without these, a bare "how much sanctioned amount has been
    # released in [village]?" (no scheme named) fell through to an unnecessary
    # "which scheme?" pause instead of being understood as PMAY-G.
    # Plural "amounts"/"numbers" ('s?') — the singular-only forms below missed
    # "sanctioned amountS" (PMAY-OFF-023) and "amount released" is fine as a
    # fixed phrase, but sanction NUMBER(S) (PMAY-OFF-026) had no pattern at all.
    r"sanctioned amounts?|amounts? (?:released|sanctioned|pending)|"
    r"released amounts?|pending amounts?|sanction dates?|sanction numbers?|"
    # "received (any/the/no) amount", "received full/partial amount" — the
    # release-status phrasing PMAY-OFF-008/009/010 use, distinct from the
    # "amount released" form already covered above. The qualifier
    # (any/the/no/full/partial) is REQUIRED, not optional — found during a
    # 5.1 end-to-end verification pass that the optional form let a bare,
    # scheme-generic "beneficiaries received amount" (equally plausible for
    # Focus Plus's own disbursement vocabulary) silently infer PMAY-G alone,
    # which is exactly the mis-routing risk this whole vocabulary block's own
    # design comment above warns against. "received sanctioned amount" (no
    # qualifier word) still classifies correctly regardless of this fix —
    # it's already caught by the "sanctioned amounts?" alternative earlier
    # in this same pattern.
    r"receiv\w*\s+(?:any|the|no|full|partial)\s+(?:sanctioned\s+)?amounts?)\b",
    re.IGNORECASE,
)
# Focus Plus is a Meghalaya STATE farmer cash-benefit scheme. These terms name it or
# its scheme-specific machinery and belong to no other scheme. "tranche"/"tranch" is
# claimed HERE, not left shared with PMAY-G: it's Focus Plus's actual vocabulary (the
# stored column is tranche_label), while PMAY-G's own word for the same idea is
# "installment" (see _PMAY_ONLY_TERMS). "batch"/"disbursement" are still left out —
# those really are generic enough that an unnamed question using only those still
# asks "which scheme?".
_FOCUSPLUS_ONLY_TERMS = re.compile(
    r"\bfocus[\s-]?plus\b|\bfocus\s*\+|\bfocusplus\b|"
    r"\btranche?s?\b|"
    r"\bproducer group\b|\bproducer-group\b|\bproducer groups\b|"
    # "Sakania PG", "PG members", "how many PGs" — the short form users
    # actually type; PGs exist only in FOCUS (curated.v_focus_legacy).
    r"\bpgs?\b|\blamps?\b|\bfocus\s+legacy\b|"
    r"\bmeghalayaone\b|\bmbda\b|\bmeghalaya basin development\b|"
    r"\bfocus\+?\s*card\b|\b93k\b|\b12\.5k\b",
    re.IGNORECASE,
)
# CM Elevate covers 15 sub-schemes under one programme. These terms name the
# programme itself or its scheme-specific vocabulary that belongs to no other
# scheme. "on hold" / "verification" / "application mode" are deliberately left
# out — they read as generic status words, so an unnamed question using only
# those still asks "which scheme?".
_CMELEVATE_ONLY_TERMS = re.compile(
    r"\bcm[\s-]?elevate\b|\bcmelevate\b|"
    r"\bpiggery\b|\bpoultry\b|\bgoat farming\b|\bwarehouse scheme\b|"
    r"\bsericulture\b|\bmotorcaravan\b|\bagro tourism villa\b|"
    r"\bprime small enterprise\b|\bprime tourism vehicle\b|"
    r"\bprime agriculture response vehicle\b|\bgreen taxi\b|"
    r"\bcinema theatre scheme\b|\bsports and wellness centre\b|"
    r"\bany business venture\b|\brequest_?id\b|"
    # CM Elevate is the only scheme whose rows are APPLICATIONS by APPLICANTS
    # (one row per application — v_cm_elevate); no other scheme holds either.
    # Without these, KPI questions that never say "CM Elevate" ("How many
    # applicants have applied to more than one scheme?", "... sent back or
    # asked to resubmit?") paused on "which scheme?" (2026-09-23 KPI sweep).
    # A question that also uses another scheme's vocabulary still asks.
    r"\bapplicants?\b|\bapplications?\b|\bresubmi\w*\b|\bsent\s+back\b|"
    r"\bloan\s+default\w*\b|\bcm\s*connect\w*\b|\ballotment\s+category\b|"
    r"\bapproval\s+workflow\b",
    re.IGNORECASE,
)


def _infer_scheme_from_terms(question: str) -> list[str] | None:
    """A single scheme implied by scheme-specific vocabulary, or None if the
    question could plausibly mean more than one."""
    hits = [
        s for s, rx in (
            ("MGNREGA", _MGNREGA_ONLY_TERMS),
            ("PMAY-G", _PMAY_ONLY_TERMS),
            ("Focus Plus", _FOCUSPLUS_ONLY_TERMS),
            ("CM Elevate", _CMELEVATE_ONLY_TERMS),
        ) if rx.search(question)
    ]
    return hits if len(hits) == 1 else None


# A resumed one-tap question is built by naming the scheme in the stem. Naively
# appending " for <scheme>" reads fine for a DATA stem ("total person-days for
# MGNREGA") but produces broken phrasing for a KNOWLEDGE stem that already says
# the generic word "scheme" ("tell me about scheme" -> "tell me about scheme for
# Focus Plus") — that phrasing is grammatically odd enough that the RAG answer
# composer sometimes reads it as asking about a DIFFERENT, uncovered scheme and
# refuses with "not covered" even though the retrieved passages score well
# above the medium-confidence floor (verified: top score 0.77, well above the
# 0.55 floor, yet the composer still said "not covered" on this exact phrasing).
# When the stem already names "scheme(s)" generically, replace that word with
# the actual scheme name instead of appending — "tell me about scheme" becomes
# "tell me about Focus Plus", which both reads naturally and matches how the
# reference docs open ("Focus Plus is ...").
_GENERIC_SCHEME_WORD = re.compile(r"\bschemes?\b", re.IGNORECASE)


def _scheme_option_question(stem: str, scheme: str) -> str:
    if _GENERIC_SCHEME_WORD.search(stem):
        return _GENERIC_SCHEME_WORD.sub(scheme, stem, count=1)
    return f"{stem} for {scheme}"


def _scheme_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    options = [
        {"label": "MGNREGA (rural employment)",
         "question": _scheme_option_question(stem, "MGNREGA")},
        {"label": "PMAY-G (rural housing)",
         "question": _scheme_option_question(stem, "PMAY-G")},
        {"label": "Focus Plus (farmer cash benefit)",
         "question": _scheme_option_question(stem, "Focus Plus")},
        {"label": "CM Elevate (livelihood / enterprise schemes)",
         "question": _scheme_option_question(stem, "CM Elevate")},
        {"label": "Compare across schemes",
         "question": f"{stem} across MGNREGA, PMAY-G, Focus Plus and CM Elevate"},
    ]
    return ClarificationNeeded(
        "Which scheme does your question concern — MGNREGA, PMAY-G, Focus Plus, or "
        "CM Elevate? Please select one, or choose to compare across schemes.",
        options=options,
        rule="scheme-not-specified",
    )


# Plain-language, user-facing scheme summaries — separate from SCHEME_CATALOG
# in schema_context.py, which is written for the SQL-generation prompt (DB
# grain, money units, join keys) and reads as database jargon to an end user.
_SCHEME_USER_SUMMARY = {
    "MGNREGA": "Rural employment guarantee scheme — up to 100 days of guaranteed "
               "wage employment per household per year.",
    "PMAY-G": "Rural housing scheme (Gramin) — financial assistance to build a "
              "pucca house for eligible rural households.",
    "Focus Plus": "Meghalaya state farmer cash-benefit scheme — direct cash "
                  "payments (DBT) to registered farmers.",
    "CM Elevate": "Meghalaya livelihood & enterprise support programme — covers "
                  "15 individual schemes (piggery, poultry, small enterprise "
                  "loans, tourism vehicles, and more) under one umbrella.",
}

# "What schemes are available?" / "what can you help with?" — answered directly
# and concisely instead of falling through to RAG, which has no single document
# listing all 4 schemes and tends to elaborate at length on whichever one scores
# highest in vector search (QA repeatedly saw an over-detailed PMAY-only answer).
_SCHEME_LISTING_CUE = re.compile(
    r"\b(what|which) schemes?\b|\bschemes? (?:are|is) available\b|"
    r"\blist (?:the |all )?schemes?\b|\bschemes? (?:do you|you) (?:support|cover|know|have)\b|"
    r"\bwhat (?:can|do) you (?:help with|assist with|cover)\b",
    re.IGNORECASE,
)

# A vague eligibility ask — "is there any scheme that can help my family?",
# "which scheme should I apply for?" — carries no vocabulary naming a scheme
# outright, so it used to fall into the "which scheme does your question
# concern?" pause. That pause is the wrong move here: unlike a DATA question
# (where guessing the scheme risks a confidently wrong number), there's
# nothing to get wrong about naming all four — so skip the tap and lay them
# out directly. When the wording DOES carry scheme-specific vocabulary (e.g.
# "...to help me build a house") _infer_scheme_from_terms already pins it to
# one scheme and the "which scheme?" rule never pauses in the first place —
# this cue only needs to cover the genuinely scheme-agnostic case, so it
# defers to that inference rather than overriding it.
_SCHEME_HELP_CUE = re.compile(
    r"\bis there (?:any|a) (?:govt\.?|government )?schemes?\b|"
    r"\b(?:any|a) scheme (?:that|which|to) (?:can |could )?help\b|"
    r"\bscheme(?:s)? (?:that|which) (?:can|could) help\b|"
    r"\bwhich scheme (?:can|could|should) (?:i|we)\b|"
    r"\bwhat scheme should (?:i|we)\b",
    re.IGNORECASE,
)


def _scheme_listing_answer(question: str) -> "dict | None":
    explicit = _SCHEME_LISTING_CUE.search(question or "")
    # "Which scheme has the lowest verification rate / the most incomplete
    # data / is the pipeline stuck for?" asks for a figure, not the list of
    # schemes we cover — it got the canned list instead (2026-09-23 KPI sweep:
    # C4-04, C2-08, DC-04).
    if explicit and (_DATA_HINTS.search(question or "") or _DATA_SHAPE_CUE.search(question or "")):
        return None
    if not explicit:
        if not _SCHEME_HELP_CUE.search(question or ""):
            return None
        # A "help me" ask that already names scheme-specific vocabulary (a
        # house, job cards, farmer cash, an enterprise, ...) has a clear
        # intent to route on — leave it to the normal KNOWLEDGE/RAG path
        # instead of burying that signal under the generic four-scheme list.
        if _infer_scheme_from_terms(question) is not None:
            return None
    lines = [f"- **{name}** — {desc}" for name, desc in _SCHEME_USER_SUMMARY.items()]
    answer = (
        "I cover four Meghalaya government schemes:\n\n" + "\n".join(lines) +
        "\n\nAsk me about any of these — eligibility, benefits, how to apply, "
        "or the actual data (numbers, by district or year)."
    )
    return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
            "answer": answer, **_empty_data_fields()}


# "What is the difference between the schemes?" / "compare MGNREGA and PMAY-G" as
# a KNOWLEDGE question — no per-scheme reference doc contains a cross-scheme
# comparison, so plain RAG retrieval reliably comes back "not covered". Compose
# a structured side-by-side directly from _SCHEME_USER_SUMMARY instead.
_SCHEME_COMPARISON_CUE = re.compile(
    r"\bdifference between\b[^?]{0,40}\bschemes?\b|\bschemes?\b[^?]{0,40}\bdiffer(?:ence)?\b|"
    r"\bcompare\b[^?]{0,40}\bschemes?\b|\bhow (?:do|does)\b[^?]{0,40}\bschemes?\b[^?]{0,20}\bdiffer\b|"
    r"\bdifference between\b.{0,60}\b(mgnrega|pmay|focus\s*plus|cm\s*elevate)\b.{0,20}\b(and|vs\.?|versus)\b",
    re.IGNORECASE,
)
# "compare Focus Plus and CM Elevate schemes BY BENEFICIARIES" / "... by amount" /
# "... by expenditure" names a real figure to pull from megh_db, not "how do the
# schemes differ conceptually" — _SCHEME_COMPARISON_CUE's bare "compare ... schemes"
# still matches that (it doesn't require a metric to be absent), so without this
# guard _scheme_comparison_answer intercepts a genuine statistics question at step
# 0-a, before classify_intent / DATA routing ever runs, and answers it with the
# canned RAG-style scheme blurb instead of a queried number.
_SCHEME_COMPARISON_METRIC_GUARD = re.compile(
    r"\b(beneficiar\w*|amount|amounts|expenditure|spend\w*|wages?|"
    r"person[\s-]?days?|job\s?cards?|houses?|disburs\w*|payments?|"
    r"number of|how many|how much|count of|total|percentage|per ?cent|"
    r"\brate\b)\b",
    re.IGNORECASE,
)


def _scheme_comparison_clarification() -> "ClarificationNeeded":
    names = list(SCHEME_CATALOG)
    options = [
        {"label": f"{a} vs {b}", "question": f"difference between {a} and {b}"}
        for a, b in itertools.combinations(names, 2)
    ]
    options.append({"label": "All four schemes",
                     "question": "difference between MGNREGA, PMAY-G, Focus Plus and CM Elevate"})
    return ClarificationNeeded(
        "Which schemes would you like to compare — MGNREGA, PMAY-G, Focus Plus, or "
        "CM Elevate? Pick a pair, or compare all four.",
        options=options,
        rule="scheme-comparison-not-specified",
    )


def _scheme_comparison_answer(question: str) -> "dict | None":
    if not _SCHEME_COMPARISON_CUE.search(question or ""):
        return None
    if _SCHEME_COMPARISON_METRIC_GUARD.search(question or ""):
        return None  # names a real figure — let classify_intent send it to DATA
    named = _named_schemes(question)
    if len(named) < 2:
        raise _scheme_comparison_clarification()
    targets = named
    lines = [f"- **{name}** — {_SCHEME_USER_SUMMARY.get(name, '')}" for name in targets]
    answer = (
        "Here's a high-level comparison:\n\n" + "\n".join(lines) +
        "\n\nAsk about a specific one — eligibility, benefits, or the application "
        "process — for more detail."
    )
    return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
            "answer": answer, **_empty_data_fields()}


# ── Named a scheme we simply don't hold ─────────────────────────────────────
# A user can reasonably name another Meghalaya / central scheme ("PM-KISAN",
# "Ujjwala", "Jal Jeevan"). The right answer is not the generic "which scheme?"
# prompt — it's to say plainly that only four schemes are loaded right now,
# then let them pick one. Keep this list to real scheme names/aliases; a bare
# word that is also scheme vocabulary must not appear. CM Elevate is now a
# supported scheme (see _SCHEME_NAME_PATTERN) and must NOT appear here.
_UNSUPPORTED_SCHEME = re.compile(
    r"\b("
    r"prime\s+meghalaya|meghalaya\s+prime|"
    r"pm[\s-]?kisan|pmkisan|kisan\s+samman|"
    r"pmay[\s-]?u\b|pmay\s+urban|awas\s+yojana\s+urban|"
    r"pmgsy|gram\s+sadak|"
    r"pmuy|ujjwala|ujwala|"
    r"saubhagya|"
    r"jal\s+jeevan(\s+mission)?|jjm\b|har\s+ghar\s+jal|nal\s+se\s+jal|"
    r"ayushman(\s+bharat)?|pm[\s-]?jay|pmjay|"
    r"mhis\b|cmhis\b|megha\s+health|"
    r"nsap\b|ignoaps|old[\s-]?age\s+pension|widow\s+pension|disability\s+pension|"
    r"nrlm\b|day[\s-]?nrlm|aajeevika|ajeevika|livelihoods?\s+mission|"
    r"swachh\s+bharat|sbm\b|nirmal\s+bharat|"
    r"mid[\s-]?day\s+meal|pm[\s-]?poshan|"
    r"icds\b|anganwadi|poshan\s+abhiyaan?|"
    r"kanyashree|ladli|sukanya|"
    r"atal\s+pension|apy\b|"
    r"mudra|pmmy\b|stand[\s-]?up\s+india|"
    r"kisan\s+credit\s+card|kcc\b|"
    r"fasal\s+bima|pmfby|crop\s+insurance|"
    r"e[\s-]?shram|"
    r"nfsa\b|one\s+nation\s+one\s+ration|public\s+distribution|ration\s+card"
    r")\b",
    re.IGNORECASE,
)


def _unsupported_scheme_named(question: str) -> "str | None":
    """The name of a scheme the user asked about that we don't hold — or None.
    Only fires when NO supported scheme is also named, so mixed questions
    ("compare CM Elevate with MGNREGA") still route normally. The unsupported
    match is blanked out before the supported-scheme check so a near-miss like
    "PMAY-U" isn't swallowed by the PMAY-G pattern."""
    m = _UNSUPPORTED_SCHEME.search(question or "")
    if not m:
        return None
    without = (question[:m.start()] + " " + question[m.end():])
    if any(p.search(without) for p in _SCHEME_NAME_PATTERN.values()):
        return None
    return m.group(0)


def _unsupported_scheme_clarification(question: str, name: str) -> "ClarificationNeeded":
    # Drop the unsupported scheme name (plus any preposition left dangling by
    # its removal, e.g. "... years in pm-kisan?" -> "... years") so the
    # resumed one-tap question reads cleanly.
    stem = re.sub(re.escape(name), " ", question, flags=re.IGNORECASE)
    stem = re.sub(r"\s+", " ", stem).strip().rstrip(" ?.")
    stem = re.sub(r"\s+(?:in|for|of|under|from|about|on)$", "", stem, flags=re.IGNORECASE).strip()
    stem = stem or question.strip().rstrip(" ?.")
    options = [
        {"label": "MGNREGA (rural employment)",
         "question": _scheme_option_question(stem, "MGNREGA")},
        {"label": "PMAY-G (rural housing)",
         "question": _scheme_option_question(stem, "PMAY-G")},
        {"label": "Focus Plus (farmer cash benefit)",
         "question": _scheme_option_question(stem, "Focus Plus")},
        {"label": "CM Elevate (livelihood / enterprise schemes)",
         "question": _scheme_option_question(stem, "CM Elevate")},
        {"label": "Compare across schemes",
         "question": f"{stem} across MGNREGA, PMAY-G, Focus Plus and CM Elevate"},
    ]
    return ClarificationNeeded(
        f'I don\'t have any data for "{name.strip()}". Right now I only hold '
        "four schemes — MGNREGA, PMAY-G, Focus Plus and CM Elevate. Pick one of those "
        "and I'll answer.",
        options=options,
        rule="scheme-not-available",
    )


# ── Bank / financial-channel details — not held for most loaded schemes ─────
# Focus Plus now exposes bank_name_raw via curated.v_focus_plus (added so
# bank-wise disbursement questions can be answered), but it has no
# account-number/IFSC field, so those specific asks still need the
# not-held explanation. PMAY-G, CM Elevate and MGNREGA never captured any
# bank field at ingest at all. Without this check an account/IFSC question
# reaches SQL generation, which correctly finds no column to use but can only
# hand back a bare "not available in this data" — true, but it doesn't say
# *why*, so route it to a real explanation up front.
_BANK_REQUESTED = re.compile(
    r"\bbanks?\b|\bbanking\b|\bifsc\b|\bbank[\s-]?account|\baccount[\s-]?number|"
    r"\bbank[\s-]?wise\b|\bbank[\s-]?transfer|\bdbt\b|\blifcom\b",
    re.IGNORECASE,
)
# Focus Plus only lacks account-number/IFSC fields — bare bank-name questions
# ("which bank", "bank-wise disbursement") should reach SQL generation instead.
_BANK_ACCOUNT_DETAIL_REQUESTED = re.compile(
    r"\bifsc\b|\bbank[\s-]?account|\baccount[\s-]?number|\bbank[\s-]?transfer|"
    r"\bdbt\b",
    re.IGNORECASE,
)
_BANK_NOT_HELD_TEXT = {
    "Focus Plus": (
        "Account numbers and IFSC codes aren't held for Focus Plus — only the "
        "bank name is. Shall I answer using bank name instead?"
    ),
    "CM Elevate": (
        "There is no loan-channel field for CM Elevate — Bank and LIFCOM are not "
        "recorded, and no payment of any kind is held for this scheme. Shall I "
        "answer on applications by scheme or district instead?"
    ),
    "PMAY-G": (
        "Bank transfer status, DBT outcomes and account details are not held for "
        "PMAY-G — only the amount released and the number of installments are. "
        "Shall I use those instead?"
    ),
    "MGNREGA": (
        "Bank details are not held for MGNREGA — only wages, person-days, job "
        "cards and expenditure are. Shall I answer using one of those instead?"
    ),
}
_BANK_GENERIC_TEXT = (
    "Bank name is only held for Focus Plus — MGNREGA, PMAY-G and CM Elevate "
    "never captured a bank field at ingest, and none of the four schemes hold "
    "account numbers or IFSC codes. Shall I answer using Focus Plus bank name, "
    "or by scheme, district, block or village instead?"
)


# ── §11.4 PII — generated SQL asked for a blocklisted column (app/core/pii_guard.py) ─
# Deliberately never names the blocklisted column in user-facing text (that
# goes to the log only, in execute_with_repair) — this is a refusal, not a
# data-availability explanation, so the wording stays generic per scheme.
_PII_NOT_AVAILABLE_TEXT = {
    "Focus Plus": (
        "Focus Plus can't show individual member IDs or pincodes — those are "
        "personal identifiers. Shall I answer with a count instead, or a "
        "district/block breakdown?"
    ),
    "CM Elevate": (
        "CM Elevate can't show personal applicant details (date of birth, "
        "address, ID or account numbers) — only application, scheme, "
        "geography and status details are available. Shall I answer using "
        "one of those instead?"
    ),
}
_PII_GENERIC_TEXT = (
    "That detail includes a personal identifier that can't be shown "
    "individually. Shall I answer with an aggregate count or a different "
    "breakdown instead?"
)


def _pii_not_available_clarification(schemes: list[str]) -> "ClarificationNeeded":
    text = _PII_NOT_AVAILABLE_TEXT[schemes[0]] if len(schemes) == 1 and schemes[0] in _PII_NOT_AVAILABLE_TEXT \
        else _PII_GENERIC_TEXT
    return ClarificationNeeded(text, rule="pii-column-blocked")


def _named_or_inferred_schemes(question: str) -> list[str]:
    named = [s for s, rx in _SCHEME_NAME_PATTERN.items() if rx.search(question)]
    return named or _infer_scheme_from_terms(question) or []


def _bank_clarification(question: str) -> "ClarificationNeeded | None":
    schemes = _named_or_inferred_schemes(question)
    is_account_detail = bool(_BANK_ACCOUNT_DETAIL_REQUESTED.search(question))
    if not is_account_detail and schemes == ["Focus Plus"]:
        # Bare bank-name question scoped to Focus Plus only — bank_name_raw is
        # queryable via curated.v_focus_plus, so let SQL generation handle it.
        return None
    text = _BANK_NOT_HELD_TEXT[schemes[0]] if len(schemes) == 1 else _BANK_GENERIC_TEXT
    return ClarificationNeeded(text, rule="column-not-held")


# ── Administrative expenditure — deliberately excluded from reporting ──────
# The raw source has adm_exp_rec / adm_exp_non_rec / adm_exp_total (MGNREGA) and
# an equivalent programme-expenditure figure (PMAY-G), but both are intentionally
# left out of the curated views/facts (data/mgnrega/README.md marks them
# **excluded**; mgnrega_classification_rules.yaml and pmay_classification_rules.yaml
# both define a dedicated "administrative_expenditure_requested" condition for
# exactly this). That YAML condition was never wired into the live pipeline
# (see the "deliberately NOT loaded here yet" note in annotations.py), so without
# this check the question reached SQL generation, which has no such column to
# read and either errors or returns a wrong/empty figure instead of explaining
# the exclusion.
_ADMIN_EXPENDITURE_REQUESTED = re.compile(
    r"\badministrative\s+(?:expenditure|expense|cost|spend(?:ing)?)\b|"
    r"\badmin\s+(?:expenditure|expense|cost)\b|\boverhead\s+(?:expenditure|cost)s?\b|"
    r"\bprogramme\s+expenditure\b|\bprogram\s+expenditure\b",
    re.IGNORECASE,
)
_ADMIN_EXPENDITURE_NOT_HELD_TEXT = {
    "MGNREGA": (
        "Administrative expenditure is deliberately excluded from MGNREGA reporting "
        "here — only unskilled wage, semi-skilled wage, material and total expenditure "
        "are held. Did you mean total expenditure instead?"
    ),
    "PMAY-G": (
        "Administrative and programme expenditure are not held for PMAY-G — only the "
        "per-house sanctioned and released amounts are. Did you mean amount released "
        "instead?"
    ),
}
_ADMIN_EXPENDITURE_GENERIC_TEXT = (
    "Administrative expenditure isn't held for querying in any of the schemes I "
    "cover — MGNREGA reports only wage/material/total expenditure, and PMAY-G only "
    "sanctioned and released amounts. Shall I answer using one of those instead?"
)


def _admin_expenditure_clarification(question: str) -> "ClarificationNeeded":
    schemes = _named_or_inferred_schemes(question)
    if len(schemes) == 1 and schemes[0] in _ADMIN_EXPENDITURE_NOT_HELD_TEXT:
        text = _ADMIN_EXPENDITURE_NOT_HELD_TEXT[schemes[0]]
    else:
        text = _ADMIN_EXPENDITURE_GENERIC_TEXT
    return ClarificationNeeded(text, rule="column-not-held")


# ── "What % were women?" — women_employment_provided has no confirmed ratio ──
# schema_context.py's MGNREGA rule 6: women_employment_provided may be reported
# as a raw count, but NEVER as a computed ratio/percentage/share — its
# definition (persons vs households, and against which denominator) is
# unconfirmed, so a computed percentage risks a confidently wrong number. The
# SQL-gen prompt already carries this as a text rule, but a question that
# explicitly demands the percentage can still make the model try (and fail
# oddly) rather than explain why — so intercept it here, before SQL
# generation, the same way the bank / admin-expenditure checks do.
# PMAY-G's analogous "share of houses allotted to women" IS a well-defined,
# supported computation (house_alloted_to has an explicit Woman* value set) —
# excluded here via _WOMEN_SHARE_PMAYG_CONTEXT so this doesn't also block that.
_WOMEN_SHARE_REQUESTED = re.compile(
    r"\b(percentage|percent|%|share|ratio|proportion)\b[^?.!]{0,40}\bwomen\b|"
    r"\bwomen\b[^?.!]{0,40}\b(percentage|percent|%|share|ratio|proportion)\b",
    re.IGNORECASE,
)
_WOMEN_SHARE_PMAYG_CONTEXT = re.compile(
    r"\bhouses?\b|\bdwelling\b|\ballot\w*\b", re.IGNORECASE,
)
_WOMEN_SHARE_NOT_COMPUTABLE_TEXT = (
    "A reliable percentage or share can't be computed for women's employment — "
    "women_employment_provided's exact definition (which denominator it's a "
    "share of) isn't confirmed in the source data, so publishing a ratio risks "
    "a misleading number. I can give you the raw count of women provided "
    "employment instead — would that help?"
)


def _women_share_clarification(question: str) -> "ClarificationNeeded":
    return ClarificationNeeded(_WOMEN_SHARE_NOT_COMPUTABLE_TEXT, rule="column-not-held")


# ── "Top how many?" clarification ───────────────────────────────────────────
# A ranking question over a dimension ("top districts", "which blocks spent the
# most", "rank villages by person-days") that names no count. Silently defaulting
# to a fixed top-N is a guess the user can't see or correct; a one-tap follow-up
# ("Top 3 / 5 / 10 / all") is cheaper than returning the wrong list length.
_TOPN_CHOICES = (3, 5, 10)


def _inject_topn(question: str, n: int) -> str:
    """Rewrite the ranking question so it states the count `n`, so the resumed
    turn is a complete standalone question the SQL layer can LIMIT on."""
    q = question.strip().rstrip(" ?.")
    new_q, hit = re.subn(r"\btop\b(?![\s-]*\d)", f"top {n}", q, count=1, flags=re.IGNORECASE)
    if hit:
        return new_q + "?"
    # No literal "top" to splice into ("which blocks spent the most") — append it.
    return f"{q}, showing only the top {n}?"


def _topn_clarification(question: str) -> "ClarificationNeeded":
    q = question.strip().rstrip(" ?.")
    options = [{"label": f"Top {n}", "question": _inject_topn(question, n)} for n in _TOPN_CHOICES]
    options.append({"label": "All of them", "question": f"{q}, return every row with no limit?"})
    return ClarificationNeeded(
        "How many results should be returned — the top 3, the top 5, the top 10, "
        "or the complete list?",
        options=options,
        rule="ranking-count-not-specified",
    )


# ── "Which area / year?" clarification ──────────────────────────────────────
# An aggregate question ("how many houses sanctioned", "total MGNREGA
# expenditure", or a bare "show MGNREGA spend") that names no place and no year
# gets answered statewide across every year — a scope the user never asked for
# and can't see in the reply. One free-text follow-up ("West Garo Hills
# 2023-24") is cheaper than a number that silently means something else.
# Applies to MGNREGA and PMAY-G alike.
_AGGREGATE_CUE = re.compile(
    r"\b(how many|how much|number of|count of|no\.? of|total(?:\s+number)?|"
    r"sum of|what(?:'s| is| was) the total|average|avg|mean)\b",
    re.IGNORECASE,
)
# A bare metric noun with no quantity word in front of it — "show MGNREGA
# spend", "PMAY-G houses", "person-days". On its own the metric name still means
# "give me the total <metric>", so it needs a place and a year just as much as
# an explicit "how much" does. Kept to unambiguous scheme metrics — generic
# words ("amount", "money", "funds", "works") are left out so a membership or
# list question isn't dragged into a scope pause.
_BARE_METRIC_CUE = re.compile(
    r"\b(person[\s-]?days?|expenditure|spend(?:ing)?|spent|"
    r"wages?|wage bill|job cards?|muster rolls?|"
    r"houses?(?:\s+(?:sanctioned|completed|approved|released|pending))?|"
    r"dwelling units?|sanctioned amount|amount released|"
    r"instal{1,2}ments?|disbursements?|utili[sz]ation)\b",
    re.IGNORECASE,
)
# The question already fixes its own scope (a breakdown, a trend, a comparison
# across a dimension, or an explicit "all of Meghalaya") — nothing to ask.
_HAS_BREAKDOWN = re.compile(
    r"\bby (?:district|block|village|panchayat|gp|year|month)\b|"
    r"\b(?:per|each|every|for all|across all|all the) "
    r"(?:district|block|village|panchayat|year|month)s?\b|"
    r"\b(?:district|block|village|year)[\s-]?wise\b|"
    r"\bbreak[\s-]?down\b|\btrend\b|\byear[\s-]?on[\s-]?year\b|"
    r"\bover (?:the )?(?:last|past) \w+ years?\b|"
    r"\bcompare\b|\bcomparison\b|\bversus\b|\bvs\.?\b|"
    r"\bcorrelat\w*|\brelationship between\b|\blinked (?:to|with)\b|"
    r"\b(?:districts?|blocks?|villages?|panchayats?|gps?)\s+"
    r"(?:with|where|that|having|which)\b|"
    # A rank window over a geography dimension — "top 5 districts", "bottom
    # blocks", "10 largest villages". It inherently spans every area in that
    # dimension, so geography is already scoped; only the year is still open.
    r"\b(?:top|bottom|leading|largest|biggest|smallest|highest|lowest)\s+"
    r"(?:\d+\s+)?(?:districts?|blocks?|villages?|panchayats?|gps?)\b|"
    r"\b\d+\s+(?:largest|biggest|smallest|highest|lowest)\s+"
    r"(?:districts?|blocks?|villages?|panchayats?|gps?)\b|"
    # "which district received the highest ...", "district with the lowest
    # ..." — the same rank-window logic as "top N districts" above, just
    # phrased as "which <geo> ... <superlative>" instead of "<superlative>
    # <geo>". Still inherently spans every area in the dimension, so
    # geography is already scoped; only the year is still open. Anchored
    # loosely (superlative anywhere within ~40 chars either side of the
    # geography noun) so "which district received the highest total
    # disbursement" and "highest total expenditure in which district" both
    # match.
    r"\bwhich (?:district|block|village|panchayat|gp)\b[^?]{0,40}\b"
    r"(?:highest|lowest|most|least|maximum|minimum|greatest|top|biggest|"
    r"largest|smallest)\b|"
    r"\b(?:highest|lowest|most|least|maximum|minimum|greatest|top|biggest|"
    r"largest|smallest)\b[^?]{0,40}\bwhich (?:district|block|village|panchayat|gp)\b|"
    r"\bacross (?:the )?(?:districts?|blocks?|villages?|panchayats?|state|years?)\b",
    re.IGNORECASE,
)
# A cross-scheme set / overlap question whose answer IS a geography list or its
# count — "how many common districts in both schemes", "which villages are
# covered by both", "districts with both MGNREGA and PMAY-G activity". Geography
# is the thing being counted, not a filter, so there is no area or year to ask
# for — it is inherently statewide across the whole data window. This must not
# swallow a plain cross-scheme metric question ("how much did both schemes
# spend"), so every branch is anchored to a geography noun.
_CROSS_SCHEME_SET_QUESTION = re.compile(
    r"\b(?:common|shared|overlapping|overlap(?:ping)?|mutual|convergen\w*|"
    r"distinct|unique)\s+(?:districts?|blocks?|villages?|panchayats?|gps?|areas?|"
    r"geograph\w+)\b|"
    r"\b(?:districts?|blocks?|villages?|panchayats?|gps?|areas?)\s+"
    r"(?:(?:are|is|were|was|that|which|have|having|has)\s+){0,2}"
    r"(?:common (?:to|across|between)|shared (?:by|between|across)|"
    r"in (?:both|all|either)|covered (?:by|under) both|"
    r"covered by (?:both )?(?:mgnrega|pmay|schemes)|"
    r"with both|have both|having both|present in both|"
    r"served by both|running both|under both|in common)\b|"
    r"\bhow many (?:districts?|blocks?|villages?|panchayats?|gps?)\b[^?]*"
    r"\b(?:both schemes?|both mgnrega and pmay|pmay and mgnrega|"
    r"in common|overlap)\b|"
    # "blocks (wise) common in both schemes", "which blocks are common in both",
    # "common blocks in both schemes" — a geography noun sitting next to both
    # "common"/"shared"/"overlap" and "both", in either order. Still anchored to
    # the geography noun so a bare metric question can't match.
    r"\b(?:districts?|blocks?|villages?|panchayats?|gps?|areas?)\b(?:[\s-]?wise)?"
    r"[^?]{0,30}\b(?:common|shared|overlap\w*|convergen\w*)\b[^?]{0,20}\bboth\b|"
    r"\b(?:common|shared|overlap\w*|convergen\w*)\b[^?]{0,20}"
    r"\b(?:districts?|blocks?|villages?|panchayats?|gps?|areas?)\b[^?]{0,20}\bboth\b",
    re.IGNORECASE,
)


# A reply to the scope pause is normally a bare fragment ("Ri Bhoi, 2023-24").
# These shapes instead mean the user dropped the earlier question and asked a
# fresh one — don't fold them into the original.
_REPLY_IS_NEW_QUESTION = re.compile(
    r"\b(how many|how much|number of|count of|what(?:'s| is| are| was) the|"
    r"who (?:is|can)|how do i|how to apply|what documents?|which documents?|"
    r"explain|define|difference between|tell me about)\b",
    re.IGNORECASE,
)


def _reply_abandons_scope_pause(reply: str) -> bool:
    """True when the reply to a 'which area / year?' pause is itself a new,
    self-standing question rather than the scope fragment we asked for."""
    r = (reply or "").strip()
    if len(r.split()) > 12:
        return True
    return bool(_REPLY_IS_NEW_QUESTION.search(r) or _KNOWLEDGE_HINTS.search(r))


# ── "Which district in this region?" clarification ─────────────────────────
# "Garo Hills" / "Khasi Hills" / "Jaintia Hills" name a hill RANGE, not a district —
# each covers several districts (region_groupings in the *_entity_resolver.yaml). When
# a question names one and no specific district, offer its districts as one-tap chips
# instead of the generic "which area?" free-text pause. Applies to every scheme.
def _swap_region_phrase(question: str, aliases: list[str], repl: str) -> str:
    """Replace the first hill-range phrase in `question` with `repl`. Longest alias
    first so 'South West Garo Hills' isn't half-matched by 'Garo Hills'."""
    forms = sorted({a for a in aliases if a}, key=len, reverse=True)
    pat = re.compile(r"\b(" + "|".join(re.escape(a) for a in forms) + r")\b", re.IGNORECASE)
    new, n = pat.subn(repl, question, count=1)
    return new if n else f"{question.rstrip(' ?.')} for {repl}"


def _region_clarification(question: str, region: dict) -> "ClarificationNeeded":
    canon = region["canonical"]
    dists = region["districts"]
    aliases = [canon, *region.get("aliases", [])]
    all_list = ", ".join(dists[:-1]) + " and " + dists[-1]
    options = [{"label": d, "question": _swap_region_phrase(question, aliases, d)}
               for d in dists]
    options.append({
        "label": f"All of {canon} combined",
        "question": _swap_region_phrase(question, aliases, f"all of {canon}"),
    })
    return ClarificationNeeded(
        f"“{canon}” is a region covering {len(dists)} districts "
        f"— {all_list}. Which district, or all of {canon} combined?",
        options=options,
        rule="region-needs-district",
    )


def _scope_clarification(question: str, schemes: list[str]) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    # District chips first (picking one still leaves the year open, so it falls
    # straight into `_year_clarification` on the next turn — a second round of
    # buttons rather than free text), then the one-tap statewide/all-years
    # shortcut, mirroring how `_year_clarification` appends its own "combined"
    # option last.
    seen: dict[str, None] = {}
    for s in schemes or []:
        for d in all_districts(s):
            seen.setdefault(d, None)
    options = [{"label": d, "question": f"{stem} for {d}"} for d in seen]
    options.append({
        "label": "All of Meghalaya, all years",
        "question": f"{stem} for all of Meghalaya, all years",
    })
    return ClarificationNeeded(
        "Which area and time period should the answer cover — a specific district, "
        "block, or village, and which financial year? Pick a district below, or "
        "choose the statewide, all-years total; you can also just type a block or "
        "village name (for example, \"West Garo Hills, 2023-24\").",
        options=options,
        rule="scope-not-specified",
    )


# ── "Which financial year?" clarification ───────────────────────────────────
# The scope gate above only fires when a question pins NO geography at all. A
# question that already fixes its place — "compare districts for MGNREGA", "total
# PMAY-G houses in West Garo Hills" — sails past it and is then answered across
# EVERY financial year at once, a scope the user never chose and can't see in the
# reply. This gate catches exactly that: geography is settled, the year is not.
# One-tap year chips (the scheme's FYs + "all years combined") resume the flow.
#
# The financial years each scheme actually holds in megh_db — the SINGLE source
# of truth for every year chip we offer (the "which year?" pause AND the
# out-of-range guard). These are DEFAULTS only: refresh_scheme_years() overwrites
# them at startup with the real DISTINCT year_key set from the curated views, so
# the chips and the guard always match the live data even after a data reload.
# Values below were verified against curated.v_employment / v_expenditure
# (MGNREGA) and curated.v_pmay (PMAY-G) on 2026-08-30 — MGNREGA covers FY
# 2022-23..2025-26; PMAY-G covers FY 2017-18..2023-24 (NOT 2024-25 / 2025-26).
# Focus Plus holds only FY 2022-23 (Tranch 1) and FY 2025-26 (Tranches 2-4) — the two
# middle years are empty for it (focusplus_schema_partitions.yaml). A three-year gap is
# expected, and asking a Focus Plus question for FY 2023-24 / 2024-25 correctly triggers
# the "that year isn't in the data" guard.
# CM Elevate is DIFFERENT IN KIND, not just sparser: it holds an empty list on
# purpose. There is no year_key, no FK to dim_year, no date column of any kind
# anywhere in fact_cm_elevate_application (cmelevate_schema_partitions.yaml
# semantic_rules.time_rule) — refresh_scheme_years() below does not even probe
# it. The year rule (_scheme_has_no_time_dimension) and _year_out_of_range_clarification both treat
# an empty list here as "no time dimension exists" and refuse a time filter
# outright instead of offering year chips.
_SCHEME_DATA_YEARS: dict[str, list[str]] = {
    "MGNREGA": ["2022-23", "2023-24", "2024-25", "2025-26"],
    "PMAY-G":  ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"],
    "Focus Plus": ["2022-23", "2025-26"],
    "CM Elevate": [],
    # NOT a scheme — the year coverage of curated.v_focus_legacy (Focus Plus
    # producer-group payments), used only for producer-group questions via
    # _year_schemes_for. Excluded from the "every scheme" fallback below.
    "Focus Legacy": ["2021-22", "2022-23", "2024-25", "2025-26"],
}
_YEARS_ONLY_KEYS = frozenset({"Focus Legacy"})

# A question about producer groups (PG / LAMPS / "Focus Legacy"). These live
# only in curated.v_focus_legacy — a different payee (a group, not a farmer),
# different years and no tranches — so the Focus Plus farmer-payment
# clarifications (tranche, "count of what", which year of 2022-23/2025-26) do
# not apply to them.
_PRODUCER_GROUP_Q = re.compile(
    r"\bproducer[\s-]+groups?\b|\bpgs?\b|\blamps?\b|\bfocus\s+legacy\b", re.IGNORECASE)


def _is_producer_group_question(question: str) -> bool:
    return bool(_PRODUCER_GROUP_Q.search(question or ""))


_PG_NAME_STOP = frozenset({
    "in", "of", "the", "a", "an", "are", "is", "was", "there", "for", "members",
    "member", "how", "many", "much", "does", "do", "has", "have", "had", "named",
    "called", "to", "by", "what", "which", "total", "number", "under", "from", "at",
    "with", "and", "or", "focus", "plus", "legacy", "all", "each", "every", "any",
    "about", "on", "me", "show", "give", "list", "tell", "get", "paid", "amount",
})


def _pg_name_from_question(question: str) -> "str | None":
    """The producer-group NAME a question asks about ("Sakania" in "members in
    Sakania PG", "Bak 15 star" in "... in Bak 15 star Producer group?"), or
    None for a general PG question ("how many PGs in West Garo Hills"). Read
    deterministically: the name is the run of non-stop words right before the
    PG keyword, or after "PG named/called". Without this, the place resolver
    treats the name as a village, fails to find it, and tells SQL generation
    not to filter on it — so the named-PG query was rejected (2026-09-23)."""
    toks = re.findall(r"[A-Za-z0-9][\w'-]*|[^\w\s]", question or "")
    low = [t.lower() for t in toks]
    for i, t in enumerate(low):
        kw_end = None
        if t in ("pg", "pgs", "lamps", "lamp"):
            kw_end = i
        elif t == "producer" and i + 1 < len(low) and low[i + 1] in ("group", "groups"):
            kw_end = i + 1
        if kw_end is None:
            continue
        name: list[str] = []
        j = i - 1
        while j >= 0 and len(name) < 6 and re.match(r"\w", toks[j]) and low[j] not in _PG_NAME_STOP:
            name.insert(0, toks[j])
            j -= 1
        if not name:
            k = kw_end + 1
            if k < len(low) and low[k] in ("named", "called"):
                k += 1
                while k < len(low) and len(name) < 6 and re.match(r"\w", toks[k]) \
                        and low[k] not in _PG_NAME_STOP:
                    name.append(toks[k])
                    k += 1
        if name:
            return " ".join(name)
    return None


_NEWER_BATCH_RE = re.compile(
    r"\bnewer\s+batch\b|\bnew\s+batch\b|\bregistration\s+(?:batch|cohort)\b|\b12\.5\s*k\b",
    re.IGNORECASE)
_LEGACY_BATCH_RE = re.compile(
    r"\blegacy\b|\bpaid\s+(?:batch|cohort)\b|\b93\s*k\b", re.IGNORECASE)


def _focus_plus_batch_in(question: str) -> "str | None":
    """'12.5K' / '93K' when the question names exactly one Focus Plus cohort,
    else None (neither, both, or a side-by-side comparison of the readings)."""
    q = question or ""
    if re.search(r"\bside\s+by\s+side\b|\bcompare\b|\bvs\.?\b|\bversus\b", q, re.IGNORECASE):
        return None
    new, old = bool(_NEWER_BATCH_RE.search(q)), bool(_LEGACY_BATCH_RE.search(q))
    if new == old:
        return None
    return "12.5K" if new else "93K"


# One-tap answers for context-layer clarifications that ask the user to pick a
# READING ("which did you mean?"). Without these the engine's question renders
# with no chips at all — a dead end (reported 2026-09-23 for "how many
# beneficiaries ... for Focus Plus"). Each chip names the reading with the
# words the matcher treats as a qualifier (payments / members with an id /
# legacy), so the resumed question never re-trips the same rule.
# (The Focus Plus "beneficiary_reading_unclear" set was removed 2026-09-23 with
# that rule — beneficiaries are now counted distinct, nothing to choose.)
# Rules not listed here get chips parsed from their own text instead.
_ENGINE_CHIPS: dict[str, list[tuple[str, str]]] = {}


def _engine_clarification(question: str, schemes: list[str],
                          resolved: dict) -> "ClarificationNeeded | None":
    """The context-layer clarification (node 5.3) for `question`, with one-tap
    chips when the fired rule asks the user to choose a reading. Text comes
    from check_clarifications (so tests that stub it keep working); the rule
    name is only looked up to attach chips. Never raises."""
    try:
        text = clarification_engine.check_clarifications(question, schemes, resolved)
    except Exception:  # noqa: BLE001
        logger.warning("clarification engine failed — continuing without it", exc_info=True)
        return None
    if not text:
        return None
    options = None
    try:
        hit = clarification_engine.match_clarification(question, schemes, resolved)
        if hit and hit[1] == text:
            stem = question.strip().rstrip(" ?.")
            chips = _ENGINE_CHIPS.get(hit[0])
            if chips:
                options = [{"label": label, "question": f"{stem}, {suffix}"}
                           for label, suffix in chips]
            elif hit[2]:
                # The readings the rule's own text lists. Each chip appends its
                # reading, which the engine then sees as already chosen, so the
                # resumed question cannot re-ask the same thing.
                options = [{"label": o[:1].upper() + o[1:], "question": f"{stem}, {o}"}
                           for o in hit[2]]
            else:
                # A rule that offers a substitute ("Shall I use the allotment
                # category?") — one "Yes" chip that accepts it, carrying the
                # rule's explanation so SQL generation uses the substitute.
                yes_q = clarification_engine.offer_chip_question(question, text)
                if yes_q:
                    offer = clarification_engine._offer_parts(text)[1]
                    options = [{"label": f"Yes, {offer}"[:80], "question": yes_q}]
    except Exception:  # noqa: BLE001 — chips are an enhancement
        logger.warning("clarification chips failed", exc_info=True)
    return ClarificationNeeded(text, options=options, rule="column-not-held")


async def _pg_not_found_clarification(question: str, entity_result: dict) -> "ClarificationNeeded | None":
    """When a named producer group matched nothing, offer the closest real PG
    names (trigram similarity, same pg_trgm the village resolver uses) as
    one-tap chips instead of a bare "no records". Each chip re-asks the same
    question with the real name — and the real district when the user named a
    different one. None when nothing is close enough, or on any DB error."""
    name = _pg_name_from_question(question)
    if not name:
        return None
    try:
        rows = await fetch_rows(
            """
            SELECT pg_name, lgd_district, lgd_block,
                   MAX(similarity(UPPER(pg_name), UPPER($1))) AS score
            FROM curated.v_focus_legacy
            WHERE similarity(UPPER(pg_name), UPPER($1)) > 0.2
            GROUP BY pg_name, lgd_district, lgd_block
            ORDER BY score DESC
            LIMIT 6
            """,
            [name],
        )
    except Exception as e:  # noqa: BLE001 — suggestions are an enhancement
        logger.warning("producer-group suggestions failed: %s", e)
        return None
    if not rows:
        return None
    asked_district = (entity_result.get("display") or {}).get("district") or \
        (entity_result.get("resolved") or {}).get("district")
    options = []
    for r in rows:
        real = re.sub(r"\s+pg$", "", str(r["pg_name"]).strip(), flags=re.IGNORECASE)
        dist = str(r["lgd_district"] or "").title()
        q2 = re.sub(re.escape(name), lambda _m: real, question, count=1, flags=re.IGNORECASE)
        if asked_district and dist and str(asked_district).lower() != dist.lower():
            q2 = re.sub(re.escape(str(asked_district)), lambda _m: dist, q2,
                        count=1, flags=re.IGNORECASE)
        elif not asked_district and dist:
            q2 = f"{q2.rstrip(' ?.')} in {dist}"
        options.append({"label": f"{r['pg_name']} — {str(r['lgd_block'] or '').title()} block, {dist}",
                        "question": q2})
    where = f" in {str(asked_district).title()}" if asked_district else ""
    return ClarificationNeeded(
        f"No producer group named “{name}” was found{where}. "
        "Did you mean one of these?",
        options=options,
        rule="pg-not-found",
    )


def _year_schemes_for(question: str, schemes: "list[str] | None") -> list[str]:
    """The year-coverage key(s) to check `question`'s years against: the
    producer-group years for a Focus-Plus-only PG question, else `schemes`."""
    if list(schemes or []) == ["Focus Plus"] and _is_producer_group_question(question):
        return ["Focus Legacy"]
    return list(schemes or [])


def _fy_short(year_key: int) -> str:
    """2022 -> '2022-23'."""
    return f"{year_key}-{(year_key + 1) % 100:02d}"


def _fy_start(short: str) -> int:
    """'2022-23' -> 2022."""
    return int(str(short)[:4])


async def refresh_scheme_years() -> None:
    """Load each scheme's real DISTINCT financial years from megh_db so the year
    chips and the out-of-range guard track the live data. Best-effort — on any
    failure the verified defaults in _SCHEME_DATA_YEARS stay in place."""
    from app.database.db import run_readonly
    sql_by_scheme = {
        # Wrapped in an outer SELECT: run_readonly rejects a top-level UNION
        # ("query must be a read-only SELECT, got Union"), so this failed on
        # every startup and MGNREGA silently kept its hard-coded default years.
        "MGNREGA": (
            "SELECT DISTINCT year_key FROM ("
            "SELECT year_key FROM curated.v_employment WHERE year_key IS NOT NULL "
            "UNION "
            "SELECT year_key FROM curated.v_expenditure WHERE year_key IS NOT NULL"
            ") y"
        ),
        "PMAY-G": "SELECT DISTINCT year_key FROM curated.v_pmay WHERE year_key IS NOT NULL",
        "Focus Plus": (
            "SELECT DISTINCT year_key FROM curated.v_focus_plus WHERE year_key IS NOT NULL"
        ),
        "Focus Legacy": (
            "SELECT DISTINCT year_key FROM curated.v_focus_legacy WHERE year_key IS NOT NULL"
        ),
        # CM Elevate deliberately has no entry here — curated.v_cm_elevate has no
        # year_key column at all (not merely NULL), so there is nothing to probe.
        # Its default of [] in _SCHEME_DATA_YEARS above is the permanent value.
    }
    for scheme, sql in sql_by_scheme.items():
        try:
            rows = await run_readonly(sql)
            yrs = sorted({int(r["year_key"]) for r in rows if r.get("year_key") is not None})
            if yrs:
                _SCHEME_DATA_YEARS[scheme] = [_fy_short(y) for y in yrs]
                logger.info("scheme years loaded: %s -> %s", scheme, _SCHEME_DATA_YEARS[scheme])
            else:
                logger.warning("scheme years: %s query returned no rows, keeping default %s",
                               scheme, _SCHEME_DATA_YEARS[scheme])
        except Exception as e:  # noqa: BLE001
            logger.warning("scheme years: %s query failed, keeping default %s (%s)",
                           scheme, _SCHEME_DATA_YEARS[scheme], e)

# An explicit "all years" ask, and a request for a per-year series — read from
# the text only for understand.fallback_frame (no Understand frame this turn).
_ALL_YEARS_CUE = re.compile(
    r"\ball[\s-]?(?:the\s+)?(?:financial |fiscal |fy )?years?\b|"
    r"\bevery (?:financial |fiscal )?year\b|\beach year\b|"
    r"\bacross (?:all )?(?:the )?(?:financial |fiscal )?years?\b|"
    r"\ball[\s-]?time\b|\bsince inception\b|\bto date\b|\bcumulative\b|"
    r"\ball years combined\b|\boverall\b|\bin total\b|\bgrand total\b",
    re.IGNORECASE,
)
_TIME_SERIES_CUE = re.compile(
    r"\btrend\b|\bover time\b|\bover (?:the )?(?:last|past) \w+ (?:years?|fys?)\b|"
    r"\byear[\s-]?on[\s-]?year\b|\byear[\s-]?wise\b|\bby year\b|\bby financial year\b|"
    r"\bper year\b|\bannually\b|\bannual\b|\bhistory\b|\bhistorical\b|"
    r"\bgrowth\b|\bchange over\b|\beach (?:financial )?year\b",
    re.IGNORECASE,
)
def _year_choices_for(schemes: list[str]) -> list[str]:
    """Every financial year the given scheme(s) hold, distinct, oldest first.
    Falls back to the full set when `schemes` is empty or unrecognised."""
    years, _live = _available_years_for(schemes)
    return years


def _year_clarification(question: str, schemes: list[str]) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    years, live = _available_years_for(schemes)
    options = [
        {"label": f"FY {y}", "question": f"{stem} for FY {y}"}
        for y in years
    ]
    options.append({
        "label": "All financial years combined",
        "question": f"{stem} across all financial years",
    })
    if len(live) == 1:
        scope_word = live[0]
    elif len(live) == 2:
        scope_word = " and ".join(live)
    else:
        scope_word = ", ".join(live[:-1]) + " and " + live[-1]
    year_list = ", ".join(f"FY {y}" for y in years[:-1]) + f" and FY {years[-1]}"
    return ClarificationNeeded(
        f"{scope_word} data is available for {year_list}. "
        "Which of these is required — a single financial year, or all of them "
        "combined?",
        options=options,
        rule="year-not-specified",
    )


def _year_chip_question(question: str, raw_year: str, year_key: int) -> str:
    """The follow-up question text for one financial-year chip: the SAME
    question, with the ambiguous year token the user typed swapped for an
    unambiguous "FY 2023-24".

    Deliberately a substitution, not an append (the shape `_year_clarification`
    uses): by the time a bare "2023" turns out to be ambiguous, the question may
    already carry the answer to an EARLIER clarification round — the village
    chip's ", RI MULIANG block, WEST KHASI HILLS" suffix — and appending "for
    FY 2023-24" after it would both read as a new trailing clause and leave the
    original "2023" in place, still ambiguous, for the resumed turn to trip on
    all over again. An "FY " already in front of the token is consumed so the
    result never reads "FY FY 2023-24"."""
    stem = question.strip().rstrip(" ?.")
    label = f"FY {_fy_short(year_key)}"
    rx = re.compile(r"(?:\bFY\s*)?\b" + re.escape(str(raw_year)) + r"\b", re.IGNORECASE)
    if rx.search(stem):
        return rx.sub(label, stem, count=1)
    # The extractor normalised the token out of recognition — fall back to
    # naming the year explicitly rather than silently dropping the choice.
    return f"{stem}, {label}"


def _year_ambiguity_clarification(question: str, raw_year: str, candidates: list,
                                  schemes: list[str], *, village_hint: "str | None" = None,
                                  resolved_so_far: "dict | None" = None) -> "ClarificationNeeded":
    """A year the user DID name but which maps to more than one financial year
    — "2023" is FY 2022-23 or FY 2023-24, and the resolver catalogue's own rule
    for it is "return ambiguous and ask which financial year. Do not default."
    (data/mgnrega/mgnrega_entity_resolver.yaml, year.ambiguous_input).

    Asking is right; asking the way this used to — a bare question with no
    options and no `rule` — was not. No options meant the UI rendered a
    clarification bubble with nothing to tap, and no rule meant it wasn't in
    RESUMABLE_CLARIFICATION_RULES, so a typed answer ("2023-24") was not merged
    back into the paused question either: the pause was a dead end in both
    directions, on a question the user had already spent one clarification
    round narrowing. Reported from the live UI, 2026-09-22.

    Distinct from `_year_clarification` (rule "year-not-specified"), which is
    the different case of a question that pins no year at all."""
    starts: list[int] = []
    for c in candidates or []:
        raw = c.get("canonical") if isinstance(c, dict) else c
        m = re.search(r"\d{4}", str(raw or ""))
        if m and int(m.group(0)) not in starts:
            starts.append(int(m.group(0)))
    # Never offer a year the scheme(s) in play don't actually hold — the chips
    # and the out-of-range guard read the same single source of truth
    # (_SCHEME_DATA_YEARS, refreshed from the live data at startup).
    held = [_fy_start(y) for y in _year_choices_for(schemes)]
    if held:
        starts = [k for k in starts if k in held] or list(held)
    starts.sort()
    options = [{"label": f"FY {_fy_short(k)}",
                "question": _year_chip_question(question, raw_year, k),
                "pins": {"year_key": k}}
               for k in starts]
    listed = " or ".join(f"FY {_fy_short(k)}" for k in starts) if starts else "more than one financial year"
    return ClarificationNeeded(
        f"“{raw_year}” could mean {listed}. Which financial year is required?",
        options=options,
        rule="year-ambiguous",
        village_hint=village_hint,
        resolved_so_far=resolved_so_far,
    )


# ── "Which tranche?" clarification (Focus Plus only) ───────────────────────
# Focus Plus's amount_disbursed differs sharply by tranche_label (5,000 for
# Tranch 1, 2,500 for every later tranche — see schema_context.py rule 7), so
# silently summing every tranche together produces a total that reads as a
# single entitlement when it's actually a mix ratio. clarify_rules rule 5
# asks with these one-tap chips (Tranch 1..4 plus "all combined") when the
# scheme's rules file has no tranche default.
def _tranche_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    labels = tranche_labels("Focus Plus")
    options = [
        {"label": lbl, "question": f"{stem} for {lbl}"}
        for lbl in labels
    ]
    options.append({
        "label": "All tranches combined",
        "question": f"{stem} across all tranches",
    })
    label_list = ", ".join(labels[:-1]) + f" and {labels[-1]}" if len(labels) > 1 else labels[0]
    return ClarificationNeeded(
        f"Focus Plus data is split into {label_list}. Which of these is required "
        "— a single tranche, or all of them combined?",
        options=options,
        rule="tranche-not-specified",
    )


# ── "That year isn't in the data" guard ────────────────────────────────────
# Year coverage per scheme lives in _SCHEME_DATA_YEARS (loaded from megh_db at
# startup by refresh_scheme_years()). This guard is PER SCHEME: a year MGNREGA
# lacks (say FY 2019-20) but PMAY-G has is fine for a PMAY-G question and only
# blocked for an MGNREGA one.
#
# A question that names a financial year no scheme in play holds ("1999-20",
# "2010", "FY 2027-28", or "2019-20" for MGNREGA) can't be answered. Without the
# guard the year is dropped as a note and the flow either falls into the generic
# "which year?" pause (looks like we ignored what the user typed) or answers
# across the years that DO exist (a figure for the wrong period). Instead: tell
# the user which years that scheme has, with those years as one-tap chips.

# A raw mention that is clearly meant as a year/financial-year even though it
# didn't resolve — a 4-digit 19xx/20xx/21xx, or an "NN-NN" / "NNNN-NN" range.
_YEAR_SHAPED_RE = re.compile(
    r"\b(?:19|20|21)\d{2}\b|\b\d{2}\s*[-/]\s*\d{2}\b|\b\d{4}\s*[-/]\s*\d{2,4}\b"
)


def _looks_like_year_mention(text: str) -> bool:
    return bool(_YEAR_SHAPED_RE.search(text or ""))


def _allowed_year_starts(schemes: "list[str] | None") -> set:
    """FY start years the given scheme(s) actually hold (union). Empty schemes =>
    every scheme's years."""
    years, _live = _available_years_for(schemes or [])
    return {_fy_start(y) for y in years}


def _year_in_data_range(year_key: int, schemes: "list[str] | None" = None) -> bool:
    return year_key in _allowed_year_starts(schemes)


# A token that is unambiguously a financial year: an "NNNN-NN" / "NNNN-NNNN"
# range (any century), a 19xx or 21xx four-digit year, or a 20xx year in the
# 2010-2039 plausible band. A bare "2000" / "2500" is deliberately NOT matched
# so "top 2000 villages" isn't mistaken for a year.
_YEAR_RANGE_TOKEN_RE = re.compile(
    r"\b(?:fy\s*|financial\s+year\s*|fiscal(?:\s+year)?\s*)?"
    r"((?:19|20|21)\d\d\s*[-/]\s*\d{2,4}|(?:19|21)\d\d|20[1-3]\d)\b",
    re.IGNORECASE,
)


_MALFORMED_YEAR_CUE_RE = re.compile(
    # "of" deliberately excluded — it's the ending of ordinary amount phrasing
    # too ("total expenditure of 150000"), not just year phrasing, so it would
    # false-positive on a real currency figure. "in"/"for"/"during"/"fy" are
    # unambiguously temporal.
    r"\b(?:in|for|during|fy|financial\s+year|fiscal(?:\s+year)?)\s*[:\-]?\s*(\d{4,8})"
    r"\s*[?.!]*\s*\Z",
    re.IGNORECASE,
)


def _out_of_range_year_in(text: str, schemes: "list[str] | None" = None) -> "str | None":
    """Raw text of the first financial-year token in `text` that NONE of the
    given scheme(s) hold, or None if every year mentioned is available / none is
    mentioned. Runs on raw text only — no LLM, no DB."""
    for m in _YEAR_RANGE_TOKEN_RE.finditer(text or ""):
        tok = m.group(1)
        yk = _parse_year_key(tok)
        if yk is not None:
            if not _year_in_data_range(yk, schemes):
                return tok
        elif _YEAR_SHAPED_RE.search(tok):   # e.g. "1999-20" — a year we can't parse
            return tok
    # A digit run right after an explicit temporal cue, at the very END of the
    # question ("in 20217", "...beneficiaries in Bamil Reserve Apal in 20217?")
    # that _YEAR_RANGE_TOKEN_RE above didn't match at all — its 20[1-3]\d
    # alternative needs a \b right after the 4th digit, so one extra trailing
    # digit ("20217") makes the WHOLE token invisible to it, not just
    # unparseable. Without this, "in 20217" skipped the guard entirely and the
    # SQL generator copied the literal straight into year_key = 20217, ran
    # clean, and silently returned 0 (2026-09-09 bug report — no clarification
    # was ever offered). Anchored to end-of-question (not just gated on a cue
    # word) so a real amount stated mid-sentence ("sanctioned amount of 500000
    # in Siju") is never mistaken for a year — a year mention is normally the
    # last thing named in these questions, an amount normally isn't.
    m = _MALFORMED_YEAR_CUE_RE.search(text or "")
    if m and _parse_year_key(m.group(1)) is None:
        return m.group(1)
    return None


def _available_years_for(schemes: list[str]) -> "tuple[list[str], list[str]]":
    """(distinct FY list across the given scheme(s), scheme names used). Falls
    back to every scheme when `schemes` is empty or unrecognised.

    Years are merged scheme-by-scheme, so without an explicit sort the result
    lands in whatever order the schemes happen to combine in (e.g. MGNREGA's
    2022-23..2025-26 ahead of PMAY-G's earlier 2017-18..2021-22) rather than
    chronological order. Sort ascending (oldest first) so the year chips read
    in a sane order regardless of scheme combination."""
    live = [s for s in (schemes or []) if s in _SCHEME_DATA_YEARS] or \
        [s for s in _SCHEME_DATA_YEARS if s not in _YEARS_ONLY_KEYS]
    seen: set[str] = set()
    years: list[str] = []
    for s in live:
        for y in _SCHEME_DATA_YEARS[s]:
            if y not in seen:
                seen.add(y)
                years.append(y)
    years.sort(key=_fy_start)
    return years, live


def _scheme_has_no_time_dimension(schemes: "list[str] | None") -> bool:
    """True when NO scheme in play has any financial year at all — CM Elevate
    (no year_key, no date column of any kind, see _SCHEME_DATA_YEARS).

    Guards against an unbreakable clarification loop. `_year_out_of_range_
    clarification` offers exactly ONE option in this case, "Answer without a
    time filter", whose chip question is the stem with the year stripped — but
    when the year never came from the question text (the LLM mention-extractor
    tags one for a question that names none, which it does for CM Elevate),
    that stem IS the original question. So the chip re-asks the identical
    question, re-trips the identical guard, and the user can never get an
    answer. Reported from the live UI 2026-09-21 and reproduced deterministically:
    "Top 5 CM Elevate schemes by applications" -> chip question
    "Top 5 CM Elevate schemes by applications" -> same clarification, forever.

    A clarification whose only option changes nothing is not a question worth
    asking: callers drop the time filter, record a note saying so, and answer.
    That is exactly what the single chip promised to do anyway.
    """
    years, _live = _available_years_for(schemes)
    return not years


def _no_time_dimension_note(schemes: "list[str] | None") -> str:
    _years, live = _available_years_for(schemes)
    scheme_word = live[0] if len(live) == 1 else (" and ".join(live) if live else "This scheme")
    return (f"{scheme_word} has no date field in this data, so records cannot be placed "
            "in a financial year — answered without a time filter.")


def _year_out_of_range_clarification(question: str, raw_year: str,
                                    schemes: list[str]) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    # Strip the offending year (and any "for "/"in "/"FY " lead-in, or a bare
    # comma before it) out of the stem, so the chip questions we build below
    # don't carry it back in and trip this same pause on the next turn.
    stem = re.sub(
        r"\s*,?\s*(?:for\s+|in\s+|during\s+|of\s+)?(?:fy\s*)?" +
        re.escape(raw_year.strip()) + r"\b",
        "", stem, count=1, flags=re.IGNORECASE,
    ).strip().rstrip(",").strip() or question.strip().rstrip(" ?.")

    years, live = _available_years_for(schemes)
    if not years:
        # Every scheme in play has NO time dimension at all (CM Elevate: no
        # year_key, no date column of any kind) — there is no "these years are
        # available" chip list to offer. Refuse the time filter outright rather
        # than showing an out-of-range message with zero year options.
        scheme_word = live[0] if len(live) == 1 else (" and ".join(live) if live else "This scheme")
        return ClarificationNeeded(
            f"{scheme_word} has no date field in this data, so records cannot be "
            f"placed in a financial year or any other time period. I can answer "
            "without a time filter instead.",
            options=[{"label": "Answer without a time filter", "question": stem}],
            rule="no-time-dimension",
        )
    if len(live) == 1:
        coverage = (f"For {live[0]}, data is available only for the financial "
                    f"years {', '.join(years)}.")
    else:
        per_scheme = "; ".join(
            f"{s} — {', '.join(_SCHEME_DATA_YEARS[s])}" for s in live
        )
        coverage = ("Data is available only for the following financial years: "
                    f"{per_scheme}.")

    options = [
        {"label": f"FY {y}", "question": f"{stem} for FY {y}"}
        for y in years
    ]
    options.append({
        "label": "All available years combined",
        "question": f"{stem} across all financial years",
    })
    return ClarificationNeeded(
        f"{coverage} No data is held for “{raw_year.strip()}”. "
        "Please select one of the financial years listed above, or all of them "
        "combined.",
        options=options,
        rule="year-out-of-range",
    )


def _named_schemes(question: str) -> list[str]:
    """Schemes named outright in the question text, in catalog order. Falls
    back to fuzzy matching (_fuzzy_named_schemes) when the exact regex finds
    nothing — otherwise a misspelled scheme name ("manrega", "pamay") reads as
    "no scheme named" and forces an unnecessary clarification prompt instead
    of being understood."""
    exact = [s for s, pattern in _SCHEME_NAME_PATTERN.items() if pattern.search(question)]
    if exact:
        return exact
    return _fuzzy_named_schemes(question)


def _shortcut_scheme(question: str) -> list[str] | None:
    """Skip the classifier call when the text already pins the scheme set —
    faster and more reliable than the model for the common case, and one fewer
    model call per query at scale. Deterministic whenever:
      * two or more schemes are named  -> use exactly those (the user listed
        them; "compare MGNREGA and PMAY" needs no classification), or
      * an explicit cross-scheme phrase ("both schemes", "across schemes")
        is present  -> the whole catalog, or
      * exactly one scheme is named    -> that one, or
      * no scheme is named but the vocabulary pins exactly one (same check
        the "which scheme?" rule uses to skip its own pause) -> that one.
    Without this last case, a vocabulary-only question ("sanctioned amount",
    "person-days") skipped the "which scheme?" pause (correctly inferring
    MGNREGA/PMAY-G) but then still went to the LLM classifier here, which
    doesn't apply the same vocabulary rule and can return every scheme "to be
    safe" — inconsistent with the pause having just been skipped, and it broke
    the PMAY-G year-gate exemption (which only applies when the scheme set is
    exactly ["PMAY-G"]).
    Returns None only when nothing in the text pins it, so the classifier still
    handles the genuinely unnamed/ambiguous case."""
    named = _named_schemes(question)
    if len(named) >= 2:
        return named
    # "CM Elevate applications ... split by scheme" means CM Elevate's own 15
    # sub-schemes, not "compare all four schemes" — the whole-catalogue
    # shortcut below sent it cross-scheme and it dead-ended on a join pause
    # (2026-09-23 KPI sweep, DC-01).
    if _SUB_SCHEME_BREAKDOWN.search(question) and (
            named == ["CM Elevate"]
            or (not named and _infer_scheme_from_terms(question) == ["CM Elevate"])):
        return ["CM Elevate"]
    if _EXPLICIT_BOTH.search(question):
        return list(SCHEME_CATALOG)
    if named:
        return named
    return _infer_scheme_from_terms(question)


@dataclass(frozen=True)
class ScopeMeta:
    """How a `classify_scheme` decision was reached — node 5.1's contribution
    to the query-analyzer's `response.scope` output (5.2). Purely descriptive:
    never read back by any decision logic."""
    confidence: float
    source: str  # "llm" | "shortcut" | "fallback"
    reason: str


async def _classify_scheme_detailed(question: str) -> "tuple[list[str], ScopeMeta]":
    """Same decision `classify_scheme` makes, plus a trace of how it was
    reached. Extracted here so `classify_scheme`'s own contract (a bare
    `list[str]`, asserted by its existing test suite) never has to change."""
    shortcut = _shortcut_scheme(question)
    if shortcut:
        logger.info("classify_scheme: shortcut matched %s, skipping model call", shortcut)
        named = _named_schemes(question)
        if len(named) >= 2:
            reason = f"Named schemes: {', '.join(named)}"
        elif _EXPLICIT_BOTH.search(question):
            reason = "Question explicitly asks about all schemes together"
        elif named:
            reason = f"Named scheme: {named[0]}"
        else:
            reason = "Scheme inferred from scheme-specific vocabulary in the question"
        return shortcut, ScopeMeta(confidence=0.95, source="shortcut", reason=reason)

    catalog = "\n".join(f'  - "{name}": {desc}' for name, desc in SCHEME_CATALOG.items())
    scheme_options = " | ".join(f'"{name}"' for name in SCHEME_CATALOG)
    prompt = f"""Classify which scheme(s) this question needs. Available schemes:
{catalog}

Return ONLY JSON: {{"schemes": [{scheme_options}, ...]}}
Use several if the question compares or combines schemes. If it names none specifically
and gives no scheme-specific vocabulary, return every scheme.

Question: "{question}"
JSON:"""
    raw = await llm.call_classifier(prompt, guided={"guided_json": _SCHEMES_JSON_SCHEMA})
    payload = _extract_json(raw)
    if payload and isinstance(payload.get("schemes"), list):
        schemes = [s for s in payload["schemes"] if s in SCHEME_CATALOG]
        # Safety net: a scheme the user named outright must never be dropped by
        # the classifier. Union it back in (catalog order) so "across MGNREGA and
        # PMAY-G" can't come back PMAY-only.
        for s in _named_schemes(question):
            if s not in schemes:
                schemes.append(s)
        if schemes:
            ordered = [s for s in SCHEME_CATALOG if s in schemes]
            reason = f"Classifier model selected: {', '.join(ordered)}"
            return ordered, ScopeMeta(confidence=0.8, source="llm", reason=reason)
    # Deterministic fallback if the model call fails or returns unusable JSON.
    logger.warning("classify_scheme: unusable response %r — defaulting to both schemes", raw[:200])
    return list(SCHEME_CATALOG), ScopeMeta(
        confidence=0.3, source="fallback",
        reason="Classifier response was unusable — defaulted to every scheme")


async def classify_scheme(question: str) -> list[str]:
    """Which scheme(s) — any combination of SCHEME_CATALOG's four (MGNREGA,
    PMAY-G, Focus Plus, CM Elevate) — does this question touch?"""
    schemes, _meta = await _classify_scheme_detailed(question)
    return schemes


# Bare dimension nouns and the state name are NOT place mentions — "which
# villages have activity in Meghalaya" names no specific village or district.
# The classifier sometimes extracts them anyway; drop them before resolution,
# or `resolve_village("villages")` fuzzy-matches "Model Village" etc. and raises
# a nonsense clarification.
_GENERIC_PLACE_TERMS = {
    "village", "villages", "vill", "hamlet", "hamlets", "gaon",
    "district", "districts", "dist", "distt",
    "block", "blocks", "dev block", "development block", "cd block", "c.d. block",
    "panchayat", "panchayats", "gram panchayat", "gp", "gps", "vec",
    "state", "meghalaya", "region", "regions", "area", "areas",
    "place", "places", "location", "locations", "zone", "zones",
    "year", "years", "fy", "financial year", "all", "every", "each", "any",
}


def _clean_mention(value: str) -> str | None:
    """Normalise a raw mention; return None if it's a bare dimension word / the
    state name (i.e. not an actual place or period)."""
    v = value.strip().strip("\"'`.,?!()[]").strip()
    core = re.sub(r"^(the|a|an|this|that|each|every|all)\s+", "", v, flags=re.IGNORECASE).strip()
    if not core or core.lower() in _GENERIC_PLACE_TERMS:
        return None
    # A scheme name is never a place — "... for Focus Plus" reads like a place
    # after a preposition (the extractor prompt deliberately teaches it to
    # follow "of"/"for"/"under" onto place names), so the model occasionally
    # tags the scheme itself as the district/block/village. Reject it here as
    # a deterministic backstop regardless of what the LLM returned, or it goes
    # on to fail district/block/village resolution and gets reported as a
    # place "not in Meghalaya" (reported 2026-09-10: "which district received
    # highest total disbursement for Focus Plus" -> mentions.district ==
    # "Focus Plus" -> OutOfScope).
    if any(rx.search(core) for rx in _SCHEME_NAME_PATTERN.values()):
        return None
    return v


def _mention_in_question(value: str, question: str) -> bool:
    """True when `value` actually occurs in `question` (case- and
    whitespace-insensitive). The extractor must copy spans verbatim, so a value
    that fails this is the model echoing one of its own prompt examples, not an
    extraction — ported from the pre-restructure codebase. Without it, Focus
    Plus questions naming no year came back with {"year": "2017-18"} (the FY
    2017-18 example below) and paused on "no data for 2017-18" (2026-09-23
    KPI sweep: F1-03, F1-06, F1-09, F3-02)."""
    norm = lambda t: re.sub(r"\s+", " ", t or "").strip().lower()
    return norm(value) in norm(question)


async def extract_entity_mentions(question: str) -> dict:
    """Which spans of the question name a district, block, village, year or
    assembly constituency? Span-finding only — resolving each span to a
    canonical DB value is a separate, deterministic step (entity_resolver),
    not this LLM call."""
    prompt = f"""Extract place/time names from this question, verbatim as the user typed
them. Do not correct spelling or guess the canonical form.

Return ONLY JSON with keys from: "district", "block", "village", "year",
"assembly_constituency", "blocks", "districts". Include a key ONLY when the
question NAMES a specific one. A bare word like "village", "villages",
"district", "block", "year", or the state name "Meghalaya" is NOT a name —
omit it. If the question names none, return {{}}.

When the question names TWO OR MORE blocks to compare against each other
("compare X and Y", "X vs Y", "X and Y, the block, not the village"), put ALL
of their names in the plural "blocks" array — do NOT use the singular "block"
key and keep only one, that silently drops the other block from the answer.
Use "block" only when exactly one block is named. The same rule applies to
districts: TWO OR MORE named to compare against each other go in the plural
"districts" array, never the singular "district" key — even when one of them
is a short acronym like "EKH" or "WGH". Use "district" only when exactly one
district is named.

Block, assembly-constituency and village names overlap heavily in Meghalaya —
a bare name (e.g. "Mawlai") could be any of the three. Use "assembly_constituency"
ONLY when the question itself signals a constituency: it says "constituency",
"AC", "assembly", "MLA", or gives a number before the name (e.g. "15 Mawlai",
"AC 9"). Otherwise tag an ambiguous bare name as "block".

A place name can follow ANY preposition, not just "in"/"for" — "disbursement
OF Selsella", "expenditure OF West Garo Hills", "spending OF Abagre" all name
Selsella/West Garo Hills/Abagre as the AREA the figure is about, exactly like
"disbursement in Selsella" would. Do not read "of" as meaning the metric noun
(disbursement, expenditure, spending, amount, total) is itself the thing being
named — the name after "of" is still a place, and must still be extracted.

A SCHEME name (MGNREGA, PMAY-G, Focus Plus, CM Elevate, or a close variant)
is NEVER a place — do not extract it as a district/block/village even when it
follows "for"/"of"/"under" exactly like a place would ("disbursement for
Focus Plus" names the scheme, not an area; extract nothing).

Examples:
Question: "Tell me about total disbursement of Selsella across all financial years for MGNREGA."
JSON: {{"block": "Selsella"}}
Question: "What is the total expenditure of West Garo Hills under PMAY-G?"
JSON: {{"district": "West Garo Hills"}}
Question: "how many job cards issued in Ri Bhoi"
JSON: {{"district": "Ri Bhoi"}}
Question: "show me MGNREGA spend"
JSON: {{}}
Question: "Compare the sanctioned amounts of Dambo Rongjeng and Samanda, the block, not the village"
JSON: {{"blocks": ["Dambo Rongjeng", "Samanda"]}}
Question: "Compare PMAY performance between ekh and wgh for FY 2017-18"
JSON: {{"districts": ["ekh", "wgh"], "year": "2017-18"}}
Question: "which district received highest total disbursement for Focus Plus"
JSON: {{}}

Question: "{question}"
JSON:"""
    raw = await llm.call_classifier(prompt, guided={"guided_json": _ENTITY_JSON_SCHEMA})
    payload = _extract_json(raw)
    if not isinstance(payload, dict):
        return {}
    out: dict[str, object] = {}
    for k, v in payload.items():
        if k in ("district", "block", "village", "year", "assembly_constituency") \
                and isinstance(v, str) and v.strip():
            cleaned = _clean_mention(v)
            if cleaned and _mention_in_question(cleaned, question):
                out[k] = cleaned
    blocks_raw = payload.get("blocks")
    if isinstance(blocks_raw, list):
        cleaned_blocks: list[str] = []
        seen: set[str] = set()
        for v in blocks_raw:
            if not isinstance(v, str):
                continue
            c = _clean_mention(v)
            if c and _mention_in_question(c, question) and c.lower() not in seen:
                seen.add(c.lower())
                cleaned_blocks.append(c)
        if len(cleaned_blocks) >= 2:
            out["blocks"] = cleaned_blocks
        elif len(cleaned_blocks) == 1 and "block" not in out:
            # A single-element array is just a singular mention the model
            # phrased as a list — fold it back so the existing singular path
            # (block-vs-village disambiguation etc.) still runs for it.
            out["block"] = cleaned_blocks[0]
    districts_raw = payload.get("districts")
    if isinstance(districts_raw, list):
        cleaned_districts: list[str] = []
        seen_d: set[str] = set()
        for v in districts_raw:
            if not isinstance(v, str):
                continue
            c = _clean_mention(v)
            if c and _mention_in_question(c, question) and c.lower() not in seen_d:
                seen_d.add(c.lower())
                cleaned_districts.append(c)
        if len(cleaned_districts) >= 2:
            out["districts"] = cleaned_districts
        elif len(cleaned_districts) == 1 and "district" not in out:
            # A single-element array is just a singular mention the model
            # phrased as a list — fold it back so the existing singular path
            # runs for it.
            out["district"] = cleaned_districts[0]
    return out


def _parse_year_key(text: str) -> "int | None":
    """FY start year as an int from '2023', '2023-24', '2023-2024', 'FY 2023-24',
    'FY23'. Returns None if no plausible year (2010-2039) is present."""
    m = re.search(r"\b(20[1-3]\d)\s*[-/]\s*(?:20)?\d{2}\b", text)   # 2023-24 / 2023-2024
    if m:
        return int(m.group(1))
    m = re.search(r"\bfy\s*'?(\d{2})\b", text, re.IGNORECASE)        # FY23
    if m:
        return 2000 + int(m.group(1))
    m = re.search(r"\b(20[1-3]\d)\b", text)                          # bare 2023
    if m:
        return int(m.group(1))
    return None


def _village_chip_question(question: str, raw_text: str, candidate: dict) -> str:
    """The follow-up question text for one village-disambiguation chip.

    The old approach appended "<block> block, <district>" to the ORIGINAL
    ambiguous fragment (e.g. "siju") and left the fragment itself unchanged.
    That only narrows resolve_village's search scope — it does not say WHICH
    candidate was picked. Two candidates that both fuzzy-match the same raw
    text and also sit in the same block (e.g. "siju" fuzzy-matches both SIJU
    SONGMONG and Siju Arteka, both in SIJU block, SOUTH GARO HILLS) stay tied
    even after the block/district is appended, so every chip regenerates the
    IDENTICAL question and the clarification loops forever — reported
    2026-09-09 for both an exact-duplicate dim_geography row (Asimgre, DALU
    block) and this fuzzy-match case (siju). Substituting the candidate's own
    canonical name into the question fixes it: re-resolution then runs an
    EXACT match on a name that is (almost always, and after the duplicate-row
    fix in entity_resolver.resolve_village, effectively always) unique.

    A second, compounding bug (also reported 2026-09-09, "nongthymmai" in
    EAST/WEST KHASI HILLS): when the LLM mention-extractor can't cleanly split
    a resumed chip's OWN text ("Nongthymmai, RI MULIANG block, WEST KHASI
    HILLS") into village/block, resolve_entities lands back on this same
    ambiguous-village branch and calls this function AGAIN — with `question`
    now already carrying the previous round's appended ", <block> block,
    <district>". Blindly appending another one lets the suffix grow every
    round ("..., RI MULIANG block, WEST KHASI HILLS, MAWSHYNRUT block, WEST
    KHASI HILLS, ...", naming more and more blocks at once), which defeats any
    single-candidate text match downstream and loops forever. Strip a
    previously-appended suffix (there is at most one meaningful one — this
    function is the only writer of that shape) before appending the current
    candidate's, so the text never grows past one such suffix."""
    stem = question.strip().rstrip(" ?.")
    stem = re.sub(r"(,\s*[^,]+?\s+block,\s*[^,]+)+$", "", stem, flags=re.IGNORECASE).rstrip()
    # Same growth problem for the "(NAME)" fallback pin below: strip any pins
    # a previous round appended so they can't stack ("... (DALMAGRE) (DALDAGRE)").
    stem = re.sub(r"(\s*\([^()]*\))+$", "", stem).rstrip()
    name = candidate["name"]
    # Whole-word match only — a plain substring replace rewrote "dalu" INSIDE
    # an earlier round's "DALUAGRE" into "DALUAGREAGRE", a name that exists
    # nowhere, so every round re-asked the same question (reported 2026-09-23).
    _raw_word = rf"(?<!\w){re.escape(raw_text)}(?!\w)" if raw_text else None
    if _raw_word and re.search(_raw_word, stem, re.IGNORECASE):
        pinned = re.sub(_raw_word, lambda _m: name, stem, count=1, flags=re.IGNORECASE)
    elif re.search(rf"(?<!\w){re.escape(name)}(?!\w)", stem, re.IGNORECASE):
        pinned = stem
    else:
        pinned = f"{stem} ({name})"
    # State the level explicitly, so _explicit_level_in reads the trailing
    # ", <BLOCK> block, <DISTRICT>" as the village's scope rather than as a
    # block question (which would drop the village the user just picked).
    if not re.search(r"\bthe\s+village\b", pinned, re.IGNORECASE):
        pinned = f"{pinned}, the village"
    return f"{pinned}, {candidate['block']} block, {candidate['district']}"


def _village_candidate_named_in(question: str, candidates: list[dict]) -> "dict | None":
    """The one ambiguity candidate the question text already names outright,
    or None. A clicked village chip puts the candidate's exact name AND block
    into the question ("... DALJAGRE ..., RONGRAM block, WEST GARO HILLS"), but
    the mention extractor / remembered village_hint can still hand
    resolve_village the original fuzzy fragment ("dalu"), which re-finds the
    same candidate set — without this check the pause loops forever. Picks
    only when exactly one distinct village matches by whole-word name
    (narrowed by block name when several do)."""
    def _in_text(s: object) -> bool:
        return bool(s) and re.search(rf"(?<!\w){re.escape(str(s))}(?!\w)", question, re.IGNORECASE) is not None

    # A "(NAME)" pin is _village_chip_question's explicit pick when the raw
    # fragment wasn't in the text to substitute — it outranks a stale name
    # left over from an earlier round.
    pinned = [c for c in candidates if c.get("name") and re.search(
        rf"\(\s*{re.escape(str(c['name']))}\s*\)", question, re.IGNORECASE)]
    if len({c.get("village_code") for c in pinned}) == 1:
        return pinned[0]

    hits = [c for c in candidates if _in_text(c.get("name"))]
    if len(hits) > 1:
        narrowed = [c for c in hits if _in_text(c.get("block"))]
        if narrowed:
            hits = narrowed
    codes = {c.get("village_code") for c in hits}
    return hits[0] if len(codes) == 1 and hits else None


# ── "Is that a village, a block, or a constituency?" ────────────────────────
# Ported from the pre-restructure codebase (Old_meghalaya), which offered every
# admin level a bare name could mean. This one only ever asked block-vs-
# village, so "Mawlai" (block, AC 15 and a village) never offered the
# constituency. Each chip appends an explicit level word that
# _explicit_level_in reads back, so a resumed chip resolves straight through.
_DIM_CHIP_WORD = {
    "district": "district",
    "block": "block",
    "assembly_constituency": "assembly constituency",
    "village": "village",
}
_DIM_CHIP_LABEL = {
    "district": "district",
    "block": "C&RD block",
    "assembly_constituency": "assembly constituency",
    "village": "village",
}


def _dimension_collision_clarification(question: str, name: str,
                                       dims: "dict[str, str]") -> "ClarificationNeeded":
    """Ask which ADMIN LEVEL a bare, level-ambiguous place name refers to.
    `dims` is {dimension: canonical display name} from
    collides_across_dimensions. Each chip substitutes the canonical name for
    what the user typed, so a typo is corrected along with the level choice
    ("malwai" -> "Mawlai"); the village chip keeps the user's own text."""
    stem = question.strip().rstrip(" ?.")
    options = []
    for dim, canonical in dims.items():
        shown = str(canonical).title() if canonical else name
        if canonical and canonical.lower() != str(name).lower():
            resumed = re.sub(rf"(?<!\w){re.escape(str(name))}(?!\w)", lambda _m: canonical,
                             stem, count=1, flags=re.IGNORECASE)
        else:
            resumed = stem
        options.append({
            "label": f"The {shown} {_DIM_CHIP_LABEL[dim]}",
            "question": f"{resumed}, the {_DIM_CHIP_WORD[dim]}, not another area type",
        })
    labels = list(dims)
    listed = ", ".join(_DIM_CHIP_LABEL[d] for d in labels[:-1]) + \
        f" or {_DIM_CHIP_LABEL[labels[-1]]}"
    return ClarificationNeeded(
        f"“{name}” could refer to more than one kind of area in Meghalaya — the "
        f"{listed}. These cover different places and give different numbers, so "
        "please pick the one you mean.",
        options=options,
        rule="entity-ambiguous",
    )


_EXPLICIT_LEVEL_RE = {
    "assembly_constituency": re.compile(
        r"\b(assembly\s+constituenc\w*|constituenc\w*|\bAC\b|assembly|MLA)\b", re.IGNORECASE),
    "block": re.compile(r"\bblock\b", re.IGNORECASE),
    "village": re.compile(r"\bvillage\b", re.IGNORECASE),
    "district": re.compile(r"\bdistrict\b", re.IGNORECASE),
}

# Assembly constituency is recorded on exactly ONE fact: MGNREGA employment
# (curated.v_employment). Not on MGNREGA expenditure, nor on PMAY-G / Focus
# Plus / CM Elevate — so the AC chip is suppressed for questions it could
# never answer.
_AC_CAPABLE_METRIC = re.compile(
    r"\bperson[\s-]?days?\b|\bjob\s?cards?\b|\bmuster\b|"
    r"\b100[\s-]?days?\b|\bhundred\s+days?\b|"
    r"\b(?:households?|persons?|people|women|men)\b[^?.!]{0,30}\b"
    r"(?:employ\w*|work\w*|receiv\w*)\b|"
    r"\bemploy\w*\b|\bbeneficiar\w*\b|\bworkers?\b",
    re.IGNORECASE,
)
_AC_INCAPABLE_METRIC = re.compile(
    r"\bexpenditure\b|\bspend(?:ing)?\b|\bspent\b|\bwages?\b|\bwage\s+bill\b|"
    r"\bmaterial\s+cost\b|\bamount\b|\bcost\b|\butili[sz]ation\b|"
    r"\bhouses?\b|\bsanction\w*\b|\breleas\w*\b|\bdisburs\w*\b|"
    r"\binstal{1,2}ments?\b|\bapplications?\b",
    re.IGNORECASE,
)


def _ac_dimension_available(question: str, schemes: list[str]) -> bool:
    """True when an assembly-constituency reading of a place name could
    actually be queried for THIS question. False suppresses the AC chip."""
    if (schemes or []) != ["MGNREGA"]:
        return False
    q = question or ""
    if _AC_INCAPABLE_METRIC.search(q) and not _AC_CAPABLE_METRIC.search(q):
        return False
    if _AC_CAPABLE_METRIC.search(q):
        return True
    return not _AC_INCAPABLE_METRIC.search(q)


# Step 2: narrowing inside a chosen constituency. An AC is an electoral
# boundary, not an administrative parent (8 of 56 straddle two districts), so
# the options come from what it ACTUALLY contains in the data.
_AC_SCOPED_RE = re.compile(r",\s*within\s+the\s+", re.IGNORECASE)
_AC_NARROW_RE = re.compile(
    r",\s*within\s+the\s+(?P<name>.+?)\s+(?P<level>district|block)\s+only\b",
    re.IGNORECASE,
)


def _ac_drilldown_clarification(question: str, ac_display: str,
                                contents: dict) -> "ClarificationNeeded | None":
    """Offer to narrow inside a just-chosen assembly constituency, or None when
    there is nothing meaningful to narrow to."""
    districts = contents.get("districts") or []
    blocks = contents.get("blocks") or []
    if not districts and not blocks:
        return None
    stem = question.strip().rstrip(" ?.")
    options = [{"label": f"The whole {ac_display} constituency",
                "question": f"{stem}, the whole constituency"}]
    if len(districts) > 1:
        for d in districts:
            options.append({
                "label": f"Only the {str(d).title()} part",
                "question": f"{stem}, within the {d} district only",
            })
    for b in blocks[:8]:
        options.append({
            "label": f"{str(b).title()} block",
            "question": f"{stem}, within the {b} block only",
        })
    if len(options) < 2:
        return None
    where = (f"spans {len(districts)} districts and " if len(districts) > 1 else "covers ")
    return ClarificationNeeded(
        f"The {ac_display} assembly constituency {where}"
        f"{len(blocks)} C&RD block(s), with {contents.get('villages', 0)} villages in the "
        "employment data. Do you want the whole constituency, or just part of it?",
        options=options,
        rule="ac-narrow-scope",
    )


# Candidate place phrases after a preposition ("in X", "for X", "of X") — the
# grammar that actually introduces a place. Used only to hand the collision
# gate a name to test when the extractor dropped it.
_PLACE_PREP_RE = re.compile(
    r"\b(?:in|for|of|at|from|within|under)\s+"
    r"(?P<name>[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,3})",
    re.IGNORECASE,
)
_NOT_A_PLACE_WORD = {
    "mgnrega", "mnrega", "nrega", "pmay", "pmayg", "awaas", "awas",
    "focus", "focus plus", "focusplus", "cm", "cm elevate", "cmelevate",
    "meghalaya", "fy", "financial", "financial year", "all", "each", "every",
    "the", "a", "an", "this", "that", "total", "district", "block", "village",
    "assembly", "constituency", "state", "india", "government", "scheme",
}


def _place_phrase_candidates(question: str, scheme: str) -> list[str]:
    """Names following a place preposition, longest phrase first, skipping
    district names (districts never collide) and non-place words."""
    districts = {d.strip().upper() for d in canonical_names(scheme, "district")}
    out: list[str] = []
    for m in re.finditer(rf"(?={_PLACE_PREP_RE.pattern})", question or "", re.IGNORECASE):
        words = (m.group("name") or "").strip().rstrip(".,").split()
        for take in range(len(words), 0, -1):
            cand = " ".join(words[:take]).strip()
            if len(cand) < 4 or cand.lower() in _NOT_A_PLACE_WORD:
                continue
            if cand.upper() in districts:
                break
            if cand not in out:
                out.append(cand)
    return out


def _canonical_in_question(question: str, scheme: str, dimension: str) -> "str | None":
    """The catalogue name for `dimension` that appears verbatim in `question`,
    or None. Longest match wins, so "North Tura" is not shadowed by "Tura"."""
    best: str | None = None
    for canon in collision_canonical_names(scheme, dimension):
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(canon)}(?![A-Za-z0-9])",
                     question or "", re.IGNORECASE):
            if best is None or len(canon) > len(best):
                best = canon
    return best


# A village chip's trailing ", <BLOCK> block, <DISTRICT>" names the CONTAINING
# area, not the level asked about — stripped before level detection, but only
# when the question also carries a chip's level phrase.
_CHIP_SCOPE_SUFFIX_RE = re.compile(
    r",\s*[A-Z][A-Za-z.'\- ]*\s+block\s*,\s*[A-Z][A-Za-z.'\- ]*\s*$")
_CHIP_LEVEL_PHRASE_RE = re.compile(
    r",\s*the\s+(?:village|block|district|assembly\s+constituency)\b", re.IGNORECASE)
# "by block", "each village", "village-wise" name a GROUPING, not the place.
_BREAKDOWN_LEVEL_PHRASE_RE = re.compile(
    r"\b(?:by|per|each|every|all|across)\s+(?:the\s+)?"
    r"(?:village|block|district|assembly\s+constituenc\w*|constituenc\w*)s?\b|"
    r"\b(?:village|block|district)[\s-]?wise\b",
    re.IGNORECASE,
)
# The rejected half of a choice chip ("the block, not the village", "not
# another area type") names the level the user did NOT pick.
_NEGATED_LEVEL_PHRASE_RE = re.compile(
    r"\bnot\s+(?:the\s+|a\s+)?(?:village|block|district|assembly\s+constituency|"
    r"constituency|another\s+area\s+type)\b",
    re.IGNORECASE,
)


def _explicit_level_in(question: str) -> "str | None":
    """The admin level the question names outright, or None. Finest-first so a
    question naming two levels ("village in X district") reports the one being
    asked about rather than the containing area."""
    q = question or ""
    if _CHIP_LEVEL_PHRASE_RE.search(q):
        q = _CHIP_SCOPE_SUFFIX_RE.sub("", q)
    q = _NEGATED_LEVEL_PHRASE_RE.sub(" ", q)
    q = _BREAKDOWN_LEVEL_PHRASE_RE.sub(" ", q)
    for dim in ("village", "assembly_constituency", "block", "district"):
        if _EXPLICIT_LEVEL_RE[dim].search(q):
            return dim
    return None


async def resolve_entities(question: str, schemes: list[str],
                            prior_resolved: "dict | None" = None,
                            village_hint: "str | None" = None,
                            mentions: "dict | None" = None) -> dict:
    """Thin wrapper around `_resolve_entities` (the real body, unchanged)
    whose only job is to stamp whatever was ALREADY resolved onto a
    ClarificationNeeded on its way out — see
    ClarificationNeeded.resolved_so_far for why, and
    ConversationState.pending_resolved for where it ends up.

    A wrapper rather than a try/except around the body itself: the body is
    ~400 lines with a dozen raise sites spread through it, and stamping
    each one by hand is exactly the kind of thing the next branch added to
    it would quietly forget to do. `resolved` is created here and passed
    in, so this function still holds a reference to the same dict the body
    was filling when it paused.

    `mentions` (optional): place/time spans already extracted by the caller,
    in extract_entity_mentions()'s shape — the Understand node's QueryFrame
    supplies these (app/nlu/understand.py::normalise_frame). When given, the
    LLM mention-extraction call is skipped and everything downstream
    (resolution, ambiguity/collision pauses, notes) runs unchanged on them."""
    resolved: dict[str, object] = {}
    try:
        return await _resolve_entities(question, schemes, prior_resolved,
                                        village_hint, resolved,
                                        dict(mentions) if mentions is not None else None)
    except ClarificationNeeded as e:
        if not e.resolved_so_far:
            e.resolved_so_far = {k: v for k, v in resolved.items() if v is not None}
        raise


async def _resolve_entities(question: str, schemes: list[str],
                            prior_resolved: "dict | None",
                            village_hint: "str | None",
                            resolved: dict,
                            mentions_override: "dict | None" = None) -> dict:
    """Resolve every extracted mention to a canonical DB value. Ambiguous ->
    raise ClarificationNeeded (ask, per the resolver's own hard rule — never
    guess). Not-found is not an error: it means the value genuinely is not in
    this data, which the response composer should say plainly, not silently
    drop the filter.

    `prior_resolved` (optional): the previous turn's resolved entities, passed
    only when this question is a rewritten follow-up. Used purely as a
    fallback — for any dimension (district/block/village_code/year_key) the
    CURRENT question names nothing for at all, carry the prior turn's value
    forward instead of leaving it unset. This covers a village/year the
    follow-up rewrite paraphrased away in its wording (the rewrite works from
    prev.question/answer TEXT, so an entity can silently vanish if it doesn't
    literally reappear). A dimension the current question DOES name something
    for (even something that fails to resolve) is left alone — the user is
    talking about something new for that slot, not carrying the old one over.

    `village_hint` (optional): the exact village-name text from a just-resumed
    village-ambiguity pause (ClarificationNeeded.village_hint /
    ConversationState.pending_village_hint). Used ONLY when this question's own mention
    extraction finds no village at all — the merged resume text ("...the one
    in Betasing block") does not reliably make the LLM re-tag the original
    village name, and without it SQL generation has no village_code to filter
    on and can invent one instead of using the now-resolved block/district."""
    # Out-of-range financial year — checked FIRST, before the LLM mention call
    # and any geography resolution. Works purely off the raw question text, so it
    # still fires when the extractor is unavailable or drops the year slot (a
    # comma-joined scope-pause reply like "wgh, 1999-20" does exactly that). A
    # year outside the data window makes the whole question unanswerable
    # regardless of the place, so this must not depend on anything downstream.
    # A scheme with NO time dimension at all can't offer year chips, and its
    # single "answer without a time filter" option loops forever — drop the
    # time filter and say so instead. See _scheme_has_no_time_dimension.
    _no_time_dim = _scheme_has_no_time_dimension(schemes)
    # Producer-group questions read curated.v_focus_legacy, whose years differ
    # from v_focus_plus's — check year ranges against those instead.
    _yschemes = _year_schemes_for(question, schemes)
    _pre_notes: list[str] = []
    if settings.YEAR_RANGE_GUARD_ENABLED:
        _yraw = _out_of_range_year_in(question, _yschemes)
        if _yraw is not None:
            if _no_time_dim:
                _pre_notes.append(_no_time_dimension_note(schemes))
            else:
                raise _year_out_of_range_clarification(question, _yraw, _yschemes)

    mentions = (mentions_override if mentions_override is not None
                else await extract_entity_mentions(question))

    # A named producer group ("Sakania PG") is not a place: take its name out of
    # every place slot and hand it to SQL generation as its own resolved filter.
    _pg_name = _pg_name_from_question(question) if _yschemes == ["Focus Legacy"] else None
    if _pg_name:
        _pgf = _pg_name.lower()
        for _slot in ("district", "block", "village", "assembly_constituency"):
            _v = str(mentions.get(_slot) or "").strip().lower()
            if _v and (_v in _pgf or _pgf in _v):
                mentions.pop(_slot, None)
        for _slot in ("districts", "blocks"):
            if isinstance(mentions.get(_slot), list):
                mentions[_slot] = [x for x in mentions[_slot]
                                   if str(x).strip().lower() not in _pgf]
        resolved["pg_name_pattern"] = "%" + "%".join(
            re.findall(r"[a-z0-9]+", _pgf)) + "%"
        logger.info("producer group named %r -> pg_name ILIKE %r",
                    _pg_name, resolved["pg_name_pattern"])

    notes: list[str] = list(_pre_notes)
    # Human-readable names for whatever the query ends up filtering on, keyed by
    # dimension. Handed to the response composer so it says "West Garo Hills",
    # not the "wgh" the user typed or the "WEST GARO HILLS" DB literal.
    display: dict[str, str] = {}
    # Tell the answer composer what "PG" means here — without it the model
    # hedged that "PGs" might mean pay grades and its answer was discarded.
    if _yschemes == ["Focus Legacy"]:
        display["producer_group"] = (f"{_pg_name} (FOCUS producer group)" if _pg_name
                                     else "FOCUS producer groups (PG = producer group)")

    # The admin level the question states outright — the user said it ("the
    # Mawlai constituency") or this is a resumed level-choice chip ("..., the
    # assembly constituency, not another area type"). When stated, move the
    # place name into that slot and clear the others, so it resolves at the
    # chosen level and nowhere else. The name is re-read from the question
    # TEXT (the chip wrote the canonical name there) because the extractor
    # often echoes the user's original typo back into the wrong slot.
    _stated_level = _explicit_level_in(question)
    if _stated_level in ("district", "block", "assembly_constituency", "village") \
            and not mentions.get("districts") and not mentions.get("blocks"):
        _placed = None
        if _stated_level == "village":
            _placed = (mentions.get("village") or mentions.get("block")
                       or mentions.get("assembly_constituency")
                       or mentions.get("district") or village_hint)
        else:
            _placed = _canonical_in_question(question, schemes[0] if schemes else "", _stated_level)
            if not _placed:
                for _slot in ("district", "block", "village", "assembly_constituency"):
                    _v = mentions.get(_slot)
                    if _v and (await resolve_dimension(
                            str(_v), schemes[0], _stated_level)).status == "resolved":
                        _placed = str(_v)
                        break
        # Keep the containing scope the question names alongside the place (a
        # village chip's ", RONGRAM block, WEST GARO HILLS") — only the
        # ambiguous place name itself is being re-levelled. Scope values are
        # kept only when they genuinely resolve at their own level.
        if _placed:
            _scope_slots = ("district", "block") if _stated_level == "village" else ("district",)
            _keep: dict[str, object] = {}
            for _slot in _scope_slots:
                _v = mentions.get(_slot)
                if _slot != _stated_level and _v and str(_v).lower() != str(_placed).lower() \
                        and (await resolve_dimension(str(_v), schemes[0], _slot)).status == "resolved":
                    _keep[_slot] = _v
            for _slot in ("district", "block", "village", "assembly_constituency"):
                mentions.pop(_slot, None)
            mentions[_stated_level] = _placed
            mentions.update(_keep)
            logger.info("explicit level %r — placed %r, cleared other place slots",
                        _stated_level, _placed)

    # ── Admin-level collision gate ──────────────────────────────────────────
    # Before resolving any single place name, check whether it names more than
    # one KIND of area (block vs assembly constituency vs village). The
    # per-dimension branches below each see one slot in isolation and can only
    # ever offer block-vs-village, so a bare "Mawlai" (block, AC 15 and a
    # village) never offered the constituency reading. Skipped when the level
    # is already stated, for plural comparisons, and while a village_hint
    # carries a just-resumed village choice.
    if _stated_level is None and not village_hint \
            and not mentions.get("districts") and not mentions.get("blocks"):
        _scheme0 = schemes[0] if schemes else ""
        if not any(mentions.get(s) for s in
                   ("district", "block", "village", "assembly_constituency")):
            # The extractor sometimes drops a plainly-named place; scan the
            # raw text for a catalogue block/AC name so the gate can see it.
            _found = None
            for _dim in ("block", "assembly_constituency"):
                _found = _canonical_in_question(question, _scheme0, _dim)
                if _found:
                    mentions = {**mentions, _dim: _found}
                    logger.info("admin-level gate: %r scanned from question text", _found)
                    break
            # Exact scan misses a MISSPELLED place ("mawlwai"); let the
            # resolver's fuzzy stage judge the "in <name>" phrases instead.
            # Whether it actually pauses is still decided below (2+ readings).
            if not _found:
                for _cand in _place_phrase_candidates(question, _scheme0):
                    if _pg_name and _cand.lower() in _pg_name.lower():
                        continue  # the producer group's own name, not a place
                    if collides_across_dimensions(_cand, _scheme0, village_hit=True):
                        mentions = {**mentions, "block": _cand}
                        logger.info("admin-level gate: %r fuzzy-scanned from question text", _cand)
                        break
        for _slot in ("district", "block", "village", "assembly_constituency"):
            _name = mentions.get(_slot)
            if not _name:
                continue
            # A district name is never level-ambiguous (collides_across_dimensions
            # returns nothing for one) — don't spend a DB probe on it.
            if not collides_across_dimensions(str(_name), _scheme0, village_hit=True):
                break
            try:
                _vr_probe = await resolve_village(str(_name))
                _village_hit = _vr_probe.status in ("resolved", "ambiguous")
            except Exception as e:  # noqa: BLE001 — the gate only decides whether to ask
                logger.warning("admin-level gate: village probe for %r failed: %s", _name, e)
                _village_hit = False
            _dims = collides_across_dimensions(str(_name), _scheme0, village_hit=_village_hit)
            # Drop the AC reading when this question's metric has no AC column
            # (only MGNREGA employment carries one) — offering it would invite
            # a choice that can never be answered.
            if "assembly_constituency" in _dims and not _ac_dimension_available(question, schemes):
                _dims = {k: v for k, v in _dims.items() if k != "assembly_constituency"}
                if len(_dims) < 2:
                    _dims = {}
            if _dims:
                logger.info("admin-level collision on %r: %s — asking", _name, list(_dims))
                raise _dimension_collision_clarification(question, str(_name), _dims)
            break

    district_canon = None
    if mentions.get("districts"):
        # Two-or-more named districts to compare against each other (see
        # extract_entity_mentions) — resolve each independently and carry the
        # whole set forward as an IN-list, instead of the singular "district"
        # dimension which can only ever hold one value and would silently
        # drop every district but the last (the "compare ekh and wgh" bug).
        _district_canons: list[str] = []
        _district_displays: list[str] = []
        for _dname in mentions["districts"]:
            r = await resolve_dimension(_dname, schemes[0], "district")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which district is being referred to by “{_dname}”?",
                                           rule="entity-ambiguous")
            if r.status != "resolved":
                notes.append(f"'{_dname}' is not a known district — say so, do not filter on it.")
                continue
            _district_canons.append(r.canonical)
            _district_displays.append(r.display or str(_dname).title())
        if _district_canons:
            resolved["district_list"] = _district_canons
            display["district"] = " and ".join(_district_displays)
    else:
        if not mentions.get("district"):
            # The LLM mention-extractor intermittently drops a plainly-named district
            # ("how many villages are covered in West Garo Hills" -> {}); fall back to
            # a deterministic scan of the raw question against the 12-name closed set.
            backstop = scan_dimension(question, schemes[0], "district")
            if backstop and backstop.status == "resolved":
                district_canon = backstop.canonical
                resolved["district"] = backstop.canonical
                display["district"] = backstop.display or str(backstop.canonical).title()
                logger.info("resolve_entities: district backstop matched %r in question text",
                            backstop.canonical)
        # A hill-range name ("Garo Hills", "Khasi region") the extractor tagged as a
        # district isn't one — leave it unresolved so _answer_data's region handler can
        # offer the range's districts as chips (or expand it). Don't raise the generic
        # "which district?" here.
        _mdist = mentions.get("district")
        if _mdist and detect_region(_mdist, schemes[0] if schemes else "") is not None:
            _mdist = None
        if _mdist:
            r = await resolve_dimension(_mdist, schemes[0], "district")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which district is being referred to by “{_mdist}”?",
                                           rule="entity-ambiguous")
            if r.status == "resolved":
                district_canon = r.canonical
                resolved["district"] = r.canonical
                display["district"] = r.display or str(r.canonical).title()
            else:
                # Not a known district — it may be a VILLAGE the extractor
                # mistagged as "district" (a bare place name after "in" gives the
                # model no reliable signal for which admin level it is). Try
                # village resolution before concluding this is out of scope.
                _vr = await resolve_village(_mdist)
                _named = (_village_candidate_named_in(question, _vr.candidates)
                          if _vr.status == "ambiguous" else None)
                if _named is not None:
                    resolved["village_code"] = _named["village_code"]
                    display["village"] = str(_named["name"]).title()
                elif _vr.status == "ambiguous":
                    listed = ", ".join(
                        f"{c['name']} in {c['block']} block ({c['district']})" for c in _vr.candidates[:5])
                    options = [
                        {"label": f"{c['name']} — {c['block']} block, {c['district']}",
                         "question": _village_chip_question(question, _mdist, c)}
                        for c in _vr.candidates[:5]
                    ]
                    raise ClarificationNeeded(
                        f"“{_mdist}” corresponds to more than one village: {listed}. "
                        "Which of these is intended?",
                        options=options, rule="entity-ambiguous", village_hint=_mdist)
                if _named is not None:
                    pass  # already resolved from the question text above
                elif _vr.status == "resolved":
                    resolved["village_code"] = _vr.canonical
                    display["village"] = _vr.display or str(_mdist).title()
                elif settings.OUT_OF_SCOPE_GUARD_ENABLED:
                    # Genuinely not a district, block, or village of ours — almost
                    # always a place in another state ("districts in Guwahati").
                    # Don't silently drop the filter and count 0; say plainly
                    # this is out of scope.
                    raise OutOfScope(f"district '{_mdist}' is not in Meghalaya")
                else:
                    notes.append(f"'{_mdist}' is not a known district — say so, do not filter on it.")

    if mentions.get("blocks"):
        # Two-or-more named blocks to compare against each other (see
        # extract_entity_mentions) — resolve each independently and carry the
        # whole set forward as an IN-list, instead of the singular "block"
        # dimension which can only ever hold one value and would silently
        # drop every block but the last.
        _has_block_word = bool(re.search(r"\bblock\b", question, re.IGNORECASE))
        _block_canons: list[str] = []
        _block_displays: list[str] = []
        for _bname in mentions["blocks"]:
            r = await resolve_dimension(_bname, schemes[0], "block")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which block is being referred to by “{_bname}”?",
                                           rule="entity-ambiguous")
            if r.status != "resolved":
                notes.append(f"'{_bname}' is not a known block — say so, do not filter on it.")
                continue
            if not _has_block_word:
                _vcheck = await resolve_village(_bname)
                if _vcheck.status in ("resolved", "ambiguous"):
                    stem = question.strip().rstrip(" ?.")
                    raise ClarificationNeeded(
                        f"“{_bname}” could mean either the block or a village with "
                        "that name. Which did you mean?",
                        options=[
                            {"label": f"The {_bname} block", "question": f"{stem}, the block, not the village"},
                            {"label": f"The {_bname} village", "question": f"{stem}, the village, not the block"},
                        ],
                        rule="entity-ambiguous")
            _block_canons.append(r.canonical)
            _block_displays.append(r.display or str(_bname).title())
        if _block_canons:
            resolved["block_list"] = _block_canons
            display["block"] = " and ".join(_block_displays)
    elif mentions.get("block"):
        r = await resolve_dimension(mentions["block"], schemes[0], "block")
        if r.status == "ambiguous":
            raise ClarificationNeeded(f"Which block is being referred to by “{mentions['block']}”?",
                                       rule="entity-ambiguous")
        if r.status == "resolved":
            # Block and village names collide constantly in Meghalaya (26 of 56
            # block names are also village names, per the resolver YAML) — a bare
            # name the user didn't explicitly call a "block" is genuinely
            # ambiguous. Silently answering at the block level here is exactly
            # the bug QA reported (bot picks village data for a block question,
            # or vice versa, without ever asking).
            if not re.search(r"\bblock\b", question, re.IGNORECASE):
                _vcheck = await resolve_village(mentions["block"])
                if _vcheck.status in ("resolved", "ambiguous"):
                    stem = question.strip().rstrip(" ?.")
                    raise ClarificationNeeded(
                        f"“{mentions['block']}” could mean either the block or a village with "
                        "that name. Which did you mean?",
                        options=[
                            {"label": f"The {mentions['block']} block", "question": f"{stem}, the block, not the village"},
                            {"label": f"The {mentions['block']} village", "question": f"{stem}, the village, not the block"},
                        ],
                        rule="entity-ambiguous")
            resolved["block"] = r.canonical
            display["block"] = r.display or str(r.canonical).title()
        else:
            # The mention-extractor sometimes tags a full DISTRICT name as the
            # "block" when the question itself says "by block" right next to it
            # ("compare ... by block in West Garo Hills") — it reads the phrase
            # "by block in X" as naming X as the block. Before treating this as
            # not-a-known-block (or, worse, OutOfScope — a real district getting
            # rejected as "not in Meghalaya" is a confusing wrong answer), check
            # whether the same text is actually a district and use it as one.
            _as_district = await resolve_dimension(mentions["block"], schemes[0], "district")
            if _as_district.status == "resolved":
                # Either newly discovered here, or (commonly) the SAME text was
                # already captured as the district via the raw-text backstop
                # scan above (mentions.get("district") was empty, so that scan
                # ran on the full question text and found "West Garo Hills"
                # there too) — in that case district_canon is already set and
                # this "block" mention is just a duplicate tag for it. Either
                # way, there's nothing wrong here: don't overwrite an existing
                # district_canon, and don't fall through to "not a known block".
                # Also skip when a district_list comparison already resolved —
                # this "block" mention is then just the extractor's other tag
                # for one of those same districts.
                if not district_canon and not resolved.get("district_list"):
                    district_canon = _as_district.canonical
                    resolved["district"] = _as_district.canonical
                    display["district"] = _as_district.display or str(_as_district.canonical).title()
            else:
                # Also not a district — it may be a VILLAGE the extractor
                # mistagged as "block" (villages far outnumber blocks, and a
                # bare name after "in" gives the model no reliable signal for
                # which admin level it is — e.g. "PMAY beneficiaries in
                # Abagre", a real West Garo Hills village). Try village
                # resolution before concluding this is out of scope. Scope by
                # district_canon when the question already pinned one down —
                # otherwise a village-disambiguation chip's own answer text
                # ("Nongthymmai, MAWRYNGKNENG block, EAST KHASI HILLS") gets
                # re-resolved with no district scope, rediscovers the exact
                # same statewide candidate set the chip was meant to narrow,
                # and raises the identical clarification forever (reported
                # 2026-09-09, "nongthymmai" in EAST KHASI HILLS).
                _vr = await resolve_village(mentions["block"], district=district_canon)
                if _vr.status == "ambiguous":
                    # District scoping alone doesn't always get to one candidate
                    # (e.g. several distinctly-blocked villages share a name inside
                    # the same district). The chip that got us here already names
                    # the intended block in its own text ("Nongthymmai, MAWRYNGKNENG
                    # block, EAST KHASI HILLS") — the LLM extractor just keeps
                    # re-tagging the village as "block" and dropping the real block,
                    # so re-resolving lands back on the SAME candidate set every
                    # round and the clarification loops forever (reported
                    # 2026-09-09, "nongthymmai" in EAST KHASI HILLS). Before asking
                    # again, check the raw text deterministically: if exactly one
                    # candidate's own block name appears in it, that already IS the
                    # user's answer.
                    _named = _village_candidate_named_in(question, _vr.candidates)
                    _text_hits = [_named] if _named is not None else [
                        c for c in _vr.candidates
                        if c.get("block") and re.search(
                            rf"\b{re.escape(c['block'])}\b", question, re.IGNORECASE)
                    ]
                    if len(_text_hits) == 1:
                        _pick = _text_hits[0]
                        resolved["village_code"] = _pick["village_code"]
                        display["village"] = str(_pick["name"]).title()
                        _vr = None
                    else:
                        listed = ", ".join(
                            f"{c['name']} in {c['block']} block ({c['district']})" for c in _vr.candidates[:5])
                        options = [
                            {"label": f"{c['name']} — {c['block']} block, {c['district']}",
                             "question": _village_chip_question(question, mentions["block"], c)}
                            for c in _vr.candidates[:5]
                        ]
                        raise ClarificationNeeded(
                            f"“{mentions['block']}” corresponds to more than one village: {listed}. "
                            "Which of these is intended?",
                            options=options, rule="entity-ambiguous", village_hint=mentions["block"])
                if _vr is None:
                    pass  # already resolved directly from the single text hit above
                elif _vr.status == "resolved":
                    resolved["village_code"] = _vr.canonical
                    display["village"] = _vr.display or str(mentions["block"]).title()
                elif settings.OUT_OF_SCOPE_GUARD_ENABLED:
                    raise OutOfScope(f"block '{mentions['block']}' is not in Meghalaya")
                else:
                    notes.append(f"'{mentions['block']}' is not a known block — say so, do not filter on it.")

    if mentions.get("assembly_constituency"):
        r = await resolve_dimension(mentions["assembly_constituency"], schemes[0], "assembly_constituency")
        if r.status == "ambiguous":
            raise ClarificationNeeded(
                f"Which assembly constituency is being referred to by "
                f"“{mentions['assembly_constituency']}”?", rule="entity-ambiguous")
        if r.status == "resolved":
            resolved["assembly_constituency"] = r.canonical
            display["assembly_constituency"] = r.display or str(r.canonical).title()
            # Having settled on the constituency, offer to narrow inside it —
            # unless the question already narrowed itself (a resumed
            # drill-down chip, "the whole constituency", or another named
            # area). A resumed "within the X block only" chip is applied here
            # deterministically; the extractor has no reason to tag it.
            _already_narrowed = (
                _AC_SCOPED_RE.search(question)
                or re.search(r"\bwhole\s+constituency\b", question, re.IGNORECASE)
                or any(resolved.get(k) for k in
                       ("district", "district_list", "block", "block_list",
                        "village_code", "village_code_list"))
            )
            _narrow = _AC_NARROW_RE.search(question)
            if _narrow:
                _lvl = _narrow.group("level").lower()
                _nm = _narrow.group("name").strip()
                _nr = await resolve_dimension(_nm, schemes[0], _lvl)
                if _nr.status == "resolved":
                    _canon, _disp = _nr.canonical, _nr.display or str(_nr.canonical).title()
                else:
                    # The chip's value was read live from curated.v_employment,
                    # so it is a valid (upper-case) literal even when the YAML
                    # catalogue has no entry for it.
                    _canon, _disp = _nm.upper(), _nm.title()
                resolved[_lvl] = _canon
                display[_lvl] = _disp
                if _lvl == "district":
                    district_canon = _canon
                logger.info("AC drill-down: also filtering %s = %r", _lvl, _canon)
            elif not _already_narrowed:
                _contents = await constituency_contents(str(r.canonical))
                _drill = _ac_drilldown_clarification(
                    question, display["assembly_constituency"], _contents)
                if _drill is not None:
                    raise _drill
        else:
            # assembly_constituency data exists ONLY in mgnrega_employment (no
            # catalogue loaded for other schemes, or the name genuinely isn't
            # one) — say so instead of silently falling back to a block/
            # district filter, which would answer a different, unintended level.
            notes.append(
                f"'{mentions['assembly_constituency']}' is not a known assembly constituency "
                f"for {schemes[0] if schemes else 'this scheme'} — say so, do not silently "
                "filter on a block or district instead.")

    if mentions.get("year"):
        raw_year = mentions["year"]
        year_key = None
        # MGNREGA has a curated year catalogue (handles aliases like "FY24",
        # "last year"); try it first when MGNREGA is in play.
        if "MGNREGA" in schemes:
            r = await resolve_dimension(raw_year, "MGNREGA", "year")
            if r.status == "ambiguous":
                # A bare "2023" is FY 2022-23 or FY 2023-24 and the year
                # catalogue's own rule is to ask, never default. Ask with
                # one-tap chips and a RESUMABLE rule — see
                # _year_ambiguity_clarification for what the bare raise
                # this replaces did to the live UI.
                raise _year_ambiguity_clarification(
                    question, raw_year, r.candidates, schemes,
                    village_hint=mentions.get("village") or village_hint,
                    resolved_so_far=resolved)
            if r.status == "resolved":
                year_key = r.canonical
        # Fallback / PMAY path — PMAY has no year catalogue, so parse the FY start
        # year straight from the text ("2023", "2023-24", "FY 2023-24" -> 2023).
        if year_key is None:
            year_key = _parse_year_key(raw_year)
        if year_key is not None and not _year_in_data_range(year_key, _yschemes):
            # A real, parseable year — just not one these scheme(s) hold.
            if _no_time_dim:
                # No scheme here has ANY year, so there is no coverage range to
                # quote and no chip worth offering — drop the filter, say so,
                # and answer. See _scheme_has_no_time_dimension.
                notes.append(_no_time_dimension_note(schemes))
            else:
                if settings.YEAR_RANGE_GUARD_ENABLED:
                    raise _year_out_of_range_clarification(question, raw_year, _yschemes)
                _yrs, _lv = _available_years_for(_yschemes)
                notes.append(f"'{raw_year}' is outside the data "
                             f"({', '.join(_lv)} cover FY {_yrs[0]} to FY {_yrs[-1]} only).")
        elif year_key is None:
            # Couldn't pin it to a year at all. If it was plainly typed as one
            # ("1999-20", "FY 2019-20"), it's an out-of-range year we simply
            # failed to parse — say the coverage, same as above; otherwise it's
            # gibberish in the year slot, so leave a soft note and move on.
            if _no_time_dim:
                notes.append(_no_time_dimension_note(schemes))
            else:
                if settings.YEAR_RANGE_GUARD_ENABLED and _looks_like_year_mention(raw_year):
                    raise _year_out_of_range_clarification(question, raw_year, _yschemes)
                notes.append(f"'{raw_year}' is not a recognisable financial year.")
        else:
            # Both v_employment and v_pmay key the year on `year_key` (smallint).
            resolved["year_key"] = year_key
            display["year"] = f"FY {year_key}-{(year_key + 1) % 100:02d}"

    # Prefer the current question's own village mention; fall back to the
    # remembered hint from a just-resumed village-ambiguity pause only when
    # this turn's extraction found no village at all (see the docstring above).
    _village_text = mentions.get("village") or village_hint
    if _village_text:
        r = await resolve_village(_village_text, district=district_canon,
                                   block=resolved.get("block"))
        _named = (_village_candidate_named_in(question, r.candidates)
                  if r.status == "ambiguous" else None)
        if _named is not None:
            resolved["village_code"] = _named["village_code"]
            display["village"] = str(_named["name"]).title()
        elif r.status == "ambiguous":
            # Two candidates can share the same (name, district) while being
            # genuinely different villages in different blocks with their own
            # data (e.g. two "Adugre"s in SOUTH WEST GARO HILLS — one in
            # Betasing block, one in Rerapara) — block is the distinguishing
            # feature, so it MUST be in both the message and the chip label, or
            # they read as duplicates and the user can't tell them apart.
            listed = ", ".join(
                f"{c['name']} in {c['block']} block ({c['district']})" for c in r.candidates[:5])
            options = [
                {"label": f"{c['name']} — {c['block']} block, {c['district']}",
                 "question": _village_chip_question(question, _village_text, c)}
                for c in r.candidates[:5]
            ]
            raise ClarificationNeeded(
                f"“{_village_text}” corresponds to more than one village: {listed}. "
                "Which of these is intended?",
                options=options,
                rule="entity-ambiguous",
                village_hint=_village_text)
        if _named is not None:
            pass  # already resolved from the question text above
        elif r.status == "resolved":
            # Symmetric check to the block branch above: this name might also be
            # a block name. Only worth asking when the district/block scope
            # didn't already pin it down (a village resolved WITH a district
            # scope is unambiguous) and the user didn't already say "village".
            if not district_canon and not re.search(r"\bvillage\b", question, re.IGNORECASE):
                _bcheck = await resolve_dimension(_village_text, schemes[0], "block")
                if _bcheck.status == "resolved":
                    stem = question.strip().rstrip(" ?.")
                    raise ClarificationNeeded(
                        f"“{_village_text}” could mean either the village or a block "
                        "with that name. Which did you mean?",
                        options=[
                            {"label": f"The {_village_text} village", "question": f"{stem}, the village, not the block"},
                            {"label": f"The {_village_text} block", "question": f"{stem}, the block, not the village"},
                        ],
                        rule="entity-ambiguous")
            resolved["village_code"] = r.canonical
            display["village"] = r.display or str(_village_text).title()
        else:
            notes.append(f"'{_village_text}' is not a known village — say so, do not filter on it.")

    # PMAY house-construction-stage ("Proposed Site", "Existing site(Old House)",
    # "plinth stage", "not started", …). A closed set the LLM mention-extractor
    # above doesn't cover — matched deterministically against the SME alias
    # catalogue over the whole question. "completed" / "in progress" are left to
    # the is_completed / is_in_progress boolean path on purpose.
    if "PMAY-G" in schemes:
        hs = resolve_house_status(question, "PMAY-G")
        if hs and hs.values:
            resolved["house_status"] = hs.values if len(hs.values) > 1 else hs.values[0]
            display["house_status"] = hs.display or " and ".join(hs.values)

    # Focus Plus tranche_label ("Tranch 1".."Tranch 4 - Feb-March") — closed set,
    # not covered by the LLM mention-extractor, and routinely mistyped against
    # its odd stored spelling ("tranche2" vs "Tranch 2 - August"). Resolved
    # deterministically (with a RapidFuzz fallback for misspellings) so a
    # near-miss maps to the exact stored label instead of silently filtering
    # the SQL to zero rows and reporting a misleading null total.
    if "Focus Plus" in schemes:
        tr = resolve_tranche_label(question, "Focus Plus")
        if tr and tr.values:
            resolved["tranche_label"] = tr.values if len(tr.values) > 1 else tr.values[0]
            display["tranche_label"] = tr.display or " and ".join(tr.values)

    # CM Elevate sub-scheme ("Piggery", "Dairy Development", ... — a 15-value
    # closed set), resolved deterministically to the EXACT stored scheme_name
    # (ported from the pre-restructure codebase). Left to the SQL generator,
    # "Piggery" became scheme_name = 'Piggery' and counted 0 instead of the 169
    # East Khasi Hills applications under 'Meghalaya Piggery Development
    # Scheme' (2026-09-23 regression sweep).
    if "CM Elevate" in (schemes or []):
        cs = resolve_cm_scheme(question, "CM Elevate")
        if cs and cs.values:
            resolved["cm_scheme"] = cs.values if len(cs.values) > 1 else cs.values[0]
            display["cm_scheme"] = cs.display or " and ".join(cs.values)

    # Focus Plus batch_label ('93K' legacy paid cohort / '12.5K' newer
    # registration cohort) — a closed two-value set. Resolved here so the SQL
    # verifier sees the filter as a resolved value; left to the generator it
    # rejected `batch_label = '12.5K'` as an unresolved substitution, and the
    # "members with an id in the newer batch" chip never answered
    # (2026-09-23). Only when exactly ONE cohort is named — a side-by-side
    # comparison of the readings spans both.
    if list(schemes or []) == ["Focus Plus"] and not _is_producer_group_question(question):
        _b = _focus_plus_batch_in(question)
        if _b:
            resolved["batch_label"] = _b
            display["batch"] = ("newer registration batch (12.5K)" if _b == "12.5K"
                                else "legacy paid batch (93K)")

    if prior_resolved:
        if not mentions.get("district") and "district" not in resolved and prior_resolved.get("district"):
            resolved["district"] = prior_resolved["district"]
        if not mentions.get("block") and "block" not in resolved and prior_resolved.get("block"):
            resolved["block"] = prior_resolved["block"]
        if not mentions.get("year") and "year_key" not in resolved and prior_resolved.get("year_key"):
            resolved["year_key"] = prior_resolved["year_key"]
        if not mentions.get("village") and "village_code" not in resolved and prior_resolved.get("village_code"):
            resolved["village_code"] = prior_resolved["village_code"]
        # Focus Plus tranche pin — same fallback as district/block/village/year
        # above. There is no LLM `mentions` signal for tranche_label (it's
        # resolved deterministically, not via mention extraction — see
        # resolve_tranche_label), so the only guard needed is that THIS
        # question's own resolution found nothing: a bare short follow-up
        # ("top 3 only") that never re-says "tranche" would otherwise lose the
        # tranche the previous turn pinned. Only ever carries a real stored
        # label — never a sentinel — so it stays safe to drop straight into
        # the SQL prompt's tranche_label filter (see prompt_builder._entities_block).
        if (schemes == ["Focus Plus"] and "tranche_label" not in resolved
                and prior_resolved.get("tranche_label")):
            resolved["tranche_label"] = prior_resolved["tranche_label"]

    return {"resolved": resolved, "notes": notes, "display": display}


def _join_path_hint(retrieved: list[dict]) -> join_graph.JoinPathResult | None:
    """Given schema-retrieval candidates, look up a join path ONLY when
    retrieval itself named 2+ distinct table-granularity tables — a real,
    already-computed pre-generation signal, not an invented one (see
    design.md's "Join discovery gates SQL generation only where it has a
    genuine pre-generation signal" decision). Returns None when there are
    fewer than 2 such tables, meaning: no gate, no hint, behavior unchanged.

    The GATE (a non-"ok" status escalated to ClarificationNeeded by the
    caller) fires only when the two candidates come from two different
    schemes — which is what this guard was always scoped to, per the original
    note that "every piloted scheme has exactly one fact table, so this can
    only arise across schemes". That premise does not hold for the retrieved
    set: schema_metadata_ingest tags every curated VIEW with
    granularity == "table" too, and each scheme declares its top-level views
    self-contained (empty adjacency / "joins_needed: none" in
    foreign_key_augmentation.yaml). Two such views from the SAME scheme —
    e.g. MGNREGA's v_district_year_summary and v_expenditure — are competing
    ALTERNATIVES for answering one question, never operands of a join, so
    BFS between them always reports no_path. Gating on that hard-blocked
    ordinary single-scheme questions behind a clarification the user cannot
    act on. Same-scheme pairs therefore still produce an additive hint when a
    real path exists, and simply produce nothing when one does not.
    "shared" (conformed dimensions such as curated.dim_geography) is not a
    scheme and never makes a pair cross-scheme on its own."""
    scheme_of: dict[str, str | None] = {}
    for r in retrieved:
        if r.get("granularity") == "table" and r["ref"] not in scheme_of:
            scheme_of[r["ref"]] = r.get("scheme_id")
    table_refs = list(scheme_of)
    if len(table_refs) < 2:
        return None

    pair = table_refs[:2]
    result = join_graph.find_join_path(pair)
    if result.status != "ok":
        schemes = {scheme_of[t] for t in pair if scheme_of[t] and scheme_of[t] != "shared"}
        if len(schemes) < 2:
            # Single-scheme pair: alternative views, not a join. No gate.
            return None
    return result


def _one_scheme_at_a_time_options(question: str, schemes: "list[str] | None") -> list[dict]:
    """One chip per scheme for a cross-scheme join pause, so it is never a dead
    end: each chip re-asks the question for that one scheme alone."""
    stem = (question or "").strip().rstrip(" ?.")
    return [{"label": f"Just {s}", "question": f"{stem} for {s}"} for s in (schemes or [])]


async def generate_sql(question: str, schemes: list[str], entity_result: dict) -> str:
    # The frame drives generation. The most common KPI shape (one scheme's
    # metric value for an area / year) is filled straight from an SME-verified
    # template — no model call; everything else is generated with a REQUIRED
    # FILTERS block from the frame (prompt_builder picks it up from the same
    # context). No Understand frame this turn => plain generation, as before.
    frame = understand.sql_frame()
    if frame is not None:
        picked = sql_templates.choose(frame, schemes, entity_result, entity_result.get("gate_trace"))
        if picked is not None:
            key, sql = picked
            entity_result.setdefault("gate_trace", []).append(f"sql:template:{key}")
            logger.info("SQL from template %s (no model call)", key)
            return sql
        entity_result.setdefault("gate_trace", []).append("sql:llm")
    # Schema-retrieval node (§5.8) — semantic candidates that supplement the
    # hand-written backbone below; [] for any scheme not yet indexed into
    # megh_schema_metadata, which leaves the prompt unchanged (see design.md's
    # "additive, not gating" decision).
    retrieved = await schema_retrieval.retrieve(question, schemes)

    # Join discovery (§5.9) — gate generation only in the narrow case where
    # retrieval itself supplied 2+ required tables and the graph says they
    # can't be safely joined; otherwise fold a valid path in as an additive
    # hint (same enforcement tier as PROHIBITED JOINS — see design.md).
    join_result = _join_path_hint(retrieved)
    # Retrieval sometimes pairs two tables the question doesn't need at all
    # (CM Elevate "total applications by scheme" retrieved
    # dim_cm_elevate_scheme + v_district_year_summary) and the pause below
    # then refused a question v_cm_elevate alone answers (2026-09-23 KPI
    # sweep, DC-01). When every retrieved table belongs to the one scheme
    # being asked about, drop the join hint and generate normally — the
    # post-generation join validator (_execute_one_attempt) still rejects
    # any unsafe join the SQL actually makes.
    # Same when retrieval pulled in a table from a scheme the question isn't
    # about (CM Elevate "gender split by scheme" retrieved v_employment +
    # v_pmay_monthly_sanctions) — that is a retrieval misfire, not a join the
    # user asked for. The gate stays for a genuine cross-scheme question whose
    # two tables both belong to schemes being asked about.
    if join_result is not None and join_result.status in ("no_path", "fan_out_guard"):
        _asked = set(schemes or [])
        _owners = {prompt_builder._scheme_of(str(t).split(".")[-1]) for t in join_result.tables}
        _owners.discard("shared")
        _owners.discard("cross")
        if len(schemes or []) == 1 or not _owners <= _asked:
            logger.info("join hint %s for %s ignored (single-scheme question or table "
                        "outside the asked schemes %s)",
                        join_result.status, join_result.tables, sorted(_asked))
            join_result = None
    if join_result is not None and join_result.status == "no_path":
        raise ClarificationNeeded(
            "I couldn't find an approved way to connect "
            f"{join_result.tables[0]} and {join_result.tables[1]} for this "
            "question — could you narrow it to one of them, or ask about "
            "them separately?",
            options=_one_scheme_at_a_time_options(question, schemes),
            rule="join-no-path",
        )
    if join_result is not None and join_result.status == "fan_out_guard":
        raise ClarificationNeeded(
            "Combining "
            f"{join_result.tables[0]} and {join_result.tables[1]} directly "
            "would double-count rows (no shared dimension between them) — "
            "could you ask about them one at a time, or via a scheme-level summary?",
            options=_one_scheme_at_a_time_options(question, schemes),
            rule="join-fan-out",
        )

    # The whole prompt — hand-written backbone + live schema + SME catalog +
    # prohibited joins + retrieved schema notes + required join hint +
    # few-shot + resolved entities — is assembled in one place.
    joins = join_result.joins if join_result is not None and join_result.status == "ok" else None
    prompt = await prompt_builder.build_sql_prompt(question, schemes, entity_result, retrieved, joins)
    raw = await llm.call_sql_generator(prompt, guided={"guided_regex": _SQL_SHAPE_REGEX})
    return _extract_sql(raw)


# The generator sometimes reads "in Meghalaya" as a place filter and invents a
# WHERE on a state pseudo-row that no fact row matches — the query then runs
# clean but counts 0. Catch that shape and force one repair pass (the repair
# prompt carries the "whole dataset is Meghalaya" rule, so it drops the filter).
_STATE_PSEUDO_FILTER = re.compile(
    r"entity_type\s*=\s*'\s*state\s*'"
    r"|lgd_(?:village_name|district|block)\s*(?:=|ilike)\s*'\s*%?\s*meghalaya\s*%?\s*'",
    re.IGNORECASE,
)


# curated.* stores lgd_district / lgd_block UPPERCASE (docs/DATA_MODEL.md). When
# entity resolution misses and the generator copies the question's Title-Case
# spelling straight into the literal (lgd_district = 'West Garo Hills'), the
# query runs clean and counts zero. Upper-case *only* the string literals
# compared with `=` / `!=` / `IN` against those two columns — nothing else is
# touched, and an already-uppercase or ILIKE clause is left as-is.
_GEO_LITERAL_RE = re.compile(
    r"(?P<pre>\blgd_(?:district|block)\s*(?:=|!=|<>|\bIN\b)\s*\(?\s*)"
    r"(?P<lits>'(?:[^']|'')*'(?:\s*,\s*'(?:[^']|'')*')*)",
    re.IGNORECASE,
)


def _uppercase_geo_literals(sql: str) -> str:
    changed = _GEO_LITERAL_RE.sub(lambda m: m.group("pre") + m.group("lits").upper(), sql)
    if changed != sql:
        logger.info("normalised lgd_district/lgd_block literal(s) to upper-case for storage match")
    return changed


# A `column "X" does not exist` error usually means the generator picked a view
# that lacks a geography column (e.g. v_pmay_monthly_sanctions) rather than a
# genuine typo. Point the repair at the objects that DO carry the column instead
# of just echoing the Postgres message back.
_MISSING_COL_RE = re.compile(r'column "([\w.]+)" does not exist', re.IGNORECASE)
_COL_HOMES = {
    "lgd_district": "curated.v_pmay, curated.v_employment, curated.v_expenditure, "
                    "curated.v_district_year_summary, curated.v_focus_plus, "
                    "curated.v_cm_elevate, "
                    "curated.v_cross_scheme_money_district_year, curated.dim_geography",
    "lgd_block": "curated.v_pmay, curated.v_employment, curated.v_expenditure, "
                 "curated.v_focus_plus, curated.v_cm_elevate, curated.dim_geography",
    "lgd_village_name": "curated.v_pmay, curated.v_employment, curated.v_expenditure, "
                        "curated.v_focus_plus, curated.v_cm_elevate, curated.dim_geography",
}


def _missing_column_hint(error: str) -> "str | None":
    m = _MISSING_COL_RE.search(error)
    if not m:
        return None
    col = m.group(1).split(".")[-1].lower()
    if col in ("scheme_key", "scheme_code"):
        # The generator added a scheme filter/join to a per-scheme object that
        # carries neither column. scheme_key / scheme_code live ONLY on
        # curated.dim_scheme and curated.v_cross_scheme_money_district_year.
        # Every row in curated.v_pmay / v_expenditure / v_employment /
        # fact_pmay_house / fact_mgnrega_* already belongs to one scheme, so a
        # single-scheme question needs no scheme filter and no join to
        # dim_scheme at all.
        return (f'"{col}" does not exist on the object the previous query selected from. '
                "It lives ONLY on curated.dim_scheme and "
                "curated.v_cross_scheme_money_district_year. The per-scheme fact tables "
                "and views (curated.v_pmay, curated.v_expenditure, curated.v_employment, "
                "curated.v_focus_plus, curated.v_cm_elevate, curated.fact_pmay_house, "
                "curated.fact_mgnrega_*, curated.fact_focus_plus_disbursement, "
                "curated.fact_cm_elevate_application) are each already a single scheme — "
                "DELETE the scheme filter and any JOIN to curated.dim_scheme entirely, and "
                "keep every other clause (year_key, geography, NOT is_placeholder, "
                "aggregation) exactly as it was.")
    homes = _COL_HOMES.get(col)
    if not homes:
        return (f'The previous query used a column "{col}" that its source object does not '
                "have. Select from a curated object that exposes every column you reference.")
    tail = (" — for a per-district PMAY-G breakdown use curated.v_pmay and GROUP BY lgd_district")
    if col in ("lgd_block", "lgd_village_name"):
        # The usual cause here is a cross-scheme money question at block/village grain
        # pointed at v_cross_scheme_money_district_year, which is district x year only.
        tail = (". For combined MGNREGA + PMAY-G money at block or village grain there is no "
                "cross-scheme view: aggregate curated.v_expenditure and curated.v_pmay to that "
                "grain in separate CTEs (MGNREGA total_exp is LAKH -> /100; PMAY amount_released "
                "is RUPEES -> /1e7, WHERE NOT is_placeholder), then FULL OUTER JOIN the two CTEs "
                "on the grain columns and sum the two crore figures")
    return (f'"{col}" does not exist on the object the previous query selected from. That '
            f"column lives on: {homes}. Rebuild against one of those{tail}.")


# The generator reaches for COUNT(DISTINCT x) OVER (...) on "top N% / decile /
# concentration" questions; Postgres rejects DISTINCT (and nested aggregates)
# inside a window function. A plain error echo doesn't get the model out of the
# pattern — hand it the rank-in-a-CTE recipe explicitly.
_WINDOW_FN_ERR_RE = re.compile(
    r"DISTINCT is not implemented for window functions"
    r"|window function calls cannot contain"
    r"|aggregate function calls cannot contain window function calls",
    re.IGNORECASE,
)


_NEEDLESS_JOIN_ERR_RE = re.compile(
    r'column reference "[\w.]+" is ambiguous|'
    r'directly joins curated\.dim_(?:geography|year|cm_elevate_scheme|pmay_house_status)|'
    r'joins curated\.v_\w+ to curated\.dim_(?:geography|year|cm_elevate_scheme|pmay_house_status)',
    re.IGNORECASE)


def _needless_join_hint(error: str) -> "str | None":
    """Every curated.v_* view already carries the geography and year NAMES, so
    joining curated.dim_geography / curated.dim_year to one is never needed —
    and it is what produced both an "ambiguous column" error and the join
    validator's "no FK connects them" rejection (2026-09-23 KPI sweep:
    "District × Year matrix of MGNREGA households employed")."""
    if not _NEEDLESS_JOIN_ERR_RE.search(error):
        return None
    return (
        "Do NOT join curated.dim_geography or curated.dim_year. Every curated.v_* view "
        "(v_employment, v_expenditure, v_pmay, v_focus_plus, v_focus_legacy, v_cm_elevate) "
        "already has lgd_district, lgd_block, lgd_village_name, village_code and (except "
        "v_cm_elevate) year_key, financial_year and financial_year_short on every row. "
        "v_cm_elevate also already has scheme_name and v_pmay has status_name (never join "
        "curated.dim_cm_elevate_scheme or curated.dim_pmay_house_status to them). Select and "
        "GROUP BY those columns straight from the one view, with no JOIN."
    )


def _window_fn_hint(error: str) -> "str | None":
    if not _WINDOW_FN_ERR_RE.search(error):
        return None
    return (
        "PostgreSQL forbids DISTINCT and nested aggregates inside a window function, so "
        "COUNT(DISTINCT ...) OVER (...) cannot work. Rebuild as: (1) a CTE that aggregates "
        "the metric per unit — SUM(<metric>) AS m ... GROUP BY <unit>; (2) a CTE that ranks "
        "those units — NTILE(<100/percent>) OVER (ORDER BY m DESC) AS bucket (top 10% -> "
        "NTILE(10), quartile -> NTILE(4)); (3) an outer SELECT returning "
        "ROUND(100.0 * SUM(m) FILTER (WHERE bucket = 1) / NULLIF(SUM(m), 0), 1). "
        "Keep every filter (year, scheme, geography) from the failed query on the first CTE."
    )


def _repair_hint(error: str) -> "str | None":
    """The single targeted hint fed to the repair prompt — most specific first."""
    return _missing_column_hint(error) or _needless_join_hint(error) or _window_fn_hint(error)


# curated.v_employment and curated.v_expenditure are at source-row grain (many
# rows per village) — schema_context MGNREGA rule 2: "always SUM ... GROUP BY,
# never read a row raw". The generator sometimes answers an aggregate question
# ("how many job cards", "how much was spent") with a bare
# `SELECT <metric> FROM curated.v_employment WHERE ... LIMIT 1` — it runs clean
# and returns one village's number as if it were the statewide total (the
# "116 job cards for all of Meghalaya" bug). Detect that shape and force a
# repair pass; the hint tells the generator to wrap the metric in SUM(...).
_ROWGRAIN_VIEWS = ("curated.v_employment", "curated.v_expenditure")
_OUTER_SELECT_FROM_RE = re.compile(
    r"^\s*SELECT\b(?P<cols>.*?)\bFROM\b\s+(?P<src>[A-Za-z_][\w.]*)",
    re.IGNORECASE | re.DOTALL,
)
_AGG_CALL_RE = re.compile(r"\b(?:SUM|COUNT|AVG|MIN|MAX)\s*\(", re.IGNORECASE)
_GROUP_BY_RE = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)


def _rowgrain_no_aggregate(question: str, sql: str) -> "str | None":
    """The source-row-grain view a bare-row aggregate query reads from, or None.

    Fires only when the question is aggregate-shaped, the statement is a plain
    (non-CTE) SELECT whose FROM target is one of the source-row-grain views, the
    outer select list has no aggregate call, and there is no GROUP BY."""
    q = question or ""
    if not (_AGGREGATE_CUE.search(q) or _BARE_METRIC_CUE.search(q)):
        return None
    s = sql.strip()
    if re.match(r"^\s*WITH\b", s, re.IGNORECASE):
        return None
    m = _OUTER_SELECT_FROM_RE.match(s)
    if not m:
        return None
    src = m.group("src").lower().strip('"')
    if src not in _ROWGRAIN_VIEWS:
        return None
    if _AGG_CALL_RE.search(m.group("cols")) or _GROUP_BY_RE.search(s):
        return None
    if re.match(r"^\s*SELECT\s+'", s, re.IGNORECASE):  # canned text answer, not a data read
        return None
    return src


_VILLAGE_CODE_FILTER_RE = re.compile(r"\bvillage_code\s*(?:=|IN)\s*", re.IGNORECASE)
_VILLAGE_NAME_FILTER_RE = re.compile(r"\blgd_village_name\s*(?:=|ILIKE|IN)\s*", re.IGNORECASE)


def _village_name_filter_instead_of_code(entity_result: dict, sql: str) -> "int | None":
    """The resolved village_code when the question resolved to one but the
    generated SQL filters on lgd_village_name instead — the exact "Bamil
    Reserve Apal" bug (2026-09-09): entity resolution correctly picked
    village_code, prompt_builder's RESOLVED ENTITIES block told the generator
    to use it verbatim and NOT filter on lgd_village_name, and the generator
    did it anyway, inventing an upper-cased lgd_village_name literal. Storage
    keeps village names in mixed/title case (curated.v_pmay has "Bamil
    Reserve Apal", not "BAMIL RESERVE APAL"), so the literal silently matches
    zero rows and the query runs clean but returns 0. village_code is the
    only column guaranteed to match."""
    code = entity_result.get("resolved", {}).get("village_code")
    if code is None or _VILLAGE_CODE_FILTER_RE.search(sql):
        return None
    return code if _VILLAGE_NAME_FILTER_RE.search(sql) else None


_RESOLVED_FILTER_KEYS = (
    "district", "district_list", "block", "block_list", "village_code", "village_code_list",
    "assembly_constituency", "tranche_label", "batch_label", "house_status",
    "pg_name_pattern", "year_key", "cm_scheme",
)


def _missing_resolved_value(entity_result: dict, sql: str) -> "str | None":
    """Deterministic replacement for the verifier model's "check 2" — every
    resolved entity value must appear somewhere in the SQL text. The small
    verifier model got this wrong both ways in the 2026-09-23 KPI sweep: it
    rejected correct SQL for filters that were NOT resolved entities (a valid
    `sanction_date >= '2020-01-01'`, `batch_label = '12.5K'`, a PG-name ILIKE)
    and for "NOT FOUND" notes, which killed otherwise-correct answers."""
    s = (sql or "").lower()
    resolved = entity_result.get("resolved") or {}
    for key in _RESOLVED_FILTER_KEYS:
        v = resolved.get(key)
        if v in (None, "", []):
            continue
        for item in (v if isinstance(v, list) else [v]):
            if key == "year_key":
                y = int(item)
                if str(y) in s or f"{y}-{(y + 1) % 100:02d}" in s:
                    continue
            elif str(item).lower() in s:
                continue
            return (f"the question resolved {key} = {item!r} but the query never filters on "
                    "it — add that exact value to the WHERE clause and keep every other clause.")
    return None


# Verifier-model verdicts to discard: its checks 1 (prohibited joins) and 2
# (resolved entities) are enforced exactly in code — the post-generation join
# validator and _missing_resolved_value — and the model's versions of them
# were hallucinating violations (a GROUP BY "joining a view to itself", an
# empty entity block "requiring" a filter).
_VERIFIER_CODE_CHECKED = re.compile(
    r"\bcheck\s*[12]\b|resolved\s+entit|prohibited\s+join|joins?\s+.*\bto\s+itself",
    re.IGNORECASE)


async def _verify_sql(question: str, schemes: list[str], entity_result: dict, sql: str) -> "str | None":
    """One short issue sentence if the semantic verifier (SQL_VERIFY_MODEL,
    qwen4-deploy — see app/core/config.py) flags this SQL as not actually
    answering the question, else None.

    This is the catch-all for the class of bug the regex guards above can't
    be: they only recognise SQL shapes a past incident already taught them to
    match. The verifier judges the query against the same schema rules and
    resolved entities the generator itself was given, instead of a fixed
    pattern.

    Best-effort like every other auxiliary check in this module (premise_check,
    followups, context layer): a verifier outage, timeout, or unparseable
    response degrades to "no issue found" rather than blocking an answer the
    pipeline would otherwise have produced successfully."""
    if not settings.SQL_VERIFY_ENABLED:
        return None
    missing = _missing_resolved_value(entity_result, sql)
    if missing:
        request_trace.append("verifier", {"check": "resolved_values", "issue": missing})
        return missing
    frame_issue = understand.frame_sql_issue(understand.sql_frame(), schemes, entity_result, sql)
    if frame_issue:
        request_trace.append("verifier", {"check": "frame", "issue": frame_issue})
        return frame_issue
    try:
        prompt = prompt_builder.build_verify_prompt(question, schemes, entity_result, sql)
        with request_trace.stage("verify_model"):
            raw = await llm.call_sql_verifier(prompt, guided={"guided_json": _SQL_VERIFY_JSON_SCHEMA})
        data = _extract_json(raw)
    except Exception:  # noqa: BLE001
        logger.warning("SQL verifier call failed — continuing without it", exc_info=True)
        return None
    if not data or data.get("ok", True):
        request_trace.append("verifier", {"check": "model", "ok": True})
        return None
    issue = data.get("issue") or "the SQL verifier flagged this query as not answering the question"
    request_trace.append("verifier", {"check": "model", "ok": False, "issue": issue[:300]})
    if _VERIFIER_CODE_CHECKED.search(issue):
        logger.info("SQL verifier issue discarded (enforced in code instead): %s", issue[:200])
        return None
    return issue


async def _execute_one_attempt(sql: str, question: str, schemes: list[str], entity_result: dict,
                               scope: "auth.UserScope | None",
                               retrieved_for_membership_check: list[dict]) -> tuple[str, list[dict]]:
    """One candidate SQL string through every §5.7/5.9/5.11/5.12 guardrail and,
    if all pass, execution + redaction. Raises on any failure — the caller
    (`execute_with_repair`'s loop, or `app.orchestration.pipeline_graph`'s graph nodes)
    decides whether that failure is repairable. Extracted verbatim from
    `execute_with_repair`'s per-attempt try-block (openspec/changes/
    langgraph-full-pipeline-rewrite) so the graph's execution path can reuse
    this exact, already-tested logic instead of duplicating safety-critical
    checks — behavior is unchanged, this is a pure extract-method refactor."""
    # Re-authorize on every attempt, not just the first — a repaired
    # query can touch different tables/columns/scope than the one
    # auth.authorize() originally cleared. Raises rather than falls
    # into the generic except below, so a denial ends the request
    # instead of spending a repair attempt on it.
    if scope is not None and settings.AUTH_ENABLED:
        decision = auth.authorize(scope, schemes=schemes,
                                  resolved_entities=entity_result["resolved"], sql=sql)
        if not decision.allow:
            raise SQLAuthorizationDenied(decision)
    bad_code = _village_name_filter_instead_of_code(entity_result, sql)
    if bad_code is not None:
        raise ValueError(
            f"the question resolved to village_code = {bad_code} but this query filters on "
            "lgd_village_name instead — village name spelling/case is not reliable for "
            "matching (storage keeps mixed/title case, not upper-case), so that filter can "
            "silently match zero rows. Replace the lgd_village_name filter with "
            f"village_code = {bad_code} exactly, and keep every other clause as it was."
        )
    if _STATE_PSEUDO_FILTER.search(sql):
        raise ValueError(
            "generated SQL filters on a non-existent 'Meghalaya' / entity_type='State' "
            "pseudo-row — the whole dataset is already Meghalaya; remove that geographic "
            "filter entirely and keep every other clause"
        )
    bad_view = _rowgrain_no_aggregate(question, sql)
    if bad_view:
        raise ValueError(
            f"this is an aggregate question but the query reads raw rows from {bad_view}, "
            "which is at source-row grain (many rows per village) — a bare "
            "SELECT <metric> ... LIMIT 1 returns ONE arbitrary row, not a total. Wrap the "
            "metric in SUM(...): for a statewide total use "
            "SELECT SUM(<metric>) AS <name> FROM <view> [WHERE year_key = ...] with no "
            "GROUP BY; add GROUP BY <unit> only if the question asks for a per-district / "
            "per-block / per-year breakdown. job_cards_issued_total is a STOCK — pin a "
            "single year_key (the latest if none is named) and SUM across geographies, "
            "never across years. Keep every other clause exactly as it was."
        )
    # §11.4 PII — Layer 1 (app/core/pii_guard.py): the generated SQL text
    # itself references a blocklisted column (bare, aliased, or as a
    # scheme_specific JSONB key), or exposes an entire non-PII-only
    # JSONB container column whole (bare/aliased scheme_specific, or
    # SELECT * on a view that includes it — see find_container_exposure's
    # docstring / openspec/changes/urgent-pii-redaction-followup for why
    # that column can't just be blocklisted outright). Never executed,
    # never repaired — a privacy refusal is not a SQL bug to fix and retry.
    #
    # Deliberately ordered ahead of the join validator and the paid
    # semantic verifier below (moved here 2026-09-12; both used to run
    # first): a PII denial is unconditional and never repaired, so
    # running repairable/paid checks before it risks spending the one
    # available repair attempt — or a paid LLM call — on a query that
    # was always going to be denied for PII regardless of the outcome
    # of those checks. No data-exposure difference either way (nothing
    # executes until every check here passes), purely a cost/latency
    # fix.
    blocked_cols = pii_guard.find_blocked_columns(sql, schemes)
    exposed_container = pii_guard.find_container_exposure(sql, schemes)
    if blocked_cols or exposed_container:
        logger.warning(
            "pii_guard: blocked column(s) %s / exposed container %r in generated SQL "
            "(schemes=%s) — routing to clarification, not repair",
            blocked_cols, exposed_container, schemes)
        raise _pii_not_available_clarification(schemes)
    # Post-generation join validation (PRD §5.11 / follow-up to
    # join_graph.py's pre-generation-only hint — see
    # openspec/changes/join-graph-post-generation-validation). Unlike
    # find_join_path()'s narrow pre-generation gate, this checks the
    # SQL actually written: a JOIN whose own ON clause connects two
    # tables the FK graph knows about but has no relationship between
    # is not a repair candidate for a bug this codebase invented —
    # it's a repairable generation mistake, same tier as the other
    # free structural checks above, not a privacy refusal or a hard
    # denial. sql_join_validator deliberately never flags a CTE-to-CTE
    # join (this codebase's sanctioned cross-scheme aggregate pattern)
    # or a table absent from every curated YAML/live_fks() — see its
    # module docstring.
    invented_joins = sql_join_validator.find_invented_joins(sql)
    if invented_joins:
        a, b = invented_joins[0]
        path_hint = join_graph.find_join_path([a, b])
        if path_hint.status == "ok" and path_hint.joins:
            clauses = "; ".join(f"{j.left} JOIN {j.right} ON {j.on_clause}" for j in path_hint.joins)
            suggestion = (f"There is no direct relationship between them, but a valid route "
                         f"exists: {clauses}.")
        else:
            suggestion = "No relationship between these two tables exists in the FK graph at all."
        raise ValueError(
            f"the query directly joins {a} to {b}, but no foreign-key or curated "
            f"relationship connects them. {suggestion} If these need to be compared "
            "independently, aggregate each to a shared, non-key column (e.g. "
            "village_code) in its own CTE first and join the CTEs — never join the base "
            "tables directly. Keep every other clause that is not implicated."
        )
    # §5.11 "tables must belong to the retrieved set" (baseline-audit
    # finding 11) — distinct from the join-graph rule just above: that
    # one asks "are these two tables related at all", this one asks
    # "was this fact table actually surfaced for this question at
    # all". Scoped to fact tables only (see
    # schema_retrieval.find_tables_outside_retrieved_set's docstring
    # for why dimensions are exempt) and a true no-op whenever
    # retrieval named no fact-table candidate this query — same
    # "additive, never gating for an un-indexed scheme" posture as
    # every other Phase 3 mechanism.
    if settings.RETRIEVED_SET_GUARD_ENABLED:
        stray_tables = schema_retrieval.find_tables_outside_retrieved_set(
            sql, retrieved_for_membership_check)
        if stray_tables:
            retrieved_fact_refs = sorted({
                r["ref"] for r in retrieved_for_membership_check
                if r.get("granularity") == "table" and join_graph.is_fact(r["ref"])
            })
            raise ValueError(
                f"the query references {', '.join(stray_tables)}, which schema "
                f"retrieval did not surface as relevant to this question — the fact "
                f"table(s) actually retrieved for it are: {', '.join(retrieved_fact_refs)}. "
                "Rewrite the query to use one of those instead, unless the question "
                "genuinely requires comparing against a different scheme's fact table."
            )
    # Last — the free regex guards above catch known bug shapes without
    # spending a model call; only a query that clears all of them goes to
    # the semantic verifier, which is the paid check.
    verify_issue = await _verify_sql(question, schemes, entity_result, sql)
    if verify_issue:
        raise ValueError(
            f"semantic verifier flagged this query: {verify_issue}. Fix the SQL to "
            "address that specific problem and keep every other clause (filters, "
            "year_key, geography, aggregation) that is not implicated."
        )
    # Duplicate records (app/sql/dedup.py) — CM Elevate repeats 27 application
    # numbers and PMAY-G 368 identical registrations, so every read of those
    # views is swapped for a de-duplicated one here, after all validators have
    # judged the generator's own SQL. The returned `sql` is the rewritten one,
    # so the UI's "SQL query used" shows the de-duplication.
    sql, _dedup_applied = dedup.dedupe_sql(sql)
    if _dedup_applied:
        logger.info("dedup: counted distinct %s", ", ".join(_dedup_applied))
    request_trace.incr("sql_attempts")
    with request_trace.stage("execute"):
        rows = await run_readonly(sql)
    # §11.4 PII — Layer 2 (app/core/pii_guard.py): unconditional post-execution
    # redaction, independent of Layer 1's text scan, so every downstream
    # consumer of `rows` (the HTTP response, conversation_store.persist_turn,
    # response_cache, semantic_cache — all four read this same object) never
    # sees a blocklisted value even if Layer 1 somehow missed it.
    rows = pii_guard.redact_rows(rows, schemes)
    return sql, rows


async def execute_with_repair(question: str, schemes: list[str], entity_result: dict,
                              initial_sql: str | None = None, *,
                              scope: "auth.UserScope | None" = None,
                              max_repairs: "int | None" = None) -> tuple[str, list[dict]]:
    # settings.SQL_GENERATION_MAX_RETRIES was declared but never read — this
    # was a hard-coded 1 (found 2026-09-23 while tracing KPI-sweep failures).
    if max_repairs is None:
        max_repairs = max(0, int(settings.SQL_GENERATION_MAX_RETRIES))
    sql = initial_sql if initial_sql is not None else await generate_sql(question, schemes, entity_result)
    # §5.11 "tables must belong to the retrieved set" — fetched once, not
    # per-attempt: unlike the SQL-shape checks below, this depends only on
    # (question, schemes), not on the candidate SQL itself, so a repair
    # attempt re-checks against the same retrieved set rather than paying
    # another embedding call for an answer that can't change.
    retrieved_for_membership_check = await schema_retrieval.retrieve(question, schemes)
    for attempt in range(max_repairs + 1):
        sql = _uppercase_geo_literals(sql)
        try:
            return await _execute_one_attempt(
                sql, question, schemes, entity_result, scope, retrieved_for_membership_check)
        except SQLAuthorizationDenied:
            raise  # denial ends the request — never treated as a repairable error
        except ClarificationNeeded:
            raise  # PII refusal ends the request — never treated as a repairable error
        except (UnsafeSQLError, Exception) as e:
            if attempt == max_repairs:
                raise  # repair budget spent — let the caller fall back
            logger.warning("SQL failed (attempt %d/%d), repairing: %s",
                           attempt + 1, max_repairs + 1, e)
            request_trace.incr("repairs")
            request_trace.append("repair_errors", str(e)[:300])
            # The repair prompt carries the same schema + resolved-entities context as
            # the first attempt (not a schema-only stub) — a repair usually fails for
            # want of exactly that context — plus a targeted hint when the error names
            # a missing column.
            repair_prompt = prompt_builder.build_repair_prompt(
                question, schemes, entity_result, failed_sql=sql, error=str(e),
                extra_hint=_repair_hint(str(e)))
            raw = await llm.call_sql_generator(repair_prompt, guided={"guided_regex": _SQL_SHAPE_REGEX})
            sql = _extract_sql(raw)
    return sql, []  # unreachable: the loop always returns rows or re-raises


# ── Numeric faithfulness guard for the composed answer ──────────────────────
# The composer is an LLM and will occasionally transcribe a number wrong
# ("170981" -> "17098"). On a government dashboard that is unacceptable, so the
# composed sentence is checked against the actual result values: any number it
# states that is not in the data (beyond rounding tolerance) triggers one strict
# retry, then a deterministic fallback sentence built straight from the rows.
_NUM_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# "the data doesn't cover / isn't available / can't be broken down" — a hedge the
# composer must not use when the query actually returned a usable non-zero value.
_HEDGE_RE = re.compile(
    r"do(?:es)?n['’]?t\s+cover|does\s+not\s+cover(?:ed)?|not\s+cover(?:ed)?|isn['’]?t\s+covered|"
    r"not\s+available|no\s+data\b|"
    r"(?:doesn['’]?t|does\s+not|don['’]?t|do\s+not)\s+(?:have|include|contain|provide)|"
    r"only\s+provides?\b|can(?:not|['’]?t)\s+(?:be\s+)?(?:broken\s+down|split)|"
    r"no\s+(?:specific\s+)?(?:breakdown|split)\b",
    re.IGNORECASE,
)


def _as_number(v: object) -> "int | float | None":
    """Coerce a result cell to int/float, or None if it isn't numeric. Handles
    decimal.Decimal (asyncpg returns it for SUM/AVG over numeric columns — the
    reason a cross-scheme SUM was being skipped) without relying on
    Decimal.is_integer(), which is Python 3.12+ only."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, numbers.Number):          # float, Decimal, Fraction, …
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
            return int(s) if "." not in s else float(s)
    return None


def _data_numbers(rows: list[dict]) -> set[str]:
    """Every numeric leaf value in the result, as normalised digit strings."""
    out: set[str] = set()
    for row in rows:
        for v in row.values():
            n = _as_number(v)
            if n is None:
                continue
            if isinstance(n, int):
                out.add(str(n))
            else:
                out.add(f"{n:g}")
                out.add(f"{n:.2f}".rstrip("0").rstrip("."))
    return out


def _answer_numbers_faithful(answer: str, data_nums: set[str]) -> bool:
    """True if every 'reported' number in the answer traces back to a data value.
    Years and small integers (< 100, no decimal) are treated as prose, not data."""
    data_floats: list[float] = []
    for d in data_nums:
        try:
            data_floats.append(float(d))
        except ValueError:
            pass
    for tok in _NUM_TOKEN.findall(answer):
        raw = tok.replace(",", "")
        # A year or a financial-year range fragment — "2020", "2020-2021",
        # "2020-21" — is prose, not a measured quantity. The number tokenizer
        # splits "2020-2021" into "2020" and "-2021" (the hyphen read as a
        # sign), so the second-half forms "-YYYY" / "-YY" are matched here too.
        if re.fullmatch(r"-?(19|20|21)\d\d|-\d{2}", raw):
            continue
        try:
            fval = float(raw)
        except ValueError:
            continue
        if abs(fval) < 100 and "." not in raw:         # ordinal / "one or two"
            continue
        if raw in data_nums:
            continue
        if any(dv == fval or (dv and abs(dv - fval) / abs(dv) <= 0.005)
               or abs(dv - fval) < 0.5 for dv in data_floats):
            continue
        return False
    return True


def _row_metrics(row: dict) -> list[tuple[str, "int | float"]]:
    """(column, numeric value) for every numeric cell in the row — Decimal included."""
    out: list[tuple[str, "int | float"]] = []
    for k, v in row.items():
        n = _as_number(v)
        if n is not None:
            out.append((k, n))
    return out


def _fmt_num(v: "int | float") -> str:
    return f"{v:,}" if isinstance(v, int) else f"{v:,.2f}"


def _answer_covers_metrics(answer: str, row: dict) -> bool:
    """Every numeric metric in a single aggregate row must appear in the answer —
    catches a cross-scheme result where the composer names only one side."""
    ans = answer.replace(",", "")
    for _k, v in _row_metrics(row):
        forms = {str(v)}
        if isinstance(v, float):
            forms.add(f"{v:.2f}".rstrip("0").rstrip("."))
        if not any(f in ans for f in forms):
            return False
    return True


def _result_digest(rows: list[dict], max_values: int = 40) -> "tuple[str, set[str]]":
    """A deterministic whole-result summary, computed from EVERY row (not just the
    preview the composer is shown): the distinct coverage of each dimension
    column, and sum / mean / max / min of each numeric column together with which
    dimension row holds the max and the min.

    Returns (indented_text_block, allowed_number_strings). The strings are unioned
    into the numeric-faithfulness whitelist so a total or average the composer
    copies out of this block is not flagged as an invented number. Without this,
    any multi-row result (a district x year matrix, a per-block list) could only
    be described one visible cell at a time — never "the total is X" or "Y is
    highest" — because those figures are not present in the raw rows.

    The actual per-column computation lives in app.response.findings.compute_result_stats
    (a typed, structured version of what used to be computed inline here) so the
    new findings module and this text formatting read the exact same numbers,
    computed by the same code — this function is now just that computation's
    text rendering, unchanged from its pre-refactor output."""
    stats = findings.compute_result_stats(rows)
    if stats is None:
        return "", set()

    def _label(row: dict) -> str:
        parts = [str(row[k]) for k in stats.dimensions if row.get(k) is not None]
        return " / ".join(parts) if parts else "(row)"

    lines: list[str] = [f"total rows: {stats.total_rows}"]
    allowed: set[str] = set()

    for k, vals in stats.dimensions.items():
        shown = ", ".join(vals) if len(vals) <= max_values else f"{len(vals)} distinct values"
        lines.append(f"{k} ({len(vals)}): {shown}")

    for k, ns in stats.numeric.items():
        for val in (ns.total, ns.max, ns.min, ns.mean):
            f = float(val)
            allowed.add(str(int(f)) if f.is_integer() else f"{f:g}")
            allowed.add(f"{f:.2f}".rstrip("0").rstrip("."))
        lines.append(
            f"{k}: sum={_fmt_num(ns.total)}; mean={_fmt_num(round(ns.mean, 2))}; "
            f"max={_fmt_num(ns.max)} at [{_label(ns.max_row)}]; min={_fmt_num(ns.min)} at [{_label(ns.min_row)}]"
        )

    return "\n".join(f"  - {ln}" for ln in lines), allowed


def _deterministic_answer(rows: list[dict]) -> str:
    """A plain, exact sentence from the rows — used only when the LLM composer
    keeps misquoting or dropping numbers."""
    if len(rows) == 1:
        nums = _row_metrics(rows[0])
        if len(nums) == 1:
            k, v = nums[0]
            return f"**{answer_format.cell(k, v)}** {answer_format.header(k).lower()}."
        if len(nums) >= 2:
            # Every value is shown in the record card under the answer — name
            # them here too, formatted, so the sentence stands on its own.
            return "; ".join(f"{answer_format.header(k)}: **{answer_format.cell(k, v)}**"
                             for k, v in nums) + "."
    # Multi-row: the UI renders every row in the table under the chart.
    return f"The breakdown ({len(rows)} rows) is shown below."


def _no_data_answer(schemes: list[str] | None, entities: dict[str, str] | None) -> str:
    """Plain 'nothing matched' message for a query that returned no rows at all.
    Built deterministically rather than left to the composer — on an empty
    result it sometimes free-forms RAG-style refusal wording ("the reference
    material does not contain...") that reads like an internal document search
    failed, when the honest answer is just that no records match the filters."""
    scope_bits = [v for v in (entities or {}).values() if v]
    scope = f" for {', '.join(scope_bits)}" if scope_bits else ""
    msg = f"I couldn't find any matching records{scope} in the data available."
    metrics = available_metrics_text(schemes or [])
    if metrics:
        msg += "\n\nData I do have here:\n" + metrics
    return msg


def _is_plain_list_result(rows: list[dict]) -> bool:
    """A multi-row result whose rows carry no numeric metric — a pure list of
    dimension values (e.g. the districts that satisfy a coverage filter). Those
    rows ARE the answer; a 'not covered / can't tell' hedge over them is wrong."""
    return len(rows) >= 2 and not any(_row_metrics(r) for r in rows)


def _deterministic_list_answer(rows: list[dict]) -> str:
    """Plain sentence naming every value in a single-column list result — used
    when the composer hedges over a membership answer whose rows already are the
    answer set."""
    cols = list(rows[0].keys())
    if len(cols) == 1:
        vals = [str(r[cols[0]]) for r in rows if r.get(cols[0]) is not None]
        label = cols[0].replace("_", " ")
        if len(vals) <= 40:
            return f"{len(vals)} {label} values match: " + ", ".join(vals) + "."
        return (f"{len(vals)} {label} values match, including: "
                + ", ".join(vals[:40]) + ", …")
    return _deterministic_answer(rows)


_DIM_LABEL = {
    "district": "district",
    "block": "block (C&RD block)",
    "village": "village",
    "year": "financial year",
    "house_status": "house construction stage",
}


def _entity_names_block(entities: dict[str, str] | None) -> str:
    """A context block naming the canonical form of every place / year / category
    the query actually filtered on, so the composer uses the full proper name in
    its answer instead of echoing the user's abbreviation, code or misspelling
    ("wgh" -> "West Garo Hills", "fy24" -> "FY 2024-25")."""
    if not entities:
        return ""
    lines = [f"  - {_DIM_LABEL.get(k, k)}: {v}" for k, v in entities.items() if v]
    if not lines:
        return ""
    return (
        "\nEntity names — the query filtered on exactly these values. In your "
        "answer, refer to each place, year or category by the full name given "
        "here, even when the question used a short form, code or misspelling; "
        "never echo the user's shorthand back as the name.\n" + "\n".join(lines) + "\n"
    )


async def compose_response(question: str, sql: str, rows: list[dict],
                           notes: list[str] | None = None,
                           entities: dict[str, str] | None = None,
                           schemes: list[str] | None = None,
                           result_findings: list[dict] | None = None) -> str:
    """`result_findings` (node 5.13, openspec/changes/multi-tenant-rls-scheme-scaleout
    task under 5.15): deterministic findings over the FULL result — extremes,
    ties, stale data, large-result-set, threshold breaches — each already
    carrying a ready-to-read `message` built from the same `rows` this
    function itself answers from (see app/response/findings.py). Kept in its OWN
    block with its OWN instruction (below), deliberately not merged into
    `notes` — `notes` is framed as "premises to correct," which a finding
    like "district X has the highest value" isn't; conflating the two
    would mislabel findings text under a correction instruction it doesn't
    fit, and risk every finding getting force-quoted into a 1-3-sentence
    answer meant to describe the result, not enumerate every observation
    about it. See this function's own findings_block below for the actual
    "mention at most one, only if relevant" instruction that keeps this
    additive without turning the answer into a findings dump."""
    if not rows:
        return _no_data_answer(schemes, entities)
    preview = rows[:40]
    truncated = len(rows) > len(preview)
    # "No usable value" — every numeric cell is 0 or null (rows is non-empty
    # here; a truly empty result returns via _no_data_answer above). This is
    # the shape a metric the data simply doesn't track comes back as; when we
    # see it, hand the composer the real metric list so it can tell the user
    # exactly what IS available rather than a vague "not covered".
    _nums = [n for r in rows for _k, n in _row_metrics(r)]
    no_usable_value = bool(_nums) and all(n in (0, None) for n in _nums)
    metrics_block = ""
    if no_usable_value:
        metrics_block = (
            "\nMetrics the data DOES carry — if the question asked for something "
            "that is not in this list, say plainly it isn't tracked in the "
            "available scheme data, then name what is:\n"
            + available_metrics_text(schemes or []) + "\n"
        )
    # A metric the schema simply doesn't carry comes back as no rows, or as a
    # single 0 / NULL. Tell the composer to say that plainly instead of
    # reporting a confident "0" the user will read as a real measurement.
    guidance = (
        "If the result contains a number that answers the question, state it "
        "plainly as the answer — a nonzero COUNT is exactly the count that was "
        "asked for; never reply that the data 'doesn't cover' a metric the query "
        "just counted. ONLY when the result is empty, or the value is 0 or null, "
        "do NOT assert a real count of zero — instead say the data available "
        "doesn't cover that metric for the scheme/area asked, and name what IS "
        "available if you can tell from the query. Never describe a column the "
        "query didn't select. Copy every number digit-for-digit from the result "
        "JSON or the whole-result summary — do not shorten, round or reformat it "
        "(adding thousands separators is fine). If a Context note below says the "
        "question assumed a figure the data contradicts, correct that figure in "
        "your first sentence and answer from the real value — never echo the "
        "user's assumed number as if it were right. Make that first sentence ONE "
        "clean clause naming the real figure (e.g. 'Tranche 1 shows 0 beneficiaries, "
        "not the 4 the question assumes.') — never a reasoning trail like 'contradicting "
        "the assumed figure of X, so Y cannot be calculated because Z is empty'. Put "
        "the supporting figures in a separate, plainly listed second sentence (e.g. "
        "'Tranches 2, 3 and 4 each had 93,286 beneficiaries, out of 373,144 total.') "
        "rather than chaining them onto the correction with 'The available figures "
        "are...'. If the result is a list of "
        "names or rows and carries no numeric column, that list IS the answer — "
        "it is the exact set the query already selected as matching the question "
        "(e.g. 'which districts have both schemes'). Name those values as the "
        "answer; never say the data 'only lists names' or lacks the detail to "
        "decide — the filtering happened in the query. Never state or imply a "
        "scope the query wasn't actually filtered to — a specific tranche, year, "
        "district, block, village or category — unless it appears in the Entity "
        "names block below or literally in the question; if the question and the "
        "Entity names block name no tranche/year/area, the result covers all of "
        "them and must be described that way (e.g. 'across all tranches'), not "
        "attributed to one you're not told about."
    )
    # For any multi-row result, hand the composer a deterministic summary built
    # from EVERY row — totals, mean, extremes, full dimension coverage — so its
    # answer matches the charts/table instead of describing only the ~40 rows it
    # can see. Also stops it declaring that rows it can't see "have no data".
    digest_text, digest_nums = _result_digest(rows)
    summary_block = ""
    if digest_text:
        warn = ""
        if truncated:
            warn = (
                f" Only the first {len(preview)} of {len(rows)} rows appear below; "
                "do NOT say any district, block, village, year or category is "
                "missing or has no data merely because it is absent from them."
            )
        summary_block = (
            "\nWhole-result summary — computed from EVERY row. Use THESE figures "
            "for any total, average, highest/lowest or coverage statement; they "
            "are authoritative even though only some rows are shown below." + warn
            + "\n" + digest_text + "\n"
        )
    notes_block = ""
    if notes:
        notes_block = "\nContext (question premises to reconcile against the data — " \
                      "correct any the result contradicts):\n" + \
                      "\n".join(f"  - {n}" for n in notes) + "\n"
    # node 5.13 findings, node 5.15's own input per the GT proposal — a
    # SEPARATE block from notes_block above, deliberately: these are
    # observations about the result, not premises to correct, and the
    # instruction below caps it at "at most one, only if it fits" so a
    # result with several findings (e.g. one extreme per numeric column)
    # doesn't turn a 1-3-sentence answer into a findings enumeration.
    findings_block = ""
    _finding_msgs = [f["message"] for f in (result_findings or []) if f.get("message")]
    if _finding_msgs:
        findings_block = (
            "\nAdditional observations about this result (weave in AT MOST ONE, "
            "only if it genuinely adds something beyond what the question asked "
            "— never force one in, never list more than one):\n" +
            "\n".join(f"  - {m}" for m in _finding_msgs) + "\n"
        )
    names_block = _entity_names_block(entities)
    # A formatted bullet list of the rows is appended under the answer
    # by answer_format.present() — so for a multi-row result the composer must
    # SUMMARISE, not enumerate every row inline (the run-on answers the user
    # reported 2026-09-23).
    layout = (
        "A chart and a table of every row are shown directly below your text, so do NOT "
        "list the rows one by one. In at most two sentences give the overall picture: "
        "the total or the leader, and one notable point (e.g. the gap to the next, or a "
        "concentration)." if len(rows) >= 2 else
        "Give the figure in one or two sentences.")
    prompt = f"""Answer the user's question using ONLY the numbers in the result and the
whole-result summary below — do not invent or round differently than shown.
Write for a senior government officer, in a formal, professional briefing style:
  - The first sentence IS the answer: lead with the figure itself, and put the key
    figure(s) in **bold** (Markdown). Never open with "The data shows..." or a
    description of what the query returned.
  - Write place and scheme names in normal Title Case (West Garo Hills, Ri Bhoi —
    never WEST GARO HILLS), and use plain words, never raw column names (say
    "payments", not "payments_count" or "amount raw").
  - Short, declarative sentences — one idea each, no chains of clauses.
  - Plain prose only: no tables, no bullet lists, no headings — the formatted
    breakdown is added under your text automatically.
  - {layout}
{guidance}
{metrics_block}{names_block}{summary_block}{notes_block}{findings_block}
Question: "{question}"
Result ({len(rows)} row(s), showing up to {len(preview)}):
{json.dumps(preview, default=str)}

Answer:"""
    # Live streaming (app/response/answer_stream.py): with an on_event sink
    # bound, this FIRST call streams as "token" events; every check below
    # still runs on the complete text, and the strict retry stays
    # non-streaming. No sink: exactly llm.call_response_composer(prompt).
    on_event = answer_stream.current()
    answer = await answer_stream.compose(prompt, on_event)

    data_nums = _data_numbers(preview) | digest_nums
    # A note may ask the composer to name the figure the question wrongly assumed
    # ("not the 1.71 L assumed…") — allow those premise numbers through the
    # faithfulness check so the correction itself isn't flagged as a misquote.
    if notes:
        for _p in premise_check.extract_premises(question):
            data_nums.add(f"{_p.value:g}")
            data_nums.add(re.sub(r"[^\d.]", "", _p.text) or f"{_p.value:g}")
    # Same reasoning, for findings_block above: a finding can legitimately cite
    # a number that isn't itself a data CELL value — "This result has 847 rows"
    # (large_result_set) or a configured threshold ("crossed 50000") — both
    # deterministically generated (app/response/findings.py), never LLM output, so
    # trusting them here can't reintroduce the hallucination risk this guard
    # exists to catch. Without this, the guard would flag the composer's own
    # correctly-woven-in finding as an untraceable number and fire the
    # deterministic fallback below, discarding a good answer.
    for _m in _finding_msgs:
        for _tok in _NUM_TOKEN.findall(_m):
            data_nums.add(_tok.replace(",", ""))
    misquoted = bool(data_nums) and not _answer_numbers_faithful(answer, data_nums)
    # A single aggregate row with 2+ metrics (e.g. a cross-scheme MGNREGA + PMAY
    # count) — the answer must report every one, not just the first scheme.
    dropped_metric = (len(preview) == 1 and len(_row_metrics(preview[0])) >= 2
                      and not _answer_covers_metrics(answer, preview[0]))

    if misquoted or dropped_metric:
        why = "MISQUOTED a number" if misquoted else "left out one of the result values"
        logger.warning("compose_response: answer %s (%r) — strict retry", why, answer[:160])
        if len(preview) == 1:
            allowed = "; ".join(f"{k} = {v}" for k, v in preview[0].items())
        else:
            allowed = ", ".join(sorted(data_nums, key=len, reverse=True))
        strict_prompt = (
            prompt + "\n" + answer.strip() +
            f"\n\nThat answer {why}. State EVERY value in the result, each labelled with what "
            "it measures, digit-for-digit (thousands separators allowed). The values are:\n  "
            + allowed + "\nRewrite the answer now.\n\nAnswer:"
        )
        answer = await llm.call_response_composer(strict_prompt)
        still_bad = (bool(data_nums) and not _answer_numbers_faithful(answer, data_nums)) or (
            len(preview) == 1 and len(_row_metrics(preview[0])) >= 2
            and not _answer_covers_metrics(answer, preview[0]))
        if still_bad:
            logger.warning("compose_response: retry still wrong — using deterministic answer")
            answer = _deterministic_answer(preview)
            request_trace.note("fallback", "number_check")

    # Deterministic safety net for the opposite failure: the query DID return a
    # real, non-zero number, but the composer hedged with a "not covered / no
    # data / can't break it down" phrasing anyway (seen when the question names
    # two categories joined by "or" and the query returns their combined COUNT).
    # A usable number must be reported as the answer.
    if _HEDGE_RE.search(answer):
        metrics_now = _row_metrics(preview[0]) if len(preview) == 1 else []
        if metrics_now and all(v not in (0, None) for _k, v in metrics_now):
            logger.warning("compose_response: hedged over a real value %r — deterministic answer",
                           answer[:160])
            answer = _deterministic_answer(preview)
        elif _is_plain_list_result(rows):
            logger.warning("compose_response: hedged over a %d-row list result %r — "
                           "deterministic list answer", len(rows), answer[:160])
            answer = _deterministic_list_answer(rows)
    final_answer = _present_answer(answer, rows, sql)
    # Whatever the checks/formatting changed since the stream, the client
    # must end on exactly this text.
    await answer_stream.settle(on_event, final_answer)
    return final_answer


def _present_answer(answer: str, rows: list[dict], sql: str = "") -> str:
    """Professional Markdown layout for every data answer (app/response/answer_format.py):
    the summary, then a table (multi-row) or labelled bullets (one row, several
    metrics), then a one-line note when duplicate records were counted once
    (app/sql/dedup.py). Best-effort — any formatting failure returns the answer as-is."""
    try:
        if not answer_format._places:
            for _s in SCHEME_CATALOG:
                answer_format.register_places(canonical_names(_s, "district"))
                answer_format.register_places(canonical_names(_s, "block"))
        out = answer_format.present(answer, rows)
        applied = [label for view, (_k, _t, label) in dedup.DEDUP_VIEWS.items()
                   if f"FROM {view} ORDER BY" in (sql or "")]
        note = dedup.note_for(applied)
        return f"{out}\n\n{note}" if note else out
    except Exception:  # noqa: BLE001 — presentation must never cost the answer
        logger.warning("answer formatting failed — returning plain answer", exc_info=True)
        return answer


_DATA_SHAPE_CUE = re.compile(
    r"\b(?:gender|district|block|scheme|status|tranche|year)[\s-]*(?:wise\s+)?split\b|"
    r"\bsplit\s+by\b|\bbreakdown\b|\bdistribution\b|\bcross[\s-]?tab\b|\bmatrix\b|"
    r"\b(?:approval|verification|application|file|payment)\s+status\b|"
    r"\bworkflow\b|\bpipeline\b|\bcurrent[_\s]level\b|\bsitting\b",
    re.IGNORECASE)


async def classify_intent(question: str) -> str:
    """DATA (a number from megh_db) vs KNOWLEDGE (how the scheme works, from the
    reference docs). Keyword fast-path first; one classifier call otherwise."""
    # "what are common districts in both schemes?" opens with "what are", which
    # otherwise reads as KNOWLEDGE — but it is a list computed from the coverage
    # data, never something in the reference docs. Force DATA before the keyword
    # fast-path so the "what are" knowledge cue can't win.
    if _CROSS_SCHEME_SET_QUESTION.search(question):
        return "DATA"
    # "What is the gender split / approval status of ...", "where are
    # applications sitting in the workflow" — a result shape or record state
    # can only come from the data, even behind a "what is" opener.
    if _DATA_SHAPE_CUE.search(question):
        return "DATA"
    if _DATA_HINTS.search(question) and not _KNOWLEDGE_HINTS.search(question):
        return "DATA"
    if _KNOWLEDGE_HINTS.search(question) and not _DATA_HINTS.search(question):
        return "KNOWLEDGE"
    prompt = f"""Classify the question into exactly one label:
  DATA      - needs a number/count/list computed from the scheme database. This
              INCLUDES comparison and correlation questions ("do districts with
              high X also have high Y", "is A related to B by district", "which
              districts lead on both schemes") — answered by querying the figures
              and comparing them, NOT from the reference docs.
  KNOWLEDGE - asks how a scheme works: eligibility, documents, components, rules, history

Return ONLY JSON: {{"intent": "DATA"|"KNOWLEDGE"}}

Question: "{question}"
JSON:"""
    raw = await llm.call_classifier(prompt, guided={"guided_json": _INTENT_JSON_SCHEMA})
    payload = _extract_json(raw)
    if payload and payload.get("intent") in ("DATA", "KNOWLEDGE"):
        return payload["intent"]
    logger.warning("classify_intent: unusable response %r — defaulting to DATA", raw[:120])
    return "DATA"


def _empty_data_fields() -> dict:
    # `data` / `sql_query` are the keys the frontend renderer reads; keep them
    # present (empty) on every route so the UI never sees `undefined`.
    return {"schemes": [], "resolved_entities": {}, "sql": None, "sql_query": None,
            "row_count": 0, "rows": [], "data": []}


def _denied(decision: "auth.AuthDecision", schemes: list[str], resolved: dict) -> dict:
    return {
        "route": "denied", "intent": "DATA", "confidence": "high",
        "answer": decision.reason, "denied": True, "denied_by": decision.check,
        **{**_empty_data_fields(), "schemes": schemes, "resolved_entities": resolved},
    }


def _out_of_scope_result(question: str, raw_question: str) -> dict:
    """Standard 'I'm Megh One AI …' reply for an OutOfScope raised mid-pipeline —
    shaped like the edge returns in _run_pipeline so the frontend renders it the
    same way as an off-topic hit caught up front."""
    hit = edge.out_of_scope()
    return {
        "route": "edge", "intent": "EDGE", "confidence": "high",
        "answer": hit["response"], "edge_type": hit["type"],
        "suggestions": hit.get("suggestions", []),
        "rewritten_question": question if question != raw_question else None,
        **_empty_data_fields(),
    }


async def _answer_data(question: str, scope: "auth.UserScope | None" = None,
                       skip_scope_clarify: bool = False,
                       prior_resolved: "dict | None" = None,
                       village_hint: "str | None" = None,
                       is_followup: bool = False) -> dict:
    # Named a scheme we don't hold ("CM Elevate", "PM-KISAN", …) — say so plainly
    # instead of the generic "which scheme?" prompt, then offer the three we have.
    _unsupported = _unsupported_scheme_named(question)
    if _unsupported:
        raise _unsupported_scheme_clarification(question, _unsupported)

    # Ask which scheme before doing anything expensive, when the question could
    # honestly mean either one. Guessing here is worse than a one-tap follow-up.
    # Then the metric / "top how many?" before spending model calls
    # (app/nlu/clarify_rules.py rules 1-2, on this turn's QueryFrame).
    question, _pre_assumptions, _pre_trace = clarify_rules.gates_before_resolution(question)

    schemes, _scope_meta = await understand.schemes_for_answer(
        clarify_rules.gate_frame(question), question)
    # node 5.2 scope-decision trace — descriptive only, never read by any
    # decision below. Attached to the response in the final return dict.
    scope_trace = {
        "schemes": schemes,
        "confidence": _scope_meta.confidence,
        "source": _scope_meta.source,
        "reason": _scope_meta.reason,
        "is_followup": is_followup,
        "in_scope": True,
    }
    # raises ClarificationNeeded if ambiguous
    entity_result = await understand.resolve_for_answer(
        clarify_rules.gate_frame(question), question, schemes,
        prior_resolved=prior_resolved, village_hint=village_hint)

    # node 5.3 generic clarification gate — "the source cannot answer this at
    # all" (Phase 1 scope only, see app/nlu/clarification_engine.py). Checked
    # ahead of the region/scope/year/tranche asks below, matching every
    # classification-rules.yaml file's own stated ordering intent: requests
    # the source cannot answer are caught before missing detail is asked
    # for, so the bot never collects a district/year for a question it can
    # never answer regardless.
    if settings.CLARIFICATION_ENGINE_ENABLED:
        _engine_clar = _engine_clarification(question, schemes, entity_result["resolved"])
        if _engine_clar is not None:
            raise _engine_clar

    # "Garo Hills" / "Khasi Hills" name a hill RANGE, not a district. When one is
    # named and no specific district resolved, either offer its districts as one-tap
    # chips ("which Garo Hills district?") or, if the question already says "all of
    # Garo Hills" or asks for a per-district breakdown, expand it to every district in
    # the range and carry that forward for SQL generation.
    if not entity_result["resolved"].get("district") and not entity_result["resolved"].get("district_list"):
        _scheme0 = schemes[0] if schemes else ""
        region = detect_region(question, _scheme0)
        if region:
            _want_all = region["expand"] or bool(_HAS_BREAKDOWN.search(question))
            if not _want_all and not skip_scope_clarify:
                raise _region_clarification(question, region)
            entity_result["resolved"]["district_list"] = [d.upper() for d in region["districts"]]
            entity_result["resolved"]["district_list_region"] = region["canonical"]
            entity_result["display"]["district"] = region["canonical"]

    # Area, then (with geography settled) financial year, then (Focus Plus
    # only) tranche — clarify_rules rules 3-5, which apply the scheme's
    # disclosed default where its rules file has one and ask otherwise.
    # skip_scope_clarify: a checkpointer resume of that very pause (a reply
    # that still names no area must not loop back here); `already_all_combined`
    # lets a session that already chose "all tranches combined" skip a re-ask.
    question = clarify_rules.gates_after_resolution(
        question, schemes, entity_result, skip_scope_clarify=skip_scope_clarify,
        prior_resolved=prior_resolved, pre_assumptions=_pre_assumptions, pre_trace=_pre_trace)

    # node 5.2 query analyzer — additive; runs only once every clarification
    # gate above has passed, so it never fires on a question that's about to
    # pause anyway. Isolated the same way findings/chart_spec are: a failure
    # here must not affect the answer, only whether `analysis` is populated.
    analysis = None
    if settings.QUERY_ANALYZER_ENABLED:
        try:
            analysis = await query_analyzer.analyze_query(question, schemes, entity_result)
        except Exception:  # noqa: BLE001
            logger.warning("query analyzer failed — continuing without it", exc_info=True)

    with request_trace.stage("sql_generation"):
        sql = await generate_sql(question, schemes, entity_result)

    # Authorization — role/scope vs. what the query actually asks for. Checked
    # inside execute_with_repair on every attempt (including this first one),
    # so granularity (GROUP BY) and geography literals are re-evaluated against
    # whichever SQL is actually about to execute, including a repaired query
    # that changed tables/columns/scope after a validation failure.
    try:
        sql, rows = await execute_with_repair(question, schemes, entity_result,
                                              initial_sql=sql, scope=scope)
    except SQLAuthorizationDenied as e:
        logger.info("auth deny (%s) user=%s: %s", e.decision.check,
                    scope.user_id if scope else None, e.decision.reason)
        return _denied(e.decision, schemes, entity_result["resolved"])

    # A named producer group that matched nothing — offer the closest real names.
    if not rows and entity_result["resolved"].get("pg_name_pattern"):
        _pg_clar = await _pg_not_found_clarification(question, entity_result)
        if _pg_clar is not None:
            raise _pg_clar

    # A number the question states as already-true ("the 1.71 L sanctioned
    # houses") is never part of the SQL — check it against the result so the
    # composer corrects a false premise instead of repeating it as fact.
    notes = list(entity_result.get("notes") or [])
    if settings.PREMISE_CHECK_ENABLED:
        try:
            notes.extend(premise_check.check_premises(question, rows))
        except Exception:  # noqa: BLE001
            logger.warning("premise check failed — continuing without it", exc_info=True)

    # Silent, disclosed defaults for a detail the question left unspecified —
    # only for conditions that aren't already a clarify_rules rule above
    # (defaults_engine's collision set enforces that itself). Runs after premise_check into the same `notes` channel,
    # ahead of compose_response, so the composer surfaces it identically to
    # an existing premise correction.
    if settings.DEFAULTS_ENGINE_ENABLED:
        try:
            notes.extend(defaults_engine.apply_defaults(question, schemes, entity_result["resolved"]))
        except Exception:  # noqa: BLE001
            logger.warning("defaults engine failed — continuing without it", exc_info=True)

    # openspec/changes/query-analyzer-predicate-integration: the analyzer's
    # own flagged non-entity ambiguity (unclear metric / comparison basis) —
    # a DISCLOSED NOTE, not a clarification pause. An LLM-judged ambiguity has
    # no production validation yet, and this codebase's own established bias
    # (see app/nlu/clarification_engine.py's module docstring) is to under-fire
    # rather than interrupt on an unproven signal — so this surfaces the
    # gap without stopping the answer. `origin == "entity_note"` entries are
    # excluded: those already came from entity_result["notes"] above and
    # would otherwise be disclosed twice.
    if analysis:
        for _amb in analysis.get("ambiguous") or []:
            if _amb.get("origin") == "llm" and _amb.get("term"):
                notes.append(
                    f"'{_amb['term']}' may be ambiguous — "
                    f"{_amb.get('why') or 'consider stating it more specifically'}.")

    # Structured, deterministic findings over the full result (node 5.13) —
    # additive; never omitted, empty list when nothing fires. Computed BEFORE
    # compose_response (moved 2026-09-18, was after — see the 2026-09-11
    # comment this replaces) so the composer can weave a finding's own text
    # into its prose via the same `notes` channel premise_check/defaults_engine
    # already use, per Grant Thornton §5.15's spec that the composer take
    # findings as an input, not just attach them as a sibling field.
    # **Deliberate trade-off, accepted explicitly, not a silent regression**:
    # this removes the isolation the prior ordering guaranteed (a findings
    # failure could never affect the answer text, only whether the separate
    # `findings` field was populated). Each detector still runs inside its
    # own try/except in findings.evaluate() itself, so a single detector
    # raising still can't take down the others or this call — but a
    # detector that runs successfully and produces an odd/wrong message can
    # now reach the answer, which it could not before. Findings' `message`
    # text is built directly from `stats` computed over these same `rows`
    # (see findings.py's `_finding` callers), so it carries the same
    # verified-real-numbers property compose_response's own numeric-
    # faithfulness guard already checks the composed answer against.
    result_findings: list[dict] = []
    if settings.FINDINGS_ENABLED:
        try:
            result_findings = findings.evaluate(question, schemes, rows, entity_result["resolved"])
        except Exception:  # noqa: BLE001
            logger.warning("findings evaluation failed — continuing without it", exc_info=True)

    with request_trace.stage("compose"):
        answer = await compose_response(question, sql, rows, notes=notes,
                                        entities=entity_result.get("display"),
                                        schemes=schemes, result_findings=result_findings)

    # Chart-type selection (node 5.14) — additive; never omitted, `None`
    # when nothing fires. Computed over the same rows[:200] slice the
    # `data` field below carries, so the row-count-based gates here (the
    # 1-row kpi_bar check, the <=6-row doughnut check) always agree with
    # what web/ai_query.html's buildAnalytics() actually sees when it
    # reads response["data"], not a count from a differently-truncated
    # view. Isolated the same way findings is: a selection failure must
    # not affect the answer, only whether this extra field is populated.
    result_chart_type: "str | None" = None
    if settings.CHART_SPEC_ENABLED:
        try:
            result_chart_type = chart_spec.select_chart_type(rows[:200], question)
        except Exception:  # noqa: BLE001
            logger.warning("chart_spec selection failed — continuing without it", exc_info=True)

    return {
        "route": "data",
        "intent": "DATA",
        "confidence": "high" if rows else "low",
        "schemes": schemes,
        "scope": scope_trace,
        "resolved_entities": entity_result["resolved"],
        "sql": sql,
        "sql_query": sql,
        "row_count": len(rows),
        "rows": rows[:20],
        "data": rows[:200],
        "answer": answer,
        "findings": result_findings,
        "chart_type": result_chart_type,
        "analysis": analysis,
        "assumptions": entity_result.get("assumptions") or [],
        "gate_trace": entity_result.get("gate_trace") or [],
    }


# ── "What is EKH?" — spell out a district / block name or abbreviation ──────
# A bare "what is <term>", "<term> full form", "what does <term> stand for"
# where <term> is one of Meghalaya's 12 districts or its ~56 C&RD blocks. The
# KB has no glossary for these, and the edge whitelist bounces a lone "ekh" as
# off-topic — so both routes fail the user. Answer it straight from the
# entity-resolver catalogue instead. A question that also wants a figure
# ("person-days in EKH") carries a data cue and is left for the DATA path.
_DEFN_CUE_RE = re.compile(
    r"\b(what(?:'?s| is| are| was| does| do)?|whats|what do you (?:mean by|call)|"
    r"full[\s-]?form|full name|long form|short form|expand(?:ed)?|expansion|"
    r"meaning|abbreviat\w*|acronym|stands? for|stand for|define|definition)\b",
    re.IGNORECASE,
)
_DEFN_STRIP_RE = re.compile(
    r"\b(what(?:'?s| is| are| was| does| do)?|whats|what do you (?:mean by|call)|"
    r"the full form of|full[\s-]?form of|full name of|full form for|long form of|"
    r"short form of|full[\s-]?form|full name|long form|short form|"
    r"the meaning of|meaning of|abbreviat\w* of|abbreviat\w* for|"
    r"acronym for|acronym of|expansion of|expanded|expand|"
    r"definition of|define|tell me|please|does|do|stands? for|stand for|"
    r"means?|in full|name of|the name of|"
    r"districts?|distt|dist|blocks?|c&rd|cd|"
    r"in meghalaya|of meghalaya|meghalaya)\b",
    re.IGNORECASE,
)


def _format_geo_definition(hit: dict) -> str:
    name = hit["display"]
    acronym = str(hit.get("acronym") or "").strip()
    if hit["type"] == "district":
        lead = (f"“{acronym}” is short for {name}"
                if acronym and hit.get("used_abbrev") else name)
        hq = hit.get("hq")
        seat = f" (headquarters: {hq})" if hq else ""
        return (
            f"{lead} — one of the 12 districts of Meghalaya{seat}. "
            f"Ask for its MGNREGA or PMAY-G figures, e.g. "
            f"“PMAY-G houses completed in {name}” or "
            f"“MGNREGA person-days in {name} in 2023-24”."
        )
    parent = hit.get("district")
    where = f" in {parent} district" if parent else ""
    return (
        f"{name} is a C&RD (community & rural development) block{where} of "
        f"Meghalaya. Ask for its MGNREGA or PMAY-G figures, e.g. "
        f"“MGNREGA person-days in {name}” or "
        f"“PMAY-G houses sanctioned in {name}”."
    )


def _geo_definition_answer(question: str) -> "dict | None":
    """A direct answer for a 'spell out this district / block' question, or None
    to let normal routing handle it."""
    q = (question or "").strip()
    if not q or len(q.split()) > 10:
        return None
    if not _DEFN_CUE_RE.search(q):
        return None
    if _DATA_HINTS.search(q) or _AGGREGATE_CUE.search(q):
        return None
    core = _DEFN_STRIP_RE.sub(" ", q)
    core = re.sub(r"[^\w&./ -]+", " ", core)
    core = re.sub(r"\s+", " ", core).strip(" -.")
    if not core or len(core.split()) > 5:
        return None
    hit = lookup_geo_term(core)
    if not hit:
        return None
    logger.info("geo-definition shortcut: %r -> %s %r", question, hit["type"], hit["display"])
    return {
        "route": "knowledge", "intent": "RAG", "confidence": "high",
        "answer": _format_geo_definition(hit), "sources": [],
        **_empty_data_fields(),
    }


def reply_abandons_clarification(paused_question: str, reply: str) -> bool:
    """True when a reply to a clarification pause is NOT an answer to it —
    a greeting/thanks/goodbye/abuse, or a fresh self-standing question — and
    the pause should therefore be DROPPED and the reply handled as a new turn.

    Used only by the LangGraph checkpointer resume owners
    (app/api/routers/query.py's `pipeline_graph.resume_via_graph` branch) —
    `_run_pipeline` resumes by slot filling on the frame instead
    (app/nlu/frame_merge.py). That branch used to resume unconditionally on
    `is_paused()`, so a user who typed "thanks" or asked something completely
    different at a clarification prompt had it fed to the graph as their
    answer and glued onto the paused question.
    """
    stem = (paused_question or "").rstrip(" ?.")
    r = (reply or "").strip()
    # A one-tap chip carries the whole rewritten question — always an answer,
    # never an abandonment, even though it is long enough to look like one.
    if stem and r.lower().startswith(stem.lower()):
        return False
    hit = edge.detect_edge_case(r)
    # "off_topic" is the whitelist gate mis-firing on a bare scope fragment
    # ("wgh", "Ri Bhoi 2023-24") with no scheme words — NOT an abandonment.
    if bool(hit) and hit.get("type") != "off_topic":
        return True
    return _reply_abandons_scope_pause(r)


def matching_chip(reply: str, options: "list[dict] | None") -> "dict | None":
    """The one-tap chip whose own question text is exactly this reply, if any.

    A chip sends its whole `question` as an ordinary user message, so the only
    thing that distinguishes "the user tapped a chip" from "the user typed a
    sentence" is that the text matches an option we offered. Comparing against
    the offered options is exact where the prefix test in
    `merge_clarification_reply` is a heuristic that only holds for chips which
    APPEND their choice — a chip that substitutes its choice into the middle of
    the question (the FY chips, `_village_chip_question`) shares only a prefix
    with the paused question and would otherwise be merged into it as if it
    were free text."""
    target = (reply or "").strip().casefold().rstrip(" ?.")
    for opt in options or []:
        if not isinstance(opt, dict):
            continue
        q = str(opt.get("question") or "").strip().casefold().rstrip(" ?.")
        if q and q == target:
            return opt
    return None


def merge_clarification_reply(paused_question: str, reply: str,
                              options: "list[dict] | None" = None) -> str:
    """Fold a clarification reply back into the question that paused.

    A one-tap chip sends the WHOLE rewritten question, which already begins
    with the paused stem — blindly concatenating duplicates it ("Total MGNREGA
    person-days in 2023-24, Total MGNREGA person-days in 2023-24 for South Garo
    Hills"). That mangled text then goes to the SQL generator, which is exactly
    how a resumed "for South Garo Hills" chip produced SQL with NO district
    filter at all — a state-wide total silently presented as a district answer.
    Reported from the live UI, 2026-09-21.

    Used only by the LangGraph checkpointer resume owners
    (app/orchestration/pipeline_graph.py's two resume points and
    app/orchestration/langgraph_followup.py) — `_run_pipeline` never glues
    reply text: it fills the paused slot on the frame (app/nlu/frame_merge.py).
    """
    stem = paused_question.rstrip(" ?.")
    reply = str(reply).strip()
    # The chip already carries the full question — pass it straight through.
    # Checked against the offered options first (exact, and correct for a chip
    # that rewrites the middle of the question), then by the original prefix
    # test, which still covers every caller that has no options to hand.
    if matching_chip(reply, options) is not None:
        return reply
    if reply.lower().startswith(stem.lower()):
        return reply
    return f"{stem}, {reply}"


async def apply_post_answer_context(result: dict, raw_question: str,
                                    session: "Session | None" = None) -> dict:
    """The post-answer half of `answer_question`: deterministic 'Next steps'
    suggestions + the Context Updater (fold this turn into the session's
    structured state, refresh the rolling summary). Both best-effort; see
    context_manager. Skipped for a clarification pause: nothing was actually
    answered yet, and `_run_pipeline` never reaches here for one anyway (it
    raises).

    Extracted from `answer_question` so the ONE caller that deliberately does
    NOT go through it — app/api/routers/query.py's `pipeline_graph.resume_via_graph`
    branch, which must continue a paused graph thread at the node it paused at
    rather than restart `_run_pipeline` from node 5.1 — can still run the same
    post-processing. Before this existed, a graph-resumed turn silently skipped
    the whole context layer: ConversationState (scheme/district/block/village/
    year/metric) never learned the resumed turn, so the NEXT follow-up had
    nothing to inherit, and query.py's `save_context_state` then mirrored that
    stale blob to L2, outliving the worker. See
    tests/unit/test_graph_resume_context_layer.py.
    """
    _frame = None
    if session is not None:
        _turn_frame = session.understand_frame or {}
        if _turn_frame.get("question") == raw_question:
            _frame = _turn_frame.get("frame")
    _attach_followups(result, result.get("rewritten_question") or raw_question, frame=_frame)
    if settings.CONTEXT_LAYER_ENABLED and session is not None:
        try:
            context_manager.update_state(
                session, raw_question, result.get("rewritten_question") or raw_question, result)
            await context_manager.maybe_update_summary(session)
        except Exception:  # noqa: BLE001 — the context layer must never break an answer
            logger.warning("context layer post-processing failed (non-fatal)", exc_info=True)
    return result


async def answer_question(question: str, session: "Session | None" = None,
                          scope: "auth.UserScope | None" = None,
                          on_event: "answer_stream.OnEvent | None" = None) -> dict:
    """Public entry point. Runs the pipeline, then attaches deterministic
    'Next steps' suggestions to any data/knowledge answer.

    `on_event` (optional): live answer events for a streaming client — see
    app/response/answer_stream.py. The composer streams "token" events; this
    is the ONE central place that makes every other answer path (deterministic
    answers, scheme listings, edge replies, KB fallbacks, an "Understood as"
    prefix) reach the client, as a final "replace" when the returned answer
    differs from what was shown. A clarification pause raises instead and is
    rendered by the caller, as before."""
    raw_question = question
    with answer_stream.bind(on_event):
        result = await _run_pipeline(question, session=session, scope=scope)
        result = await apply_post_answer_context(result, raw_question, session=session)
        await answer_stream.settle(on_event, result.get("answer") or "")
    return result


def _attach_followups(result: dict, question: str, frame: "dict | None" = None) -> None:
    """Add `follow_up_options` (+ back-compat `follow_ups` / `follow_up`) to a
    data/knowledge result. Best-effort — a failure here never breaks the answer."""
    if not settings.FOLLOWUP_SUGGEST_ENABLED:
        return
    if result.get("route") not in ("data", "knowledge"):
        return
    try:
        opts = followups.build_followups(
            result["route"], question,
            result.get("schemes") or [], result.get("resolved_entities") or {},
            sql=result.get("sql"),
            rows=result.get("rows") or result.get("data"), frame=frame)
    except Exception:  # noqa: BLE001
        logger.warning("follow-up suggestion build failed", exc_info=True)
        return
    if opts:
        result["follow_up_options"] = opts
        result["follow_ups"] = [o["question"] for o in opts]
        result["follow_up"] = opts[0]["question"]


def _pipeline_graph_selected(session: "Session | None") -> bool:
    """True => this call should go through pipeline_graph instead of the
    bespoke _answer_data path. PIPELINE_GRAPH_ENABLED=True always wins
    (100% rollout); otherwise a session-sticky canary keyed by
    PIPELINE_GRAPH_CANARY_PERCENT — bucketed by user_id when the caller is a
    real user, else session_id, so one conversation never flips paths
    mid-thread. No stable identity (no session) => stays on the bespoke path,
    never canaried. See config.py's PIPELINE_GRAPH_CANARY_PERCENT docstring —
    multi-tenant-rls-scheme-scaleout/tasks.md 5.2."""
    if settings.PIPELINE_GRAPH_ENABLED:
        return True
    pct = max(0, min(100, settings.PIPELINE_GRAPH_CANARY_PERCENT))
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    if session is None:
        return False
    key = session.user_id or session.session_id
    bucket = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 100
    return bucket < pct


async def _run_pipeline(question: str, session: "Session | None" = None,
                        scope: "auth.UserScope | None" = None) -> dict:
    """Understand, then answer. The message's QueryFrame is built first
    (frame_merge.frame_for_turn — which resumes a pending pause by filling its
    slot, or merges a follow-up onto the previous answer's frame) and is
    published via understand.current_frame for the gates in _answer_data and
    the LangGraph nodes. A pause records the frame + the slot it asks
    (frame_merge.on_pause); an answer gets the "Understood as / Assumed"
    lines and is remembered for the next follow-up (frame_merge.after_answer)."""
    if session is not None:
        session.understand_frame = None
    turn = await frame_merge.frame_for_turn(question, session)
    token = understand.current_frame.set(turn.frame)
    try:
        result = await _run_pipeline_body(turn.question, session=session, scope=scope,
                                          frame_followup=turn.followup, frame_intent=turn.intent)
    except ClarificationNeeded as e:
        frame_merge.on_pause(e, turn)
        raise
    finally:
        understand.current_frame.reset(token)
    frame_merge.after_answer(result, question, turn, session)
    return result


async def _run_pipeline_body(question: str, session: "Session | None" = None,
                             scope: "auth.UserScope | None" = None,
                             frame_followup: bool = False,
                             frame_intent: "str | None" = None) -> dict:
    """`question` is the turn's standalone question from
    frame_merge.frame_for_turn: the message itself, a pause with its slot
    filled, or a follow-up merged onto the previous answer's frame.

    `frame_followup`: the Understand node's decision that this message
    continues the previous answer (it saw the recent turns). The question is
    already standalone; the previous turn's entities only seed resolution as
    a fallback (prior_resolved).

    `frame_intent`: the frame's DATA / KNOWLEDGE routing decision, used
    instead of the separate classify_intent model call — the frame read the
    message WITH its conversation, where a bare continuation ("what about
    PMAY", a typed "ekh" answering "which district?") looks like a knowledge
    question to a classifier that sees the sentence alone. EDGE is not taken
    from the frame: the deterministic edge handling below runs first. None
    (no Understand frame this turn) => classify_intent as before."""
    raw_question = question
    question = _correct_scheme_spelling(question)

    # Computed early so the step-0 edge check below can relax its whitelist
    # gate for a plausible follow-up — see edge.detect_edge_case's has_context.
    prev = session.last_turn if session is not None else None
    has_antecedent = prev is not None and prev.route in _ANTECEDENT_ROUTES
    ctx_state = (session.state if (session is not None and settings.CONTEXT_LAYER_ENABLED
                                   and settings.CONTEXT_STATE_ENABLED) else None)

    # 0-. "What is EKH?" / "MYLLIEM full form" — spell out a district or block
    #     straight from the resolver catalogue. Must run BEFORE the edge layer
    #     (which bounces a lone abbreviation as off-topic) and before routing
    #     (KNOWLEDGE / RAG has no glossary for these).
    geo_def = _geo_definition_answer(question)
    if geo_def:
        if question != raw_question:
            geo_def["rewritten_question"] = question
        return geo_def

    # 0-a. "What schemes are available?" / "what's the difference between the
    #      schemes?" — answered directly (see _scheme_listing_answer /
    #      _scheme_comparison_answer) rather than falling through to RAG, which
    #      has no single document covering either and either over-elaborates on
    #      one scheme or says "not covered".
    direct = _scheme_listing_answer(question) or _scheme_comparison_answer(question)
    if direct:
        if question != raw_question:
            direct["rewritten_question"] = question
        return direct

    # 0. Edge — greetings, identity, thanks, off-topic, abuse.
    hit = edge.detect_edge_case(question, has_context=has_antecedent)
    if hit:
        return {"route": "edge", "intent": "EDGE", "confidence": "high",
                "answer": hit["response"], "edge_type": hit["type"],
                "suggestions": hit.get("suggestions", []),
                **_empty_data_fields()}

    # 0f. Deterministic reference resolution ("the previous year", "the
    #     current year", "the former/latter", "the other one", "both") against
    #     the session's structured conversation state — see
    #     context_manager.substitute_references. frame_for_turn already ran it
    #     on the message before Understand; re-run on the standalone question
    #     a merge produced. Ambiguous ("the other one" with no recorded
    #     comparison) reuses the existing clarification mechanism rather than
    #     guessing. Any other failure degrades to the question unchanged.
    if ctx_state is not None:
        try:
            question = context_manager.substitute_references(question, ctx_state)
        except context_manager.AmbiguousReference as e:
            raise ClarificationNeeded(e.question, options=e.options, rule="entity-ambiguous")
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.substitute_references failed — continuing unchanged",
                           exc_info=True)

    # 1. Follow-up — decided by the Understand node, whose frame is already
    #    merged onto the previous answer (app/nlu/frame_merge.py), so `question`
    #    is standalone. Only a continuation of an actual scheme answer counts:
    #    a fragment has nothing coherent to attach to otherwise.
    is_followup_rewrite = bool(frame_followup and has_antecedent)

    # 1b. Re-check edge on the reference-substituted question (cheap).
    hit = edge.detect_edge_case(question, has_context=has_antecedent)
    if hit:
        return {"route": "edge", "intent": "EDGE", "confidence": "high",
                "answer": hit["response"], "edge_type": hit["type"],
                "suggestions": hit.get("suggestions", []),
                "rewritten_question": question if question != raw_question else None,
                **_empty_data_fields()}

    # 1f. A follow-up fragment that rewrote to a standalone question still
    #     naming no scheme (and no scheme-specific vocabulary of its own) gets
    #     the session's pinned scheme appended deterministically — see
    #     context_manager.inject_scheme_hint. Only for an actual continuation
    #     (is_followup_rewrite), never for a brand-new question: that case is
    #     deliberately left to the existing "which scheme?" pause below.
    if is_followup_rewrite and ctx_state is not None:
        try:
            question = context_manager.inject_scheme_hint(question, ctx_state)
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.inject_scheme_hint failed — continuing unchanged",
                           exc_info=True)

    # 1c. Bank / financial-channel details are not held for any loaded scheme —
    #     say so, with the reason, before routing. Checked ahead of the DATA/
    #     KNOWLEDGE split: phrasing like "what is the bank-wise disbursement…"
    #     trips _KNOWLEDGE_HINTS on "what is" and would otherwise dead-end in
    #     RAG ("not covered in the reference material") instead of explaining
    #     that the column itself isn't queryable.
    if _BANK_REQUESTED.search(question):
        _clarification = _bank_clarification(question)
        if _clarification is not None:
            raise _clarification

    # 1d. Administrative expenditure is deliberately excluded from reporting for
    #     every scheme that has it (see _ADMIN_EXPENDITURE_REQUESTED above) —
    #     same reasoning and same place as the bank check just above.
    if _ADMIN_EXPENDITURE_REQUESTED.search(question):
        raise _admin_expenditure_clarification(question)

    # 1e. "What percentage were women?" — no confirmed denominator to compute
    #     one from (see _WOMEN_SHARE_REQUESTED above). Same place, same reasoning.
    #     PMAY-G's house-allotment women's share is a different, well-defined
    #     computation — left alone.
    if _WOMEN_SHARE_REQUESTED.search(question) and not _WOMEN_SHARE_PMAYG_CONTEXT.search(question):
        raise _women_share_clarification(question)

    # 2. Route: number question or scheme-rules question?
    if frame_intent in ("DATA", "KNOWLEDGE"):
        intent = frame_intent
    else:
        with request_trace.stage("intent"):
            intent = await classify_intent(question)

    # 3. KNOWLEDGE -> RAG over the scheme reference docs.
    if intent == "KNOWLEDGE":
        # Scope retrieval to a single scheme when we're confident which one this
        # is about — named outright, or (for a follow-up with nothing named of
        # its own) the scheme the previous turn was about. Without this, vector
        # search has no scheme filter at all and can blend in another scheme's
        # content (e.g. PMAY-Urban passages into a PMAY-G-scoped answer).
        _kb_scheme = None
        _named = _named_schemes(question)
        if len(_named) == 1:
            _kb_scheme = _named[0]
        elif prev is not None and len(prev.schemes or []) == 1:
            _kb_scheme = prev.schemes[0]

        # Genuinely scheme-agnostic ("tell me about the scheme", "how do I
        # apply", "what are the benefits") — no scheme named, no follow-up
        # antecedent, and no vocabulary that pins it to one. Guessing here (or
        # letting bare vector search pick whichever doc scores highest) is how
        # a vague question came back "not covered" while quietly assuming
        # MGNREGA. Ask which of the four schemes instead, same one-tap chips
        # the DATA path already uses (clarify_rules rule 1): neither the frame
        # nor the scheme names / vocabulary in the text pins one.
        if _kb_scheme is None and settings.SCHEME_CLARIFY_ENABLED \
                and not clarify_rules.gate_frame(question).resolved_schemes \
                and not _shortcut_scheme(question):
            raise _scheme_clarification(question)

        # Two or more schemes named outright ("how do I apply across MGNREGA,
        # PMAY-G, Focus Plus and CM Elevate") — retrieve each scheme's chunks
        # separately (see rag.answer_from_kb_multi) instead of one unscoped
        # search, which otherwise lets one scheme's passages crowd out another's.
        if len(_named) > 1:
            kb = await rag.answer_from_kb_multi(question, schemes=_named)
            base = {"rewritten_question": question if question != raw_question else None,
                    "schemes": _named}
        else:
            kb = await rag.answer_from_kb(question, scheme=_kb_scheme)
            base = {"rewritten_question": question if question != raw_question else None,
                    "schemes": [_kb_scheme] if _kb_scheme else []}
        if kb:
            return {"route": "knowledge", "intent": "RAG", "confidence": kb["confidence"],
                    "answer": kb["answer"], "sources": kb["sources"],
                    **_empty_data_fields(), **base}
        return {"route": "knowledge", "intent": "RAG", "confidence": "low", "sources": [],
                "answer": "I don't have information about that for MGNREGA, PMAY-G, "
                          "Focus Plus or CM Elevate.",
                **_empty_data_fields(), **base}

    # 4. DATA -> NL->SQL. On a hard failure, try the KB once before giving up.
    # A rewritten follow-up's entities are seeded with the previous turn's
    # resolved district/block/village/year as a fallback (see resolve_entities'
    # `prior_resolved` param) — the LLM rewrite works from prev.question/answer
    # TEXT, so an entity can silently drop if it doesn't literally reappear in
    # the rewritten wording (e.g. a village name the rewrite paraphrases away).
    _prior_resolved = prev.resolved_entities if (is_followup_rewrite and prev is not None) else None
    if is_followup_rewrite and ctx_state is not None:
        # Extends the fallback above with session-level structured state, so a
        # KNOWLEDGE/EDGE turn sitting between the last DATA answer and this
        # follow-up (which leaves resolved_entities empty — see
        # context_manager.update_state) doesn't erase district/block/village/
        # year a later "and in 2023-24?" still needs. Turn-level prev values
        # still win where both are present.
        try:
            _prior_resolved = context_manager.merged_prior_resolved(_prior_resolved, ctx_state)
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.merged_prior_resolved failed — using turn-level only",
                           exc_info=True)
    try:
        # openspec/changes/multi-tenant-rls-scheme-scaleout: the actual
        # production cutover point for the Grant Thornton proposal's "runtime
        # pipeline is implemented as a LangGraph agent" requirement (Section 4
        # of the proposal PDF) — app/orchestration/pipeline_graph.py's node-decomposed
        # StateGraph is code-complete and test-verified but was, until this
        # flag existed as a real branch, never reachable from a live request
        # (settings.PIPELINE_GRAPH_ENABLED was defined but read nowhere).
        # answer_data_via_graph_compat has the exact same calling contract as
        # _answer_data (see its own docstring for the pause/resume design),
        # so nothing below this line, in app/api/routers/query.py, or in
        # app/conversation/session_store.py needs to change for this branch to exist.
        # Local import: app.orchestration.pipeline_graph imports app.orchestration.pipeline at module
        # level, so importing it back at module level here would cycle.
        # _pipeline_graph_selected also covers the PIPELINE_GRAPH_CANARY_PERCENT
        # staged rollout (multi-tenant-rls-scheme-scaleout/tasks.md 5.2) —
        # PIPELINE_GRAPH_ENABLED alone still means "always graph" (pct ignored).
        if _pipeline_graph_selected(session):
            from app.orchestration import pipeline_graph
            # Task 5.4: real cross-request resume via the graph's own
            # checkpointer needs a stable, session-scoped thread_id — pass
            # session.session_id only when LANGGRAPH_FOLLOWUP_ENABLED is off.
            # The two are deliberately mutually exclusive here: when both
            # flags are on, LANGGRAPH_FOLLOWUP_ENABLED's own wrapper
            # (app/orchestration/langgraph_followup.py) already catches ClarificationNeeded
            # around this entire call via ITS OWN, separate checkpointer —
            # if pipeline_graph ALSO kept its checkpoint alive in that case,
            # two independent checkpointers would both think they own the
            # same pause, and pipeline_graph's would never actually get
            # resumed (query.py's LANGGRAPH_FOLLOWUP_ENABLED branch owns the
            # resume call in that combination, not the one added for this
            # task) — a real, permanent orphan, the exact bug fixed
            # 2026-09-17 for the always-fresh-UUID case. Passing thread_id=None
            # here (the pre-5.4 default) keeps that combination exactly as
            # tested: fresh UUID, cleaned up on pause, no change. A pause the
            # graph keeps (graph_resumable) is resumed by the router's graph
            # branch, not by frame slot filling — the router stores no
            # pending_frame for it, so exactly one owner holds each pause.
            _graph_thread_id = (
                session.session_id
                if session is not None and not settings.LANGGRAPH_FOLLOWUP_ENABLED
                else None
            )
            result = await pipeline_graph.answer_data_via_graph_compat(
                question, scope=scope, prior_resolved=_prior_resolved,
                is_followup=is_followup_rewrite, thread_id=_graph_thread_id)
        else:
            result = await _answer_data(question, scope=scope, prior_resolved=_prior_resolved,
                                        is_followup=is_followup_rewrite)
        if question != raw_question:
            result["rewritten_question"] = question
        return result
    except Exception as e:  # noqa: BLE001 — sorted by data_path_fallback_or_reraise
        fallback = await data_path_fallback_or_reraise(e, question, raw_question)
        if fallback is None:
            raise
        return fallback


async def data_path_fallback_or_reraise(e: BaseException, question: str,
                                        raw_question: str) -> "dict | None":
    """Decide what an exception escaping the DATA path becomes. Returns a
    result dict to answer with, or None meaning "the caller must re-raise"
    (the caller does a bare `raise`, so the original traceback is preserved).

    This is `_run_pipeline`'s own DATA-path except-ladder, lifted out verbatim
    so the ONE caller that does not go through `_run_pipeline` —
    app/api/routers/query.py's `pipeline_graph.resume_via_graph` branch, which must
    continue a paused graph thread at the node it paused at — gets identical
    behavior instead of none at all.

    Before this existed, ANY non-transient failure on a resumed turn (most
    commonly `_execute_one_attempt` raising ValueError once the SQL repair
    budget is spent — e.g. the §5.11 semantic verifier rejecting both the
    generated and the repaired SQL) escaped raw to query.py's generic handler
    and surfaced as a bare **502 Bad Gateway** in the chat UI. The bespoke path
    and the non-resume graph path both turn that same failure into a graceful
    KB fallback / "try rephrasing" reply. Reported from the live UI, 2026-09-21.
    """
    if isinstance(e, ClarificationNeeded):
        return None
    if isinstance(e, OutOfScope):
        logger.info("out of scope (%s) — returning Megh One AI scope reply", e)
        return _out_of_scope_result(question, raw_question)
    if isinstance(e, (llm.ModelBusyError, asyncio.TimeoutError, httpx.TimeoutException,
                      httpx.TransportError)):
        # The model gateway hiccuped (saturated slot, read timeout, connection
        # reset) part-way through the DATA path — this is NOT "the question can't
        # be answered from the data". Propagate it so the router returns a
        # 503/504 "busy, please retry" instead of the misleading "couldn't build
        # a working query" fallback below, which reads as if the question itself
        # were at fault.
        logger.warning("data path hit a transient gateway error (%s) — re-raising", e)
        return None
    if isinstance(e, httpx.HTTPStatusError):
        if e.response is not None and e.response.status_code >= 500:
            logger.warning("data path hit gateway %s — re-raising", e.response.status_code)
            return None
    logger.warning("data path failed (%s) — trying KB fallback", e, exc_info=True)
    request_trace.note("fallback", "kb_after_data_failure")
    return await _data_path_kb_fallback(question)


async def _data_path_kb_fallback(question: str) -> dict:
    """The DATA path genuinely couldn't produce a query (bad/uncoverable question,
    not an infra blip) — try the knowledge base once, then give the 'rephrase it'
    reply. Transient gateway errors are handled by the caller and never reach here."""
    kb = await rag.answer_from_kb(question)
    if kb:
        return {"route": "knowledge", "intent": "RAG", "confidence": kb["confidence"],
                "answer": kb["answer"], "sources": kb["sources"], **_empty_data_fields()}
    # Name the scheme(s) actually in play, not a hardcoded pair — this message used
    # to always say "MGNREGA / PMAY-G data" even for a Focus Plus / CM Elevate
    # question, which reads as if the conversation's own context had been dropped
    # (it hadn't — this text just never grew past the original two-scheme build).
    _fallback_schemes = _named_schemes(question) or _infer_scheme_from_terms(question)
    _schemes_text = " / ".join(_fallback_schemes) if _fallback_schemes else " / ".join(SCHEME_CATALOG)
    return {"route": "data", "intent": "DATA", "confidence": "low",
            "answer": ("I understood the question but couldn't build a working query for it "
                       f"against the current {_schemes_text} data. Try rephrasing it, or ask "
                       "for a simpler breakdown first (e.g. \"PMAY-G sanctions by district "
                       "for 2023\")."),
            **_empty_data_fields()}
