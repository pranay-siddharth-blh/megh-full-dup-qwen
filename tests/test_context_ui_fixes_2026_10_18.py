"""
Context failures from the user's own UI conversation of 2026-10-18
(app.conversation_turns, session_1792306638804) and the live matrix
(tests/live_context_matrix.py), fixed the same day. Each test calls the real
function. No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_context_ui_fixes_2026_10_18.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402
from app.session_store import Turn  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _places_loaded():
    from app.entity_resolver import load_all
    load_all()


PREV = Turn(question="Total MGNREGA person-days in FY 2023-24", raw_question="Total MGNREGA person-days in 2023-24",
            route="data", schemes=["MGNREGA"])


# ── "What is the total beneficiaries?" after a data answer is its follow-up ──

@pytest.mark.parametrize("q", ["What is the total beneficiaries?", "What was the total?",
                               "What is the total expenditure?", "What is the number of job cards?"])
def test_what_is_the_total_after_a_data_answer_is_a_followup(q):
    assert p.is_scopeless_followup(q, PREV)


@pytest.mark.parametrize("q", ["What is MGNREGA?", "What is a job card?", "What is the target number of entrepreneurs?",
                               "What are the eligibility rules?"])
def test_definition_questions_stay_knowledge(q):
    assert not p.is_scopeless_followup(q, PREV)


def test_not_after_a_knowledge_answer_or_with_no_antecedent():
    k = Turn(question="Who is eligible for PMAY-G?", raw_question="x", route="knowledge", schemes=["PMAY-G"])
    assert not p.is_scopeless_followup("What is the total beneficiaries?", k)
    assert not p.is_scopeless_followup("What is the total beneficiaries?", None)


# ── The same scheme named again with only a measure keeps the scope ─────────

@pytest.mark.parametrize("q", ["What is the total beneficiaries MGNREGA?", "How many MGNREGA beneficiaries?"])
def test_same_scheme_again_is_a_followup(q):
    assert p.is_scopeless_followup(q, PREV)


@pytest.mark.parametrize("q", ["How many PMAY-G houses?", "MGNREGA beneficiaries in Ri Bhoi",
                               "total MGNREGA job cards in 2022-23"])
def test_another_scheme_a_place_or_a_year_is_a_new_question(q):
    assert not p.is_scopeless_followup(q, PREV)


# ── "manraya" / "manrega" (voice typing) is MGNREGA ─────────────────────────

@pytest.mark.parametrize("q, fixed", [("What is the total beneficiaries manraya?", "What is the total beneficiaries MGNREGA?"),
                                       ("manrega persondays", "MGNREGA persondays")])
def test_spoken_scheme_names_are_rewritten(q, fixed):
    assert p._correct_scheme_spelling(q) == fixed
    assert p._named_schemes(q) == ["MGNREGA"]


@pytest.mark.parametrize("q", ["How many managers are there?", "Show manual records", "Mairang block", "pmay houses"])
def test_no_false_scheme_corrections(q):
    assert p._correct_scheme_spelling(q) == q


# ── Spoken digit years ──────────────────────────────────────────────────────

@pytest.mark.parametrize("q, want", [
    ("Okay. Ah, now give me how many houses are there in two zero, two three, two two zero two four.",
     "Okay. Ah, now give me how many houses are there in 2023-24."),
    ("houses in two zero two three", "houses in 2023"),
    ("two zero two three, two zero two five", "2023, 2025"),
    ("top two zero districts", "top two zero districts"),
    ("one two three four", "one two three four"),
    ("twenty twenty five to twenty six", "2025-26"),
])
def test_spoken_years(q, want):
    assert p._spoken_years_to_digits(q) == want


# ── KI-308: the verifier may not remove a RESOLVED place the guard requires ──
ISSUE = ("Check 2 violation: The RESOLVED ENTITY lgd_district = 'WEST GARO HILLS' is present in the WHERE clause, "
         "but it should not be included since the question specifically asks for Dalu block and the RESOLVED "
         "ENTITIES block only specifies lgd_block = 'DALU'. Including lgd_district = 'WEST GARO HILLS' introduces "
         "an unnecessary and potentially incorrect filter that was not part of the resolved entities.")
SQL = ("SELECT SUM(person_days) AS person_days FROM curated.v_employment WHERE lgd_block = 'DALU' "
       "AND year_key = 2024 AND lgd_district = 'WEST GARO HILLS' LIMIT 1")


def test_ki308_removal_of_a_resolved_district_is_discarded():
    resolved = {"block": "DALU", "year_key": 2024, "district": "WEST GARO HILLS"}
    assert p._verifier_wants_resolved_filter_removed(ISSUE, resolved, SQL)


def test_ki308_removal_of_an_unresolved_district_is_kept():
    assert not p._verifier_wants_resolved_filter_removed(ISSUE, {"block": "DALU"}, SQL)


def test_ki308_other_complaints_are_kept():
    assert not p._verifier_wants_resolved_filter_removed("lgd_district WEST GARO HILLS is missing",
                                                         {"district": "WEST GARO HILLS"}, SQL)


# ── "What is the total <term>?" is a figure, not a term definition ──────────
# (live matrix 2026-10-18, MGNREGA / Focus Legacy F2: the term gate in the
# follow-up stage skipped the follow-up and answered statewide)

@pytest.mark.parametrize("q", ["What is the total job cards?", "What is the total producer groups?",
                               "What is the number of job cards?", "What is the total?"])
def test_an_aggregate_opener_is_not_a_term_question(q):
    assert not p._is_scheme_term_question(q)
    assert p.is_scopeless_followup(q, PREV)


@pytest.mark.parametrize("q", ["What is a job card?", "What is DBT?", "What is Gram Sabha?", "meaning of muster roll"])
def test_real_term_questions_still_are(q):
    assert p._is_scheme_term_question(q)


# ── The CM Elevate family is one topic (live matrix 2026-10-18, CM Elevate F4) ──
import time  # noqa: E402
import types  # noqa: E402

from app import context_manager, context_policy  # noqa: E402
from app.session_store import ConversationState, Session  # noqa: E402


def test_a_knowledge_aside_about_cm_elevate_keeps_the_legacy_figure_as_antecedent():
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    data = Turn(question="How many CM Elevate Legacy applications are there in Ri Bhoi?", raw_question="x",
                route="data", schemes=["CM Elevate Legacy"], resolved_entities={"district": "RI BHOI"})
    know = Turn(question="Who is eligible for CM Elevate?", raw_question="Who is eligible for CM Elevate?",
                route="knowledge", schemes=["CM Elevate"])
    s.turns = [data, know]
    plan = types.SimpleNamespace(kind=context_policy.GEOGRAPHY_CHANGE)
    got = p._data_thread_antecedent("And in West Garo Hills?", know, s, plan)
    assert got is data


def test_a_knowledge_aside_about_cm_elevate_does_not_switch_the_legacy_topic():
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.state = ConversationState(scheme="CM Elevate Legacy", district="RI BHOI", year=2024)
    context_manager.update_state(s, "Who is eligible for CM Elevate?", "Who is eligible for CM Elevate?",
                                 {"route": "knowledge", "schemes": ["CM Elevate"]})
    assert (s.state.scheme, s.state.district, s.state.year) == ("CM Elevate Legacy", "RI BHOI", 2024)


def test_another_scheme_still_switches():
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.state = ConversationState(scheme="CM Elevate Legacy", district="RI BHOI", year=2024)
    context_manager.update_state(s, "Who is eligible for PMAY-G?", "Who is eligible for PMAY-G?",
                                 {"route": "knowledge", "schemes": ["PMAY-G"]})
    assert (s.state.scheme, s.state.district) == ("PMAY-G", None)
