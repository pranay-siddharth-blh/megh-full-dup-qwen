"""
app/nlu/clarify_rules.py — the clarification gates: ONE ordered list of
rules evaluated on the normalised QueryFrame (app/nlu/understand.py). They
replaced the five regex predicates on raw question text
(_needs_scheme/_topn/_scope/_year/_tranche_clarification), which are gone.

    1. scheme missing                        -> ask   (never defaulted)
    2. metric missing / vague qualifier      -> ask;  ranking without N -> default top-N
    3. area missing for an aggregate question -> default statewide (else ask)
    4. year missing once the place is settled -> scheme's default year policy (else ask)
    5. Focus Plus tranche missing             -> default all tranches (else ask)

A rule asks ONLY when a slot is genuinely empty AND the scheme's
*_default_rules.yaml has no default for it. When a default exists it is
applied the way the matching one-tap option would have applied it (same
question wording, same pinned values) and its assumption_text is recorded,
so the answer discloses exactly what was assumed. Questions and options come
from the pipeline's existing builders, so the UI does not change.

The scheme is never defaulted even though the rules files carry a
missing_scheme entry — CLAUDE.md: "the LLM never guesses missing slots", and
a guessed scheme is a confidently wrong number.

Rules 1-2 run before entity resolution, rules 3-5 after it — through
gates_before_resolution / gates_after_resolution below, which
pipeline._answer_data AND the LangGraph nodes both call, so the two paths
cannot drift. They read this turn's published frame (understand.current_frame)
or, when the Understand model gave none, understand.fallback_frame(question).
pipeline.py imports this module; this module imports pipeline lazily.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core import request_trace
from app.core.config import settings
from app.nlu import defaults_engine
from app.nlu.understand import QueryFrame, current_frame, fallback_frame

# A metric that is only a judgement word — nothing to rank or total by.
_VAGUE_WORDS = {"best", "worst", "top", "good", "bad", "better", "worse", "performance",
                "performing", "performer", "performers", "lagging", "laggard", "progress",
                "doing", "well", "poorly", "status", "overall", "most", "least", "numbers",
                "figures", "data", "stats", "statistics"}
_METRIC_CONDITIONS = ("vague_qualifier", "missing_metric_for_ranking", "missing_metric_for_trend")
_ALL_YEARS = re.compile(r"\ball\b.*\byears?\b|\boverall\b|\bcumulative\b|\bto date\b|\bever\b|"
                        r"\bsince (?:the )?(?:start|beginning|inception)\b|\ball[\s-]time\b",
                        re.IGNORECASE)
_RELATIVE = (
    (re.compile(r"\b(this|current|latest|recent|present)\b", re.IGNORECASE), "relative_year_latest"),
    (re.compile(r"\b(last|previous|past|prior)\b", re.IGNORECASE), "relative_year_previous"),
    (re.compile(r"\b(first|earliest|oldest)\b", re.IGNORECASE), "relative_year_earliest"),
)
_GEO_KEYS = ("district", "district_list", "block", "block_list", "village_code",
             "assembly_constituency", "district_list_region")


@dataclass
class GateOutcome:
    """What the gates decided for this turn (when nothing was asked)."""
    question: str                                   # possibly rewritten by an applied default
    assumptions: list[str] = field(default_factory=list)
    pins: dict = field(default_factory=dict)        # resolved-entity values a default pinned
    display: dict = field(default_factory=dict)
    fired: list[str] = field(default_factory=list)  # "rule:outcome" trace for the audit record


def _fire(out: "GateOutcome", outcome: str) -> None:
    """Record a rule outcome on the turn AND in the request's audit trace — the
    trace keeps it even when the rule then raises a clarification."""
    out.fired.append(outcome)
    request_trace.append("rules_fired", outcome)


def _default(schemes: list[str], condition: str) -> "dict | None":
    """The first scheme's default for `condition` from its *_default_rules.yaml."""
    for s in schemes or []:
        rule = defaults_engine._load_scheme_rules(s).get(condition)
        if rule:
            return rule
    return None


def _stem(question: str) -> str:
    return question.strip().rstrip(" ?.")


def _fy_label(year_key: int) -> str:
    return f"FY {year_key}-{(year_key + 1) % 100:02d}"


# ── rules 1-2: before entity resolution ────────────────────────────────────
def before_resolution(frame: QueryFrame, question: str) -> GateOutcome:
    """Rules 1 (scheme) and 2 (metric / top-N). Raises the existing
    ClarificationNeeded when a rule must ask; else returns the outcome."""
    from app.orchestration import pipeline

    out = GateOutcome(question=question)
    schemes = list(frame.resolved_schemes)

    # 1. scheme missing — ask, never default.
    if not schemes:
        _fire(out, "scheme:ask")
        raise pipeline._scheme_clarification(question)
    _fire(out, "scheme:ok")

    # 2a. metric missing / only a vague qualifier — ask with the rules file's
    #     own question for that condition (the clarification engine's text).
    metric_toks = re.findall(r"[a-z]+", (frame.metric or "").casefold())
    vague = bool(metric_toks) and all(t in _VAGUE_WORDS for t in metric_toks)
    missing = not metric_toks and frame.query_type in ("ranking", "comparison", "trend")
    if vague or missing:
        _fire(out, "metric:ask")
        raise _metric_clarification(question, schemes, frame)
    _fire(out, "metric:ok")

    # 2b. ranking with no N — the scheme's missing_top_n default (else ask).
    if settings.TOPN_CLARIFY_ENABLED and frame.query_type == "ranking" and frame.top_n is None \
            and frame.group_by:
        rule = _default(schemes, "missing_top_n")
        if rule is None:
            _fire(out, "top_n:ask")
            raise pipeline._topn_clarification(question)
        n = int(str(rule.get("default_value") or 5))
        out.question = pipeline._inject_topn(out.question, n)
        out.assumptions.append(rule.get("assumption_text") or f"Showing the top {n}.")
        _fire(out, f"top_n:default:{n}")
    return out


def _metric_clarification(question: str, schemes: list[str], frame: QueryFrame):
    from app.nlu import clarification_engine
    from app.orchestration import pipeline

    stem = _stem(question)
    for scheme in schemes:
        rules = clarification_engine._load_scheme_rules(scheme)
        for cond in _METRIC_CONDITIONS:
            rule = rules.get(cond)
            if not rule or not rule.get("question"):
                continue
            text = str(rule["question"])
            try:
                text = text.format(value=frame.metric or "that", scheme=scheme)
            except (KeyError, IndexError, ValueError):
                pass
            chips = pipeline._ENGINE_CHIPS.get(cond)
            options = [{"label": label, "question": f"{stem}, {suffix}"} for label, suffix in chips] \
                if chips else None
            return pipeline.ClarificationNeeded(text, options=options, rule="metric-not-specified")
    return pipeline.ClarificationNeeded(
        "Which figure should the answer be based on — for example the amount spent, the "
        "number of beneficiaries, or the number of households?",
        rule="metric-not-specified")


# ── rules 3-5: after entity resolution ─────────────────────────────────────
def after_resolution(frame: QueryFrame, question: str, schemes: list[str], resolved: dict, *,
                     skip_scope_clarify: bool = False, already_all_combined: bool = False) -> GateOutcome:
    """Rules 3 (area), 4 (year) and 5 (Focus Plus tranche) on the resolved
    entities. Raises the existing ClarificationNeeded when a rule must ask;
    otherwise returns the (possibly defaulted) question, pins and
    assumptions. `resolved` is never mutated here — the caller applies pins."""
    from app.orchestration import pipeline

    out = GateOutcome(question=question)
    producer_group = pipeline._is_producer_group_question(question)
    stated_statewide = any(g.level == "state" for g in frame.geo_mentions) or \
        any((g.text or "").casefold() in ("meghalaya", "all of meghalaya") for g in frame.geo_mentions)
    has_geo = any(resolved.get(k) for k in _GEO_KEYS)

    # 3. area missing for an aggregate question -> statewide default (else ask).
    if skip_scope_clarify or producer_group:
        _fire(out, "area:skip")
    elif has_geo:
        _fire(out, "area:ok")
    elif frame.group_by or stated_statewide:
        _fire(out, "area:statewide-stated" if stated_statewide else "area:breakdown")
    elif settings.SCOPE_CLARIFY_ENABLED:
        rule = _default(schemes, "missing_geography")
        if rule is None:
            _fire(out, "area:ask")
            raise pipeline._scope_clarification(question, schemes)
        out.question = f"{_stem(out.question)} for all of Meghalaya"
        out.assumptions.append(rule.get("assumption_text") or "Covering all of Meghalaya.")
        _fire(out, "area:default:statewide")

    # 4. year missing once the place is settled -> the scheme's year default.
    if resolved.get("year_key") or frame.year_key is not None:
        _fire(out, "year:ok")
    elif pipeline._scheme_has_no_time_dimension(schemes) or producer_group:
        _fire(out, "year:no-time-dimension")
    else:
        _year_rule(frame, out, schemes)

    # 5. Focus Plus tranche missing -> all tranches default (else ask).
    if schemes == ["Focus Plus"] and not producer_group and settings.TRANCHE_CLARIFY_ENABLED:
        if resolved.get("tranche_label") or frame.tranche or already_all_combined \
                or (frame.group_by or "").casefold().startswith("tranch"):
            _fire(out, "tranche:ok")
        else:
            rule = _default(schemes, "tranche_unspecified")
            if rule is None:
                _fire(out, "tranche:ask")
                raise pipeline._tranche_clarification(out.question)
            out.question = f"{_stem(out.question)} across all tranches"
            out.assumptions.append(rule.get("assumption_text") or "Covering all tranches.")
            _fire(out, "tranche:default:all")
    return out


def _year_rule(frame: QueryFrame, out: GateOutcome, schemes: list[str]) -> None:
    from app.orchestration import pipeline

    if not settings.YEAR_CLARIFY_ENABLED:      # same switch the old year gate honours
        _fire(out, "year:off")
        return
    text = frame.year_text or ""
    if text and _ALL_YEARS.search(text):
        out.question = f"{_stem(out.question)} across all financial years"
        _fire(out, "year:all-stated")
        return
    condition = None
    if text:
        condition = next((c for rx, c in _RELATIVE if rx.search(text)), None)
        if condition is None:
            _fire(out, "year:stated-unparsed")   # e.g. "since 2020" — left to the pipeline
            return
    elif frame.query_type == "trend":
        condition = "trend_without_period"
    elif len(schemes) > 1:
        condition = "multi_year_request_without_years"
    else:
        condition = "missing_time_period"
    rule = _default(schemes, condition) or _default(schemes, "missing_time_period")
    if rule is None:
        _fire(out, "year:ask")
        raise pipeline._year_clarification(out.question, schemes)
    value = str(rule.get("default_value") or "")
    year_key = pipeline._parse_year_key(value)
    if year_key is not None:
        out.pins["year_key"] = year_key
        out.display["year"] = _fy_label(year_key)
        out.question = f"{_stem(out.question)} for {_fy_label(year_key)}"
        _fire(out, f"year:default:{year_key}")
    else:   # all_available_years and similar
        out.question = f"{_stem(out.question)} across all financial years"
        _fire(out, f"year:default:{value or 'all'}")
    out.assumptions.append(str(rule.get("assumption_text") or "").strip() or "Covering all financial years.")


# ── the gates as the pipeline and the LangGraph nodes call them ────────────
def gate_frame(question: str) -> QueryFrame:
    """The frame the gates read: this turn's published model frame, else a
    fallback frame built from `question` (see understand.fallback_frame)."""
    frame = current_frame.get()
    return frame if frame is not None else fallback_frame(question)


def gates_before_resolution(question: str) -> "tuple[str, list[str], list[str]]":
    """Rules 1-2 (scheme, metric / top-N). Returns (question, assumptions,
    trace); raises ClarificationNeeded when a rule must ask."""
    out = before_resolution(gate_frame(question), question)
    return out.question, out.assumptions, out.fired


def gates_after_resolution(question: str, schemes: list[str], entity_result: dict, *,
                           skip_scope_clarify: bool, prior_resolved: "dict | None",
                           pre_assumptions: "list[str] | None" = None,
                           pre_trace: "list[str] | None" = None) -> str:
    """Rules 3-5 (area, year, tranche). Applies any default's pins to
    entity_result and records every assumption applied this turn in
    entity_result["assumptions"] (the deterministic "Assumed: ..." line —
    not the composer's notes, so it is stated once, verbatim) and the rule
    trace in entity_result["gate_trace"]. Returns the (possibly defaulted)
    question; raises ClarificationNeeded when a rule must ask."""
    resolved = entity_result["resolved"]
    out = after_resolution(
        gate_frame(question), question, schemes, resolved, skip_scope_clarify=skip_scope_clarify,
        already_all_combined=bool((prior_resolved or {}).get("tranche_all_combined")))
    resolved.update(out.pins)
    entity_result.setdefault("display", {}).update(out.display)
    assumptions = list(pre_assumptions or []) + out.assumptions
    entity_result["assumptions"] = assumptions
    entity_result["gate_trace"] = list(pre_trace or []) + out.fired
    request_trace.note("assumptions", assumptions)
    return out.question
