"""
LangGraph interrupt()/checkpointer follow-up emitter (app/langgraph_
followup.py) — the actual component the Grant Thornton proposal names for
node 5.4 ("LangGraph's interrupt() primitive with a checkpointer"), built
per explicit instruction (2026-09-13) overriding phase-2-orchestration-
durability/design.md's earlier decision not to adopt LangGraph.

Monkeypatches `app.pipeline.answer_question` — no DB, no model gateway,
same stance as every other test in this directory:
`python tests/test_langgraph_followup.py`, exit code 0 = all pass.

Covers:
(a) a pause-eligible ClarificationNeeded suspends the graph and durably
    checkpoints it — proven by using a brand-new graph + a brand-new
    AsyncSqliteSaver connection to the same file for the resume call,
    simulating a separate process/request rather than reusing in-memory
    state (this is exactly what app/langgraph_followup.py's own
    `run_with_pause` already does on every call — this test does not
    special-case anything to prove it);
(b) the reply merges into the original question and the pipeline is
    re-run with the merged text;
(c) multi-round pause: a second still-missing piece asks again before
    the turn completes ("the gate is re-evaluated... asks again");
(d) entity-ambiguous's village_hint threads through to the resumed
    pipeline call via ConversationState.pending_village_hint;
(e) a non-pause-eligible ClarificationNeeded rule (e.g. a terminal
    "cannot answer this at all" refusal) is never swallowed or
    interrupted — it propagates exactly as it does outside this module;
(f) the checkpoint file is a real, separate SQLite file, not an
    in-memory stand-in.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import pipeline  # noqa: E402
from app import langgraph_followup as lf  # noqa: E402
from app.auth import UserScope  # noqa: E402
from app.pipeline import ClarificationNeeded  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_orig_answer_question = pipeline.answer_question
_SCOPE = UserScope(user_id="u1", role="admin", granularity_cap="village",
                    schemes=["MGNREGA"], geographies="all")


async def _run_checks() -> None:
    # Fresh checkpoint file for this test run — proves each check below
    # starts from a clean, real, on-disk store, not stale state from a
    # previous run or another test file.
    lf._CHECKPOINT_DB_PATH.unlink(missing_ok=True)

    # ── (a)+(b)+(f) single pause, durable resume, correct merge ─────────
    print("1. SINGLE PAUSE -> DURABLE RESUME -> MERGED QUESTION")
    calls: list[str] = []

    async def fake_scope_gate(question, session=None, scope=None):
        calls.append(question)
        if "West Garo Hills" not in question:
            raise ClarificationNeeded(
                "Which area?",
                options=[{"label": "West Garo Hills", "question": "expenditure for West Garo Hills"}],
                rule="scope-not-specified")
        return {"route": "data", "answer": f"Answer for: {question}", "rows": [1, 2, 3]}

    pipeline.answer_question = fake_scope_gate
    check("checkpoint file does not exist before first call",
          not lf._CHECKPOINT_DB_PATH.exists())

    r1 = await lf.run_with_pause(session_id="single1", question="total MGNREGA expenditure", scope=_SCOPE)
    check("first call pauses", r1.get("paused") is True, r1)
    check("pause carries the clarifying question", r1.get("clarification", {}).get("question") == "Which area?")
    check("pause carries the rule", r1.get("clarification", {}).get("rule") == "scope-not-specified")
    check("pause carries the one-tap options", r1.get("clarification", {}).get("options") == [
        {"label": "West Garo Hills", "question": "expenditure for West Garo Hills"}])
    check("checkpoint file now exists on disk (real, not in-memory)",
          lf._CHECKPOINT_DB_PATH.exists())

    r2 = await lf.run_with_pause(session_id="single1", question="ignored on resume",
                                  scope=_SCOPE, resume="West Garo Hills")
    check("resume completes the turn", r2.get("route") == "data", r2)
    check("resumed pipeline call used the reply merged into the original question",
          r2.get("answer") == "Answer for: total MGNREGA expenditure, West Garo Hills", r2)
    check("the resumed question text ignored on the resume call, not concatenated twice",
          "ignored on resume" not in (r2.get("answer") or ""))

    # ── (c) multi-round pause ────────────────────────────────────────────
    print("2. MULTI-ROUND PAUSE (asks again for a second missing piece)")

    async def two_round_gate(question, session=None, scope=None):
        if "West Garo Hills" not in question:
            raise ClarificationNeeded("Which area?", rule="scope-not-specified")
        if "2023-24" not in question:
            raise ClarificationNeeded("Which year?", rule="year-not-specified")
        return {"route": "data", "answer": f"Final: {question}"}

    pipeline.answer_question = two_round_gate
    m1 = await lf.run_with_pause(session_id="multi1", question="MGNREGA expenditure", scope=_SCOPE)
    check("round 1 pauses on scope", m1.get("clarification", {}).get("rule") == "scope-not-specified", m1)
    m2 = await lf.run_with_pause(session_id="multi1", question="x", scope=_SCOPE, resume="West Garo Hills")
    check("round 2 pauses on year (gate re-evaluated, still missing something)",
          m2.get("clarification", {}).get("rule") == "year-not-specified", m2)
    m3 = await lf.run_with_pause(session_id="multi1", question="x", scope=_SCOPE, resume="2023-24")
    check("round 3 completes with both replies merged in",
          m3.get("answer") == "Final: MGNREGA expenditure, West Garo Hills, 2023-24", m3)

    # ── (d) entity-ambiguous village_hint passthrough ────────────────────
    print("3. ENTITY-AMBIGUOUS village_hint THREADS THROUGH TO RESUME")

    async def village_gate(question, session=None, scope=None):
        if "Betasing" not in question:
            raise ClarificationNeeded("Which village?", rule="entity-ambiguous", village_hint="Adugre")
        hint = session.state.pending_village_hint if session is not None else None
        return {"route": "data", "answer": f"resolved with hint={hint}: {question}"}

    pipeline.answer_question = village_gate
    v1 = await lf.run_with_pause(session_id="village1", question="Adugre houses", scope=_SCOPE)
    check("pauses with entity-ambiguous rule", v1.get("clarification", {}).get("rule") == "entity-ambiguous", v1)
    v2 = await lf.run_with_pause(session_id="village1", question="x", scope=_SCOPE,
                                  resume="the one in Betasing block")
    check("village_hint reached the resumed pipeline call via session.state",
          v2.get("answer") == "resolved with hint=Adugre: Adugre houses, the one in Betasing block", v2)

    # ── (e) non-pause-eligible rule propagates, never swallowed ──────────
    print("4. NON-PAUSE-ELIGIBLE RULE PROPAGATES (never interrupted, never swallowed)")

    async def terminal_gate(question, session=None, scope=None):
        raise ClarificationNeeded("Cannot answer this at all.", rule="column-not-held")

    pipeline.answer_question = terminal_gate
    raised = None
    try:
        await lf.run_with_pause(session_id="term1", question="pending dues", scope=_SCOPE)
    except ClarificationNeeded as e:
        raised = e
    check("a terminal (non-pause-eligible) rule raises rather than pausing", raised is not None)
    check("the raised exception is the original one, with its own rule intact",
          raised is not None and raised.rule == "column-not-held")
    # A raised (non-interrupt) exception leaves the checkpoint in an
    # "errored, node not yet completed" state — `snap.next` still names the
    # node (expected: it never finished), but critically NO interrupt was
    # recorded for it, unlike the pause-eligible cases above. That absence
    # is the actual signal this rule was propagated, not paused.
    async with lf._checkpointer_context() as cp:
        graph = lf._build_graph().compile(checkpointer=cp)
        snap = await graph.aget_state({"configurable": {"thread_id": "term1"}})
        check("no interrupt was recorded for the terminal-refusal session",
              all(not t.interrupts for t in snap.tasks), snap.tasks)


asyncio.run(_run_checks())
pipeline.answer_question = _orig_answer_question


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL LANGGRAPH FOLLOW-UP CHECKS PASSED")
