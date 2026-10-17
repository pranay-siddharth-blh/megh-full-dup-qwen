"""Business definitions (D-048; errors.md cases 1-3): gender, people across years,
households vs persons. Calls the real pipeline functions and checks the backbone
and the executed few-shots carry the definitions."""
import yaml

from app import pipeline as p
from app import schema_context

M = ["MGNREGA"]
CASE3 = ("SELECT SUM(households_employed) AS beneficiary_households, "
         "SUM(persons_employed) AS persons_employed FROM curated.v_employment LIMIT 1")


def test_case3_multi_year_sum_is_labelled_household_years():
    out = p._mgnrega_people_years_alias(M, CASE3)
    assert "AS household_years" in out and "AS person_years" in out
    assert "beneficiary_households" not in out


def test_single_year_per_year_ratio_and_money_are_untouched():
    for sql in (
        "SELECT SUM(households_employed) AS hh FROM curated.v_employment WHERE year_key = 2024",
        "SELECT SUM(households_employed) AS hh FROM curated.v_employment "
        "WHERE year_key = (SELECT MAX(year_key) FROM curated.v_employment)",
        "SELECT financial_year_short, SUM(households_employed) AS hh FROM curated.v_employment "
        "GROUP BY financial_year_short, year_key",
        "SELECT SUM(households_employed) AS household_years FROM curated.v_employment",
        "SELECT SUM(person_days)::numeric / NULLIF(SUM(households_employed), 0) AS d FROM curated.v_employment",
        "SELECT SUM(total_exp) AS t FROM curated.v_expenditure",
    ):
        assert p._mgnrega_people_years_alias(M, sql) == sql
    assert p._mgnrega_people_years_alias(["PMAY-G"], CASE3) == CASE3


def test_multi_year_in_list_renames_the_order_by_alias_too():
    sql = ("SELECT lgd_district, SUM(persons_employed) AS persons FROM curated.v_employment "
           "WHERE year_key IN (2022, 2023) GROUP BY lgd_district ORDER BY persons DESC")
    out = p._mgnrega_people_years_alias(M, sql)
    assert "AS person_years" in out and "ORDER BY person_years DESC" in out


def test_rewrite_runs_in_the_scheme_rewrite_chain():
    import asyncio
    out = asyncio.run(p._scheme_sql_rewrites("How many beneficiaries in MGNREGA, all years", M,
                                             {"resolved": {}}, CASE3))
    assert "household_years" in out


def test_answer_note_explains_household_years():
    notes = p._mgnrega_answer_notes("q", "SELECT 1", [{"household_years": 1494437}])
    assert any("household-years" in n and "DISTINCT households" in n for n in notes)


def test_backbone_carries_the_definitions():
    mg = schema_context.build_schema_context(["MGNREGA"])
    assert "men_employed" in mg and "women_employment_provided" in mg
    assert "2025-26" in mg and "household_years" in mg
    assert "households_employed (rule 11)" in mg
    fp = schema_context.build_schema_context(["Focus Plus"])
    assert "93,286 + 105,813 = 199,099" in fp and "12.5K registration cohort" in fp


def test_new_examples_are_present_and_marked_executed():
    mg = yaml.safe_load(open("data/mgnrega/few_shot.yaml", encoding="utf-8"))["sql_generation_examples"]
    qs = {e["question"]: e for e in mg}
    men = qs["How many men worked under MGNREGA in East Garo Hills in 2024-25?"]["sql"]
    assert "SUM(persons_employed) - SUM(women_employment_provided) AS men_employed" in men
    assert qs["How many men got MGNREGA work in 2025-26?"]["sql"] is None
    assert "household_years" in qs["How many beneficiaries are there under MGNREGA across all years?"]["sql"]
    fp = yaml.safe_load(open("data/focus_plus/focusplus_few_shot.yaml", encoding="utf-8"))["sql_generation_examples"]
    per_year = {e["question"]: e for e in fp}["How many Focus Plus beneficiaries were there in each financial year?"]
    assert "all_years_unique_beneficiaries" in per_year["sql"]


MEN_SQL = ("SELECT SUM(persons_employed) AS persons_employed, SUM(women_employment_provided) AS women_employed, "
           "SUM(persons_employed) - SUM(women_employment_provided) AS men_employed FROM curated.v_employment "
           "WHERE lgd_district = 'RI BHOI' AND year_key = 2023 LIMIT 1")
LIVE_COMPLAINT = ("Check 3 fails: The query uses SUM() on the metric columns (persons_employed, "
                  "women_employment_provided), but the question asks specifically for 'how many men worked'. "
                  "The SQL computes men_employed as a derived column")


def test_verifier_complaint_about_the_men_definition_is_discarded():
    # live 2026-10-16: the 30B verifier rejected this exact query four times (errors.md case 1)
    assert p._mgnrega_definition_complaint_is_false(M, MEN_SQL, LIVE_COMPLAINT)
    assert p._mgnrega_definition_complaint_is_false(
        M, "SELECT SUM(households_employed) AS household_years FROM curated.v_employment",
        "Check 3 fails: the question asks for a single beneficiary count")


def test_other_verifier_complaints_still_count():
    assert not p._mgnrega_definition_complaint_is_false(
        M, MEN_SQL, "Check 1 fails: the district filter is missing the resolved block DALU")
    assert not p._mgnrega_definition_complaint_is_false(
        M, "SELECT SUM(persons_employed) AS men_employed FROM curated.v_employment", LIVE_COMPLAINT)
    assert not p._mgnrega_definition_complaint_is_false(["PMAY-G"], MEN_SQL, LIVE_COMPLAINT)
