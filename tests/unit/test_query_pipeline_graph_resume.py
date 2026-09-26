"""
tests/unit/test_query_pipeline_graph_resume.py — app/api/routers/query.py's wiring to
REAL cross-request resume via app/orchestration/pipeline_graph.py's own checkpointer
(openspec/changes/multi-tenant-rls-scheme-scaleout task 5.4, 2026-09-18).

Before this task, PIPELINE_GRAPH_ENABLED's pauses were always converted back
to the bespoke ClarificationNeeded/pending_scope_q mechanism (see
tests/unit/test_pipeline_graph_cutover.py) — the graph's OWN checkpointer/
interrupt() primitives were exercised only WITHIN one call, never across an
HTTP request boundary. This file proves the real thing: a pause durably
survives to a second, independent request, and is continued via
resume_via_graph, not re-run from node 5.1 with a bespoke-merged question.

Uses the same TestClient + real-graph-internals-mocked pattern as
tests/unit/test_pipeline_graph.py (mocks _classify_scheme_detailed/
resolve_entities/generate_sql/_execute_one_attempt/compose_response —
the LLM/DB-touching layer — but runs the REAL StateGraph, REAL SQLite
checkpointer, REAL HTTP route), not the simpler single-function monkeypatch
tests/unit/test_query_langgraph_wiring.py uses for app/orchestration/langgraph_followup.py
(that component wraps the whole pipeline as one opaque node; this one
doesn't, so a shallower mock wouldn't exercise the graph's own node
decomposition or checkpointer at all).

`python tests/unit/test_query_pipeline_graph_resume.py`, exit code 0 = all pass.
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
from app.orchestration import pipeline_graph as pg  # noqa: E402
from app.core.auth import AuthDecision, UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.api.routers import query as query_router  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


class _Patcher:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.orig)


class _Multi:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.__enter__()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.__exit__(*exc)


_SCOPE = UserScope(user_id="pgr-u1", role="admin", granularity_cap="village",
                    schemes=["MGNREGA"], geographies="all", tenant_id=1,
                    db_user_id=1, username="pgr-tester")

app.dependency_overrides[query_router._identity] = lambda: _SCOPE

_ENTITY_RESULT_OK = {"resolved": {"district": "EAST KHASI HILLS", "year_key": 2023},
                     "display": {"district": "East Khasi Hills", "year": "FY 2023-24"}, "notes": []}
_FAKE_ROWS = [{"amount_disbursed": 12345}]


def _patches(**overrides):
    async def _classify(_q):
        return ["MGNREGA"], pipeline.ScopeMeta(confidence=0.95, source="shortcut",
                                                reason="Named scheme: MGNREGA")

    call_n = {"n": 0}
    calls: list[str] = []

    async def _resolve_scope_gate(question, *_a, **_kw):
        call_n["n"] += 1
        calls.append(question)
        if "West Garo Hills" not in question:
            raise pipeline.ClarificationNeeded(
                "Which area?",
                options=[{"label": "West Garo Hills", "question": "expenditure for West Garo Hills"}],
                rule="scope-not-specified")
        return {"resolved": dict(_ENTITY_RESULT_OK["resolved"]),
                "display": dict(_ENTITY_RESULT_OK["display"]), "notes": []}

    async def _gen_sql(*_a, **_kw):
        return "SELECT amount_disbursed FROM curated.v_mgnrega LIMIT 5"

    async def _retrieve(*_a, **_kw):
        return []

    async def _execute_ok(sql, *_a, **_kw):
        return sql, [dict(r) for r in _FAKE_ROWS]

    async def _compose(*_a, **_kw):
        return "Total disbursement was 12,345."

    class _FakeQueryAnalyzer:
        async def analyze_query(self, *_a, **_kw):
            return None

    defaults = {
        "_classify_scheme_detailed": _classify,
        "resolve_entities": _resolve_scope_gate,
        "generate_sql": _gen_sql,
        "_execute_one_attempt": _execute_ok,
        "compose_response": _compose,
        "query_analyzer": _FakeQueryAnalyzer(),
    }
    defaults.update(overrides)
    patches = [_Patcher(pipeline, name, fn) for name, fn in defaults.items()]
    patches.append(_Patcher(pipeline.schema_retrieval, "retrieve", _retrieve))
    patches.append(_Patcher(pipeline.clarification_engine, "check_clarifications",
                            lambda *_a, **_kw: None))
    return patches, call_n, calls


try:
    pg._CHECKPOINT_DB_PATH.unlink(missing_ok=True)
    settings.LANGGRAPH_FOLLOWUP_ENABLED = False
    settings.PIPELINE_GRAPH_ENABLED = True
    settings.PIPELINE_GRAPH_CANARY_PERCENT = 0

    print("1. PIPELINE_GRAPH_ENABLED, LANGGRAPH_FOLLOWUP off — pause does NOT "
         "set pending_scope_q, checkpoint survives under session_id as thread_id")
    patches, call_n, calls = _patches()
    sid = "pgr-resume-1"
    with _Multi(patches):
        r1 = client.post("/api/query", json={"question": "total MGNREGA expenditure", "session_id": sid})
    check("200 OK", r1.status_code == 200, r1.text[:400])
    b1 = r1.json()
    check("needs_clarification True", b1.get("needs_clarification") is True, b1)
    check("clarification rule is scope-not-specified",
          b1.get("clarification", {}).get("rule") == "scope-not-specified", b1)
    sess = session_store.ensure(sid, _SCOPE.user_id)
    check("graph path did NOT set pending_scope_q (resume state lives in the "
          "checkpointer, not ConversationState — see graph_resumable)",
          sess.state.pending_scope_q is None)
    check("pipeline_graph reports this session_id as a paused thread",
          asyncio.run(pg.is_paused(sid)) is True)

    print("2. Second request on the SAME session — resumes via resume_via_graph, "
         "not re-run from node 5.1 with a bespoke-merged question")
    with _Multi(patches):
        r2 = client.post("/api/query", json={"question": "West Garo Hills", "session_id": sid})
    check("200 OK", r2.status_code == 200, r2.text[:400])
    b2 = r2.json()
    check("resume completed (no longer a clarification)", b2.get("needs_clarification") is not True, b2)
    check("exactly 2 real resolve_entities calls across BOTH HTTP requests "
          "(not 3 — the pre-fix duplicate-replay-call bug, see "
          "tests/unit/test_pipeline_graph.py scenario 8 for the same fix at the "
          "graph-internals level; this proves it holds through the full "
          "HTTP -> query.py -> resume_via_graph path too)",
          call_n["n"] == 2, call_n)
    check("the second call used the real MERGED question, never a stale replay",
          calls == ["total MGNREGA expenditure",
                    "total MGNREGA expenditure, West Garo Hills"], calls)
    check("session no longer reported paused", asyncio.run(pg.is_paused(sid)) is False)
    check("row_count reflects the real execution result", b2.get("row_count") == 1, b2)

    print("3. BOTH flags on — LANGGRAPH_FOLLOWUP_ENABLED owns the resume; "
         "pipeline_graph must NOT also keep a checkpoint alive for this session_id "
         "(the mutual-exclusivity fix — two independent checkpointers must not "
         "both think they own the same pause)")
    settings.LANGGRAPH_FOLLOWUP_ENABLED = True
    from app.orchestration import langgraph_followup as lf  # noqa: E402
    sid2 = "pgr-resume-both-flags"

    async def _lf_scope_gate(question, session=None, scope=None):
        if "West Garo Hills" not in question:
            raise pipeline.ClarificationNeeded(
                "Which area?", rule="scope-not-specified",
                options=[{"label": "West Garo Hills", "question": "expenditure for West Garo Hills"}])
        return {"route": "data", "answer": f"Answer for: {question}", "rows": [1]}

    orig_answer_question = pipeline.answer_question
    pipeline.answer_question = _lf_scope_gate
    try:
        r3 = client.post("/api/query", json={"question": "total MGNREGA expenditure", "session_id": sid2})
    finally:
        pipeline.answer_question = orig_answer_question
    check("200 OK", r3.status_code == 200, r3.text[:400])
    check("pipeline_graph itself does NOT report this session_id as paused — "
          "langgraph_followup owns it instead (thread_id=None was passed, "
          "so pipeline_graph used a fresh throwaway id and cleaned it up)",
          asyncio.run(pg.is_paused(sid2)) is False)
    check("langgraph_followup DOES report it paused (the one mechanism that "
          "actually owns this pause when both flags are on)",
          asyncio.run(lf.is_paused(sid2)) is True)

finally:
    settings.LANGGRAPH_FOLLOWUP_ENABLED = False
    settings.PIPELINE_GRAPH_ENABLED = False
    settings.PIPELINE_GRAPH_CANARY_PERCENT = 0
    app.dependency_overrides.pop(query_router._identity, None)


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL QUERY <-> PIPELINE_GRAPH REAL-RESUME (5.4) CHECKS PASSED")
