"""Gate 2 (2026-11-16): a question resumed from a scheme pick that asks a breakdown stays DATA (the classifier once sent
"a breakdown of CMSS applications by blocks of Ri Bhoi" to the documents)."""
import pytest

from app import pipeline as p


@pytest.mark.parametrize("q", ["a breakdown of CMSS applications by blocks of Ri Bhoi",
                               "Show me the breakdown by blocks of West Garo Hills for MGNREGA",
                               "PMAY-G houses sanctioned by district", "Focus Plus beneficiaries block-wise"])
def test_grouping_questions_are_recognised(q):
    assert p._c14_resumed_grouping(q)


@pytest.mark.parametrize("q", ["Who is eligible for CMSS?", "What documents are required to apply for Homestay?",
                               "How do I apply for PMAY-G in West Garo Hills?"])
def test_knowledge_questions_are_not(q):
    assert not p._c14_resumed_grouping(q)
