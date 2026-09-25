"""
openspec change `query-analyzer-consolidation` — app.query_audit's `analysis`
and `scope` columns (node 5.2 and its node 5.1 sibling), added the same
idempotent way `findings`/`chart_type` were in phase-2-audit-trail-enrichment
(see tests/unit/test_query_audit_trail.py, which this file deliberately mirrors
rather than duplicates wholesale).

Runs without a live DB (db.fetchval/db.execute monkeypatched) and without the
model gateway. Plain script — `python tests/unit/test_query_analyzer_audit_trail.py`,
exit code 0 = pass.
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
from app.api.routers.query import _mirror_audit  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


print("0. DDL declares the two new app.query_audit columns")
for col in ("analysis JSONB", "scope JSONB"):
    check(f"_DDL contains 'ALTER TABLE app.query_audit ADD COLUMN IF NOT EXISTS {col}'",
          f"ADD COLUMN IF NOT EXISTS {col}" in _DDL)


print("1. _persist_turn's app.query_audit INSERT carries analysis/scope when present")

sql_calls: list[tuple[str, str, list]] = []


async def _fake_fetchval(sql, params=None):
    sql_calls.append(("fetchval", sql, params or []))
    return 1


async def _fake_execute(sql, params=None):
    sql_calls.append(("execute", sql, params or []))
    return "INSERT 0 1"


def _audit_call():
    return next((c for c in sql_calls if "app.query_audit" in c[1]), None)


_FAKE_ANALYSIS = {"query_type": "aggregation", "metric": "amount disbursed", "entities": {},
                   "time_scope": None, "granularity": "district", "ambiguous": [],
                   "intent_summary": "total disbursement"}
_FAKE_SCOPE = {"schemes": ["MGNREGA"], "confidence": 0.95, "source": "shortcut",
               "reason": "Named scheme: MGNREGA", "is_followup": False, "in_scope": True}

result_full = {
    "route": "data",
    "answer": "Here are the figures.",
    "sql": "SELECT amount FROM curated.v_x LIMIT 5",
    "row_count": 5,
    "data": [{"amount": 1}],
    "findings": [],
    "chart_type": None,
    "analysis": _FAKE_ANALYSIS,
    "scope": _FAKE_SCOPE,
}

orig_fetchval, orig_execute = db.fetchval, db.execute
db.fetchval, db.execute = _fake_fetchval, _fake_execute
try:
    sql_calls.clear()
    asyncio.run(conversation_store._persist_turn(
        tenant_id=1, user_id=1, session_id="s1", result=result_full,
        question="total disbursement", latency_ms=5.0, username="tester", ip="127.0.0.1"))
    call = _audit_call()
    check("an app.query_audit INSERT was issued", call is not None)
    if call is not None:
        params = call[2]
        col_list_sql = call[1]
        idx_analysis = col_list_sql.index("analysis")
        # Column order in the INSERT text vs. bound param order must agree —
        # asserted structurally (find each column's position among the named
        # columns) rather than a brittle fixed index, since this INSERT's
        # column count changes as more audit fields are added over time.
        cols = [c.strip() for c in
                col_list_sql.split("(", 1)[1].split(")", 1)[0].split(",")]
        analysis_param = params[cols.index("analysis")]
        scope_param = params[cols.index("scope")]
        check("bound analysis param is a JSON string of the analysis object",
              analysis_param is not None and json.loads(analysis_param) == _FAKE_ANALYSIS,
              detail=str(analysis_param))
        check("bound scope param is a JSON string of the scope object",
              scope_param is not None and json.loads(scope_param) == _FAKE_SCOPE,
              detail=str(scope_param))
        # Existing findings/chart_type/answer fields must still land correctly
        # — the regression guard for reordering the INSERT's column list.
        check("answer is still bound correctly after the reorder",
              params[cols.index("answer")] == "Here are the figures.")
        check("chart_type is still bound correctly after the reorder",
              params[cols.index("chart_type")] is None)
finally:
    db.fetchval, db.execute = orig_fetchval, orig_execute


print("2. analysis/scope absent (KNOWLEDGE/EDGE-shaped result) -> explicit NULL, not a crash")

result_no_analysis = {
    "route": "knowledge",
    "answer": "Some knowledge answer.",
    "sql": None,
    "row_count": None,
    "data": [],
    "findings": [],
    "chart_type": None,
}

db.fetchval, db.execute = _fake_fetchval, _fake_execute
try:
    sql_calls.clear()
    asyncio.run(conversation_store._persist_turn(
        tenant_id=1, user_id=1, session_id="s2", result=result_no_analysis,
        question="how does the scheme work", latency_ms=5.0, username="tester", ip="127.0.0.1"))
    call = _audit_call()
    check("an app.query_audit INSERT was issued for the no-analysis case", call is not None)
    if call is not None:
        params = call[2]
        cols = [c.strip() for c in
                call[1].split("(", 1)[1].split(")", 1)[0].split(",")]
        check("analysis is bound as NULL, not omitted or erroring",
              params[cols.index("analysis")] is None)
        check("scope is bound as NULL, not omitted or erroring",
              params[cols.index("scope")] is None)
finally:
    db.fetchval, db.execute = orig_fetchval, orig_execute


print("3. JSONL mirror (_mirror_audit) carries analysis/scope in parity with the DB path")


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
    _mirror_audit(_Scope(), "s1", "total disbursement", result_full, _time.monotonic(), "127.0.0.1")
    check("JSONL mirror includes the analysis object", captured_audit.get("analysis") == _FAKE_ANALYSIS)
    check("JSONL mirror includes the scope object", captured_audit.get("scope") == _FAKE_SCOPE)
finally:
    _auth.audit = orig_audit


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL QUERY ANALYZER AUDIT TRAIL CHECKS PASSED")
