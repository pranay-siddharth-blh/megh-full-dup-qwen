"""Metric catalogue, 15 Nov 2026: two or three measures BY one grouping ("PMAY-G houses sanctioned vs completed by
district in a grouped bar chart", "CM Elevate Legacy subsidy and loan disbursed by scheme as a stacked bar chart") are
ONE grouped query with one value column per measure (metric_catalog.build_several), when the measures share one
view and each is verified for a breakdown. Measures on different views decline (the model path answers). A shared
noun left out ("houses sanctioned vs completed") is written out before matching (metric_catalog.expand_elision).
Offline: the catalogue is faked, as in test_catalog_several_measures_2026_11_14."""
import pytest

from app import metric_catalog as mc
from app import pipeline as p
from app.config import settings

_COLS = {
    "curated.v_pmay": {"is_completed", "is_in_progress", "lgd_district", "lgd_block", "village_code", "year_key"},
    "curated.v_expenditure": {"total_exp", "lgd_district", "lgd_block", "village_code", "year_key"},
    "curated.v_employment": {"person_days", "lgd_district", "lgd_block", "village_code", "year_key"},
}


def _metric(key, scheme, prefix, expr, base, unit, phrases):
    return mc.Metric(key=key, scheme=scheme, display_name=key, expression=expr, base_object=base, unit=unit,
                     notes="", alias=mc._alias(key, prefix, unit),
                     phrases=tuple(mc._phrase(x) for x in phrases), columns=frozenset(_COLS[base]))


@pytest.fixture
def catalogue(monkeypatch):
    pm = [
        _metric("pmay_houses_sanctioned", "PMAY-G", "pmay_", "COUNT(*)", "curated.v_pmay", "houses",
                ["houses sanctioned", "sanctioned houses", "houses", "sanction"]),
        _metric("pmay_houses_completed", "PMAY-G", "pmay_", "COUNT(*) FILTER (WHERE is_completed)", "curated.v_pmay",
                "houses", ["houses completed", "completed houses", "houses built"]),
        _metric("pmay_completion_rate", "PMAY-G", "pmay_", "ROUND(100.0*COUNT(*) FILTER (WHERE is_completed)"
                "/NULLIF(COUNT(*),0),1)", "curated.v_pmay", "percent", ["completion rate", "houses completed"]),
        _metric("pmay_houses_in_progress", "PMAY-G", "pmay_", "COUNT(*) FILTER (WHERE is_in_progress)",
                "curated.v_pmay", "houses", ["houses in progress"]),
    ]
    mg = [
        _metric("mgnrega_total_expenditure", "MGNREGA", "mgnrega_", "SUM(total_exp)", "curated.v_expenditure",
                "lakh rupees", ["expenditure"]),
        _metric("mgnrega_employment_generated", "MGNREGA", "mgnrega_", "SUM(person_days)", "curated.v_employment",
                "person-days", ["person days"]),
    ]
    ms = pm + mg
    state = {"metrics": {m.key: m for m in ms}, "by_scheme": {"PMAY-G": pm, "MGNREGA": mg}, "loaded": True,
             "no_block_level": frozenset(), "single_year": frozenset(),
             "verified": {t: {} for t in mc.QUERY_TYPES}}
    for m in ms:
        state["verified"]["total"][m.key] = {"evidence": "test"}
        state["verified"]["breakdown"][m.key] = {"evidence": "test"}
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return state


def _er(**resolved):
    display = {"district": str(resolved["district"]).title()} if resolved.get("district") else {}
    return {"resolved": resolved, "display": display, "notes": []}


def test_elision_writes_out_the_shared_noun(catalogue):
    q = "Compare PMAY-G houses sanctioned vs completed by district"
    assert mc.expand_elision(q, "PMAY-G") == "Compare PMAY-G houses sanctioned vs houses completed by district"
    # the other way round: "<word> and <phrase>"
    assert mc.expand_elision("PMAY-G sanctioned and completed houses", "PMAY-G") \
        == "PMAY-G sanctioned houses and completed houses"


@pytest.mark.parametrize("q", [
    "PMAY-G houses completed by district",              # nothing joined
    "PMAY-G houses sanctioned and Ri Bhoi",             # the joined word makes no phrase
    "PMAY-G houses sanctioned vs houses completed",     # already written out (the word after the join is taken)
])
def test_elision_writes_nothing_otherwise(catalogue, q):
    assert mc.expand_elision(q, "PMAY-G") is None


def test_two_measures_by_district_are_one_grouped_query(catalogue):
    plan = p._metric_catalog_plan(
        "Compare PMAY-G houses sanctioned vs completed by district in a grouped bar chart across all financial years",
        ["PMAY-G"], _er())
    assert plan["status"] == "built" and plan["verified"] and plan["qtype"] == "breakdown", plan
    sql, params, shown = plan["query"]
    assert sql.startswith("/* metric:pmay_houses_sanctioned+pmay_houses_completed breakdown */ SELECT lgd_district AS "
                          "district, COUNT(*) AS houses_sanctioned, COUNT(*) FILTER (WHERE is_completed) AS "
                          "houses_completed")
    assert sql.count("SELECT") == 1 and "GROUP BY lgd_district" in sql and "lgd_district IS NOT NULL" in sql
    assert params == [] and mc.is_catalog_sql(sql)
    # the completed column is the measure's own breakdown, the count is never the completion rate
    assert "completion_rate" not in sql


def test_grouped_query_keeps_the_place_and_year_filters(catalogue):
    plan = p._metric_catalog_plan("PMAY-G houses sanctioned and houses completed by block in 2023-24",
                                  ["PMAY-G"], _er(district="RI BHOI", year_key=2023))
    assert plan["status"] == "built" and plan["verified"], plan
    sql, params, _ = plan["query"]
    assert "GROUP BY lgd_block" in sql and params == ["RI BHOI", 2023]


def test_one_value_column_per_measure_equals_each_breakdown(catalogue):
    """Same WHERE, same GROUP BY: each column is the measure's own single breakdown."""
    ms = [catalogue["metrics"]["pmay_houses_sanctioned"], catalogue["metrics"]["pmay_houses_completed"]]
    f = {"district": "RI BHOI"}
    sql, params, _ = mc.build_several(ms, f, "block")
    for m in ms:
        one, ps, _ = mc.build(m, f, "block", qtype="breakdown")
        assert ps == params
        assert one.split("\nFROM", 1)[1] == sql.split("\nFROM", 1)[1]


@pytest.mark.parametrize("q,er,why", [
    ("MGNREGA expenditure and person days by district in 2023-24", {"year_key": 2023}, "not one view"),
    ("PMAY-G houses sanctioned and houses completed by district", {}, "no year named"),
    ("PMAY-G houses sanctioned and average houses completed by district across all financial years", {},
     "asks more"),
    ("Which district has the most PMAY-G houses sanctioned and houses completed across all financial years", {},
     "only totals or one breakdown"),
])
def test_declines(catalogue, q, er, why):
    plan = p._metric_catalog_plan(q, ["PMAY-G"] if "PMAY" in q else ["MGNREGA"], _er(**er))
    assert plan["query"] is None and why in plan["reason"], plan


def test_one_measure_not_verified_for_a_breakdown_declines(catalogue):
    del catalogue["verified"]["breakdown"]["pmay_houses_completed"]
    plan = p._metric_catalog_plan("PMAY-G houses sanctioned vs completed by district across all financial years",
                                  ["PMAY-G"], _er())
    assert plan["query"] is None and not plan["verified"] and "not verified for a breakdown" in plan["reason"]


def test_build_several_refuses_different_views_and_one_measure(catalogue):
    m = catalogue["metrics"]
    assert mc.build_several([m["mgnrega_total_expenditure"], m["mgnrega_employment_generated"]], {}, "district") \
        is None
    assert mc.build_several([m["pmay_houses_sanctioned"]], {}, "district") is None
    assert mc.build_several([m["pmay_houses_sanctioned"], m["pmay_houses_completed"]], {}, None) is None


def test_single_measure_build_is_unchanged(catalogue):
    m = catalogue["metrics"]["pmay_houses_completed"]
    sql, params, shown = mc.build(m, {"district": "RI BHOI"}, "block", qtype="breakdown")
    assert sql == ("/* metric:pmay_houses_completed breakdown */ SELECT lgd_block AS block, COUNT(*) FILTER (WHERE "
                   "is_completed) AS houses_completed\nFROM curated.v_pmay\nWHERE UPPER(lgd_district) = UPPER($1) AND "
                   "lgd_block IS NOT NULL\nGROUP BY lgd_block ORDER BY lgd_block")
