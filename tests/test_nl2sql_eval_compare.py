"""The NL->SQL accuracy set's result comparison (tests/nl2sql_eval/compare.py):
fair to answers that differ only in naming, extra columns, rounding or units,
strict about everything else."""
import datetime as dt
from decimal import Decimal

from tests.nl2sql_eval.compare import compare


def test_scalar_with_a_different_alias_matches():
    assert compare([{"n": 120}], [{"applications": 120}])["match"]


def test_wrong_number_fails():
    r = compare([{"n": 120}], [{"n": 121}])
    assert not r["match"] and "no column holds" in r["reason"]


def test_extra_columns_are_allowed():
    gold = [{"d": "RI BHOI", "n": 5}, {"d": "EAST KHASI HILLS", "n": 9}]
    pred = [{"district": "East Khasi Hills", "count": 9, "share_pct": 64.3},
            {"district": "Ri Bhoi", "count": 5, "share_pct": 35.7}]
    assert compare(gold, pred)["match"]


def test_row_order_matters_only_when_ordered():
    gold = [{"d": "A", "n": 9}, {"d": "B", "n": 5}]
    pred = [{"d": "B", "n": 5}, {"d": "A", "n": 9}]
    assert compare(gold, pred)["match"]
    assert not compare(gold, pred, ordered=True)["match"]


def test_values_must_stay_paired_across_columns():
    gold = [{"d": "A", "n": 9}, {"d": "B", "n": 5}]
    pred = [{"d": "A", "n": 5}, {"d": "B", "n": 9}]
    r = compare(gold, pred)
    assert not r["match"] and "not as rows" in r["reason"]


def test_rounding_and_decimal_types():
    assert compare([{"pct": Decimal("33.3333")}], [{"p": 33.33}])["match"]
    assert compare([{"pct": 33.3333}], [{"p": 33.3}])["match"]
    assert not compare([{"pct": 33.3333}], [{"p": 34}])["match"]


def test_unit_scaling_rupees_to_lakh_and_crore():
    assert compare([{"amt": 12_345_678}], [{"amt_lakh": 123.46}])["match"]
    assert compare([{"amt": 123_456_789}], [{"amt_cr": 12.35}])["match"]
    assert compare([{"share": 0.4567}], [{"share_pct": 45.67}])["match"]
    r = compare([{"amt": 12_345_678}], [{"amt_lakh": 123.46}])
    assert r["mapping"]["amt"][1] == 1e5


def test_a_different_grain_never_matches():
    gold = [{"total": 14}]
    pred = [{"d": "A", "n": 9}, {"d": "B", "n": 5}]
    r = compare(gold, pred)
    assert not r["match"] and "row count" in r["reason"]


def test_text_is_case_and_space_insensitive_and_dates_compare():
    assert compare([{"b": "MYLLIEM "}], [{"block": "mylliem"}])["match"]
    assert compare([{"d": dt.date(2024, 4, 1)}], [{"x": dt.date(2024, 4, 1)}])["match"]


def test_nulls_and_empties():
    assert compare([], [])["match"]
    assert not compare([{"n": 1}], None)["match"]
    assert compare([{"n": None}], [{"m": None}])["match"]
    assert not compare([{"n": None}], [{"m": 0}])["match"]


def test_two_gold_columns_cannot_share_one_pipeline_column():
    gold = [{"a": 5, "b": 5}]
    assert not compare(gold, [{"x": 5}])["match"]
    assert compare(gold, [{"x": 5, "y": 5}])["match"]


def test_a_single_number_stated_in_the_answer_counts():
    from tests.nl2sql_eval.compare import stated_in_answer
    gold = [{"houses": 3541}]
    assert stated_in_answer(gold, "Across all years there are 3,541 houses at the Roof Cast stage.")
    assert stated_in_answer([{"pd": 1161895}], "That is 11,61,895 person-days.")          # Indian grouping
    assert stated_in_answer([{"pd": 1161895}], "That is 1,161,895 person-days.")
    assert stated_in_answer([{"pct": 9.94}], "About 9.9% came from the top-up round.")
    assert not stated_in_answer(gold, "There are 3,540 houses.")                         # counts are exact
    assert not stated_in_answer([{"y": 2023}], "In 2023 ...")                           # a year never counts
    assert not stated_in_answer([{"n": 7}], "7 blocks")                                 # too small to trust
    assert not stated_in_answer([{"a": 1, "b": 2}], "1 and 2")                          # not a single number
    assert not stated_in_answer([{"d": "RI BHOI"}], "RI BHOI")


def test_one_row_with_a_column_per_category_matches_one_row_per_category():
    from tests.nl2sql_eval.compare import long_as_wide
    gold = [{"gender": "Female", "n": 1103}, {"gender": "Male", "n": 501}]
    assert long_as_wide(gold, [{"female_registrants": 1103, "male_registrants": 501}])
    # "male" is not a whole word of "female_registrants": swapped numbers never pair up
    assert not long_as_wide(gold, [{"female_registrants": 501, "male_registrants": 1103}])
    assert not long_as_wide(gold, [{"total": 1604}])
    assert not long_as_wide(gold, [{"female": 1103, "male": 501}, {"female": 1, "male": 2}])
