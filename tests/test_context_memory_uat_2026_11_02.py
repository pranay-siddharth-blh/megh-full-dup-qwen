"""
BLH Bot UAT 2026-11-02 — the four context failures (D-098). Every test calls the real
function; none re-implements it.

  3. "compare this with spend on Focus scheme" -> "Which Focus?" -> typed "compare both
     schemes by district" was answered for Focus Plus only (a typed reply other than one
     bare scheme name dropped the paused question).
  4. "show the comparison visually in chart form" after a Focus Plus vs Focus Legacy
     answer paused "Which scheme?" (turn_kind read a reference cue, the rewrite gate did not).
  8. "where are these 126 beneficiaries registered?" answered the district split of all
     1,71,107 (the 126 lived only in the answer's text); the explicit question was
     answered with the statewide sanctioned amount (the PMAY-G fixed query).
 10. "What is completion rate" right after a PMAY-G answer asked "PMAY-G, Focus Legacy or
     Focus Plus?" (D-061's picker ignored the active topic).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import context_manager as cm  # noqa: E402
from app import context_policy as cp  # noqa: E402
from app import pipeline as p  # noqa: E402
from app import prompt_builder, topic_memory  # noqa: E402
from app.session_store import ConversationState, Session, Turn  # noqa: E402

PAUSED_FOCUS = "compare this with spend on Focus scheme"
PMAY_ANSWER = ("PMAY-G beneficiaries in Meghalaya (statewide), across all financial years (FY 2017-18 to "
               "FY 2023-24): 1,71,107 (including 126 registered with a sanctioned amount of ₹0 and no house "
               "sanctioned yet).")
PMAY_FACTS_SQL = ("SELECT 'MEGHALAYA' AS entity_key, COUNT(*) AS houses, "
                  "COUNT(*) FILTER(WHERE is_completed) AS completed, "
                  "COUNT(*) FILTER(WHERE status_name IS NULL) AS no_status, "
                  "COUNT(*) FILTER(WHERE is_placeholder) AS placeholders FROM curated.v_pmay")


def _focus_options():
    return p._focus_ambiguity_clarification(PAUSED_FOCUS).options


def _typed(reply, paused=PAUSED_FOCUS, options=None):
    opts = options if options is not None else _focus_options()
    return p._resume_scheme_pause(reply, opts) or p._resume_scheme_pause_typed(reply, paused, opts)


# ── UAT 3: a typed reply to a scheme pause ────────────────────────────────────
def test_typed_both_with_scope_takes_every_offered_scheme_and_keeps_the_scope():
    out = _typed("compare both schemes by district")
    assert out == "compare this with spend on Focus Legacy and Focus Plus scheme by district?"


def test_typed_all_options_variants():
    for reply in ("both", "all of them", "compare them"):
        assert "Focus Legacy and Focus Plus" in _typed(reply), reply


def test_typed_one_scheme_or_side_word_plus_scope():
    assert _typed("focus legacy by district") == "compare this with spend on Focus Legacy scheme by district?"
    assert _typed("legacy by district") == "compare this with spend on Focus Legacy scheme by district?"


def test_typed_scope_only_keeps_the_paused_question():
    # still no scheme: the which-Focus question is asked again, now with the scope
    assert _typed("by district") == "compare this with spend on Focus scheme by district?"


def test_bare_scheme_name_still_resumes_exactly_as_before():
    assert _typed("Focus Plus") == "compare this with spend on Focus Plus scheme"
    assert _typed("legacy") == "compare this with spend on Focus Legacy scheme"


def test_typed_reply_that_would_lose_words_goes_on_untouched():
    # a filter the paused question cannot hold, a new measure question, small talk, a year scope
    for reply in ("both, for women", "how many members in focus legacy", "thanks", "all years"):
        assert _typed(reply) is None, reply


def test_scheme_not_specified_pause_several_and_all():
    stem = "How many beneficiaries are there"
    opts = [{"label": lbl, "question": p._scheme_option_question(stem, s)} for s, lbl in p._SCHEME_PICK_LABELS]
    assert _typed("mgnrega and pmay-g", stem, opts) == "How many beneficiaries are there for MGNREGA and PMAY-G?"
    assert _typed("pmay by block", stem, opts) == "How many beneficiaries are there for PMAY-G by block?"
    assert _typed("all of them by district", stem, opts).endswith("CMSS by district?")


def test_a_scheme_the_pause_did_not_offer_is_a_new_question():
    assert p._resume_scheme_pause_typed("compare with mgnrega by district", PAUSED_FOCUS, _focus_options()) is None


# ── UAT 4: one follow-up decision ─────────────────────────────────────────────
def _prev(schemes, route="data", question="compare focus plus and focus legacy by district"):
    return Turn(question=question, raw_question=question, route=route, schemes=list(schemes))


def test_reference_cue_is_a_followup_for_the_rewrite_gate():
    tk = cp.turn_kind("show the comparison visually in chart form")
    assert tk.kind == cp.TURN_FOLLOWUP
    assert p._c14_cue_followup(tk, _prev(["Focus Plus", "Focus Legacy"])) is True


def test_cue_followup_needs_an_answered_scheme_turn_and_a_real_cue():
    tk = cp.turn_kind("show the comparison visually in chart form")
    assert p._c14_cue_followup(tk, None) is False
    assert p._c14_cue_followup(tk, _prev([], route="edge")) is False
    # a bare fragment ("who is harshit") is not a cue: the older checks still decide it
    frag = cp.turn_kind("who is harshit")
    assert p._c14_cue_followup(frag, _prev(["PMAY-G"])) is False


# ── UAT 10: a vague question continues the active topic ───────────────────────
def _topics(active):
    def item(s):
        return {"schemes": [s], "state": ConversationState(scheme=s).to_dict(), "last_turn": None,
                "questions": [], "turns": 1, "summary": s}
    keys = ["Focus Plus", "Focus Legacy", "PMAY-G"]
    items = {k: item(k) for k in keys}
    items["Focus Plus + Focus Legacy"] = {"schemes": ["Focus Plus", "Focus Legacy"], "state": {},
                                          "last_turn": None, "questions": [], "turns": 1, "summary": ""}
    return {"active": active, "order": keys + ["Focus Plus + Focus Legacy"], "ack": None, "items": items}


def _session(topics):
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.turns = [_prev(["PMAY-G"], question="What is the PMAY-G completion rate in Meghalaya, by district?")]
    s.state = ConversationState(scheme="PMAY-G")
    s.topics = topics
    return s


def test_vague_question_runs_in_the_active_topic():
    for q in ("What is completion rate", "define completion rate"):
        assert p._vague_topic_clarification(q, _session(_topics("PMAY-G"))) is None, q


def test_vague_question_still_asks_when_the_active_topic_is_a_comparison():
    e = p._vague_topic_clarification("What is completion rate", _session(_topics("Focus Plus + Focus Legacy")))
    assert e is not None and e.rule == topic_memory.TOPIC_PAUSE_RULE
    assert {o["label"] for o in e.options} == {"PMAY-G", "Focus Legacy", "Focus Plus"}


# ── UAT 8: a figure the previous answer stated ────────────────────────────────
def test_quoted_figures_reads_pointer_plus_number_never_a_year():
    assert cm.quoted_figures("where are these 126 beneficiaries registered?") == ["126"]
    assert cm.quoted_figures("show the 1,71,107 by district") == ["171107"]
    assert cm.quoted_figures("what about the 2023?") == []
    assert cm.quoted_figures("top 5 districts") == []


def test_figure_clause_is_the_clause_not_the_sentence():
    assert cm.figure_clause("where are these 126 beneficiaries registered?", PMAY_ANSWER) == (
        "126", "registered with a sanctioned amount of ₹0 and no house sanctioned yet")
    other = "CM Elevate applications in Ri Bhoi: 1,204. Of these, 45 are pending with the bank; 12 were rejected."
    assert cm.figure_clause("which district has most of those 45?", other) == ("45", "are pending with the bank")


def test_result_subsets_reads_each_filtered_count_from_the_sql_tree():
    row = {"entity_key": "MEGHALAYA", "houses": 171107, "completed": 129943, "no_status": 12, "placeholders": 126}
    subs = cm.result_subsets({"route": "data", "sql": PMAY_FACTS_SQL, "rows": [row]})
    assert {"figure": "126", "column": "placeholders", "condition": "is_placeholder"} in subs
    assert {"figure": "12", "column": "no_status", "condition": "status_name IS NULL"} in subs
    assert all(s["column"] != "houses" for s in subs)          # an unfiltered count is not a subset
    assert cm.result_subsets({"route": "data", "sql": PMAY_FACTS_SQL, "rows": [row, row]}) == []


def test_subset_for_figure_never_guesses_between_two_conditions():
    t = Turn(question="q", raw_question="q", route="data", subsets=[
        {"figure": "5", "column": "a", "condition": "x"}, {"figure": "5", "column": "b", "condition": "y"},
        {"figure": "126", "column": "placeholders", "condition": "is_placeholder"}])
    assert cm.subset_for_figure(t, "5") is None
    assert cm.subset_for_figure(t, "126")["condition"] == "is_placeholder"


def test_figure_reference_rewrite_uses_the_stored_condition():
    prev = Turn(question="How many beneficiaries are enrolled?", raw_question="How many beneficiaries are enrolled?",
                route="data", schemes=["PMAY-G"], answer=PMAY_ANSWER,
                subsets=[{"figure": "126", "column": "placeholders", "condition": "is_placeholder"}])
    q, cond = p._c14_figure_reference_question("where are these 126 beneficiaries registered?", prev, None)
    assert cond == "is_placeholder"
    assert q.startswith("where are these 126 beneficiaries registered (the 126 placeholders) under PMAY-G")


def test_figure_reference_rewrite_without_a_stored_condition_uses_the_answer_clause():
    prev = Turn(question="How many beneficiaries are enrolled?", raw_question="How many beneficiaries are enrolled?",
                route="data", schemes=["PMAY-G"], answer=PMAY_ANSWER)
    q, cond = p._c14_figure_reference_question("where are these 126 beneficiaries registered?", prev, None)
    assert cond is None
    assert "(the 126 registered with a sanctioned amount of ₹0" in q
    assert "2017" not in q                                   # the year range is not copied


def test_figure_tier_in_the_rewrite_evidence():
    prev = Turn(question="How many beneficiaries are enrolled?", raw_question="x", route="data",
                schemes=["PMAY-G"], answer=PMAY_ANSWER)
    ev = cm.build_rewrite_evidence("where are these 126 beneficiaries registered?", prev)
    assert "answer_figure" in ev["tiers"] and "126 registered with a sanctioned amount" in ev["answer"]
    assert cm.build_rewrite_evidence("what about 2023-24?", prev)["answer"] == ""


def test_pmay_fixed_query_refuses_a_stated_subset_but_not_years_dates_or_instalments():
    assert p._pmay_stated_condition("What is the location of 126 PMAY-G beneficiaries with a sanction amount of 0?")
    assert p._pmay_stated_condition("Where are these 126 beneficiaries registered?")
    for q in ("How many PMAY houses were sanctioned in 2023?", "houses sanctioned in FY 23-24",
              "sanctioned between 01/04/2022 and 31/03/2023", "houses with 3 instalments released",
              "houses sanctioned on 15 March 2023", "How many PMAY-G houses completed in Ri Bhoi in 2022-23?"):
        assert not p._pmay_stated_condition(q), q


def test_rows_must_add_up_to_the_figure_pointed_at():
    q = "where are these 126 beneficiaries registered (the 126 placeholders) under PMAY-G?"
    short = [{"village": "A", "beneficiary_count": 100}, {"village": "B", "beneficiary_count": 14}]
    full = [{"village": "A", "beneficiary_count": 112}, {"village": "B", "beneficiary_count": 14}]
    assert "114" in p._c17_figure_reference_mismatch(q, short)
    assert "no rows" in p._c17_figure_reference_mismatch(q, [])
    assert p._c17_figure_reference_mismatch(q, full) is None
    # a list of places without a count column is not judged; a question we did not write is never judged
    assert p._c17_figure_reference_mismatch(q, [{"village": "A"}]) is None
    assert p._c17_figure_reference_mismatch("where are these 126 beneficiaries registered?", short) is None


def test_subset_condition_is_a_mandatory_resolved_entity_in_the_sql_prompt():
    block = prompt_builder._entities_block({"resolved": {"subset_condition": "is_placeholder"}}, "", ["PMAY-G"])
    assert "is_placeholder" in block and "add no other condition" in block


def test_subsets_survive_the_durable_snapshot_and_topic_memory():
    subs = [{"figure": "126", "column": "placeholders", "condition": "is_placeholder"}]
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.turns = [Turn(question="q", raw_question="q", route="data", schemes=["PMAY-G"], subsets=subs)]
    s2 = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s2.apply_snapshot(s.to_snapshot())
    assert s2.last_turn.subsets == subs
    assert topic_memory._turn_from(topic_memory._turn_dict(s.last_turn)).subsets == subs
