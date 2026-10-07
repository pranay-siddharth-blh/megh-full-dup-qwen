"""Only the years / places a scheme actually has data for (reported 2026-10-06).

"give me financial years in MGNREGA" was answered "42 distinct financial years
... 1984-85 through 2023-24": the SQL model read curated.dim_year, the shared
calendar, not MGNREGA's data (FY 2022-23 to 2025-26). Two guards:
  * _scheme_years_answer (scope_scheme): the list from _SCHEME_DATA_YEARS,
    loaded from each scheme's own views, with no model call;
  * _sql_dimension_only_issue (execute_attempt): a query reading only the
    shared calendar / place registries is rejected for repair.
"""
import asyncio
import inspect

import pytest

from app import pipeline as p


@pytest.fixture(autouse=True)
def _verified_years(monkeypatch):
    # the verified defaults (refresh_scheme_years replaces them from the DB live)
    monkeypatch.setattr(p, "_SCHEME_DATA_YEARS", {
        "MGNREGA": ["2022-23", "2023-24", "2024-25", "2025-26"],
        "PMAY-G": ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"],
        "Focus Plus": ["2022-23", "2025-26"],
        "CM Elevate": [],
        "Focus Legacy": ["2021-22", "2022-23", "2024-25", "2025-26"],
        "CM Elevate Legacy": ["2024-25", "2025-26"],
    })


def test_reported_question_lists_only_mgnrega_years():
    r = p._scheme_years_answer("So, give me financial years in MGNREGA.", ["MGNREGA"])
    assert r is not None and r["route"] == "data"
    assert r["answer"] == ("MGNREGA data covers 4 financial years: FY 2022-23, FY 2023-24, "
                           "FY 2024-25 and FY 2025-26.")
    assert [row["financial_year"] for row in r["rows"]] == ["2022-23", "2023-24", "2024-25", "2025-26"]
    assert "1984" not in r["answer"] and "dim_year" not in (r["sql"] or "")
    assert "curated.v_employment" in r["sql"]


@pytest.mark.parametrize("question,schemes,expect", [
    ("Which years of data are available for PMAY-G?", ["PMAY-G"], "PMAY-G data covers 7 financial years"),
    ("What financial years does Focus Legacy cover?", ["Focus Legacy"],
     "There is no Focus Legacy data for FY 2023-24 (an absent year, not a zero one)."),
    ("How many financial years in Focus Plus?", ["Focus Plus"],
     "There is no Focus Plus data for FY 2023-24 and FY 2024-25 (absent years, not zero ones)."),
    ("financial years in CM Elevate", ["CM Elevate"], "CM Elevate records no financial year at all"),
    ("fys for CM Elevate Legacy", ["CM Elevate Legacy"],
     "The two Sericulture schemes' records carry no financial year."),
])
def test_every_scheme_answers_from_its_own_years(question, schemes, expect):
    r = p._scheme_years_answer(question, schemes)
    assert r is not None and expect in r["answer"]


def test_two_schemes_get_one_line_each():
    r = p._scheme_years_answer("financial years for MGNREGA and PMAY-G", ["MGNREGA", "PMAY-G"])
    assert r["answer"].count("\n") == 1 and {row["scheme"] for row in r["rows"]} == {"MGNREGA", "PMAY-G"}


@pytest.mark.parametrize("question,schemes", [
    ("Total MGNREGA person-days by financial year", ["MGNREGA"]),
    ("How many houses per financial year under PMAY-G", ["PMAY-G"]),
    ("MGNREGA expenditure in financial year 2023-24", ["MGNREGA"]),
    ("Compare Focus Plus disbursed across financial years", ["Focus Plus"]),
    ("How many Focus Legacy payments in each financial year?", ["Focus Legacy"]),
    ("Which financial year had the highest PMAY-G sanctions?", ["PMAY-G"]),
])
def test_a_figure_per_year_is_still_a_data_question(question, schemes):
    assert p._scheme_years_answer(question, schemes) is None


def test_scheme_stage_answers_years_before_any_sql():
    src = inspect.getsource(p._data_scheme_stage)
    assert "_scheme_years_answer(question, schemes)" in src
    assert src.index("classify_scheme(") < src.index("_scheme_years_answer(")


def test_route_stage_answers_years_before_the_knowledge_split():
    # "which years of data are available for PMAY-G?" was classified KNOWLEDGE
    src = inspect.getsource(p._turn_route_stage)
    assert "_scheme_years_answer(question, _years_schemes)" in src
    assert src.index("_scheme_years_answer(") < src.index("classify_intent(")


@pytest.mark.parametrize("question,first", [
    ("Which years of data are available for PMAY-G?", "PMAY-G data covers 7"),
    ("What financial years does Focus Legacy cover?", "Focus Legacy data covers 4"),
])
def test_route_stage_returns_the_years_answer(question, first):
    t = p._new_turn(question)
    r = asyncio.run(p._turn_route_stage(t, None, None))
    assert r is not None and r["answer"].startswith(first) and r["route"] == "data"


def test_refresh_reads_the_same_per_scheme_sql():
    assert "_SCHEME_YEAR_SQL.items()" in inspect.getsource(p.refresh_scheme_years)
    assert all("dim_year" not in sql for sql in p._SCHEME_YEAR_SQL.values())


# ── the SQL backstop ────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT financial_year_short FROM curated.dim_year ORDER BY year_key LIMIT 100",
    "SELECT DISTINCT lgd_district FROM curated.dim_geography",
    "SELECT y.financial_year FROM curated.dim_year y JOIN curated.dim_scheme s ON true",
])
def test_dimension_only_sql_is_rejected(sql):
    issue = p._sql_dimension_only_issue(["MGNREGA"], sql)
    assert issue and "not what MGNREGA has data for" in issue


@pytest.mark.parametrize("sql", [
    "SELECT d.financial_year_short, SUM(e.person_days) FROM curated.v_employment e "
    "JOIN curated.dim_year d ON d.year_key = e.year_key GROUP BY 1",
    "SELECT money_unit FROM curated.dim_scheme WHERE scheme_name = 'Focus Plus'",
    "SELECT DISTINCT financial_year_short FROM curated.v_focus_plus",
    "SELECT COUNT(*) FROM curated.v_pmay",
])
def test_sql_on_the_schemes_own_data_passes(sql):
    assert p._sql_dimension_only_issue(["Focus Plus"], sql) is None


def test_dimension_guard_runs_before_the_database():
    async def run():
        with pytest.raises(ValueError, match="shared"):
            await p._execute_one_attempt(
                "give me financial years in MGNREGA", ["MGNREGA"], {"resolved": {}, "unresolved": []},
                "SELECT financial_year_short FROM curated.dim_year ORDER BY year_key LIMIT 100")
    asyncio.run(run())
