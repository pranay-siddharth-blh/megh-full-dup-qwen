"""
The test team's context-memory report (2026-10-29, "Megh One AI — Context Memory
Test Report", 7/10). Each bug's cause, found in the code, and its fix:

  Bug 1  a knowledge aside wiped the data context. The measure-after-knowledge
         rewrite appended only the scheme ("how many person-days under MGNREGA?"),
         which names its scheme, so it ran as a NEW question: asked the year,
         answered statewide, "(new question)". Now the chat's data scope of that
         scheme comes along (_c01_kmeasure_question), and a question that keeps
         the chat's own scope is not labelled new (_c14_keeps_chat_scope).
  Bug 2  "and sanctioned?" after a knowledge aside was rewritten against the aside:
         "sanctioned" is a measure the chat knows (detect_metric) but no measure
         FAMILY, so _is_measure_only refused it.
  Bug 3  after "compare it with Ri Bhoi", "what about expenditure?" was statewide:
         resolve_entities carried a single district / block but not district_list.
  Bug 4  "person-days in Tikrikilla block?" after West Garo Hills by block is a
         NEW question (D-061) and kept the year only on an exact measure match
         (D-075); a block of the chat's own district now keeps the year too.
  Bug 5  "how many are on hold?" with CM Elevate, MGNREGA and PMAY-G topics open
         asked which topic: the which-topic step did not use CM Elevate's
         applications-only vocabulary (_cme_open_topic_pin).
  Typo   "toatal persendays" carried no continuation signal read raw; the
         continuation check now also reads the rephraser's typo gloss, accepted
         only when it yields a measure.

Real functions; whole turns through the real conversation layer and graph with
the data path, the KB and the models stubbed. No DB, gateway or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_test_team_report_2026_10_29.py -q
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, context_budget, context_policy as cp, conversation_layer as cl  # noqa: E402
from app import entity_resolver, llm, rag  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import ConversationState, Session  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402

EKH, WGH, RIB = "EAST KHASI HILLS", "WEST GARO HILLS", "RI BHOI"


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


# ── A whole chat: conversation layer -> graph -> router bookkeeping ─────────

@pytest.fixture
def chat(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED", "CONVERSATION_LAYER_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    seen, decisions = [], []
    answer = {}

    async def data(question, scope=None, **kw):
        seen.append((question, dict(kw.get("prior_resolved") or {})))
        return {"route": "data", "intent": "DATA", "schemes": [answer["scheme"]], "sql": "SELECT 1",
                "resolved_entities": dict(answer["entities"]), "rows": [{"n": 1}], "data": [{"n": 1}],
                "row_count": 1, "answer": "answer.", "confidence": "high"}
    stub_data_path(monkeypatch, data)

    async def kb(question, scheme=None, retrieval_query=None):
        return {"answer": f"About {scheme}.", "confidence": "high", "sources": [], "citations": []}

    async def kb_multi(question, schemes=None):
        return await kb(question, (schemes or [None])[0])

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")

    async def classifier(prompt, **k):
        # the model's routing, as live: "what is …" / "who is eligible" read as KNOWLEDGE
        if '"intent"' in prompt:
            q = prompt.rsplit('Question: "', 1)[-1].lower()
            return '{"intent": "KNOWLEDGE"}' if ("what is" in q or "who is eligible" in q) else '{"intent": "DATA"}'
        raise RuntimeError("no model offline")
    monkeypatch.setattr(rag, "answer_from_kb", kb)
    monkeypatch.setattr(rag, "answer_from_kb_multi", kb_multi)
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    monkeypatch.setattr(llm, "call_classifier", classifier)
    orig = context_budget.log_decision

    def spy(stage, **f):
        decisions.append((stage, f))
        return orig(stage, **f)
    monkeypatch.setattr(context_budget, "log_decision", spy)
    s = Session(session_id=f"report-{time.time()}", user_id="u", created=time.time(), last_seen=time.time())

    def ask(q, scheme=None, entities=None):
        if scheme:
            answer.update(scheme=scheme, entities=entities or {})
        decisions.clear()
        n = len(seen)

        async def turn():
            layer = await cl.prepare_turn(s, q)
            out = layer.response if layer.response is not None else await graph_turn(layer.question, session=s)
            s.turns.append(build_turn(layer.question, out))
            return out
        out = asyncio.run(turn())
        return out, (seen[-1] if len(seen) > n else None)
    ask.session, ask.decisions = s, decisions
    return ask


def test_bug1_a_knowledge_aside_keeps_the_data_context(chat):
    chat("How many job cards in East Khasi Hills in 2024-25?", "MGNREGA", {"district": EKH, "year_key": 2024})
    out, _ = chat("what is a job card in MGNREGA?")
    assert out["route"] == "knowledge"
    out, (question, _prior) = chat("how many person-days?", "MGNREGA", {"district": EKH, "year_key": 2024})
    assert "East Khasi Hills" in question and "2024-25" in question          # the chat's scope, no year pause
    assert out["scope_banner"] == "MGNREGA · East Khasi Hills district · FY 2024-25"  # and not "(new question)"; place type: H-6


def test_bug2_a_measure_after_a_knowledge_aside_is_data(chat):
    chat("How many PMAY-G houses were completed in East Khasi Hills in 2023-24?", "PMAY-G",
         {"district": EKH, "year_key": 2023})
    out, _ = chat("what is PMAY-G and who is eligible?")
    assert out["route"] == "knowledge"
    out, (question, prior) = chat("and sanctioned?", "PMAY-G", {"district": EKH, "year_key": 2023})
    assert out["route"] == "data"
    assert "sanctioned" in question and prior.get("district") == EKH and prior.get("year_key") == 2023


def test_typo_measure_continues_the_chat(chat):
    chat("MGNREGA person-days in Ri Bhoi in 2023-24", "MGNREGA", {"district": RIB, "year_key": 2023})
    out, (question, prior) = chat("toatal persendays", "MGNREGA", {"district": RIB, "year_key": 2023})
    assert out["route"] == "data" and prior.get("district") == RIB and prior.get("year_key") == 2023
    assert not any(st == "continuation" and f.get("continues") is False for st, f in chat.decisions)


def test_an_unrelated_message_still_does_not_continue(chat):
    chat("MGNREGA person-days in Ri Bhoi in 2023-24", "MGNREGA", {"district": RIB, "year_key": 2023})
    chat("he is my collik remember")       # 2026-09-29: must not continue the scheme conversation
    assert any(st == "continuation" and f.get("continues") is False for st, f in chat.decisions)


# ── The functions behind each fix ───────────────────────────────────────────

def _prev_knowledge(scheme):
    from app.session_store import Turn
    return Turn(question="what is it?", raw_question="what is it?", route="knowledge", schemes=[scheme])


def test_kmeasure_question_keeps_the_chats_scope_only_on_the_same_scheme():
    st = ConversationState(scheme="MGNREGA", district=EKH, year=2024)
    prev = _prev_knowledge("MGNREGA")
    assert p._c01_kmeasure_question("how many person-days?", prev, st) == \
        "how many person-days under MGNREGA in East Khasi Hills in FY 2024-25?"
    # its own year is kept, not doubled
    assert p._c01_kmeasure_question("how many person-days in 2022-23?", prev, st) == \
        "how many person-days in 2022-23 under MGNREGA in East Khasi Hills?"
    # a chat on another scheme (or none): the scheme alone, as before
    assert p._c01_kmeasure_question("how many houses?", _prev_knowledge("PMAY-G"), st) == \
        "how many houses under PMAY-G?"
    assert p._c01_kmeasure_question("how many person-days?", prev, None) == "how many person-days under MGNREGA?"


def test_is_measure_only_reads_the_chats_measure_vocabulary():
    assert p._is_measure_only("and sanctioned?")
    assert not p._is_measure_only("and who is eligible for a sanction?")
    assert not p._is_measure_only("what about Ri Bhoi?")


def test_bug3_a_comparisons_districts_are_carried(monkeypatch):
    # the extractor as the model reads these questions; no village in the DB
    # (the stubs of tests/test_bare_place_names_2026_10_21.py _stub_resolver)
    async def mentions(text):
        d = [n for n, dim in entity_resolver.place_mentions(text).items() if dim == "district"]
        return {"district": d[0]} if d else {}

    async def no_village(*a, **k):
        return entity_resolver.Resolved("not_found", "village", str(a[0]) if a else "")

    async def none(*a, **k):
        return None

    async def no_contents(*a, **k):
        return {"districts": [], "blocks": [], "villages": 0}

    async def empty(*a, **k):
        return {}
    monkeypatch.setattr(p, "extract_entity_mentions", mentions)
    monkeypatch.setattr(p, "resolve_village", no_village)
    monkeypatch.setattr(p, "_scan_village_in_question", none)
    monkeypatch.setattr(p, "constituency_contents", no_contents)
    monkeypatch.setattr(p, "_mgnrega_village_names", empty)
    monkeypatch.setattr(p, "village_names_exact", empty)

    def run(q, prior):
        return asyncio.run(p.resolve_entities(q, ["MGNREGA"], prior_resolved=prior))
    pair = {"district_list": [WGH, RIB], "year_key": 2023}
    r = run("what about expenditure under MGNREGA in FY 2023-24?", pair)
    assert r["resolved"].get("district_list") == [WGH, RIB] and not r["resolved"].get("district")
    assert r["display"]["district"] == "West Garo Hills and Ri Bhoi"
    assert run("what about expenditure in East Khasi Hills?", pair)["resolved"].get("district") == EKH
    stale = run("what about expenditure?", {**pair, "district": WGH})["resolved"]
    assert stale.get("district_list") == [WGH, RIB] and not stale.get("district")
    assert run("what about expenditure?", {"district": WGH, "year_key": 2023})["resolved"].get("district") == WGH


def test_bug4_a_block_of_the_chats_district_keeps_the_year():
    st = ConversationState(scheme="MGNREGA", district=WGH, year=2023, metric="expenditure")
    assert p._same_scheme_context_year("person-days in Tikrikilla block?", "person-days in Tikrikilla block?",
                                       st) == {"year_key": 2023}
    # a block elsewhere, or another scheme: a new question, as D-061 says
    assert p._same_scheme_context_year("person-days in Mawphlang block?", "person-days in Mawphlang block?",
                                       st) is None
    assert not p._c14_drills_into_chat_place("houses in Tikrikilla block for PMAY-G?", st)


def _three_topics():
    s = Session(session_id="topics", user_id="u", created=time.time(), last_seen=time.time())
    s.topics = {"order": ["MGNREGA", "PMAY-G", "CM Elevate"], "active": "CM Elevate",
                "items": {k: {"state": {"scheme": k}, "last_turn": {"route": "data"}} for k in
                          ("MGNREGA", "PMAY-G", "CM Elevate")}}
    return s


def test_bug5_an_applications_only_word_settles_the_open_cm_elevate_topic():
    s = _three_topics()
    assert p._vague_topic_clarification("how many are on hold?", s) is None       # runs in CM Elevate
    # a measure every topic can hold still asks
    assert p._vague_topic_clarification("how many beneficiaries?", s) is not None
    # without an open CM Elevate topic the word stays generic
    assert p._cme_open_topic_pin("how many are on hold?", ["MGNREGA", "PMAY-G"]) is None


def test_new_question_label_only_when_the_chats_scope_is_set_aside():
    st = ConversationState(scheme="MGNREGA", district=EKH, year=2024)
    assert p._c14_keeps_chat_scope("how many person-days under MGNREGA in East Khasi Hills in FY 2024-25?", st)
    assert not p._c14_keeps_chat_scope("how many person-days under MGNREGA in Ri Bhoi in FY 2024-25?", st)
    assert not p._c14_keeps_chat_scope("how many person-days under MGNREGA?", st)
    assert not p._c14_keeps_chat_scope("how many houses under PMAY-G in East Khasi Hills in FY 2024-25?", st)


def test_measure_typos_are_corrected_from_the_synonym_table():
    assert p._vocab_typo("persendays") == "persondays"
    assert "metric" in cp.continuation_signals(p._rephrase_gloss("toatal persendays"))
    assert "metric" not in cp.continuation_signals(p._rephrase_gloss("he is my collik remember"))
