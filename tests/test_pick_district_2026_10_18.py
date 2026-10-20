"""
User session 2026-10-18: after "how many houses are there in 2023-2024" was answered
for all of Meghalaya, "don't give all of Meghalaya … ask me … What are the districts
are there? Then I will choose one." went to the KB ("the scheme documents hold no
district list"). Now it offers the previous question once per district (chips), and
the rephrase guard no longer reads "don't" as a lost name. Every test calls the real
function.
"""
import asyncio
import time

import pytest

from app import entity_resolver
from app import pipeline as p
from app.session_store import Session, Turn

USER_MSG = ("Okay, now for the above question, don't give all all of Meghalaya. Okay, ask me "
            "follow up question. I will say one district. Show me the district. What are the "
            "districts are there? Then I will choose one.")
PREV_Q = "How many PMAY-G houses were sanctioned for all of Meghalaya in FY 2023-24"


@pytest.fixture(scope="module", autouse=True)
def _catalog():
    entity_resolver.load_all()


@pytest.mark.parametrize("text", [
    USER_MSG,
    "show me the districts, I will pick one",
    "list the districts",
    "ask me which district, I'll choose",
])
def test_asks_to_pick_a_district(text):
    assert p._asks_to_pick_district(text)


@pytest.mark.parametrize("text", [
    "which district has the most houses",
    "district-wise houses sanctioned",
    "houses by district",
    "how many districts are there",
    "houses in East Khasi Hills",
    "show me the blocks",
])
def test_a_question_about_districts_is_not_a_pick(text):
    assert not p._asks_to_pick_district(text)


def test_chips_are_the_previous_question_per_district():
    e = p._pick_district_clarification(PREV_Q, ["PMAY-G"])
    assert e.rule == "scope-not-specified"
    assert e.stem == "How many PMAY-G houses were sanctioned in FY 2023-24"
    labels = [o["label"] for o in e.options]
    assert "East Khasi Hills" in labels and labels[-1] == "All of Meghalaya"
    assert len(labels) == len(entity_resolver.all_districts("PMAY-G")) + 1
    ekh = next(o for o in e.options if o["label"] == "East Khasi Hills")
    assert ekh["question"] == "How many PMAY-G houses were sanctioned in FY 2023-24 in East Khasi Hills"


def test_an_earlier_district_is_taken_out_of_the_chips():
    e = p._pick_district_clarification(
        "How many PMAY-G houses were sanctioned in West Garo Hills in FY 2023-24", ["PMAY-G"],
        prev_district="West Garo Hills")
    assert "West Garo Hills" not in e.stem


def _session_after_data_answer():
    s = Session(session_id="pick", user_id="u", created=time.time(), last_seen=time.time())
    s.turns = [Turn(question=PREV_Q, raw_question="how many houses are there in 2023-2024",
                    route="data", schemes=["PMAY-G"])]
    return s


def test_followup_stage_offers_district_chips_after_a_data_answer():
    s = _session_after_data_answer()
    t = p._new_turn(USER_MSG)
    t.update(prev=s.last_turn, has_context=True)
    with pytest.raises(p.ClarificationNeeded) as ei:
        asyncio.run(p._turn_followup_stage(t, session=s))
    assert ei.value.rule == "scope-not-specified"
    assert any(o["label"] == "East Khasi Hills" for o in ei.value.options)
    # A typed district reply merges into the previous question.
    assert s.turn_context["standalone_question"] == "How many PMAY-G houses were sanctioned in FY 2023-24"


def test_no_chips_after_a_knowledge_answer():
    s = _session_after_data_answer()
    s.turns[-1].route = "knowledge"
    t = p._new_turn("list the districts, I will pick one")
    t.update(prev=s.last_turn, has_context=True)
    try:
        asyncio.run(p._turn_followup_stage(t, session=s))
    except p.ClarificationNeeded as e:
        assert e.rule != "scope-not-specified"


def test_contractions_are_not_names():
    assert p._is_known_word("don't") and p._is_known_word("can’t") and p._is_known_word("I'll")
    assert not p._is_known_word("mawlai's")
    assert p._rephrase_violation(
        "don't give all of Meghalaya, what are the districts",
        "Do not give all of Meghalaya; what are the districts?") is None
