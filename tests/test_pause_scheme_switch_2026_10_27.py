"""KI-405 (KI-223 back): a scheme switch typed while a "which area / year?" pause waits.

"How many PMAY-G beneficiaries are there?" paused for its area; the officer typed
"What about MGNREGA?". The reply was glued onto the paused question ("How many
PMAY-G beneficiaries are there, What about MGNREGA?") and answered as a two-scheme
figure (live context suite scenario I, 2026-10-24). A pure switch to another
scheme is now the paused question asked for that scheme, and it is still asked
its own area / year (the scope is not taken as answered)."""
import asyncio

from _graph_turn import graph_turn, stub_data_path

from app import llm
from app import pipeline as p
from app.routers import query as router
from app.session_store import Session

PAUSED = "How many PMAY-G beneficiaries are there?"


def _paused_session(rule="scope-not-specified"):
    s = Session(session_id="ki405", user_id="u", created=0.0, last_seen=0.0)
    router.remember_pause(s, PAUSED, p.ClarificationNeeded("Which area should the answer cover?", rule=rule))
    return s


def _run(monkeypatch, session, reply):
    seen = {}

    async def fake_answer_data(question, **kw):
        seen.update(q=question, skip=kw.get("skip_scope_clarify"))
        return {"route": "data", "intent": "DATA", "answer": "ok", "schemes": ["MGNREGA"],
                "sql": "S", "rows": [], "data": [], "resolved_entities": {}}

    async def classifier(prompt, **_kw):
        return '{"intent": "DATA"}'

    stub_data_path(monkeypatch, fake_answer_data)
    monkeypatch.setattr(llm, "call_classifier", classifier)
    monkeypatch.setattr(llm, "call_rewriter", classifier)
    asyncio.run(graph_turn(reply, session=session))
    return seen


def test_a_scheme_switch_reasks_the_paused_question_for_that_scheme(monkeypatch):
    s = _paused_session()
    seen = _run(monkeypatch, s, "What about MGNREGA?")
    assert seen["q"] == "How many MGNREGA beneficiaries are there?"
    assert "PMAY" not in seen["q"]
    assert not seen["skip"]                                  # MGNREGA's own area is still asked
    assert s.turn_context["resumed_question"] == seen["q"]   # a second pause remembers the full question
    assert s.pending_scope_q is None


def test_the_same_on_a_year_pause(monkeypatch):
    seen = _run(monkeypatch, _paused_session("year-not-specified"), "same for Focus Plus")
    assert seen["q"] == "How many Focus Plus beneficiaries are there?"


def test_a_place_reply_still_answers_the_pause(monkeypatch):
    seen = _run(monkeypatch, _paused_session(), "West Garo Hills")
    assert seen["q"].startswith("How many PMAY-G beneficiaries are there") and "West Garo Hills" in seen["q"]


def test_only_a_pure_switch_to_another_scheme_counts():
    f = p._c14_pause_scheme_switch
    assert f("What about MGNREGA?", PAUSED, "scope-not-specified") == "MGNREGA"
    assert f("What about PMAY-G?", PAUSED, "scope-not-specified") is None          # the same scheme
    assert f("MGNREGA", PAUSED, "scope-not-specified") is None                     # no switch cue
    assert f("What about MGNREGA in 2023-24?", PAUSED, "scope-not-specified") is None  # says more
    assert f("what about focus", PAUSED, "scope-not-specified") is None            # which Focus? is asked
    assert f("What about MGNREGA?", PAUSED, "entity-ambiguous") is None            # other pauses unchanged
