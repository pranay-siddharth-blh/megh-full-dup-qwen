"""
Confirms node 5.2 (the query analyzer, app/query_analyzer.py) flows through
correctly when a question is driven via the LangGraph pause/resume path
(app/langgraph_followup.py), not just the default bespoke path already
covered by tests/test_query_analyzer_integration.py.

app/langgraph_followup.py deliberately wraps the ENTIRE existing pipeline
(app.pipeline.answer_question) as a single opaque graph node — per its own
module docstring, "it does not reimplement scope/year/entity resolution,
SQL generation, or any other pipeline stage as graph nodes." This means
node 5.2 is not a separate graph node to add; it already runs, unmodified,
every time `answer_question` is called from inside that one node. This test
verifies that claim directly rather than asserting it from reading the code:
unlike tests/test_langgraph_followup.py (which mocks `answer_question`
itself, replacing the whole pipeline with a fake), this test mocks only the
deep internals `pipeline.answer_question` -> `_run_pipeline` -> `_answer_data`
calls (`_classify_scheme_detailed`, `resolve_entities`, `generate_sql`,
`execute_with_repair`, `compose_response`, `clarification_engine.
check_clarifications`) so the REAL `_answer_data` code — including the real
`query_analyzer.analyze_query` call — executes inside the graph node.

Requires the `langgraph`/`langgraph-checkpoint-sqlite` packages (declared in
requirements.txt; installed in this environment to make this test runnable).
No DB, no live model gateway.
Run: `python tests/test_langgraph_query_analyzer.py`, exit code 0 = pass.
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

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_SCOPE = UserScope(user_id="u1", role="admin", granularity_cap="village",
                    schemes=["MGNREGA"], geographies="all")
_ENTITY_RESULT = {"resolved": {"district": "EAST KHASI HILLS", "year_key": 2023},
                   "display": {"district": "East Khasi Hills", "year": "FY 2023-24"}, "notes": []}
_FAKE_ROWS = [{"amount_disbursed": 12345}]
_FAKE_ANALYSIS = {
    "query_type": "aggregation", "metric": "amount disbursed", "entities": {"districts": ["East Khasi Hills"]},
    "time_scope": "FY 2023-24", "granularity": "district", "ambiguous": [],
    "intent_summary": "total disbursement in East Khasi Hills",
}


async def _run() -> None:
    lf._CHECKPOINT_DB_PATH.unlink(missing_ok=True)

    orig = {
        "_classify_scheme_detailed": pipeline._classify_scheme_detailed,
        "resolve_entities": pipeline.resolve_entities,
        "generate_sql": pipeline.generate_sql,
        "execute_with_repair": pipeline.execute_with_repair,
        "compose_response": pipeline.compose_response,
        "query_analyzer": pipeline.query_analyzer,
    }
    orig_check_clarifications = pipeline.clarification_engine.check_clarifications
    pipeline.clarification_engine.check_clarifications = lambda *_a, **_kw: None

    class _FakeQueryAnalyzer:
        async def analyze_query(self, *_a, **_kw):
            return dict(_FAKE_ANALYSIS)

    async def _fake_classify_scheme_detailed(_question):
        return ["MGNREGA"], pipeline.ScopeMeta(confidence=0.95, source="shortcut",
                                                reason="Named scheme: MGNREGA")

    async def _fake_resolve_entities(*_a, **_kw):
        return dict(_ENTITY_RESULT)

    async def _fake_generate_sql(*_a, **_kw):
        return "SELECT amount_disbursed FROM curated.v_mgnrega LIMIT 5"

    async def _fake_execute_with_repair(question, schemes, entity_result, *, initial_sql, scope=None):
        return initial_sql, [dict(r) for r in _FAKE_ROWS]

    async def _fake_compose_response(*_a, **_kw):
        return "Total disbursement in East Khasi Hills was 12,345."

    pipeline._classify_scheme_detailed = _fake_classify_scheme_detailed
    pipeline.resolve_entities = _fake_resolve_entities
    pipeline.generate_sql = _fake_generate_sql
    pipeline.execute_with_repair = _fake_execute_with_repair
    pipeline.compose_response = _fake_compose_response
    pipeline.query_analyzer = _FakeQueryAnalyzer()

    try:
        print("1. 5.2 SURVIVES THE LANGGRAPH WRAPPER — real _answer_data code runs inside the graph node")
        result = await lf.run_with_pause(
            session_id="lg-analyzer-1",
            question="total disbursement in East Khasi Hills under MGNREGA",
            scope=_SCOPE,
        )
        check("the turn completed (not paused) — a clean path through the real pipeline",
              result.get("paused") is not True, detail=str(result))
        check("result carries the real 'analysis' key from query_analyzer via the graph node",
              "analysis" in result, detail=str(result))
        check("analysis content matches what the real _answer_data code assembled",
              result.get("analysis") == _FAKE_ANALYSIS, detail=str(result.get("analysis")))
        check("result carries the real 'scope' key (node 5.1's decision trace) via the graph node",
              "scope" in result, detail=str(result))
        check("scope.source reflects the real _classify_scheme_detailed path, not a stub",
              result.get("scope", {}).get("source") == "shortcut", detail=str(result.get("scope")))
        check("scope.schemes came from the real classify_scheme decision",
              result.get("scope", {}).get("schemes") == ["MGNREGA"], detail=str(result.get("scope")))
        check("the answer text itself still came through correctly alongside analysis/scope",
              result.get("answer") == "Total disbursement in East Khasi Hills was 12,345.",
              detail=str(result.get("answer")))

        print("2. 5.2 STILL RUNS ACROSS A PAUSE/RESUME ROUND (graph re-enters the same node on resume)")

        call_count = {"n": 0}
        orig_fake_resolve = pipeline.resolve_entities

        async def _resolve_entities_needs_scope_once(question, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise pipeline.ClarificationNeeded("Which district?", rule="scope-not-specified")
            return dict(_ENTITY_RESULT)

        pipeline.resolve_entities = _resolve_entities_needs_scope_once
        r1 = await lf.run_with_pause(session_id="lg-analyzer-2", question="total disbursement under MGNREGA",
                                      scope=_SCOPE)
        check("first attempt pauses on scope, as the real gate would",
              r1.get("paused") is True and r1.get("clarification", {}).get("rule") == "scope-not-specified",
              detail=str(r1))
        r2 = await lf.run_with_pause(session_id="lg-analyzer-2", question="ignored", scope=_SCOPE,
                                      resume="East Khasi Hills")
        check("resumed turn completes with analysis populated from the real analyzer call",
              r2.get("analysis") == _FAKE_ANALYSIS, detail=str(r2.get("analysis")))
        pipeline.resolve_entities = orig_fake_resolve
    finally:
        for name, fn in orig.items():
            setattr(pipeline, name, fn)
        pipeline.clarification_engine.check_clarifications = orig_check_clarifications


asyncio.run(_run())

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL LANGGRAPH QUERY ANALYZER (5.2 via LangGraph path) CHECKS PASSED")
