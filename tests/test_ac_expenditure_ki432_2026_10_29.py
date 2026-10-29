"""KI-432 — MGNREGA constituency EXPENDITURE.

MGNREGA Excel sheet run 2026-10-27: 0/10. The SQL prompt said the constituency column
"exists ONLY in mgnrega_employment … say that level isn't available" for expenditure,
written before v_expenditure got ac_name (title case 'Amlarem'). The model gave up,
or a repair dropped the filter and the STATEWIDE total was answered as Amlarem's.
Now the prompt names v_expenditure.ac_name, and _resolved_scope_missing rejects SQL
that leaves out a resolved constituency. Live 2026-10-29: 0/4 -> 4/4 (Amlarem FY
2023-24 1,090.03 lakh; Mawkyrwat 35.26 crore = 3,526.39 lakh, both = megh_db).

OFFLINE: the real prompt_builder._entities_block and _resolved_scope_missing.
    .venv/Scripts/python.exe -m pytest tests/test_ac_expenditure_ki432_2026_10_29.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p, prompt_builder as pb  # noqa: E402

ER = {"resolved": {"assembly_constituency": "AMLAREM", "year_key": 2023}}
Q = "MGNREGA expenditure in Amlarem constituency in FY 2023-24"


def test_the_prompt_names_the_expenditure_column():
    block = pb._entities_block(ER, Q, ["MGNREGA"])
    assert "UPPER(ac_name) = UPPER('AMLAREM')" in block
    assert "UPPER(assembly_constituency_name) = UPPER('AMLAREM')" in block
    assert "isn't available" not in block


@pytest.mark.parametrize("sql,bad", [
    ("SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE year_key = 2023", True),
    ("SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE UPPER(ac_name) = UPPER('AMLAREM') "
     "AND year_key = 2023", False),
    ("SELECT SUM(person_days) FROM curated.v_employment WHERE UPPER(assembly_constituency_name) = 'AMLAREM' "
     "AND year_key = 2023", False),
    ("SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'WEST JAINTIA HILLS' "
     "AND year_key = 2023", True),
])
def test_a_query_without_the_constituency_is_sent_back(sql, bad):
    hit = p._resolved_scope_missing(Q, ["MGNREGA"], ER, sql)
    assert bool(hit) is bad
    if bad:
        assert hit[0] == "assembly_constituency" and "ac_name" in hit[1]
