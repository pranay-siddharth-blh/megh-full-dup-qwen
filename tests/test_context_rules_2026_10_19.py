"""Context rules restated by the user on 2026-10-19 (with MAIN_Contex.pdf §9.4):
  * inside one chat the scheme it is on is never asked again; a NEW chat whose
    question names no scheme (and whose words pin none) asks which scheme;
  * "there" / "that district" brings the chat's place into a new same-scheme question;
  * a follow-up that only names a new measure keeps the user's words plus the chat's
    scope; the old measure does not leak into it (KI-334)."""
import asyncio

import pytest

from app import context_policy as cp
from app import pipeline as p
from app.session_store import ConversationState, Session, Turn


def _session(scheme=None, prev_schemes=None):
    s = Session(session_id="t", user_id="u", created=0.0, last_seen=0.0)
    if scheme:
        s.state.scheme = scheme
    if prev_schemes is not None:
        s.turns.append(Turn(question="q", raw_question="q", route="data", schemes=prev_schemes,
                            resolved_entities={}, answer=""))
    return s


def test_chat_scheme_is_the_state_scheme_else_the_last_single_scheme():
    assert p._chat_active_scheme(None) is None
    assert p._chat_active_scheme(_session()) is None
    assert p._chat_active_scheme(_session(scheme="PMAY-G")) == "PMAY-G"
    assert p._chat_active_scheme(_session(prev_schemes=["MGNREGA"])) == "MGNREGA"
    assert p._chat_active_scheme(_session(prev_schemes=["MGNREGA", "PMAY-G"])) is None


def _scheme_stage(question, chat_scheme):
    d = p._new_data_turn(question)
    d["chat_scheme"] = chat_scheme
    return d, asyncio.run(p._data_scheme_stage(d))


def test_new_chat_without_a_scheme_asks():
    with pytest.raises(p.ClarificationNeeded) as e:
        _scheme_stage("how many beneficiaries are there?", None)
    assert e.value.rule == "scheme-not-specified"


def test_inside_a_chat_the_scheme_is_inherited_not_asked():
    d, _ = _scheme_stage("how many beneficiaries are there?", "PMAY-G")
    assert d["schemes"] == ["PMAY-G"]
    assert d["question"].endswith("under PMAY-G?")


def test_words_that_pin_one_scheme_need_no_chat_scheme():
    d, _ = _scheme_stage("total person-days in Ri Bhoi in 2023-24", None)
    assert d["schemes"] == ["MGNREGA"]


def test_place_reference_brings_the_chat_place():
    st = ConversationState(scheme="MGNREGA", district="RI BHOI", year=2023)
    out = p._same_scheme_context_year("what is the total expenditure there under MGNREGA?",
                                      "what is the total expenditure there?", st)
    assert out == {"year_key": 2023, "district": "RI BHOI"}
    # D-061: its own scheme and measure -> a new question, nothing inherited
    out = p._same_scheme_context_year("MGNREGA expenditure by district", "MGNREGA expenditure by district", st)
    assert out is None


PREV = Turn(question="How many PMAY-G houses were completed in Ri Bhoi in 2023-24?", raw_question="", route="data",
            schemes=["PMAY-G"], resolved_entities={"district": "RI BHOI", "year_key": 2023}, answer="")
ST = ConversationState(scheme="PMAY-G", district="RI BHOI", year=2023)


@pytest.mark.parametrize("q", ["how many beneficiaries are there?", "what is the total amount released?"])
def test_a_pure_measure_change_is_rewritten_deterministically(q):
    assert p._pure_measure_change(q, PREV, cp.plan_state_merge(q, ST, prev=PREV, is_followup=True))
    phrase = p._swap_scope_phrase(ST, "PMAY-G", PREV)
    assert phrase == " in Ri Bhoi in FY 2023-24"


@pytest.mark.parametrize("q", ["how many of those were completed?", "what was the total?", "how many in 2022-23?",
                               "and the sanctioned amount by block?", "how many MGNREGA households?"])
def test_other_follow_ups_keep_the_model_rewrite(q):
    assert not p._pure_measure_change(q, PREV, cp.plan_state_merge(q, ST, prev=PREV, is_followup=True))
