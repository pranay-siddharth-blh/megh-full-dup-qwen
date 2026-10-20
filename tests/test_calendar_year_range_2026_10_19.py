"""
KI-323 (conversation harness, 2026-10-19): "How many in 2023-24?" for PMAY-G was answered
110,890 houses — the SQL filtered sanction_date by CALENDAR 2023 although the pipeline had
resolved year_key = 2023 (FY 2023-24 = 106,527). `_calendar_year_range_issue` (c11) sends such
a query to the repair step with the exact fix. Real function, real SQL.
"""
from app import pipeline as p

CAL = """SELECT COUNT(*) AS houses FROM curated.v_pmay
WHERE NOT is_placeholder AND sanction_date >= '2023-01-01' AND sanction_date < '2024-01-01' LIMIT 1"""
FY = "SELECT COUNT(*) AS houses FROM curated.v_pmay WHERE NOT is_placeholder AND year_key = 2023 LIMIT 1"
ENT = {"resolved": {"year_key": 2023}}


def test_calendar_range_for_a_financial_year_is_an_issue():
    issue = p._calendar_year_range_issue("How many PMAY-G houses in FY 2023-24?", ENT, CAL)
    assert issue and "FY 2023-24" in issue and "year_key = 2023" in issue and "sanction_date" in issue


def test_year_key_filter_is_fine_and_so_is_an_explicit_month_range():
    assert p._calendar_year_range_issue("How many PMAY-G houses in FY 2023-24?", ENT, FY) is None
    assert p._calendar_year_range_issue("How many PMAY-G houses in FY 2023-24?", {"resolved": {}}, CAL) is None
    months = "SELECT COUNT(*) FROM curated.v_focus_legacy WHERE date_of_remittance >= '2026-01-01' AND date_of_remittance < '2026-04-01'"
    assert p._calendar_year_range_issue("remittances made between January and March 2026", {"resolved": {"year_key": 2025}}, months) is None
    # an FY-shaped date range (April to March) is not a calendar year
    fy_dates = "SELECT COUNT(*) FROM curated.v_pmay WHERE sanction_date >= '2023-04-01' AND sanction_date < '2024-04-01'"
    assert p._calendar_year_range_issue("houses in FY 2023-24", ENT, fy_dates) is None


def test_two_years_name_both_keys():
    issue = p._calendar_year_range_issue("houses in FY 2022-23 and FY 2023-24", {"resolved": {"year_key_list": [2022, 2023]}},
                                         CAL.replace("'2023-01-01'", "'2022-01-01'"))
    assert issue and "year_key IN (2022, 2023)" in issue
