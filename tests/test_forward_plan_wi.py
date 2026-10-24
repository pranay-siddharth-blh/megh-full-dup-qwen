"""The forward plan (documents/Context_Memory_Forward_Backward_Review_v3.docx,
WI-1 .. WI-6) and KI-301, built 2026-10-16. Offline: no gateway, no DB. The live
scenarios are tests/live_context_validation.py H .. M (KI-033, KI-223, KI-301,
WI-1+2, WI-3, WI-4)."""
import asyncio
import time
import types

import pytest

from app import context_manager, pipeline as p, pipeline_graph as pg
from app.session_store import ConversationState, Session, Turn


@pytest.fixture(autouse=True, scope="module")
def _places_loaded():
    # Place names come from the entity resolver's local YAML (app startup loads it).
    from app.entity_resolver import load_all
    load_all()


def _session(**state):
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.state = ConversationState(**state)
    return s


# ── WI-1: a knowledge turn naming another scheme switches the topic ─────────
def test_knowledge_turn_naming_another_scheme_switches_the_topic():
    s = _session(scheme="MGNREGA", district="EAST KHASI HILLS", year=2022, metric="person-days")
    context_manager.update_state(s, "Who is eligible for PMAY-G?", "Who is eligible for PMAY-G?",
                                 {"route": "knowledge", "schemes": ["PMAY-G"]})
    st = s.state
    assert (st.scheme, st.district, st.year, st.metric) == ("PMAY-G", None, None, None)


@pytest.mark.parametrize("q", ["What is DBT?", "How does MGNREGA work?"])
def test_a_digression_that_names_no_other_scheme_keeps_the_topic(q):
    s = _session(scheme="MGNREGA", district="EAST KHASI HILLS", year=2022)
    context_manager.update_state(s, q, q, {"route": "knowledge", "schemes": ["MGNREGA"]})
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", "EAST KHASI HILLS", 2022)


# ── WI-2: a year is allowed in a measure after a knowledge answer ───────────
def _kturn(question, schemes):
    return Turn(question=question, raw_question=question, route="knowledge", schemes=schemes)


def test_a_measure_with_a_year_after_a_knowledge_answer_takes_its_scheme():
    prev = _kturn("Who is eligible for PMAY-G?", ["PMAY-G"])
    assert p._measure_after_knowledge("How many in 2023-24?", prev)
    assert p._measure_after_knowledge("How many beneficiaries in 2022-23?", prev)
    assert not p._is_measure_only("How many in 2023-24?")                 # the default still refuses a year
    assert not p._measure_after_knowledge("How many in Ri Bhoi in 2023-24?", prev)   # a place: not measure-only


# ── WI-4: "this year" takes the session's year only on a follow-up ──────────
def test_a_standalone_question_does_not_borrow_the_sessions_year():
    st = ConversationState(scheme="MGNREGA", year=2022)
    assert p._reference_state("How many PMAY-G houses were sanctioned in Ri Bhoi this year?", st).year is None
    assert p._reference_state("what about last year?", st).year == 2022
    assert p._reference_state("and this year?", st).year == 2022


# ── WI-5: an answer built from the conversation is marked for the router ────
@pytest.mark.parametrize("extra", [{"is_followup_rewrite": True}, {"plan": {"kind": "GEOGRAPHY_CHANGE"}},
                                   {"scope_resumed": True}])
def test_a_context_built_answer_is_context_dependent(extra):
    state = {"response": {"route": "knowledge", "answer": "x"}, "response_origin": "knowledge",
             "raw_question": "and in Ri Bhoi?", "question": "and in Ri Bhoi?", **extra}
    out = asyncio.run(pg.node_finalize(state, types.SimpleNamespace(context=types.SimpleNamespace(session=None, scope=None))))
    assert out["response"]["context_dependent"] is True


def test_a_standalone_answer_is_not_context_dependent():
    state = {"response": {"route": "knowledge", "answer": "x"}, "response_origin": "knowledge",
             "raw_question": "What is MGNREGA?", "question": "What is MGNREGA?"}
    out = asyncio.run(pg.node_finalize(state, types.SimpleNamespace(context=types.SimpleNamespace(session=None, scope=None))))
    assert not out["response"].get("context_dependent")


# ── WI-6: a semantic hit must name the same scheme, place and year ──────────
def test_semantic_hit_needs_the_same_scheme_place_and_year(monkeypatch):
    from app import semantic_cache as sc
    from app.config import settings
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    cache = sc.SemanticCache(ttl=600, max_entries=50, threshold=0.5)

    async def same_vec(_q):
        return [1.0, 0.0]
    monkeypatch.setattr(cache, "_embed", same_vec)

    async def run():
        await cache.put("MGNREGA person-days in Ri Bhoi in FY 2024-25", {"answer": "A"}, scope_key="k")
        hit_other_year, _ = await cache.lookup("MGNREGA person-days in Ri Bhoi in FY 2023-24", "k")
        hit_other_place, _ = await cache.lookup("MGNREGA person-days in East Khasi Hills in FY 2024-25", "k")
        hit_same, _ = await cache.lookup("person-days under MGNREGA, Ri Bhoi, FY 2024-25", "k")
        return hit_other_year, hit_other_place, hit_same
    other_year, other_place, same = asyncio.run(run())
    assert other_year is None and other_place is None
    assert same is not None and same["answer"] == "A"


# ── 2026-10-24: a semantic hit must also keep direction, status and measure ──
def test_semantic_hit_needs_the_same_direction_status_and_measure(monkeypatch):
    from app import semantic_cache as sc
    from app.config import settings
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True)
    cache = sc.SemanticCache(ttl=600, max_entries=50, threshold=0.5)

    async def same_vec(_q):
        return [1.0, 0.0]
    monkeypatch.setattr(cache, "_embed", same_vec)

    stored = {
        "top 5 districts by person days in MGNREGA": [
            "bottom 5 districts by person days in MGNREGA",
            "top 10 districts by person days in MGNREGA"],
        "How many houses were sanctioned under PMAY-G in 2023-24?": [
            "How many houses were completed under PMAY-G in 2023-24?"],
        "PMAY-G amount released in 2023-24": ["PMAY-G amount sanctioned in 2023-24"],
        "How many women were employed under MGNREGA?": ["How many men were employed under MGNREGA?"],
        "CM Elevate applications on hold": ["CM Elevate applications approved"],
        "average wage in MGNREGA": ["percentage of wage in MGNREGA expenditure"],
    }
    paraphrases = [
        ("How many houses were sanctioned under PMAY-G in 2023-24?", "PMAY-G houses sanctioned in 2023-24"),
        ("top 5 districts by person days in MGNREGA", "top 5 districts in MGNREGA by person days"),
        ("how many producer groups are there in Focus Legacy",
         "number of producer groups under Focus Legacy"),
    ]

    async def run():
        misses, hits = [], []
        for q, others in stored.items():
            cache._store.clear()
            await cache.put(q, {"answer": q}, scope_key="k")
            for o in others:
                misses.append((o, (await cache.lookup(o, "k"))[0]))
        for a, b in paraphrases:
            cache._store.clear()
            await cache.put(a, {"answer": a}, scope_key="k")
            hits.append((b, (await cache.lookup(b, "k"))[0]))
        return misses, hits
    misses, hits = asyncio.run(run())
    assert [o for o, v in misses if v is not None] == []
    assert [b for b, v in hits if v is None] == []


# ── KI-301: a pronoun beside a scheme name points at the previous term ──────
def test_its_after_a_term_question_is_a_followup():
    prev = _kturn("What is Gram Panchayat?", [])
    assert p.pronoun_refers_to_previous_term("what is its role in PMAY-G?", prev)
    assert p.pronoun_refers_to_previous_term("How does it work under MGNREGA?", prev)


def test_its_is_not_a_followup_otherwise():
    term = _kturn("What is Gram Panchayat?", [])
    scheme_q = _kturn("What is PMAY-G?", ["PMAY-G"])
    data = Turn(question="q", raw_question="What is Gram Panchayat?", route="data", schemes=["MGNREGA"])
    assert not p.pronoun_refers_to_previous_term("What benefits will I get under this Focus Plus?", term)
    assert not p.pronoun_refers_to_previous_term("what is its role in PMAY-G?", scheme_q)   # named a scheme
    assert not p.pronoun_refers_to_previous_term("what is its role in PMAY-G?", data)        # not knowledge
    assert not p.pronoun_refers_to_previous_term("what is its role?", term)                  # no scheme: the old path
