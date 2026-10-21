"""
KI-315 (conversation harness, 2026-10-18): the 30B verifier demanded a single total for
"… in Ri Bhoi in FY 2023-24 by block" although the SQL grouped by block; the repair
dropped the GROUP BY, the breakdown guard put it back, and the budget ran out.
`_verifier_total_vs_breakdown_is_false` discards that complaint. Real function, real SQL.
"""
from app import pipeline as p

SQL_BY_BLOCK = """SELECT lgd_block, COUNT(*) AS houses
FROM curated.v_pmay
WHERE NOT is_placeholder AND lgd_district = 'RI BHOI' AND year_key = 2023 AND house_status = 'Completed'
GROUP BY lgd_block ORDER BY houses DESC"""
SQL_TOTAL = """SELECT COUNT(*) AS houses FROM curated.v_pmay
WHERE NOT is_placeholder AND lgd_district = 'RI BHOI' AND year_key = 2023"""
ISSUE = ("Check 2: The RESOLVED ENTITY 'lgd_district = 'RI BHOI'' is correctly present in the WHERE clause, but the "
         "question asks for a total count of completed houses, not a breakdown by block. The query uses GROUP BY "
         "lgd_block which violates the requirement for a single aggregated total.")


def test_total_demand_is_discarded_when_the_question_asks_by_block():
    q = "How many PMAY-G houses were completed in Ri Bhoi in FY 2023-24 by block"
    assert p._verifier_total_vs_breakdown_is_false(ISSUE, q, SQL_BY_BLOCK)
    assert p._verifier_total_vs_breakdown_is_false(ISSUE, "PMAY-G houses completed in Ri Bhoi in FY 2023-24, block-wise",
                                                   SQL_BY_BLOCK)


def test_rule_stays_quiet_elsewhere():
    # the question really asks for one total: the complaint may stand
    assert not p._verifier_total_vs_breakdown_is_false(ISSUE, "How many PMAY-G houses were completed in Ri Bhoi in FY 2023-24",
                                                       SQL_BY_BLOCK)
    # the SQL does not group by the dimension asked for
    assert not p._verifier_total_vs_breakdown_is_false(ISSUE, "How many PMAY-G houses were completed in Ri Bhoi by block",
                                                       SQL_TOTAL)
    # a complaint about something else
    assert not p._verifier_total_vs_breakdown_is_false("Check 1: prohibited join with dim_geography_alias",
                                                       "PMAY-G houses completed in Ri Bhoi by block", SQL_BY_BLOCK)
    # a year breakdown grouped by the year column
    assert p._verifier_total_vs_breakdown_is_false(
        "the query should aggregate to a single total, not group by financial_year_short",
        "MGNREGA person-days in West Jaintia Hills for each financial year",
        "SELECT financial_year_short, SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'WEST JAINTIA HILLS' GROUP BY financial_year_short")
