"""
app/orchestration/langgraph_followup.py — the actual LangGraph `interrupt()` + checkpointer
component the Grant Thornton proposal names for node 5.4 (Follow-up emitter):

    "Purpose. Surfaces the clarification question to the user and pauses
    the graph until the user replies. When the reply arrives, the answer
    is merged back into the analysis and the gate is re-evaluated. If
    another piece is still missing, the gate asks again; eventually it is
    satisfied and the pipeline proceeds.
    Tools. LangGraph's interrupt() primitive with a checkpointer (Redis
    for speed and simplicity, Postgres for queryable history)."

`phase-2-orchestration-durability/design.md` recorded a decision NOT to
adopt LangGraph, reasoning that this deployment's 2-VM/4-worker scale
didn't justify it and that the existing bespoke ClarificationNeeded +
ConversationState mechanism (see app/conversation/session_store.py, app/orchestration/pipeline.py)
already closes the durability gap that decision was actually about.
**That decision is superseded for this module only, by explicit
instruction (2026-09-13): "ignore infra just implement the component."**
This is a genuine, working `interrupt()`/checkpointer implementation, not
a stub — it does not replace the bespoke mechanism (still the pipeline's
own default path; see app/api/routers/query.py), it is an alternative,
opt-in pause/resume path exercising the exact primitives the proposal
names, wired in at `run_with_pause` below.

Checkpointer backend: `AsyncSqliteSaver`, not Redis/Postgres as the
proposal names — chosen because it needs zero external infrastructure
(a local file, no server to run) per the "ignore infra" instruction,
while still being a REAL, persistent checkpointer, not an in-memory
stand-in — a graph paused via one process/connection can be resumed via
an entirely separate one pointed at the same file (proven in
tests/unit/test_langgraph_followup.py by using two independently-constructed
checkpointer instances, simulating a process restart). LangGraph's
checkpointer interface is pluggable — swapping in
`langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` later is a
one-line change to `_build_checkpointer` below, not a graph rewrite.
(Attempted here first: blocked in this environment by `psycopg`'s
native `libpq` dependency not being installed — an infra concern this
module was explicitly told to ignore, not a design limitation.)

Scope: this graph wraps the EXISTING pipeline (`app.orchestration.pipeline.
answer_question`) for exactly the pause-eligible clarification rules
`app/api/routers/query.py` already recognizes (the shared
`pipeline.RESUMABLE_CLARIFICATION_RULES`) — it does not reimplement
scope/year/entity resolution, SQL generation, or any other pipeline
stage as graph nodes. Turning the entire ~3,600-line pipeline into a
LangGraph graph is a much larger, separate undertaking this instruction
did not ask for ("implement the component", not "migrate the
pipeline") and this module does not attempt it.
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from app.orchestration import pipeline
from app.core.auth import UserScope
from app.orchestration.pipeline import ClarificationNeeded
from app.conversation.session_store import session_store

logger = logging.getLogger(__name__)

# The rules app/api/routers/query.py already treats as resumable
# (it stashes session.pending_scope_q/pending_village_hint for exactly
# these) — every other ClarificationNeeded rule (e.g. "column-not-held"
# from app/nlu/clarification_engine.py, "pii-column-blocked") is a terminal
# refusal, not a pause: re-raised, never interrupted.
_PAUSE_ELIGIBLE_RULES = pipeline.RESUMABLE_CLARIFICATION_RULES

# Where the SQLite checkpoint file lives — a sibling of the JSONL audit
# mirror, same "durable local file, no server" posture.
_CHECKPOINT_DB_PATH = Path(__file__).resolve().parents[2] / "logs" / "langgraph_followup_checkpoints.sqlite"


class FollowupState(TypedDict, total=False):
    """Graph state — deliberately a plain, JSON-serializable bag (session_id,
    question text, `UserScope` as a plain dict, and the final result), not a
    live Session object or an arbitrary class instance. `scope` is stored via
    `dataclasses.asdict` / rebuilt via `UserScope(**...)` rather than passed
    through as the dataclass instance itself — LangGraph's checkpoint
    serializer falls back to a msgpack-extension/pickle path for an
    unregistered class, which it explicitly warns "will be blocked in a
    future version"; a plain dict needs no such fallback and survives a
    LangGraph version upgrade that tightens this. The live, in-process
    Session is re-acquired inside the node on every invocation (including on
    resume) via `session_store.ensure`, which already rehydrates from the
    durable conversation_store mirror when this is a fresh in-process
    session — see phase-2-orchestration-durability. This graph's own
    checkpointer is responsible only for *this pause's* resumption context
    (which question is being asked, which reply resumes it), not for
    re-deriving the whole conversation history, which is Phase 1's job,
    reused here rather than duplicated.
    """
    question: str
    session_id: str
    scope: dict
    result: dict | None
    # Set by _classify_node right before routing to _gate_node; cleared by
    # _gate_node once consumed. See _gate_node's docstring for why this
    # field — not a local variable — is what makes the resume-doesn't-
    # repeat-expensive-work fix below actually work.
    pending_clarification: dict | None


async def _classify_node(state: FollowupState) -> dict[str, Any]:
    """Runs the existing pipeline. Deliberately does NOT call interrupt()
    itself — see _gate_node's docstring for why splitting this from the
    pause into two nodes matters. On success, returns the result; on a
    pause-eligible ClarificationNeeded, returns the clarification payload
    via `pending_clarification` (a real node return, so it IS checkpointed)
    instead of pausing here, and routes to _gate_node next.

    Found and fixed 2026-09-17: the original single-node version called
    interrupt() itself, right after this same pipeline call, in the same
    node. LangGraph's interrupt()/replay model re-executes a node IN FULL
    from its top on every resume — so every resumed clarification was
    silently re-running this exact (real LLM/DB) pipeline call a second,
    wasted time with the ORIGINAL unmerged question (re-raising the
    identical ClarificationNeeded, immediately discarded) before the real,
    merged-question attempt happened as a third call. Verified empirically
    with a call-counting instrumentation: one pause + one resume produced
    3 calls to pipeline.answer_question for 2 logical attempts. Splitting
    the expensive call (this node, never re-entered on resume — only
    _gate_node is) from the interrupt() call (below) eliminates the
    duplicate entirely; tests/unit/test_langgraph_followup.py now asserts the
    call count directly so this can't silently regress."""
    scope = UserScope(**state["scope"])
    session = session_store.ensure(state["session_id"], scope.user_id)
    session.scope = scope
    try:
        result = await pipeline.answer_question(
            state["question"], session=session, scope=scope)
    except ClarificationNeeded as e:
        if e.rule not in _PAUSE_ELIGIBLE_RULES:
            # Not resumable — a terminal refusal (e.g. "the data cannot
            # answer this at all"). Propagate exactly as the bespoke path
            # does; this graph makes no pause/resume claim for these.
            raise
        return {
            "pending_clarification": {
                "question": e.question, "options": e.options,
                "rule": e.rule, "village_hint": e.village_hint,
            },
            "result": None,
        }
    # Clear pending_village_hint on every successful pipeline call, not just
    # when this turn itself set it. pipeline._run_pipeline's own top-of-function
    # clearing (session_store.py's ConversationState / pipeline.py:3725-3729)
    # only fires when pending_scope_q is also set — which this graph
    # deliberately never sets (see this module's docstring) — so without this,
    # a village_hint set on one entity-ambiguous pause would silently leak
    # into every later turn on the same session once this component is wired
    # into a real request path, rather than being a one-shot resume signal.
    if session.state.pending_village_hint is not None:
        session.state.pending_village_hint = None
    return {"result": result, "pending_clarification": None}


async def _gate_node(state: FollowupState) -> dict[str, Any]:
    """The ONLY node that re-executes on resume — cheap on purpose (no
    pipeline call, no LLM/DB work): reads the clarification payload
    _classify_node already computed and returned (so it survived as a
    genuine checkpointed state field, unlike a local variable would have),
    then calls interrupt(). On the pausing pass this suspends here; on
    resume, LangGraph re-enters _gate_node (not _classify_node) from the
    top with that same `pending_clarification` already in state —
    interrupt() at this call site returns the reply immediately instead of
    pausing again, with zero re-execution of _classify_node's pipeline
    call. This is the actual fix: interrupt() must live in a node that has
    nothing expensive before it, not bundled into the node that does the
    expensive work, precisely because LangGraph replays a paused node in
    full on every resume."""
    pending = state["pending_clarification"]
    scope = UserScope(**state["scope"])
    session = session_store.ensure(state["session_id"], scope.user_id)
    if pending.get("village_hint"):
        # Reuses ConversationState.pending_village_hint purely as a narrow
        # data-passing channel to the next _classify_node attempt —
        # app/orchestration/pipeline.py's own resume logic already reads this field
        # unconditionally. This graph does NOT use
        # ConversationState.pending_scope_q: LangGraph's checkpointer (via
        # `question` in this state) is what tracks that a pause is in
        # progress, not that bespoke field.
        session.state.pending_village_hint = pending["village_hint"]
    reply = interrupt({"question": pending["question"], "options": pending["options"],
                       "rule": pending["rule"]})
    # pipeline.merge_clarification_reply, not a bare f-string: a one-tap chip
    # sends the WHOLE rewritten question, so concatenating it onto the paused
    # one duplicates it (see that function's docstring — app/orchestration/pipeline_graph.py's
    # two resume points were already converted; this one was missed). Passing
    # the options we offered also catches a chip that rewrites the MIDDLE of
    # the question rather than appending to it (the financial-year chips).
    merged = pipeline.merge_clarification_reply(
        state["question"], reply, pending.get("options"))
    logger.info("langgraph_followup: resumed %r -> merged %r", pending["rule"], merged)
    return {"question": merged, "result": None, "pending_clarification": None}


def _route_after_classify(state: FollowupState) -> str:
    """'gate' when _classify_node just returned a clarification payload
    (needs a pause); 'done' once a real result exists."""
    return "gate" if state.get("pending_clarification") is not None else "done"


def _build_graph():
    graph = StateGraph(FollowupState)
    graph.add_node("classify", _classify_node)
    graph.add_node("gate", _gate_node)
    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify", _route_after_classify, {"gate": "gate", "done": END})
    # After a resume merges the reply, go straight back to classify for the
    # real attempt — "the gate is re-evaluated... if another piece is
    # still missing, the gate asks again" (proposal's own wording); a
    # second missing piece routes classify -> gate again, same as before.
    graph.add_edge("gate", "classify")
    return graph


def _checkpointer_context():
    """A fresh AsyncSqliteSaver context manager over the shared checkpoint
    file. Callers use `async with _checkpointer_context() as cp:` so each
    call gets its own connection — proves the checkpoint is read from disk,
    not a shared in-process object, matching how a real interrupted request
    (this call) and its later resume (a different request, possibly a
    different worker) would only share the file, not memory."""
    _CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(_CHECKPOINT_DB_PATH))


async def is_paused(session_id: str) -> bool:
    """True if `session_id`'s thread is currently suspended at an interrupt()
    (i.e. a prior `run_with_pause(resume=None)` call paused and no resume has
    completed it yet). A caller wiring this component into a live request
    path uses this to decide whether an incoming message is a fresh question
    (`resume=None`) or a reply to an outstanding pause (`resume=<message>`) —
    deliberately checked against this graph's own checkpointer, not against
    `ConversationState.pending_scope_q`, which this component never sets
    (see `_run_pipeline_node`'s docstring): the two mechanisms track pause
    state independently, on purpose, so enabling this component cannot
    corrupt the bespoke mechanism's own resume logic if a session somehow
    carries state for both."""
    config = {"configurable": {"thread_id": session_id}}
    async with _checkpointer_context() as checkpointer:
        graph = _build_graph().compile(checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        return bool(snapshot.next)


async def run_with_pause(
    *, session_id: str, question: str, scope: UserScope, resume: str | None = None,
) -> dict[str, Any]:
    """Public entry point. Two ways to call this:

    - `resume=None`: start (or continue an un-paused) turn with `question`.
    - `resume=<user's reply text>`: resume a pause previously raised for
      this exact `session_id` — `question` is ignored in this case (the
      graph already has the paused question in its checkpointed state).

    Returns either `{"paused": True, "clarification": {...}}` (the graph
    hit a pause-eligible ClarificationNeeded and is now durably suspended
    — call this function again with `resume=` to continue) or the
    pipeline's normal result dict (the turn completed, possibly after one
    or more pause/resume rounds).
    """
    graph_def = _build_graph()
    config = {"configurable": {"thread_id": session_id}}
    async with _checkpointer_context() as checkpointer:
        graph = graph_def.compile(checkpointer=checkpointer)
        if resume is not None:
            stream_input = Command(resume=resume)
        else:
            stream_input = FollowupState(
                question=question, session_id=session_id, scope=dataclasses.asdict(scope),
                result=None, pending_clarification=None)
        final_state: dict[str, Any] = {}
        async for event in graph.astream(stream_input, config=config, stream_mode="values"):
            final_state = event
        # A node that calls interrupt() suspends without raising — astream
        # simply stops yielding for it, no exception reaches here. A node
        # that raises an ordinary exception (the non-pause-eligible
        # ClarificationNeeded case, re-raised above) propagates it straight
        # out of `graph.astream` instead — this line is never reached for
        # that case, confirmed in tests/unit/test_langgraph_followup.py's
        # "non-pause-eligible rule propagates" check. So reaching here at
        # all already means either a clean finish or a genuine interrupt;
        # `aget_state` + a non-empty `tasks[i].interrupts` is how LangGraph
        # documents distinguishing the latter.
        snapshot = await graph.aget_state(config)
        if snapshot.next:  # non-empty means the graph is paused, not finished
            payload = snapshot.tasks[0].interrupts[0].value
            return {"paused": True, "clarification": payload}
        return final_state.get("result") or {}
