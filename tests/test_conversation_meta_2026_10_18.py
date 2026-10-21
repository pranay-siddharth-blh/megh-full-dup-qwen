"""
Talking about the conversation itself (D-052, KI-310; app/pipeline/common/c15_conversation_meta.py).
Live probe 2026-10-18: after a data answer, "why are you not giving me district wise?" went to the
reference documents, "that's wrong, I asked for completed houses" lost the year, "can you explain
this number?" / "what did you just tell me?" / "you are not understanding me" / "what should I ask
next?" were bounced as off-topic or "didn't catch that", and "thank you, it is very helpful"
re-ran the last data question. Every test calls the real function.
"""
import asyncio
import time

import pytest

from app import edge, entity_resolver
from app import pipeline as p
from app.session_store import Session, Turn

PREV_Q = "How many PMAY-G houses were completed for all of Meghalaya in FY 2023-24"


@pytest.fixture(scope="module", autouse=True)
def _catalog():
    entity_resolver.load_all()


def _data_turn():
    return Turn(question=PREV_Q, raw_question="how many houses completed in 2023-24", route="data",
                schemes=["PMAY-G"], resolved_entities={"year_key": 2023},
                answer="Completed houses in Meghalaya (statewide), in FY 2023-24: 71,976.",
                result_summary="1 row: area=Meghalaya; completed houses=71976")


def _knowledge_turn():
    return Turn(question="Who is eligible for PMAY-G?", raw_question="who is eligible", route="knowledge",
                schemes=["PMAY-G"], answer="Households without a pucca house …")


def _session(prev=None):
    s = Session(session_id="meta", user_id="u", created=time.time(), last_seen=time.time())
    if prev is not None:
        s.turns = [prev]
    return s


# ── what kind of message it is ───────────────────────────────────────────────

@pytest.mark.parametrize("text, kind", [
    ("why are you not giving me district wise?", "breakdown"),
    ("I asked for block wise", "breakdown"),
    ("why not by block?", "breakdown"),
    ("that's wrong, I asked for completed houses", "correction"),
    ("no, I meant sanctioned houses", "correction"),
    ("can you explain this number?", "explain"),
    ("I don't understand", "explain"),
    ("what does this mean?", "explain"),
    ("what did you just tell me?", "recap"),
    ("repeat that", "recap"),
    ("you are not understanding me", "misread"),
    ("why you are not giving this thing?", "misread"),
    ("that's wrong", "misread"),
    ("what should I ask next?", "suggest"),
    ("what else can you tell me?", "suggest"),
    ("suggest me some questions", "suggest"),
])
def test_meta_kinds_after_a_data_answer(text, kind):
    assert p._meta_kind(text, _data_turn()) == kind


@pytest.mark.parametrize("text", [
    "explain the MGNREGA wage rate",
    "I want to know about farmers getting money",
    "houses in East Khasi Hills",
    "which district has the most houses",
    "ok compare with last year",
    "what is the completion rate",
    "I want houses completed in Ri Bhoi",
    "tell me what is going on in my block",
    "suggest me a scheme for farmers",
    "district wise",
])
def test_a_question_is_never_meta(text):
    assert p._meta_kind(text, _data_turn()) is None


def test_without_a_previous_answer_only_misread_and_suggest_apply():
    assert p._meta_kind("what did you just tell me?", None) is None
    assert p._meta_kind("can you explain this number?", None) is None
    assert p._meta_kind("what should I ask next?", None) == "suggest"
    assert p._meta_kind("you are not understanding me", None) == "misread"


def test_a_breakdown_needs_a_data_answer_behind_it():
    assert p._meta_kind("why are you not giving me district wise?", _knowledge_turn()) is None


# ── the question a correction / breakdown runs ──────────────────────────────

def test_breakdown_runs_the_previous_question_by_district():
    q, preface, standalone = p._meta_question("why are you not giving me district wise?", _data_turn())
    assert q == "How many PMAY-G houses were completed in FY 2023-24 by district"
    assert standalone and "district-wise" in preface


def test_correction_runs_only_the_corrected_part():
    q, preface, standalone = p._meta_question("that's wrong, I asked for completed houses", _data_turn())
    assert q == "completed houses" and not standalone and preface.startswith("Sorry")
    assert p._meta_question("no, I meant the sanctioned houses", _data_turn())[0] == "sanctioned houses"


def test_followup_stage_runs_the_correction_in_the_previous_scope(monkeypatch):
    # Since KI-334 (2026-10-19) a correction that only names a new measure is a
    # deterministic measure change on the chat's scheme: the user's words plus
    # the scheme, with the place and year carried by the data-context stage. The
    # rewrite model is no longer called for it.
    async def never(*a, **kw):
        raise AssertionError("the rewrite model must not be called")
    monkeypatch.setattr(p, "rewrite_followup", never)
    s = _session(_data_turn())
    t = p._new_turn("that's wrong, I asked for completed houses")
    t.update(prev=s.last_turn, has_context=True)
    asyncio.run(p._turn_followup_stage(t, session=s))
    assert t["question"] == "completed houses under PMAY-G?"
    assert s.turn_context["answer_preface"].startswith("Sorry about that")
    assert t["is_followup_rewrite"]


def test_followup_stage_runs_the_breakdown_without_a_model_call(monkeypatch):
    async def never(*a, **kw):
        raise AssertionError("the rewrite model must not be called")
    monkeypatch.setattr(p, "rewrite_followup", never)
    s = _session(_data_turn())
    t = p._new_turn("why are you not giving me district wise?")
    t.update(prev=s.last_turn, has_context=True)
    asyncio.run(p._turn_followup_stage(t, session=s))
    assert t["question"] == "How many PMAY-G houses were completed in FY 2023-24 by district"
    assert t["is_followup_rewrite"] and s.turn_context["answer_preface"]


def test_a_failed_data_turn_keeps_the_standalone_question_and_no_preface(monkeypatch):
    """Harness finding 2026-10-18: after a failed breakdown, the next follow-up was rewritten
    from the raw complaint, and the apology sat in front of the failure text."""
    async def fake_kb(question):
        return {"route": "data", "answer": "I understood the question but couldn't build a working query …",
                "schemes": ["PMAY-G"], "rows": [], "sql": None}
    monkeypatch.setattr(p, "_data_path_kb_fallback", fake_kb)
    r = asyncio.run(p._data_path_error_result(ValueError("verifier"),
                                              "How many PMAY-G houses were completed in Ri Bhoi in FY 2023-24 by block",
                                              "why are you not giving me block wise?"))
    assert r["rewritten_question"] == "How many PMAY-G houses were completed in Ri Bhoi in FY 2023-24 by block"
    assert r["answer_failed"] is True
    s = _session()
    s.turn_context = {"answer_preface": "Sorry — here it is block-wise."}
    p._attach_preface(r, s)
    assert r["answer"].startswith("I understood")
    from app.routers.query import build_turn
    assert build_turn("why are you not giving me block wise?", r).question.endswith("by block")


def test_preface_opens_the_answer():
    s = _session()
    s.turn_context = {"answer_preface": "Sorry — here it is district-wise."}
    r = {"route": "data", "answer": "Houses by district: …"}
    p._attach_preface(r, s)
    assert r["answer"] == "Sorry — here it is district-wise.\n\nHouses by district: …"
    e = {"route": "edge", "answer": "x"}
    p._attach_preface(e, s)
    assert e["answer"] == "x"


# ── the replies ──────────────────────────────────────────────────────────────

def test_recap_says_the_last_answer_again():
    r = asyncio.run(p._conversation_meta_answer("what did you just tell me?", _data_turn(), _session(_data_turn())))
    assert r["route"] == "edge" and r["edge_type"] == "recap" and r["context_dependent"]
    assert "71,976" in r["answer"] and "FY 2023-24" in r["answer"]
    assert r["suggestions"][0] == "Break that down by district"


def test_misread_names_what_was_understood_and_asks_for_the_real_question():
    s = _session(_data_turn())
    r = asyncio.run(p._conversation_meta_answer("you are not understanding me", _data_turn(), s))
    assert r["edge_type"] == "misread" and PREV_Q.rstrip("?") in r["answer"] and "scheme" in r["answer"]
    r2 = asyncio.run(p._conversation_meta_answer("you are not understanding me", _data_turn(), s))
    assert r2["answer"].split(" ")[0] != r["answer"].split(" ")[0]          # the wording rotates


def test_suggest_lists_next_questions_for_the_topic():
    r = asyncio.run(p._conversation_meta_answer("what should I ask next?", _data_turn(), _session(_data_turn())))
    assert r["edge_type"] == "suggest" and "PMAY-G" in r["answer"]
    assert "- Break that down by district" in r["answer"] and "- Compare with the previous financial year" in r["answer"]
    assert len(r["suggestions"]) == 5
    none = asyncio.run(p._conversation_meta_answer("what should I ask next?", None, _session()))
    assert none["suggestions"] == list(edge.STARTERS)[:5]


def test_explain_uses_the_model_when_its_numbers_are_the_answers(monkeypatch):
    async def fake(prompt, **kw):
        assert "71,976" in prompt and "PMAY-G" in prompt
        return "This is the count of PMAY-G houses marked completed across all of Meghalaya in FY 2023-24 — 71,976 in all. I can break it down by district."
    monkeypatch.setattr(p.llm, "call_rewriter", fake)
    r = asyncio.run(p._conversation_meta_answer("can you explain this number?", _data_turn(), _session(_data_turn())))
    assert r["edge_type"] == "explain" and r["answer"].startswith("This is the count")


def test_explain_falls_back_when_the_model_invents_a_number(monkeypatch):
    async def fake(prompt, **kw):
        return "About 72,000 houses were completed, roughly 6,000 a month, which is 55% of the target."
    monkeypatch.setattr(p.llm, "call_rewriter", fake)
    r = asyncio.run(p._conversation_meta_answer("I don't understand", _data_turn(), _session(_data_turn())))
    assert "72,000" not in r["answer"] and "71,976" in r["answer"] and "PMAY-G" in r["answer"]


def test_explain_falls_back_when_the_model_fails(monkeypatch):
    async def fake(prompt, **kw):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(p.llm, "call_rewriter", fake)
    r = asyncio.run(p._conversation_meta_answer("what does this mean?", _data_turn(), _session(_data_turn())))
    assert r["edge_type"] == "explain" and "71,976" in r["answer"]


def test_meta_reply_is_an_aside_so_the_topic_continues():
    from app import conversation_layer, topic_memory
    from app.routers.query import build_turn
    s = _session(_data_turn())
    r = asyncio.run(p._conversation_meta_answer("what did you just tell me?", s.last_turn, s))
    assert topic_memory._memory(s)["aside"] == "what did you just tell me?"
    s.turns.append(build_turn("what did you just tell me?", r))
    assert conversation_layer.resume_after_small_talk(s)
    assert s.last_turn.route == "data" and s.last_turn.question == PREV_Q


def test_a_refused_request_does_not_end_the_topic():
    """Proposal §9.2: an out-of-scope message leaves the active topic untouched —
    a harmful one included (live 2026-10-18: "what about 2022-23?" after a refusal
    asked "which scheme?")."""
    from app import conversation_layer, conversation_replies, edge
    from app.routers.query import build_turn
    s = _session(_data_turn())
    refused = edge.detect_harmful("how to make a bomb")
    base = {"route": "edge", "intent": "EDGE", "edge_type": refused["type"], "answer": refused["response"],
            "suggestions": []}
    styled = conversation_replies.restyle(s, "how to make a bomb", base) or base
    assert styled["suggestions"] == [] and "can't" in styled["answer"]          # still a firm refusal
    s.turns.append(build_turn("how to make a bomb", styled))
    assert conversation_layer.resume_after_small_talk(s)
    assert s.last_turn.route == "data" and s.last_turn.question == PREV_Q


def test_a_denied_followup_does_not_end_the_topic():
    """Proposal F2: a follow-up outside the account's area is refused for that turn
    only; the topic survives (live 2026-10-18: after "by block" was denied for a
    district-level account, "and statewide?" was bounced as off-topic)."""
    from app import conversation_layer
    s = _session(_data_turn())
    s.turns.append(Turn(question="by block", raw_question="by block", route="denied", schemes=["PMAY-G"],
                        answer="This query requires data at block level …"))
    assert conversation_layer.resume_after_small_talk(s)
    assert s.last_turn.route == "data" and s.last_turn.question == PREV_Q


# ── roll-up: block -> district -> state (E3) ─────────────────────────────────

def _block_turn():
    return Turn(question="MGNREGA expenditure in Mawphlang block in FY 2023-24", raw_question="only Mawphlang", route="data",
                schemes=["MGNREGA"], resolved_entities={"block": "MAWPHLANG", "district": "EAST KHASI HILLS", "year_key": 2023},
                answer="Mawphlang block spent 1168.22 lakh.")


@pytest.mark.parametrize("text", ["back to the district level", "and for the whole district?", "the district total please"])
def test_rollup_block_to_district(text):
    from app import context_policy as cp
    q, level, plan = p._rollup_question(text, _block_turn())
    assert level == "district" and q == "MGNREGA expenditure in East Khasi Hills district in FY 2023-24"
    # the plan clears the levels rolled past, so prior_resolved cannot put the block back
    left = cp.apply_merge_plan(_block_turn().resolved_entities, plan)
    assert "block" not in left and left.get("district") == "EAST KHASI HILLS"


def test_rollup_to_state_and_from_village():
    from app import context_policy as cp
    q, level, plan = p._rollup_question("and statewide?", _block_turn())
    assert (q, level) == ("MGNREGA expenditure in all of Meghalaya in FY 2023-24", "state")
    assert "district" not in cp.apply_merge_plan(_block_turn().resolved_entities, plan)
    v = Turn(question="MGNREGA expenditure in Nongmadan village in FY 2023-24", raw_question="x", route="data", schemes=["MGNREGA"],
             resolved_entities={"village": "NONGMADAN", "block": "MAWPHLANG", "district": "EAST KHASI HILLS"})
    assert p._rollup_question("back to the block level", v)[:2] == \
        ("MGNREGA expenditure in Mawphlang block in FY 2023-24", "block")
    assert p._rollup_question("whole district", v)[0] == "MGNREGA expenditure in East Khasi Hills district in FY 2023-24"


def test_rollup_from_a_breakdown_uses_the_last_aggregate_question():
    """"which villages?" then "back to the district level": the district TOTAL, not a
    statewide village list (live 2026-10-18)."""
    villages = Turn(question="Which villages in Mawphlang block had MGNREGA expenditure in FY 2023-24?", raw_question="which villages?",
                    route="data", schemes=["MGNREGA"], resolved_entities={"block": "MAWPHLANG", "district": "EAST KHASI HILLS"})
    turns = [_data_turn(), _block_turn(), villages]
    q, level, _ = p._rollup_question("back to the district level", villages, turns)
    assert q == "MGNREGA expenditure in East Khasi Hills district in FY 2023-24"
    q2, level2, _ = p._rollup_question("and statewide?", villages, turns)
    assert q2 == "MGNREGA expenditure in all of Meghalaya in FY 2023-24" and level2 == "state"
    # the live shape: the block turn's question kept "broken down by block", so the
    # district turn is the last aggregate — and it already names the district
    ekh = Turn(question="How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24?", raw_question="x", route="data",
               schemes=["MGNREGA"], resolved_entities={"district": "EAST KHASI HILLS", "year_key": 2023})
    by_block = Turn(question="How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24, broken down by block?",
                    raw_question="by block", route="data", schemes=["MGNREGA"], resolved_entities={"district": "EAST KHASI HILLS"})
    only = Turn(question="How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24, broken down by block, specifically for Mawphlang?",
                raw_question="only Mawphlang", route="data", schemes=["MGNREGA"],
                resolved_entities={"district": "EAST KHASI HILLS", "block": "MAWPHLANG", "year_key": 2023})
    q3, _, _ = p._rollup_question("back to the district level", villages, [ekh, by_block, only, villages])
    assert q3 == "How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24?"
    back = Turn(question=q3, raw_question="back to the district level", route="data", schemes=["MGNREGA"],
                resolved_entities={"district": "EAST KHASI HILLS", "year_key": 2023})
    q4, _, _ = p._rollup_question("and statewide?", back, [ekh, by_block, only, villages, back])
    assert q4 == "How much money was spent under MGNREGA in all of Meghalaya in FY 2023-24?"
    twice = Turn(question="How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24 for East Khasi Hills district",
                 raw_question="x", route="data", schemes=["MGNREGA"], resolved_entities={"district": "EAST KHASI HILLS"})
    assert p._rollup_question("statewide", twice)[0] == \
        "How much money was spent under MGNREGA in all of Meghalaya in FY 2023-24 for all of Meghalaya"


def test_rollup_reads_the_topic_ledger_when_the_session_holds_one_turn():
    """On the server a session is rehydrated with only its last turn (session_sync);
    the earlier aggregate question is found in the durable topic ledger (live
    2026-10-18: the roll-up re-ran the village list for the district instead)."""
    from app import topic_memory
    ekh = Turn(question="How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24?", raw_question="x", route="data",
               schemes=["MGNREGA"], resolved_entities={"district": "EAST KHASI HILLS", "year_key": 2023})
    by_block = Turn(question="How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24, broken down by block?",
                    raw_question="by block", route="data", schemes=["MGNREGA"], resolved_entities={"district": "EAST KHASI HILLS"})
    villages = Turn(question="Which villages in Mawphlang block, East Khasi Hills district, had MGNREGA expenditure in FY 2023-24?",
                    raw_question="which villages?", route="data", schemes=["MGNREGA"],
                    resolved_entities={"district": "EAST KHASI HILLS", "block": "MAWPHLANG", "year_key": 2023})
    s = _session()
    mem = topic_memory._memory(s)
    for t in (ekh, by_block, villages):
        key = topic_memory.topic_key(t.schemes)
        mem["items"].setdefault(key, {"schemes": list(t.schemes), "ledger": []})
        topic_memory._touch(mem, key)
        topic_memory._file_ledger(mem, key, t, s.state)
    s.turns = [villages]                                   # what a rehydrated worker holds
    q, level, _ = p._rollup_question("back to the district level", villages, s.turns, s)
    assert q == "How much money was spent under MGNREGA in East Khasi Hills in FY 2023-24?" and level == "district"


def test_rollup_leaves_other_messages_alone():
    assert p._rollup_question("by block", _block_turn()) is None                       # a breakdown
    assert p._rollup_question("and West Garo Hills?", _block_turn()) is None           # names a place
    assert p._rollup_question("back to the district level", _data_turn()) is None      # nothing below district
    assert p._rollup_question("what is the district level in MGNREGA", _knowledge_turn()) is None


def test_followup_stage_rolls_up_without_a_model_call(monkeypatch):
    async def never(*a, **kw):
        raise AssertionError("the rewrite model must not be called")
    monkeypatch.setattr(p, "rewrite_followup", never)
    s = _session(_block_turn())
    t = p._new_turn("back to the district level")
    t.update(prev=s.last_turn, has_context=True)
    asyncio.run(p._turn_followup_stage(t, session=s))
    assert t["question"] == "MGNREGA expenditure in East Khasi Hills district in FY 2023-24" and t["is_followup_rewrite"]


# ── "compare with pmay" -> cross-scheme comparison in the same scope ─────────

def _mg_turn():
    return Turn(question="Total MGNREGA person-days in FY 2023-24", raw_question="Total MGNREGA person-days in FY 2023-24",
                route="data", schemes=["MGNREGA"], resolved_entities={"year_key": 2023}, answer="27,264,054 person-days")


@pytest.mark.parametrize("text", ["compare with pmay", "Compare with PMAY-G", "vs pmay", "ok, compare it with PMAY-G please",
                                  "and compared to pmay?"])
def test_compare_with_a_scheme_keeps_the_scope(text):
    assert p._compare_with_scheme_question(text, _mg_turn()) == "Compare MGNREGA and PMAY-G in all of Meghalaya in FY 2023-24"


def test_compare_with_a_scheme_in_a_district_and_without_a_year():
    pm = Turn(question="PMAY-G houses completed in Ri Bhoi in FY 2023-24", raw_question="x", route="data", schemes=["PMAY-G"],
              resolved_entities={"district": "RI BHOI", "year_key": 2023})
    assert p._compare_with_scheme_question("and compared to Focus Plus?", pm) == "Compare PMAY-G and Focus Plus in Ri Bhoi in FY 2023-24"
    fp = Turn(question="Focus Plus beneficiaries in West Garo Hills", raw_question="x", route="data", schemes=["Focus Plus"],
              resolved_entities={"district": "WEST GARO HILLS"})
    assert p._compare_with_scheme_question("compare with mgnrega", fp) == "Compare Focus Plus and MGNREGA in West Garo Hills"
    assert p._compare_with_scheme_question("compare it with CM Elevate Legacy", fp) == \
        "Compare Focus Plus and CM Elevate Legacy in West Garo Hills"


@pytest.mark.parametrize("text", [
    "compare with mgnrega",                 # the same scheme
    "compare with pmay in Ri Bhoi",         # a new place: not a plain comparison
    "compare with pmay and focus plus",     # two schemes
    "compare with focus",                   # bare Focus: the which-Focus pause must ask
    "compare with last year",               # no scheme
    "pmay houses in 2023-24",               # no compare cue
])
def test_compare_with_a_scheme_leaves_other_messages_alone(text):
    assert p._compare_with_scheme_question(text, _mg_turn()) is None


def test_followup_stage_runs_the_comparison_without_a_model_call(monkeypatch):
    async def never(*a, **kw):
        raise AssertionError("the rewrite model must not be called")
    monkeypatch.setattr(p, "rewrite_followup", never)
    s = _session(_mg_turn())
    t = p._new_turn("compare with pmay")
    t.update(prev=s.last_turn, has_context=True)
    asyncio.run(p._turn_followup_stage(t, session=s))
    assert t["question"] == "Compare MGNREGA and PMAY-G in all of Meghalaya in FY 2023-24" and t["is_followup_rewrite"]
    from app import cross_scheme
    assert cross_scheme.detect(t["question"], ["MGNREGA", "PMAY-G"]) == ["MGNREGA", "PMAY-G"]


def test_edge_stage_answers_meta_before_the_edge_banks(monkeypatch):
    async def none(*a, **kw):
        return None
    monkeypatch.setattr(p, "_guardrail_check", none)      # the model guardrail: not under test
    monkeypatch.setattr(p, "_scheme_pick_answer", none)
    s = _session(_data_turn())
    t = p._new_turn("what should I ask next?")
    t.update(prev=s.last_turn, has_context=True)
    r = asyncio.run(p._turn_edge_stage(t, session=s))
    assert r["edge_type"] == "suggest"


# ── the small gaps the same probe found ─────────────────────────────────────

def test_thanks_with_a_compliment_is_thanks():
    assert edge.detect_edge_case("thank you, it is very helpful", has_context=True)["type"] == "thanks"
    assert edge.detect_edge_case("thank you so much, very helpful")["type"] == "thanks"


def test_farmers_getting_money_reaches_the_pipeline():
    assert edge.detect_edge_case("I want to know about farmers getting money") is None


def test_what_is_going_on_in_a_place_is_a_figures_question():
    assert p._FIGURE_SUMMARY_MATCH.search("tell me what is going on in Dalu block under MGNREGA")
    assert p._FIGURE_SUMMARY_MATCH.search("overview of Ri Bhoi")


# ── a place overview becomes the scheme's headline question ─────────────────

@pytest.mark.parametrize("text, want", [
    ("I am a block officer from Dalu, tell me what is going on in my block, MGNREGA",
     "Compare expenditure and person-days in Dalu block"),
    ("overview of Ri Bhoi under PMAY-G in 2023-24", "PMAY-G house status in Ri Bhoi district in FY 2023-24"),
    ("status of Dalu block under CM Elevate", "Number of CM Elevate applications by status in Dalu block"),
    ("how is East Khasi Hills doing in Focus Plus",
     "Total Focus Plus amount disbursed and number of beneficiaries in East Khasi Hills district"),
])
def test_overview_question(text, want):
    q, preface = p._overview_question(text)
    assert q == want and preface.startswith("Here's an overview of")


@pytest.mark.parametrize("text", [
    "MGNREGA person-days in Dalu block",                  # names its measure
    "tell me what is going on in my block",               # no scheme yet (the scheme pause asks)
    "overview of Meghalaya under PMAY-G",                 # no district / block
    "how is the MGNREGA wage rate decided",               # a rules question
    "compare Dalu and Rongram blocks under MGNREGA",      # two places
])
def test_overview_question_leaves_real_questions_alone(text):
    assert p._overview_question(text) is None


@pytest.mark.parametrize("text", ["why is it so low?", "what is the reason?", "how come it is this much", "why only this many"])
def test_asking_why_a_figure_is_what_it_is(text):
    assert p._meta_kind(text, _all_years_turn()) == "reason"


def test_why_questions_about_the_bot_or_with_content_are_not_reason():
    assert p._meta_kind("why are you not giving me district wise?", _all_years_turn()) == "breakdown"
    assert p._meta_kind("why is MGNREGA expenditure low in Dalu", _all_years_turn()) is None
    assert p._meta_kind("why is it so low?", _knowledge_turn()) is None


def test_reason_reply_says_the_records_hold_figures_not_reasons():
    prev = _all_years_turn()
    prev.resolved_entities = {"block": "DALU", "year_key": 2024}
    r = asyncio.run(p._conversation_meta_answer("why is it so low?", prev, _session(prev)))
    assert r["edge_type"] == "reason" and "not the reasons" in r["answer"] and "MGNREGA" in r["answer"]
    # a chip is sent as the message, so it is a question the pipeline answers as typed
    assert r["suggestions"][0] == "MGNREGA person-days by block in West Garo Hills in FY 2024-25"
    assert "Show every financial year, year by year" not in r["suggestions"]       # KI-311
    pm = _data_turn()
    pm.resolved_entities = {"district": "RI BHOI", "year_key": 2023}
    r2 = asyncio.run(p._conversation_meta_answer("why so few?", pm, _session(pm)))
    assert r2["suggestions"][:3] == ["PMAY-G houses completed by district in FY 2023-24",
                                     "Compare with the previous financial year",
                                     "Show every financial year, year by year"]


def test_an_opening_okay_does_not_hide_a_followup():
    assert p.looks_like_followup("okay give me for East Khasi Hills")
    assert p.looks_like_followup("ok, now for East Khasi Hills")
    assert p._c01_strip_opening_fillers("okay") == "okay"           # a bare filler stays itself


def _all_years_turn():
    return Turn(question="Compare expenditure and person-days in Dalu block", raw_question="MGNREGA", route="data",
                schemes=["MGNREGA"], resolved_entities={"block": "DALU"},
                answer="Under MGNREGA, DALU block recorded total expenditure of 8,892.08 lakh and 2,646,057 person-days.")


def test_last_year_with_no_year_in_play_asks_which_years():
    from app.session_store import ConversationState
    e = p._relative_year_clarification("ok compare with last year", _all_years_turn(), ConversationState())
    assert e.rule == "year-not-specified" and "last year" in e.question and "Dalu" in e.question
    assert e.options[0] == {"label": "FY 2025-26",
                            "question": "Compare expenditure and person-days in Dalu block for FY 2025-26"}
    assert [o["label"] for o in e.options] == ["FY 2025-26", "FY 2024-25", "FY 2023-24"]   # MGNREGA: no year-by-year (KI-311)
    pm = Turn(question="How many PMAY-G houses were completed for all of Meghalaya", raw_question="x", route="data",
              schemes=["PMAY-G"])
    pe = p._relative_year_clarification("and last year?", pm, ConversationState())
    assert pe.options[-1]["question"] == "How many PMAY-G houses were completed for each financial year"


def test_last_year_with_a_year_in_play_is_left_to_reference_substitution():
    from app.session_store import ConversationState
    st = ConversationState(); st.year = 2023
    assert p._relative_year_clarification("compare with last year", _all_years_turn(), st) is None
    assert p._relative_year_clarification("compare with FY 2022-23", _all_years_turn(), ConversationState()) is None
    assert p._relative_year_clarification("compare Ri Bhoi with last year", _all_years_turn(), ConversationState()) is None


def test_followup_stage_pauses_for_the_year(monkeypatch):
    s = _session(_all_years_turn())
    t = p._new_turn("ok compare with last year")
    t.update(prev=s.last_turn, has_context=True)
    with pytest.raises(p.ClarificationNeeded) as ei:
        asyncio.run(p._turn_followup_stage(t, session=s))
    assert ei.value.rule == "year-not-specified"
    assert s.turn_context["standalone_question"] == "Compare expenditure and person-days in Dalu block"


def test_route_stage_runs_the_overview_as_data(monkeypatch):
    async def never(*a, **kw):
        raise AssertionError("the intent classifier must not be called")
    monkeypatch.setattr(p, "classify_intent", never)
    s = _session()
    t = p._new_turn("overview of Ri Bhoi under PMAY-G")
    asyncio.run(p._turn_route_stage(t, session=s))
    assert t["intent"] == "DATA" and t["question"] == "PMAY-G house status in Ri Bhoi district"
    assert s.turn_context["answer_preface"] == "Here's an overview of Ri Bhoi district under PMAY-G:"
