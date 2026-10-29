"""KI-435 / KI-436 — two MGNREGA Excel-sheet bugs (run 2026-10-27,
new_docs/MGNREGA_Excel_Test_Report_2026-10-27.md).

KI-435: "administrative SPEND in X block" matched no scheme, so the route gate said
"no usable administrative-expenditure figure in any scheme", while "administrative
expenditure" got MGNREGA's 0.00-with-note answer. Live 2026-10-29: both wordings now
give the same answer.

KI-436: "how many villages in AMPATHI AC had MGNREGA employment" counted every village
row (120; correct 114). The village-LIST guard covered only "which villages"; the new
count guard sends back a count that keeps zero-employment villages. Live 2026-10-29:
4/4 (Ampathi 114, Rangsakona 123 = megh_db).

OFFLINE: the real scheme inference and guard.
    .venv/Scripts/python.exe -m pytest tests/test_mgnrega_excel_bugs_2026_10_29.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402


@pytest.mark.parametrize("q", [
    "What was the administrative spend in Mawkyrwat block in FY 2023-24?",
    "admin spending in Dalu block",
    "administrative expenditure in Mawkyrwat block in FY 2023-24",
])
def test_every_administrative_wording_is_mgnrega(q):
    assert p._named_or_inferred_schemes(q) == ["MGNREGA"]


BAD = ("SELECT COUNT(DISTINCT geography_key) FROM curated.v_employment "
       "WHERE assembly_constituency_name = 'AMPATHI' AND year_key = 2023")


@pytest.mark.parametrize("q", [
    "How many villages in Ampathi constituency had MGNREGA employment in FY 2023-24?",
    "Number of villages in Ampathi assembly constituency with MGNREGA employment",
    "How many villages received employment in Ampathi constituency?",
])
def test_a_village_count_with_employment_must_drop_zero_rows(q):
    assert p._mgnrega_village_count_issue(q, ["MGNREGA"], BAD)
    assert p._mgnrega_village_count_issue(q, ["MGNREGA"], BAD + " AND persons_employed > 0") is None


def test_other_village_counts_are_left_alone():
    assert p._mgnrega_village_count_issue("How many villages are in Ampathi constituency?", ["MGNREGA"], BAD) is None
    assert p._mgnrega_village_count_issue("How many villages had employment?", ["PMAY-G"], BAD) is None
