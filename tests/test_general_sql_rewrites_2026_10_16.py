"""General SQL rewrites added 2026-10-16 after misses in the held-out NL->SQL
accuracy set (tests/nl2sql_eval). Each fixes a class of query, checked here on
questions and SQL of our own — never the eval items' wording.

  - CM Elevate Legacy: a count of records that received a loan gets
    total_loan_disbursement > 0 (schema rule 11).
  - CM Elevate: a side-by-side district comparison (one FILTER column per
    district) is no longer split into a row per district.
  - Focus Legacy: an unasked "paid in N distinct years" condition is dropped.
"""
from app import pipeline as p
from app import sql_ast

# ── CM Elevate Legacy: received a loan ──────────────────────────────────────
LOAN_SQL = ("SELECT COALESCE(loan_entity, '(not recorded)') AS lender, COUNT(*) AS records, "
            "SUM(total_loan_disbursement) AS loan FROM curated.v_cm_elevate_disbursement "
            "WHERE financial_year_short = '2023-24' GROUP BY loan_entity")


def test_records_that_took_a_loan_get_the_loan_filter():
    out = p._cm_legacy_loan_received_filter(
        "How many CM Elevate Legacy beneficiaries took a loan from each lender in 2023-24?",
        ["CM Elevate Legacy"], LOAN_SQL)
    assert sql_ast.filtered_by(out, "total_loan_disbursement")
    assert sql_ast.filtered_by(out, "financial_year_short")      # the existing filter stays


def test_borrowers_wording_too():
    out = p._cm_legacy_loan_received_filter("Count of borrowers per lender under CM Elevate Legacy",
                                            ["CM Elevate Legacy"], LOAN_SQL)
    assert sql_ast.filtered_by(out, "total_loan_disbursement")


def test_loan_rewrite_leaves_other_questions_and_schemes_alone():
    q = "How many CM Elevate Legacy records are there per lender?"
    assert p._cm_legacy_loan_received_filter(q, ["CM Elevate Legacy"], LOAN_SQL) == LOAN_SQL
    q2 = "How many records received a loan?"
    assert p._cm_legacy_loan_received_filter(q2, ["CM Elevate"], LOAN_SQL) == LOAN_SQL
    already = LOAN_SQL.replace("WHERE ", "WHERE total_loan_disbursement > 0 AND ")
    q3 = "How many CM Elevate Legacy records got a loan per lender?"
    assert p._cm_legacy_loan_received_filter(q3, ["CM Elevate Legacy"], already) == already
    no_count = ("SELECT SUM(total_loan_disbursement) AS loan FROM curated.v_cm_elevate_disbursement")
    assert p._cm_legacy_loan_received_filter(q3, ["CM Elevate Legacy"], no_count) == no_count


# ── CM Elevate: side-by-side district comparison ────────────────────────────
PIVOT = ("SELECT scheme_name, "
         "COUNT(*) FILTER (WHERE lgd_district = 'EAST KHASI HILLS') AS ekh, "
         "COUNT(*) FILTER (WHERE lgd_district = 'WEST JAINTIA HILLS') AS wjh "
         "FROM curated.v_cm_elevate WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST JAINTIA HILLS') "
         "GROUP BY scheme_name")


def test_a_pivoted_district_comparison_is_left_alone():
    q = "Which CM Elevate schemes have fewer applications in East Khasi Hills than in West Jaintia Hills?"
    out = p._cm_elevate_compare_by_district(q, ["CM Elevate"], PIVOT)
    assert out == PIVOT
    case_pivot = PIVOT.replace("COUNT(*) FILTER (WHERE lgd_district = 'EAST KHASI HILLS')",
                               "SUM(CASE WHEN lgd_district = 'EAST KHASI HILLS' THEN 1 ELSE 0 END)")
    assert p._cm_elevate_compare_by_district(q, ["CM Elevate"], case_pivot) == case_pivot


def test_a_merged_district_comparison_still_gets_split():
    merged = ("SELECT scheme_name, COUNT(*) AS applications FROM curated.v_cm_elevate "
              "WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST JAINTIA HILLS') GROUP BY scheme_name")
    out = p._cm_elevate_compare_by_district("Compare CM Elevate applications in EKH and WJH by scheme",
                                            ["CM Elevate"], merged)
    assert sql_ast.groups_by(out, "lgd_district")


# ── Focus Legacy: unasked "paid in N years" ─────────────────────────────────
YEARS_SQL = ("SELECT COUNT(DISTINCT village_code) AS villages FROM curated.v_focus_legacy "
             "WHERE lgd_district = 'RI BHOI' AND pg_id IN (SELECT pg_id FROM curated.v_focus_legacy "
             "GROUP BY pg_id HAVING COUNT(DISTINCT financial_year_short) = 4)")


def test_an_unasked_year_count_condition_is_dropped():
    out = p._focus_legacy_unasked_year_coverage(
        "How many villages in Ri Bhoi have a Focus Legacy group that received money?", ["Focus Legacy"], YEARS_SQL)
    assert "financial_year_short" not in out
    assert sql_ast.filter_values(out, "lgd_district") == ["RI BHOI"]


def test_a_question_about_years_paid_keeps_it():
    for q in ("Which Focus Legacy groups were paid in more than one year?",
              "Villages with a Focus Legacy group paid every year",
              "How many Focus Legacy groups were paid twice?"):
        assert p._focus_legacy_unasked_year_coverage(q, ["Focus Legacy"], YEARS_SQL) == YEARS_SQL


def test_other_schemes_untouched():
    q = "How many villages in Ri Bhoi have a group that received money?"
    assert p._focus_legacy_unasked_year_coverage(q, ["Focus Plus"], YEARS_SQL) == YEARS_SQL


# ── A breakdown the question asks for survives the rephraser and the SQL ────
def test_breakdown_dimensions_are_read():
    assert p._c02_breakdowns("Block-wise for Ri Bhoi, what Focus Plus amount was paid?") == {"block"}
    assert p._c02_breakdowns("PMAY-G houses in each block of East Garo Hills") == {"block"}
    assert p._c02_breakdowns("CM Elevate applications district by district") == {"district"}
    assert p._c02_breakdowns("Focus Legacy payments by financial year in Ri Bhoi") == {"year"}
    assert p._c02_breakdowns("blockwise MGNREGA spend") == {"block"}
    assert p._c02_breakdowns("How many PMAY-G houses in East Garo Hills?") == set()
    assert p._c02_breakdowns("MGNREGA person-days per district") == {"district"}
    assert p._c02_breakdowns("average MGNREGA spend per year", include_per=False) == set()


def test_a_rephrase_that_drops_the_breakdown_is_rejected():
    assert p._rephrase_violation("Block-wise for Ri Bhoi, what Focus Plus amount was paid?",
                                 "What Focus Plus amount was paid in Ri Bhoi?") == "breakdown"
    assert p._rephrase_violation("Give me the PMAY-G houses in each block of East Garo Hills",
                                 "How many PMAY-G houses are there in each block of East Garo Hills?") is None


def test_one_total_row_for_a_breakdown_question_goes_to_repair():
    total = "SELECT SUM(amount_disbursed) AS amount FROM curated.v_focus_plus WHERE lgd_district = 'RI BHOI'"
    issue = p._breakdown_missing_issue("Focus Plus amount in each block of Ri Bhoi", total)
    assert issue and "GROUP BY" in issue and "block" in issue
    grouped = total.replace(" WHERE", " WHERE 1=1 AND").replace("'RI BHOI'", "'RI BHOI' GROUP BY block_name_raw")
    assert p._breakdown_missing_issue("Focus Plus amount in each block of Ri Bhoi", grouped) is None
    # an average "per year" is one value, not a breakdown
    assert p._breakdown_missing_issue("average MGNREGA spend per year in Ri Bhoi",
                                      "SELECT AVG(total_exp) FROM curated.v_expenditure") is None
    # no breakdown asked
    assert p._breakdown_missing_issue("Focus Plus amount in Ri Bhoi", total) is None


def test_the_all_years_scope_chip_is_not_a_question_about_years():
    # The year pause's "All financial years combined" chip appends this scope.
    q = "How many villages in Ri Bhoi have a Focus Legacy group that received money across all financial years"
    out = p._focus_legacy_unasked_year_coverage(q, ["Focus Legacy"], YEARS_SQL)
    assert "financial_year_short" not in out
    q2 = "Focus Legacy groups in Ri Bhoi paid in all years combined"
    assert "financial_year_short" not in p._focus_legacy_unasked_year_coverage(q2, ["Focus Legacy"], YEARS_SQL)
    # ...while asking about years still keeps it
    q3 = "Focus Legacy groups paid every year, across all financial years"
    assert p._focus_legacy_unasked_year_coverage(q3, ["Focus Legacy"], YEARS_SQL) == YEARS_SQL


# ── PMAY-G village ranking: placeholder rows are is_placeholder, not entity_type ──
import asyncio  # noqa: E402

import pytest  # noqa: E402

PMAY_RANK = ("SELECT lgd_village_name, COUNT(*) AS houses FROM curated.v_pmay "
             "WHERE lgd_district = 'RI BHOI' AND year_key = 2021 "
             "GROUP BY lgd_village_name ORDER BY houses DESC LIMIT 3")


@pytest.fixture
def no_db(monkeypatch):
    async def rows(sql):
        return [{"lgd_village_name": "X", "houses": 1}]
    async def ok(*_a, **_k):
        return None
    monkeypatch.setattr(p, "run_readonly", rows)
    monkeypatch.setattr(p, "_verify_sql", ok)


def test_pmay_village_ranking_is_not_asked_to_drop_placeholders(no_db):
    # D-060 (2026-10-22): the zero-sanction registrations are beneficiaries in real
    # villages and v_pmay has no "Unresolved" bucket, so nothing is demanded.
    q = "Top 3 villages in Ri Bhoi by PMAY-G houses sanctioned in 2021-22"
    rows = asyncio.run(p._execute_one_attempt(q, ["PMAY-G"], {"resolved": {}, "unresolved": []}, PMAY_RANK))
    assert rows


def test_pmay_village_ranking_with_is_placeholder_passes_the_guard(no_db):
    q = "Top 3 villages in Ri Bhoi by PMAY-G houses sanctioned in 2021-22"
    sql = PMAY_RANK.replace("WHERE ", "WHERE NOT is_placeholder AND ")
    rows = asyncio.run(p._execute_one_attempt(q, ["PMAY-G"], {"resolved": {}, "unresolved": []}, sql))
    assert rows


# ── A question's subject read as a "district" is not out of scope ───────────
@pytest.mark.parametrize("mention", ["LAMPS cooperatives", "12.5K registration batch payments",
                                     "producer groups", "existing cooperative societies"])
def test_a_subject_is_not_a_place(mention):
    assert p._c09_not_a_place(mention)


@pytest.mark.parametrize("mention", ["Guwahati", "Assam", "Kolkata", "Kamrup", "Nagaon", "Sylhet"])
def test_real_places_outside_meghalaya_are_still_places(mention):
    assert not p._c09_not_a_place(mention)


# ── A breakdown grouped on an unselected column gets the column selected ────
def test_unselected_group_by_column_is_selected_for_a_breakdown():
    sql = ("SELECT COUNT(*) AS payments, SUM(amount_disbursed) AS amount FROM curated.v_focus_plus "
           "WHERE lgd_district = 'RI BHOI' GROUP BY block_name_raw ORDER BY amount DESC")
    out = p._select_unselected_group_by("Focus Plus payments and amount in each block of Ri Bhoi", sql)
    assert sql_ast.output_names(out)[0].lower() == "block_name_raw"
    # no breakdown asked: left to the per-scheme rule
    assert p._select_unselected_group_by("Focus Plus amount in Ri Bhoi", sql) == sql
    selected = sql.replace("SELECT COUNT(*)", "SELECT block_name_raw, COUNT(*)")
    assert p._select_unselected_group_by("Focus Plus amount in each block of Ri Bhoi", selected) == selected


# ── A subquery that "correlates" a table with itself ────────────────────────
def test_self_correlated_subquery_goes_to_repair():
    bad = ("SELECT scheme_name, COUNT(*) AS n FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI' "
           "GROUP BY scheme_name HAVING COUNT(*) > (SELECT COUNT(*) FROM curated.v_cm_elevate "
           "WHERE lgd_district = 'EAST KHASI HILLS' AND scheme_name = curated.v_cm_elevate.scheme_name)")
    issue = p._self_correlated_subquery_issue(bad)
    assert issue and "alias" in issue
    aliased = bad.replace("FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'",
                          "FROM curated.v_cm_elevate o WHERE lgd_district = 'RI BHOI'"
                          ).replace("curated.v_cm_elevate.scheme_name", "o.scheme_name")
    assert p._self_correlated_subquery_issue(aliased) is None
    plain = "SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district IN (SELECT lgd_district FROM curated.v_pmay)"
    assert p._self_correlated_subquery_issue(plain) is None


# ── "more in A than in B": the two places side by side ──────────────────────
def test_two_places_on_separate_rows_go_to_repair():
    long_form = ("SELECT lgd_district, scheme_name, COUNT(*) AS n FROM curated.v_cm_elevate "
                 "WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST JAINTIA HILLS') "
                 "GROUP BY scheme_name, lgd_district")
    q = "Which CM Elevate schemes have fewer applications in East Khasi Hills than in West Jaintia Hills?"
    issue = p._two_place_comparison_issue(q, long_form)
    assert issue and "FILTER" in issue and "HAVING" in issue
    assert p._two_place_comparison_issue("Compare CM Elevate applications in EKH and WJH by scheme",
                                         long_form) is None              # a plain comparison may list rows
    assert p._two_place_comparison_issue(q, PIVOT) is None               # already side by side
    # the CM Elevate district-split rewrite leaves such a question alone
    merged = ("SELECT scheme_name, COUNT(*) AS n FROM curated.v_cm_elevate "
              "WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST JAINTIA HILLS') GROUP BY scheme_name")
    assert p._cm_elevate_compare_by_district(q, ["CM Elevate"], merged) == merged


def test_every_and_per_do_not_demand_a_group_by():
    total = "SELECT COUNT(*) AS houses FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'"
    assert p._breakdown_missing_issue("Counting every financial year, how many PMAY-G houses in Ri Bhoi?",
                                      total) is None
    assert p._breakdown_missing_issue("PMAY-G houses in each financial year in Ri Bhoi", total)
    # the rephrase check still keeps "every <dim>"
    assert p._c02_breakdowns("PMAY-G houses in every block of Ri Bhoi") == {"block"}


def test_two_places_merged_into_one_figure_go_to_repair():
    q = "Which CM Elevate schemes have fewer applications in East Khasi Hills than in West Jaintia Hills?"
    merged = ("SELECT scheme_name, COUNT(*) AS n FROM curated.v_cm_elevate "
              "WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST JAINTIA HILLS') GROUP BY scheme_name")
    issue = p._two_place_comparison_issue(q, merged)
    assert issue and "into one figure" in issue
    # one row per place, nothing else grouped: the answer can compare the two rows
    per_place = ("SELECT lgd_district, COUNT(*) AS n FROM curated.v_cm_elevate "
                 "WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST JAINTIA HILLS') GROUP BY lgd_district")
    assert p._two_place_comparison_issue("Did East Khasi Hills have more CM Elevate applications than "
                                         "West Jaintia Hills?", per_place) is None


# ── "CM Elevate schemes … each scheme" is CM Elevate's own sub-schemes ──────
def test_cm_elevate_each_scheme_stays_cm_elevate():
    assert p._shortcut_scheme("For each CM Elevate scheme, how many applications came from Ri Bhoi?") == ["CM Elevate"]
    assert p._shortcut_scheme("CM Elevate Legacy records by scheme") == ["CM Elevate Legacy"]
    # every onboarded scheme (was a pinned 6 — CMSS / Homestay onboarding 2026-11-11/12)
    from app import scheme_registry
    assert len(p._shortcut_scheme("Compare beneficiaries across all schemes") or []) == len(scheme_registry.NAMES)
