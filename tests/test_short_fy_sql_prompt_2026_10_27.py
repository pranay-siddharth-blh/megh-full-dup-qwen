"""KI-431 (MGNREGA Excel sheet run, 2026-10-27): "How many households received employment in
Meghalaya in FY23?" ended in "couldn't build a working query". The year was resolved right
(FY 2022-23, year_key 2022), but the SQL model read "FY 23" as year_key = 2023; the year guard
then said the query "does not filter on" the year, and every repair kept 2023.
Fix: the SQL and repair prompts get each short FY form written out in full, and the guard names
the wrong year it found."""
import asyncio

import pytest

from app import context_policy, llm, prompt_builder
from app import pipeline as p

MG = ["MGNREGA"]


@pytest.mark.parametrize("text, out", [
    ("households in Meghalaya in FY23?", "households in Meghalaya in FY 2022-23?"),
    ("households in Meghalaya in FY 23?", "households in Meghalaya in FY 2022-23?"),
    ("person-days in FY'25", "person-days in FY 2024-25"),
    ("person-days in FY 23-24", "person-days in FY 2023-24"),
    ("in 23-24", "in FY 2023-24"),
    ("FY 24 and FY 25", "FY 2023-24 and FY 2024-25"),
    ("in FY 2023-24", "in FY 2023-24"),                       # long form untouched
    ("top 20 districts in 2024-25", "top 20 districts in 2024-25"),
    ("blocks with 30-31 villages", "blocks with 30-31 villages"),
])
def test_expand_short_fy(text, out):
    assert context_policy.expand_short_fy(text) == out


def _capture(monkeypatch, attr):
    seen = {}

    def fake(question, *a, **k):
        seen["q"] = question
        return "PROMPT"

    async def fake_llm(prompt):
        return "SELECT 1"
    monkeypatch.setattr(prompt_builder, attr, fake)
    monkeypatch.setattr(llm, "call_sql_generator", fake_llm)
    return seen


def test_the_sql_prompt_gets_the_full_year(monkeypatch):
    seen = _capture(monkeypatch, "build_sql_prompt")
    asyncio.run(p.generate_sql("How many households received employment in Meghalaya in FY 23?", MG,
                               {"resolved": {"year_key": 2022}}))
    assert "FY 2022-23" in seen["q"] and "FY 23?" not in seen["q"]


def test_the_repair_prompt_gets_the_full_year(monkeypatch):
    seen = _capture(monkeypatch, "build_repair_prompt")
    asyncio.run(p._repair_sql("How many households received employment in Meghalaya in FY23?", MG,
                              {"resolved": {"year_key": 2022}}, "SELECT 1", "err"))
    assert "FY 2022-23" in seen["q"]


SQL_WRONG = "SELECT SUM(households_employed) FROM curated.v_employment WHERE year_key = 2023"
SQL_NONE = "SELECT SUM(households_employed) FROM curated.v_employment"
ER = {"resolved": {"year_key": 2022}}


def test_the_guard_names_the_wrong_year():
    field, msg = p._resolved_scope_missing("households in Meghalaya in FY 23?", MG, ER, SQL_WRONG)
    assert field == "year" and "year_key = 2023 instead" in msg and "year_key = 2022" in msg


def test_the_guard_keeps_the_missing_year_wording():
    field, msg = p._resolved_scope_missing("households in Meghalaya in FY 23?", MG, ER, SQL_NONE)
    assert field == "year" and "does not filter on it" in msg


def test_the_right_year_passes():
    assert p._resolved_scope_missing("households in Meghalaya in FY 23?", MG, ER,
                                     SQL_WRONG.replace("2023", "2022")) is None


@pytest.mark.parametrize("sql, years", [
    (SQL_WRONG, {2023}),
    ("SELECT 1 FROM curated.v_employment WHERE e.year_key IN (2022, 2023)", {2022, 2023}),
    ("SELECT 1 FROM curated.v_employment WHERE 2024 = year_key", {2024}),
    (SQL_NONE, set()),
])
def test_year_key_literals(sql, years):
    assert p._vr_year_key_literals(sql) == years
