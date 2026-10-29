"""
Conversation layer (app/conversation_layer.py): idle expiry, "start a new
topic" / "forget the previous question", and returning to a topic in plain
words ("what was the PMAY-G information again?"), plus the durable snapshot
carrying topic memory and the router wiring.

Each turn runs the way the router + graph run it: conversation_layer.
prepare_turn, then topic_memory.resolve_turn (the context stage's first step),
then the REAL context_manager.update_state and the router's REAL build_turn.
No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_conversation_layer.py -q
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_manager as cm, conversation_layer as cl, pipeline as p, topic_memory as tm  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import Session  # noqa: E402

EKH, WGH = "EAST KHASI HILLS", "WEST GARO HILLS"


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_LAYER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_STATE_ENABLED", True)
    monkeypatch.setattr(settings, "CONVERSATION_LAYER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 1800)


@pytest.fixture(autouse=True)
def _no_graph(monkeypatch):
    """No LangGraph runtime here: record the paused-run drops instead."""
    dropped = []

    async def drop(session_id):
        dropped.append(session_id)
    monkeypatch.setattr(cl, "_drop_paused_run", drop)
    return dropped


def _session(sid="conv-1"):
    return Session(session_id=sid, user_id="u", created=time.time(), last_seen=time.time())


def ask(session, question, *, scheme=None, district=None, year=None, route="data"):
    """One turn: the layer, then topic memory, then (unless one of them
    answered) an answer with the given scheme / district / year, folded in."""
    session.turn_context = {}
    layer = asyncio.run(cl.prepare_turn(session, question))
    if layer.response is not None:
        result, ran = layer.response, layer.question
    else:
        t = tm.resolve_turn(session, layer.question)
        ran = t.question
        if t.response is not None:
            result = t.response
        elif route == "data":
            resolved = {k: v for k, v in (("district", district), ("year_key", year)) if v is not None}
            result = {"route": "data", "intent": "DATA", "schemes": [scheme], "sql": "SELECT 1",
                      "resolved_entities": resolved, "answer": f"{scheme} answer"}
        else:
            result = {"route": "knowledge", "intent": "RAG", "schemes": [scheme] if scheme else [],
                      "resolved_entities": {}, "answer": f"About {scheme}."}
        cm.update_state(session, layer.question, ran, result)
    session.turns.append(build_turn(layer.question, result))
    return SimpleNamespace(layer=layer, ran=ran, result=result)


# ── Reset: what counts ──────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "Start a new topic", "start a new topic.", "Let's start again", "let's start over",
    "Forget the previous question", "forget that", "Forget everything", "forget it please",
    "New topic", "Reset", "reset the conversation", "Clear the context", "ok, let's start afresh",
    "Can we start a new conversation?", "Change the topic", "Start a new topic and forget the previous one",
    "Forget what I asked before",
])
def test_bare_resets(q):
    assert cl.parse_reset(q) == ""


@pytest.mark.parametrize("q, rest", [
    ("Forget that. How many MGNREGA job cards are there?", "How many MGNREGA job cards are there?"),
    ("New topic: PMAY-G houses in Ri Bhoi", "PMAY-G houses in Ri Bhoi"),
    ("Let's start again, what is CM Elevate?", "what is CM Elevate?"),
])
def test_reset_with_a_question(q, rest):
    assert cl.parse_reset(q) == rest


@pytest.mark.parametrize("q", [
    "When did the scheme start?",
    "How many new houses were sanctioned?",
    "What is the reset date for MGNREGA wages?",
    "Show beneficiaries who started again in 2024",
    "Tell me about PMAY-G",
    "How many beneficiaries are there?",
    "What about MGNREGA?",
    "newly registered job cards",
])
def test_ordinary_questions_are_not_resets(q):
    assert cl.parse_reset(q) is None


# ── Reset: what it does ─────────────────────────────────────────────────────

def test_bare_reset_clears_the_context_and_acknowledges(_no_graph):
    s = _session()
    ask(s, "Tell me about PMAY-G", scheme="PMAY-G", route="knowledge")
    ask(s, "How many PMAY-G houses in West Garo Hills in 2023?", scheme="PMAY-G", district=WGH, year=2023)
    out = ask(s, "Let's start again")
    r = out.result
    assert r["route"] == "edge" and r["edge_type"] == cl.RESET_EDGE and r["confidence"] == "low"
    assert out.layer.changed
    assert (s.state.scheme, s.state.district, s.state.year) == (None, None, None)
    assert s.topics == {} and s.summary is None and s.pending_scope_q is None
    # The only turn left is the acknowledgement, which nothing follows up on.
    assert [t.route for t in s.turns] == ["edge"]
    assert _no_graph == ["conv-1"]           # a paused run would be dropped too


def test_after_a_reset_a_bare_follow_up_inherits_nothing():
    s = _session()
    ask(s, "Tell me about PMAY-G", scheme="PMAY-G", route="knowledge")
    ask(s, "Forget the previous question")
    # "How many beneficiaries?" now has no scheme to inherit: the existing
    # "which scheme?" pause is what follows, not a PMAY-G answer.
    assert s.state.scheme is None
    assert not router.is_scopeless_followup("How many beneficiaries?", s.last_turn)


def test_reset_with_a_question_runs_only_the_question():
    s = _session()
    ask(s, "How many PMAY-G houses in West Garo Hills?", scheme="PMAY-G", district=WGH)
    out = ask(s, "Forget that. How many MGNREGA job cards are there?", scheme="MGNREGA")
    assert out.layer.question == "How many MGNREGA job cards are there?" and out.layer.response is None
    assert s.state.scheme == "MGNREGA" and s.state.district is None     # West Garo Hills not carried
    assert s.last_turn.raw_question == "How many MGNREGA job cards are there?"


def test_reset_drops_a_pending_clarification():
    s = _session()
    s.pending_scope_q, s.pending_scope_rule = "How many beneficiaries?", "scheme-not-specified"
    s.turns.append(build_turn("How many beneficiaries?", {"route": "clarification"}))
    ask(s, "start over")
    assert s.pending_scope_q is None and s.pending_scope_rule is None


# ── Idle expiry ─────────────────────────────────────────────────────────────

def test_idle_conversation_starts_afresh(_no_graph):
    s = _session()
    ask(s, "How many MGNREGA beneficiaries in East Khasi Hills?", scheme="MGNREGA", district=EKH)
    s.context_at = time.time() - 1801
    out = ask(s, "How many beneficiaries?", scheme="PMAY-G")
    assert out.layer.action == "expired" and not out.layer.changed
    assert out.ran == "How many beneficiaries?"
    assert s.state.district is None              # East Khasi Hills not carried
    assert _no_graph == ["conv-1"]


def test_recent_conversation_does_not_expire():
    s = _session()
    ask(s, "How many MGNREGA beneficiaries in East Khasi Hills?", scheme="MGNREGA", district=EKH)
    s.context_at = time.time() - 1700
    out = ask(s, "What about 2024?", scheme="MGNREGA", district=EKH, year=2024)
    assert out.layer.action == "none" and s.state.district == EKH


def test_unknown_age_never_expires_and_is_stamped():
    s = _session()
    ask(s, "How many MGNREGA beneficiaries in East Khasi Hills?", scheme="MGNREGA", district=EKH)
    s.context_at = 0.0                           # a snapshot written before the layer
    out = ask(s, "What about 2024?", scheme="MGNREGA", district=EKH, year=2024)
    assert out.layer.action == "none" and s.context_at > 0


def test_expiry_zero_means_never(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 0)
    s = _session()
    ask(s, "How many MGNREGA beneficiaries in East Khasi Hills?", scheme="MGNREGA", district=EKH)
    s.context_at = time.time() - 10 * 86400
    assert ask(s, "What about 2024?", scheme="MGNREGA", district=EKH, year=2024).layer.action == "none"


# ── Returning to a topic in plain words ─────────────────────────────────────

def _pmay_then_mgnrega(s):
    ask(s, "How many PMAY-G houses were sanctioned in West Garo Hills in 2023?",
        scheme="PMAY-G", district=WGH, year=2023)
    ask(s, "How many MGNREGA beneficiaries in East Khasi Hills?", scheme="MGNREGA", district=EKH)


@pytest.mark.parametrize("q", [
    "What was the PMAY-G information again?",
    "Remind me about PMAY-G",
    "Can you show the PMAY-G data again?",
    "what were the pmay figures again",
    "Recap PMAY-G for me",
])
def test_recall_restores_the_earlier_topic(q):
    s = _session()
    _pmay_then_mgnrega(s)
    out = ask(s, q, scheme="PMAY-G", district=WGH, year=2023)
    assert out.layer.action == "recall" and out.layer.changed
    assert out.layer.question.startswith("Go back to PMAY-G, ")
    # topic_memory restored PMAY-G's place and year and re-asked its question.
    assert out.ran == "How many PMAY-G houses were sanctioned in West Garo Hills in 2023?"
    assert (s.state.scheme, s.state.district, s.state.year) == ("PMAY-G", WGH, 2023)


@pytest.mark.parametrize("q", [
    "What about PMAY-G?",                         # the existing scheme swap (KI-180), unchanged
    "PMAY-G houses in Ri Bhoi again?",            # a real question
    "How many PMAY-G houses were completed again?",
    "What was the MGNREGA information again?",    # the topic in progress
    "What was the CM Elevate information again?", # never discussed
    "Go back to PMAY-G",                          # already topic_memory's own form
])
def test_recall_leaves_other_messages_alone(q):
    s = _session()
    _pmay_then_mgnrega(s)
    assert cl.recall_target(s, q) is None


# ── A measure right after a knowledge answer ────────────────────────────────
# Live 2026-10-08: "Tell me about PMAY-G" -> "How many beneficiaries are there?"
# was asked "which scheme?". pipeline._measure_after_knowledge has the rewrite,
# but its branch is entered only when looks_like_followup is true, and "how
# many ..." reads as a standalone question.

@pytest.mark.parametrize("q", ["How many beneficiaries are there?", "How many beneficiaries?",
                               "What was the total?"])
def test_measure_after_knowledge_gets_the_scheme(q):
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    out = ask(s, q, scheme="PMAY-G")
    assert out.layer.action == "inject" and out.layer.changed
    assert out.ran == f"{q.rstrip(' ?.')} under PMAY-G?"


def test_the_pipeline_own_follow_up_branch_is_left_to_the_pipeline():
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    # looks_like_followup is true for "give me beneficiaries": the pipeline's
    # follow-up branch applies the very same rewrite, so the layer does not.
    assert cl.knowledge_measure_question(s, "give me beneficiaries") is None


@pytest.mark.parametrize("q", [
    "How many MGNREGA beneficiaries are there?",       # a scheme of its own (explicit override)
    "How many person-days were generated?",            # a measure only MGNREGA holds
    "Who is eligible?",                                # not a measure
])
def test_measure_injection_leaves_other_questions_alone(q):
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    assert cl.knowledge_measure_question(s, q) is None


def test_a_measure_with_its_own_year_takes_the_knowledge_scheme():
    # WI-2 (forward plan, 2026-10-16): the year stays, the scheme is appended —
    # "Who is eligible for PMAY-G?" then "How many in 2023-24?" used to be
    # answered for the old topic.
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    assert cl.knowledge_measure_question(s, "How many beneficiaries in 2023-24?") ==         "How many beneficiaries in 2023-24 under PMAY-G?"


def test_no_scheme_in_context_still_asks_which_scheme():
    s = _session()
    assert cl.knowledge_measure_question(s, "How many beneficiaries?") is None
    ask(s, "Hi", route="knowledge")                    # no scheme
    assert cl.knowledge_measure_question(s, "How many beneficiaries?") is None


def test_after_a_data_answer_the_pipeline_carries_the_scope_itself():
    s = _session()
    ask(s, "How many PMAY-G houses in West Garo Hills?", scheme="PMAY-G", district=WGH)
    # is_scopeless_followup handles it inside the pipeline, with the place.
    assert cl.knowledge_measure_question(s, "How many beneficiaries are there?") is None


def test_coming_back_to_a_topic_with_a_measure():
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    ask(s, "Tell me about MGNREGA.", scheme="MGNREGA", route="knowledge")
    out = ask(s, "Coming back to PMAY-G, how many beneficiaries are there?", scheme="PMAY-G")
    assert out.layer.question == "Go back to PMAY-G, how many beneficiaries are there under PMAY-G?"
    assert out.ran == "how many beneficiaries are there under PMAY-G?"
    assert s.state.scheme == "PMAY-G"


def test_a_measure_after_a_bare_return_uses_the_restored_topic():
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    ask(s, "Tell me about MGNREGA.", scheme="MGNREGA", route="knowledge")
    assert ask(s, "Go back to PMAY-G").result["edge_type"] == tm.TOPIC_SWITCH_EDGE
    out = ask(s, "How many beneficiaries are there?", scheme="PMAY-G")
    assert out.ran == "How many beneficiaries are there under PMAY-G?"


# ── "What schemes are there?" in any wording ────────────────────────────────
# UI 2026-10-09: "what schmes are present" got the off-topic refusal, and
# "what schemes are present" the "which scheme?" pause.

@pytest.mark.parametrize("q", [
    "what schmes are present", "what schemes are present", "what all schemes are there",
    "what schems are available", "wat schemes r there", "which scheams are present in this app",
    "show me all the schemes", "tell me the schemes", "give me the list of schemes",
    "available schemes", "schemes list", "how many schemes are there", "what are the schemes",
    "hi, what schemes are present?", "what programmes are there",
])
def test_listing_requests_get_the_listing_wording(q):
    # either the layer rewrites it to the listing wording, or (since 2026-10-14,
    # "how many schemes are onboarded/there") the pipeline's own cue answers it as is
    assert cl.listing_question(q) == cl.LISTING_QUESTION or p._SCHEME_LISTING_CUE.search(q)
    assert p._scheme_listing_answer(cl.LISTING_QUESTION) is not None   # the pipeline answers it


@pytest.mark.parametrize("q", [
    "what schemes are there",              # the pipeline's own cue already answers these
    "which schemes are available",
    "What schemes can you help me with?",  # the capability reply, unchanged
    "what schemes help farmers",
    "which scheme gave the most money",
    "what scheme is PMAY-G",
    "list MGNREGA beneficiaries",
    "How many beneficiaries are there?",
    "show schemes in Ri Bhoi",
])
def test_other_questions_are_not_listing_requests(q):
    assert cl.listing_question(q) is None


@pytest.mark.parametrize("q", ["what schemes are present", "which schemes are available"])
def test_listing_abandons_a_waiting_area_pause(q, _no_graph):
    s = _session()
    s.pending_scope_q, s.pending_scope_rule = "How many beneficiaries are there under PMAY-G?", "scope-not-specified"
    layer = asyncio.run(cl.prepare_turn(s, q))
    assert layer.question == cl.LISTING_QUESTION and s.pending_scope_q is None
    assert _no_graph == ["conv-1"]


def test_listing_through_the_layer():
    s = _session()
    layer = asyncio.run(cl.prepare_turn(s, "what schmes are present"))
    assert layer.question == cl.LISTING_QUESTION and layer.action == "listing" and layer.response is None


# ── "What about X?" swaps X's counterpart ───────────────────────────────────
# Live 2026-10-09: villages "in employment" for West Khasi Hills (530) ->
# "what about expenditure" became total expenditure (₹131.54 cr).

_WKH_EMP = "How many villages are there under MGNREGA in employment for West Khasi Hills across all financial years"


@pytest.mark.parametrize("q", ["what about expenditure", "What about expenditure?", "and expenditure?",
                               "expenditure?", "same for expenditure", "what about in expenditure",
                               "ok what about the expenditure data"])
def test_what_about_expenditure_keeps_the_measure(q):
    s = _session()
    ask(s, _WKH_EMP, scheme="MGNREGA", district="WEST KHASI HILLS")
    out = ask(s, q, scheme="MGNREGA", district="WEST KHASI HILLS")
    assert out.layer.action == "swap" and out.layer.changed
    assert out.ran == _WKH_EMP.replace("employment", "expenditure")


def test_swap_back_and_forth():
    s = _session()
    ask(s, _WKH_EMP, scheme="MGNREGA")
    ask(s, "what about expenditure", scheme="MGNREGA")
    out = ask(s, "and employment?", scheme="MGNREGA")
    assert out.ran == _WKH_EMP


@pytest.mark.parametrize("prev, q, want", [
    ("How many female employees are there for MGNREGA for all of Meghalaya across all financial years",
     "what about men", "How many male employees are there for MGNREGA for all of Meghalaya across all financial years"),
    ("How many women worked under MGNREGA in Ri Bhoi in 2023-24", "and men?",
     "How many men worked under MGNREGA in Ri Bhoi in 2023-24"),
    ("How many PMAY-G houses were sanctioned in West Garo Hills in 2023-24?", "what about completed",
     "How many PMAY-G houses were completed in West Garo Hills in 2023-24?"),
])
def test_other_counterparts(prev, q, want):
    s = _session()
    ask(s, prev, scheme="MGNREGA")
    assert cl.counterpart_swap(s, q) == want


@pytest.mark.parametrize("prev, q", [
    ("How many villages are there under MGNREGA for West Khasi Hills", "what about expenditure"),  # no counterpart
    (_WKH_EMP, "what about expenditure in Ri Bhoi"),        # more than the term: the rewrite decides
    (_WKH_EMP, "what about 2023-24"),
    (_WKH_EMP, "what about PMAY-G"),
])
def test_no_counterpart_leaves_the_message_alone(prev, q):
    s = _session()
    ask(s, prev, scheme="MGNREGA")
    assert cl.counterpart_swap(s, q) is None


def test_swap_after_small_talk():
    s = _session()
    ask(s, _WKH_EMP, scheme="MGNREGA")
    _edge_turn(s, "thanks", "thanks")
    out = ask(s, "what about expenditure", scheme="MGNREGA")
    assert out.ran == _WKH_EMP.replace("employment", "expenditure")


# ── Small talk does not end a topic ─────────────────────────────────────────
# Live 2026-10-08 (GN-04, reproduced with the layer off): PMAY-G data ->
# "Thanks!" -> "What about 2022-23?" was asked "which scheme?".

def _edge_turn(s, text, kind):
    result = {"route": "edge", "intent": "EDGE", "edge_type": kind, "answer": "ok"}
    cm.update_state(s, text, text, result)
    s.turns.append(build_turn(text, result))


@pytest.mark.parametrize("text, kind", [("Thanks!", "thanks"), ("thank you", "thanks"), ("Hi", "greeting")])
def test_small_talk_keeps_the_previous_answer_as_antecedent(text, kind):
    s = _session()
    ask(s, "How many PMAY-G houses in West Garo Hills in 2023?", scheme="PMAY-G", district=WGH, year=2023)
    _edge_turn(s, text, kind)
    assert cl.resume_after_small_talk(s)
    assert s.last_turn.route == "data" and s.last_turn.schemes == ["PMAY-G"]
    assert s.state.scheme == "PMAY-G" and s.state.district == WGH


def test_small_talk_after_a_knowledge_answer_still_gets_the_scheme():
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    _edge_turn(s, "thanks", "thanks")
    out = ask(s, "How many beneficiaries are there?", scheme="PMAY-G")
    assert out.ran == "How many beneficiaries are there under PMAY-G?"


def test_small_talk_on_another_worker_uses_the_durable_topic():
    s = _session()
    ask(s, "How many PMAY-G houses in West Garo Hills in 2023?", scheme="PMAY-G", district=WGH, year=2023)
    _edge_turn(s, "Thanks!", "thanks")
    asyncio.run(cl.prepare_turn(s, "ok"))        # files the PMAY-G topic (checkpoint runs in resolve_turn)
    tm.checkpoint(s)
    other = _session()
    other.apply_snapshot(s.to_snapshot())        # only the last turn comes back
    other.turns = [t for t in other.turns if t.route != "data"]
    _edge_turn(other, "Thanks!", "thanks")
    assert cl.resume_after_small_talk(other) and other.last_turn.schemes == ["PMAY-G"]


@pytest.mark.parametrize("text, kind", [("Who are you?", "identity"), ("Let's start again", "context_reset"),
                                        ("Go back to MGNREGA", "topic_switch")])
def test_other_edge_replies_are_left_alone(text, kind):
    s = _session()
    ask(s, "How many PMAY-G houses in West Garo Hills in 2023?", scheme="PMAY-G", district=WGH, year=2023)
    _edge_turn(s, text, kind)
    assert not cl.resume_after_small_talk(s)


def test_small_talk_with_nothing_before_it():
    s = _session()
    _edge_turn(s, "Hi", "greeting")
    assert not cl.resume_after_small_talk(s)


# ── The spec's acceptance scenarios, end to end through the layer ──────────

def test_scenario_complete_multi_topic_conversation():
    """Spec §22: PMAY-G -> follow-up -> MGNREGA -> follow-up -> back to PMAY-G."""
    s = _session()
    ask(s, "Tell me about PMAY-G.", scheme="PMAY-G", route="knowledge")
    ask(s, "How many PMAY-G beneficiaries are there?", scheme="PMAY-G")
    assert s.state.scheme == "PMAY-G"
    ask(s, "What about MGNREGA?", scheme="MGNREGA")
    ask(s, "How many MGNREGA beneficiaries are there?", scheme="MGNREGA")
    assert s.state.scheme == "MGNREGA"
    out = ask(s, "What was the PMAY-G information again?", scheme="PMAY-G")
    assert out.layer.action == "recall"
    assert out.ran == "How many PMAY-G beneficiaries are there?"
    assert s.state.scheme == "PMAY-G"
    assert {d["topic"] for d in tm.describe(s)["topics"]} == {"PMAY-G", "MGNREGA"}


def test_scenario_disabled_layer_is_a_pass_through(monkeypatch, _no_graph):
    monkeypatch.setattr(settings, "CONVERSATION_LAYER_ENABLED", False)
    s = _session()
    _pmay_then_mgnrega(s)
    s.context_at = time.time() - 99999
    for q in ("Let's start again", "What was the PMAY-G information again?"):
        layer = asyncio.run(cl.prepare_turn(s, q))
        assert (layer.question, layer.action, layer.response, layer.changed) == (q, "none", None, False)
    assert s.state.scheme == "MGNREGA" and _no_graph == []


def test_a_failure_inside_the_layer_never_breaks_the_turn(monkeypatch):
    s = _session()
    monkeypatch.setattr(cl, "parse_reset", lambda q: 1 / 0)
    layer = asyncio.run(cl.prepare_turn(s, "Let's start again"))
    assert layer.question == "Let's start again" and layer.response is None


# ── Durable snapshot ────────────────────────────────────────────────────────

def test_topics_and_age_survive_the_snapshot():
    s = _session()
    _pmay_then_mgnrega(s)
    tm.checkpoint(s)
    snap = s.to_snapshot()
    other = _session()                            # another worker
    other.apply_snapshot(snap)
    assert other.topics["items"].keys() == s.topics["items"].keys()
    assert other.context_at == pytest.approx(s.context_at)
    assert cl.recall_target(other, "What was the PMAY-G information again?") == "PMAY-G"


def test_an_older_snapshot_still_loads():
    s = _session()
    snap = s.to_snapshot()
    snap["_session"].pop("topics"), snap["_session"].pop("context_at")
    other = _session()
    other.apply_snapshot(snap)
    assert other.topics == {} and other.context_at == 0.0


def test_the_cleared_state_is_what_gets_saved():
    s = _session()
    ask(s, "How many PMAY-G houses in West Garo Hills?", scheme="PMAY-G", district=WGH)
    ask(s, "Start a new topic")
    snap = s.to_snapshot()
    assert snap["scheme"] is None and snap["district"] is None
    assert snap["_session"]["topics"] is None and snap["_session"]["pending"] is None
    assert snap["_session"]["last_turn"]["route"] == "edge"


# ── Router wiring (routers.query._answer) ───────────────────────────────────

def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


@pytest.fixture
def turn(monkeypatch):
    """_answer with every side effect stubbed; the pipeline records the
    question it was given and the caches record reads and writes."""
    seen = SimpleNamespace(asked=[], cache_reads=0, puts=0)

    async def cache_get(q, scope_key):
        seen.cache_reads += 1
        return None

    async def lookup(q, scope_key):
        return None, None

    async def answer_question(q, session=None, scope=None):
        seen.asked.append(q)
        return {"answer": "fresh", "route": "data", "schemes": ["MGNREGA"], "resolved_entities": {}}

    async def put(*a, **k):
        seen.puts += 1

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(router.response_cache, "get", cache_get)
    monkeypatch.setattr(router.response_cache, "put", put)
    monkeypatch.setattr(router.semantic_cache, "lookup", lookup)
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.session_sync, "sync_in", noop)
    monkeypatch.setattr(router.session_sync, "sync_out", noop)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    seen.scope = SimpleNamespace(user_id="u", db_user_id=None, tenant_id=None, username="",
                                 cache_fingerprint=lambda: "fp")
    return seen


def _post(turn, question, sid):
    return asyncio.run(router._answer(router.QueryRequest(question=question, session_id=sid),
                                      _request(), turn.scope))


def test_router_refuses_a_session_held_by_another_user(turn):
    # K-2 (chat UI audit 2026-10-29): after a sign-out on a shared computer the next
    # officer reused the previous officer's session id and continued their chat
    from fastapi import HTTPException
    _post(turn, "How many MGNREGA job cards are there in Ri Bhoi?", "conv-k2")
    other = SimpleNamespace(user_id="someone-else", db_user_id=None, tenant_id=None, username="",
                            cache_fingerprint=lambda: "fp")
    with pytest.raises(HTTPException) as e:
        asyncio.run(router._answer(router.QueryRequest(question="and in 2024-25?", session_id="conv-k2"),
                                   _request(), other))
    assert e.value.status_code == 403
    assert turn.asked == ["How many MGNREGA job cards are there in Ri Bhoi?"]


def test_router_answers_a_bare_reset_without_the_pipeline_or_caches(turn):
    out = _post(turn, "Let's start again", "conv-r1")
    assert out["edge_type"] == cl.RESET_EDGE and out["session_id"] == "conv-r1"
    assert turn.asked == [] and turn.cache_reads == 0 and turn.puts == 0


def test_router_runs_the_question_after_a_reset_uncached(turn):
    _post(turn, "Forget that. How many MGNREGA job cards are there?", "conv-r2")
    assert turn.asked == ["How many MGNREGA job cards are there?"]
    assert turn.cache_reads == 0 and turn.puts == 0


def test_router_leaves_an_ordinary_question_unchanged_and_cached(turn):
    _post(turn, "How many MGNREGA job cards are there in Ri Bhoi?", "conv-r3")
    assert turn.asked == ["How many MGNREGA job cards are there in Ri Bhoi?"]
    assert turn.cache_reads == 1 and turn.puts == 1


def test_router_never_caches_a_topic_switch(turn):
    s = _session()
    assert router.is_cacheable("Go back to MGNREGA, what about 2023?", s) is False
    assert router.is_cacheable("How many MGNREGA job cards are there in Ri Bhoi?", s) is True


# ── "Each year, for these schemes" / "why only one year?" (UI 2026-10-12) ────
_COMPLAINT = ("Okay, Mgnrega in the above query, whatever you have given, so Mandrega having only one year, so in my "
              "our database it is coming three years. I have three years, four years I have four years, but why you "
              "are giving only one year? Please cross verify and give it to me. Clear answer, I want for above query.")


def _multi_prev(s):
    ask(s, "total beneficiaries in MGNREGA, PMAY-G, CM Elevate Legacy and Focus Plus", scheme="MGNREGA")
    s.turns[-1].schemes = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate Legacy"]


def test_complaint_about_one_year_asks_every_year_for_that_scheme():
    s = _session()
    _multi_prev(s)
    assert cl.per_year_plan(s, _COMPLAINT) == ["How many MGNREGA beneficiaries were there in each financial year?"]


def test_each_year_for_all_schemes_is_one_question_per_scheme():
    s = _session()
    _multi_prev(s)
    plan = cl.per_year_plan(s, "Okay, for that query, give how many beneficiaries are there in each year for all "
                               "schemes, all years. Whatever you have given in the previous query.")
    assert plan == [f"How many {x} beneficiaries were there in each financial year?"
                    for x in ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate Legacy"]]


def test_cm_elevate_per_year_means_cm_elevate_legacy_once():
    s = _session()
    plan = cl.per_year_plan(s, "total beneficiaries in MGNREGA, PMAY-G, CM Elevate and Focus Plus in which "
                               "financial years. Mention for every scheme.")
    assert any("CM Elevate Legacy" in q for q in plan) and not any("CM Elevate beneficiaries" in q for q in plan)


@pytest.mark.parametrize("q", ["How many MGNREGA beneficiaries were there in each financial year?",
                               "How many PMAY-G houses were sanctioned in West Garo Hills in 2023-24?",
                               "What about 2022-23?", "Who is eligible for PMAY-G?"])
def test_plain_questions_are_left_to_the_pipeline(q):
    s = _session()
    _multi_prev(s)
    assert cl.per_year_plan(s, q) is None


def test_answer_many_merges_answers_and_tables():
    async def fake(q):
        if "MGNREGA" in q:
            return {"answer": "563,127 in 2022-23 and 530,969 in 2023-24.", "schemes": ["MGNREGA"], "sql_query": "S1",
                    "data": [{"financial_year_short": "2022-23", "beneficiaries": 563127},
                             {"financial_year_short": "2023-24", "beneficiaries": 530969}]}
        if "PMAY-G" in q:
            raise p.ClarificationNeeded("Which area?", options=[], rule="scope-not-specified")
        raise RuntimeError("down")
    out = asyncio.run(cl.answer_many(["How many MGNREGA beneficiaries were there in each financial year?",
                                      "How many PMAY-G beneficiaries were there in each financial year?",
                                      "How many Focus Plus beneficiaries were there in each financial year?"], fake))
    assert out["route"] == "data" and out["row_count"] == 2
    assert out["data"][0] == {"scheme": "MGNREGA", "financial_year": "2022-23", "beneficiaries": 563127}
    assert "**MGNREGA** — 563,127" in out["answer"]
    assert "**PMAY-G** — needs one more detail" in out["answer"]
    assert "**Focus Plus** — this figure could not be fetched" in out["answer"]


@pytest.mark.parametrize("q, ctx, want", [
    (_COMPLAINT, True, True),
    ("The numbers you gave are wrong, please recheck for PMAY-G", False, True),
    ("Why are you showing only 2023-24? check again", True, True),
    ("Please apply for PMAY-G on my behalf", True, False),
    ("Write an Instagram post about your answer", True, False),
    ("Book a train ticket for me", True, False),
])
def test_guardrail_model_does_not_refuse_a_follow_up_about_the_answer(q, ctx, want):
    assert p._overrules_scope_verdict(q, ctx) is want
