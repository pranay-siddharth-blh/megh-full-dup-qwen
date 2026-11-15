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
    assert "ROUND((SUM(amount_disbursed))::numeric / 10000000, 2)" in sql
    assert "TRIM_SCALE(ROUND((SUM(amount_disbursed))::numeric / 10000000, 7))" in sql


def test_per_district_is_the_district_grouping():
    s = P._c16_shape("MGNREGA person-days per district", {})
    assert s and s["qtype"] == "breakdown" and s["group"] == "district"
    s = P._c16_shape("PMAY-G houses completed in each block", {})
    assert s and s["group"] == "block"
    assert P._c16_shape("MGNREGA average person-days per district", {})["qtype"] != "breakdown"


def test_the_figure_of_a_scheme_is_its_headline_measure():
    assert P._c16_default_measure_question("Give me the MGNREGA figure for Ri Bhoi?", "MGNREGA") == \
        "MGNREGA person-days Give me the MGNREGA figure for Ri Bhoi?"
    assert P._c16_default_measure_question("MGNREGA in Ri Bhoi", "MGNREGA") is None


def test_one_place_listed_twice_is_that_place():
    f = P._c16_filters({"district_list": ["SOUTH WEST KHASI HILLS", "SOUTH WEST KHASI HILLS"], "block": "MAWKYRWAT",
                        "district": "SOUTH WEST KHASI HILLS"})
    assert f == {"district": "SOUTH WEST KHASI HILLS", "block": "MAWKYRWAT"}
    # two different places listed beside one: still declined
    assert P._c16_filters({"district_list": ["RI BHOI", "WEST GARO HILLS"], "district": "RI BHOI"}) is None


def _frame(**kw):
    d = {"schemes": ["MGNREGA"], "qtype": "breakdown", "group": "district", "measure_text": "MGNREGA person-days",
         "filters": {}, "metric_key": "mgnrega_employment_generated", "source": "catalogue"}
    d.update(kw)
    return P._c18_af.AnswerFrame.from_dict(d)


def test_rank_inside_a_place_is_a_frame_edit(monkeypatch):
    # the place index needs megh_db: read the district the way it would (offline)
    def one_place(text, prefer=None):
        for name in ("Ri Bhoi", "North Garo Hills", "West Garo Hills"):
            k = text.find(name)
            if k >= 0:
                return name.upper(), "district", text[:k] + " " + text[k + len(name):]
        return None
    monkeypatch.setattr(P, "_c18_one_place", one_place)
    for q, order in (("what is the top block in Ri Bhoi", "desc"), ("the weakest block in North Garo Hills?", "asc"),
                     ("which block is the highest in West Garo Hills", "desc")):
        out = P._c18_edit_rank_in_place(q, _frame())
        assert out is not None, q
        kind, new = out
        assert kind == "rank" and new.qtype == "ranking" and new.group == "block" and new.order == order
        assert new.filters.get("district") and not new.filters.get("block")
        assert new.measure_text == "MGNREGA person-days"
    # a measure / year of its own, or no rank word: not this edit
    assert P._c18_edit_rank_in_place("which block has the most expenditure in Ri Bhoi", _frame()) is None
    assert P._c18_edit_rank_in_place("blocks in Ri Bhoi", _frame()) is None


def test_block_ranking_inside_listed_districts():
    s = P._c16_shape("Which block has the highest: PMAY-G houses completed in West Garo Hills and Ri Bhoi",
                     {"district": ["WEST GARO HILLS", "RI BHOI"]})
    assert s and s["qtype"] == "ranking" and s["group"] == "block"
    assert P._c16_shape("Which district has the highest PMAY-G houses completed in West Garo Hills and Ri Bhoi",
                        {"district": ["WEST GARO HILLS", "RI BHOI"]}) is None
