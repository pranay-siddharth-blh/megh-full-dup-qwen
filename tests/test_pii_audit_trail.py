"""
Follow-up Fix #2 (openspec/changes/urgent-pii-redaction-followup) — a
PII-blocked clarification pause (ClarificationNeeded(rule="pii-column-blocked"))
must be visible in the durable audit trail (app.conversation_turns /
app.query_audit), not just grep-able from the application log.

Runs without a live DB or the model gateway (db.fetchval/db.execute are
monkeypatched to capture SQL + params instead of hitting Postgres). Plain
script, no pytest — `python tests/test_pii_audit_trail.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.update(
    ENV="prod",
    AUTH_ENABLED="false",  # anonymous_scope() path — no JWT plumbing needed here
    JWT_SECRET="test-secret-at-least-32-characters-long",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from starlette.testclient import TestClient  # noqa: E402

import app.routers.query as query_router  # noqa: E402
from app import auth as _auth  # noqa: E402
from app import conversation_store, db, pipeline  # noqa: E402
from app.main import app  # noqa: E402
from app.pipeline import ClarificationNeeded  # noqa: E402
from app.routers.query import _identity  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


print("1. /api/query's ClarificationNeeded HANDLER SETS denied_by ON THE PERSISTED RESULT")

captured: dict = {}


def _fake_persist_turn(*, tenant_id, user_id, session_id, result, question,
                       latency_ms, username, ip):
    captured["result"] = result  # sync stand-in for the real fire-and-forget call


async def _fake_answer_question(*_a, **_kw):
    raise ClarificationNeeded(
        "CM Elevate can't show personal applicant details (date of birth, "
        "address, ID or account numbers).", rule="pii-column-blocked")


orig_persist_turn = conversation_store.persist_turn
orig_answer_question = query_router.answer_question
orig_pipeline_answer_question = pipeline.answer_question
query_router.conversation_store.persist_turn = _fake_persist_turn
query_router.answer_question = _fake_answer_question
# LANGGRAPH_FOLLOWUP_ENABLED=True (a real deployment combination, exercised
# together with PIPELINE_GRAPH_ENABLED for the first time by
# multi-tenant-rls-scheme-scaleout tasks.md 7.2's flag-combination sweep)
# makes app/routers/query.py call app.langgraph_followup.run_with_pause
# instead of query_router.answer_question directly — and that module calls
# pipeline.answer_question via its OWN `from app import pipeline` binding,
# a separate name from query_router's `from app.pipeline import
# answer_question` above. Patching only query_router.answer_question (as
# this test always has) leaves the real pipeline running whenever that flag
# is on. Patch both bindings so this test's fake fires regardless of which
# routing branch query.py takes.
pipeline.answer_question = _fake_answer_question
app.dependency_overrides[_identity] = lambda: _auth.anonymous_scope()
try:
    r = client.post("/api/query", json={"question": "show me applicant date of birth"})
    check("request succeeds (a clarification pause, not an error)",
          r.status_code == 200, f"got {r.status_code}")
    body = r.json() if r.status_code == 200 else {}
    check("response body still carries the pii-column-blocked rule",
          body.get("clarification", {}).get("rule") == "pii-column-blocked")
    check("conversation_store.persist_turn was actually called", "result" in captured)
    result = captured.get("result", {})
    check("the persisted result has denied_by == 'pii-column-blocked'",
          result.get("denied_by") == "pii-column-blocked")
    check("the persisted result's route is 'clarification'",
          result.get("route") == "clarification")
finally:
    query_router.conversation_store.persist_turn = orig_persist_turn
    query_router.answer_question = orig_answer_question
    pipeline.answer_question = orig_pipeline_answer_question
    app.dependency_overrides.pop(_identity, None)


print("2. THAT SAME RESULT REACHES app.conversation_turns AND app.query_audit COLUMNS")

sql_calls: list[tuple[str, str, list]] = []


async def _fake_fetchval(sql, params=None):
    sql_calls.append(("fetchval", sql, params or []))
    return 1  # conv_id


async def _fake_execute(sql, params=None):
    sql_calls.append(("execute", sql, params or []))
    return "INSERT 0 1"


orig_fetchval = db.fetchval
orig_execute = db.execute
db.fetchval = _fake_fetchval
db.execute = _fake_execute
try:
    if "result" not in captured:
        check("prerequisite: section 1 captured a result to persist", False)
    else:
        asyncio.run(conversation_store._persist_turn(
            tenant_id=1, user_id=1, session_id="s1", result=captured["result"],
            question="show me applicant date of birth", latency_ms=5.0,
            username="tester", ip="127.0.0.1"))
        turns_call = next((c for c in sql_calls if "app.conversation_turns" in c[1]), None)
        audit_call = next((c for c in sql_calls if "app.query_audit" in c[1]), None)
        check("an app.conversation_turns INSERT was issued", turns_call is not None)
        check("an app.query_audit INSERT was issued", audit_call is not None)
        check("app.conversation_turns' bound params include denied_by='pii-column-blocked'",
              turns_call is not None and "pii-column-blocked" in turns_call[2])
        check("app.query_audit's bound params include denied_by='pii-column-blocked'",
              audit_call is not None and "pii-column-blocked" in audit_call[2])
finally:
    db.fetchval = orig_fetchval
    db.execute = orig_execute


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL PII AUDIT TRAIL CHECKS PASSED")
