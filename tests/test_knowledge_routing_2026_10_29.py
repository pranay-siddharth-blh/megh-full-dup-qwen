"""
Knowledge fix (2026-10-29, megh_chatbot_knowledge_fix_prompt.md): offline checks of
the real functions behind the knowledge routing and answer fixes. The live end-to-end
suite is tests/live_chat_knowledge.py (needs the VPN).

KR1  _knowledge_form_question (c14) — the question's FORM routes it, data look-alikes stay DATA
K5   _is_years_list_question (c06) — "what year did PMAY-G start" is not a years-of-data list
K10  _FOCUS_ACRONYM_ASK (c14) — "what does FOCUS stand for" is the FOCUS scheme's own name
KR3  rag._sub_asks / rag._facet_queries — each part of a multi-part question is searched
KR11 rag._looks_hinglish — romanised Hindi gets an English wording
KR12 rag._faq_match — the FAQ entry for the very question goes first
KR4  rag._supporting_chunks — cite the pieces the answer uses
KR5  rag._rag_unit_supported / _rag_unit_numbers — numbers must be in the passages
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import entity_resolver, rag  # noqa: E402
from app import pipeline as p  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _places():
    # the place vetoes read the place index (as the app's lifespan loads it)
    entity_resolver.load_all()


# ── KR1: routing by form ────────────────────────────────────────────────────
@pytest.mark.parametrize("q, form", [
    ("How much does Focus Plus pay?", "rate"),
    ("how much does it pay?", "rate"),
    ("How much does Focus Plus pay per household?", "rate"),
    ("How much does Focus Legacy give each producer group member?", "rate"),
    ("What details are recorded when a PMAY-G beneficiary is registered?", "registration_details"),
    ("what details does awaassoft record for a pmay-g beneficiary at registration", "registration_details"),
    ("How can I check my PMAY-G beneficiary status?", "process"),
    ("How can an entrepreneur apply under the CM-ELEVATE programme?", "process"),
    ("mgnrega work within how many kilometres of the village?", "distance"),
    ("MGNREGS gives how many days of work to a family in a year?", "guaranteed_days"),
    ("mgnrega funding pattern between central and state government", "funding_pattern"),
    ("who pays for MGNREGA, the centre or the state?", "funding_pattern"),
    ("How many members does a producer group need for Focus Plus?", "design_count"),
    ("How many sub-schemes are there under CM-ELEVATE?", "design_count"),
    ("what year did PMAY-G start and which ministry runs it?", "launch_admin"),
    ("When and where was Focus Plus launched, and how much does it pay?", "rate"),
    ("Is the Focus Legacy money a loan that must be repaid?", "loan_or_grant"),
])
def test_knowledge_forms_route_to_knowledge(q, form):
    assert p._knowledge_form_question(q) == form


@pytest.mark.parametrize("q", [
    "How much has Focus Plus paid in 2022-23?",
    "How many PMAY-G beneficiaries are registered in Ri Bhoi?",
    "How many CM Elevate applications in 2024?",
    "What was MGNREGA wage expenditure in West Garo Hills?",
    "How many producer groups got Focus Legacy money?",
    "How many members are there in Focus Legacy?",
    "How much did Focus Plus pay in East Garo Hills?",
    "how much has it paid in East Garo Hills?",
    "How many days of work did households get in Ri Bhoi?",
    "How much loan was sanctioned under CM Elevate Legacy?",
    "How many members are there in Bak-15 Wachal Pg?",
    "how many schemes does CM Elevate data have?",
    "what does each district get under focus plus?",
    "How many loans have been repaid?",
    "How many schemes run under CM Elevate?",
    "What extra fields does the Warehouse scheme record?",
    "How much does Focus Plus pay in total?",
])
def test_data_lookalikes_stay_data(q):
    assert p._knowledge_form_question(q) is None


def test_launch_question_is_not_a_years_of_data_list():
    assert not p._is_years_list_question("what year did PMAY-G start and which ministry runs it?")
    assert not p._is_years_list_question("In which year was MGNREGA launched?")
    assert p._is_years_list_question("Which financial years does PMAY-G have?")


def test_focus_acronym_question_names_the_focus_scheme():
    assert p._FOCUS_ACRONYM_ASK.search("What does FOCUS stand for, and is the money a loan?")
    assert p._FOCUS_ACRONYM_ASK.search("full form of focus")
    assert not p._FOCUS_ACRONYM_ASK.search("What is Focus?")


# ── KR3: multi-part questions ───────────────────────────────────────────────
def test_sub_asks_split_each_part():
    asks = rag._sub_asks("When and where was Focus Plus launched, and how much does it pay?")
    assert len(asks) == 2 and asks[0].startswith("When and where") and asks[1].startswith("how much")
    assert len(rag._sub_asks("When was PMAY-G launched, and what did it replace?")) == 2
    assert rag._sub_asks("How many days of work does MGNREGA guarantee?") == []
    assert rag._sub_asks("What is the difference between FOCUS and FOCUS+?") == []


def test_facet_queries_reach_the_related_facts_piece():
    qs = rag._facet_queries("When was CM Elevate launched, and what subsidy does it give?", "CM Elevate")
    assert any("launched" in q for q in qs) and any("sub-schemes" in q for q in qs)
    assert any("job card" in q for q in rag._facet_queries("How do I apply?", "MGNREGA"))
    assert rag._facet_queries("How do I apply?", None) == []


def test_related_facts_rule_follows_the_question():
    launch = rag._completeness_rule("When was PMAY-G launched?", [])
    assert "ministry" in launch and "how many sub-schemes" not in launch
    assert "job card" in rag._completeness_rule("How do I apply?", [], "MGNREGA")
    assert "job card" not in rag._completeness_rule("How do I apply?", [], "PMAY-G")


# ── KR11: Hinglish ──────────────────────────────────────────────────────────
def test_hinglish_is_recognised():
    assert rag._looks_hinglish("awas yojana gramin kab shuru hui?")
    assert rag._looks_hinglish("focus plus scheme kitna paisa deta hai")
    assert not rag._looks_hinglish("When was PMAY-G launched?")


# ── KR12: FAQ exact match ───────────────────────────────────────────────────
def _piece(heading, text="", doc="faq.md"):
    return {"heading": heading, "text": text, "doc": doc, "score": 0.6}


def test_faq_match_finds_the_entry_for_the_question():
    chunks = [_piece("1. Overview"), _piece('Is "Common Facility Centre (CFC)" a CM-ELEVATE scheme?')]
    assert rag._faq_match("Is Common Facility Centre part of CM Elevate?", chunks) == 1
    assert rag._faq_match("Is CFC a CM Elevate scheme?", chunks) == 1
    who = [_piece("What is CM-ELEVATE?"), _piece("Who is eligible for CM-ELEVATE?")]
    assert rag._faq_match("who are the intended benficiaries in cm elevate", who) == 1


def test_faq_match_ignores_a_one_word_overlap():
    chunks = [_piece("What documents are needed to apply for MGNREGA?"), _piece("How do I apply for a job card?")]
    assert rag._faq_match("How do I apply?", chunks) is None


# ── KR5: numbers and words checked against the passages ────────────────────
def test_numbers_must_be_in_the_passages():
    nums, stems = rag._passage_facts(["It was launched during 2021; some say March 2021, others September 2021."])
    assert rag._rag_unit_supported("FOCUS was launched in 2021, in March or September 2021.", nums, stems)
    assert rag._rag_unit_numbers("₹1,20,000 and 35%") == {"120000", "35"}
    assert rag._rag_unit_numbers("launched in 2019") - nums == {"2019"}


# ── KR4: citations are the pieces the answer uses ───────────────────────────
def test_citations_are_the_pieces_used():
    used = {"heading": "What is the unemployment allowance?", "doc": "faq.md",
            "text": "If work is not provided within 15 days, the state pays an unemployment allowance "
                    "of not less than one-fourth of the wage rate for the first 30 days."}
    unrelated = {"heading": "What happens if MGNREGA authorities delay wage payment?", "doc": "faq.md",
                 "text": "Workers are entitled to compensation for delayed payment of wages."}
    answer = ("If work is not provided within 15 days, the state pays an unemployment allowance of "
              "one-fourth of the wage rate for the first 30 days.")
    assert rag._supporting_chunks(answer, [unrelated, used]) == [used]


# ── KR9: next steps after a knowledge answer ────────────────────────────────
def test_knowledge_next_steps_end_with_one_data_question():
    from app import followups
    for scheme, data_q in followups._KNOWLEDGE_DATA_NEXT.items():
        opts = followups.build_followups("knowledge", "Who is eligible?", [scheme], {})
        assert opts and opts[-1]["question"] == data_q
        assert p._knowledge_form_question(data_q) is None      # the chip itself routes DATA


def test_definition_question_is_not_followed_by_a_what_is_chip():
    from app import followups
    opts = followups.build_followups("knowledge", "What does FOCUS stand for?", ["Focus Legacy"], {})
    assert not any(o["question"].lower().startswith("what is") for o in opts)


# ── KR3 backstop: the ministry of a launch answer, from the passages ───────
def test_launch_answer_gets_the_one_ministry_the_passages_name():
    chunks = [{"text": "Launched in 2016, implemented by the Ministry of Rural Development. The Union Cabinet "
                       "approved it."},
              {"text": "- **Ministry of Rural Development (MoRD):** The nodal central ministry."}]
    assert rag._passage_ministries(chunks) == {"Ministry of Rural Development"}
    out = rag._with_related_ministry("When was PMAY-G launched?", "PMAY-G was launched in 2016.", chunks)
    assert out.endswith("It is implemented by the Ministry of Rural Development.")
    # not for another kind of question, nor when the answer names one already
    assert rag._with_related_ministry("Who is eligible for PMAY-G?", "x", chunks) == "x"
    named = "Launched in 2016 by the Ministry of Rural Development."
    assert rag._with_related_ministry("When was PMAY-G launched?", named, chunks) == named


def test_faq_entry_dates_are_kept_in_the_answer():
    faq = [{"faq_match": True, "heading": 'Is "Common Facility Centre (CFC)" a CM-ELEVATE scheme?',
            "text": "It has been publicly announced as one (notified 11 March 2024). It does not, however, "
                    "appear among the 15 schemes in the curated application database."}]
    out = rag._with_faq_facts("Yes, CFC is part of CM-ELEVATE as one of its 15 sectors.", faq)
    assert "11 March 2024" in out
    assert rag._with_faq_facts("x", [dict(faq[0], faq_match=False)]) == "x"


def test_subscheme_count_is_added_once():
    ch = [{"text": "across 15 covered sectors - from livestock"},
          {"text": "Fifteen. Publicly announced sub-schemes include Piggery"}]
    assert rag._passage_subscheme_counts(ch) == {"15"}
    assert rag._with_subscheme_count("What subsidy does it give?", "35% to 75%.", ch).endswith(
        "The programme covers 15 sub-schemes.")
    assert rag._with_subscheme_count("What subsidy does it give?", "Across fifteen sectors.", ch) \
        == "Across fifteen sectors."
    assert rag._passage_subscheme_counts([{"text": "2 crore houses in 12 districts"}]) == set()


def test_a_records_count_is_not_the_programme_count():
    ch = [{"text": "8,823 applicant records across 13 sub-schemes"}, {"text": "across 15 covered sectors"}]
    assert rag._passage_subscheme_counts(ch) == {"15"}


def test_an_initial_does_not_end_a_sentence():
    units = rag.split_units("The Chief Minister is Conrad K. Sangma. He launched FOCUS+.")
    assert [u for _, u in units] == ["The Chief Minister is Conrad K. Sangma.", "He launched FOCUS+."]


def test_a_rule_question_about_a_named_scheme_overrules_a_scope_refusal():
    assert p._overrules_scope_verdict("How far from my home can MGNREGA work be given?")
    assert p._overrules_scope_verdict("How much does Focus Plus pay?")
    assert not p._overrules_scope_verdict("How far is Shillong from Guwahati?")
    assert not p._overrules_scope_verdict("Write a poem about how much MGNREGA pays")


def test_numbers_the_officer_spelt_out_may_be_repeated():
    q = "I am asking fifty lakh rupees for my house"
    assert rag._question_numbers(q) == {"50"}
    assert rag._rag_unit_numbers("not the ₹50 lakh you are asking for") <= rag._question_numbers(q)
