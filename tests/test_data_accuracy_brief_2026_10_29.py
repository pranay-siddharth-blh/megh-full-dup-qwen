"""Data-accuracy brief (2026-10-29, megh_chatbot_fix_prompt.md): offline regression
tests for the general fixes behind D1-D10. Each calls the real function. The live
end-to-end suite is tests/live_chat_golden.py (needs the VPN)."""
import asyncio

import pytest

from app import conversation_layer, entity_resolver, pipeline as p, scheme_registry
from app.routers import stats


# ── RC6: one money format ──────────────────────────────────────────────────
@pytest.mark.parametrize("value, unit, want", [
    (374931500, "rupees", "₹37,49,31,500 (≈ ₹37.49 crore)"),          # D7
    (525658223.25, "rupees", "₹52,56,58,223.25 (≈ ₹52.57 crore)"),     # D10: paise kept when present
    (466430000.00, "rupees", "₹46,64,30,000 (≈ ₹46.64 crore)"),        # D8: no ".00"
    (25701.49, "lakh", "₹25,701.49 lakh (≈ ₹257.01 crore)"),           # D2: lakh column keeps lakh
    (940000, "rupees", "₹9,40,000 (≈ ₹9.40 lakh)"),
    (35000, "rupees", "₹35,000"),
    (3628.67, "crore", "₹3,628.67 crore"),
    (0, "rupees", "₹0"),
])
def test_money_format(value, unit, want):
    assert p._c12_money(value, unit) == want


def test_d9_bare_amount_column_is_money_in_rupees():
    rows = [{"producer_groups": 11906, "amount_disbursed": "510105000.00"}]
    out = p._c12_normalise_figures("a total amount disbursed of 51,01,05,000.00.", rows, ["Focus Legacy"])
    assert out == "a total amount disbursed of ₹51,01,05,000 (≈ ₹51.01 crore)."


def test_d2_lakh_figure_gets_rupee_and_crore():
    rows = [{"total_expenditure_lakh": "25701.49"}]
    out = p._c12_normalise_figures("expenditure is 25,701.49 lakh.", rows, ["MGNREGA"])
    assert out == "expenditure is ₹25,701.49 lakh (≈ ₹257.01 crore)."


def test_d8_crore_figure_restored_to_exact_cell():
    rows = [{"beneficiaries": 93286, "amount_raw": "466430000.00"}]
    out = p._c12_normalise_figures("amount paid of ₹46.64 crore.", rows, ["Focus Plus"])
    assert out == "amount paid of ₹46,64,30,000 (≈ ₹46.64 crore)."


def test_old_bracket_absorbed_and_idempotent():
    rows = [{"area": "Meghalaya", "still to be released (Rs)": 374931500}]
    once = p._c12_normalise_figures("Amount: ₹37,49,31,500 (₹37.49 crore).", rows, ["PMAY-G"])
    assert once == "Amount: ₹37,49,31,500 (≈ ₹37.49 crore)."
    assert p._c12_normalise_figures(once, rows, ["PMAY-G"]) == once


def test_mgnrega_unsuffixed_money_is_lakh_and_counts_are_not_money():
    assert p._c17_unit_by_name("total_exp", "MGNREGA") == "lakh"
    assert p._c17_unit_by_name("amount_disbursed", "Focus Legacy") == "rupees"
    assert p._c17_unit_by_name("avg_wage_per_day", "MGNREGA") is None
    assert p._c17_unit_by_name("payments", "Focus Plus") is None
    assert p._c17_unit_by_name("records", "CM Elevate Legacy") is None
    assert p._c17_unit_by_name("amount", "CM Elevate") is None          # holds no money


def test_person_days_in_crore_is_not_money():
    out = p._c12_normalise_figures("Person-days: 9.09 crore.", [{"person_days": 90912345}], ["MGNREGA"])
    assert out == "Person-days: 9.09 crore."


def test_scope_sentence_reads_across_all_years():
    out = p._finish_answer("Completed houses: 1,29,941.", [{"completed houses": 129941}], ["PMAY-G"], {})
    assert "figure for across" not in out


# ── RC1: multi-part questions ──────────────────────────────────────────────
def test_sub_asks_split():
    assert p._c17_sub_asks("How many PMAY-G houses in total, and how many completed?") == [
        "How many PMAY-G houses in total", "how many completed"]


def test_d5_total_and_completed_gives_the_breakdown():
    assert p._pmay_metrics("How many PMAY-G houses in total, and how many completed?", False) == [
        "houses", "completed", "progress"]
    assert p._pmay_metrics("How many PMAY-G houses were completed in Ri Bhoi?", False) == ["completed"]


def test_d5_breakdown_adds_up_to_the_total():
    row = {"houses": 171107, "completed": 129941, "st_house_sanctioned": 2057, "st_plinth": 13984,
           "st_roof_cast": 25000, "st_proposed_site": 40, "st_existing_site": 73}
    moving, rest = p._pmay_progress(row)
    assert (moving, rest) == (41041, 125)
    assert 129941 + moving + rest == 171107


def test_d10_total_and_top_scheme_are_two_queries():
    plan = p._c17_ask_plan("CM Elevate Legacy: number of records, subsidy disbursed, scheme with most records?")
    assert plan == ["CM Elevate Legacy: number of records, subsidy disbursed?", "Which scheme with most records?"]
    q2 = p._c17_ranking_question(plan[1], {"schemes": ["CM Elevate Legacy"], "resolved_entities": {}})
    assert q2 == "Which scheme with most records under CM Elevate Legacy across all financial years?"
    assert p._c17_ask_plan("Which district had the most households completing 100 days in FY 2022-23?") is None
    assert p._c17_ask_plan("How many PMAY-G houses in total, and how many completed?") is None


def test_answer_asks_keeps_every_part_and_notes_once():
    seen = []

    async def ask(q):
        seen.append(q)
        if len(seen) == 1:
            return {"route": "data", "schemes": ["CM Elevate Legacy"], "resolved_entities": {},
                    "answer": "2,823 records.\n\nNote: X.", "data": [{"records": 2823}], "sql_query": "SELECT 1"}
        return {"route": "data", "schemes": ["CM Elevate Legacy"], "resolved_entities": {},
                "answer": "Highest records: Piggery, 1,353.\n\nNote: X.",
                "data": [{"s": "a", "n": 1}, {"s": "b", "n": 2}], "sql_query": "SELECT 2"}

    plan = conversation_layer.AskPlan(["records?", "Which scheme with most records?"])
    out = asyncio.run(conversation_layer.answer_many(plan, ask))
    assert "2,823" in out["answer"] and "Piggery" in out["answer"]
    assert out["answer"].count("Note: X.") == 1
    assert out["schemes"] == ["CM Elevate Legacy"] and len(out["data"]) == 2
    assert "under CM Elevate Legacy" in seen[1]


# ── RC2: an explicit scheme locks routing ──────────────────────────────────
def test_d10_named_legacy_scheme_has_sub_schemes():
    assert scheme_registry.DATASETS["CM Elevate Legacy"].sub_scheme_column == "scheme_name"
    assert scheme_registry.DATASETS["MGNREGA"].sub_scheme_column is None


# ── RC3 / RC4: SQL hygiene and invented answers ────────────────────────────
D3_SQL = ("SELECT lgd_district AS district, SUM(households_completed_100_days) AS households_100_days "
          "FROM curated.v_employment WHERE year_key = 2022 GROUP BY lgd_district "
          "ORDER BY households_100_days DESC NULLS LAST LIMIT 1")
D3_Q = "Which district had the most households completing 100 days in FY 2022-23?"


def test_d3_superlative_reads_three_rows():
    from app import sql_ast
    assert sql_ast.outer_limit(p._c17_sql_hygiene(D3_Q, D3_SQL)) == 3
    assert sql_ast.outer_limit(p._c17_sql_hygiene("Top 5 districts by person-days", D3_SQL)) == 1


def test_d3_runners_up_answer_and_tie():
    sql = p._c17_sql_hygiene(D3_Q, D3_SQL)
    rows = [{"district": "EAST GARO HILLS", "households_100_days": 22049},
            {"district": "SOUTH GARO HILLS", "households_100_days": 9969},
            {"district": "SOUTH WEST KHASI HILLS", "households_100_days": 7778}]
    out = p._c17_runners_up_answer(D3_Q, sql, rows, ["MGNREGA"], {"year": "FY 2022-23"})
    assert "East Garo Hills, 22,049" in out and "Next: South Garo Hills (9,969), then South West Khasi Hills (7,778)" in out
    tied = [dict(rows[0]), {**rows[1], "households_100_days": 22049}, rows[2]]
    assert "tied between East Garo Hills and South Garo Hills" in p._c17_runners_up_answer(
        D3_Q, sql, tied, ["MGNREGA"], {"year": "FY 2022-23"})


def test_d9_limit_on_one_row_total_dropped():
    sql = "SELECT COUNT(DISTINCT pg_id) AS g, SUM(amount_disbursed) AS a FROM curated.v_focus_legacy LIMIT 1000000"
    assert "LIMIT" not in p._c17_sql_hygiene("Focus Legacy groups and total", sql)
    grouped = "SELECT lgd_district, COUNT(*) AS n FROM curated.v_pmay GROUP BY lgd_district LIMIT 5"
    assert "LIMIT 5" in p._c17_sql_hygiene("houses by district", grouped)


def test_d10_literal_answer_rejected_label_kept():
    assert p._c17_sql_issue("x", ["PMAY-G"], "SELECT COUNT(*) AS n, 'PMAY' AS scheme_with_most_records FROM curated.v_pmay")
    assert p._c17_sql_issue("x", ["PMAY-G"], "SELECT 'Meghalaya' AS name, COUNT(*) AS n FROM curated.v_pmay") is None


def test_other_schemes_view_rejected():
    assert "v_pmay" in p._c17_sql_issue("x", ["CM Elevate Legacy"], "SELECT COUNT(*) FROM curated.v_pmay")
    assert p._c17_sql_issue("x", ["PMAY-G"], "SELECT COUNT(*) FROM curated.v_pmay") is None


def test_unordered_superlative_rejected():
    sql = "SELECT lgd_district, SUM(person_days) AS pd FROM curated.v_employment GROUP BY lgd_district"
    assert p._c17_sql_issue("Which district had the most person-days?", ["MGNREGA"], sql)


# ── RC5: caveats ───────────────────────────────────────────────────────────
def test_d8_provisional_money_note_removed():
    # user decision 2026-11-03: the note came with every money answer; it is no longer added
    r = {"route": "data", "schemes": ["Focus Plus"], "answer": "₹46,64,30,000 paid.",
         "rows": [{"a": 1}], "resolved_entities": {"year_key": 2022}, "sql": "SELECT 1"}
    p._c17_attach_caveats(r)
    assert r["answer"] == "₹46,64,30,000 paid."


def test_d9_absent_year_note(monkeypatch):
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "Focus Legacy", ["2021-22", "2022-23", "2024-25", "2025-26"])
    r = {"route": "data", "schemes": ["Focus Legacy"], "answer": "11,906 groups.", "rows": [{"g": 11906}],
         "resolved_entities": {}, "sql": "SELECT COUNT(DISTINCT pg_id) AS g FROM curated.v_focus_legacy"}
    p._c17_attach_caveats(r)
    # user decision 2026-11-03: the years the data holds, from _SCHEME_DATA_YEARS, not the missing ones
    assert "Note: Focus Legacy data covers FY 2021-22, FY 2022-23, FY 2024-25 and FY 2025-26." in r["answer"]
    assert "no Focus Legacy data" not in r["answer"] and "absent" not in r["answer"]
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "Focus Legacy", ["2024-25", "2021-22", "2022-23"])   # unordered
    r2 = dict(r, answer="11,906 groups.")
    p._c17_attach_caveats(r2)
    assert "Note: Focus Legacy data covers FY 2021-22, FY 2022-23 and FY 2024-25." in r2["answer"]
    # no gap in the years held: no note
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "Focus Legacy", ["2021-22", "2022-23"])
    r3 = dict(r, answer="11,906 groups.")
    p._c17_attach_caveats(r3)
    assert "Note" not in r3["answer"]
    assert "provisional" not in r["answer"]                 # no money stated
    one_year = dict(r, answer="5 groups.", sql="SELECT COUNT(*) FROM curated.v_focus_legacy WHERE year_key = 2024")
    p._c17_attach_caveats(one_year)
    assert "Note" not in one_year["answer"]


def test_cards_and_chat_read_one_provisional_flag():
    row = {"person_days": 1, "exp_lakh": 1, "villages": 1, "sanctioned": 1, "completed": 1, "released": 1,
           "payments": 1, "amount": 1e7, "districts": 1, "applications": 1, "schemes": 1, "groups": 1,
           "memberships": 1, "records": 1, "disbursed": 1e7}
    cards = stats._cards({k: row for k in stats._SQL})
    assert cards["focus_plus"][1][0].endswith("*") == scheme_registry.DATASETS["Focus Plus"].provisional
    assert not cards["pmay_g"][2][0].endswith("*")


# ── §3: districts written short, years named as FYs ────────────────────────
def test_direction_short_forms():
    v = {"canonical": "East Khasi Hills", "aliases": ["EKH"]}
    entity_resolver._add_direction_aliases(v)
    assert "E Khasi Hills" in v["aliases"] and "EKH" in v["aliases"]
    sw = {"canonical": "South West Garo Hills", "aliases": []}
    entity_resolver._add_direction_aliases(sw)
    assert "SW Garo Hills" in sw["aliases"] and "S West Garo Hills" not in sw["aliases"]


def test_compare_names_years_as_fy():
    shape = p._AnswerShape("compare", "exp", ["exp"], ["year_key"])
    assert p._c12s_label({"year_key": 2022, "exp": 1}, shape) == "FY 2022-23"


def test_verifier_sees_the_limit_the_question_asked():
    from app import sql_ast
    widened = p._c17_sql_hygiene(D3_Q, D3_SQL)
    assert sql_ast.outer_limit(p._c17_as_asked(D3_Q, widened)) == 1
    assert p._c17_as_asked("Top 3 districts by person-days", widened) == widened


def test_any_model_limit_on_a_singular_superlative_becomes_three():
    from app import sql_ast
    q = "Which district has the most by number of PMAY-G houses in total across all financial years?"
    sql = "SELECT lgd_district, COUNT(*) AS houses FROM curated.v_pmay GROUP BY lgd_district ORDER BY houses DESC LIMIT 12"
    assert sql_ast.outer_limit(p._c17_sql_hygiene(q, sql)) == 3


def test_short_district_form_is_not_the_region():
    entity_resolver.load_all()
    assert entity_resolver.detect_region("person-days in E Khasi Hills", "MGNREGA") is None
    assert entity_resolver.detect_region("houses in W Garo Hills", "PMAY-G") is None
    assert entity_resolver.detect_region("houses in Garo Hills", "PMAY-G")["canonical"] == "Garo Hills"


def test_follow_up_context_points_at_the_winner_row():
    from app import context_manager
    rows = [{"district": "EAST GARO HILLS", "households_100_days": 22049},
            {"district": "SOUTH GARO HILLS", "households_100_days": 9969},
            {"district": "SOUTH WEST KHASI HILLS", "households_100_days": 7778}]
    r = {"route": "data", "rows": rows, "row_count": 3, "rewritten_question": D3_Q,
         "sql": p._c17_sql_hygiene(D3_Q, D3_SQL)}
    p._c17_mark_winner(r)
    assert r["winner_row"] == rows[0]
    assert context_manager.summarize_result(r).startswith("1 row (the one asked for): district=EAST GARO HILLS")


def test_years_note_names_every_scheme_of_a_multi_scheme_answer(monkeypatch):
    # user report 2026-11-03: "total disbursement in MGNREGA, PMAY-G, Focus Plus, CM Elevate"
    # noted Focus Plus' years alone; every scheme's years are listed (live list, sorted)
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "MGNREGA", ["2018-19", "2017-18", "2019-20"])
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "PMAY-G", ["2017-18", "2018-19"])
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "Focus Plus", ["2022-23", "2025-26"])
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "CM Elevate", [])
    r = {"route": "data", "schemes": ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"], "answer": "₹1 crore.",
         "rows": [{"a": 1}], "resolved_entities": {}, "sql": "SELECT 1"}
    p._c17_attach_caveats(r)
    assert ("Note: years in the data — MGNREGA: FY 2017-18 to FY 2019-20; PMAY-G: FY 2017-18 and FY 2018-19; "
            "Focus Plus: FY 2022-23 and FY 2025-26.") in r["answer"]
    assert "CM Elevate:" not in r["answer"]                    # no financial year: nothing to list
    # the same years for every scheme and no gap: no note
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "Focus Plus", ["2017-18", "2018-19"])
    same = dict(r, answer="₹1 crore.", schemes=["PMAY-G", "Focus Plus"])
    p._c17_attach_caveats(same)
    assert "Note" not in same["answer"]
    # one year asked: no note
    one = dict(r, answer="₹1 crore.", resolved_entities={"year_key": 2022})
    p._c17_attach_caveats(one)
    assert "Note" not in one["answer"]
