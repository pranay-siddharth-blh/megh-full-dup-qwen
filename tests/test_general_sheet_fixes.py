"""General sheet test run 2026-10-09 (Test Case Results - 30th Sep 26.xlsx):
regression tests for the nine failed cases, each against the real function."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import pipeline as p
from app import rag
from app.session_store import Turn


def _session(*turns):
    turns = list(turns)
    return SimpleNamespace(turns=turns, last_turn=turns[-1] if turns else None)


def _kturn(q, scheme):
    return Turn(question=q, raw_question=q, route="knowledge", schemes=[scheme])


# ── TC-001 / TC-016: six schemes, counted as six ────────────────────────────
@pytest.mark.parametrize("question", ["What schemes are available?", "what schemes do you have?"])
def test_tc001_listing_counts_six(question):
    ans = p._scheme_listing_answer(question)["answer"]
    assert ans.startswith("I cover eight ")          # CMSS 2026-11-11, Homestay 2026-11-12
    assert sum(1 for line in ans.splitlines() if line.startswith("- **")) == 8


def test_tc001_not_covered_reply_says_six():
    assert "I cover eight Meghalaya schemes" in p._knowledge_not_covered_answer("x", None)


# ── TC-005: Focus Legacy has its own how-to-apply entry ─────────────────────
def test_tc005_focus_legacy_faq_has_apply_steps():
    faq = (Path(__file__).resolve().parents[1] / "data" / "incoming" / "Focus_Legacy" / "FOCUS_LEGACY_FAQ.md").read_text(
        encoding="utf-8")
    assert "### 8a. How do I apply for FOCUS?" in faq


# ── TC-006 / TC-015: no internal-source wording; documents are composed ─────
@pytest.mark.parametrize("text,expected", [
    ("The provided reference material does not contain a helpline number.",
     "The published scheme information does not contain a helpline number."),
    ("The reference material does not specify a fixed date.",
     "The published scheme information does not specify a fixed date."),
    ("Dates are not given in the passages provided.",
     "Dates are not given in the published scheme information."),
    ("- the knowledge base has no list", "- The published scheme information has no list"),
])
def test_tc015_internal_sources_hidden(text, expected):
    assert rag._hide_internal_sources(text) == expected


def test_tc015_document_words_are_not_rewritten():
    text = "- **Proof of identity** — documents such as Aadhaar."
    assert rag._hide_internal_sources(text) == text


def test_tc015_not_covered_reply_never_names_reference_material():
    for s in ("MGNREGA", "CM Elevate Legacy", None):
        assert "reference material" not in p._knowledge_not_covered_answer("x", s)


@pytest.mark.parametrize("question", ["What documents are required?", "Documents?",
                                      "How can I apply?", "How do I apply for PMAY-G?"])
def test_tc006_list_questions_always_composed(question):
    assert rag._LIST_QUESTION.search(question)


def test_tc006_documents_rule_only_for_documents():
    assert rag._DOCS_QUESTION.search("What documents are required?")
    assert not rag._DOCS_QUESTION.search("How can I apply?")


# ── TC-007: "the two schemes" = the two schemes of the last turns ───────────
@pytest.mark.parametrize("a,b", [("Focus Plus", "Focus Legacy"), ("CM Elevate", "CM Elevate Legacy"),
                                 ("MGNREGA", "PMAY-G")])
def test_tc007_two_schemes_from_two_turns(a, b):
    s = _session(_kturn(f"What is {a}?", a), _kturn(f"What is {b}?", b))
    prev = p._recent_compared_schemes(s)
    assert prev == [a, b]
    out = p._scheme_comparison_answer("What is the difference between the two schemes?", prev)
    assert out and f"**{a}**" in out["answer"] and f"**{b}**" in out["answer"]


def test_tc007_one_scheme_still_asks():
    s = _session(_kturn("What is MGNREGA?", "MGNREGA"))
    with pytest.raises(p.ClarificationNeeded):
        p._scheme_comparison_answer("What is the difference between the two schemes?",
                                    p._recent_compared_schemes(s))


# ── TC-010: entitlement questions are KNOWLEDGE ─────────────────────────────
@pytest.mark.parametrize("question", ["How many days of work are guaranteed?", "How are wages paid?",
                                      "How much assistance is given?",
                                      "How much amount is given per house under PMAY-G?"])
def test_tc010_entitlement_questions(question):
    assert p._is_entitlement_question(question)


@pytest.mark.parametrize("question", [
    "How much assistance was given in Ri Bhoi in 2023-24?",
    "How many households completed 100 days of guaranteed employment in East Khasi Hills?",
    "total MGNREGA person-days in Ri Bhoi",
    "How much subsidy is disbursed under CM Elevate Legacy?",
])
def test_tc010_figures_stay_data(question):
    assert not p._is_entitlement_question(question)


# ── TC-011 / TC-012: model scope verdicts that are overruled ────────────────
@pytest.mark.parametrize("question", ["How do I get this?", "How can I apply for it?",
                                      "What is PM-KISAN?", "Tell me about the Jal Jeevan Mission scheme"])
def test_tc011_tc012_scope_verdict_overruled(question):
    assert p._overrules_scope_verdict(question)


@pytest.mark.parametrize("question", ["apply for PMAY-G for me", "Who won the last IPL final?",
                                      "write an Instagram post on MGNREGA"])
def test_tc011_real_out_of_scope_stands(question):
    assert not p._overrules_scope_verdict(question)


def test_tc022_short_followup_overruled_only_with_context():
    assert p._overrules_scope_verdict("And the lowest?", has_context=True)
    assert not p._overrules_scope_verdict("And the lowest?", has_context=False)


# ── TC-022: which year / year-wise ──────────────────────────────────────────
def test_tc022_which_year_question_skips_year_pause():
    q = "For the village ABAGRE under the MGNREGA scheme, which year had the highest expenditure?"
    assert not p._needs_year_clarification(q, ["MGNREGA"], {})
    assert p._needs_year_clarification("What is the total MGNREGA expenditure for the village ABAGRE?",
                                       ["MGNREGA"], {})


@pytest.mark.parametrize("reply,ok", [("Show it year-wise", True), ("by year please", True),
                                      ("each year", True), ("show person-days year-wise", False),
                                      ("2023-24", False)])
def test_tc022_yearwise_reply(reply, ok):
    assert p._is_yearwise_reply(reply) is ok


def test_tc022_scoped_top_year_is_not_called_statewide():
    sql = ("SELECT financial_year_short, SUM(total_exp) AS t FROM curated.v_expenditure "
           "WHERE village_code = 273035 GROUP BY 1 ORDER BY t DESC LIMIT 1")
    ans = "2024-25 had the highest expenditure of 20.33 lakh. No other years are available in the result."
    out = p._mgnrega_top_one_wording(ans, sql, [{"financial_year_short": "2024-25", "t": 20.33}])
    assert out == "2024-25 had the highest expenditure of 20.33 lakh."
