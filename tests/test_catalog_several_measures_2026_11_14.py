"""Metric catalogue, 14 Nov 2026: two or three measures asked together ("producer groups and total disbursed",
"expenditure and person days in Ri Bhoi in 2023-24") are read by ONE query of scalar subqueries, each the verified
total query of its own measure. Anything one of them could not answer alone the same way declines (model path).
Offline: the catalogue is faked, as in test_metric_catalog_2026_10_26."""
import pytest

from app import metric_catalog as mc
from app import pipeline as p
from app.config import settings

_COLS = {
    "curated.v_expenditure": {"total_exp", "lgd_district", "lgd_block", "village_code", "year_key",
                              "financial_year_short"},
    "curated.v_employment": {"person_days", "job_cards_issued_total", "lgd_district", "lgd_block",
                             "village_code", "year_key", "financial_year_short"},
}


def _metric(key, expr, base, unit, phrases):
    return mc.Metric(key=key, scheme="MGNREGA", display_name=key, expression=expr, base_object=base, unit=unit,
                     notes="", alias=mc._alias(key, "mgnrega_", unit),
                     phrases=tuple(mc._phrase(x) for x in phrases), columns=frozenset(_COLS[base]))


@pytest.fixture
def catalogue(monkeypatch):
    ms = [
        _metric("mgnrega_total_expenditure", "SUM(total_exp)", "curated.v_expenditure", "lakh rupees",
                ["MGNREGA Total Expenditure", "expenditure"]),
        _metric("mgnrega_employment_generated", "SUM(person_days)", "curated.v_employment", "person-days",
                ["person days"]),
        _metric("mgnrega_job_card_stock", "SUM(job_cards_issued_total)", "curated.v_employment", "job cards",
                ["job cards"]),
    ]
    state = {"metrics": {m.key: m for m in ms}, "by_scheme": {"MGNREGA": ms}, "loaded": True,
             "no_block_level": frozenset(), "single_year": frozenset({"mgnrega_job_card_stock"}),
             "verified": {t: {} for t in mc.QUERY_TYPES}}
    for m in ms:
        state["verified"]["total"][m.key] = {"evidence": "test"}
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return state


def _er(**resolved):
    display = {"district": str(resolved["district"]).title()} if resolved.get("district") else {}
    return {"resolved": resolved, "display": display, "notes": []}


def test_match_lists_the_measures_in_question_order(catalogue):
    m = mc.match("person days and expenditure in Ri Bhoi", "MGNREGA")
    assert m.status == "several"
    assert [x.key for x in m.several] == ["mgnrega_employment_generated", "mgnrega_total_expenditure"]


def test_two_totals_are_one_query(catalogue):
    plan = p._metric_catalog_plan("MGNREGA expenditure and person days in Ri Bhoi in 2023-24", ["MGNREGA"],
                                  _er(district="RI BHOI", year_key=2023))
    assert plan["status"] == "built" and plan["verified"] and plan["qtype"] == "total"
    sql, params, shown = plan["query"]
    assert sql.startswith("/* metric:mgnrega_total_expenditure+mgnrega_employment_generated total */ SELECT (")
    assert sql.count("SELECT") == 3 and sql.count("FROM") == 2
    # each subquery has its own place and year, renumbered after the one before it
    assert "$1" in sql and "$2" in sql and "$3" in sql and "$4" in sql
    assert params == ["RI BHOI", 2023, "RI BHOI", 2023]
    assert "$" not in shown and "'RI BHOI'" in shown
    assert mc.is_catalog_sql(sql)


def test_combine_renumbers_without_touching_longer_numbers(catalogue):
    m = catalogue["metrics"]["mgnrega_total_expenditure"]
    part = ("/* metric:x total */ SELECT a FROM t WHERE b = $1 AND c = $2", [1, 2], "SELECT a FROM t")
    sql, params, _ = mc.combine_totals([(m, part), (m, part)])
    assert "b = $3 AND c = $4" in sql and params == [1, 2, 1, 2]


@pytest.mark.parametrize("q,er,why", [
    ("MGNREGA expenditure and person days by district in 2023-24", {"year_key": 2023}, "only totals"),
    ("MGNREGA expenditure and average person days in 2023-24", {"year_key": 2023}, "asks more"),
    ("MGNREGA expenditure and person days", {}, "no year named"),
    ("MGNREGA expenditure and job cards across all financial years", {}, "one financial year at a time"),
])
def test_declines_what_one_measure_could_not_answer(catalogue, q, er, why):
    plan = p._metric_catalog_plan(q, ["MGNREGA"], _er(**er))
    assert plan["query"] is None and why in plan["reason"], plan


def test_one_unverified_measure_declines_the_whole_question(catalogue):
    del catalogue["verified"]["total"]["mgnrega_employment_generated"]
    plan = p._metric_catalog_plan("MGNREGA expenditure and person days in 2023-24", ["MGNREGA"], _er(year_key=2023))
    assert plan["query"] is None and not plan["verified"]


def test_a_single_measure_with_and_still_declines(catalogue):
    """The one-measure path is unchanged: "and" with only one measure named is something more to compute."""
    plan = p._metric_catalog_plan("MGNREGA expenditure and wages in 2023-24", ["MGNREGA"], _er(year_key=2023))
    assert plan["query"] is None
