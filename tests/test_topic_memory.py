"""
Topic memory (app/topic_memory.py): several topics in one conversation, each
with its own context, and going back to an earlier one.

Each turn is folded in with the REAL context_manager.update_state and the
router's REAL build_turn, so what topic_memory files and restores is exactly
what the pipeline would hold. No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_topic_memory.py -q
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_manager as cm, pipeline as p, topic_memory as tm  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn, pause_question, remember_pause  # noqa: E402
from app.session_store import Session  # noqa: E402

EKH, WGH, RIB = "EAST KHASI HILLS", "WEST GARO HILLS", "RI BHOI"


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_LAYER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_STATE_ENABLED", True)


def _session():
    return Session(session_id="topic-1", user_id="u", created=time.time(), last_seen=time.time())


def ask(session, question, *, scheme=None, district=None, year=None, route="data"):
    """One turn the way the graph + router run it: resolve the topic (the
    context stage's first step), then, unless the topic layer answered,
    'answer' with the given scheme / district / year and fold it in."""
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


def topics(session):
    return [d["topic"] for d in tm.describe(session)["topics"]]


def item(session, key):
    return session.topics["items"][key]


# ── Detecting a switch ──────────────────────────────────────────────────────

@pytest.mark.parametrize("q, names, remainder", [
    ("Go back to MGNREGA", ["MGNREGA"], ""),
    ("Go back to MGNREGA. What about 2023?", ["MGNREGA"], "What about 2023?"),
    ("Coming back to PMAY, how many houses were completed?", ["PMAY-G"], "how many houses were completed?"),
    ("Let's continue MGNREGA", ["MGNREGA"], ""),
    ("Back to the previous MGNREGA question", ["MGNREGA"], ""),
    ("ok now go back to manrega", ["MGNREGA"], ""),
    ("switch back to pmay-g and what about 2022?", ["PMAY-G"], "what about 2022?"),
    ("Go back to MGNREGA: What about 2024?", ["MGNREGA"], "What about 2024?"),
])
def test_named_switches_are_recognised(q, names, remainder):
    sw = tm.parse_switch(q)
    assert sw is not None and sw.names == names and sw.remainder == remainder


def test_unnamed_and_bare_focus_switches():
    sw = tm.parse_switch("Coming back to the previous question, what about 2024?")
    assert sw.names == [] and not sw.bare_focus and sw.remainder == "what about 2024?"
    assert tm.parse_switch("Now regarding FOCUS").bare_focus


@pytest.mark.parametrize("q", [
    "What about MGNREGA?",            # the existing scheme swap, unchanged
    "What about 2024?",
    "How many beneficiaries in MGNREGA?",
    "continue with MGNREGA beneficiaries in East Khasi Hills",   # a question, not a switch
    "back to back houses in PMAY",
    "resume",
])
def test_ordinary_questions_are_not_switches(q):
    assert tm.parse_switch(q) is None
    assert not tm.is_topic_command(q)


# ── Test 1: one topic ───────────────────────────────────────────────────────

def test_single_topic_follow_ups_stay_in_the_topic():
    s = _session()
    ask(s, "How many MGNREGA beneficiaries are there?", scheme="MGNREGA")
    t = ask(s, "What about East Khasi Hills?", scheme="MGNREGA", district=EKH)
    assert t.action == "continue" and t.topic == "MGNREGA"
    t = ask(s, "What about 2024?", scheme="MGNREGA", district=EKH, year=2024)
    assert t.question == "What about 2024?"           # untouched: the follow-up layer handles it
    tm.checkpoint(s)
    assert topics(s) == ["MGNREGA"] and s.topics["active"] == "MGNREGA"
    assert item(s, "MGNREGA")["turns"] == 3
    assert item(s, "MGNREGA")["state"]["district"] == EKH


# ── Test 2: two topics ──────────────────────────────────────────────────────

def _mgnrega_then_pmay(s):
    ask(s, "How many MGNREGA beneficiaries are there?", scheme="MGNREGA")
    ask(s, "What about East Khasi Hills?", scheme="MGNREGA", district=EKH)
    ask(s, "What about 2024?", scheme="MGNREGA", district=EKH, year=2024)
    ask(s, "How many PMAY-G houses were sanctioned in West Garo Hills in 2023?",
        scheme="PMAY-G", district=WGH, year=2023)
    ask(s, "How many were completed?", scheme="PMAY-G", district=WGH, year=2023)


def test_two_topics_keep_independent_contexts():
    s = _session()
    _mgnrega_then_pmay(s)
    tm.checkpoint(s)
    assert topics(s) == ["MGNREGA", "PMAY-G"] and s.topics["active"] == "PMAY-G"
    m, pm = item(s, "MGNREGA")["state"], item(s, "PMAY-G")["state"]
    assert (m["scheme"], m["district"], m["year"]) == ("MGNREGA", EKH, 2024)
    assert (pm["scheme"], pm["district"], pm["year"]) == ("PMAY-G", WGH, 2023)


# ── Test 3: switch back ─────────────────────────────────────────────────────

def test_bare_switch_restores_the_topic_and_acknowledges():
    s = _session()
    _mgnrega_then_pmay(s)
    t = ask(s, "Go back to MGNREGA")
    assert t.action == "switch" and t.topic == "MGNREGA"
    r = t.response
    assert r["route"] == "edge" and r["edge_type"] == tm.TOPIC_SWITCH_EDGE
    assert "MGNREGA" in r["answer"] and "PMAY" not in r["answer"]
    # The restored context is MGNREGA's, not PMAY-G's (test 5: isolation).
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", EKH, 2024)
    # The next message continues MGNREGA: its antecedent is MGNREGA's last
    # turn, not the acknowledgement and not the PMAY-G turn.
    t = tm.resolve_turn(s, "What about 2023?")
    assert t.action == "continue" and t.topic == "MGNREGA"
    assert s.last_turn.schemes == ["MGNREGA"] and s.last_turn.question == "What about 2024?"
    assert (s.state.scheme, s.state.district) == ("MGNREGA", EKH)


def test_switch_with_a_question_runs_the_question_in_that_topic():
    s = _session()
    _mgnrega_then_pmay(s)
    t = ask(s, "Go back to MGNREGA. What about 2023?", scheme="MGNREGA", district=EKH, year=2023)
    assert t.response is None and t.question == "What about 2023?" and t.topic == "MGNREGA"
    assert s.state.scheme == "MGNREGA" and s.state.district == EKH and s.state.year == 2023
    # PMAY-G's record is untouched by the MGNREGA turn.
    assert item(s, "PMAY-G")["state"]["district"] == WGH


def test_turn_count_stays_the_conversations():
    s = _session()
    _mgnrega_then_pmay(s)
    n = s.state.turn_count
    tm.resolve_turn(s, "Go back to MGNREGA")
    assert s.state.turn_count == n


# ── Test 4: three topics ────────────────────────────────────────────────────

def test_three_topics_restore_the_right_context_at_every_switch():
    s = _session()
    _mgnrega_then_pmay(s)
    ask(s, "Focus Plus beneficiaries in Ri Bhoi", scheme="Focus Plus", district=RIB)
    ask(s, "Back to PMAY")
    assert (s.state.scheme, s.state.district, s.state.year) == ("PMAY-G", WGH, 2023)
    ask(s, "What about 2022?", scheme="PMAY-G", district=WGH, year=2022)
    ask(s, "Go back to MGNREGA")
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", EKH, 2024)
    tm.checkpoint(s)
    assert item(s, "PMAY-G")["state"]["year"] == 2022          # the PMAY-G follow-up was kept
    assert item(s, "Focus Plus")["state"]["district"] == RIB
    assert s.topics["order"][-1] == "MGNREGA"


# ── Test 5: isolation ───────────────────────────────────────────────────────

def test_filters_never_cross_topics():
    s = _session()
    _mgnrega_then_pmay(s)
    ask(s, "Go back to MGNREGA")
    ask(s, "What about Ri Bhoi?", scheme="MGNREGA", district=RIB, year=2024)
    ask(s, "Back to PMAY-G")
    assert s.state.district == WGH and s.state.scheme == "PMAY-G"
    tm.checkpoint(s)
    assert item(s, "MGNREGA")["state"]["district"] == RIB


def test_a_knowledge_digression_does_not_take_the_data_state():
    s = _session()
    ask(s, "MGNREGA person-days in East Khasi Hills 2024", scheme="MGNREGA", district=EKH, year=2024)
    ask(s, "What is PMAY-G?", scheme="PMAY-G", route="knowledge")
    tm.checkpoint(s)
    # The data state (still MGNREGA's, update_state leaves it) is filed under
    # MGNREGA, never under the PMAY-G knowledge topic.
    assert item(s, "PMAY-G")["state"] is None
    assert item(s, "MGNREGA")["state"]["district"] == EKH
    ask(s, "Go back to MGNREGA")
    assert (s.state.scheme, s.state.district) == ("MGNREGA", EKH)


# ── Test 6: ambiguous ───────────────────────────────────────────────────────

def test_unnamed_return_with_one_other_topic_goes_there():
    s = _session()
    _mgnrega_then_pmay(s)
    t = ask(s, "Coming back to the previous topic")
    assert t.topic == "MGNREGA" and s.state.district == EKH


def test_unnamed_return_with_several_topics_asks_and_the_reply_picks():
    s = _session()
    _mgnrega_then_pmay(s)
    ask(s, "Focus Plus beneficiaries in Ri Bhoi", scheme="Focus Plus", district=RIB)
    s.turn_context = {"standalone_question": "a stale value from an earlier turn"}
    q = "Go back to the previous question, what about 2024?"
    with pytest.raises(p.ClarificationNeeded) as e:
        tm.resolve_turn(s, q)
    assert e.value.rule == tm.TOPIC_PAUSE_RULE
    assert [o["label"] for o in e.value.options] == ["PMAY-G", "MGNREGA"]      # most recent first
    assert e.value.options[1]["question"] == "Go back to MGNREGA: what about 2024?"
    assert s.state.scheme == "Focus Plus"                  # nothing switched while asking
    remember_pause(s, pause_question(s, q), e.value)
    assert s.pending_scope_q == q
    # A typed name picks the topic; the paused question's remainder runs in it.
    t = tm.resolve_turn(s, "mgnrega")
    assert t.topic == "MGNREGA" and t.question == "what about 2024?"
    assert s.pending_scope_q is None and s.state.district == EKH


def test_the_chip_reply_picks_the_topic():
    s = _session()
    _mgnrega_then_pmay(s)
    ask(s, "Focus Plus beneficiaries in Ri Bhoi", scheme="Focus Plus", district=RIB)
    with pytest.raises(p.ClarificationNeeded) as e:
        tm.resolve_turn(s, "back to the earlier topic")
    remember_pause(s, pause_question(s, "back to the earlier topic"), e.value)
    t = tm.resolve_turn(s, e.value.options[0]["question"])       # "Go back to PMAY-G"
    assert t.topic == "PMAY-G" and t.response is not None and s.state.district == WGH


def test_bare_focus_is_never_guessed():
    s = _session()
    ask(s, "Focus Plus beneficiaries in Ri Bhoi", scheme="Focus Plus", district=RIB)
    ask(s, "MGNREGA person-days", scheme="MGNREGA", district=EKH)
    # One Focus topic in this conversation: going back to it is not a guess.
    assert ask(s, "go back to focus").topic == "Focus Plus"
    ask(s, "Focus Legacy payments in Ri Bhoi", scheme="Focus Legacy", district=RIB)
    ask(s, "MGNREGA in 2023", scheme="MGNREGA", district=EKH, year=2023)
    with pytest.raises(p.ClarificationNeeded) as e:
        tm.resolve_turn(s, "go back to focus")
    assert sorted(o["label"] for o in e.value.options) == ["Focus Legacy", "Focus Plus"]


# ── Existing behaviour is left alone ────────────────────────────────────────

def test_a_topic_never_discussed_runs_as_before():
    s = _session()
    ask(s, "MGNREGA person-days", scheme="MGNREGA", district=EKH)
    t = tm.resolve_turn(s, "Go back to PMAY")
    assert t.response is None and t.question == "Go back to PMAY" and t.action == "continue"
    assert s.state.scheme == "MGNREGA"


def test_regarding_the_active_topic_with_a_question_is_unchanged():
    s = _session()
    _mgnrega_then_pmay(s)
    q = "Regarding PMAY, how many houses were completed?"
    t = tm.resolve_turn(s, q)
    assert t.question == q and t.response is None


def test_an_explicit_switch_abandons_another_pending_pause():
    s = _session()
    _mgnrega_then_pmay(s)
    s.pending_scope_q, s.pending_scope_rule = "PMAY-G houses", "year-not-specified"
    ask(s, "Go back to MGNREGA")
    assert s.pending_scope_q is None and s.state.scheme == "MGNREGA"


def test_a_pending_pause_reply_is_not_touched():
    s = _session()
    _mgnrega_then_pmay(s)
    s.pending_scope_q, s.pending_scope_rule = "PMAY-G houses", "year-not-specified"
    t = tm.resolve_turn(s, "2023-24")
    assert t.question == "2023-24" and s.pending_scope_q == "PMAY-G houses"


def test_off_when_the_context_layer_is_off(monkeypatch):
    s = _session()
    _mgnrega_then_pmay(s)
    monkeypatch.setattr(settings, "CONTEXT_LAYER_ENABLED", False)
    t = tm.resolve_turn(s, "Go back to MGNREGA")
    assert t.response is None and t.question == "Go back to MGNREGA" and s.state.scheme == "PMAY-G"


def test_the_number_of_topics_is_bounded():
    s = _session()
    for i in range(tm.MAX_TOPICS + 3):
        s.turns.append(build_turn(f"q{i}", {"route": "data", "schemes": [f"S{i}"], "answer": "x"}))
        tm.checkpoint(s)
    assert len(s.topics["items"]) == tm.MAX_TOPICS == len(s.topics["order"])
    assert "S0" not in s.topics["items"]


def test_a_comparison_is_its_own_topic():
    assert tm.topic_key(["PMAY-G", "MGNREGA"]) == "MGNREGA + PMAY-G"
    s = _session()
    s.turns.append(build_turn("MGNREGA vs PMAY-G", {"route": "data", "schemes": ["PMAY-G", "MGNREGA"]}))
    tm.checkpoint(s)
    assert topics(s) == ["MGNREGA + PMAY-G"]


# ── Through the real graph (models / RAG / DB stubbed, as test_pipeline_graph) ─
# The existing `env` stubs and `converse` driver, reused unchanged: every
# stage, gate and context function is real.
from test_pipeline_graph import CME, _loaded, converse, env  # noqa: E402,F401

MG_WGH = "How many MGNREGA person-days in West Garo Hills in 2023-24?"


def _answer(outcome):
    kind, result = outcome[0], outcome[1]
    assert kind == "answer", outcome
    return result


def test_graph_go_back_then_follow_up_continues_the_old_topic(env, monkeypatch):
    out, s = converse([CME, MG_WGH, "Go back to CM Elevate", "What about West Khasi Hills?"],
                      monkeypatch=monkeypatch)
    assert "v_employment" in _answer(out[1])["sql"]
    ack = _answer(out[2])
    assert ack["edge_type"] == tm.TOPIC_SWITCH_EDGE and "CM Elevate" in ack["answer"]
    assert out[2][2]["scheme"] == "CM Elevate" and out[2][2]["district"] == "EAST KHASI HILLS"
    r = _answer(out[3])
    # Continued CM Elevate with the district replaced; nothing from MGNREGA
    # (West Garo Hills, 2023-24) leaked in.
    assert r["schemes"] == ["CM Elevate"]
    assert "v_cm_elevate" in r["sql"] and "WEST KHASI HILLS" in r["sql"]
    assert "WEST GARO" not in r["sql"] and "year_key" not in r["sql"]
    assert out[3][2]["scheme"] == "CM Elevate" and out[3][2]["district"] == "WEST KHASI HILLS"


def test_graph_switch_with_a_question_in_one_message(env, monkeypatch):
    out, s = converse([CME, MG_WGH, "Go back to CM Elevate, what about West Khasi Hills?"],
                      monkeypatch=monkeypatch)
    r = _answer(out[2])
    assert r["schemes"] == ["CM Elevate"] and "WEST KHASI HILLS" in r["sql"]
    assert "WEST GARO" not in r["sql"] and "year_key" not in r["sql"]


def test_graph_without_a_switch_the_follow_up_stays_on_the_latest_topic(env, monkeypatch):
    # Existing behaviour, unchanged: no switch means the active (latest) topic.
    out, s = converse([CME, MG_WGH, "What about West Khasi Hills?"], monkeypatch=monkeypatch)
    assert out[2][2]["scheme"] == "MGNREGA"


def test_graph_the_switch_reply_is_never_cached(env, monkeypatch):
    out, s = converse([CME, MG_WGH, "Go back to CM Elevate"], monkeypatch=monkeypatch)
    assert _answer(out[2])["confidence"] == "low"     # cache.ResponseCache.put skips it
