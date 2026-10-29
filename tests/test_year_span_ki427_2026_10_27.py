"""KI-427 — a stated span of financial years ("from A to B", "A through B",
"between A and B") resolves to EVERY year in it, not only the last one the
extractor hands back; KI-441 — a trend answer's movement verb follows the data.

Live 2026-10-27 (own wordings, not the held-out set): "each financial year from
2021-22 to 2024-25" in Ri Bhoi resolved year_key 2024 and the SQL filtered that one
year 3 runs out of 3; FY 2021-22 (not held by MGNREGA) was stripped to "from to
2024-25". After the fix: year_key_list [2022, 2023, 2024], BETWEEN 2022 AND 2024,
3/3. The composed trend then said "rose from 1,212,513 … to 928,817".

OFFLINE: every test calls the real function.
    .venv/Scripts/python.exe -m pytest tests/test_year_span_ki427_2026_10_27.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p, prompt_builder as pb  # noqa: E402


@pytest.mark.parametrize("q,span", [
    ("job cards in Ri Bhoi in each financial year from 2021-22 to 2024-25", (2021, 2024)),
    ("houses built between 2019-20 and 2022-23, year by year", (2019, 2022)),
    ("expenditure from FY 2020-21 through FY 2023-24", (2020, 2023)),
    ("person-days from FY23 to FY25", (2022, 2024)),
    ("person-days 2022-23 up to 2024-25", (2022, 2024)),
    ("person-days for 2022-23 and 2024-25", None),          # two years, not a span
    ("compare 2022-23 with 2024-25", None),
    ("person-days in 2023-24", None),
    ("person-days from 2024-25 to 2022-23", None),          # backwards: not read as a span
])
def test_stated_span(q, span):
    assert p._c09_stated_year_span(q) == span


def test_a_span_end_the_scheme_lacks_is_clamped_not_dropped():
    q = "job cards in Ri Bhoi in each financial year from 2021-22 to 2024-25"
    new_q, note, handled = p._apply_year_gap(q, ["MGNREGA"])
    assert handled
    assert p._c09_stated_year_span(new_q) == (2022, 2024)
    assert "range uses FY 2022-23" in note
    # a plain two-year question still drops the year it cannot answer
    new_q, note, _ = p._apply_year_gap("job cards in Ri Bhoi for 2021-22 and 2024-25", ["MGNREGA"])
    assert "2021-22" not in new_q and "left out" in note


def test_the_prompt_names_every_year_of_the_span():
    block = pb._entities_block({"resolved": {"district": "RI BHOI", "year_key_list": [2022, 2023, 2024]}},
                               "", ["MGNREGA"])
    assert "year_key BETWEEN 2022 AND 2024" in block
    block = pb._entities_block({"resolved": {"year_key_list": [2022, 2024]}}, "", ["MGNREGA"])
    assert "year_key IN (2022, 2024)" in block


Q = "person-days in Ri Bhoi in each financial year from 2022-23 to 2024-25"
ER = {"resolved": {"district": "RI BHOI", "year_key_list": [2022, 2023, 2024]}}
BASE = "SELECT year_key, SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND "


@pytest.mark.parametrize("where,bad", [
    ("year_key = 2024 GROUP BY year_key", True),
    ("year_key BETWEEN 2022 AND 2024 GROUP BY year_key", False),
    ("year_key IN (2022, 2023, 2024) GROUP BY year_key", False),
    ("financial_year_short BETWEEN '2022-23' AND '2024-25' GROUP BY 1", False),
    ("year_key BETWEEN 2023 AND 2024 GROUP BY year_key", True),
])
def test_the_guard_rejects_sql_that_leaves_out_part_of_the_span(where, bad):
    hit = p._resolved_scope_missing(Q, ["MGNREGA"], ER, BASE + where)
    assert bool(hit) is bad
    if bad:
        assert hit[0] == "year" and "BETWEEN 2022 AND 2024" in hit[1]


# ── KI-441: the trend's movement verb ───────────────────────────────────────
TREND_SQL = ("SELECT year_key, financial_year, SUM(person_days) AS person_days FROM curated.v_employment "
             "WHERE lgd_district = 'RI BHOI' AND year_key BETWEEN 2022 AND 2024 "
             "GROUP BY year_key, financial_year ORDER BY year_key")
FALLING = [{"year_key": 2022, "financial_year": "2022-23", "person_days": 1212513},
           {"year_key": 2023, "financial_year": "2023-24", "person_days": 1100000},
           {"year_key": 2024, "financial_year": "2024-25", "person_days": 928817}]


def _shape(rows):
    shape = p._answer_shape("person-days in Ri Bhoi each year from 2022-23 to 2024-25", TREND_SQL, rows)
    assert shape is not None and shape.kind == "trend"
    return shape


def test_a_fall_written_as_a_rise_is_corrected():
    ans = "MGNREGA person-days in Ri Bhoi rose from 1,212,513 in FY 2022-23 to 928,817 in FY 2024-25."
    out = p._c12s_fix_trend_direction(ans, _shape(FALLING), FALLING)
    assert out.startswith("MGNREGA person-days in Ri Bhoi fell from 1,212,513")


def test_a_rise_written_as_a_fall_is_corrected_and_a_right_verb_is_kept():
    rising = list(reversed([dict(r, year_key=r["year_key"]) for r in FALLING]))
    for r, y in zip(rising, (2022, 2023, 2024)):
        r["year_key"], r["financial_year"] = y, f"{y}-{(y + 1) % 100:02d}"
    ans = "Person-days fell from 928,817 in FY 2022-23 to 1,212,513 in FY 2024-25."
    assert p._c12s_fix_trend_direction(ans, _shape(rising), rising).startswith("Person-days rose from")
    ok = "Person-days fell from 1,212,513 to 928,817; they rose from 1,100,000 in one block."
    assert p._c12s_fix_trend_direction(ok, _shape(FALLING), FALLING) == ok


# ── KI-411: an all-years total split by two names of the year ───────────────
@pytest.mark.parametrize("group,year_only", [
    ("GROUP BY year_key", True),
    ("GROUP BY year_key, financial_year_short", True),       # the split that passed
    ("GROUP BY financial_year, year_key", True),
    ("GROUP BY lgd_block, year_key", False),
])
def test_a_split_by_several_year_columns_is_year_only(group, year_only):
    sql = ("SELECT year_key, financial_year_short, COUNT(*) AS houses FROM curated.v_pmay "
           f"WHERE lgd_district = 'RI BHOI' {group}")
    assert p._vr_grouped_by_year_only(sql) is year_only


def test_the_combined_figure_question_is_not_a_split_request():
    q = "Total PMAY-G houses sanctioned in Ri Bhoi, counting every financial year"
    assert p._ALL_YEARS_CUE.search(q) and not p._YEAR_SPLIT_ASKED.search(q)
