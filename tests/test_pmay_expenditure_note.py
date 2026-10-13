"""
"Total expenditure for MGNREGA" -> "give for pmay" (user report 2026-10-08).
PMAY-G records no expenditure; its nearest money figure is the amount
released. The answer must say that first instead of silently answering
"Amount released …". Real functions, no model / DB / VPN.
    .venv/Scripts/python.exe -m pytest tests/test_pmay_expenditure_note.py -q
"""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402

ANSWER = ("Amount released in Meghalaya (statewide), across all financial years "
          "(FY 2017-18 to FY 2023-24): ₹21,85,25,98,500.")


@pytest.mark.parametrize("q", [
    "what is the total expenditure for PMAY-G for all of Meghalaya across all financial years",
    "How much was spent under PMAY-G in West Garo Hills?",
    "PMAY-G spending in 2023-24",
])
def test_expenditure_question_says_pmay_has_no_expenditure(q):
    out = p._pmay_expenditure_not_held({"metrics": ["released"], "question": q}, ANSWER)
    assert out.startswith("PMAY-G does not record a total expenditure figure")
    assert out.endswith(ANSWER)           # the released figure is still given, unchanged


@pytest.mark.parametrize("spec", [
    {"metrics": ["released"], "question": "How much amount was released under PMAY-G?"},
    {"metrics": ["released"], "question": "Total amount disbursed for PMAY-G"},
    {"metrics": ["houses"], "question": "How many PMAY-G houses and what expenditure rules apply?"},
])
def test_other_pmay_questions_are_unchanged(spec):
    assert p._pmay_expenditure_not_held(spec, ANSWER) == ANSWER


def test_the_note_is_applied_where_the_pmay_answer_is_finalised():
    src = inspect.getsource(p)
    assert "_pm_answer = _pmay_expenditure_not_held(_pm_det, _pm_answer)" in src
