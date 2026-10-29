"""KI-406 (user decision 2026-10-27, U5 "keep the previous year").

Live context suite scenario U1 (the user's own UI chat of 2026-10-18):
"Total MGNREGA person-days in 2023-24" -> "What is the total beneficiaries?"
(kept FY 2023-24) -> "What is the total beneficiaries manraya?" — "manraya" is the
spoken MGNREGA, so the turn read STANDALONE (own scheme + own measure, D-061),
inherited nothing, was asked the year and the suite's first chip answered ALL years.

The rule now: a standalone question that only repeats the chat's measure on the
chat's own scheme keeps the chat's YEAR (never its place). A new measure is still a
new question (D-061's founding case) and is asked the year (D-065).

OFFLINE: calls the real `_same_scheme_context_year` and the follow-up stage through
the graph.
    .venv/Scripts/python.exe -m pytest tests/test_same_measure_year_ki406_2026_10_27.py -q
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_policy as cp  # noqa: E402
from app import llm, pipeline as p  # noqa: E402
from app.session_store import ConversationState, Session, Turn  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402

T3 = "What is the total beneficiaries manraya?"
# The chat after T2: MGNREGA, statewide, FY 2023-24, measure "beneficiaries".
ST = ConversationState(scheme="MGNREGA", year=2023, metric="beneficiaries")
# Same chat with a place, to show the place is never carried by this rule.
ST_PLACE = ConversationState(scheme="MGNREGA", district="EAST KHASI HILLS", year=2022, metric="person-days")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_the_reported_turn_reads_standalone():
    # Precondition: the spoken scheme name makes it a question of its own.
    assert cp.turn_kind(T3).kind == cp.TURN_STANDALONE


def test_repeating_the_chats_measure_keeps_the_year():
    assert p._same_scheme_context_year(T3, T3, ST, kind=cp.TURN_STANDALONE) == {"year_key": 2023}
    assert p._same_scheme_context_year(T3, T3, ST) == {"year_key": 2023}


def test_repeating_the_measure_keeps_the_year_but_not_the_place():
    q = "MGNREGA person-days please"
    assert p._same_scheme_context_year(q, q, ST_PLACE) == {"year_key": 2022}


def test_a_new_measure_still_inherits_nothing():
    # D-061's founding case: person-days, then a beneficiaries ranking.
    q = "Which district has the highest beneficiaries in MGNREGA?"
    assert p._same_scheme_context_year(q, q, ST_PLACE) is None


def test_another_scheme_or_its_own_year_inherits_nothing():
    q = "What is the total beneficiaries under PMAY-G?"
    assert p._same_scheme_context_year(q, q, ST) is None
    q = "What is the total beneficiaries manraya in 2022-23?"
    assert p._same_scheme_context_year(q, q, ST) is None


def test_no_measure_in_the_chat_keeps_the_old_rule():
    st = ConversationState(scheme="MGNREGA", year=2023)
    assert p._same_scheme_context_year(T3, T3, st) is None


def test_the_reported_turn_reaches_the_data_path_with_the_year(monkeypatch):
    seen = {}

    async def classifier(prompt, **_kw):
        return '{"intent": "DATA"}'

    async def fake_answer_data(question, **kw):
        seen["prior"] = kw.get("prior_resolved")
        return {"route": "data", "intent": "DATA", "answer": "ok", "schemes": ["MGNREGA"],
                "sql": "S", "rows": [], "data": [], "resolved_entities": {}}

    monkeypatch.setattr(llm, "call_classifier", classifier)
    monkeypatch.setattr(llm, "call_rewriter", classifier)
    stub_data_path(monkeypatch, fake_answer_data)
    prev_q = "What is the total beneficiaries under MGNREGA in FY 2023-24?"
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.turns = [Turn(question=prev_q, raw_question="What is the total beneficiaries?", route="data",
                    schemes=["MGNREGA"], resolved_entities={"year_key": 2023})]
    s.state = ST
    _run(graph_turn(T3, session=s))
    assert s.turn_context.get("turn_kind") == cp.TURN_STANDALONE
    assert seen["prior"] == {"year_key": 2023}
