"""
openspec changes `query-analyzer-consolidation` and
`query-analyzer-predicate-integration` — end-to-end integration check
through app/pipeline.py::_answer_data confirming both `analysis` (node 5.2)
and `scope` (node 5.1's decision trace) reach the final response dict, wired
exactly the way web/ai_query.html's NODE 1/NODE 2 renderers expect, and that
an `origin: "llm"` ambiguous entry is disclosed as a note (while an
`origin: "entity_note"` one is not disclosed a second time). Every sub-step
(_classify_scheme_detailed, resolve_entities, generate_sql,
execute_with_repair, compose_response, query_analyzer.analyze_query) is
monkeypatched at the module-attribute level — same stance
tests/test_pii_guard.py already uses for _answer_data-adjacent checks. No DB,
no live model gateway.
Run: `python tests/test_query_analyzer_integration.py`, exit code 0 = pass.
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

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_ENTITY_RESULT = {"resolved": {"district": "EAST KHASI HILLS", "year_key": 2023},
                   "display": {"district": "East Khasi Hills", "year": "FY 2023-24"}, "notes": []}
_FAKE_ROWS = [{"amount_disbursed": 12345}]
_FAKE_ANALYSIS = {
    "query_type": "aggregation", "metric": "amount disbursed", "entities": {"districts": ["East Khasi Hills"]},
    "time_scope": None, "granularity": "district", "ambiguous": [], "intent_summary": "total disbursement",
}


async def _run():
    orig = {
        "_classify_scheme_detailed": pipeline._classify_scheme_detailed,
        "resolve_entities": pipeline.resolve_entities,
        "generate_sql": pipeline.generate_sql,
        "execute_with_repair": pipeline.execute_with_repair,
        "compose_response": pipeline.compose_response,
        "query_analyzer": pipeline.query_analyzer,
    }
    orig_check_clarifications = pipeline.clarification_engine.check_clarifications
    # Node 5.3 is real, unrelated business logic this integration test isn't
    # exercising — neutralize it so it can't turn an unrelated YAML/hardcoded
    # rule match into a ClarificationNeeded for this fixture's fake question.
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
        print("1. END-TO-END — analysis AND scope both reach the final response")
        result = await pipeline._answer_data("total disbursement in East Khasi Hills under MGNREGA",
                                              is_followup=False)
        check("response has a top-level 'analysis' key", "analysis" in result)
        check("response has a top-level 'scope' key", "scope" in result)
        check("analysis matches what query_analyzer returned", result.get("analysis") == _FAKE_ANALYSIS,
              detail=str(result.get("analysis")))
        check("scope.schemes matches classify_scheme's decision", result.get("scope", {}).get("schemes") == ["MGNREGA"],
              detail=str(result.get("scope")))
        check("scope.source reflects the shortcut path", result.get("scope", {}).get("source") == "shortcut",
              detail=str(result.get("scope")))
        check("scope.is_followup reflects the is_followup argument passed in",
              result.get("scope", {}).get("is_followup") is False, detail=str(result.get("scope")))
        check("scope.in_scope is true on a successful answer", result.get("scope", {}).get("in_scope") is True)
        check("existing fields (answer/rows/schemes) are still present and correct",
              result.get("answer") and result.get("schemes") == ["MGNREGA"] and result.get("rows") == _FAKE_ROWS,
              detail=str(result))

        print("2. END-TO-END — is_followup=True threads through to scope.is_followup")
        # By the time _answer_data runs, a follow-up fragment has already been
        # rewritten to a standalone question by rewrite_followup (see
        # _run_pipeline) — is_followup is carried as a separate flag, not
        # re-derived from the (already-standalone) question text here.
        result2 = await pipeline._answer_data("total disbursement in East Khasi Hills under MGNREGA",
                                               is_followup=True)
        check("is_followup=True is reflected in scope", result2.get("scope", {}).get("is_followup") is True,
              detail=str(result2.get("scope")))

        print("3. END-TO-END — a query_analyzer failure never breaks the answer")

        class _FailingQueryAnalyzer:
            async def analyze_query(self, *_a, **_kw):
                raise RuntimeError("boom")

        pipeline.query_analyzer = _FailingQueryAnalyzer()
        result3 = await pipeline._answer_data("total disbursement in East Khasi Hills under MGNREGA")
        check("response is still returned despite the analyzer raising", result3.get("route") == "data",
              detail=str(result3))
        check("analysis is None/omitted rather than propagating the exception",
              result3.get("analysis") is None, detail=str(result3.get("analysis")))
        check("answer text is unaffected by the analyzer failure",
              result3.get("answer") == "Total disbursement in East Khasi Hills was 12,345.")

        print("4. openspec/changes/query-analyzer-predicate-integration — "
              "origin='llm' ambiguity is disclosed as a note; origin='entity_note' is not duplicated")

        captured_notes: list = []

        async def _capturing_compose_response(question, sql, rows, *, notes=None, **_kw):
            captured_notes.clear()
            captured_notes.extend(notes or [])
            return "Total disbursement in East Khasi Hills was 12,345."

        class _AmbiguousQueryAnalyzer:
            async def analyze_query(self, *_a, **_kw):
                return {
                    **_FAKE_ANALYSIS,
                    "ambiguous": [
                        {"term": "Foo Bar", "kind": "district", "why": "not a known district",
                         "origin": "entity_note"},
                        {"term": "performance", "kind": "metric", "why": "no specific metric named",
                         "origin": "llm"},
                    ],
                }

        pipeline.compose_response = _capturing_compose_response
        pipeline.query_analyzer = _AmbiguousQueryAnalyzer()
        await pipeline._answer_data("MGNREGA performance in East Khasi Hills")
        check("exactly one disclosed note was added (the origin='llm' entry only)",
              len(captured_notes) == 1, detail=str(captured_notes))
        check("the disclosed note mentions the llm-flagged term",
              captured_notes and "performance" in captured_notes[0], detail=str(captured_notes))
        check("the disclosed note does NOT mention the entity_note-origin term "
              "(would be a duplicate disclosure)",
              not any("Foo Bar" in n for n in captured_notes), detail=str(captured_notes))
    finally:
        for name, fn in orig.items():
            setattr(pipeline, name, fn)
        pipeline.clarification_engine.check_clarifications = orig_check_clarifications


asyncio.run(_run())

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL QUERY ANALYZER INTEGRATION (5.2 end-to-end) CHECKS PASSED")
