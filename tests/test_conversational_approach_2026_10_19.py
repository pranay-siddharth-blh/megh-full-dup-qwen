"""Conversational Memory approach (documents/Megh_One_AI_Conversational_Memory_Approach.pdf,
2026-10-19): going back by a bare ordinal, the user's name, the first greeting, one steer-back
per run of asides, coverage questions, greeting back on a mixed message, and the
rule-computed callback to the same figure for another year."""
from types import SimpleNamespace

from app import conversation_replies as cr
from app import pipeline as p
from app import topic_memory


def _session():
    return SimpleNamespace(topics={}, state=None, turns=[], last_turn=None)


def _edge(edge_type):
    return {"route": "edge", "intent": "EDGE", "edge_type": edge_type, "answer": "", **p._empty_data_fields()}


# ── going back ──────────────────────────────────────────────────────────────
def test_go_back_to_the_first_one_is_question_one():
    assert topic_memory.parse_backward("go back to the first one").ordinal == 1
    assert topic_memory.parse_backward("back to the second one").ordinal == 2
    assert topic_memory.parse_backward("go back to the last one").ordinal == "last"
    # without the lead, "the first one" still points into a result
    assert topic_memory.parse_backward("which one had the highest? the first one") is None


# ── the user's name ─────────────────────────────────────────────────────────
def test_introduced_name():
    assert cr.introduced_name("hi, I'm Ravi") == "Ravi"
    assert cr.introduced_name("my name is Ravi Kumar") == "Ravi Kumar"
    assert cr.introduced_name("Hello, I am Banteilang here") == "Banteilang"
    for not_a_name in ("I am a block officer from Dalu", "I am confused", "I'm fine", "I am asking about MGNREGA",
                       "I am from Tura", "I'm back", "I am looking for PMAY-G data"):
        assert cr.introduced_name(not_a_name) is None, not_a_name


def test_name_reply_then_greeting_uses_the_name():
    s = _session()
    first = cr.small_talk_reply(s, "hi, I'm Ravi")
    assert first["answer"].startswith("Nice to meet you, Ravi!") and "Megh One AI" in first["answer"]
    again = cr.small_talk_reply(s, "hello again")
    assert "Ravi" in again["answer"] and "I'm Megh One AI" not in again["answer"]


# ── greetings and asides ────────────────────────────────────────────────────
def test_first_greeting_introduces_once():
    s = _session()
    one = cr.small_talk_reply(s, "hi")
    assert "Megh One AI" in one["answer"] and "What schemes are there?" in one["suggestions"]
    two = cr.small_talk_reply(s, "hello")
    assert "Megh One AI" not in two["answer"]


def test_steer_back_once_per_run_of_asides():
    s = _session()
    s.state = SimpleNamespace(scheme="MGNREGA", district="WEST GARO HILLS", block=None, village=None)
    one = cr.restyle(s, "who won the cricket match yesterday?", _edge("scope_general"))
    assert "MGNREGA in West Garo Hills" in one["answer"] and "I'm Megh One AI" not in one["answer"]
    two = cr.restyle(s, "what is the capital of France?", _edge("scope_general"))
    assert cr.STEER_AGAIN in two["answer"] and "West Garo Hills" not in two["answer"]
    # an answered turn ends the run
    p._attach_conversational_touches({"route": "data", "answer": "x"}, s, "MGNREGA job cards")
    three = cr.restyle(s, "who is the PM?", _edge("scope_general"))
    assert "West Garo Hills" in three["answer"]


def test_thanks_offers_chips_then_just_happy_to_help():
    s = _session()
    s.state = SimpleNamespace(scheme="PMAY-G", district="RI BHOI", block=None, village=None)
    one = cr.restyle(s, "thanks", _edge("thanks"))
    assert "PMAY-G" in one["answer"] and len(one["suggestions"]) >= 2
    two = cr.restyle(s, "thank you", _edge("thanks"))
    assert two["answer"] == "Happy to help!" and two["suggestions"] == []


# ── coverage ────────────────────────────────────────────────────────────────
def test_coverage_kind():
    assert p._coverage_kind("which years do you have for MGNREGA?") == "years"
    assert p._coverage_kind("which districts can I see?") == "areas"
    assert p._coverage_kind("what years are available for PMAY-G") == "years"
    assert p._coverage_kind("which district has the most job cards?") is None
    assert p._coverage_kind("how many job cards in 2023-24") is None


def test_coverage_answers(monkeypatch):
    # the district catalogue is loaded from megh_db at startup; offline it is empty
    monkeypatch.setattr(p._c15_entity_resolver, "all_districts", lambda s: ["EAST KHASI HILLS", "RI BHOI"])
    years = p._coverage_answer("which years do you have for MGNREGA?", None)
    assert years["edge_type"] == "coverage" and "MGNREGA data covers FY" in years["answer"]
    restricted = SimpleNamespace(geo_restricted=True, allowed_districts=lambda: ["RI BHOI"], allowed_blocks=lambda: [])
    areas = p._coverage_answer("which districts can I see?", None, restricted)
    assert areas["answer"].startswith("You can view Ri Bhoi district.")
    everyone = p._coverage_answer("which districts can I see?", None, None)
    assert "East Khasi Hills" in everyone["answer"]


# ── data answers: greeting back and the callback ────────────────────────────
def _data(value, year, answer):
    return {"route": "data", "answer": answer, "schemes": ["MGNREGA"], "rows": [{"person_days": value}],
            "resolved_entities": {"district": "EAST KHASI HILLS", "year_key": year}}


def test_social_prefix():
    assert p._social_prefix("Hi, how many job cards in West Garo Hills in 2024-25?") == "greeting"
    assert p._social_prefix("thanks. what about 2023-24?") == "thanks"
    assert p._social_prefix("how many job cards") is None
    assert p._social_prefix("thanks") is None          # a pure thank-you is the edge's


def test_callback_to_the_same_figure_for_another_year():
    s = _session()
    first = _data(3408697, 2022, "3,408,697 person-days were generated in East Khasi Hills across FY 2022-23.")
    p._attach_conversational_touches(first, s, "MGNREGA person-days in East Khasi Hills 2022-23")
    assert "down from" not in first["answer"]
    second = _data(3061525, 2023, "3,061,525 person-days were generated in East Khasi Hills for FY 2023-24.")
    p._attach_conversational_touches(second, s, "thanks. what about 2023-24?")
    assert second["answer"].startswith("You're welcome! 3,061,525")
    assert second["answer"].endswith("That's down from 3,408,697 in FY 2022-23 (about 10.2% lower).")
    assert second["context_dependent"] is True


def test_no_callback_across_places_or_when_already_compared():
    s = _session()
    p._attach_conversational_touches(_data(3408697, 2022, "a"), s, "q")
    other = _data(100, 2023, "b")
    other["resolved_entities"]["district"] = "RI BHOI"
    p._attach_conversational_touches(other, s, "q")
    assert other["answer"] == "b"
    compared = _data(3061525, 2023, "3,061,525 in FY 2023-24 against 3,408,697 in 2022-23.")
    p._attach_conversational_touches(compared, s, "q")
    assert "down from" not in compared["answer"]


def test_scope_sentence_names_only_what_is_missing():
    out = p._finish_answer("3,408,697 person-days were generated in East Khasi Hills across FY 2022-23.",
                           [{"person_days": 3408697}], ["MGNREGA"],
                           {"district": "East Khasi Hills", "year": "FY 2022-23"})
    assert out.endswith("FY 2022-23. This is the MGNREGA figure.")


def test_scope_sentence_is_added_once():
    rows = [{"person_days": 3857203}]
    once = p._finish_answer("3,857,203 person-days were generated in West Garo Hills for FY 2024-25.", rows,
                            ["MGNREGA"], {"district": "West Garo Hills", "year": "FY 2024-25"})
    assert p._finish_answer(once, rows, ["MGNREGA"], {"year": "FY 2024-25"}) == once
