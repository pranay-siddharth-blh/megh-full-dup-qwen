"""
Step 9 — the audit trail as a feedback loop:
app/core/request_trace.py, the trace in app.query_audit + logs/query_audit.jsonl,
app/conversation/failures.py, GET /admin/failures, tests/eval/export_failures.py.

Covers: trace helpers (no-op outside a request, stages add up, total time);
a real /api/query answer writes raw question, frame before/after normalise,
rules fired, assumptions, SQL source, per-stage latency into the JSONL audit
line AND hands the same trace to the DB insert; a pause records the
clarification asked + its slot; failure rules (zero rows, repair used,
fallback reply, clarification loop) in Python and in the SQL; the admin
endpoint's counts; the export script appending needs-expected-answer cases,
collapsing a clarification loop into one conversation, and never duplicating.
No DB, no gateway.
Run: `python tests/unit/test_audit_trace.py`, exit code 0 = pass.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

import yaml  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.api import deps  # noqa: E402
from app.api.routers import query as query_router  # noqa: E402
from app.conversation import conversation_memory, conversation_store, failures  # noqa: E402
from app.core import auth, request_trace  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.main import app  # noqa: E402
from app.nlu import entity_resolver  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


entity_resolver.load_all()
scheme_registry.load_all()

print("\n=== request_trace helpers ===")
request_trace.note("x", 1)
request_trace.incr("repairs")
with request_trace.stage("s"):
    pass
check("no active trace: every helper is a silent no-op", request_trace.snapshot() is None)
tok = request_trace.start("hello")
with request_trace.stage("sql_generation"):
    pass
with request_trace.stage("sql_generation"):
    pass
request_trace.incr("repairs")
request_trace.append("rules_fired", "scheme:ok")
snap = request_trace.snapshot()
request_trace.reset(tok)
check("snapshot carries raw question, counters, lists",
      snap["raw_question"] == "hello" and snap["repairs"] == 1 and snap["rules_fired"] == ["scheme:ok"])
check("stages add up and a total is stamped", "sql_generation" in snap["stages_ms"] and "total" in snap["stages_ms"])
check("private fields are not exported", not any(k.startswith("_") for k in snap))

print("\n=== failure rules ===")
recs = [
    {"session_id": "a", "route": "data", "row_count": "0", "question": "q1"},
    {"session_id": "a", "route": "data", "row_count": "5", "question": "q2", "trace": {"repairs": 2}},
    {"session_id": "a", "route": "data", "row_count": "3", "question": "q3",
     "trace": json.dumps({"fallback": "number_check"})},
    {"session_id": "b", "route": "clarification", "row_count": "0", "question": "c1"},
    {"session_id": "b", "route": "clarification", "row_count": "0", "question": "c2"},
    {"session_id": "b", "route": "clarification", "row_count": "0", "question": "c3"},
    {"session_id": "c", "route": "clarification", "row_count": "0", "question": "ok-1"},
    {"session_id": "c", "route": "data", "row_count": "9", "question": "fine"},
]
failed = {r["question"]: r["reasons"] for r in failures.classify(recs)}
check("zero rows", failed.get("q1") == ["zero_rows"])
check("repair used", failed.get("q2") == ["repair_used"])
check("fallback reply (trace stored as JSON text too)", failed.get("q3") == ["fallback_reply"])
check("clarification asked more than twice in one conversation",
      all(failed.get(q) == ["clarify_loop"] for q in ("c1", "c2", "c3")))
check("a single clarification and a good answer are not failures", "ok-1" not in failed and "fine" not in failed)
sql = failures.FAILURES_SQL.format(tenant_clause="AND tenant_id = $2", threshold=2, limit=10)
check("SQL form: same four rules, day-bounded, tenant filter slot",
      all(k in sql for k in ("zero_rows", "repair_used", "fallback_reply", "clarify_loop", "$1::date",
                             "AND tenant_id = $2", "HAVING count(*) > 2")))

print("\n=== /api/query writes the trace ===")
tmp = Path(tempfile.mkdtemp())
audit_file = tmp / "audit.jsonl"
orig_audit_path = auth._audit_path
auth._audit_path = audit_file
_SCOPE = UserScope(user_id="tr-u1", role="admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"], geographies="all",
                   tenant_id=1, db_user_id=1, username="tr-user")
app.dependency_overrides[query_router._identity] = lambda: _SCOPE
client = TestClient(app, raise_server_exceptions=False)
FRAMES = {
    "total manrega expendture": dict(rewritten_question="What is the total MGNREGA expenditure?",
                                     schemes=["MGNREGA"], metric="total expenditure", query_type="value"),
    "total expenditure?": dict(rewritten_question="What is the total expenditure?", metric="total expenditure",
                               query_type="value"),
}
persisted: list[dict] = []


async def _build(message, ctx):
    return {"frame": u.QueryFrame(intent="DATA", **FRAMES[message]).model_dump(), "meta": {"flags": []}}


async def _exec(question, schemes, entity_result, initial_sql=None, *, scope=None, max_repairs=None):
    return initial_sql, [{"total_expenditure_crore": 12.3}]


async def _one_attempt(sql, question, schemes, entity_result, scope, retrieved):
    # The LangGraph path (PIPELINE_GRAPH_ENABLED) executes through its own
    # attempt nodes on top of this, not execute_with_repair.
    return sql, [{"total_expenditure_crore": 12.3}]


async def _compose(question, sql, rows, notes=None, **kw):
    return "It is **12.3** crore."


async def _no_state(session_id):
    return {}

patches = [
    (u, "build_frame", _build), (pipeline, "execute_with_repair", _exec), (pipeline, "compose_response", _compose),
    (pipeline, "_execute_one_attempt", _one_attempt),
    (conversation_store, "persist_turn", lambda **k: persisted.append(k)),
    (conversation_store, "save_context_state", lambda **k: None),
    (conversation_store, "load_context_state", _no_state),
    (conversation_memory, "index_turn", lambda **k: None),
    (pipeline.clarification_engine, "check_clarifications", lambda *a, **k: None),
]
originals = [(o, n, getattr(o, n)) for o, n, _ in patches]
for o, n, fn in patches:
    setattr(o, n, fn)
flag_names = ("FRAME_GATES_ENABLED", "QUERY_ANALYZER_ENABLED", "CONTEXT_SUMMARY_ENABLED",
              "CONTEXT_SEMANTIC_MEMORY_ENABLED", "RESPONSE_CACHE_ENABLED", "SEMANTIC_CACHE_ENABLED")
flags_before = {n: getattr(settings, n) for n in flag_names}
for n, v in zip(flag_names, (True, False, False, False, False, False)):
    setattr(settings, n, v)
try:
    r = client.post("/api/query", json={"question": "total manrega expendture", "session_id": "tr-1"}).json()
    line = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1])
    t = line.get("trace") or {}
    check("answered", r.get("route") == "data", str(r)[:200])
    check("JSONL: raw question", t.get("raw_question") == "total manrega expendture")
    check("JSONL: frame before normalise (as the model returned it)",
          (t.get("frame_before") or {}).get("metric") == "total expenditure")
    check("JSONL: frame after normalise (canonical schemes + year)",
          (t.get("frame_after") or {}).get("resolved_schemes") == ["MGNREGA"], str(t.get("frame_after"))[:200])
    check("JSONL: rules fired", "scheme:ok" in (t.get("rules_fired") or [])
          and any(x.startswith("year:default") for x in t.get("rules_fired") or []), str(t.get("rules_fired")))
    check("JSONL: assumptions", any("FY 2025-26" in a for a in t.get("assumptions") or []))
    st = t.get("stages_ms") or {}
    check("JSONL: latency per stage", all(k in st for k in ("understand", "normalise", "sql_generation",
                                                          "compose", "total")), str(st))
    check("SQL + row_count stay in their own audit columns", line.get("sql") and line.get("row_count") == 1)
    check("DB insert receives the same trace", persisted and (persisted[-1].get("trace") or {}).get(
        "raw_question") == "total manrega expendture")

    r = client.post("/api/query", json={"question": "total expenditure?", "session_id": "tr-2"}).json()
    t = json.loads(audit_file.read_text(encoding="utf-8").splitlines()[-1]).get("trace") or {}
    check("a pause records the clarification asked + its slot",
          (t.get("clarification") or {}).get("rule") == "scheme-not-specified"
          and t["clarification"].get("slot") == "scheme" and t["clarification"].get("options"), str(t)[:300])
    check("... and the rule that fired", "scheme:ask" in (t.get("rules_fired") or []))

    print("\n=== GET /admin/failures ===")

    async def _fake_failures(*, tenant_id, day, limit=500):
        return [{"id": 1, "reasons": ["zero_rows"]}, {"id": 2, "reasons": ["zero_rows", "repair_used"]},
                {"id": 3, "reasons": ["clarify_loop"]}]
    orig_af = conversation_store.admin_failures
    conversation_store.admin_failures = _fake_failures
    app.dependency_overrides[deps.require_admin] = lambda: _SCOPE
    try:
        resp = client.get("/admin/failures?day=2026-09-25")
        body = resp.json()
        check("endpoint returns the day's failures with per-reason counts",
              resp.status_code == 200 and body["count"] == 3 and body["counts"]["zero_rows"] == 2
              and body["counts"]["repair_used"] == 1 and body["counts"]["clarify_loop"] == 1, str(body)[:200])
        check("bad day format rejected", client.get("/admin/failures?day=25-09-2026").status_code == 422)
    finally:
        conversation_store.admin_failures = orig_af
        app.dependency_overrides.pop(deps.require_admin, None)
finally:
    for o, n, fn in originals:
        setattr(o, n, fn)
    for n, v in flags_before.items():
        setattr(settings, n, v)
    auth._audit_path = orig_audit_path
    app.dependency_overrides.pop(query_router._identity, None)

print("\n=== export_failures.py -> cases.yaml ===")
day = "2026-09-25"
jsonl = tmp / "q.jsonl"
jsonl.write_text("\n".join(json.dumps(x) for x in [
    {"ts": f"{day}T10:00:00+0530", "session_id": "s1", "route": "data", "row_count": "0",
     "question": "villages with zero work in wgh", "username": "officer1", "ip": "10.0.0.1"},
    {"ts": f"{day}T10:01:00+0530", "session_id": "s2", "route": "clarification", "row_count": "0",
     "question": "expenditure", "username": "officer2", "ip": "10.0.0.2"},
    {"ts": f"{day}T10:02:00+0530", "session_id": "s2", "route": "clarification", "row_count": "0",
     "question": "mgnrega", "username": "officer2", "ip": "10.0.0.2"},
    {"ts": f"{day}T10:03:00+0530", "session_id": "s2", "route": "clarification", "row_count": "0",
     "question": "wgh", "username": "officer2", "ip": "10.0.0.2"},
    {"ts": f"{day}T10:04:00+0530", "session_id": "s3", "route": "data", "row_count": "0",
     "question": "harness turn", "username": "eval-harness", "ip": "testclient"},
    {"ts": "2026-09-24T10:00:00+0530", "session_id": "s4", "route": "data", "row_count": "0",
     "question": "yesterday", "username": "officer1", "ip": "10.0.0.1"},
]) + "\n", encoding="utf-8")
cases_file = tmp / "cases.yaml"
cases_file.write_text("# header line\nversion: 1\ncases:\n- id: x-1\n  source: kpi_workbook\n  turns: [a]\n",
                      encoding="utf-8")
cmd = [sys.executable, str(ROOT / "tests" / "eval" / "export_failures.py"), "--day", day,
       "--audit-file", str(jsonl), "--cases", str(cases_file)]
out1 = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
doc = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
new = [c for c in doc["cases"] if c["id"].startswith("fail-")]
check("export ran", out1.returncode == 0, out1.stderr[-400:])
check("zero-rows turn exported as its own case",
      any(c["turns"] == ["villages with zero work in wgh"] and c["failure_reasons"] == ["zero_rows"] for c in new))
check("clarification loop exported ONCE as the whole conversation",
      sum(1 for c in new if "clarify_loop" in c["failure_reasons"]) == 1
      and any(c["turns"] == ["expenditure", "mgnrega", "wgh"] for c in new), str(new))
check("marked needs_expected_answer, human-owned source (kept by build_cases)",
      all(c["needs_expected_answer"] is True and c["source"] == "audit_log" for c in new))
check("harness traffic and other days excluded", len(new) == 2 and not any(
    "harness turn" in c["turns"] or "yesterday" in c["turns"] for c in new))
check("existing cases + header kept", doc["cases"][0]["id"] == "x-1"
      and cases_file.read_text(encoding="utf-8").startswith("# header line"))
subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
doc2 = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
check("re-running adds nothing (no duplicates)", len(doc2["cases"]) == len(doc["cases"]))

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL AUDIT-TRACE CHECKS PASSED")
