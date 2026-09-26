"""
Phase 2 audit-trail enrichment (openspec/changes/phase-2-audit-trail-enrichment)
— app.query_audit and its JSONL mirror must capture the executed SQL, a
bounded result preview, findings, and chart_type, so the durable compliance
trail can reconstruct what actually ran and what the user was shown, not
just query metadata.

Runs without a live DB (db.fetchval/db.execute are monkeypatched to capture
SQL + params instead of hitting Postgres) and without the model gateway.
Plain script, no pytest — `python tests/unit/test_query_audit_trail.py`, exit
code 0 = pass.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.update(
    ENV="prod",
    AUTH_ENABLED="false",
    JWT_SECRET="test-secret-at-least-32-characters-long",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from app.core import auth as _auth  # noqa: E402
from app.conversation import conversation_store  # noqa: E402
from app.database import db
from app.database.appdb import _DDL  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.api.routers.query import _mirror_audit  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


print("0. DDL declares the five new app.query_audit columns")
for col in ("sql TEXT", "result_preview JSONB", "findings JSONB", "chart_type TEXT", "answer TEXT"):
    check(f"_DDL contains 'ALTER TABLE app.query_audit ADD COLUMN IF NOT EXISTS {col}'",
          f"ADD COLUMN IF NOT EXISTS {col}" in _DDL)


print("1. _persist_turn's app.query_audit INSERT carries sql/result_preview/findings/chart_type/answer")

sql_calls: list[tuple[str, str, list]] = []


async def _fake_fetchval(sql, params=None):
    sql_calls.append(("fetchval", sql, params or []))
    return 1  # conv_id


async def _fake_execute(sql, params=None):
    sql_calls.append(("execute", sql, params or []))
    return "INSERT 0 1"


def _audit_call():
    return next((c for c in sql_calls if "app.query_audit" in c[1]), None)


big_rows = [{"district": f"D{i}", "amount": i} for i in range(30)]
result_full = {
    "route": "data",
    "answer": "Here are the figures.",
    "sql": "SELECT district, amount FROM curated.v_x LIMIT 30",
    "row_count": 30,
    "data": big_rows,
    "findings": [{"type": "large_result_set", "detail": "30 rows returned"}],
    "chart_type": "bar",
}

orig_fetchval, orig_execute = db.fetchval, db.execute
db.fetchval, db.execute = _fake_fetchval, _fake_execute
try:
    sql_calls.clear()
    asyncio.run(conversation_store._persist_turn(
        tenant_id=1, user_id=1, session_id="s1", result=result_full,
        question="how many beneficiaries by district", latency_ms=5.0,
        username="tester", ip="127.0.0.1"))
    call = _audit_call()
    check("an app.query_audit INSERT was issued", call is not None)
    if call is not None:
        params = call[2]
        check("bound params include the executed SQL text",
              result_full["sql"] in params, str(params))
        preview_json = next((p for p in params if isinstance(p, str) and '"district": "D0"' in p), None)
        check("bound params include a result_preview JSON blob", preview_json is not None)
        if preview_json is not None:
            preview_rows = json.loads(preview_json)
            check(f"result_preview is capped at settings.AUDIT_RESULT_PREVIEW_ROWS "
                  f"({settings.AUDIT_RESULT_PREVIEW_ROWS}), not the full 30 rows",
                  len(preview_rows) == settings.AUDIT_RESULT_PREVIEW_ROWS,
                  f"got {len(preview_rows) if preview_json else 'n/a'}")
        check("bound params include the findings payload",
              isinstance(params[-4], str) and "large_result_set" in params[-4], str(params[-4]))
        check("bound params include chart_type 'bar'", params[-3] == "bar", str(params[-3]))
        # Step 9: the request's diagnostic trace is the last bound param
        # (app.query_audit.trace) — None here, no trace was passed.
        check("trace is the last bound param (None when no trace passed)", params[-1] is None, str(params[-1]))
        check("bound params include the final response text",
              params[-2] == result_full["answer"], str(params[-2]))
finally:
    db.fetchval, db.execute = orig_fetchval, orig_execute


print("2. Findings/chart_type disabled or empty still write explicit empty values, not missing keys")

result_empty = {
    "route": "data",
    "answer": "No notable findings.",
    "sql": "SELECT 1",
    "row_count": 1,
    "data": [{"x": 1}],
    "findings": [],
    "chart_type": None,
}

db.fetchval, db.execute = _fake_fetchval, _fake_execute
try:
    sql_calls.clear()
    asyncio.run(conversation_store._persist_turn(
        tenant_id=1, user_id=1, session_id="s2", result=result_empty,
        question="single value query", latency_ms=5.0,
        username="tester", ip="127.0.0.1"))
    call = _audit_call()
    check("an app.query_audit INSERT was issued for the empty-findings case", call is not None)
    if call is not None:
        params = call[2]
        check("findings serializes to an explicit empty list '[]', not omitted",
              params[-4] == "[]", str(params[-4]))
        check("chart_type is passed through as an explicit NULL (None), not omitted",
              params[-3] is None, str(params[-3]))
        check("answer text is bound even for a minimal result",
              params[-2] == result_empty["answer"], str(params[-2]))
finally:
    db.fetchval, db.execute = orig_fetchval, orig_execute


print("3. JSONL mirror (_mirror_audit) carries the same five fields as the Postgres path")


class _Scope:
    tenant_id = 1
    db_user_id = 1
    username = "tester"
    role = "analyst"


captured_audit: dict = {}
orig_audit = _auth.audit
_auth.audit = lambda record: captured_audit.update(record)
try:
    import time as _time
    _mirror_audit(_Scope(), "s1", "how many beneficiaries by district", result_full,
                  _time.monotonic(), "127.0.0.1")
    check("JSONL mirror includes the same sql text", captured_audit.get("sql") == result_full["sql"])
    check("JSONL mirror's result_preview is a list capped the same way as the DB path",
          isinstance(captured_audit.get("result_preview"), list)
          and len(captured_audit["result_preview"]) == settings.AUDIT_RESULT_PREVIEW_ROWS)
    check("JSONL mirror includes the findings list",
          captured_audit.get("findings") == result_full["findings"])
    check("JSONL mirror includes chart_type", captured_audit.get("chart_type") == "bar")
    check("JSONL mirror includes the final response text",
          captured_audit.get("answer") == result_full["answer"])
finally:
    _auth.audit = orig_audit


print("4. delete_conversation never touches app.query_audit (compliance trail survives history deletion)")

del_calls: list[str] = []


async def _fake_fetchval_conv(sql, params=None):
    del_calls.append(sql)
    return 42  # conv_id found


async def _fake_execute_conv(sql, params=None):
    del_calls.append(sql)
    return "DELETE 1"


db.fetchval, db.execute = _fake_fetchval_conv, _fake_execute_conv
try:
    del_calls.clear()
    ok = asyncio.run(conversation_store.delete_conversation(session_id="s1", user_id=1))
    check("delete_conversation reports success", ok is True)
    check("delete_conversation issued exactly 3 statements (lookup + 2 deletes)",
          len(del_calls) == 3, str(del_calls))
    check("no statement referenced app.query_audit",
          not any("query_audit" in c for c in del_calls), str(del_calls))
finally:
    db.fetchval, db.execute = orig_fetchval, orig_execute


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL QUERY AUDIT TRAIL CHECKS PASSED")
