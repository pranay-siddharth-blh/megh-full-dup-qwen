"""
openspec change `query-analyzer-consolidation` — app/query_analyzer.py, the
structured "query analyzer" node (pipeline architecture doc §5.2). No DB, no
live model gateway: llm.call_classifier is monkeypatched, same stance as
tests/test_scope_scheme_classifier.py and tests/test_intent_classifier.py.
Run: `python tests/test_query_analyzer.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import llm, query_analyzer  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def _no_model_call(*_a, **_kw):
    raise AssertionError("analyze_query should not need the model when the fast-path decides query_type "
                          "and a stub is asserting isolation")


async def _stub_llm(payload: str):
    async def _inner(*_a, **_kw):
        return payload
    return _inner


print("1. RANKING FAST-PATH — query_type + limit from regex alone")


async def _run_ranking_checks():
    orig = llm.call_classifier

    async def _returns_metric_only(*_a, **_kw):
        return '{"query_type": "lookup", "metric": "disbursement", "time_scope": "", ' \
               '"intent_summary": "top blocks by disbursement", "ambiguous_terms": []}'
    llm.call_classifier = _returns_metric_only
    try:
        entity_result = {"resolved": {}, "display": {}, "notes": []}
        a = await query_analyzer.analyze_query("top 5 blocks by disbursement", ["MGNREGA"], entity_result)
        check("ranking fast-path overrides the model's query_type guess",
              a["query_type"] == "ranking", detail=str(a))
        check("explicit count parsed into limit", a.get("limit") == 5, detail=str(a.get("limit")))
        check("metric still comes from the model call", a["metric"] == "disbursement", detail=str(a["metric"]))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_ranking_checks())


print("2. COMPARISON FAST-PATH")


async def _run_comparison_checks():
    orig = llm.call_classifier

    async def _returns_ok(*_a, **_kw):
        return '{"query_type": "aggregation", "metric": "expenditure", "time_scope": "",' \
               ' "intent_summary": "compare two districts", "ambiguous_terms": []}'
    llm.call_classifier = _returns_ok
    try:
        entity_result = {"resolved": {"district_list": ["EAST KHASI HILLS", "WEST GARO HILLS"]},
                          "display": {"district": "East Khasi Hills and West Garo Hills"}, "notes": []}
        a = await query_analyzer.analyze_query("compare EKH and WGH expenditure", ["MGNREGA"], entity_result)
        check("comparison fast-path overrides the model's query_type guess",
              a["query_type"] == "comparison", detail=str(a))
        check("resolved districts appear in entities.districts",
              a["entities"]["districts"] == ["East Khasi Hills and West Garo Hills"], detail=str(a["entities"]))
        check("granularity is district when only districts are resolved",
              a["granularity"] == "district", detail=a["granularity"])
    finally:
        llm.call_classifier = orig


asyncio.run(_run_comparison_checks())


print("3. LLM FALLBACK — no fast-path cue, model decides query_type/time_scope")


async def _run_llm_fallback_checks():
    orig = llm.call_classifier

    async def _returns_lookup(*_a, **_kw):
        return '{"query_type": "lookup", "metric": "sanctioned houses", "time_scope": "FY 2022-23",' \
               ' "intent_summary": "how many houses were sanctioned", "ambiguous_terms": []}'
    llm.call_classifier = _returns_lookup
    try:
        entity_result = {"resolved": {"village_code": "V123"}, "display": {"village": "Sample Village"},
                          "notes": []}
        a = await query_analyzer.analyze_query("sanctioned houses in Sample Village",
                                                 ["PMAY-G"], entity_result)
        check("no fast-path cue -> model's query_type used", a["query_type"] == "lookup", detail=str(a))
        check("no resolved year -> model's time_scope used", a["time_scope"] == "FY 2022-23",
              detail=str(a["time_scope"]))
        check("village granularity when a village is resolved", a["granularity"] == "village",
              detail=a["granularity"])
        check("village appears in entities.villages", a["entities"]["villages"] == ["Sample Village"],
              detail=str(a["entities"]))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_llm_fallback_checks())


print("4. RESOLVED YEAR WINS OVER MODEL'S time_scope GUESS")


async def _run_year_precedence_checks():
    orig = llm.call_classifier

    async def _returns_other_year(*_a, **_kw):
        return '{"query_type": "aggregation", "metric": "person-days", "time_scope": "last 3 years",' \
               ' "intent_summary": "total person-days", "ambiguous_terms": []}'
    llm.call_classifier = _returns_other_year
    try:
        entity_result = {"resolved": {"year_key": 2023}, "display": {"year": "FY 2023-24"}, "notes": []}
        a = await query_analyzer.analyze_query("person-days in 2023-24", ["MGNREGA"], entity_result)
        check("deterministic resolved year overrides the model's time_scope guess",
              a["time_scope"] == "FY 2023-24", detail=str(a["time_scope"]))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_year_precedence_checks())


print("5. NOT-FOUND NOTE SURFACED AS AN AMBIGUOUS ENTRY")


async def _run_notes_checks():
    orig = llm.call_classifier

    async def _returns_ok(*_a, **_kw):
        return '{"query_type": "aggregation", "metric": "expenditure", "time_scope": "",' \
               ' "intent_summary": "total expenditure", "ambiguous_terms": []}'
    llm.call_classifier = _returns_ok
    try:
        entity_result = {"resolved": {}, "display": {},
                          "notes": ["'Foo Bar' is not a known district — say so, do not filter on it."]}
        a = await query_analyzer.analyze_query("expenditure in Foo Bar", ["MGNREGA"], entity_result)
        check("not-found note produces one ambiguous entry", len(a["ambiguous"]) == 1, detail=str(a["ambiguous"]))
        check("ambiguous entry names the unresolved term",
              a["ambiguous"][0]["term"] == "Foo Bar", detail=str(a["ambiguous"]))
        check("ambiguous entry's kind is 'district'",
              a["ambiguous"][0]["kind"] == "district", detail=str(a["ambiguous"]))
        check("not-found note's origin is 'entity_note' (openspec/changes/"
              "query-analyzer-predicate-integration)",
              a["ambiguous"][0]["origin"] == "entity_note", detail=str(a["ambiguous"]))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_notes_checks())


print("5b. LLM-FLAGGED AMBIGUOUS TERM CARRIES origin='llm' (distinct from entity notes)")


async def _run_llm_ambiguous_origin_checks():
    orig = llm.call_classifier

    async def _returns_ambiguous_metric(*_a, **_kw):
        return '{"query_type": "aggregation", "metric": "", "time_scope": "",' \
               ' "intent_summary": "unclear metric question",' \
               ' "ambiguous_terms": [{"term": "performance", "kind": "metric",' \
               ' "why": "no specific metric named"}]}'
    llm.call_classifier = _returns_ambiguous_metric
    try:
        entity_result = {"resolved": {}, "display": {}, "notes": []}
        a = await query_analyzer.analyze_query("how is MGNREGA performance", ["MGNREGA"], entity_result)
        check("LLM-flagged ambiguous term is present", len(a["ambiguous"]) == 1, detail=str(a["ambiguous"]))
        check("LLM-flagged ambiguous term's origin is 'llm'",
              a["ambiguous"][0]["origin"] == "llm", detail=str(a["ambiguous"]))
        check("LLM-flagged ambiguous term keeps its own term/kind/why",
              a["ambiguous"][0]["term"] == "performance" and a["ambiguous"][0]["kind"] == "metric",
              detail=str(a["ambiguous"]))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_llm_ambiguous_origin_checks())


print("6. MODEL-CALL FAILURE DOES NOT RAISE — returns None")


async def _run_failure_checks():
    orig = llm.call_classifier

    async def _raises(*_a, **_kw):
        raise RuntimeError("gateway exploded")
    llm.call_classifier = _raises
    try:
        entity_result = {"resolved": {}, "display": {}, "notes": []}
        a = await query_analyzer.analyze_query("what is the total expenditure", ["MGNREGA"], entity_result)
        check("a model-call exception is swallowed, not raised", a is None, detail=str(a))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_failure_checks())


print("7. UNUSABLE MODEL OUTPUT DEGRADES GRACEFULLY, STILL RETURNS AN OBJECT")


async def _run_garbage_checks():
    orig = llm.call_classifier

    async def _returns_garbage(*_a, **_kw):
        return "not json at all"
    llm.call_classifier = _returns_garbage
    try:
        entity_result = {"resolved": {}, "display": {}, "notes": []}
        a = await query_analyzer.analyze_query("what is the total expenditure", ["MGNREGA"], entity_result)
        check("unusable model output still returns an analysis object", a is not None, detail=str(a))
        check("query_type falls back to aggregation cue from the question text",
              a["query_type"] == "aggregation", detail=str(a))
        check("metric is None rather than a crash", a["metric"] is None, detail=str(a))
        check("intent_summary has a deterministic fallback, not empty",
              bool(a["intent_summary"]), detail=str(a))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_garbage_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL QUERY ANALYZER (5.2) CHECKS PASSED")
