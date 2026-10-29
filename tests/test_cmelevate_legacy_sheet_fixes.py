"""CM Elevate Legacy sheet test run 2026-10-12 (Test Case Results - 30th Sep 26.xlsx, TC-01..TC-36):
regression tests for the failures, against the real functions."""
import pytest

from app import pipeline as p


# ── the user's decision (2026-10-22, replacing 2026-10-19 and 2026-10-12): a bare
# "CM-ELEVATE" with a financial word is CM Elevate Legacy, directly; with only
# "applications" (held by both datasets) it asks which dataset — the sheet's TC-11/26
# were answered 8,840 from the applications data for a Legacy 2,823. ──
@pytest.mark.parametrize("q", ["How many CM-ELEVATE records are there in each district?",
                               "Give me a district-wise summary for CM-ELEVATE"])
def test_cm_elevate_questions_without_dataset_words_ask_which_dataset(q):
    assert p._pin_cm_elevate_dataset(q) == q
    assert p._cm_elevate_dataset_choice(q) == "ask"


# User decision 2026-10-29 (D-090): "applications" settles the applications dataset.
@pytest.mark.parametrize("q", ["How many total applications are recorded under CM-ELEVATE?",
                               "How many CM-ELEVATE applications are recorded in each district?",
                               "Which districts have the highest number of CM-ELEVATE applications?",
                               "How many CM-ELEVATE applications are mapped to Amlarem constituency?",
                               "Show me the number of CM-ELEVATE applications in each block of West Garo Hills."])
def test_cm_elevate_applications_questions_are_the_applications_dataset(q):
    assert p._pin_cm_elevate_dataset(q) == q
    assert p._cm_elevate_dataset_choice(q) == "applications"


@pytest.mark.parametrize("q", ["What is the total amount disbursed under CM Elevate?",
                               "How many applications have been sanctioned under CM-ELEVATE?",
                               "Compare the number of sanctioned CM-ELEVATE applications across West Garo Hills "
                               "and Ri Bhoi."])
def test_bare_cm_elevate_with_a_financial_word_is_legacy(q):
    assert "CM Elevate Legacy" in p._pin_cm_elevate_dataset(q)
    assert p._cm_elevate_dataset_choice(q) == "legacy"


@pytest.mark.parametrize("q", ["How many CM ELEVATE applicants are there in East Khasi Hills?",
                               "How many CM ELEVATE applications are pending at level 1?",
                               "What is the current application status distribution across CM ELEVATE?",
                               "How many applications are currently on hold under CM Elevate?",
                               "How many applications under Piggery scheme are currently sent back in Ri Bhoi?",
                               "What is the CM-ELEVATE programme in Meghalaya?"])
def test_applications_vocabulary_and_knowledge_stay_on_cm_elevate(q):
    assert "CM Elevate Legacy" not in p._pin_cm_elevate_dataset(q)


# ── "who are the intended beneficiaries" is a knowledge question (TC-03) ──
def test_who_benefits_is_knowledge():
    assert p._WHO_BENEFITS_MATCH.search("Who are the intended beneficiaries of CM-ELEVATE?")
    assert p._WHO_BENEFITS_MATCH.search("Who can apply under CM Elevate?")
    assert not p._WHO_BENEFITS_MATCH.search("How many beneficiaries are there in Ri Bhoi?")


# ── a breakdown that asks for applications first is ranked by applications (TC-26 / TC-36) ──
def test_order_by_records_when_applications_asked_first():
    sql = ("SELECT COALESCE(lgd_district, 'ALL DISTRICTS') AS lgd_district, COUNT(*) AS records, "
           "ROUND(SUM(total_disbursement)/1e7,2) AS total_disbursed_cr FROM curated.v_cm_elevate_disbursement "
           "GROUP BY ROLLUP (lgd_district) ORDER BY GROUPING(lgd_district), total_disbursed_cr DESC")
    out = p._cm_legacy_order_by_records("Give me a district-wise summary of applications, sanctioned cases and "
                                        "total disbursement under CM-ELEVATE.", ["CM Elevate Legacy"], sql)
    assert out.endswith("ORDER BY GROUPING(lgd_district), records DESC")
    money_first = "What is the total disbursement and number of applications for each district?"
    assert p._cm_legacy_order_by_records(money_first, ["CM Elevate Legacy"], sql) == sql
    assert p._cm_legacy_order_by_records("x applications", ["CM Elevate"], sql) == sql


# ── the name before "village" survives the rephraser whole and in order (all-villages run) ──
def test_rephrase_keeps_village_name_order():
    assert p._rephrase_violation(
        "What is the total CM Elevate Legacy disbursement amount for kyrdemkulai 6 km village?",
        "What is the total disbursement amount under CM Elevate Legacy for 6 km village in kyrdemkulai?") \
        == "name:village"
    assert p._rephrase_violation(
        "How many cm elevate legacy applications are recorded in kyrdemkulai 6 km village?",
        "How many CM Elevate Legacy applications are recorded in kyrdemkulai 6 km village?") is None
