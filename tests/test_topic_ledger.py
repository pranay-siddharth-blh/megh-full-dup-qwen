"""
The topic ledger (app/topic_memory.py, Context Memory proposal Phase 3,
2026-10-18): going back to an earlier QUESTION, not only an earlier topic —
by order ("the first question", "question 3"), by content ("the East Khasi
Hills one", "the job cards question", "MGNREGA ka 2022 wala figure"), asking
with chips when several match, and "what did we discuss?".

Each turn is folded in with the REAL context_manager.update_state and the
router's REAL build_turn / remember_pause, as tests/test_topic_memory.py does.
No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_topic_ledger.py -q
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_manager as cm, pipeline as p, topic_memory as tm  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn, is_cacheable, pause_question, remember_pause  # noqa: E402
from app.session_store import Session  # noqa: E402

EKH, WGH, RIB = "EAST KHASI HILLS", "WEST GARO HILLS", "RI BHOI"
Q1 = "How many MGNREGA person-days were generated in East Khasi Hills in FY 2022-23?"
Q2 = "Who is eligible for PMAY-G?"
Q3 = "How many MGNREGA job cards were issued in West Garo Hills in FY 2023-24?"
Q4 = "How many PMAY-G houses were completed?"


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_LAYER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_STATE_ENABLED", True)
    monkeypatch.setattr(settings, "BACKWARD_RESOLVER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_LEDGER_PER_TOPIC", 6)


def _session():
    return Session(session_id="ledger-1", user_id="u", created=time.time(), last_seen=time.time())


def ask(session, question, *, scheme=None, district=None, year=None, route="data"):
    """One turn as the graph + router run it (see tests/test_topic_memory.py)."""
    session.turn_context = {}
    t = tm.resolve_turn(session, question)
    if t.response is not None:
        result = t.response
    elif route == "data":
        resolved = {k: v for k, v in (("district", district), ("year_key", year)) if v is not None}
        result = {"route": "data", "intent": "DATA", "schemes": [scheme], "sql": "SELECT 1",
                  "resolved_entities": resolved, "answer": f"{scheme} answer"}
    else:
        result = {"route": "knowledge", "intent": "RAG", "schemes": [scheme] if scheme else [],
                  "resolved_entities": {}, "answer": f"About {scheme}."}
    cm.update_state(session, question, t.question, result)
    session.turns.append(build_turn(question, result))
    return t


def _four_questions(s):
    """The conversation of the proposal's Figure 4."""
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    ask(s, Q2, scheme="PMAY-G", route="knowledge")
    ask(s, Q3, scheme="MGNREGA", district=WGH, year=2023)
    ask(s, Q4, scheme="PMAY-G")


def ledger(s, key):
    tm.checkpoint(s)
    return s.topics["items"][key]["ledger"]


# ── Filing ──────────────────────────────────────────────────────────────────

def test_each_question_is_filed_with_its_scope_and_number():
    s = _session()
    _four_questions(s)
    mg = ledger(s, "MGNREGA")
    assert [e["n"] for e in mg] == [1, 3]
    assert (mg[0]["state"]["district"], mg[0]["state"]["year"]) == (EKH, 2022)
    assert (mg[1]["state"]["district"], mg[1]["state"]["year"]) == (WGH, 2023)
    assert [e["n"] for e in s.topics["items"]["PMAY-G"]["ledger"]] == [2, 4]
    assert s.topics["items"]["PMAY-G"]["ledger"][0]["route"] == "knowledge"


def test_the_ledger_is_capped_per_topic(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_LEDGER_PER_TOPIC", 3)
    s = _session()
    for y in (2019, 2020, 2021, 2022, 2023):
        ask(s, f"MGNREGA person-days in Ri Bhoi in FY {y}-{str(y + 1)[-2:]}", scheme="MGNREGA",
            district=RIB, year=y)
    assert [e["n"] for e in ledger(s, "MGNREGA")] == [3, 4, 5]


def test_asking_the_same_question_again_keeps_its_number():
    s = _session()
    _four_questions(s)
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    assert [e["n"] for e in ledger(s, "MGNREGA")] == [3, 1]       # most recent last, number kept


def test_the_ledger_survives_the_snapshot():
    s = _session()
    _four_questions(s)
    tm.checkpoint(s)
    other = _session()
    other.apply_snapshot(s.to_snapshot())
    assert [e["n"] for e in other.topics["items"]["MGNREGA"]["ledger"]] == [1, 3]
    assert len(other.topics["items"]["MGNREGA"]["ledger"][0]["turn"]["answer"]) <= 300


# ── Going back: by content ──────────────────────────────────────────────────

def test_go_back_to_the_east_khasi_hills_one_restores_question_1():
    s = _session()
    _four_questions(s)
    t = ask(s, "Go back to the East Khasi Hills one", scheme="MGNREGA", district=EKH, year=2022)
    assert t.action == "restore" and t.topic == "MGNREGA"
    assert t.question == Q1                                     # re-run, never a stored figure


def test_restoring_puts_the_scope_and_the_antecedent_back():
    s = _session()
    _four_questions(s)
    s.turn_context = {}
    t = tm.resolve_turn(s, "Go back to the East Khasi Hills one, what about 2023-24?")
    assert t.question == "what about 2023-24?"
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", EKH, 2022)
    assert s.last_turn.question == Q1                           # the follow-up's antecedent
    assert s.topics["active"] == "MGNREGA"


def test_by_words_of_the_question():
    s = _session()
    _four_questions(s)
    t = ask(s, "back to the job cards question", scheme="MGNREGA", district=WGH, year=2023)
    assert t.action == "restore" and t.question == Q3


def test_by_year_with_a_scheme_in_hinglish():
    s = _session()
    _four_questions(s)
    t = ask(s, "MGNREGA ka 2022 wala figure batao", scheme="MGNREGA", district=EKH, year=2022)
    assert t.action == "restore" and t.question == Q1


def test_you_said_then_a_new_question_runs_in_the_restored_scope():
    s = _session()
    _four_questions(s)
    s.turn_context = {}
    t = tm.resolve_turn(s, "You showed the person-days for East Khasi Hills, what about Ri Bhoi?")
    assert t.action == "restore" and t.question == "what about Ri Bhoi?"
    assert s.state.district == EKH and s.last_turn.question == Q1


def test_asking_for_more_than_the_entry_held_runs_the_users_words():
    s = _session()
    _four_questions(s)
    s.turn_context = {}
    q = "Show me the East Khasi Hills data again by block"
    t = tm.resolve_turn(s, q)
    assert t.action == "restore" and t.question == q and s.state.district == EKH


def test_a_misspelt_place_still_matches(monkeypatch):
    monkeypatch.setattr(p, "_correct_place_spelling", lambda q: q.replace("East Kasi Hills", "East Khasi Hills"))
    s = _session()
    _four_questions(s)
    t = ask(s, "Go back to the East Kasi Hills one", scheme="MGNREGA", district=EKH, year=2022)
    assert t.action == "restore" and t.question == Q1


# ── Going back: by order ────────────────────────────────────────────────────

@pytest.mark.parametrize("q, n", [
    ("Go back to the first question", 1),
    ("go back to question 3", 3),
    ("What was the second question?", 2),
    ("back to question number 4", 4),
    ("what was the last question again", 4),
])
def test_by_order(q, n):
    s = _session()
    _four_questions(s)
    want = {1: Q1, 2: Q2, 3: Q3, 4: Q4}[n]
    s.turn_context = {}
    t = tm.resolve_turn(s, q)
    assert t.action == "restore" and t.question == want


def test_the_second_mgnrega_question_counts_within_the_topic():
    s = _session()
    _four_questions(s)
    s.turn_context = {}
    t = tm.resolve_turn(s, "go back to the second MGNREGA question")
    assert t.question == Q3 and s.state.district == WGH


def test_the_previous_question_is_still_the_previous_topic():
    # Unchanged behaviour (tests/test_topic_memory.py): "the previous question"
    # is the topic before the active one, not a numbered question.
    s = _session()
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    ask(s, Q4, scheme="PMAY-G")
    t = ask(s, "Coming back to the previous question")
    assert t.action == "switch" and t.topic == "MGNREGA" and t.response is not None


# ── Several matches: ask with chips ─────────────────────────────────────────

def test_two_matches_ask_and_the_chip_restores_the_one_picked():
    s = _session()
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    ask(s, "What about FY 2023-24?", scheme="MGNREGA", district=EKH, year=2023)
    ask(s, Q4, scheme="PMAY-G")
    q = "Go back to the East Khasi Hills one"
    s.turn_context = {}
    with pytest.raises(p.ClarificationNeeded) as e:
        tm.resolve_turn(s, q)
    assert e.value.rule == tm.LEDGER_PAUSE_RULE
    labels = [o["label"] for o in e.value.options]
    assert labels == ["#2 MGNREGA · East Khasi Hills · FY 2023-24 · person-days",
                      "#1 MGNREGA · East Khasi Hills · FY 2022-23 · person-days"]   # most recent first
    assert s.state.scheme == "PMAY-G"                           # nothing restored while asking
    remember_pause(s, pause_question(s, q), e.value)
    s.turn_context = {}
    t = tm.resolve_turn(s, e.value.options[1]["question"])      # "Go back to question 1"
    assert t.action == "restore" and t.question == Q1 and s.state.year == 2022
    assert s.pending_scope_q is None


def test_a_year_narrows_two_matches_to_one():
    s = _session()
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    ask(s, "What about FY 2023-24?", scheme="MGNREGA", district=EKH, year=2023)
    s.turn_context = {}
    t = tm.resolve_turn(s, "Go back to the East Khasi Hills 2022-23 one")
    assert t.action == "restore" and t.question == Q1


def test_an_unrelated_reply_to_the_chips_runs_as_its_own_message():
    s = _session()
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    ask(s, "What about FY 2023-24?", scheme="MGNREGA", district=EKH, year=2023)
    q = "Go back to the East Khasi Hills one"
    s.turn_context = {}
    with pytest.raises(p.ClarificationNeeded) as e:
        tm.resolve_turn(s, q)
    remember_pause(s, pause_question(s, q), e.value)
    t = ask(s, "How many PMAY-G houses were sanctioned?", scheme="PMAY-G")
    assert t.action == "continue" and s.pending_scope_q is None


# ── Not a reference: runs exactly as before ─────────────────────────────────

@pytest.mark.parametrize("q", [
    "What about East Khasi Hills?",
    "continue with MGNREGA beneficiaries in East Khasi Hills",
    "Which one had the highest?",
    "show the last one",
    "How many beneficiaries before 2023?",
    "Show it again by block",
    "How many PMAY-G houses were completed in Ri Bhoi?",
])
def test_ordinary_questions_are_untouched(q):
    s = _session()
    _four_questions(s)
    before = (s.state.scheme, s.state.district, s.state.year)
    s.turn_context = {}
    t = tm.resolve_turn(s, q)
    assert t.action == "continue" and t.question == q
    assert (s.state.scheme, s.state.district, s.state.year) == before


def test_a_reference_that_matches_nothing_runs_as_before():
    s = _session()
    _four_questions(s)
    s.turn_context = {}
    t = tm.resolve_turn(s, "Go back to the Ri Bhoi one")
    assert t.action == "continue" and t.question == "Go back to the Ri Bhoi one"


def test_off_switch(monkeypatch):
    s = _session()
    _four_questions(s)
    monkeypatch.setattr(settings, "BACKWARD_RESOLVER_ENABLED", False)
    s.turn_context = {}
    t = tm.resolve_turn(s, "Go back to the East Khasi Hills one")
    assert t.action == "continue"


# ── "What did we discuss?" ──────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["What did we discuss so far?", "what have we talked about",
                               "list my previous questions", "Summarise our conversation",
                               "ok what all did I ask?"])
def test_history_requests_are_recognised(q):
    assert tm.parse_history(q)


@pytest.mark.parametrize("q", ["What did we discuss about MGNREGA wages?", "How many questions are there?",
                               "What is MGNREGA?"])
def test_other_questions_are_not_history_requests(q):
    assert not tm.parse_history(q)


def test_history_lists_the_questions_numbered_and_keeps_the_topic():
    s = _session()
    _four_questions(s)
    t = ask(s, "What did we discuss so far?")
    r = t.response
    assert r["edge_type"] == tm.HISTORY_EDGE and r["confidence"] == "low"
    assert f"1. {Q1}" in r["answer"] and f"3. {Q3}" in r["answer"] and "**PMAY-G**" in r["answer"]
    assert r["suggestions"][0] == Q4                            # most recent first
    # an aside: the answer before it stays the follow-up antecedent
    from app import conversation_layer
    assert conversation_layer.resume_after_small_talk(s)
    assert s.last_turn.question == Q4


def test_history_with_nothing_discussed_yet():
    s = _session()
    t = ask(s, "what did we talk about?")
    assert "haven't looked at any scheme" in t.response["answer"]


# ── Never cached ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["Go back to the East Khasi Hills one", "go back to question 3",
                               "What did we discuss so far?", "MGNREGA ka 2022 wala figure batao"])
def test_references_are_never_cached(q):
    s = _session()
    assert tm.is_topic_command(q)
    assert not is_cacheable(q, s)


# ── Phase 4: the model picks a ledger id for a reference the rules cannot place ──
import asyncio  # noqa: E402

from app import llm  # noqa: E402

VAGUE = "What was that figure you gave earlier?"


def _model(monkeypatch, reply=None, exc=None):
    calls = []

    async def fake(prompt, **kw):
        calls.append((prompt, kw))
        if exc is not None:
            raise exc
        return reply
    monkeypatch.setattr(llm, "call_rewriter", fake)
    return calls


def _refer(s, q):
    """The context stage's order: the rules (resolve_turn, which also files
    the last answer), then the model only when they placed nothing."""
    s.turn_context = {}
    t = tm.resolve_turn(s, q)
    if t.action not in ("continue", "none"):
        return None
    return asyncio.run(tm.resolve_reference(s, q))


def test_rules_place_nothing_so_the_model_picks_a_listed_id(monkeypatch):
    calls = _model(monkeypatch, "q1")
    s = _session()
    _four_questions(s)
    assert tm.resolve_turn(s, VAGUE).action == "continue"           # the rules found nothing
    t = _refer(s, VAGUE)
    assert t.action == "restore" and t.question == Q1 and s.state.district == EKH
    prompt, kw = calls[0]
    assert kw["role"] == "reference" and "q1: " + Q1 in prompt and "q4: " + Q4 in prompt


@pytest.mark.parametrize("reply", ["East Khasi Hills, 2022", "q9", "", "I think it is about MGNREGA"])
def test_anything_but_a_listed_id_asks_never_guesses(monkeypatch, reply):
    _model(monkeypatch, reply)
    s = _session()
    _four_questions(s)
    with pytest.raises(p.ClarificationNeeded) as e:
        _refer(s, VAGUE)
    assert e.value.rule == tm.LEDGER_PAUSE_RULE and len(e.value.options) == 4
    assert s.state.scheme == "PMAY-G"                                # nothing restored


def test_none_runs_the_turn_as_before(monkeypatch):
    _model(monkeypatch, "NONE")
    s = _session()
    _four_questions(s)
    assert _refer(s, VAGUE) is None and s.state.scheme == "PMAY-G"


def test_a_failed_model_call_runs_the_turn_as_before(monkeypatch):
    _model(monkeypatch, exc=TimeoutError())
    s = _session()
    _four_questions(s)
    assert _refer(s, VAGUE) is None


def test_with_one_question_an_unclear_pick_is_not_a_chip(monkeypatch):
    _model(monkeypatch, "maybe")
    s = _session()
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    assert _refer(s, VAGUE) is None


@pytest.mark.parametrize("q", ["What about Ri Bhoi?", "Go back to the East Khasi Hills one",
                               "How many PMAY-G houses were completed in 2023?", "What did we discuss?"])
def test_the_model_is_not_called_when_there_is_no_unplaced_reference(monkeypatch, q):
    calls = _model(monkeypatch, "q1")
    s = _session()
    _four_questions(s)
    assert _refer(s, q) is None and calls == []


def test_the_model_is_not_called_with_the_flag_off(monkeypatch):
    calls = _model(monkeypatch, "q1")
    monkeypatch.setattr(settings, "LLM_REFERENCE_ENABLED", False)
    s = _session()
    _four_questions(s)
    assert _refer(s, VAGUE) is None and calls == []


# ── Phase 5: hierarchy (§9.5) and permissions (§9.6) ─────────────────────────

def _data(s, q, plan=None, **resolved):
    s.turn_context = {"plan": plan} if plan else {}
    cm.update_state(s, q, q, {"route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1",
                              "resolved_entities": resolved, "answer": "x"})


def test_a_new_district_clears_the_old_block_and_village_even_without_a_clear_in_the_plan():
    s = _session()
    _data(s, "MGNREGA expenditure in Mawphlang block", district=EKH, block="MAWPHLANG", village="LAITLYNGKOT")
    # a follow-up whose plan REPLACEs the district but says nothing about the block
    _data(s, "and Ri Bhoi?", plan={"kind": "GEOGRAPHY_CHANGE", "actions": {"district": "REPLACE"}}, district=RIB)
    assert (s.state.district, s.state.block, s.state.village) == (RIB, None, None)


def test_a_new_block_clears_the_old_village_and_keeps_the_district():
    s = _session()
    _data(s, "MGNREGA in Laitlyngkot", district=EKH, block="MAWPHLANG", village="LAITLYNGKOT")
    _data(s, "only Mylliem", plan={"kind": "GEOGRAPHY_CHANGE", "actions": {"block": "REPLACE"}},
          district=EKH, block="MYLLIEM")
    assert (s.state.district, s.state.block, s.state.village) == (EKH, "MYLLIEM", None)


def test_the_same_district_named_again_keeps_the_block():
    s = _session()
    _data(s, "MGNREGA in Mawphlang", district=EKH, block="MAWPHLANG")
    _data(s, "and in 2023-24?", plan={"kind": "TIME_CHANGE", "actions": {"year": "REPLACE"}},
          district=EKH, block="MAWPHLANG", year_key=2023)
    assert (s.state.district, s.state.block) == (EKH, "MAWPHLANG")


def test_a_denied_turn_is_never_stored_or_filed():
    s = _session()
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    s.turn_context = {}
    tm.resolve_turn(s, "And West Garo Hills?")
    denied = {"route": "denied", "intent": "DATA", "schemes": ["MGNREGA"], "denied": True,
              "resolved_entities": {"district": WGH}, "answer": "You can view East Khasi Hills only."}
    cm.update_state(s, "And West Garo Hills?", "And West Garo Hills?", denied)
    s.turns.append(build_turn("And West Garo Hills?", denied))
    assert s.state.district == EKH
    assert [e["n"] for e in ledger(s, "MGNREGA")] == [1]


# ── Phase 6: the scope banner (S2) ──────────────────────────────────────────

def _data_result(resolved, schemes=("MGNREGA",)):
    return {"route": "data", "schemes": list(schemes), "sql": "SELECT 1", "resolved_entities": resolved}


@pytest.mark.parametrize("resolved, schemes, banner", [
    ({"district": EKH, "year_key": 2022}, ["MGNREGA"], "MGNREGA · East Khasi Hills · FY 2022-23"),
    ({}, ["PMAY-G"], "PMAY-G · All of Meghalaya"),
    ({"district": EKH, "block": "MAWPHLANG", "year_key": 2023}, ["MGNREGA"], "MGNREGA · Mawphlang · FY 2023-24"),
    ({"assembly_constituency": "MAWLAI"}, ["Focus Plus"], "Focus Plus · Mawlai constituency"),
    ({"district_list": [EKH, RIB], "year_key_list": [2022, 2023]}, ["MGNREGA", "PMAY-G"],
     "MGNREGA + PMAY-G · East Khasi Hills, Ri Bhoi · FY 2022-23, FY 2023-24"),
])
def test_the_banner_names_the_scope_the_sql_ran_with(resolved, schemes, banner):
    r = _data_result(resolved, schemes)
    p._attach_scope_banner(r, None)
    assert r["scope_banner"] == banner


def test_a_restored_scope_says_from_earlier():
    s = _session()
    s.turn_context = {"restored_question": True}
    r = _data_result({"district": EKH, "year_key": 2022})
    p._attach_scope_banner(r, s)
    assert r["scope_banner"].endswith("(from earlier)")


@pytest.mark.parametrize("r", [{"route": "knowledge", "schemes": ["MGNREGA"], "answer": "x"},
                               {"route": "data", "schemes": ["MGNREGA"], "sql": None},
                               {"route": "edge", "answer": "hi"}])
def test_no_banner_without_a_data_query(r):
    p._attach_scope_banner(r, None)
    assert "scope_banner" not in r


# ── Phase 6: "Continue with …?" after an idle expiry (S3) ───────────────────
from app import conversation_layer as cl  # noqa: E402


@pytest.fixture()
def _expiry(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 1800)
    monkeypatch.setattr(settings, "CONVERSATION_LAYER_ENABLED", True)

    async def drop(_sid):
        return None
    monkeypatch.setattr(cl, "_drop_paused_run", drop)


def _idle(s):
    ask(s, Q1, scheme="MGNREGA", district=EKH, year=2022)
    s.context_at = time.time() - 1801


def test_an_expiry_sets_the_topic_aside_and_offers_it_once(_expiry):
    s = _session()
    _idle(s)
    lt = asyncio.run(cl.prepare_turn(s, "How many PMAY-G houses were completed?"))
    assert lt.action == "expired" and s.state.scheme is None           # starts fresh, as before
    chip = "Continue with MGNREGA (East Khasi Hills, FY 2022-23)"
    assert s.expired_ctx["chip"] == chip
    r = cl.attach_continue_offer(s, {"route": "data", "answer": "x"})
    assert r["continue_offer"] == chip
    assert "continue_offer" not in cl.attach_continue_offer(s, {"route": "data"})   # once


def test_tapping_the_chip_puts_the_topic_back(_expiry):
    s = _session()
    _idle(s)
    asyncio.run(cl.prepare_turn(s, "hello"))
    lt = asyncio.run(cl.prepare_turn(s, "Continue with MGNREGA (East Khasi Hills, FY 2022-23)"))
    assert lt.action == "continue-expired" and lt.changed
    assert lt.response["edge_type"] == cl.CONTINUE_EDGE and "East Khasi Hills" in lt.response["answer"]
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", EKH, 2022)
    assert s.last_turn.question == Q1 and s.expired_ctx is None
    tm.checkpoint(s)                       # the next turn files the restored last turn
    assert "MGNREGA" in s.topics["items"] and ledger(s, "MGNREGA")[0]["question"] == Q1


def test_ignoring_the_chip_drops_it(_expiry):
    s = _session()
    _idle(s)
    asyncio.run(cl.prepare_turn(s, "How many PMAY-G houses were completed?"))
    asyncio.run(cl.prepare_turn(s, "What about Ri Bhoi?"))
    assert s.expired_ctx is None
    lt = asyncio.run(cl.prepare_turn(s, "Continue with MGNREGA (East Khasi Hills, FY 2022-23)"))
    assert lt.action != "continue-expired"


def test_the_set_aside_context_survives_the_snapshot(_expiry):
    s = _session()
    _idle(s)
    asyncio.run(cl.prepare_turn(s, "hello"))
    other = _session()
    other.apply_snapshot(s.to_snapshot())
    assert other.expired_ctx["chip"] == s.expired_ctx["chip"]
    lt = asyncio.run(cl.prepare_turn(other, "continue with mgnrega (east khasi hills, fy 2022-23)?"))
    assert lt.action == "continue-expired" and other.state.district == EKH


def test_no_chip_when_there_was_no_topic(_expiry):
    s = _session()
    ask(s, "What is DBT?", route="knowledge")
    s.context_at = time.time() - 1801
    asyncio.run(cl.prepare_turn(s, "hello"))
    assert s.expired_ctx is None


# ── Another worker after a knowledge digression (live 2026-10-18, scenario H) ──
import types  # noqa: E402

from app import context_policy  # noqa: E402

QH = "How many PMAY-G houses were completed in South Garo Hills in FY 2022-23?"


def _rehydrated_after_digression():
    s = _session()
    ask(s, QH, scheme="PMAY-G", district="SOUTH GARO HILLS", year=2022)
    ask(s, Q2, scheme="PMAY-G", route="knowledge")
    tm.checkpoint(s)                                   # the next turn's context stage files Q2
    other = _session()
    other.apply_snapshot(s.to_snapshot())              # another worker: only the last turn comes back
    assert [t.route for t in other.turns][-1] == "knowledge"
    assert not any(t.route == "data" for t in other.turns)
    return other


def test_a_rehydrated_worker_still_continues_the_data_turn_after_a_digression():
    other = _rehydrated_after_digression()
    plan = types.SimpleNamespace(kind=context_policy.GEOGRAPHY_CHANGE)
    t = p._data_thread_antecedent("And in West Garo Hills?", other.last_turn, other, plan)
    assert t is not None and t.route == "data" and t.question == QH


def test_the_fallback_respects_the_scheme_and_the_window():
    other = _rehydrated_after_digression()
    assert tm.recent_data_turn(other, ["MGNREGA"]) is None          # latest DATA question is PMAY-G
    assert tm.recent_data_turn(other, ["PMAY-G"]).question == QH
    assert tm.recent_data_turn(other, within=1) is None             # only the knowledge question in range


# ── "Go back to CM Elevate" finds the CM Elevate Legacy topic (live matrix 2026-10-18, F7) ──

def test_go_back_to_cm_elevate_restores_the_legacy_topic_when_it_is_the_only_one():
    s = _session()
    ask(s, "How many CM Elevate applications are there in Ri Bhoi?", scheme="CM Elevate Legacy", district=RIB)
    ask(s, Q4, scheme="PMAY-G")
    t = ask(s, "Go back to CM Elevate")
    assert t.action == "switch" and t.topic == "CM Elevate Legacy" and s.state.district == RIB


def test_go_back_to_cm_elevate_with_both_topics_takes_the_exact_one():
    # An exact topic name wins, as for every other scheme; the Legacy fallback
    # is only for a conversation that never had a "CM Elevate" topic.
    s = _session()
    ask(s, "How many CM Elevate applicants are pending in Ri Bhoi?", scheme="CM Elevate", district=RIB)
    ask(s, "How much was disbursed under CM Elevate Legacy in FY 2024-25?", scheme="CM Elevate Legacy", year=2024)
    ask(s, Q4, scheme="PMAY-G")
    t = ask(s, "Go back to CM Elevate")
    assert t.action == "switch" and t.topic == "CM Elevate" and s.state.district == RIB


# ── A pure "go back" is not a new numbered question (browser check 2026-10-18) ──

def test_a_pure_go_back_is_not_filed_as_a_new_question():
    s = _session()
    _four_questions(s)
    # the router keeps the typed text as the question when nothing was rewritten
    s.turn_context = {}
    t = tm.resolve_turn(s, "Go back to the East Khasi Hills one")
    assert t.action == "restore"
    result = {"route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1",
              "resolved_entities": {"district": EKH, "year_key": 2022}, "answer": "x"}
    cm.update_state(s, "Go back to the East Khasi Hills one", "Go back to the East Khasi Hills one", result)
    s.turns.append(build_turn("Go back to the East Khasi Hills one", result))
    assert [e["n"] for e in ledger(s, "MGNREGA")] == [1, 3]      # nothing new filed
    assert "Go back" not in tm._history_answer(tm._memory(s))["answer"]


def test_a_go_back_with_a_new_question_is_filed():
    s = _session()
    _four_questions(s)
    s.turn_context = {}
    t = tm.resolve_turn(s, "Go back to the first question, what about Ri Bhoi?")
    assert t.question == "what about Ri Bhoi?"
    rewritten = "How many MGNREGA person-days were generated in Ri Bhoi in FY 2022-23?"
    result = {"route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1",
              "resolved_entities": {"district": RIB, "year_key": 2022}, "answer": "x",
              "rewritten_question": rewritten}
    cm.update_state(s, "Go back to the first question, what about Ri Bhoi?", rewritten, result)
    s.turns.append(build_turn("Go back to the first question, what about Ri Bhoi?", result))
    assert [e["question"] for e in ledger(s, "MGNREGA")][-1] == rewritten


def test_a_follow_up_right_after_the_continue_tap_has_the_restored_turn_as_antecedent(_expiry):
    s = _session()
    _idle(s)
    asyncio.run(cl.prepare_turn(s, "hello"))
    chip = "Continue with MGNREGA (East Khasi Hills, FY 2022-23)"
    lt = asyncio.run(cl.prepare_turn(s, chip))
    s.turns.append(build_turn(chip, lt.response))          # the router keeps the acknowledgement
    assert s.last_turn.route == "edge"
    lt2 = asyncio.run(cl.prepare_turn(s, "What about FY 2023-24?"))
    assert lt2.question == "What about FY 2023-24?"
    assert s.last_turn.question == Q1                       # the aside was skipped


# ── "Compare this with the MGNREGA figure you showed" (proposal §9.3 mid-sentence) ──

def _pmay_ekh_session():
    s = _session()
    ask(s, "How many PMAY-G houses were completed in East Khasi Hills in FY 2022-23?",
        scheme="PMAY-G", district=EKH, year=2022)
    return s


@pytest.mark.parametrize("q", ["Compare this with the MGNREGA figure you showed",
                               "compare this with MGNREGA", "How does this compare to MGNREGA?",
                               "ok, compare that number against the MGNREGA one from earlier",
                               "this vs MGNREGA?"])
def test_compare_this_with_another_scheme_becomes_the_two_scheme_question(q):
    s = _pmay_ekh_session()
    assert cl.comparison_with_earlier(s, q) == "Compare PMAY-G and MGNREGA in East Khasi Hills in FY 2022-23"


def test_compare_uses_all_years_and_statewide_when_the_scope_says_so():
    s = _session()
    ask(s, "How many PMAY-G houses were completed?", scheme="PMAY-G")
    s.state.year_all = True
    assert cl.comparison_with_earlier(s, "compare this with MGNREGA") ==         "Compare PMAY-G and MGNREGA in Meghalaya across all financial years"


@pytest.mark.parametrize("q", ["Compare MGNREGA and PMAY-G in Ri Bhoi",          # both named: the pipeline's own
                               "compare this with the previous year",            # no scheme
                               "Compare this with CM Elevate Legacy and MGNREGA",   # two named
                               "What about MGNREGA?"])
def test_other_messages_are_untouched(q):
    s = _pmay_ekh_session()
    assert cl.comparison_with_earlier(s, q) is None


def test_no_active_scheme_means_no_rewrite():
    s = _session()
    assert cl.comparison_with_earlier(s, "compare this with MGNREGA") is None


def test_the_layer_runs_the_comparison_and_never_caches_it():
    s = _pmay_ekh_session()
    lt = asyncio.run(cl.prepare_turn(s, "Compare this with the MGNREGA figure you showed"))
    assert lt.action == "compare" and lt.changed
    assert lt.question == "Compare PMAY-G and MGNREGA in East Khasi Hills in FY 2022-23"
