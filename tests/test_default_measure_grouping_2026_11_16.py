"""2026-11-16 (the user's live test): "Show me the breakdown by blocks of West Garo Hills" -> "MGNREGA" named no
measure, the catalogue declined and the model's SQL failed (a column the view does not have). A grouping of one scheme
with no measure named reads as the scheme's headline measure; anything else is unchanged."""
import pytest

from app import pipeline as p


@pytest.mark.parametrize("q,scheme,phrase", [
    ("Show me the breakdown by blocks of West Garo Hills for MGNREGA", "MGNREGA", "person-days"),
    ("PMAY-G by district", "PMAY-G", "houses sanctioned"),
    ("CMSS block-wise in East Khasi Hills", "CMSS", "applications"),
    ("Focus Plus district wise", "Focus Plus", "beneficiaries"),
])
def test_a_grouping_with_no_measure_names_the_headline_measure(q, scheme, phrase):
    out = p._c16_default_measure_question(q, scheme)
    assert out is not None and phrase in out and q in out


@pytest.mark.parametrize("q,scheme", [
    ("What is MGNREGA?", "MGNREGA"),                         # no grouping: not a breakdown
    ("MGNREGA in West Garo Hills", "MGNREGA"),               # a place, not a grouping
    ("CM Elevate Legacy by district", "CM Elevate Legacy"),  # two headline counts: left to the model / a question
])
def test_no_default_without_a_grouping_or_for_an_ambiguous_scheme(q, scheme):
    assert p._c16_default_measure_question(q, scheme) is None
