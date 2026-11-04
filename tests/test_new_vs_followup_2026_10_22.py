"""D-061 (user addendum 2026-10-22, "Context Memory: New Question = New Answer").

After "MGNREGA person-days in East Khasi Hills in 2022-23", the user asked "Which
district has the highest beneficiaries in MGNREGA?" and was answered inside East
Khasi Hills and FY 2022-23. Two rules caused it: naming the chat's own scheme read
as a follow-up (is_scopeless_followup), and a new question inherited the chat's
place and year (D-056, _same_scheme_context_year). The rule now: the question
wins; memory only fills the gaps a question leaves on purpose.

    standalone  own scheme + own measure, no reference cue -> inherits NOTHING;
                year from the question, else ASKED with the year chips
                (D-065; was the scheme's latest FY), banner "(new question)"
    follow-up   a reference cue or a fragment -> inherits only what it leaves out;
                the level it asks about ("which block") and below are cleared
    vague       a measure with no scheme named -> one topic: that topic;
                two or more: chips, never a default scheme

OFFLINE: every test calls the real function (context_policy.turn_kind, the
follow-up stage through the graph, the c13 year gate). The live counterpart is
tests/conversation_harness/scenarios/new_vs_followup_2026_10_22.yaml.
    .venv/Scripts/python.exe -m pytest tests/test_new_vs_followup_2026_10_22.py -q
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_policy as cp  # noqa: E402
from app import entity_resolver, llm, pipeline as p  # noqa: E402
from app.session_store import ConversationState, Session, Turn  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402


# The new-chat district / year asks these tests cover are the rollback path since the user's
# 2026-10-29 decision (D-089, NEW_CHAT_ASKS_SCOPE=false answers statewide / all years instead;
# tests/test_rag_fix_report_2026_10_29.py). They still guard that path with the switch on.
@pytest.fixture(autouse=True)
def _new_chat_asks_scope(monkeypatch):
    from app.config import settings as _s
    monkeypatch.setattr(_s, "NEW_CHAT_ASKS_SCOPE", True)

T1 = "MGNREGA person-days in East Khasi Hills in 2022-23"
PREV = Turn(question=T1, raw_question=T1, route="data", schemes=["MGNREGA"],
            resolved_entities={"district": "EAST KHASI HILLS", "year_key": 2022})


@pytest.fixture(scope="module", autouse=True)
def _catalogues():
    entity_resolver.load_all()


def _run(coro):
    return asyncio.run(coro)


# ── §5 of the addendum, row by row: the verdict ─────────────────────────────
STANDALONE = [
    "Which district has the highest beneficiaries in MGNREGA?",
    "How many person-days in MGNREGA in 2022-23?",
    "Top 5 villages by job cards in MGNREGA, 2024-25",
    "Total PMAY-G houses completed in 2023-24",
    "Which has more beneficiaries, MGNREGA or PMAY-G, in 2023-24?",
    "MGNREGA ka 2024-25 wala district-wise data batao",
    # beyond the table: the same rule in other words
    "how many households for PMAY-G",
    "What is the total beneficiaries MGNREGA?",
    "How many MGNREGA beneficiaries?",
    "How many beneficiaries are there in MGNREGA?",          # "are there" is not "there"
    "MGNREGA households that completed 100 days in 2023-24",  # relative "that"
    "PMAY-G houses sanctioned in Ri Bhoi this year?",         # "this year" is the calendar's
    "Compare MGNREGA and PMAY-G beneficiaries in 2023-24",    # both sides named
    "show district-wise person-days for MGNREGA",
    "top 3 blocks by person-days in MGNREGA",
    "Which block has the highest person-days in MGNREGA?",
    "person-days in 2023-24",                                 # scheme from the measure + own year
    "how many job cards in Ri Bhoi",                          # scheme from the measure + own place
    "CM Elevate applications by district",
    "total expenditure under MGNREGA in West Garo Hills",
    "PMAY-G houses completed in East Garo Hills in 2021-22",
]
FOLLOWUP = [
    "What about 2023-24?",
    "And West Garo Hills?",
    "Which block is highest?",
    "Show it statewide",
    "Mawphlang?",
    "Compare this with PMAY-G",
    "Compare it with last year",
    "2023-24?",
    "give me for pmay",
    "compare with pmay",
    "How many job cards there?",
    "what is the total for that district?",
    "MGNREGA in West Garo Hills",       # names no measure: the measure is inherited
    "for PMAY-G",
    "same for focus plus",
    "also show PMAY-G",
    "how much expenditure in this scheme?",
    "what about women?",
    "and in Dalu block",
    "same for 2021-22",
    "show the same by block",
]
VAGUE = [
    "How many beneficiaries?",
    "how many households",
    "how many job cards",                       # scheme from the measure, but no scope of its own
    "Which block has highest number of households?",
    "Which block has highest person-days?",
    "what is the total expenditure",
]


@pytest.mark.parametrize("q", STANDALONE)
def test_self_sufficient_questions_are_standalone(q):
    assert cp.turn_kind(q).kind == cp.TURN_STANDALONE, cp.turn_kind(q)


@pytest.mark.parametrize("q", FOLLOWUP)
def test_reference_cues_and_fragments_are_followups(q):
    assert cp.turn_kind(q).kind == cp.TURN_FOLLOWUP, cp.turn_kind(q)


@pytest.mark.parametrize("q", VAGUE)
def test_a_measure_without_a_named_scheme_is_vague(q):
    assert cp.turn_kind(q).kind == cp.TURN_VAGUE, cp.turn_kind(q)


def test_the_verdict_never_reads_the_chat():
    # the same words get the same verdict whatever the chat is on (stranger test)
    assert cp.turn_kind("How many person-days in MGNREGA in 2022-23?") == \
        cp.turn_kind("How many person-days in MGNREGA in 2022-23?")


# ── asked dimension (slot-conflict guard) ────────────────────────────────────
@pytest.mark.parametrize("q,asked", [
    ("Which district has the highest beneficiaries in MGNREGA?", ("district",)),
    ("Which block is highest?", ("block",)),
    ("Top 5 villages by job cards in MGNREGA, 2024-25", ("village",)),
    ("MGNREGA ka 2024-25 wala district-wise data batao", ("district",)),
    ("in which district were most houses completed", ("district",)),
    ("person-days by block", ("block",)),
    ("each village's job cards", ("village",)),
    ("How many person-days in MGNREGA in 2022-23?", ()),
    ("And West Garo Hills?", ()),
])
def test_asked_levels(q, asked):
    assert cp.asked_levels(q) == asked


# ── what the data path inherits (D-056 narrowed) ─────────────────────────────
ST = ConversationState(scheme="MGNREGA", district="EAST KHASI HILLS", block="MAWPHLANG", year=2022)


@pytest.mark.parametrize("q", STANDALONE)
def test_a_standalone_question_inherits_nothing(q):
    assert p._same_scheme_context_year(q, q, ST) is None


def test_a_vague_question_inherits_the_one_topic_but_not_the_asked_level():
    assert p._same_scheme_context_year("how many households", "how many households", ST) == \
        {"year_key": 2022, "district": "EAST KHASI HILLS", "block": "MAWPHLANG"}
    assert p._same_scheme_context_year("Which block has highest number of households?",
                                       "Which block has highest number of households?", ST) == \
        {"year_key": 2022, "district": "EAST KHASI HILLS"}
    assert p._same_scheme_context_year("which district has the most households",
                                       "which district has the most households", ST) == {"year_key": 2022}


def test_naming_the_same_scheme_is_not_a_scopeless_followup():
    assert not p.is_scopeless_followup("Which district has the highest beneficiaries in MGNREGA?", PREV)
    assert not p.is_scopeless_followup("What is the total beneficiaries MGNREGA?", PREV)
    assert p.is_scopeless_followup("How many beneficiaries were there?", PREV)


# ── through the graph: the follow-up stage ──────────────────────────────────
def _session(state=ST, prev=PREV, topics=None):
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.turns = [prev]
    s.state = state
    if topics is not None:
        s.topics = topics
    return s


def _drive(monkeypatch, question, session):
    seen = {"rewrites": 0}

    async def classifier(prompt, **_kw):
        if "Standalone question:" in prompt:
            seen["rewrites"] += 1
            return "How many MGNREGA beneficiaries in East Khasi Hills in FY 2022-23?"
        return '{"intent": "DATA"}'

    async def fake_answer_data(question, **kw):
        seen["q"], seen["prior"] = question, kw.get("prior_resolved")
        return {"route": "data", "intent": "DATA", "answer": "ok", "schemes": ["MGNREGA"],
                "sql": "S", "rows": [], "data": [], "resolved_entities": {}}

    monkeypatch.setattr(llm, "call_classifier", classifier)
    monkeypatch.setattr(llm, "call_rewriter", classifier)
    stub_data_path(monkeypatch, fake_answer_data)
    seen["result"] = _run(graph_turn(question, session=session))
    seen["turn_kind"] = session.turn_context.get("turn_kind")
    seen["new_question"] = session.turn_context.get("new_question")
    return seen


def test_the_reported_question_is_not_rewritten_and_inherits_nothing(monkeypatch):
    q = "Which district has the highest beneficiaries in MGNREGA?"
    seen = _drive(monkeypatch, q, _session())
    assert seen["rewrites"] == 0
    assert seen["q"] == q
    assert not seen["prior"]
    assert seen["turn_kind"] == cp.TURN_STANDALONE and seen["new_question"] is True


def test_a_followup_still_inherits(monkeypatch):
    seen = _drive(monkeypatch, "What about 2023-24?", _session())
    assert seen["turn_kind"] == cp.TURN_FOLLOWUP
    assert (seen["prior"] or {}).get("district") == "EAST KHASI HILLS"


def _two_topics():
    return {"active": "PMAY-G", "order": ["MGNREGA", "PMAY-G"], "ack": None, "items": {
        "MGNREGA": {"schemes": ["MGNREGA"], "state": ST.to_dict(), "last_turn": None, "questions": [],
                    "turns": 1, "summary": "MGNREGA"},
        "PMAY-G": {"schemes": ["PMAY-G"], "state": ConversationState(scheme="PMAY-G", year=2023).to_dict(),
                   "last_turn": None, "questions": [], "turns": 1, "summary": "PMAY-G"}}}


def test_vague_with_two_topics_asks_with_one_chip_per_topic():
    # D-098 (BLH UAT 2026-11-02, item 10): the ACTIVE topic answers a vague question;
    # the picker is for a chat whose active topic is no single scheme (a comparison).
    topics = _two_topics()
    topics["active"] = "MGNREGA + PMAY-G"
    s = _session(topics=topics)
    e = p._vague_topic_clarification("How many beneficiaries?", s)
    assert e is not None and e.rule == "topic-ambiguous"
    assert [o["label"] for o in e.options] == ["PMAY-G", "MGNREGA"]
    assert e.options[0]["question"] == "Go back to PMAY-G: How many beneficiaries?"


def test_vague_with_two_topics_runs_in_the_active_one():
    # D-098: active PMAY-G (the answer just given) — no picker, the question runs there
    assert p._vague_topic_clarification("How many beneficiaries?", _session(topics=_two_topics())) is None


def test_vague_with_one_topic_or_a_pinned_scheme_is_not_asked():
    one = _two_topics()
    one["order"], one["items"] = ["MGNREGA"], {"MGNREGA": one["items"]["MGNREGA"]}
    assert p._vague_topic_clarification("How many beneficiaries?", _session(topics=one)) is None
    # "job cards" is MGNREGA's alone: no question to ask
    assert p._vague_topic_clarification("how many job cards", _session(topics=_two_topics())) is None


# ── the year a standalone question gets (c13) ───────────────────────────────
@pytest.fixture
def _defaults_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ANSWER_DEFAULTS_ENABLED", True)
    monkeypatch.setattr(settings, "YEAR_CLARIFY_ENABLED", True)
    monkeypatch.setattr(settings, "SCOPE_CLARIFY_ENABLED", True)


def _data_turn(question, *, kind, chat_has_scope=True):
    d = p._new_data_turn(question)
    d["schemes"] = ["MGNREGA"]
    d["chat_has_scope"] = chat_has_scope
    d["turn_kind"] = kind
    d["entity_result"] = {"resolved": {}, "display": {}, "question": None}
    return d


def test_a_standalone_question_without_a_year_asks_the_year(_defaults_on):
    # D-065 (user, 2026-10-22): no silent latest FY — "why are you blindly giving 2025-26?"
    d = _data_turn("Which district has the highest beneficiaries in MGNREGA?", kind=cp.TURN_STANDALONE)
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(p._data_clarification_stage(d, None))
    assert exc.value.rule == "year-not-specified"
    assert "resolved" not in d["entity_result"] or not d["entity_result"]["resolved"].get("year_key")


def test_a_new_chat_still_asks_the_year(_defaults_on):
    d = _data_turn("Which district has the highest beneficiaries in MGNREGA?", kind=None, chat_has_scope=False)
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(p._data_clarification_stage(d, None))
    assert exc.value.rule == "year-not-specified"


def test_a_standalone_question_naming_its_year_keeps_it(_defaults_on):
    d = _data_turn("How many person-days in MGNREGA in 2022-23?", kind=cp.TURN_STANDALONE)
    d["entity_result"]["resolved"]["year_key"] = 2022
    _run(p._data_clarification_stage(d, None))
    assert d["entity_result"]["resolved"]["year_key"] == 2022


# ── the banner shows a wrong choice at once ─────────────────────────────────
def test_banner_marks_a_new_question():
    s = _session()
    s.turn_context = {"new_question": True}
    r = {"route": "data", "schemes": ["MGNREGA"], "sql": "S", "resolved_entities": {"year_key": 2025}}
    p._attach_scope_banner(r, s)
    assert r["scope_banner"] == "MGNREGA · All of Meghalaya · FY 2025-26 (new question)"
    s.turn_context = {"new_question": True, "restored_question": "x"}
    p._attach_scope_banner(r, s)
    assert r["scope_banner"].endswith("(from earlier)")


# ── Hinglish is normalised first (addendum §5) ──────────────────────────────
def test_hinglish_wala_is_not_a_name_in_the_rephrase_check():
    # Live 2026-10-22 (harness NQ06): the right rephrase was rejected as having
    # dropped a NAME "wala", so the raw Hinglish failed SQL and went to the documents.
    assert p._rephrase_violation("MGNREGA ka 2024-25 wala district-wise data batao",
                                 "Provide district-wise MGNREGA data for FY 2024-25.") is None


# ── D-065: a resumed pause keeps the kind of the question the user typed ─────
# User report 2026-10-22: after "How many CM Elevate Legacy records … across all
# financial years?" (all years), "What is the total disbursement amount for
# mairang?" (no scheme: vague, one topic -> the chat's scope) paused for the place
# level, then for whole-or-part of the constituency. The chip text "… for mairang
# under CM Elevate Legacy, the assembly constituency, …, the whole constituency"
# names a scheme and a measure, was read as a NEW question and answered for
# "FY 2025-26 (new question)" instead of the chat's all years.
CML_Q1 = "How many CM Elevate Legacy records are there in Meghalaya across all financial years?"
CML_PREV = Turn(question=CML_Q1, raw_question=CML_Q1, route="data", schemes=["CM Elevate Legacy"],
                resolved_entities={"year_all": True})
CML_ST = ConversationState(scheme="CM Elevate Legacy", year_all=True)
MAIRANG_PAUSED = ("What is the total disbursement amount for mairang under CM Elevate Legacy, "
                  "the assembly constituency, not another area type")
MAIRANG_CHIP = MAIRANG_PAUSED + ", the whole constituency"


def test_the_chip_text_alone_reads_as_a_new_question():
    # Why the kind has to travel with the pause: the words alone say standalone.
    assert cp.turn_kind(MAIRANG_CHIP).kind == cp.TURN_STANDALONE
    assert cp.turn_kind("What is the total disbursement amount for mairang?").kind == cp.TURN_VAGUE


def test_the_turns_own_kind_decides_what_it_inherits():
    assert p._same_scheme_context_year(MAIRANG_CHIP, MAIRANG_CHIP, CML_ST) is None
    assert p._same_scheme_context_year(MAIRANG_CHIP, MAIRANG_CHIP, CML_ST,
                                       kind=cp.TURN_VAGUE) == {"year_all": True}
    assert p._same_scheme_context_year(MAIRANG_CHIP, MAIRANG_CHIP, CML_ST, kind=cp.TURN_STANDALONE) is None


def test_a_pause_remembers_the_typed_kind_and_survives_the_snapshot():
    from app.routers.query import remember_pause
    s = _session(state=CML_ST, prev=CML_PREV)
    s.turn_context = {"turn_kind": cp.TURN_VAGUE}
    remember_pause(s, MAIRANG_PAUSED, p.ClarificationNeeded(
        "whole or part?", options=[{"label": "The whole MAIRANG constituency", "question": MAIRANG_CHIP}],
        rule="ac-narrow-scope"))
    assert s.pending_turn_kind == cp.TURN_VAGUE
    s2 = _session(state=ConversationState(), prev=CML_PREV)
    s2.apply_snapshot(s.to_snapshot())
    assert s2.pending_scope_q == MAIRANG_PAUSED and s2.pending_turn_kind == cp.TURN_VAGUE


def _paused_session(kind):
    s = _session(state=CML_ST, prev=CML_PREV)
    s.pending_scope_q = MAIRANG_PAUSED
    s.pending_scope_rule = "ac-narrow-scope"
    s.pending_scope_options = [{"label": "The whole MAIRANG constituency", "question": MAIRANG_CHIP},
                               {"label": "Mairang block", "question": MAIRANG_PAUSED + ", Mairang block"}]
    s.pending_turn_kind = kind
    return s


def test_the_reported_chip_keeps_the_chats_year(monkeypatch):
    s = _paused_session(cp.TURN_VAGUE)
    seen = _drive(monkeypatch, MAIRANG_CHIP, s)
    assert seen["turn_kind"] == cp.TURN_VAGUE
    assert seen["new_question"] is False
    assert (seen["prior"] or {}).get("year_all") is True
    assert s.pending_turn_kind is None and s.pending_scope_q is None


def test_a_chip_of_a_new_question_stays_a_new_question(monkeypatch):
    # The paused question named its own scheme and measure: still new, nothing inherited.
    seen = _drive(monkeypatch, MAIRANG_CHIP, _paused_session(cp.TURN_STANDALONE))
    assert seen["turn_kind"] == cp.TURN_STANDALONE and seen["new_question"] is True
    assert not seen["prior"]


def test_a_resumed_year_pause_keeps_the_cm_elevate_legacy_pin(monkeypatch):
    # Harness AC04c (2026-10-22): on an applications thread, "How many applications
    # have been sanctioned under CM-ELEVATE?" (sanction words -> Legacy, D-064) asked
    # its year (D-065); "all of them combined" resumed the remembered UNPINNED text
    # and answered "8,840 sanctioned" from the applications data (true 2,820).
    apps_q = "How many CM Elevate (applications) applications are there in Ri Bhoi"
    prev = Turn(question=apps_q, raw_question="applications", route="data", schemes=["CM Elevate"],
                resolved_entities={"district": "RI BHOI"})
    s = _session(state=ConversationState(scheme="CM Elevate", district="RI BHOI"), prev=prev)
    s.pending_scope_q = "How many applications have been sanctioned under CM-ELEVATE?"
    s.pending_scope_rule = "year-not-specified"
    s.pending_turn_kind = cp.TURN_STANDALONE
    # user decision 2026-11-03: the applications chat is not switched to Legacy unasked —
    # it asks to switch, and never answers the sanction question from the applications data
    with pytest.raises(p.ClarificationNeeded) as ask:
        _drive(monkeypatch, "all of them combined", s)
    assert ask.value.rule == "cm-elevate-dataset"
    assert [o["label"] for o in ask.value.options] == ["CM Elevate Legacy (switch)", "CM Elevate (stay)"]
    assert "across all financial years" in ask.value.options[0]["question"]
