"""
tests/unit/test_query_langgraph_wiring.py — app/api/routers/query.py's wiring to
app/orchestration/langgraph_followup.py behind `settings.LANGGRAPH_FOLLOWUP_ENABLED`
(openspec/changes/phase-2-orchestration-durability, "wire into production,
feature-flagged default off", 2026-09-13).

Uses starlette's TestClient against the real app (same pattern as
tests/unit/test_security.py), overriding the auth dependency to skip real
JWT/DB auth, and monkeypatching the pipeline entry point each branch
actually calls — no DB, no model gateway, same stance as every other file
in this directory. DATABASE_URL is a bogus, unreachable address;
conversation_store.persist_turn/save_context_state are fire-and-forget and
already tolerate that in every other TestClient-based test here.

`python tests/unit/test_query_langgraph_wiring.py`, exit code 0 = all pass.

Covers:
(a) LANGGRAPH_FOLLOWUP_ENABLED=False (default): the pause is answer_question's
    own (Step 10: frame slot filling on pending_frame — the old text-glue
    pending_scope_q is never written any more).
(b) LANGGRAPH_FOLLOWUP_ENABLED=True: a pause returns the same response
    shape the bespoke path returns, but deliberately does NOT set
    session.state.pending_scope_q/pending_village_hint — setting those
    would make pipeline._run_pipeline's own top-of-function merge fire a
    second time on the next call's replay-before-interrupt pipeline
    invocation and corrupt the merge (see app/orchestration/langgraph_followup.py's
    module docstring and app/api/routers/query.py's comments at this branch).
(c) LANGGRAPH_FOLLOWUP_ENABLED=True: a second request on the same session
    is correctly detected as a resume (via langgraph_followup.is_paused)
    and completes with the merged question, end to end through the real
    HTTP route.
(d) entity-ambiguous under the flag: pending_village_hint is set during
    the pause and cleared again once the turn completes — regression
    coverage for the leak fixed in app/orchestration/langgraph_followup.py's
    _run_pipeline_node (previously nothing cleared it once this module
    stopped also setting pending_scope_q, since pipeline.py's own clearing
    is gated on pending_scope_q being truthy).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.update(
    ENV="prod",
    AUTH_ENABLED="true",
    JWT_SECRET="test-secret-at-least-32-characters-long",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from starlette.testclient import TestClient  # noqa: E402

from app.orchestration import pipeline  # noqa: E402
from app.orchestration import langgraph_followup as lf  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.orchestration.pipeline import ClarificationNeeded  # noqa: E402
from app.api.routers import query as query_router  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_SCOPE = UserScope(user_id="wire-u1", role="admin", granularity_cap="village",
                    schemes=["MGNREGA"], geographies="all", tenant_id=1,
                    db_user_id=1, username="wire-tester")

app.dependency_overrides[query_router._identity] = lambda: _SCOPE

_orig_answer_question = pipeline.answer_question
_orig_query_answer_question = query_router.answer_question


async def scope_gate(question, session=None, scope=None):
    if "West Garo Hills" not in question:
        raise ClarificationNeeded(
            "Which area?",
            options=[{"label": "West Garo Hills", "question": "expenditure for West Garo Hills"}],
            rule="scope-not-specified")
    return {"route": "data", "answer": f"Answer for: {question}", "rows": [1, 2, 3]}


async def village_gate(question, session=None, scope=None):
    if "Betasing" not in question:
        raise ClarificationNeeded("Which village?", rule="entity-ambiguous", village_hint="Adugre")
    hint = session.state.pending_village_hint if session is not None else None
    return {"route": "data", "answer": f"resolved with hint={hint}: {question}"}


try:
    lf._CHECKPOINT_DB_PATH.unlink(missing_ok=True)

    # ── (a) flag OFF: unchanged bespoke behavior ─────────────────────────
    print("1. FLAG OFF (default) — the pause is answer_question's (frame slot filling), never the text-glue pending_scope_q")
    settings.LANGGRAPH_FOLLOWUP_ENABLED = False
    query_router.answer_question = scope_gate
    sid_a = "wire-off-1"
    r = client.post("/api/query", json={"question": "total MGNREGA expenditure", "session_id": sid_a})
    check("200 OK", r.status_code == 200, r.text[:300])
    body = r.json()
    check("needs_clarification True", body.get("needs_clarification") is True, body)
    check("clarification rule is scope-not-specified", body.get("clarification", {}).get("rule") == "scope-not-specified")
    sess = session_store.ensure(sid_a, _SCOPE.user_id)
    check("no text-glue resume state written (pending_scope_q is gone from the resume path)",
          sess.state.pending_scope_q is None)

    # ── (b)+(c) flag ON: pause does not touch pending_scope_q, resume works ──
    print("2. FLAG ON — pause via LangGraph, does not set pending_scope_q")
    settings.LANGGRAPH_FOLLOWUP_ENABLED = True
    pipeline.answer_question = scope_gate
    sid_b = "wire-on-1"
    r1 = client.post("/api/query", json={"question": "total MGNREGA expenditure", "session_id": sid_b})
    check("200 OK", r1.status_code == 200, r1.text[:300])
    b1 = r1.json()
    check("needs_clarification True", b1.get("needs_clarification") is True, b1)
    check("clarification rule is scope-not-specified", b1.get("clarification", {}).get("rule") == "scope-not-specified")
    sess_b = session_store.ensure(sid_b, _SCOPE.user_id)
    check("LangGraph path did NOT set pending_scope_q", sess_b.state.pending_scope_q is None)
    check("session is reported paused by the checkpointer",
          asyncio.run(lf.is_paused(sid_b)) is True)

    print("3. FLAG ON — second request resumes and completes")
    r2 = client.post("/api/query", json={"question": "West Garo Hills", "session_id": sid_b})
    check("200 OK", r2.status_code == 200, r2.text[:300])
    b2 = r2.json()
    check("resume completed (no longer a clarification)", b2.get("needs_clarification") is not True, b2)
    check("merged question reached the pipeline",
          b2.get("answer") == "Answer for: total MGNREGA expenditure, West Garo Hills", b2)
    check("session no longer reported paused",
          asyncio.run(lf.is_paused(sid_b)) is False)

    # ── (d) entity-ambiguous under the flag: village_hint set then cleared ──
    print("4. FLAG ON — entity-ambiguous pending_village_hint set on pause, cleared on completion")
    pipeline.answer_question = village_gate
    sid_d = "wire-on-village-1"
    r3 = client.post("/api/query", json={"question": "Adugre houses", "session_id": sid_d})
    check("200 OK", r3.status_code == 200, r3.text[:300])
    b3 = r3.json()
    check("clarification rule is entity-ambiguous", b3.get("clarification", {}).get("rule") == "entity-ambiguous", b3)
    sess_d = session_store.ensure(sid_d, _SCOPE.user_id)
    check("pending_village_hint set by the graph node during the pause",
          sess_d.state.pending_village_hint == "Adugre")
    check("pending_scope_q still not set", sess_d.state.pending_scope_q is None)

    r4 = client.post("/api/query", json={"question": "the one in Betasing block", "session_id": sid_d})
    check("200 OK", r4.status_code == 200, r4.text[:300])
    b4 = r4.json()
    check("resume completed with village_hint threaded through",
          b4.get("answer") == "resolved with hint=Adugre: Adugre houses, the one in Betasing block", b4)
    check("pending_village_hint cleared after completion (leak fix holds under real wiring)",
          sess_d.state.pending_village_hint is None)

finally:
    pipeline.answer_question = _orig_answer_question
    query_router.answer_question = _orig_query_answer_question
    settings.LANGGRAPH_FOLLOWUP_ENABLED = False
    app.dependency_overrides.pop(query_router._identity, None)


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL QUERY <-> LANGGRAPH WIRING CHECKS PASSED")
