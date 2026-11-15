"""The permutation bank round (2026-11-16, before the main demo): the general fixes it found, read without a database.
The whole bank (scheme x district x follow-up, voice and typed, figures checked against megh_db) is
tests/accuracy/run_perms.py; these are its offline guards.

1. a rank follow-up said with fillers ("um which block is having the lowest") is still the rank rule's (c01);
2. "per / every / each financial year" is the year grouping, and "across all districts" beside it is the state (c16);
3. a catalogue money figure below a crore keeps its rupees (metric_catalog._value_sql: 2 places of a crore rounded
   Rs 6,30,000 to "Rs 6,00,000").
"""
from __future__ import annotations

from app import metric_catalog
from app import pipeline as P


def test_rank_follow_up_with_spoken_fillers():
    assert P._c01_rank_request("um which block is having the lowest") == ("down", "block", None)
    assert P._c01_rank_request("which district is having the highest") == ("up", "district", None)
    assert P._c01_rank_request("okay top 3") == ("up", None, 3)
    # a measure / place word still makes it a new question, not this rule's
    assert P._c01_rank_request("um which block is having the lowest expenditure") is None


def test_every_financial_year_is_the_year_grouping():
    ys = P._c16_year_series
    assert ys("Could you please show me the MGNREGA expenditure per financial year across all districts?") == {"year"}
    assert ys("I want you to show me the MGNREGA expenditure for every financial year.") == {"year"}
    assert ys("Show me the MGNREGA expenditure per financial across all districts?") == {"year"}
    assert ys("MGNREGA person-days each financial year") == {"year"}
    assert ys("MGNREGA expenditure by district for every financial year") == {"year", "district"}
    assert ys("MGNREGA average expenditure per financial year") is None           # one figure
    assert ys("MGNREGA expenditure by district") is None                          # no year phrase: unchanged
    shape = P._c16_shape("MGNREGA expenditure per financial year across all districts", {})
    assert shape and shape["qtype"] == "breakdown" and shape["group"] == "year"


def test_money_below_a_crore_keeps_its_rupees():
    m = metric_catalog.Metric(key="focus_legacy_total_disbursed", scheme="Focus Legacy", display_name="x",
                              expression="SUM(amount_disbursed)", base_object="curated.v_focus_legacy",
                              unit="rupees", notes="", alias="total_disbursed_cr", phrases=(), columns=frozenset())
    sql = metric_catalog._value_sql(m)
    assert "/ 10000000" in sql and "THEN 2 ELSE 7 END" in sql
