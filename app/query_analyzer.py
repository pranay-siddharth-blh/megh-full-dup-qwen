"""
app/query_analyzer.py — the structured "query analyzer" node (pipeline
architecture doc §5.2): extracts query type, requested metric, named
entities, time scope, granularity, ambiguous terms, and a short intent
summary for an already-resolved DATA-route question, and returns it as the
`analysis` object `web/ai_query.html`'s NODE 2 renderer already expects
(`ai_query.html:2243-2283` — that renderer predates this module and was
previously dead code with nothing populating it).

Import direction is one-way (pipeline.py -> query_analyzer.py), same stance
already documented in app/findings.py and app/premise_check.py for avoiding a
cycle back into pipeline.py — the small set of question-classification
regexes this module needs are local copies of the equivalent ones in
pipeline.py (`_RANKING_CUE` etc.), not imports.

`entities`/`granularity`/`limit` are assembled deterministically from the
already-verified entity-resolution result (node 5.6) passed in by the
caller — this module never re-extracts or re-resolves an entity itself, only
one constrained-JSON model call for `metric`/`intent_summary`/`ambiguous_terms`
and a query_type/time_scope fallback the deterministic checks below don't
already answer with confidence.

analyze_query() never raises — a failure here must not turn a working answer
into a failed request (same isolation stance `_answer_data` already applies
to findings/chart_spec/defaults_engine).
"""
from __future__ import annotations

import json
import logging
import re

from app import llm

logger = logging.getLogger(__name__)

QUERY_TYPES = (
    "aggregation", "ranking", "comparison", "trend", "lookup",
    "distribution", "filter_list",
)

# ── Local copies of pipeline.py's question-classification cues ─────────────
# Deliberately duplicated rather than imported — see module docstring.
_RANKING_CUE = re.compile(
    r"\b(top|bottom|highest|lowest|most|least|best|worst|leading|leader|leads?|"
    r"rank(?:ed|ing)?|largest|smallest|biggest|maximum|minimum)\b",
    re.IGNORECASE,
)
_EXPLICIT_COUNT = re.compile(
    r"\btop[\s-]*(\d+)\b"
    r"|\b(?:top|bottom|first|last)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b"
    r"|\b(\d+)\s+(?:highest|lowest|largest|biggest|smallest|top|best|worst|most|least)\b",
    re.IGNORECASE,
)
_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_COMPARISON_CUE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|correlat\w*|relationship between|"
    r"linked (?:to|with))\b",
    re.IGNORECASE,
)
_TREND_CUE = re.compile(
    r"\btrend\b|\byear[\s-]?on[\s-]?year\b|\bover (?:the )?(?:last|past) \w+ years?\b|"
    r"\bover time\b|\bhistorical(?:ly)?\b",
    re.IGNORECASE,
)
_DISTRIBUTION_CUE = re.compile(
    r"\bby (?:district|block|village|panchayat|gp|year|month)\b|"
    r"\b(?:per|each|every|for all|across all|all the) "
    r"(?:district|block|village|panchayat|year|month)s?\b|"
    r"\b(?:district|block|village|year)[\s-]?wise\b|\bbreak[\s-]?down\b",
    re.IGNORECASE,
)
_FILTER_LIST_CUE = re.compile(
    r"\blist\b|\bwhich (?:villages?|blocks?|districts?|panchayats?)\b|"
    r"\bshow (?:me )?all\b",
    re.IGNORECASE,
)
_AGGREGATION_CUE = re.compile(
    r"\b(how many|count|total|sum|average|avg|number of)\b",
    re.IGNORECASE,
)

_ANALYSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "query_type": {"type": "string", "enum": list(QUERY_TYPES)},
        "metric": {"type": "string"},
        "time_scope": {"type": "string"},
        "intent_summary": {"type": "string"},
        "ambiguous_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "kind": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
    },
    "additionalProperties": False,
}

# Matches the consistent "'<term>' is not a known <kind>..." phrasing every
# resolve_entities() not-found note uses (app/pipeline.py, e.g. "'Foo' is not
# a known district — say so, do not filter on it."). Falls back to a generic
# kind when a note doesn't match (defensive — notes text is free-form English,
# not a contract this module should assume never changes wording).
_NOTE_TERM_RE = re.compile(
    r"^'(?P<term>.+?)' is not a known (?P<kind>[a-z][a-z\s]*?)(?:\s+for\s|\s*[—-])",
    re.IGNORECASE,
)


def _extract_json(raw: str) -> "dict | None":
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _fast_path_query_type(question: str) -> "tuple[str | None, int | None]":
    """Deterministic query_type + limit from question phrasing alone, reusing
    the same cues pipeline.py's own clarification predicates already trust.
    Returns (None, None) when nothing here is confident enough to decide —
    the caller falls back to the model's own query_type guess in that case."""
    q = question or ""
    m = _EXPLICIT_COUNT.search(q)
    limit = None
    if m:
        digits = m.group(1) or m.group(3)
        if digits:
            limit = int(digits)
        elif m.group(2):
            limit = _WORD_TO_NUM.get(m.group(2).lower())
    if _RANKING_CUE.search(q):
        return "ranking", limit
    if _COMPARISON_CUE.search(q):
        return "comparison", limit
    if _TREND_CUE.search(q):
        return "trend", limit
    if _DISTRIBUTION_CUE.search(q):
        return "distribution", limit
    if _FILTER_LIST_CUE.search(q):
        return "filter_list", limit
    if _AGGREGATION_CUE.search(q):
        return "aggregation", limit
    return None, limit


def _granularity_from_resolved(resolved: dict) -> str:
    if resolved.get("village_code"):
        return "village"
    if resolved.get("block") or resolved.get("block_list"):
        return "block"
    if resolved.get("district") or resolved.get("district_list") or resolved.get("district_list_region"):
        return "district"
    return "state"


def _entities_from_resolved(resolved: dict, display: dict) -> dict:
    districts: list[str] = []
    if display.get("district"):
        districts.append(display["district"])
    elif resolved.get("district"):
        districts.append(str(resolved["district"]))

    blocks: list[str] = []
    if display.get("block"):
        blocks.append(display["block"])
    elif resolved.get("block"):
        blocks.append(str(resolved["block"]))

    villages: list[str] = []
    if display.get("village"):
        villages.append(display["village"])

    regions: list[str] = []
    if resolved.get("district_list_region"):
        regions.append(str(resolved["district_list_region"]))
    if display.get("assembly_constituency"):
        regions.append(display["assembly_constituency"])

    return {
        "districts": districts,
        "regions": regions,
        "blocks": blocks,
        "villages": villages,
        "banks": [],
        "verticals": [],
        "ids": [],
        "persons": [],
    }


def _ambiguous_from_notes(notes: list) -> list:
    # `origin` marks provenance (not part of the frontend's own contract, but
    # harmless extra data for it — see openspec/changes/
    # query-analyzer-predicate-integration): "entity_note" entries duplicate
    # a message already surfaced via entity_result["notes"] elsewhere, so the
    # caller must not re-disclose them a second time; only "llm"-origin
    # entries (added by analyze_query below) are genuinely new information.
    out = []
    for note in notes or []:
        text = str(note)
        m = _NOTE_TERM_RE.match(text)
        if m:
            out.append({"term": m.group("term"), "kind": m.group("kind").strip(), "why": text,
                        "origin": "entity_note"})
        else:
            out.append({"term": text[:60], "kind": "unknown", "why": text, "origin": "entity_note"})
    return out


def _time_scope_from_resolved(display: dict) -> "str | None":
    return display.get("year")


async def analyze_query(question: str, schemes: list, entity_result: dict) -> "dict | None":
    """Build the node 5.2 `analysis` object for an already-resolved DATA-route
    question. Never raises: any failure is logged and `None` is returned so
    the caller can attach it (or omit it) without affecting the answer."""
    try:
        resolved = entity_result.get("resolved") or {}
        display = entity_result.get("display") or {}
        notes = entity_result.get("notes") or []

        fast_type, fast_limit = _fast_path_query_type(question)
        granularity = _granularity_from_resolved(resolved)
        entities = _entities_from_resolved(resolved, display)
        ambiguous = _ambiguous_from_notes(notes)
        det_time_scope = _time_scope_from_resolved(display)

        scheme_list = ", ".join(schemes) if schemes else "the loaded schemes"
        prompt = f"""Analyze this data question about {scheme_list}. Return ONLY JSON with:
  query_type      - one of: {', '.join(QUERY_TYPES)}
  metric          - the specific figure being asked for, a few words (e.g. "person-days",
                    "sanctioned amount", "houses completed"), or "" if unclear
  time_scope      - the time period the question covers in a few words (e.g. "FY 2023-24",
                    "all years", "last 3 years"), or "" if none is implied
  intent_summary  - one short plain-English sentence (max 12 words) paraphrasing what is
                    being asked
  ambiguous_terms - array of up to 2 {{"term","kind","why"}} objects for anything in the
                    question (other than a place name) that is unclear, e.g. an undefined
                    metric or comparison basis. Empty array if nothing is ambiguous.

Question: "{question}"
JSON:"""
        raw = await llm.call_classifier(prompt, guided={"guided_json": _ANALYSIS_JSON_SCHEMA})
        payload = _extract_json(raw) or {}

        query_type = fast_type or payload.get("query_type") or "aggregation"
        if query_type not in QUERY_TYPES:
            query_type = "aggregation"
        metric = (payload.get("metric") or "").strip() or None
        time_scope = det_time_scope or (payload.get("time_scope") or "").strip() or None
        intent_summary = (payload.get("intent_summary") or "").strip() or \
            f"{query_type.replace('_', ' ').title()} question about {scheme_list}"

        llm_ambiguous = payload.get("ambiguous_terms")
        if isinstance(llm_ambiguous, list):
            for item in llm_ambiguous:
                if isinstance(item, dict) and item.get("term"):
                    ambiguous.append({
                        "term": str(item.get("term")),
                        "kind": str(item.get("kind") or "metric"),
                        "why": str(item.get("why") or ""),
                        "origin": "llm",
                    })

        analysis = {
            "query_type": query_type,
            "metric": metric,
            "entities": entities,
            "time_scope": time_scope,
            "granularity": granularity,
            "ambiguous": ambiguous,
            "intent_summary": intent_summary,
        }
        if fast_limit is not None:
            analysis["limit"] = fast_limit
        return analysis
    except Exception:  # noqa: BLE001
        logger.warning("query_analyzer.analyze_query failed — omitting analysis", exc_info=True)
        return None
