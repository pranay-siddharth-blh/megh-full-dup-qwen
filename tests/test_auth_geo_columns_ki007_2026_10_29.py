"""KI-007 (security) — authorization reads every place column, not just lgd_*.

auth.authorize read only lgd_district / lgd_block. A district officer's "Focus Plus
in Dalu block" (Dalu is in West Garo Hills) filters block_name_raw, so it read as a
statewide query with no place and was allowed; a constituency filter
(assembly_constituency_name / ac_name) was invisible too. Now district_name_raw /
block_name_raw count as district / block filters, and a restricted account may read
a constituency only together with a district it holds (8 of 56 constituencies span
two districts).

OFFLINE: the real authorize with a real UserScope.
    .venv/Scripts/python.exe -m pytest tests/test_auth_geo_columns_ki007_2026_10_29.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import auth, scheme_registry  # noqa: E402

EKH = auth.UserScope(user_id="ekh-do", role="district_officer", granularity_cap="block",
                     schemes=list(scheme_registry.NAMES),
                     geographies={"districts": ["EAST KHASI HILLS"], "blocks": []},
                     name="EKH officer", tenant_id=1, db_user_id=42, username="ekh-do")


def _ok(sql, resolved=None, schemes=("Focus Plus",)):
    return auth.authorize(EKH, schemes=list(schemes), resolved_entities=resolved or {}, sql=sql).allow


@pytest.mark.parametrize("sql", [
    "SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = 'DALU'",
    "SELECT COUNT(*) FROM curated.v_focus_plus WHERE district_name_raw = 'WEST GARO HILLS'",
])
def test_another_districts_place_through_a_raw_column_is_refused(sql):
    assert not _ok(sql)


def test_own_district_through_a_raw_column_is_allowed():
    assert _ok("SELECT COUNT(*) FROM curated.v_focus_plus WHERE district_name_raw = 'EAST KHASI HILLS'")


def test_a_constituency_needs_the_officers_district_too():
    alone = ("SELECT SUM(person_days) FROM curated.v_employment "
             "WHERE UPPER(assembly_constituency_name) = 'TURA'")
    assert not _ok(alone, {"assembly_constituency": "TURA"}, ("MGNREGA",))
    assert not _ok("SELECT SUM(total_exp) FROM curated.v_expenditure WHERE UPPER(ac_name) = 'MYLLIEM'",
                   schemes=("MGNREGA",))
    both = alone.replace("WHERE", "WHERE lgd_district = 'EAST KHASI HILLS' AND")
    assert _ok(both, {"assembly_constituency": "TURA", "district": "EAST KHASI HILLS"}, ("MGNREGA",))


def test_granularity_sees_the_raw_and_constituency_columns():
    assert auth.infer_granularity({}, "SELECT 1 FROM curated.v_focus_plus WHERE block_name_raw = 'X'") == "block"
    assert auth.infer_granularity({}, "SELECT 1 FROM curated.v_expenditure WHERE ac_name = 'X'") == "block"
