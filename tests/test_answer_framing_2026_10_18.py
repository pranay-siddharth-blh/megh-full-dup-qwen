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
    assert out == "Under MGNREGA, in FY 2023-24 in East Khasi Hills district, the recorded total is 8,996.36 lakh total expenditure."
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
    assert "27,264,054" in out and "27264054" not in out
    assert out.endswith("This figure is for MGNREGA, all of Meghalaya (statewide).")   # the year is in the sentence
    # names the scheme but not the area -> only the area is added; names the area but not the scheme -> the scheme
    assert p._finish_answer("MGNREGA recorded 27,264,054 person-days in FY 2023-24.", rows, ["MGNREGA"], {"year": "FY 2023-24"})         .endswith("This is the statewide figure for all of Meghalaya.")
    assert p._finish_answer("Completed houses in Ri Bhoi, in FY 2023-24: 6,847.", [{"houses": 6847}], ["PMAY-G"],
                            {"district": "Ri Bhoi", "year": "FY 2023-24"})         == "Completed houses in Ri Bhoi, in FY 2023-24: 6,847. This is the PMAY-G figure."
    # names both (the place without its level word): nothing appended
    both = "A total of 8,996.36 lakh was spent under MGNREGA in East Khasi Hills for FY 2023-24."
    assert p._finish_answer(both, [{"total_expenditure_lakh": 8996.36}], ["MGNREGA"],
                            {"district": "East Khasi Hills", "year": "FY 2023-24"}) == both


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
    good = "Under MGNREGA, Meghalaya recorded 27,264,054 person-days in FY 2023-24."
    assert p._finish_answer(good, rows, ["MGNREGA"], {"year": "FY 2023-24"}) == good
    # a year is never regrouped, nor a number that is not a result value
    assert p._finish_answer("In 2023 there were 12345 visits.", rows, ["MGNREGA"], {}).count("12345") == 1
    # cross-scheme and multi-row answers are left alone apart from grouping
    assert p._finish_answer("MGNREGA 1 vs PMAY-G 2", [{"a": 1}, {"a": 2}], ["MGNREGA", "PMAY-G"], {}) == "MGNREGA 1 vs PMAY-G 2"
