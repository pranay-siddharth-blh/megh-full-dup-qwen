"""Focus Legacy sheet re-test 2026-10-22 (raw_uc/Use_Cases_-_Focus.csv, report
new_docs/Focus_Legacy_Test_Report_2026-10-22.md): regression tests against the real functions.

1. TC-28 (KI-369): "How many Producer Groups are mapped to <constituency>?" — 12 of 55 right
   (55/55 on the 13 Oct code). The generator's first query was correct; the 30B verifier called
   the v_focus_legacy -> dim_geography join "prohibited" or demanded an UPPER() that was there,
   and the repairs dropped the join: "couldn't build a working query", Dalu answered 928 (all of
   East Garo Hills, true 203), g.ac_name = 'UMROI' answered 0 (true 142, ac_name is Title Case).
2. TC-16 / TC-25 (KI-370): "FOCUS PG members" / "FOCUS Producer Groups by district" came back
   WHERE pg_entity_type = 'FOCUS_PG' — 94,766 members for 102,021.
3. TC-16 in a chat (KI-371): "How many PG members have been recorded so far?" counted groups
   (11,906) and called them members.

The SQL strings are the ones the live runs produced."""
import pytest

from app import pipeline as p

FL = ["Focus Legacy"]
DALU = {"resolved": {"assembly_constituency": "DALU"}}
AC_GOOD = ("SELECT COUNT(DISTINCT pg_id) AS producer_groups FROM curated.v_focus_legacy AS f "
           "JOIN curated.dim_geography AS g ON g.geography_key = f.geography_key "
           "WHERE UPPER(g.ac_name) = UPPER('DALU') LIMIT 1000")
AC_AS_DISTRICT = ("SELECT COUNT(DISTINCT pg_id) AS producer_groups FROM curated.v_focus_legacy "
                  "WHERE UPPER(lgd_district) = UPPER('EAST GARO HILLS') LIMIT 1000")
AC_BARE_UPPER = ("SELECT COUNT(DISTINCT pg_id) AS producer_groups FROM curated.v_focus_legacy AS f "
                 "JOIN curated.dim_geography AS g ON g.geography_key = f.geography_key "
                 "WHERE g.ac_name = 'UMROI' LIMIT 1000")
VERIFIER_JOIN = ("Check 1: The query uses a prohibited join path. It joins curated.v_focus_legacy with "
                 "curated.dim_geography, which is not allowed according to the prohibited joins list.")
VERIFIER_UPPER = ("Check 2 failed: The RESOLVED ENTITY 'DALU' assembly constituency is not correctly applied "
                  "in the WHERE clause; it should use UPPER(g.ac_name) = UPPER('DALU').")
VERIFIER_MEASURE = "Check 3: the measure should be SUM(no_of_pg_members), not COUNT(DISTINCT pg_id)."


# ── KI-369: constituency ────────────────────────────────────────────────────────

def test_bare_ac_name_comparison_becomes_case_insensitive():
    out = p._focus_legacy_ac_name_case(FL, AC_BARE_UPPER)
    assert "UPPER(g.ac_name) = 'UMROI'" in out


def test_ac_name_in_list_is_upper_cased_on_both_sides():
    out = p._focus_legacy_ac_name_case(FL, "SELECT g.ac_name, COUNT(*) FROM curated.v_focus_legacy AS f JOIN "
                                       "curated.dim_geography AS g ON g.geography_key = f.geography_key "
                                       "WHERE g.ac_name IN ('Dalu', 'Umroi') GROUP BY g.ac_name")
    assert "UPPER(g.ac_name) IN ('DALU', 'UMROI')" in out
    assert "SELECT g.ac_name" in out          # the output column is left alone


def test_ac_name_already_upper_wrapped_is_unchanged():
    assert p._focus_legacy_ac_name_case(FL, AC_GOOD) == AC_GOOD


def test_ac_name_case_rewrite_is_focus_legacy_only():
    sql = AC_BARE_UPPER.replace("v_focus_legacy", "v_cm_elevate_disbursement")
    assert p._focus_legacy_ac_name_case(["CM Elevate Legacy"], sql) == sql


def test_ac_name_case_rewrite_runs_in_the_scheme_rewrites():
    import asyncio
    out = asyncio.run(p._scheme_sql_rewrites("How many Focus Producer Groups are mapped to Umroi constituency?",
                                             FL, {"resolved": {"assembly_constituency": "UMROI"}}, AC_BARE_UPPER))
    assert "UPPER(g.ac_name)" in out


def test_constituency_answered_from_its_district_is_sent_to_repair():
    issue = p._focus_legacy_ac_filter_missing(FL, DALU, AC_AS_DISTRICT)
    assert issue and "assembly constituency DALU" in issue and "UPPER(g.ac_name) = UPPER('DALU')" in issue


def test_constituency_filter_present_passes():
    assert p._focus_legacy_ac_filter_missing(FL, DALU, AC_GOOD) is None
    assert p._focus_legacy_ac_filter_missing(FL, {"resolved": {}}, AC_AS_DISTRICT) is None


def test_constituency_drift_guard_raises_in_the_attempt():
    import asyncio
    with pytest.raises(ValueError, match="assembly constituency DALU"):
        asyncio.run(p._execute_one_attempt("How many Focus Producer Groups are mapped to Dalu constituency?",
                                           FL, DALU, AC_AS_DISTRICT))


@pytest.mark.parametrize("issue", [VERIFIER_JOIN, VERIFIER_UPPER])
def test_verifier_join_or_case_complaint_on_documented_ac_query_is_false(issue):
    assert p._focus_legacy_ac_verifier_complaint_is_false(issue, FL, DALU, AC_GOOD)


def test_verifier_measure_complaint_still_stands():
    assert not p._focus_legacy_ac_verifier_complaint_is_false(VERIFIER_MEASURE, FL, DALU, AC_GOOD)


def test_verifier_overrule_needs_the_documented_shape():
    # the join on something other than geography_key, a third table, another scheme, another AC
    assert not p._focus_legacy_ac_verifier_complaint_is_false(
        VERIFIER_JOIN, FL, DALU, AC_GOOD.replace("g.geography_key = f.geography_key",
                                                 "g.lgd_district = f.lgd_district"))
    assert not p._focus_legacy_ac_verifier_complaint_is_false(
        VERIFIER_JOIN, FL, DALU, AC_GOOD.replace("LIMIT", "AND f.pg_id IN (SELECT pg_id FROM curated.dim_producer_group) LIMIT"))
    assert not p._focus_legacy_ac_verifier_complaint_is_false(VERIFIER_JOIN, ["CM Elevate Legacy"], DALU, AC_GOOD)
    assert not p._focus_legacy_ac_verifier_complaint_is_false(
        VERIFIER_JOIN, FL, {"resolved": {"assembly_constituency": "UMROI"}}, AC_GOOD)


def test_verify_sql_discards_the_false_join_complaint(monkeypatch):
    import asyncio
    import json

    async def fake_verifier(prompt, guided=None):
        return json.dumps({"ok": False, "issue": VERIFIER_JOIN})

    monkeypatch.setattr(p.settings, "SQL_VERIFY_ENABLED", True)
    monkeypatch.setattr(p.llm, "call_sql_verifier", fake_verifier)
    q = "How many Focus Producer Groups are mapped to Dalu constituency?"
    assert asyncio.run(p._verify_sql(q, FL, DALU, AC_GOOD)) is None
    # a constituency complaint against a query that really drops the constituency is kept
    missing = "Check 2 failed: the RESOLVED ENTITY 'DALU' assembly constituency is not filtered; it uses a district."

    async def fake_missing(prompt, guided=None):
        return json.dumps({"ok": False, "issue": missing})

    monkeypatch.setattr(p.llm, "call_sql_verifier", fake_missing)
    assert asyncio.run(p._verify_sql(q, FL, DALU, AC_AS_DISTRICT)) == missing


# ── KI-370: "FOCUS PG" is the scheme, not the group type ────────────────────────

def test_focus_pg_type_as_only_condition_is_dropped():
    sql = "SELECT SUM(no_of_pg_members) AS memberships FROM curated.v_focus_legacy WHERE pg_entity_type = 'FOCUS_PG' LIMIT 1"
    out = p._focus_legacy_scheme_name_not_variant("What is the total number of FOCUS PG members recorded till now?", FL, sql)
    assert "pg_entity_type" not in out and "WHERE" not in out


def test_focus_pg_type_beside_another_condition_is_dropped():
    sql = ("SELECT lgd_district, COUNT(DISTINCT pg_id) AS focus_producer_groups FROM curated.v_focus_legacy "
           "WHERE pg_entity_type = 'FOCUS_PG' AND financial_year_short = '2024-25' GROUP BY lgd_district")
    out = p._focus_legacy_scheme_name_not_variant("How many FOCUS Producer Groups are mapped to each district?", FL, sql)
    assert "pg_entity_type" not in out and "financial_year_short = '2024-25'" in out


def test_focus_pg_display_name_is_dropped_too():
    sql = ("SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy "
           "WHERE LOWER(pg_entity_type_name) = 'newly formed focus producer group'")
    assert "pg_entity_type_name" not in p._focus_legacy_scheme_name_not_variant("How many FOCUS PGs are there?", FL, sql)


@pytest.mark.parametrize("q, sql", [
    ("How many newly formed FOCUS PGs are there?",
     "SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE pg_entity_type = 'FOCUS_PG'"),
    ("How many groups of each type?", "SELECT pg_entity_type, COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy "
                                      "WHERE pg_entity_type = 'FOCUS_PG' GROUP BY 1"),
    ("How many LAMPS cooperatives are there?",
     "SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE pg_entity_type = 'LAMP'"),
    ("How many existing cooperatives were paid?",
     "SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE pg_entity_type = 'EXISTING_COOPERATIVE'"),
])
def test_a_group_type_question_keeps_its_filter(q, sql):
    assert p._focus_legacy_scheme_name_not_variant(q, FL, sql) == sql


def test_programme_variant_alone_keeps_the_old_rule():
    # the sole-condition drop is for the group type only; programme_variant is unchanged
    sql = "SELECT COUNT(*) FROM curated.v_focus_legacy WHERE programme_variant = 'FOCUS'"
    assert p._focus_legacy_scheme_name_not_variant("How many FOCUS payments?", FL, sql) == sql


# ── KI-371: members counted as groups ───────────────────────────────────────────

def test_members_question_answered_with_a_group_count_is_sent_to_repair():
    issue = p._focus_legacy_members_counted_as_groups(
        "How many PG members have been recorded so far?", FL,
        "SELECT COUNT(DISTINCT pg_id) AS producer_groups FROM curated.v_focus_legacy LIMIT 1")
    assert issue and "SUM(no_of_pg_members)" in issue


@pytest.mark.parametrize("q, sql", [
    ("What is the total number of PG members recorded till now?",
     "SELECT SUM(no_of_pg_members) AS memberships FROM curated.v_focus_legacy LIMIT 1"),
    ("List top 5 PGs which has more than 20 members.",
     "SELECT pg_id, MAX(no_of_pg_members) AS group_size FROM curated.v_focus_legacy GROUP BY pg_id "
     "HAVING MAX(no_of_pg_members) > 20 ORDER BY 2 DESC LIMIT 5"),
    ("How many unique Producer Groups are present under FOCUS scheme?",
     "SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy"),
])
def test_members_guard_leaves_correct_queries_alone(q, sql):
    assert p._focus_legacy_members_counted_as_groups(q, FL, sql) is None


SUM_MEMBERS = "SELECT SUM(no_of_pg_members) AS memberships FROM curated.v_focus_legacy LIMIT 1"


@pytest.mark.parametrize("issue", [
    "Check 3 fails: The query uses a per-row table (curated.v_focus_legacy) without aggregating the metric column "
    "'no_of_pg_members'. The query should wrap 'no_of_pg_members' with SUM() or COUNT().",
    "Check 3: no_of_pg_members is not aggregated.",
])
def test_verifier_not_aggregated_complaint_on_a_sum_is_false(issue):
    assert p._focus_legacy_aggregate_complaint_is_false(issue, FL, SUM_MEMBERS)


@pytest.mark.parametrize("issue, sql", [
    # a complaint that SUM itself is wrong stands
    ("Check 3: summing no_of_pg_members double-counts the group; use MAX(no_of_pg_members).", SUM_MEMBERS),
    # the column really is not aggregated
    ("Check 3: without aggregating no_of_pg_members.",
     "SELECT no_of_pg_members FROM curated.v_focus_legacy LIMIT 1"),
    # a different column is named
    ("Check 3: without aggregating amount_disbursed.", SUM_MEMBERS),
])
def test_verifier_aggregate_complaint_kept_when_it_may_be_right(issue, sql):
    assert not p._focus_legacy_aggregate_complaint_is_false(issue, FL, sql)


def test_verifier_aggregate_overrule_is_focus_legacy_only():
    assert not p._focus_legacy_aggregate_complaint_is_false(
        "Check 3: without aggregating no_of_pg_members.", ["Focus Plus"], SUM_MEMBERS)


def test_members_guard_is_focus_legacy_only():
    assert p._focus_legacy_members_counted_as_groups(
        "How many members?", ["Focus Plus"], "SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy") is None
