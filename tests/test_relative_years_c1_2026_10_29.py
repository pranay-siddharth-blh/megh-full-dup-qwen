"""C1 (RAG plan, 2026-10-29): relative years in a fresh question.

Live before the fix: "MGNREGA person-days last year", "Focus Legacy producer groups
last year" and "PMAY-G houses completed in the last 3 years" were answered for ALL
years; "... in Ri Bhoi in the previous financial year" failed. The phrase is now
replaced with the FY it means, anchored on the latest FY the scheme holds
(_c06_relative_year_rewrite, called by _data_entity_stage), with a composer note.
Also: a FY in the question is no longer read as an assumed figure (premise_check).

OFFLINE: the real functions; scheme years and resolve_entities faked.
    .venv/Scripts/python.exe -m pytest tests/test_relative_years_c1_2026_10_29.py -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p, premise_check  # noqa: E402

_YEARS = {"MGNREGA": ["2022-23", "2023-24", "2024-25", "2025-26"],
          "PMAY-G": ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24"],
          "Focus Legacy": ["2021-22", "2022-23", "2024-25", "2025-26"],
          "CM Elevate": []}


@pytest.fixture(autouse=True)
def years(monkeypatch):
    for s, ys in _YEARS.items():
        monkeypatch.setitem(p._SCHEME_DATA_YEARS, s, ys)


@pytest.mark.parametrize("scheme,q,expected", [
    ("MGNREGA", "How many person-days were generated under MGNREGA last year?",
     "How many person-days were generated under MGNREGA in FY 2024-25?"),
    ("MGNREGA", "MGNREGA person-days in Ri Bhoi in the previous financial year",
     "MGNREGA person-days in Ri Bhoi in FY 2024-25"),
    ("MGNREGA", "MGNREGA total expenditure this year in East Khasi Hills",
     "MGNREGA total expenditure in FY 2025-26 in East Khasi Hills"),
    ("MGNREGA", "top 5 blocks by person-days over the last two years",
     "top 5 blocks by person-days from FY 2024-25 to FY 2025-26"),
    ("PMAY-G", "How many PMAY-G houses were completed in the last 3 years?",
     "How many PMAY-G houses were completed from FY 2021-22 to FY 2023-24?"),
    ("PMAY-G", "PMAY-G houses sanctioned in the current FY", "PMAY-G houses sanctioned in FY 2023-24"),
    ("Focus Legacy", "Focus Legacy producer groups last year", "Focus Legacy producer groups in FY 2024-25"),
])
def test_a_relative_year_becomes_the_fy_it_means(scheme, q, expected):
    out, note = p._c06_relative_year_rewrite(q, [scheme])
    assert out == expected
    assert note and "Say which financial year" in note and scheme in note


@pytest.mark.parametrize("scheme,q", [
    ("MGNREGA", "MGNREGA person-days in FY 2023-24 vs last year"),   # a year is named: the user's
    ("MGNREGA", "person-days next year"),                            # no data
    ("MGNREGA", "which was the last village added?"),                # not a year
    ("MGNREGA", "How many person-days across all financial years?"),
    ("CM Elevate", "CM Elevate applications last year"),             # no years known
])
def test_left_alone(scheme, q):
    assert p._c06_relative_year_rewrite(q, [scheme]) == (q, None)


def test_the_entity_stage_reads_the_rewritten_question(monkeypatch):
    seen = {}

    async def resolve(question, schemes, **_kw):
        seen["q"] = question
        return {"resolved": {"year_key": 2024}, "notes": []}
    monkeypatch.setattr(p, "resolve_entities", resolve)
    monkeypatch.setattr(p, "acronym_near_misses", lambda q: [])
    d = {"question": "MGNREGA person-days last year", "schemes": ["MGNREGA"], "prior_resolved": None,
         "village_hint": None, "cross": None, "pre_rephrase_question": None}
    assert asyncio.new_event_loop().run_until_complete(p._data_entity_stage(d)) is None
    assert seen["q"] == d["question"] == "MGNREGA person-days in FY 2024-25"
    assert any("last year" in n for n in d["entity_result"]["notes"])


@pytest.mark.parametrize("q", [
    "How many PMAY-G houses were completed from FY 2021-22 to FY 2023-24?",
    "How many PMAY-G houses were completed from 2021-22 to 2023-24?",
])
def test_a_financial_year_is_not_an_assumed_figure(q):
    assert premise_check.extract_premises(q) == []


def test_a_stated_figure_is_still_a_premise():
    got = premise_check.extract_premises("Is it true that 900 houses were completed in FY 2021-22?")
    assert [g.value for g in got] == [900.0]
