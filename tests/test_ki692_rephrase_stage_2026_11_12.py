"""KI-723 (2026-11-12): the rephraser may not add a stage the user never named.

"PMAY-G houses by block in East Khasi Hills" came back "How many PMAY-G houses were built by block in East Khasi
Hills?"; "built" is a completed-house word, so every block was answered with its completed count. A rephrase that adds
a stage word (built / completed / sanctioned / released / ...) is rejected and the original question goes on; the same
stage in another form ("sanction" -> "sanctioned") is kept.
"""
import pytest

from app import pipeline as p


@pytest.mark.parametrize("original, rephrased", [
    ("PMAY-G houses by block in East Khasi Hills", "How many PMAY-G houses were built by block in East Khasi Hills?"),
    ("PMAY-G houses in Ri Bhoi", "How many PMAY-G houses were completed in Ri Bhoi?"),
    ("CM Elevate applications by district", "How many CM Elevate applications were approved by district?"),
    ("Focus Plus beneficiaries in West Garo Hills", "How many Focus Plus beneficiaries were disbursed in West Garo Hills?"),
])
def test_a_rephrase_that_adds_a_stage_is_rejected(original, rephrased):
    assert p._rephrase_violation(original, rephrased) == "measure"


@pytest.mark.parametrize("original, rephrased", [
    ("pmay mein kitne ghar sanction hue ri bhoi 2022-23", "How many PMAY-G houses were sanctioned in ri bhoi in FY 2022-23?"),
    ("PMAY-G houses completed by block in East Khasi Hills",
     "How many PMAY-G houses were completed in each block of East Khasi Hills?"),
])
def test_the_same_stage_in_another_form_is_kept(original, rephrased):
    assert p._rephrase_violation(original, rephrased) is None
