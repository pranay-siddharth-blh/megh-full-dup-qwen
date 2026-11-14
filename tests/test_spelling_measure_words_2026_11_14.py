"""Spelling, 14 Nov 2026: the measure and grouping words people mistype most are in the closed vocabulary
(data/spelling_aliases.yaml `words`), and the real English words one or two edits from them are listed under
`not_typos`, so they are never "corrected". Offline (the place gazetteer is read from the local catalogue)."""
from __future__ import annotations

import pytest

from app import spelling as sp


@pytest.fixture(autouse=True, scope="module")
def _fresh():
    sp.reload()
    sp.warm()


@pytest.mark.parametrize("typed,want", [
    ("focus pluss totel amount disbursd", "Focus Plus total amount disbursd"),    # no-model bank PF-FP-misspelt
    ("focus legasy amount remited 2024-25", "Focus Legacy amount remitted 2024-25"),   # PF-FL-misspelt
    ("mgnrega persondays by distrct", "mgnrega persondays by district"),
    ("highst houses in ri bhoi", "highest houses in ri bhoi"),
    ("cmss studnets paid", "cmss students paid"),
    ("pmay houses by vilage in 2023-24", "pmay houses by village in 2023-24"),
    ("percentge of women", "percentage of women"),
    ("mgnrega by constituncy", "mgnrega by constituency"),
])
def test_measure_and_grouping_typos(typed, want):
    assert sp.normalise(typed).text == want


@pytest.mark.parametrize("q", [
    "what about the tonal", "distinct values", "votes in the vintage", "the longest road", "a refitted car",
    "it generates", "the villain", "spend money", "is it totally done", "the blocks are black",
    "what is the total", "show it by district", "the total for each village", "give me the lowest",
])
def test_real_words_are_never_corrected(q):
    assert sp.normalise(q).text == q


def test_every_not_typo_is_a_word_not_in_the_vocabulary():
    a = sp._aliases()
    assert a["not_typos"] and not (a["not_typos"] & set(a["words"]))
