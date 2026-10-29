"""
E1 stage 2a + RAG plan E2 (2026-10-29, D-085): for a new question the query plan
starts beside the guardrail model call, so the two classifier calls overlap.

Before: the guardrail call ran alone, in sequence, on every new question, and the
plan was a second classifier call made after the answer (D-078). Now the plan is
started right before the guardrail call (c14 _guardrail_check), nothing waits for
it, a guardrail refusal cancels it, and the end-of-turn shadow reuses it.
"""
import asyncio
import types

import pytest

from app import guardrails, llm, pipeline, query_plan
from app.config import settings

PLAN = {"intent": "DATA", "schemes": ["MGNREGA"], "measure": "none", "place_level": "district",
        "place_name": "Ri Bhoi", "group_by": "none", "all_years": False, "shape": "single_value",
        "order": "none", "years": [2023], "top_n": None}


def _session():
    return types.SimpleNamespace(turn_context={})


@pytest.fixture
def plan_on(monkeypatch):
    monkeypatch.setattr(settings, "QUERY_PLAN_SHADOW", True)
    monkeypatch.setattr(settings, "QUERY_PLAN_IN_TURN", True)
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_ENABLED", True)


def _stub_models(monkeypatch, guard_reply='{"verdict": "SAFE", "category": "none"}'):
    """Both fakes record when they start and end, and sleep, so an overlap shows."""
    log = []

    async def fake_guard(**kw):
        log.append(("guard", "start"))
        await asyncio.sleep(0.05)
        log.append(("guard", "end"))
        return guard_reply

    async def fake_extract(question):
        log.append(("plan", "start", question))
        await asyncio.sleep(0.05)
        log.append(("plan", "end"))
        return dict(PLAN)
    monkeypatch.setattr(llm, "call_model", fake_guard)
    monkeypatch.setattr(query_plan, "extract", fake_extract)
    return log


def test_the_plan_and_the_guardrail_calls_overlap(monkeypatch, plan_on):
    log = _stub_models(monkeypatch)
    s = _session()
    q = "total MGNREGA expenditure in Ri Bhoi in 2023-24"

    async def run():
        r = await pipeline._guardrail_check(q, q, False, False, session=s)
        plan = await query_plan.turn_plan(s)
        return r, plan
    r, plan = asyncio.run(run())
    assert r is None and plan["schemes"] == ["MGNREGA"]
    kinds = [e[:2] for e in log]
    # both started before either finished
    assert kinds.index(("plan", "start")) < kinds.index(("guard", "end"))
    assert kinds.index(("guard", "start")) < kinds.index(("plan", "end"))
    assert log[0] == ("plan", "start", q) or ("plan", "start", q) in log


@pytest.mark.parametrize("q,resumed,ctx", [
    ("and in 2022-23?", False, True),            # a follow-up: rewritten later
    ("2023", True, False),                        # a pause reply
    ("hi", False, False),                         # a greeting: no model call at all
])
def test_no_plan_is_started_where_the_guardrail_model_is_skipped_or_words_will_change(
        monkeypatch, plan_on, q, resumed, ctx):
    log = _stub_models(monkeypatch)
    s = _session()
    asyncio.run(pipeline._guardrail_check(q, q, resumed, ctx, session=s))
    assert "query_plan" not in s.turn_context
    assert not any(e[0] == "plan" for e in log)


def test_the_flag_off_keeps_stage_one_timing(monkeypatch, plan_on):
    monkeypatch.setattr(settings, "QUERY_PLAN_IN_TURN", False)
    log = _stub_models(monkeypatch)
    s = _session()
    q = "houses completed in Ri Bhoi"
    asyncio.run(pipeline._guardrail_check(q, q, False, False, session=s))
    assert "query_plan" not in s.turn_context and not any(e[0] == "plan" for e in log)


def test_no_session_means_no_plan(monkeypatch, plan_on):
    log = _stub_models(monkeypatch)
    q = "houses completed in Ri Bhoi"
    assert asyncio.run(pipeline._guardrail_check(q, q, False, False, session=None)) is None
    assert not any(e[0] == "plan" for e in log)


def test_a_guardrail_refusal_cancels_the_plan(monkeypatch, plan_on):
    _stub_models(monkeypatch, guard_reply='{"verdict": "UNSAFE", "category": "other"}')
    s = _session()
    q = "something the model thinks is harmful"
    t = pipeline._new_turn(q)
    t.update(raw_question=q, question=q, scope_resumed=False, has_context=False)
    r = asyncio.run(pipeline._turn_edge_stage(t, s, None))
    assert r["route"] == "edge" and r["edge_type"] == "unsafe"
    assert "query_plan" not in s.turn_context


def test_the_shadow_reuses_the_in_turn_plan(monkeypatch, plan_on, tmp_path):
    monkeypatch.setattr(settings, "QUERY_PLAN_FILE", str(tmp_path / "plan.jsonl"))
    _stub_models(monkeypatch)
    calls = []

    async def no_second_call(question):
        calls.append(question)
        return dict(PLAN)
    s = _session()
    q = "total MGNREGA expenditure in Ri Bhoi in 2023-24"
    result = {"route": "data", "schemes": ["MGNREGA"], "sql": "SELECT 1",
              "resolved_entities": {"district": "RI BHOI", "year_key": 2023}}

    async def run():
        await pipeline._guardrail_check(q, q, False, False, session=s)
        monkeypatch.setattr(query_plan, "extract", no_second_call)
        pending = query_plan.take_for_turn(s)
        return await query_plan.shadow(q, q, result, pending=pending)
    rec = asyncio.run(run())
    assert calls == []                       # no second classifier call
    assert rec["plan_from"] == "turn" and rec["plan_question"] == q
    assert rec["agree"]["schemes"] is True and isinstance(rec["ms"], int)
    assert "query_plan" not in s.turn_context


def test_without_an_in_turn_plan_the_shadow_still_builds_one_after(monkeypatch, plan_on, tmp_path):
    monkeypatch.setattr(settings, "QUERY_PLAN_FILE", str(tmp_path / "plan.jsonl"))
    _stub_models(monkeypatch)
    rec = asyncio.run(query_plan.shadow("houses in Ri Bhoi", "houses in Ri Bhoi",
                                        {"route": "data", "schemes": ["PMAY-G"]}))
    assert rec["plan_from"] == "after" and "plan_question" not in rec


def test_an_unused_plan_is_cancelled_when_the_turn_is_not_data_or_knowledge(monkeypatch, plan_on):
    async def slow_extract(question):
        await asyncio.sleep(10)
        return dict(PLAN)
    monkeypatch.setattr(query_plan, "extract", slow_extract)
    s = _session()

    async def run():
        query_plan.start_for_turn(s, "what can you do")
        pending = query_plan.take_for_turn(s)
        rec = await query_plan.shadow("what can you do", "what can you do", {"route": "edge"},
                                      pending=pending)
        await asyncio.sleep(0)
        return rec, pending["task"]
    rec, task = asyncio.run(run())
    assert rec is None and task.cancelled()


def test_a_failing_plan_never_breaks_the_turn(monkeypatch, plan_on):
    async def boom(question):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(query_plan, "extract", boom)
    monkeypatch.setattr(llm, "call_model", _ok_guard)
    s = _session()
    q = "houses completed in Ri Bhoi"

    async def run():
        r = await pipeline._guardrail_check(q, q, False, False, session=s)
        return r, await query_plan.turn_plan(s)
    assert asyncio.run(run()) == (None, None)


async def _ok_guard(**kw):
    return '{"verdict": "SAFE", "category": "none"}'


def test_the_guardrail_outage_path_still_works_with_the_plan_running(monkeypatch, plan_on):
    async def down(**kw):
        raise TimeoutError("gateway slow")
    monkeypatch.setattr(llm, "call_model", down)
    monkeypatch.setattr(query_plan, "extract", lambda q: asyncio.sleep(0, result=dict(PLAN)))
    monkeypatch.setattr(guardrails, "outage_monitor", guardrails._OutageMonitor())
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_FAIL_CLOSED", False)
    s = _session()
    q = "where is ganja sold cheapest in shillong"
    r = asyncio.run(pipeline._guardrail_check(q, q, False, False, session=s))
    assert r is not None and r[0]["type"] == "unverified"


def test_in_turn_planning_is_off_by_default():
    # Measured live 2026-10-29 (D-085): turned on, every new question got slower
    # (median 11.8 s -> 14.1 s) because the two 4B calls queue on the gateway.
    # Turn it on only with a stage that reads the plan and drops its own call.
    from app.config import Settings
    assert Settings.model_fields["QUERY_PLAN_IN_TURN"].default is False
