"""
Answer framing (user report 2026-10-18): "1,494,437 household years." and "household years:
1,494,437; person years: 1,865,234; financial years: 4." reached the officer as the whole
answer. Every data answer now reads as a briefing line: scheme, what the figure counts in
plain words, area, period; result figures carry thousands separators. Real functions.
"""
from app import pipeline as p

MG_ALL = {"household_years": 1494437}
MG_THREE = {"household_years": 1494437, "person_years": 1865234, "financial_years": 4}


def test_single_metric_fallback_is_a_full_sentence_with_the_caveat():
    out = p._framed_fallback([MG_ALL], ["MGNREGA"], {})
    assert out.startswith("Under MGNREGA, across all financial years in all of Meghalaya (statewide), the recorded total is "
                          "1,494,437 household-years of employment.")
    assert "not a count of distinct households" in out


def test_multi_metric_fallback_lists_each_figure_in_words():
    out = p._framed_fallback([MG_THREE], ["MGNREGA"], {"district": "RI BHOI", "year": "FY 2023-24"})
    assert out.startswith("Under MGNREGA, in FY 2023-24 in Ri Bhoi district, the records show 1,494,437 household-years of "
                          "employment, 1,865,234 person-years of employment and 4 financial years covered.")


def test_money_and_category_rows_keep_their_unit_and_label():
    out = p._framed_fallback([{"total_expenditure_lakh": 8996.36}], ["MGNREGA"], {"district": "EAST KHASI HILLS", "year": "FY 2023-24"})
    # E9 (2026-10-29): money goes through the one formatter (₹, Indian grouping, the column's own lakh)
    assert out == "Under MGNREGA, in FY 2023-24 in East Khasi Hills district, the recorded total is ₹8,996.36 lakh (≈ ₹89.96 crore) total expenditure."  # D-092
    out = p._framed_fallback([{"house_status": "Completed", "houses": 6847}], ["PMAY-G"], {"district": "RI BHOI", "year": "FY 2023-24"})
    assert out == "Under PMAY-G, for Completed, in FY 2023-24 in Ri Bhoi district, the recorded total is 6,847 houses."


def test_multi_row_fallback_keeps_the_list_under_a_framing_line():
    rows = [{"lgd_block": "DALU", "person_days": 390921}, {"lgd_block": "RONGRAM", "person_days": 470583}]
    out = p._framed_fallback(rows, ["MGNREGA"], {"district": "WEST GARO HILLS", "year": "FY 2024-25"})
    assert out.startswith("Under MGNREGA, in FY 2024-25 in West Garo Hills district, here are the 2 results:")
    assert "- DALU — person days: 390,921" in out


def test_bare_deterministic_answer_is_unchanged_for_its_other_callers():
    assert p._deterministic_answer([MG_ALL]) == "1,494,437 household years."
    assert p._is_fallback_answer("1,494,437 household years.", [MG_ALL], ["MGNREGA"], {})
    assert p._is_fallback_answer(p._framed_fallback([MG_ALL], ["MGNREGA"], {}), [MG_ALL], ["MGNREGA"], {})
    assert not p._is_fallback_answer("There are 1,494,437 household-years.", [MG_ALL], ["MGNREGA"], {})


def test_finish_groups_result_digits_and_adds_scope_when_missing():
    rows = [{"person_days": 27264054}]
    out = p._finish_answer("Total person-days in FY 2023-24 is 27264054.", rows, ["MGNREGA"], {"year": "FY 2023-24"})
    assert "2,72,64,054" in out and "27264054" not in out
    assert out.endswith("This figure is for MGNREGA, all of Meghalaya (statewide).")   # the year is in the sentence
    # names the scheme but not the area -> only the area is added; names the area but not the scheme -> the scheme
    assert p._finish_answer("MGNREGA recorded 2,72,64,054 person-days in FY 2023-24.", rows, ["MGNREGA"], {"year": "FY 2023-24"})         .endswith("This is the statewide figure for all of Meghalaya.")
    assert p._finish_answer("Completed houses in Ri Bhoi, in FY 2023-24: 6,847.", [{"houses": 6847}], ["PMAY-G"],
                            {"district": "Ri Bhoi", "year": "FY 2023-24"})         == "Completed houses in Ri Bhoi, in FY 2023-24: 6,847. This is the PMAY-G figure."
    # names both (the place without its level word): nothing appended
    # names both (the place without its level word): nothing appended; the lakh figure gets its
    # ₹ and crore size (D-092, data-accuracy brief D2)
    both = "A total of 8,996.36 lakh was spent under MGNREGA in East Khasi Hills for FY 2023-24."
    assert p._finish_answer(both, [{"total_expenditure_lakh": 8996.36}], ["MGNREGA"],
                            {"district": "East Khasi Hills", "year": "FY 2023-24"}) == (
        "A total of ₹8,996.36 lakh (≈ ₹89.96 crore) was spent under MGNREGA in East Khasi Hills for FY 2023-24.")


def test_finish_data_result_runs_for_any_data_path():
    rows = [{"person_days": 27264054}]
    r = {"route": "data", "answer": "Completed houses in Ri Bhoi, in FY 2023-24: 6847.", "schemes": ["PMAY-G"],
         "rows": [{"district": "Ri Bhoi", "houses": 6847}], "resolved_entities": {"district": "RI BHOI", "year_key": 2023}}
    p._finish_data_result(r)
    assert r["answer"] == "Completed houses in Ri Bhoi, in FY 2023-24: 6,847. This is the PMAY-G figure."
    failed = {"route": "data", "answer": "I understood the question but couldn't build a working query", "schemes": ["PMAY-G"],
              "rows": [], "answer_failed": True}
    p._finish_data_result(failed)
    assert failed["answer"].startswith("I understood")
    # names the scheme and the area already: nothing appended
    good = "Under MGNREGA, Meghalaya recorded 2,72,64,054 person-days in FY 2023-24."
    assert p._finish_answer(good, rows, ["MGNREGA"], {"year": "FY 2023-24"}) == good
    # a year is never regrouped, nor a number that is not a result value
    assert p._finish_answer("In 2023 there were 12345 visits.", rows, ["MGNREGA"], {}).count("12345") == 1
    # cross-scheme and multi-row answers are left alone apart from grouping
    assert p._finish_answer("MGNREGA 1 vs PMAY-G 2", [{"a": 1}, {"a": 2}], ["MGNREGA", "PMAY-G"], {}) == "MGNREGA 1 vs PMAY-G 2"


# ── Repeated place names written once (user report 2026-11-03) ──────────────
# PMAY-G "where are these 126 beneficiaries registered?": every fallback line repeated
# "EAST KHASI HILLS / MAWPHLANG / …" and printed the village code as a figure.
def _ph(d, b, v, n, c):
    return {"lgd_district": d, "lgd_block": b, "lgd_village_name": v, "placeholder_houses": n, "village_code": c}


PH_ROWS = [_ph("EAST KHASI HILLS", "KHATARSHNONG LAITKROH", "KHRANG", 1, 278564),
           _ph("EAST KHASI HILLS", "KHATARSHNONG LAITKROH", "KONGTHONG", 1, 278556),
           _ph("EAST KHASI HILLS", "MAWPHLANG", "LADUMRISAIN", 2, 278230)]


def test_fallback_groups_repeated_place_names_and_keeps_every_value():
    out = p._finish_answer(p._framed_fallback(PH_ROWS, ["PMAY-G"], {}), PH_ROWS, ["PMAY-G"], {})
    assert out.count("EAST KHASI HILLS / KHATARSHNONG LAITKROH") == 1
    assert "- **EAST KHASI HILLS / MAWPHLANG**" in out
    assert "  - KHRANG (village code 278564) — placeholder houses: 1" in out
    assert "  - LADUMRISAIN (village code 278230) — placeholder houses: 2" in out
    for r in PH_ROWS:                       # nothing is lost: every name, code and figure is written
        assert r["lgd_village_name"] in out and str(r["village_code"]) in out
    assert "here are the 3 results:" in out
    assert p._is_fallback_answer(p._framed_fallback(PH_ROWS, ["PMAY-G"], {}), PH_ROWS, ["PMAY-G"], {})


def test_fallback_stays_flat_when_grouping_would_move_a_row():
    # a group split across the list (a ranking across blocks): the row order wins
    rows = [PH_ROWS[0], PH_ROWS[2], PH_ROWS[1]]
    out = p._deterministic_answer(rows)
    assert "- EAST KHASI HILLS / KHATARSHNONG LAITKROH / KHRANG — placeholder houses: 1" in out
    assert "**" not in out
    # one label column, or labels that never repeat: flat as before
    assert "- DALU — person days: 390,921" in p._deterministic_answer(
        [{"lgd_block": "DALU", "person_days": 390921}, {"lgd_block": "RONGRAM", "person_days": 470583}])
    assert "**" not in p._deterministic_answer(
        [{"d": "A", "b": "X", "n": 1}, {"d": "B", "b": "Y", "n": 2}])


# ── Key points over a multi-row fallback (user report 2026-11-03) ───────────
# "highlight points of what the question asked": the 72-village answer never said 126.
KP_ROWS = PH_ROWS + [_ph("RI BHOI", "UMSNING", "UMIAM", 3, 270001)]
KP_SQL = ("SELECT lgd_district, lgd_block, lgd_village_name, village_code, "
          "COUNT(*) FILTER (WHERE is_placeholder) AS placeholder_houses FROM curated.v_pmay GROUP BY 1, 2, 3, 4")


def test_fallback_key_points_are_computed_from_every_row():
    out = p._framed_fallback(KP_ROWS, ["PMAY-G"], {}, sql=KP_SQL)
    assert out.startswith("Under PMAY-G, across all financial years in all of Meghalaya (statewide), here are the 4 results:\n"
                          "**Key points**\n")
    assert "- Placeholder houses: 7 in total, across 4 villages." in out
    assert "- Spread over 2 districts and 3 blocks." in out
    assert "- Most in EAST KHASI HILLS: 4, across 3 villages." in out
    assert "- Highest single village: 3, at UMSNING / UMIAM." in out
    assert "\n**Details**\n- **EAST KHASI HILLS / KHATARSHNONG LAITKROH**" in out
    for r in KP_ROWS:                       # the details still carry every value
        assert r["lgd_village_name"] in out and str(r["village_code"]) in out


def test_fallback_key_points_skip_the_rollup_total_and_years():
    rows = [{"lgd_district": "A", "houses": 5}, {"lgd_district": "B", "houses": 7},
            {"lgd_district": "C", "houses": 1}, {"lgd_district": None, "houses": 13}]
    out = p._framed_fallback(rows, ["PMAY-G"], {},
                             sql="SELECT lgd_district, COUNT(*) AS houses FROM curated.v_pmay GROUP BY ROLLUP(lgd_district)")
    assert "- Houses: 13 in total, across 3 districts." in out      # not 26: the TOTAL row is not a district
    yrs = [{"district": "A", "financial_year": 2022 + i, "houses": i + 1} for i in range(3)]
    assert "6,066" not in p._framed_fallback(yrs, ["PMAY-G"], {}, sql="SELECT 1")   # years are never summed


def test_fallback_without_sql_or_with_two_rows_is_unchanged():
    assert "**Key points**" not in p._framed_fallback(KP_ROWS, ["PMAY-G"], {})
    assert "**Key points**" not in p._framed_fallback(KP_ROWS[:2], ["PMAY-G"], {}, sql=KP_SQL)
    # rows of different layouts (one with a label missing): no highlights, the list as before
    mixed = KP_ROWS + [{"lgd_district": "X", "placeholder_houses": 1}]
    assert "**Key points**" not in p._framed_fallback(mixed, ["PMAY-G"], {}, sql=KP_SQL)
