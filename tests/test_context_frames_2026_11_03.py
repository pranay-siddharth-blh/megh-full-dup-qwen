"""
D-100 — conversation frames and the window resolver (app/context_frames.py).

The user's chat of 2026-11-03, replayed: Focus Plus total -> "Give a district-wise
breakup" -> "compare this with spend on Focus scheme" (which-Focus pause) -> "compare
this with spend on Focus Legacy scheme" (lost the district breakdown) -> "include focus
plus also" (went to the documents) -> "i mean compare focus plus also" (lost Focus Legacy:
its rewrite was rejected because the turn before was the documents answer). Every test
calls the real function; only the model call is stubbed (canned JSON replies).
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import context_frames as cf  # noqa: E402
from app import conversation_layer, llm  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import Session  # noqa: E402

T1_Q = "What is the total benefit amount disbursed under Focus Plus till date?"
T2_Q = "What is the district-wise breakup of the total benefit amount disbursed under Focus Plus till date?"
T3_Q = ("What is the district-wise breakup of the total benefit amount disbursed under Focus Plus and "
        "Focus Legacy schemes till date?")
COMPARE_LEGACY = "compare this with spend on Focus Legacy scheme"


@pytest.fixture(autouse=True)
def _frames_on(monkeypatch):
    # conftest switches the resolver off for the other suites; this file tests it.
    monkeypatch.setattr(settings, "CONTEXT_FRAMES_ENABLED", True)


def _session() -> Session:
    return Session(session_id="frames-test", user_id=None, created=0.0, last_seen=0.0)


def _answered(s: Session, q: str, schemes: list, route: str = "data") -> None:
    cf.record(s, q, {"route": route, "rewritten_question": q, "schemes": schemes, "resolved_entities": {}})


def _chat_to_t2() -> Session:
    s = _session()
    _answered(s, T1_Q, ["Focus Plus"])
    _answered(s, T2_Q, ["Focus Plus"])
    return s


class _Model:
    """Stands in for llm.call_rewriter: records each prompt, returns a canned reply."""
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.prompts, self.kwargs = reply, exc, [], []

    async def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        self.kwargs.append(kw)
        if self.exc:
            raise self.exc
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


def _resolve(monkeypatch, s, message, reply=None, exc=None):
    model = _Model(reply, exc)
    monkeypatch.setattr(llm, "call_rewriter", model)
    return asyncio.run(cf.resolve(s, message)), model


# ── Frames: one per answered turn, the whole window in the snapshot ──────────
def test_record_keeps_the_breakdown_level_and_skips_unanswered_turns():
    s = _chat_to_t2()
    cf.record(s, "hello", {"route": "edge", "answer": "Hi"})
    cf.record(s, "compare this with spend on Focus scheme", {"route": "data", "needs_clarification": True})
    assert [f["id"] for f in s.frames] == [1, 2]
    assert s.frames[0]["by"] == [] and s.frames[1]["by"] == ["district"]
    assert s.frames[1]["schemes"] == ["Focus Plus"] and s.frames[1]["route"] == "data"


def test_record_is_capped_at_the_session_window(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_MAX_TURNS", 3)
    s = _session()
    for _ in range(5):
        _answered(s, T1_Q, ["Focus Plus"])
    assert [f["id"] for f in s.frames] == [3, 4, 5]


def test_every_frame_survives_the_snapshot_so_any_worker_sees_the_whole_chat():
    s = _chat_to_t2()
    _answered(s, "What is Focus Plus?", ["Focus Plus"], route="knowledge")
    other_worker = _session()
    other_worker.apply_snapshot(json.loads(json.dumps(s.to_snapshot())))
    assert other_worker.frames == s.frames and len(other_worker.frames) == 3
    # a snapshot written before D-100 still loads
    old = s.to_snapshot()
    old["_session"].pop("frames")
    other_worker.apply_snapshot(old)
    assert other_worker.frames == []


def test_a_context_reset_forgets_the_frames():
    s = _chat_to_t2()
    conversation_layer.clear_context(s)
    assert s.frames == []


# ── The deterministic checks on a written question ───────────────────────────
def _base(q=T2_Q, schemes=("Focus Plus",)):
    return {"id": 2, "q": q, "route": "data", "schemes": list(schemes),
            "by": list(cf.context_policy.asked_levels(q)), "place": {}, "years": []}


def test_check_accepts_the_comparison_that_keeps_the_breakdown():
    assert cf.check(T3_Q, COMPARE_LEGACY, _base()) is None


def test_check_rejects_a_comparison_that_lost_the_district_breakdown():
    q = "What is the total benefit amount disbursed under Focus Plus and Focus Legacy till date?"
    assert cf.check(q, COMPARE_LEGACY, _base()) == "lost-breakdown"


def test_check_rejects_a_comparison_that_swapped_the_scheme_instead_of_adding_it():
    q = "What is the district-wise breakup of the total benefit amount disbursed under Focus Legacy till date?"
    assert cf.check(q, COMPARE_LEGACY, _base()) == "lost-scheme"


def test_check_rejects_a_scheme_nobody_named():
    q = "What is the district-wise breakup of the total amount spent under Focus Plus and MGNREGA till date?"
    assert cf.check(q, "include that also", _base()) == "scheme-not-permitted"


def test_check_rejects_a_dropped_scheme_when_the_message_names_none():
    q = "What is the district-wise breakup of the total benefit amount disbursed under Focus Plus till date?"
    assert cf.check(q, "show it as a chart", _base(T3_Q, ("Focus Plus", "Focus Legacy"))) == "lost-scheme"


def test_check_rejects_a_question_that_still_leans_on_the_chat():
    q = "What is the district-wise breakup of this benefit amount disbursed under Focus Plus and Focus Legacy till date?"
    assert cf.check(q, COMPARE_LEGACY, _base()) == "not-standalone"


def test_check_never_lets_a_bare_focus_through():
    assert cf.check("What is the district-wise total amount disbursed under Focus till date?",
                    "and by district", _base()) in ("bare-focus", "no-scheme")


# ── resolve(): the user's chat, turn by turn ─────────────────────────────────
def test_turn4_compare_with_legacy_continues_the_district_breakup(monkeypatch):
    s = _chat_to_t2()
    out, model = _resolve(monkeypatch, s, COMPARE_LEGACY, {"relation": "followup", "question": T3_Q})
    assert out == T3_Q
    assert "The figure the conversation is on now: T2." in model.prompts[0]
    assert T1_Q in model.prompts[0] and T2_Q in model.prompts[0]          # the whole window
    assert model.kwargs[0]["guided"]["guided_json"] == cf._SCHEMA


def test_turn5_include_also_continues_the_comparison(monkeypatch):
    s = _chat_to_t2()
    _answered(s, T3_Q, ["Focus Plus", "Focus Legacy"])
    out, model = _resolve(monkeypatch, s, "include focus plus also", {"relation": "followup", "question": T3_Q})
    assert out == T3_Q and "now: T3." in model.prompts[0]


def test_turn6_a_documents_aside_does_not_become_the_antecedent(monkeypatch):
    s = _chat_to_t2()
    _answered(s, T3_Q, ["Focus Plus", "Focus Legacy"])
    _answered(s, "Please include Focus Plus as well.", ["Focus Plus"], route="knowledge")
    out, model = _resolve(monkeypatch, s, "i mean compare focus plus also",
                          {"relation": "followup", "question": T3_Q})
    assert out == T3_Q and "now: T3." in model.prompts[0]


def test_a_failed_check_falls_back_to_the_existing_path(monkeypatch):
    lost = "What is the total benefit amount disbursed under Focus Plus and Focus Legacy till date?"
    out, _ = _resolve(monkeypatch, _chat_to_t2(), COMPARE_LEGACY, {"relation": "followup", "question": lost})
    assert out is None


# ── resolve(): what it leaves to the existing rules (no model call) ──────────
def test_a_self_sufficient_new_question_is_never_resolved(monkeypatch):
    out, model = _resolve(monkeypatch, _chat_to_t2(), "How many MGNREGA job cards were issued in 2023-24?")
    assert out is None and model.prompts == []


def test_a_bare_focus_still_gets_the_which_focus_question(monkeypatch):
    out, model = _resolve(monkeypatch, _chat_to_t2(), "compare this with spend on Focus scheme")
    assert out is None and model.prompts == []


def test_no_answered_figure_yet_means_nothing_to_continue(monkeypatch):
    s = _session()
    _answered(s, "What is Focus Plus?", ["Focus Plus"], route="knowledge")
    out, model = _resolve(monkeypatch, s, "and by district?")
    assert out is None and model.prompts == []


def test_a_reply_the_open_pause_understands_is_left_to_the_pause(monkeypatch):
    s = _chat_to_t2()
    paused = "compare this with spend on Focus scheme"
    s.pending_scope_q = paused
    s.pending_scope_rule = "focus-scheme-ambiguous"
    s.pending_scope_options = p._focus_ambiguity_clarification(paused).options
    out, model = _resolve(monkeypatch, s, "Focus Legacy")
    assert out is None and model.prompts == []


def test_an_aside_about_another_scheme_is_left_to_the_existing_rules(monkeypatch):
    s = _chat_to_t2()
    _answered(s, "What is PMAY-G?", ["PMAY-G"], route="knowledge")
    out, model = _resolve(monkeypatch, s, "and by block?")
    assert out is None and model.prompts == []


def test_model_failures_fall_back(monkeypatch):
    for kw in ({"exc": RuntimeError("gateway down")}, {"reply": "not json"},
               {"reply": {"relation": "new", "question": ""}}):
        out, model = _resolve(monkeypatch, _chat_to_t2(), COMPARE_LEGACY, **kw)
        assert out is None and len(model.prompts) == 1, kw


def test_switched_off_it_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_FRAMES_ENABLED", False)
    s = _session()
    _answered(s, T1_Q, ["Focus Plus"])
    assert s.frames == []
    out, model = _resolve(monkeypatch, _chat_to_t2(), COMPARE_LEGACY)
    assert out is None and model.prompts == []


# ── The conversation layer hands the resolved question on ───────────────────
def test_layer_leaves_everything_but_a_comparison_to_the_pipeline(monkeypatch):
    # The precise rules (place swap, scheme swap, figure reference, ...) run in c14
    # first; the frames only stand in where the comparison or the rewrite gives up.
    s = _chat_to_t2()
    s.state.scheme = "Focus Plus"
    model = _Model({"relation": "followup", "question": T3_Q})
    monkeypatch.setattr(llm, "call_rewriter", model)
    lt = asyncio.run(conversation_layer.prepare_turn(s, "include focus plus also"))
    assert lt.action != "compare" and lt.question == "include focus plus also" and model.prompts == []


def test_layer_runs_the_resolved_question_and_abandons_an_unanswered_pause(monkeypatch):
    s = _chat_to_t2()
    s.state.scheme = "Focus Plus"
    paused = "compare this with spend on Focus scheme"
    s.pending_scope_q = paused
    s.pending_scope_rule = "focus-scheme-ambiguous"
    s.pending_scope_options = p._focus_ambiguity_clarification(paused).options
    dropped = []

    async def _drop(sid):
        dropped.append(sid)
    monkeypatch.setattr(conversation_layer, "_drop_paused_run", _drop)
    monkeypatch.setattr(llm, "call_rewriter", _Model({"relation": "followup", "question": T3_Q}))
    lt = asyncio.run(conversation_layer.prepare_turn(s, COMPARE_LEGACY))
    assert (lt.question, lt.action, lt.changed) == (T3_Q, "compare", True)
    assert s.turn_context.get("frame_resolved") is True
    assert s.pending_scope_q is None and dropped == ["frames-test"]
