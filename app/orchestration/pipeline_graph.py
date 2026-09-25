"""
app/orchestration/pipeline_graph.py — a node-decomposed LangGraph `StateGraph` covering
every §5.1-5.15 pipeline node for the DATA route, built additive/parallel
per openspec/changes/langgraph-full-pipeline-rewrite (see that change's
design.md). NOT wired into app/api/routers/query.py — production traffic still
runs through app.orchestration.pipeline._answer_data. This module exists to prove the
graph decomposition is correct and behavior-preserving; cutover is a
separate, later, explicit decision (design.md's Non-Goals).

Every node below is a thin wrapper calling the exact same functions
app.orchestration.pipeline._answer_data already calls (classify_scheme, resolve_entities,
generate_sql, the newly-extracted _execute_one_attempt, compose_response,
findings.evaluate, chart_spec.select_chart_type, ...) — no pipeline logic
is reimplemented here, only re-sequenced into graph nodes/edges. Nodes 5.8
(schema retrieval) and 5.9 (join discovery) are wrapped as-is: their
current, spec-diverging behavior (direct catalog injection, deny-list-only
join checking) is preserved unchanged, per design.md's answered scoping
decision — fixing that gap is separate, out-of-scope work.

Checkpointer: pluggable, selected by `settings.PIPELINE_GRAPH_CHECKPOINTER_DSN`.
Empty (default) => SQLite (`AsyncSqliteSaver`), the same backend
app/orchestration/langgraph_followup.py already proves works for this codebase. A Postgres
DSN => `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` — the
production-shape backend design.md calls for. **Update:** the `psycopg`
native-`libpq` blocker design.md's Risks section documented is resolved —
`psycopg[binary]` (a self-contained wheel bundling libpq, not the plain
`psycopg` package that needs a system libpq install) installs and imports
cleanly in this environment; verified end-to-end (real pause + resume + a
process-restart simulation) against a disposable local Postgres container,
not just an import check — see tests/integration/test_pipeline_graph_postgres.py. What
is NOT resolved: an actual reachable *production* Postgres from this
environment (a separate, infra-access question, same one
docs/SECURITY.md's DB-role-cutover item is blocked on) — this module's
Postgres path is proven correct against any reachable Postgres, production
reachability is orthogonal to it.

Windows note: psycopg's async mode needs `asyncio.WindowsSelectorEventLoopPolicy`
instead of the default `ProactorEventLoop` on Windows — irrelevant on the
actual Linux/systemd production target, but anyone exercising the Postgres
path from a Windows dev shell needs it set before `asyncio.run(...)` (see
tests/integration/test_pipeline_graph_postgres.py's own handling of this).

Repair-loop granularity — a deliberate, reported deviation from design.md's
"authorization runs as its own node, re-entered on every path back from a
repair edge, not folded into the validation node" decision: this module
implements §5.7 (authorization), §5.9's runtime join check, §5.11 (SQL
validation) and §5.12 (execution) as ONE combined node
(`node_execute_attempt`), not four separate ones. Splitting those four
further would require decomposing `app.orchestration.pipeline._execute_one_attempt`'s
single try-block into independently callable auth/validate/execute
functions, each with its own exception-classification contract — real
surgery on safety-critical, deeply-ordered code (PII blocking must run
ahead of the paid semantic verifier; auth must be re-checked on every
repair) that risks silently changing behavior if done in the same pass as
the graph rewrite itself. This module calls `_execute_one_attempt` as one
unit and classifies its outcome (success / denied / repairable) via the
conditional edge below — the repair loop IS expressed as a graph edge
(design.md's actual durability requirement), just not sub-divided inside
that one attempt. Finer decomposition remains a safe, separate follow-up
once `_execute_one_attempt` itself is deliberately split in its own
reviewed change.
"""
from __future__ import annotations

import dataclasses
import logging
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

try:  # pragma: no cover — exercised only when a Postgres DSN is configured
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
except ImportError:  # pragma: no cover
    AsyncPostgresSaver = None  # type: ignore[assignment, misc]

from app.core import auth
from app.orchestration import pipeline
from app.core.config import settings

logger = logging.getLogger(__name__)

# The ClarificationNeeded rules a pause here can durably resume for —
# the same set app/orchestration/langgraph_followup.py and app/api/routers/query.py's bespoke
# mechanism already recognize as resumable. Every other rule is a terminal
# refusal: re-raised, never interrupted.
_PAUSE_ELIGIBLE_RULES = pipeline.RESUMABLE_CLARIFICATION_RULES

# Sibling of langgraph_followup's own checkpoint file — same "durable local
# file, no server" posture, kept separate so the two components' threads
# never collide.
_CHECKPOINT_DB_PATH = Path(__file__).resolve().parents[2] / "logs" / "pipeline_graph_checkpoints.sqlite"

_MAX_REPAIRS = 1  # matches phase-1-security-hardening's execute_with_repair default


class PipelineGraphState(TypedDict, total=False):
    """Graph state — a JSON-serializable bag mirroring every value threaded
    as an argument/return through app.orchestration.pipeline._answer_data /
    execute_with_repair today. `scope` is stored as a plain dict
    (dataclasses.asdict), not the auth.UserScope instance itself, for the
    same checkpoint-serialization reason app/orchestration/langgraph_followup.py's
    FollowupState already documents."""
    # inputs — mirror app.orchestration.pipeline._answer_data's signature exactly
    question: str
    scope: "dict | None"
    skip_scope_clarify: bool
    prior_resolved: "dict | None"
    village_hint: "str | None"
    is_followup: bool
    # working state, populated node by node
    schemes: list[str]
    scope_trace: dict
    entity_result: dict
    analysis: "dict | None"
    notes: list[str]
    sql: str
    rows: list[dict]
    attempt_count: int
    attempt_error: "str | None"           # None | "denied" | "repairable"
    attempt_error_text: "str | None"
    retrieved_for_membership_check: list[dict]
    answer: str
    result_findings: list[dict]
    result_chart_type: "str | None"
    restart: bool                         # True after a §5.4 pause resumes; routes back to 5.1
    # FRAME_GATES_ENABLED only (app/nlu/clarify_rules.py): the defaults node 5.1's
    # gates applied (e.g. top-N) and its rule trace, carried to node 5.3 where
    # they join entity_result["notes"] / ["assumptions"] with its own.
    gate_assumptions: list[str]
    gate_trace: list[str]
    denial: "dict | None"                 # auth.AuthDecision as a plain dict — see node_execute_attempt
    response: "dict | None"               # final response dict (success or denied)
    # Set by node_entities right before routing to node_entities_gate;
    # cleared by node_entities_gate once consumed. See node_entities_gate's
    # docstring for why this field, not a local variable, is what makes the
    # 2026-09-18 resume-doesn't-repeat-resolve_entities fix actually work.
    pending_clarification: "dict | None"


def _scope_obj(state: PipelineGraphState) -> "auth.UserScope | None":
    raw = state.get("scope")
    return auth.UserScope(**raw) if raw else None


def _pending_interrupt(snapshot) -> "Any | None":
    """The payload of a REAL pending `interrupt()` on this thread, or None.

    `snapshot.next` alone is NOT that test, and treating it as one caused a
    hard conversation lock-up. When a node raises a terminal (non-pause-
    eligible) `ClarificationNeeded` — `tranche-not-specified`,
    `column-not-held`, `pii-column-blocked`, `scheme-not-specified` — the
    exception propagates out of `astream`, but LangGraph has already
    checkpointed that node as a pending task, so `snapshot.next` stays
    non-empty forever with NO interrupt attached. `is_paused()` then reported
    the thread as paused, `app/api/routers/query.py` routed the NEXT turn into
    `resume_via_graph()`, and `Command(resume=...)` with nothing suspended to
    receive it just re-ran the same node against the same stale state —
    re-asking the identical clarification, turn after turn, with the user's
    answer discarded every time. Reported from the live UI 2026-09-21:
    choosing a tranche chip re-asked the tranche question in an endless loop.
    """
    for task in (snapshot.tasks or []):
        if task.interrupts:
            return task.interrupts[0].value
    return None


def _pause(e: "pipeline.ClarificationNeeded", question: str) -> dict:
    """Shared §5.4 pause handling for the two nodes (5.3, 5.6) that can raise
    a pause-eligible ClarificationNeeded. Re-raises anything not
    pause-eligible, exactly matching the bespoke mechanism's behavior for a
    terminal clarification (propagates out of the graph invocation, same as
    it propagates out of `_answer_data` today).

    On a pause, `interrupt()` durably suspends this exact node — LangGraph
    checkpoints the graph's real, structured state (schemes so far,
    entity_result so far, etc.), not just a bare question string the way
    app/orchestration/langgraph_followup.py's single opaque node does — until a reply
    resumes it. The reply is merged into `question` exactly as
    `_run_pipeline`'s existing resume logic does today, and the DATA chain
    restarts from node 5.1: a reply can change scheme/entity classification
    too, so a full restart with the merged question is correct, matching
    current bespoke behavior, not a shortcut or a regression from it.
    """
    if e.rule not in _PAUSE_ELIGIBLE_RULES:
        raise e
    # village_hint travels in the interrupt payload (not just the `update`
    # dict below) so a caller that discards this graph run entirely and
    # reconstructs a ClarificationNeeded from the payload alone — see
    # answer_data_via_graph_compat below — can still set
    # ConversationState.pending_village_hint exactly as the bespoke path
    # does. Added when wiring the compat adapter; harmless for the
    # in-graph resume path (resume_via_graph), which never reads this key.
    reply = interrupt({"question": e.question, "options": e.options, "rule": e.rule,
                       "village_hint": e.village_hint,
                       "resolved_so_far": e.resolved_so_far})
    merged = pipeline.merge_clarification_reply(question, reply, e.options)
    logger.info("pipeline_graph: resumed %r -> merged %r", e.rule, merged)
    update: dict[str, Any] = {"question": merged, "restart": True}
    if e.village_hint:
        update["village_hint"] = e.village_hint
    return update


# ── 5.1 Scope / scheme classifier ────────────────────────────────────────
async def node_scope_scheme(state: PipelineGraphState) -> dict:
    question = state["question"]
    unsupported = pipeline._unsupported_scheme_named(question)
    if unsupported:
        raise pipeline._unsupported_scheme_clarification(question, unsupported)
    # Scheme + top-N gates — the same shared helper _answer_data calls, so both
    # paths gate identically (frame-driven under FRAME_GATES_ENABLED).
    question, gate_assumptions, gate_trace = pipeline._gates_before_resolution(question)
    schemes, scope_meta = await pipeline._schemes_for_answer(question)
    scope_trace = {
        "schemes": schemes,
        "confidence": scope_meta.confidence,
        "source": scope_meta.source,
        "reason": scope_meta.reason,
        "is_followup": state.get("is_followup", False),
        "in_scope": True,
    }
    return {"question": question, "schemes": schemes, "scope_trace": scope_trace, "restart": False,
            "gate_assumptions": gate_assumptions, "gate_trace": gate_trace}


# ── 5.6 Entity resolver ──────────────────────────────────────────────────
async def node_entities(state: PipelineGraphState) -> dict:
    """Deliberately does NOT call interrupt() itself — see node_entities_gate
    below, the ONLY node re-executed on an entity-resolution resume.

    Found+fixed 2026-09-18: the original single-node version called the
    real (LLM/DB) resolve_entities() and interrupt() together, in this same
    node — LangGraph replays a paused node IN FULL on resume, so every
    resumed entity-ambiguous/scope-not-specified pause wasted a second real
    resolve_entities() call with the STALE, pre-merge question (which
    typically re-raises the identical ClarificationNeeded, silently
    discarded) before the real, merged-question attempt. Verified
    empirically via app/api/routers/query.py's real cross-request resume path
    (task 5.4) — the original test_pipeline_graph.py scenario 8/9 mocks
    didn't catch this because they don't check WHICH question text each
    call received, only that the call count reaches 2; updated alongside
    this fix to check question content directly. Same bug class, same fix
    shape, as app/orchestration/langgraph_followup.py's 2026-09-17 fix: split the
    expensive call into its own node, never re-entered on resume, and pass
    the pause payload through a real checkpointed state field instead of a
    local variable before interrupt().

    node_clarification_gate's own pauses (5.3) are deliberately NOT split
    the same way — its own pre-interrupt work (detect_region,
    _needs_scope/_year/_tranche_clarification, clarification_engine) is
    cheap, deterministic, no LLM/DB call, so replaying it on resume costs
    microseconds, not a wasted real request — not the failure mode this
    fix exists for.
    """
    try:
        entity_result = await pipeline._resolve_for_answer(
            state["question"], state["schemes"],
            prior_resolved=state.get("prior_resolved"),
            village_hint=state.get("village_hint"))
    except pipeline.ClarificationNeeded as e:
        if e.rule not in _PAUSE_ELIGIBLE_RULES:
            raise
        return {"pending_clarification": {
            "question": e.question, "options": e.options,
            "rule": e.rule, "village_hint": e.village_hint,
            "resolved_so_far": e.resolved_so_far,
        }}
    return {"entity_result": entity_result, "restart": False, "pending_clarification": None}


def _route_entities(state: PipelineGraphState) -> str:
    return "entities_gate" if state.get("pending_clarification") else "clarification_gate"


async def node_entities_gate(state: PipelineGraphState) -> dict:
    """The ONLY node re-executed on an entity-resolution resume — cheap on
    purpose (no resolve_entities call): reads the clarification payload
    node_entities already computed and returned (so it survived as a
    genuine checkpointed state field, unlike a local variable would have),
    then calls interrupt(). See node_entities' own docstring for the full
    reasoning."""
    pending = state["pending_clarification"]
    reply = interrupt({"question": pending["question"], "options": pending.get("options"),
                       "rule": pending["rule"], "village_hint": pending.get("village_hint"),
                       "resolved_so_far": pending.get("resolved_so_far")})
    merged = pipeline.merge_clarification_reply(state["question"], reply,
                                                pending.get("options"))
    logger.info("pipeline_graph: resumed %r -> merged %r", pending["rule"], merged)
    update: dict[str, Any] = {"question": merged, "restart": True, "pending_clarification": None}
    if pending.get("village_hint"):
        update["village_hint"] = pending["village_hint"]
    return update


# ── 5.3 Generic clarification gate (region expansion + scope/year/tranche) ─
async def node_clarification_gate(state: PipelineGraphState) -> dict:
    question = state["question"]
    schemes = state["schemes"]
    entity_result = state["entity_result"]
    try:
        if settings.CLARIFICATION_ENGINE_ENABLED:
            engine_clar = pipeline._engine_clarification(
                question, schemes, entity_result["resolved"])
            if engine_clar is not None:
                raise engine_clar

        if not entity_result["resolved"].get("district") and not entity_result["resolved"].get("district_list"):
            scheme0 = schemes[0] if schemes else ""
            region = pipeline.detect_region(question, scheme0)
            if region:
                want_all = region["expand"] or bool(pipeline._HAS_BREAKDOWN.search(question))
                if not want_all and not state.get("skip_scope_clarify"):
                    raise pipeline._region_clarification(question, region)
                entity_result["resolved"]["district_list"] = [d.upper() for d in region["districts"]]
                entity_result["resolved"]["district_list_region"] = region["canonical"]
                entity_result["display"]["district"] = region["canonical"]

        # Scope / year / tranche — the same shared helper _answer_data calls.
        question = pipeline._gates_after_resolution(
            question, schemes, entity_result,
            skip_scope_clarify=bool(state.get("skip_scope_clarify")),
            prior_resolved=state.get("prior_resolved"),
            pre_assumptions=state.get("gate_assumptions"), pre_trace=state.get("gate_trace"))
    except pipeline.ClarificationNeeded as e:
        return _pause(e, question)
    return {"entity_result": entity_result, "question": question, "restart": False}


# ── 5.2 Query analyzer (additive) ────────────────────────────────────────
async def node_query_analyzer(state: PipelineGraphState) -> dict:
    analysis = None
    if settings.QUERY_ANALYZER_ENABLED:
        try:
            analysis = await pipeline.query_analyzer.analyze_query(
                state["question"], state["schemes"], state["entity_result"])
        except Exception:  # noqa: BLE001
            logger.warning("query analyzer failed — continuing without it", exc_info=True)
    return {"analysis": analysis}


# ── 5.10 SQL generation ──────────────────────────────────────────────────
async def node_sql_generate(state: PipelineGraphState) -> dict:
    with pipeline.request_trace.stage("sql_generation"):
        sql = await pipeline.generate_sql(state["question"], state["schemes"], state["entity_result"])
    return {"sql": sql, "attempt_count": 0}


# ── 5.8 / 5.9 Schema retrieval + join discovery — wrapped as-is ─────────
async def node_schema_retrieve(state: PipelineGraphState) -> dict:
    retrieved = await pipeline.schema_retrieval.retrieve(state["question"], state["schemes"])
    return {"retrieved_for_membership_check": retrieved}


# ── 5.7 auth + 5.9 join check + 5.11 validation + 5.12 execution, one attempt ─
async def node_execute_attempt(state: PipelineGraphState) -> dict:
    sql = pipeline._uppercase_geo_literals(state["sql"])
    scope = _scope_obj(state)
    try:
        new_sql, rows = await pipeline._execute_one_attempt(
            sql, state["question"], state["schemes"], state["entity_result"],
            scope, state["retrieved_for_membership_check"])
        return {"sql": new_sql, "rows": rows, "attempt_error": None}
    except pipeline.SQLAuthorizationDenied as e:
        # Stored as a plain dict, not the auth.AuthDecision dataclass instance
        # — the checkpointer's serializer falls back to a pickle/msgpack-
        # extension path for an unregistered class, which it explicitly
        # warns "will be blocked in a future version" (same reasoning
        # app/orchestration/langgraph_followup.py already documents for UserScope).
        return {"attempt_error": "denied", "denial": dataclasses.asdict(e.decision)}
    except pipeline.ClarificationNeeded:
        raise  # PII / pseudo-scheme refusal — terminal, never repaired
    except Exception as e:  # noqa: BLE001 — matches execute_with_repair's own broad catch
        attempt = state.get("attempt_count", 0)
        if attempt >= _MAX_REPAIRS:
            raise  # repair budget spent — propagate exactly as execute_with_repair does
        logger.warning("pipeline_graph: SQL failed (attempt %d/%d), repairing: %s",
                       attempt + 1, _MAX_REPAIRS + 1, e)
        return {"attempt_error": "repairable", "attempt_error_text": str(e), "sql": sql}


def _route_after_attempt(state: PipelineGraphState) -> str:
    err = state.get("attempt_error")
    if err is None:
        return "done"
    if err == "denied":
        return "denied"
    return "repair"


# ── SQL repair regeneration (part of 5.10) ───────────────────────────────
async def node_repair(state: PipelineGraphState) -> dict:
    pipeline.request_trace.incr("repairs")
    pipeline.request_trace.append("repair_errors", (state.get("attempt_error_text") or "")[:300])
    repair_prompt = pipeline.prompt_builder.build_repair_prompt(
        state["question"], state["schemes"], state["entity_result"],
        failed_sql=state["sql"], error=state.get("attempt_error_text") or "",
        extra_hint=pipeline._repair_hint(state.get("attempt_error_text") or ""))
    raw = await pipeline.llm.call_sql_generator(
        repair_prompt, guided={"guided_regex": pipeline._SQL_SHAPE_REGEX})
    new_sql = pipeline._extract_sql(raw)
    return {"sql": new_sql, "attempt_count": state.get("attempt_count", 0) + 1}


# ── denied exit ───────────────────────────────────────────────────────────
async def node_denied(state: PipelineGraphState) -> dict:
    decision = auth.AuthDecision(**state["denial"])
    response = pipeline._denied(decision, state["schemes"], state["entity_result"]["resolved"])
    return {"response": response}


# ── 5.5 defaults + premise check — positioned post-execution, matching
#     _answer_data's real ordering (see tasks.md tasks 2.5 / 4.1) ─────────
async def node_defaults_premise(state: PipelineGraphState) -> dict:
    notes = list(state["entity_result"].get("notes") or [])
    if settings.PREMISE_CHECK_ENABLED:
        try:
            notes.extend(pipeline.premise_check.check_premises(state["question"], state["rows"]))
        except Exception:  # noqa: BLE001
            logger.warning("premise check failed — continuing without it", exc_info=True)
    if settings.DEFAULTS_ENGINE_ENABLED:
        try:
            notes.extend(pipeline.defaults_engine.apply_defaults(
                state["question"], state["schemes"], state["entity_result"]["resolved"]))
        except Exception:  # noqa: BLE001
            logger.warning("defaults engine failed — continuing without it", exc_info=True)
    analysis = state.get("analysis")
    if analysis:
        for amb in analysis.get("ambiguous") or []:
            if amb.get("origin") == "llm" and amb.get("term"):
                notes.append(
                    f"'{amb['term']}' may be ambiguous — "
                    f"{amb.get('why') or 'consider stating it more specifically'}.")
    return {"notes": notes}


# ── 5.15 Response composer ───────────────────────────────────────────────
# Found+fixed 2026-09-18: this node used to run BEFORE node_findings (see
# the edge order below, also fixed) — matching app.orchestration.pipeline._answer_data's
# own pre-fix ordering exactly, until that ordering changed there so
# compose_response could take findings as an input, per the GT proposal's
# §5.15 spec. Moving findings ahead of compose here too, not just in the
# bespoke path, is what keeps this graph's own field-for-field parity
# claim (tests/unit/test_pipeline_graph.py's scenario 1) actually true — the
# two paths would otherwise silently diverge on this one behavior, a gap
# the existing tests couldn't catch because they mock compose_response
# entirely (so a prompt-shape difference between the two callers is
# invisible to them).
async def node_compose(state: PipelineGraphState) -> dict:
    with pipeline.request_trace.stage("compose"):
        answer = await pipeline.compose_response(
            state["question"], state["sql"], state["rows"], notes=state.get("notes"),
            entities=state["entity_result"].get("display"), schemes=state["schemes"],
            result_findings=state.get("result_findings"))
    return {"answer": answer}


# ── 5.13 Generic result findings ─────────────────────────────────────────
async def node_findings(state: PipelineGraphState) -> dict:
    result_findings: list[dict] = []
    if settings.FINDINGS_ENABLED:
        try:
            result_findings = pipeline.findings.evaluate(
                state["question"], state["schemes"], state["rows"], state["entity_result"]["resolved"])
        except Exception:  # noqa: BLE001
            logger.warning("findings evaluation failed — continuing without it", exc_info=True)
    return {"result_findings": result_findings}


# ── 5.14 Chart generator ─────────────────────────────────────────────────
async def node_chart(state: PipelineGraphState) -> dict:
    result_chart_type = None
    if settings.CHART_SPEC_ENABLED:
        try:
            result_chart_type = pipeline.chart_spec.select_chart_type(state["rows"][:200], state["question"])
        except Exception:  # noqa: BLE001
            logger.warning("chart_spec selection failed — continuing without it", exc_info=True)
    return {"result_chart_type": result_chart_type}


# ── final assembly — identical shape to app.orchestration.pipeline._answer_data's return ─
async def node_assemble(state: PipelineGraphState) -> dict:
    rows = state["rows"]
    response = {
        "route": "data",
        "intent": "DATA",
        "confidence": "high" if rows else "low",
        "schemes": state["schemes"],
        "scope": state["scope_trace"],
        "resolved_entities": state["entity_result"]["resolved"],
        "sql": state["sql"],
        "sql_query": state["sql"],
        "row_count": len(rows),
        "rows": rows[:20],
        "data": rows[:200],
        "answer": state["answer"],
        "findings": state["result_findings"],
        "chart_type": state["result_chart_type"],
        "analysis": state.get("analysis"),
        # Same condition and shape as _answer_data's return (field-for-field parity).
        **({"assumptions": state["entity_result"].get("assumptions") or [],
            "gate_trace": state["entity_result"].get("gate_trace") or []}
           if pipeline._gate_frame() is not None else {}),
    }
    return {"response": response}


def _route_restart(next_node: str):
    """A pause-eligible ClarificationNeeded sets `restart` and routes back to
    node 5.1; otherwise proceed to `next_node`."""
    def _router(state: PipelineGraphState) -> str:
        return "restart" if state.get("restart") else next_node
    return _router


def build_graph() -> StateGraph:
    graph = StateGraph(PipelineGraphState)
    graph.add_node("scope_scheme", node_scope_scheme)
    graph.add_node("entities", node_entities)
    graph.add_node("entities_gate", node_entities_gate)
    graph.add_node("clarification_gate", node_clarification_gate)
    graph.add_node("query_analyzer", node_query_analyzer)
    graph.add_node("sql_generate", node_sql_generate)
    graph.add_node("schema_retrieve", node_schema_retrieve)
    graph.add_node("execute_attempt", node_execute_attempt)
    graph.add_node("repair", node_repair)
    graph.add_node("denied", node_denied)
    graph.add_node("defaults_premise", node_defaults_premise)
    graph.add_node("compose", node_compose)
    graph.add_node("findings", node_findings)
    graph.add_node("chart", node_chart)
    graph.add_node("assemble", node_assemble)

    graph.set_entry_point("scope_scheme")
    graph.add_edge("scope_scheme", "entities")
    graph.add_conditional_edges(
        "entities", _route_entities,
        {"entities_gate": "entities_gate", "clarification_gate": "clarification_gate"})
    graph.add_edge("entities_gate", "scope_scheme")
    graph.add_conditional_edges(
        "clarification_gate", _route_restart("query_analyzer"),
        {"restart": "scope_scheme", "query_analyzer": "query_analyzer"})
    graph.add_edge("query_analyzer", "sql_generate")
    graph.add_edge("sql_generate", "schema_retrieve")
    graph.add_edge("schema_retrieve", "execute_attempt")
    graph.add_conditional_edges(
        "execute_attempt", _route_after_attempt,
        {"done": "defaults_premise", "denied": "denied", "repair": "repair"})
    graph.add_edge("repair", "execute_attempt")
    graph.add_edge("denied", END)
    graph.add_edge("defaults_premise", "findings")
    graph.add_edge("findings", "compose")
    graph.add_edge("compose", "chart")
    graph.add_edge("chart", "assemble")
    graph.add_edge("assemble", END)
    return graph


def _checkpointer_context():
    """A fresh checkpointer context manager, backend selected by
    `settings.PIPELINE_GRAPH_CHECKPOINTER_DSN`. Same "each caller gets its
    own connection, only the durable store is shared" posture either way —
    a pause raised by one call and resumed by a later, independent call
    only share the SQLite file or the Postgres database, never in-process
    memory. Empty DSN (default) => AsyncSqliteSaver, matching
    app/orchestration/langgraph_followup.py's own default; a `postgresql://` DSN =>
    AsyncPostgresSaver, the production-shape backend design.md calls for."""
    dsn = settings.PIPELINE_GRAPH_CHECKPOINTER_DSN
    if dsn:
        if AsyncPostgresSaver is None:
            raise RuntimeError(
                "PIPELINE_GRAPH_CHECKPOINTER_DSN is set but langgraph-checkpoint-postgres "
                "is not installed — pip install langgraph-checkpoint-postgres psycopg[binary]")
        return AsyncPostgresSaver.from_conn_string(dsn)
    _CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(_CHECKPOINT_DB_PATH))


async def _ensure_checkpointer_ready(checkpointer) -> None:
    """AsyncPostgresSaver requires an explicit `setup()` to create its
    checkpoint tables (idempotent — `CREATE TABLE IF NOT EXISTS` under the
    hood, safe to call on every connection); AsyncSqliteSaver has no such
    requirement (app/orchestration/langgraph_followup.py's own working code never calls
    it), so this is a no-op there."""
    if AsyncPostgresSaver is not None and isinstance(checkpointer, AsyncPostgresSaver):
        await checkpointer.setup()


async def answer_data_via_graph(
    question: str, *, scope: "auth.UserScope | None" = None,
    skip_scope_clarify: bool = False, prior_resolved: "dict | None" = None,
    village_hint: "str | None" = None, is_followup: bool = False,
    thread_id: "str | None" = None,
) -> dict:
    """Graph-based equivalent of app.orchestration.pipeline._answer_data — same contract:
    returns the response dict on success/denial, or raises ClarificationNeeded
    for a non-resumable pause. Returns {"paused": True, "clarification": {...},
    "thread_id": ...} for a resumable pause instead of raising — call
    resume_via_graph(thread_id, reply) to continue it. `thread_id` defaults to
    a fresh id per call (no cross-call resumability) when not supplied."""
    tid = thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": tid}}
    graph_def = build_graph()
    async with _checkpointer_context() as checkpointer:
        await _ensure_checkpointer_ready(checkpointer)
        graph = graph_def.compile(checkpointer=checkpointer)
        initial = PipelineGraphState(
            question=question,
            scope=dataclasses.asdict(scope) if scope else None,
            skip_scope_clarify=skip_scope_clarify,
            prior_resolved=prior_resolved,
            village_hint=village_hint,
            is_followup=is_followup,
        )
        final_state: dict[str, Any] = {}
        try:
            async for event in graph.astream(initial, config=config, stream_mode="values"):
                final_state = event
        except BaseException:
            # A node raised (a terminal ClarificationNeeded, or any real
            # error). LangGraph has already checkpointed that node as a
            # PENDING task with no interrupt attached, so this thread would
            # otherwise look "paused" forever and hijack every later turn in
            # the session into resume_via_graph — see _pending_interrupt.
            # Drop the dead thread so the next turn starts clean. Best-effort:
            # a cleanup failure must never mask the original exception.
            try:
                await checkpointer.adelete_thread(tid)
            except Exception:  # noqa: BLE001
                logger.warning("pipeline_graph: could not clear errored thread %s", tid,
                               exc_info=True)
            raise
        snapshot = await graph.aget_state(config)
        payload = _pending_interrupt(snapshot)
        if payload is not None:
            return {"paused": True, "clarification": payload, "thread_id": tid}
        return final_state.get("response") or {}


async def resume_via_graph(thread_id: str, reply: str) -> dict:
    """Resume a pause previously returned by answer_data_via_graph as
    {"paused": True, ...} — same thread_id, the user's reply text."""
    config = {"configurable": {"thread_id": thread_id}}
    graph_def = build_graph()
    async with _checkpointer_context() as checkpointer:
        await _ensure_checkpointer_ready(checkpointer)
        graph = graph_def.compile(checkpointer=checkpointer)
        final_state: dict[str, Any] = {}
        try:
            async for event in graph.astream(Command(resume=reply), config=config,
                                             stream_mode="values"):
                final_state = event
        except BaseException:
            # Same dead-thread cleanup as answer_data_via_graph — a resumed
            # turn can raise a TERMINAL clarification too (e.g. the tranche
            # gate firing once scope/year are finally settled), and leaving
            # that thread pending is what locked the conversation into
            # re-asking the same question forever.
            try:
                await checkpointer.adelete_thread(thread_id)
            except Exception:  # noqa: BLE001
                logger.warning("pipeline_graph: could not clear errored thread %s", thread_id,
                               exc_info=True)
            raise
        snapshot = await graph.aget_state(config)
        payload = _pending_interrupt(snapshot)
        if payload is not None:
            return {"paused": True, "clarification": payload, "thread_id": thread_id}
        response = final_state.get("response") or {}
        # Surface the merged question (`"<paused question>, <reply>"`, built by
        # _pause/node_entities_gate) the same way _run_pipeline sets
        # `rewritten_question` on the bespoke path. app/api/routers/query.py's
        # resume branch bypasses _run_pipeline entirely, so without this the
        # resumed turn would record the bare reply ("West Garo Hills") as its
        # standalone question — leaving the next turn's follow-up rewrite and
        # context_manager.update_state with a fragment instead of the real
        # question. Deliberately set only here, NOT in node_assemble: the
        # non-resume entry points (answer_data_via_graph/_compat) must keep
        # field-for-field parity with _answer_data's return dict, which omits
        # this key when the question was never rewritten.
        merged = final_state.get("question")
        if response and merged:
            response.setdefault("rewritten_question", merged)
        return response


async def answer_data_via_graph_compat(
    question: str, scope: "auth.UserScope | None" = None,
    skip_scope_clarify: bool = False, prior_resolved: "dict | None" = None,
    village_hint: "str | None" = None, is_followup: bool = False,
    thread_id: "str | None" = None,
) -> dict:
    """openspec/changes/multi-tenant-rls-scheme-scaleout — the actual
    production cutover point: a drop-in replacement for
    app.orchestration.pipeline._answer_data with the EXACT SAME calling contract (same
    positional/keyword signature, raises ClarificationNeeded for a pause,
    returns a plain response dict otherwise), so app.orchestration.pipeline._run_pipeline
    (the ~3600-line router of edge-case/RAG/scheme-listing/DATA-route
    decisions this module intentionally does NOT reimplement — only the
    DATA route's own §5.1-5.15 chain is a graph) needs exactly ONE call
    swapped, behind settings.PIPELINE_GRAPH_ENABLED, and nothing else in
    app/orchestration/pipeline.py, app/api/routers/query.py, or app/conversation/session_store.py changes.

    **Update (2026-09-18, task 5.4): `thread_id` now supports real
    cross-request resume.** Default (`None`) is the original, still-default
    behavior this docstring described until now: a fresh, throwaway
    thread_id per call, a pause converted straight to `ClarificationNeeded`
    and its checkpoint deleted (see `_delete_orphaned_thread` below) —
    correct when nothing durable is tracking this thread (e.g. called
    standalone, or under `LANGGRAPH_FOLLOWUP_ENABLED`, which already owns
    pause/resume for the whole pipeline via its OWN separate checkpointer
    — see the mutual-exclusivity note at this function's call site in
    `app/orchestration/pipeline.py::_run_pipeline`, deliberately never both active for
    the same call). When the caller passes a real `thread_id` (in
    practice, the session_id — `app/api/routers/query.py` reuses it exactly
    like `app/orchestration/langgraph_followup.py` already does for its own
    checkpointer), a pause's checkpoint is deliberately left alive instead
    of cleaned up, and the raised `ClarificationNeeded` carries
    `graph_resumable=True` so `query.py`'s handler knows NOT to also set
    the bespoke `pending_scope_q`/`pending_village_hint` resume signal —
    this pause's resume state now lives durably in the graph's own
    checkpointer, checked via `is_paused()` below and continued via
    `resume_via_graph()` on the next request for the same thread_id.
    """
    result = await answer_data_via_graph(
        question, scope=scope, skip_scope_clarify=skip_scope_clarify,
        prior_resolved=prior_resolved, village_hint=village_hint, is_followup=is_followup,
        thread_id=thread_id,
    )
    if result.get("paused"):
        clar = result["clarification"]
        if thread_id is not None:
            # Real resume requested — keep the checkpoint alive; query.py's
            # is_paused()/resume_via_graph() continue it next turn.
            raise pipeline.ClarificationNeeded(
                clar["question"], options=clar.get("options"), rule=clar.get("rule"),
                village_hint=clar.get("village_hint"), graph_resumable=True,
                resolved_so_far=clar.get("resolved_so_far"),
            )
        # Found and fixed 2026-09-17: this adapter deliberately never
        # resumes via LangGraph's own checkpointer (see this function's
        # docstring) — every pause here gets a fresh, throwaway thread_id
        # and is immediately converted back into a ClarificationNeeded
        # raise. That means the checkpoint this pause just wrote is
        # guaranteed dead the moment we raise below — nothing will ever
        # call resume_via_graph with this thread_id. Left alone, that was
        # a permanent, never-cleaned-up row in the checkpoint store (the
        # SQLite file or the configured Postgres DSN) for every single
        # clarification any user ever hit — unbounded growth with zero
        # eviction path. Delete it now instead.
        await _delete_orphaned_thread(result["thread_id"])
        raise pipeline.ClarificationNeeded(
            clar["question"], options=clar.get("options"), rule=clar.get("rule"),
            village_hint=clar.get("village_hint"),
            resolved_so_far=clar.get("resolved_so_far"),
        )
    return result


async def is_paused(thread_id: str) -> bool:
    """True if `thread_id`'s graph is currently suspended at an interrupt()
    — mirrors app.orchestration.langgraph_followup.is_paused exactly (same shape, same
    reasoning: checked against this graph's own checkpointer, independent
    of ConversationState.pending_scope_q, which a real-resume pause here
    deliberately never sets — see answer_data_via_graph_compat's
    `graph_resumable` note above)."""
    config = {"configurable": {"thread_id": thread_id}}
    async with _checkpointer_context() as checkpointer:
        await _ensure_checkpointer_ready(checkpointer)
        graph = build_graph().compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        return _pending_interrupt(snapshot) is not None


async def should_resume(thread_id: str, reply: str) -> bool:
    """True when `thread_id` is genuinely suspended at an `interrupt()` AND
    `reply` is actually an answer to the question it paused on.

    Replaces a bare `is_paused()` check at app/api/routers/query.py's resume
    branch. Two distinct things that check got wrong:

    1. A thread left PENDING by a node that raised (a terminal
       ClarificationNeeded) is not paused at all — see `_pending_interrupt`.
    2. Even on a real pause, the user may ignore the question: "thanks", or a
       brand-new question of their own. `_run_pipeline`'s bespoke resume drops
       the pause in that case and handles the reply as a fresh turn; this
       branch resumed unconditionally and glued the new question onto the old
       one. See pipeline.reply_abandons_clarification.

    On False the dead/abandoned thread is cleared, so the caller can simply
    fall through to the normal answer_question path.
    """
    config = {"configurable": {"thread_id": thread_id}}
    async with _checkpointer_context() as checkpointer:
        await _ensure_checkpointer_ready(checkpointer)
        graph = build_graph().compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        if _pending_interrupt(snapshot) is None:
            return False
        paused_q = (snapshot.values or {}).get("question") or ""
    if pipeline.reply_abandons_clarification(paused_q, reply):
        logger.info("pipeline_graph: reply %r abandons the pause on %r — dropping thread",
                    reply, paused_q)
        await _delete_orphaned_thread(thread_id)
        return False
    return True


async def _delete_orphaned_thread(thread_id: str) -> None:
    """Best-effort cleanup for a thread answer_data_via_graph_compat knows
    will never be resumed — see its call site above. Never raises: a
    failure to clean up an orphan is worse than nothing (leaves the row)
    but must not turn a successful clarification into a 500."""
    try:
        async with _checkpointer_context() as checkpointer:
            await checkpointer.adelete_thread(thread_id)
    except Exception:  # noqa: BLE001
        logger.warning("pipeline_graph: failed to delete orphaned checkpoint "
                       "thread %s (non-fatal, row leaked)", thread_id, exc_info=True)
