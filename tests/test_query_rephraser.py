"""The query rephraser: graph node `rephrase`, between followup and route (D-037).

A messy NEW question (typos, Hinglish, voice-to-text, no question shape) is
rewritten into one clean English question before routing. It changes wording
only: a rewrite that adds, drops or changes a scheme, place, year, number,
measure or a name the user typed is rejected and the original goes on.
Follow-ups, pause replies and clean questions skip the model call.

Nothing here needs the VPN: the model is stubbed.
"""
import asyncio
import inspect
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import entity_resolver, llm, pipeline as p, pipeline_graph as pg  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import Session  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()


def _session():
    return Session(session_id="r-1", user_id="u", created=time.time(), last_seen=time.time())


def _model(monkeypatch, reply):
    """Stub the rephraser model: `reply` is a string, or an exception to raise."""
    calls = []

    async def fake(prompt):
        calls.append(prompt)
        if isinstance(reply, BaseException):
            raise reply
        return reply
    monkeypatch.setattr(llm, "call_rephraser", fake)
    return calls


# ── 1. Which questions need it ─────────────────────────────────────────────

@pytest.mark.parametrize("question", [
    "manrega persondays ekh 23-24 how much",                       # no question shape, typo
    "pmay mein kitne ghar sanction hue ri bhoi 2022-23",            # Hinglish
    "focus plus wgh paisa kitna diya",                              # Hinglish
    "mahila ko kaam ke din mgnrega west garo hills 2024-25",        # Hinglish phrase
    "how many aplications under cm elevate in shillong",            # typo
    "mgnrega person days east khasi hills",                         # no question shape
])
def test_messy_questions_need_a_rephrase(question):
    assert p._needs_rephrase(question)


@pytest.mark.parametrize("question", [
    "How many PMAY-G houses were sanctioned in Ri Bhoi in 2023-24?",
    "How many applications under CM Elevate in East Khasi Hills?",
    "Total MGNREGA person-days in East Khasi Hills in 2023-24",
    "How much was disbursed under Focus Plus in Mawlai block?",
    "Which financial years are there in Focus Plus?",
    "Compare MGNREGA person-days in West Garo Hills and East Garo Hills",
])
def test_clean_questions_skip_the_model(question):
    assert not p._needs_rephrase(question)


def test_too_long_or_empty_is_left_alone(monkeypatch):
    assert not p._needs_rephrase("")
    assert not p._needs_rephrase("x" * (settings.QUERY_REPHRASE_MAX_CHARS + 1))


# ── 2. The safety check: wording may change, meaning may not ───────────────

@pytest.mark.parametrize("original,rephrased", [
    ("MGNREGA persondays ekh 23-24 how much",
     "How many MGNREGA person-days were generated in ekh in FY 2023-24?"),
    ("pmay mein kitne ghar sanction hue ri bhoi 2022-23",
     "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?"),
    ("how many aplications under CM Elevate in shillong",
     "How many applications are there under CM Elevate in shillong?"),
    ("Focus Plus wgh paisa kitna diya", "How much money was given under Focus Plus in wgh?"),
    ("Focus Plus person days mawlwai all years",
     "How many person-days are there under Focus Plus in mawlwai across all financial years?"),
    ("mahila ko kaam ke din MGNREGA west garo hills 2024-25",
     "How many person-days were given to women under MGNREGA in west garo hills in FY 2024-25?"),
    ("pmay houses ri bhoi more than 50", "Which PMAY-G houses in ri bhoi number more than 50?"),
    # live 2026-10-07: chat filler may go; a fixed-up scheme name is one scheme
    ("total money spent mgnrega east garo hills 2022-23 plz",
     "How much money was spent under MGNREGA in east garo hills in FY 2022-23?"),
    ("CM Elevate Legacy leagcy sanctioned amount 2024-25",
     "What is the sanctioned amount under CM Elevate Legacy in FY 2024-25?"),
])
def test_a_faithful_rephrase_is_accepted(original, rephrased):
    assert p._rephrase_violation(original, rephrased) is None


@pytest.mark.parametrize("original,rephrased,why", [
    # the reported Mawlwai case: the measure must never become a different one
    ("Focus Plus person days mawlwai all years",
     "How many payments are there under Focus Plus in mawlwai across all financial years?", "measure"),
    ("Focus Plus person days mawlwai all years",
     "How many person-days are there under MGNREGA in mawlwai across all financial years?", "scheme"),
    ("Focus Plus person days mawlwai all years",
     "How many person-days are there under Focus Plus and MGNREGA in mawlwai?", "scheme"),
    ("Focus Plus person days mawlwai all years",          # a name "corrected" to another place
     "How many person-days are there under Focus Plus in Mawlai across all financial years?", "place"),
    ("Focus Plus person days mawlwai all years",          # a name dropped
     "How many person-days are there under Focus Plus across all financial years?", "name:mawlwai"),
    ("pmay ghar ri bhoi 2022-23", "How many PMAY-G houses were sanctioned in ri bhoi in FY 2023-24?", "year"),
    ("pmay ghar ri bhoi 2022-23", "How many PMAY-G houses were sanctioned in ri bhoi?", "year"),
    ("pmay ghar ri bhoi 2022-23",
     "How many PMAY-G houses were sanctioned in East Khasi Hills in FY 2022-23?", "place"),
    ("pmay ghar ri bhoi 2022-23 more than 50",
     "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?", "number"),
    ("pmay ghar ri bhoi 2022-23",
     "How much amount was released for PMAY-G houses in ri bhoi in FY 2022-23?", "measure"),
    ("pmay ghar ri bhoi 2022-23",
     "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23 for women?", "measure"),
    ("focus ghar", "How many houses under Focus Plus?", "scheme"),     # a bare "focus" is not guessed
    # live 2026-10-07: "producer groups paid" (a count) must not become money
    ("focus legacy producer groups paid ri bhoi 2024-25",
     "How much money was paid to producer groups under Focus Legacy in ri bhoi in FY 2024-25?", "measure"),
    ("pmay ghar ri bhoi", '{"intent": "DATA"}', "shape"),
    ("pmay ghar ri bhoi", "SELECT COUNT(*) FROM curated.v_pmay", "shape"),
])
def test_a_rephrase_that_changes_meaning_is_rejected(original, rephrased, why):
    assert p._rephrase_violation(original, rephrased) == why


# ── 3. rephrase_question: the model call and its fallbacks ─────────────────

def test_model_output_is_cleaned_and_accepted(monkeypatch):
    _model(monkeypatch, 'Rephrased question: "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?"\n')
    out = asyncio.run(p.rephrase_question("pmay mein kitne ghar sanction hue ri bhoi 2022-23"))
    assert out == "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?"


@pytest.mark.parametrize("reply", [
    "How many payments are there under Focus Plus in mawlwai across all financial years?",  # rejected
    TimeoutError("slow gateway"),                                                          # failed
    "",                                                                                    # empty
])
def test_any_problem_keeps_the_original(monkeypatch, reply):
    _model(monkeypatch, reply)
    q = "Focus Plus person days mawlwai all years"
    assert asyncio.run(p.rephrase_question(q)) == q


def test_the_prompt_carries_the_rules_and_the_message():
    from app.prompt_builder import build_rephrase_prompt
    prompt = build_rephrase_prompt("focus plus person days mawlwai")
    assert prompt.endswith("Message: focus plus person days mawlwai\nRephrased question:")
    for rule in ("Add none of your own", "EXACTLY as written", "Never swap it for a different measure",
                 "Never ask a question back"):
        assert rule in prompt
    # never confused with the follow-up rewrite's frame (test stubs key on it)
    assert "Standalone question:" not in prompt


# ── 4. The stage: when it runs, what it writes ─────────────────────────────

def _turn(question, **kw):
    t = p._new_turn(question)
    t.update(kw)
    return t


def test_stage_rewrites_a_messy_question_and_remembers_it_for_a_pause(monkeypatch):
    _model(monkeypatch, "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?")
    s = _session()
    t = _turn("pmay mein kitne ghar sanction hue ri bhoi 2022-23")
    assert asyncio.run(p._turn_rephrase_stage(t, s, None)) is None          # never ends the turn
    assert t["question"] == "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?"
    assert t["rephrased"] and t["pre_rephrase_question"] == "pmay mein kitne ghar sanction hue ri bhoi 2022-23"
    assert t["raw_question"] == "pmay mein kitne ghar sanction hue ri bhoi 2022-23"   # what the user typed
    assert s.turn_context["standalone_question"] == t["question"]


@pytest.mark.parametrize("kw", [
    {"is_followup_rewrite": True},     # the follow-up rewrite already made it standalone
    {"scope_resumed": True},           # a pause reply ("2023-24", a chip) must reach the merge as typed
])
def test_stage_skips_followups_and_pause_replies(monkeypatch, kw):
    calls = _model(monkeypatch, "anything")
    t = _turn("pmay mein kitne ghar ri bhoi", **kw)
    asyncio.run(p._turn_rephrase_stage(t, _session(), None))
    assert calls == [] and t["question"] == "pmay mein kitne ghar ri bhoi" and not t["rephrased"]


def test_stage_skips_a_typed_clarification_reply(monkeypatch):
    calls = _model(monkeypatch, "anything")
    s = _session()
    s.turn_context["clarification_reply"] = "west garo hills"
    asyncio.run(p._turn_rephrase_stage(_turn("west garo hills pmay ghar"), s, None))
    assert calls == []


def test_stage_skips_a_clean_question_and_when_disabled(monkeypatch):
    calls = _model(monkeypatch, "anything")
    asyncio.run(p._turn_rephrase_stage(_turn("How many PMAY-G houses were sanctioned in Ri Bhoi?"),
                                       _session(), None))
    monkeypatch.setattr(settings, "QUERY_REPHRASE_ENABLED", False)
    asyncio.run(p._turn_rephrase_stage(_turn("pmay mein kitne ghar"), _session(), None))
    assert calls == []


# ── 5. The graph ────────────────────────────────────────────────────────────

def test_rephrase_node_sits_between_followup_and_route():
    edges = {(e.source, e.target) for e in pg.build_graph().compile().get_graph().edges}
    assert ("followup", "rephrase") in edges and ("rephrase", "route") in edges
    assert ("followup", "route") not in edges
    assert "pipeline._turn_rephrase_stage" in inspect.getsource(pg.node_rephrase.stage_fn)
    assert pg.fresh_turn_state("q")["rephrased"] is False


def test_the_cleaned_question_reaches_route_and_the_data_path(monkeypatch):
    """End to end on the graph: the messy question is rephrased, routed DATA,
    and the DATA path receives the clean question; the answer says what it
    answered (rewritten_question) and keeps what the user typed."""
    from _graph_turn import graph_turn, stub_data_path
    clean = "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?"
    _model(monkeypatch, clean)
    seen = {}

    async def classify_intent(q):
        seen["routed"] = q
        return "DATA"

    async def fake_answer_data(question, **kw):
        seen["data"] = question
        return {"route": "data", "intent": "DATA", "answer": "11,334", "schemes": ["PMAY-G"],
                "sql": "S", "rows": [], "data": [], "resolved_entities": {}}
    monkeypatch.setattr(p, "classify_intent", classify_intent)
    stub_data_path(monkeypatch, fake_answer_data)
    monkeypatch.setattr(settings, "CONTEXT_SUMMARY_ENABLED", False)
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", False)
    r = asyncio.run(graph_turn("pmay mein kitne ghar sanction hue ri bhoi 2022-23", session=_session()))
    assert seen["routed"] == clean and seen["data"] == clean
    assert r["rewritten_question"] == clean
