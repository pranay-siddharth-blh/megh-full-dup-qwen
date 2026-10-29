"""
Single-year answers never say "across all financial years" (D-053 live probe,
2026-10-19): the 9B composer wrote "for FY 2023-24 across all financial years" in one
sentence on a correctly single-year SQL. _finish_answer, the universal last pass over
a data answer, drops the phrase on words when the resolved period is one financial
year, and leaves an all-years answer alone. Real functions.
"""
from app import pipeline as p

ROWS = [{"person_days": 27264054}]
ONE_YEAR = {"year": "FY 2023-24"}


def test_phrase_after_the_year_is_dropped_with_its_separator():
    out = p._finish_answer("MGNREGA recorded 2,72,64,054 person-days in Meghalaya for FY 2023-24 across all financial years.",
                           ROWS, ["MGNREGA"], ONE_YEAR)
    assert out == "MGNREGA recorded 2,72,64,054 person-days in Meghalaya for FY 2023-24."


def test_phrase_before_the_year_and_comma_wrapped_phrase():
    out = p._finish_answer("MGNREGA person-days across all financial years for FY 2023-24 in Meghalaya total 2,72,64,054.",
                           ROWS, ["MGNREGA"], ONE_YEAR)
    assert out == "MGNREGA person-days for FY 2023-24 in Meghalaya total 2,72,64,054."
    out = p._finish_answer("Under MGNREGA, across all financial years, Meghalaya recorded 2,72,64,054 person-days in FY 2023-24.",
                           ROWS, ["MGNREGA"], ONE_YEAR)
    assert out == "Under MGNREGA, Meghalaya recorded 2,72,64,054 person-days in FY 2023-24."


def test_sentence_initial_phrase_capitalises_the_next_word():
    out = p._finish_answer("Across all financial years, MGNREGA recorded 2,72,64,054 person-days in Meghalaya in FY 2023-24.",
                           ROWS, ["MGNREGA"], ONE_YEAR)
    assert out == "MGNREGA recorded 2,72,64,054 person-days in Meghalaya in FY 2023-24."
    two = ("MGNREGA recorded 2,72,64,054 person-days in Meghalaya in FY 2023-24. Across all financial years, "
           "this is the statewide figure.")
    assert p._finish_answer(two, ROWS, ["MGNREGA"], ONE_YEAR) == (
        "MGNREGA recorded 2,72,64,054 person-days in Meghalaya in FY 2023-24. This is the statewide figure.")


def test_variants_are_dropped_too():
    for phrase in ("over all the financial years", "for all fiscal years", "all financial years combined", "in all years"):
        out = p._finish_answer(f"MGNREGA recorded 2,72,64,054 person-days in Meghalaya {phrase} for FY 2023-24.",
                               ROWS, ["MGNREGA"], ONE_YEAR)
        assert out == "MGNREGA recorded 2,72,64,054 person-days in Meghalaya for FY 2023-24.", phrase


def test_all_years_result_keeps_the_phrase_and_scope_sentence_still_follows():
    text = "MGNREGA recorded 2,72,64,054 person-days in Meghalaya across all financial years."
    assert p._finish_answer(text, ROWS, ["MGNREGA"], {}) == text
    # the phrase is dropped before the scope check, so the closing sentence names the year
    out = p._finish_answer("Total person-days across all financial years: 2,72,64,054.", ROWS, ["MGNREGA"], ONE_YEAR)
    assert out == ("Total person-days: 2,72,64,054. This figure is for MGNREGA, all of Meghalaya (statewide), FY 2023-24.")


def test_multi_row_single_year_result_is_cleaned_as_well():
    rows = [{"lgd_block": "DALU", "person_days": 390921}, {"lgd_block": "RONGRAM", "person_days": 470583}]
    out = p._finish_answer("Across all financial years, DALU recorded 390,921 and RONGRAM 470,583 person-days in FY 2024-25.",
                           rows, ["MGNREGA"], {"district": "West Garo Hills", "year": "FY 2024-25"})
    assert out == "DALU recorded 3,90,921 and RONGRAM 4,70,583 person-days in FY 2024-25."   # Indian grouping (KI-586)


def test_number_word_helper_resolves_its_shared_names():
    # _cme_digits_for_number_words lives in schemes/cm_elevate.py; its matcher and
    # word lists are defined in common/c12 and shared through the package namespace
    assert p._cme_digits_for_number_words("Five CM ELEVATE applicants in Sasatgre village", [{"n": 5}]) == \
        "5 CM ELEVATE applicants in Sasatgre village"
    assert p._cme_digits_for_number_words("Twenty-one producer groups received payments", [{"n": 21}]) == \
        "21 producer groups received payments"
    assert p._cme_digits_for_number_words("Five applicants", [{"n": 7}]) == "Five applicants"
