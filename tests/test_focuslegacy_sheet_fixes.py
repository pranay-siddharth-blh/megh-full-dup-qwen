"""FOCUS (Focus Legacy) sheet test run 2026-10-12 (Test Case Results - 30th Sep 26.xlsx, TC-01..TC-28):
regression tests for the failures, against the real functions."""
import pytest

from app import pipeline as p


# ── "under FOCUS" is the scheme's name, not programme_variant = 'FOCUS' (TC-26) ──
def test_scheme_name_is_not_a_variant_filter():
    sql = ("SELECT lgd_block, COUNT(DISTINCT pg_id) AS producer_groups FROM curated.v_focus_legacy\n"
           "WHERE lgd_district = 'EAST JAINTIA HILLS'\n  AND programme_variant = 'FOCUS'\n  AND lgd_block IS NOT NULL\n"
           "GROUP BY lgd_block")
    out = p._focus_legacy_scheme_name_not_variant("How many Producer Groups are mapped to each block for east "
                                                  "jaintia hills under FOCUS?", ["Focus Legacy"], sql)
    assert "programme_variant" not in out and "lgd_block IS NOT NULL" in out
    asked = "How much was paid under the FOCUS variant vs the additional top-up?"
    assert p._focus_legacy_scheme_name_not_variant(asked, ["Focus Legacy"], sql) == sql
    assert p._focus_legacy_scheme_name_not_variant("x", ["Focus Plus"], sql) == sql


# ── UPPER(lgd_block) = '<mixed case>' is upper-cased too (TC-26, 'NONGstoin') ──
def test_upper_wrapped_geo_literal_is_uppercased():
    out = p._uppercase_geo_literals("SELECT 1 FROM curated.v_focus_legacy WHERE UPPER(lgd_block) = 'NONGstoin'")
    assert "'NONGSTOIN'" in out


# ── data requests about a named scheme are not refused as content / tasks (TC-09/15/20) ──
@pytest.mark.parametrize("q", ["Give me a short overview of FOCUS that I can use for an official briefing.",
                               "List top 5 FOCUS PGs which has more than 20 members.",
                               "Show me all FOCUS remittances made between April and June 2025."])
def test_scheme_data_requests_overrule_scope_verdict(q):
    assert p._overrules_scope_verdict(q)


@pytest.mark.parametrize("q", ["Write an Instagram post about FOCUS beneficiaries",
                               "Write a speech on FOCUS producer groups for the minister",
                               "Who won the IPL final?"])
def test_content_requests_still_refused(q):
    assert not p._overrules_scope_verdict(q)


# ── duplicates: a fixed query and an answer that states the repeat payments (TC-12) ──
def test_duplicates_query_and_answer():
    sql, params, _ = p._focus_legacy_duplicates_query("Are there any duplicate Producer Groups there?",
                                                      ["Focus Legacy"], {})
    assert "fl-duplicates" in sql and params == []
    a = p._focus_legacy_duplicates_answer([{"payments": 14569, "producer_groups": 11906,
                                            "groups_paid_more_than_once": 2655, "repeat_payments": 2663,
                                            "duplicate_records": 0}], {})
    assert a.startswith("No — there are no duplicate records") and "2,655 groups" in a and "2,663 of the 14,569" in a
    sql, params, _ = p._focus_legacy_duplicates_query("Any duplicate PGs in Ri Bhoi?", ["Focus Legacy"],
                                                      {"district": "RI BHOI"})
    assert params == ["RI BHOI"] and "UPPER(lgd_district) = $1" in sql
    assert p._focus_legacy_duplicates_query("How many PGs?", ["Focus Legacy"], {}) is None


# ── knowledge answers state the Rs 5,000 per member rate (TC-03 / 06 / 09) ──
def test_rate_line_added_when_missing():
    a = p._focus_legacy_rate_line("Who can benefit under the FOCUS scheme?", "Focus Legacy", "Farmers in PGs.")
    assert "5,000" in a and a.startswith("Farmers in PGs.")
    assert p._focus_legacy_rate_line("Who can benefit?", "Focus Legacy", "Rs 5,000 each.") == "Rs 5,000 each."
    assert p._focus_legacy_rate_line("Who can benefit?", "Focus Plus", "x") == "x"
    assert p._focus_legacy_rate_line("How do I contact the office?", "Focus Legacy", "Call the DAO.") == "Call the DAO."


# ── a calendar month before a bare year names a month, not a FY (TC-20) ──
@pytest.mark.parametrize("q,bad", [("Show me all Focus Legacy remittances made between January and March 2026.", None),
                                   ("Show me all Focus Legacy remittances made between April and June 2025.", None),
                                   ("Focus Legacy remittances in May 2026", "2026"),
                                   ("Focus Legacy remittances in March 2024", "2024")])
def test_calendar_month_years(q, bad):
    assert p._out_of_range_year_in(q, ["Focus Legacy"]) == bad


# ── a comparison of two FYs stays a comparison, answered per year (TC-24) ──
def test_rephrase_keeps_comparison():
    assert p._rephrase_violation(
        "Compare the total Focus Legacy remittance between FY 2022-23 and FY 2025-26 for all of Meghalaya.",
        "What is the total Focus Legacy remittance for Meghalaya in FY 2022-23 and FY 2025-26?") == "shape"


def test_fy_compare_query_and_answer():
    sql, params, _ = p._focus_legacy_fy_compare_query(
        "Compare the total FOCUS remittance between FY 2022-23 and FY 2025-26.", ["Focus Legacy"], {})
    assert "fl-fy-compare" in sql and params == [["2022-23", "2025-26"]]
    a = p._focus_legacy_fy_compare_answer(
        [{"financial_year_short": "2022-23", "amount_disbursed": 141790000, "memberships": 28358, "payments": 2139,
          "producer_groups": 2138},
         {"financial_year_short": "2025-26", "amount_disbursed": 185090000, "memberships": 37018, "payments": 8812,
          "producer_groups": 8806}], params, {})
    assert "**FY 2022-23**: ₹14,17,90,000" in a and "**FY 2025-26**: ₹18,50,90,000" in a and "higher by ₹4,33,00,000" in a
    assert p._focus_legacy_fy_compare_query("What was paid in FY 2022-23?", ["Focus Legacy"], {}) is None


# ── a village / place name is never a producer-group filter (all-villages run) ──
@pytest.mark.parametrize("sql,code,name,want", [
    ("SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE village_code = 272773 "
     "AND LOWER(pg_name) ILIKE '%charbatapara%'", 272773, "Charbatapara", "WHERE village_code = 272773"),
    ("SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE pg_name ILIKE '%sakmal%'",
     272890, "Sakmal", "WHERE village_code = 272890"),
    ("SELECT 1 FROM curated.v_focus_legacy WHERE village_code = 276106 AND pg_name ILIKE '%choklogkittim%'",
     276106, "Choklokgittim", "WHERE village_code = 276106"),
    ("SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE lgd_village_name <> 'NONGLYNKIEN'",
     277332, "Nonglynkien", "WHERE village_code = 277332"),
])
def test_place_name_not_group_name(sql, code, name, want):
    out = p._focus_legacy_place_not_group_name(["Focus Legacy"], {"resolved": {"village_code": code},
                                                                  "display": {"village": name}}, sql)
    assert want in out and "pg_name" not in out and "<>" not in out


def test_real_group_name_filter_kept():
    sql = "SELECT 1 FROM curated.v_focus_legacy WHERE village_code = 1 AND pg_name ILIKE '%sunflower%'"
    assert p._focus_legacy_place_not_group_name(["Focus Legacy"], {"resolved": {"village_code": 1},
                                                                   "display": {"village": "Nonglynkien"}}, sql) == sql


# ── an "&" in a village name survives the rephraser (all-villages run) ──
def test_rephrase_keeps_ampersand_name():
    assert p._rephrase_violation(
        "How many FOCUS scheme Producer Groups are mapped to mawkohmit & mawkynsah village?",
        "How many FOCUS scheme Producer Groups are mapped to mawkohmit and mawkynsah villages?") == "name:&"


# ── an unselected GROUP BY is dropped for Focus Legacy too (all-villages run) ──
def test_unselected_group_by_dropped():
    out = p._cm_legacy_unselected_group_by(["Focus Legacy"], (
        "SELECT SUM(amount_disbursed) AS amount_disbursed FROM curated.v_focus_legacy WHERE village_code = 273150 "
        "GROUP BY pg_id ORDER BY amount_disbursed DESC LIMIT 1"))
    assert "GROUP BY" not in out and "village_code = 273150" in out
