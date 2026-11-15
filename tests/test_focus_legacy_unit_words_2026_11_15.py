"""Focus Legacy per-place lists, 15 Nov 2026: a column's unit suffix belongs to the value, not to the measure's name.
The list read "₹10.93 crore total disbursed cr" and its total "21.28 total disbursed cr" (no ₹, no crore)."""
import pytest

from app import pipeline as p

_SQL = ("SELECT lgd_district AS district, ROUND(SUM(amount_disbursed)::numeric / 10000000, 2) AS total_disbursed_cr "
        "FROM curated.v_focus_legacy GROUP BY 1")


def test_crore_column_reads_as_rupees_crore_in_every_line_and_the_total():
    rows = [{"district": "WEST GARO HILLS", "total_disbursed_cr": "10.93"},
            {"district": "RI BHOI", "total_disbursed_cr": "4.93"}]
    a = p._focus_legacy_breakdown_answer(_SQL, rows, {}, None)
    assert " cr" not in a.replace(" crore", "")
    assert "West Garo Hills: ₹10.93 crore total disbursed" in a
    assert "account for ₹15.86 crore total disbursed." in a
    assert a.startswith("Focus Legacy total disbursed by district")
    assert p._finish_answer(a, rows, ["Focus Legacy"], {}) == a


@pytest.mark.parametrize("col,val,want", [
    ("amount_lakh", 12.5, "₹12.50 lakh"),
    ("share_pct", 41.0, "41.00%"),
    ("pg_count", 5, "5"),
    ("cr", 3, "3"),        # a bare suffix is not a unit
])
def test_value_and_words(col, val, want):
    assert p._fl_metric_value(col, val) == want


def test_words_drop_only_the_unit_suffix():
    assert p._fl_metric_words("total_disbursed_cr") == "total disbursed"
    assert p._fl_metric_words("pg_count") == "producer groups"      # 2026-11-16: never "440 pg count"
