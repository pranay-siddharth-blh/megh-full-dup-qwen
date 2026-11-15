"""Spelling, 15 Nov 2026: real words one edit from the measure vocabulary are never 'corrected'.
'applications were sent back' had become 'spent back' and was asked as money (model-on gold bank W2-CE-SB-01)."""
import pytest

from app import spelling as sp


@pytest.fixture(autouse=True, scope="module")
def _fresh():
    sp.reload()
    sp.warm()


@pytest.mark.parametrize("q", [
    "How many CM Elevate applications were sent back in West Garo Hills?",
    "send it again", "money spent in Ri Bhoi", "the relieved officers", "holiday villas", "it lowers the count",
])
def test_real_words_stay(q):
    assert sp.normalise(q).text == q


def test_spent_is_no_longer_a_correction_target():
    assert "spent" not in sp._aliases()["words"]
