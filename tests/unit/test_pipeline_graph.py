"""
Confirms app/orchestration/pipeline_graph.py — the node-decomposed LangGraph StateGraph
built for openspec/changes/langgraph-full-pipeline-rewrite — correctly
reproduces app.orchestration.pipeline._answer_data's behavior across all 15 §5 nodes:
happy path, the bounded SQL-repair loop, auth denial, a PII/terminal
refusal, and durable §5.4 pause/resume for both pause-eligible rules that
can originate from a graph node (entity-ambiguous from 5.6,
scope-not-specified from 5.3), plus a non-pause-eligible rule (from 5.1)
propagating as a plain exception instead of interrupting.

Mocking boundary: `pipeline._classify_scheme_detailed`, `resolve_entities`,
`generate_sql`, `schema_retrieval.retrieve`, and the newly-extracted
`pipeline._execute_one_attempt` (the exact function
app.orchestration.pipeline.execute_with_repair's loop now also calls — see that
function's own docstring) are mocked; `findings.evaluate`,
`chart_spec.select_chart_type`, `premise_check.check_premises`, and
`defaults_engine.apply_defaults` run for real (pure functions, no
DB/LLM) — same split test_langgraph_query_analyzer.py already
established for exercising real downstream code inside a graph node.

No DB, no live model gateway. Run: `python tests/unit/test_pipeline_graph.py`,
exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.orchestration import pipeline  # noqa: E402
from app.orchestration import pipeline_graph as pg  # noqa: E402
from app.core.auth import AuthDecision, UserScope  # noqa: E402

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
_FAKE_SQL = "SELECT amount_disbursed FROM curated.v_mgnrega LIMIT 5"


class _Patcher:
    """Small context manager: patch a dotted attribute path, restore on exit —
    keeps each scenario's mocks scoped instead of one big shared try/finally."""
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.orig)


def _patches(**overrides):
    """Standard happy-path mocks for the LLM/DB-touching layer, with any
    per-scenario override applied on top."""
    async def _classify(_q):
        return ["MGNREGA"], pipeline.ScopeMeta(confidence=0.95, source="shortcut",
                                                reason="Named scheme: MGNREGA")

    async def _resolve(*_a, **_kw):
        return {"resolved": dict(_ENTITY_RESULT["resolved"]),
                "display": dict(_ENTITY_RESULT["display"]), "notes": []}

    async def _gen_sql(*_a, **_kw):
        return _FAKE_SQL

    async def _retrieve(*_a, **_kw):
        return []

    async def _execute_ok(sql, *_a, **_kw):
        return sql, [dict(r) for r in _FAKE_ROWS]

    async def _compose(*_a, **_kw):
        return "Total disbursement in East Khasi Hills was 12,345."

    class _FakeQueryAnalyzer:
        async def analyze_query(self, *_a, **_kw):
            return None  # QUERY_ANALYZER_ENABLED path exercised, no LLM needed

    defaults = {
        "_classify_scheme_detailed": _classify,
        "resolve_entities": _resolve,
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
    return patches


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


async def _run() -> None:
    pg._CHECKPOINT_DB_PATH.unlink(missing_ok=True)

    print("1. HAPPY PATH — matches app.orchestration.pipeline._answer_data field-for-field")
    with _Multi(_patches()):
        graph_result = await pg.answer_data_via_graph(
            "total disbursement in East Khasi Hills under MGNREGA", scope=_SCOPE)
    with _Multi(_patches()):
        direct_result = await pipeline._answer_data(
            "total disbursement in East Khasi Hills under MGNREGA", scope=_SCOPE)
    check("graph result is not a pause", graph_result.get("paused") is not True, detail=str(graph_result))
    for key in ("route", "intent", "confidence", "schemes", "resolved_entities",
               "sql", "sql_query", "row_count", "rows", "data", "answer", "findings", "chart_type"):
        check(f"field '{key}' matches _answer_data's own output",
              graph_result.get(key) == direct_result.get(key),
              detail=f"graph={graph_result.get(key)!r} direct={direct_result.get(key)!r}")
    check("scope trace schemes match", graph_result["scope"]["schemes"] == ["MGNREGA"])
    check("scope trace source matches", graph_result["scope"]["source"] == "shortcut")

    print("2. CROSS-SCHEME QUESTION — one graph, no scheme-conditional branch")
    async def _classify_multi(_q):
        return ["MGNREGA", "PMAY-G"], pipeline.ScopeMeta(confidence=0.8, source="model", reason="cross-scheme")
    with _Multi(_patches(_classify_scheme_detailed=_classify_multi)):
        multi = await pg.answer_data_via_graph("compare MGNREGA and PMAY-G in East Khasi Hills", scope=_SCOPE)
    check("both schemes carried through to the response", multi.get("schemes") == ["MGNREGA", "PMAY-G"],
          detail=str(multi.get("schemes")))

    print("3. SQL REPAIR — one failure then success, exactly one repair attempt")
    attempt_n = {"n": 0}
    async def _execute_fail_once(sql, *_a, **_kw):
        attempt_n["n"] += 1
        if attempt_n["n"] == 1:
            raise ValueError("missing column boom")
        return sql, [dict(r) for r in _FAKE_ROWS]
    async def _repair_llm(*_a, **_kw):
        return "SELECT amount_disbursed FROM curated.v_mgnrega LIMIT 5 -- repaired"
    with _Multi(_patches(_execute_one_attempt=_execute_fail_once) +
               [_Patcher(pipeline.llm, "call_sql_generator", _repair_llm)]):
        repaired = await pg.answer_data_via_graph("total disbursement under MGNREGA", scope=_SCOPE)
    check("exactly one repair attempt happened", attempt_n["n"] == 2, detail=str(attempt_n))
    check("repaired run still completes with rows", repaired.get("row_count") == 1, detail=str(repaired))

    print("4. REPAIR BUDGET EXHAUSTED — second failure propagates, not swallowed")
    async def _execute_always_fail(*_a, **_kw):
        raise ValueError("still broken")
    async def _repair_llm2(*_a, **_kw):
        return _FAKE_SQL
    raised = None
    try:
        with _Multi(_patches(_execute_one_attempt=_execute_always_fail) +
                   [_Patcher(pipeline.llm, "call_sql_generator", _repair_llm2)]):
            await pg.answer_data_via_graph("total disbursement under MGNREGA", scope=_SCOPE)
    except ValueError as e:
        raised = e
    check("a second consecutive failure raises out of the graph, not a third repair",
          raised is not None and "still broken" in str(raised), detail=str(raised))

    print("5. AUTH DENIAL — ends the run, never repaired")
    async def _execute_denied(*_a, **_kw):
        raise pipeline.SQLAuthorizationDenied(
            AuthDecision(allow=False, check="geography_scope", reason="outside your assigned district"))
    with _Multi(_patches(_execute_one_attempt=_execute_denied)):
        denied = await pg.answer_data_via_graph("total disbursement under MGNREGA", scope=_SCOPE)
    check("route is 'denied'", denied.get("route") == "denied", detail=str(denied))
    check("denied_by names the failing check", denied.get("denied_by") == "geography_scope", detail=str(denied))
    check("denial reason surfaced as the answer", denied.get("answer") == "outside your assigned district")

    print("6. PII / TERMINAL REFUSAL FROM EXECUTION — propagates, never paused")
    async def _execute_pii(*_a, **_kw):
        raise pipeline.ClarificationNeeded("that data isn't available", rule="pii-column-blocked")
    raised = None
    try:
        with _Multi(_patches(_execute_one_attempt=_execute_pii)):
            await pg.answer_data_via_graph("total disbursement under MGNREGA", scope=_SCOPE)
    except pipeline.ClarificationNeeded as e:
        raised = e
    check("propagates as ClarificationNeeded, not a pause",
          raised is not None and raised.rule == "pii-column-blocked", detail=str(raised))

    print("7. NON-PAUSE-ELIGIBLE CLARIFICATION FROM NODE 5.1 — plain exception, no interrupt()")
    raised = None
    try:
        with _Multi(_patches()):
            await pg.answer_data_via_graph("how much was disbursed under PM-KISAN", scope=_SCOPE)
    except pipeline.ClarificationNeeded as e:
        raised = e
    check("an unsupported-scheme question raises directly (not a graph pause)",
          raised is not None and raised.rule == "scheme-not-available", detail=str(raised))

    print("8. §5.4 PAUSE/RESUME — entity-ambiguous, raised from node 5.6")
    # Regression check for the 2026-09-18 fix: LangGraph replays a paused
    # node in FULL on resume, so before node_entities/node_entities_gate
    # were split, resuming this pause cost a wasted second real
    # resolve_entities() call with the STALE, pre-merge question (which
    # this mock — unlike the pre-fix version — now deterministically
    # re-raises on, since it checks question content, not just a call
    # counter) before the real merged-question attempt. Tracking the exact
    # question text of every call is what catches that a plain call-count
    # assertion couldn't.
    calls: list[str] = []
    async def _resolve_ambiguous_once(question, *_a, **_kw):
        calls.append(question)
        if "East Garo Hills" not in question:
            raise pipeline.ClarificationNeeded("Which East Garo Hills village?",
                                               options=[{"label": "A"}, {"label": "B"}],
                                               rule="entity-ambiguous", village_hint="Rongram")
        return {"resolved": dict(_ENTITY_RESULT["resolved"]),
                "display": dict(_ENTITY_RESULT["display"]), "notes": []}
    with _Multi(_patches(resolve_entities=_resolve_ambiguous_once)):
        p1 = await pg.answer_data_via_graph("job cards in Rongram under MGNREGA", scope=_SCOPE)
        check("first call pauses with the right rule",
              p1.get("paused") is True and p1["clarification"]["rule"] == "entity-ambiguous", detail=str(p1))
        p2 = await pg.resume_via_graph(p1["thread_id"], "the Rongram in East Garo Hills")
    check("resume completes (not paused again)", p2.get("paused") is not True, detail=str(p2))
    check("resumed run still produced the real answer", p2.get("row_count") == 1, detail=str(p2))
    check("exactly 2 real resolve_entities calls for 1 pause + 1 resume "
          "(not 3 — the pre-fix duplicate-replay-call bug)",
          len(calls) == 2, calls)
    check("the second call used the real MERGED question, never the stale "
          "pre-merge one — proves node_entities was not wastefully replayed",
          calls == ["job cards in Rongram under MGNREGA",
                    "job cards in Rongram under MGNREGA, the Rongram in East Garo Hills"], calls)

    print("9. §5.4 PAUSE/RESUME — scope-not-specified, raised from node 5.3")
    call_n2 = {"n": 0}
    async def _resolve_no_district(*_a, **_kw):
        call_n2["n"] += 1
        return {"resolved": {}, "display": {}, "notes": []} if call_n2["n"] == 1 else {
            "resolved": dict(_ENTITY_RESULT["resolved"]), "display": dict(_ENTITY_RESULT["display"]), "notes": []}
    # clarify_rules rule 3 ASKS for the area only when the scheme's rules file
    # has no missing_geography default (otherwise it applies the disclosed
    # statewide default) — take the default away so node 5.3 pauses.
    from app.nlu import clarify_rules
    _orig_default = clarify_rules._default
    clarify_rules._default = lambda schemes, cond: (
        None if cond == "missing_geography" else _orig_default(schemes, cond))
    try:
        with _Multi(_patches(resolve_entities=_resolve_no_district)):
            s1 = await pg.answer_data_via_graph("total job cards issued under MGNREGA", scope=_SCOPE)
    finally:
        clarify_rules._default = _orig_default
    with _Multi(_patches(resolve_entities=_resolve_no_district)):
        check("pauses on scope-not-specified",
              s1.get("paused") is True and s1["clarification"]["rule"] == "scope-not-specified", detail=str(s1))
        s2 = await pg.resume_via_graph(s1["thread_id"], "East Khasi Hills")
    check("resume completes with a real result", s2.get("row_count") == 1, detail=str(s2))

    print("10. CHECKPOINTER DURABILITY — the pause actually persisted to disk, not memory")
    check("the checkpoint file exists and is non-empty after scenarios 8/9's pauses",
          pg._CHECKPOINT_DB_PATH.exists() and pg._CHECKPOINT_DB_PATH.stat().st_size > 0,
          detail=str(pg._CHECKPOINT_DB_PATH))
    # answer_data_via_graph/resume_via_graph each open their own fresh
    # AsyncSqliteSaver connection (_checkpointer_context()) rather than
    # sharing one in-process object — scenarios 8/9's pause (one call) and
    # resume (a separate, later call) already only share the file on disk,
    # never in-process memory, the same property a real process restart
    # would have. Confirmed here by checking the file itself outlived both
    # calls, rather than asserting the property abstractly.

    print("11. node_findings runs BEFORE node_compose (2026-09-18 parity fix "
         "with app.orchestration.pipeline._answer_data's own findings-before-compose reorder)")
    _compose_kwargs: dict = {}

    async def _compose_capture(*_a, **kw):
        _compose_kwargs.clear()
        _compose_kwargs.update(kw)
        return "captured"

    async def _execute_many_rows(sql, *_a, **_kw):
        return sql, [dict(_FAKE_ROWS[0]) for _ in range(150)]

    with _Multi(_patches(_execute_one_attempt=_execute_many_rows,
                         compose_response=_compose_capture)):
        many = await pg.answer_data_via_graph("total disbursement under MGNREGA", scope=_SCOPE)
    check("a 150-row result reached compose_response with a non-empty "
          "result_findings kwarg (large_result_set fires at >100 rows) — "
          "proves node_findings' state is visible to node_compose, not just "
          "that both nodes ran independently",
          bool(_compose_kwargs.get("result_findings")), detail=str(_compose_kwargs))
    if _compose_kwargs.get("result_findings"):
        check("the large_result_set finding specifically is the one that reached compose_response",
              any(f.get("type") == "large_result_set" for f in _compose_kwargs["result_findings"]),
              detail=str(_compose_kwargs["result_findings"]))
    check("the graph's own final response still carries the same findings "
          "as a sibling field (unaffected by also feeding them to compose)",
          bool(many.get("findings")), detail=str(many.get("findings")))


asyncio.run(_run())

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL PIPELINE_GRAPH (§5.1-5.15 LangGraph decomposition) CHECKS PASSED")
