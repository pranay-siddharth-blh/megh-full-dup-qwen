"""KI-368 — "which village / what block" names the level being asked for, never the
place. "Which village has the highest number of households … in Demdema block" read
"village" as the stated level and resolved the VILLAGE Demdema (272799, no rows)
instead of the block (2/2 live runs 2026-10-22; reproduced 2026-10-27).

OFFLINE: calls the real `_explicit_level_in`.
    .venv/Scripts/python.exe -m pytest tests/test_which_level_ki368_2026_10_27.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402


@pytest.mark.parametrize("q,level", [
    ("Which village has the most households employed in Demdema block in FY 2023-24?", "block"),
    ("What village in Betasing block had the most person-days?", "block"),
    ("which district has the highest beneficiaries in Mawkyrwat block", "block"),
    ("In which block is Demdema village?", "village"),       # the place is the village
    ("How many households in Demdema village?", "village"),
    ("person-days in Demdema block", "block"),
    ("in each village of Betasing block", "block"),           # the older breakdown case
])
def test_the_asked_level_is_not_the_stated_level(q, level):
    assert p._explicit_level_in(q, ["MGNREGA"]) == level


def test_an_asked_level_alone_states_no_place_level():
    assert p._explicit_level_in("Which village had the most households in 2023-24?", ["MGNREGA"]) is None
