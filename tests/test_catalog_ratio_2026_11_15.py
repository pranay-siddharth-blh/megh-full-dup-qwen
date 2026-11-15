"""Metric catalogue: money per counted thing ("average Focus Legacy amount per producer group") is the money total
divided by the count, both verified totals, in one query (2026-11-15; model-on gold bank W3-RT-04: the model averaged
the payment rows, ₹29,347, instead of total / distinct producer groups, ₹36,238). Offline, the catalogue faked."""
import pytest

from app import metric_catalog as mc
from app import pipeline as p
from app.config import settings


def _m(key, expr, unit, alias, phrases, cols):
    return mc.Metric(key=key, scheme="Focus Legacy", display_name=key, expression=expr, base_object="curated.v_focus_legacy",
                     unit=unit, notes="", alias=alias, phrases=tuple(mc._phrase(x) for x in phrases),
                     columns=frozenset(cols))


@pytest.fixture
def catalogue(monkeypatch):
    cols = {"amount_disbursed", "pg_id", "lgd_district", "lgd_block", "year_key", "financial_year_short"}
    ms = [_m("fl_amount", "SUM(amount_disbursed)", "rupees", "total_disbursed_cr", ["amount", "amount disbursed"], cols),
          _m("fl_pg", "COUNT(DISTINCT pg_id)", "Producer Groups", "pg_count", ["producer group", "pgs"], cols)]
    st = {"metrics": {m.key: m for m in ms}, "by_scheme": {"Focus Legacy": ms}, "loaded": True,
          "no_block_level": frozenset(), "single_year": frozenset(),
          "verified": {t: {} for t in mc.QUERY_TYPES}}
    for m in ms:
        st["verified"]["total"][m.key] = {"evidence": "test"}
    monkeypatch.setattr(mc, "_state", st)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return st


def _er(**r):
    return {"resolved": r, "display": {"district": str(r["district"]).title()} if r.get("district") else {}}


def test_money_per_counted_thing_is_one_ratio_query(catalogue):
    plan = p._metric_catalog_plan("What is the average Focus Legacy amount per producer group in East Jaintia Hills "
                                  "across all financial years?", ["Focus Legacy"], _er(district="EAST JAINTIA HILLS"))
    assert plan["status"] == "built" and plan["qtype"] == "ratio" and plan["verified"], plan
    sql, params, shown = plan["query"]
    assert sql.startswith("/* metric:fl_amount/fl_pg ratio */ SELECT ROUND(((SELECT SUM(amount_disbursed)")
    assert "/ NULLIF(((SELECT COUNT(DISTINCT pg_id)" in sql and "AS amount_per_producer_group_rupees" in sql
    assert "10000000" not in sql                         # the raw rupees, not the crore-rounded figure
    assert params == ["EAST JAINTIA HILLS", "EAST JAINTIA HILLS"] and "$" not in shown


def test_order_matters_count_per_money_is_not_a_ratio(catalogue):
    assert p._c16_ratio_pair("producer groups per amount", list(catalogue["metrics"].values())) is None


def test_plural_stem_matches_singular():
    assert mc._stem("beneficiaries") == mc._stem("beneficiary") == "beneficiary"
    assert mc._stem("households") == "household" and mc._stem("class") == "class"


def test_ratio_answer_reads_as_an_average():
    a = p._framed_fallback([{"amount_per_producer_group_rupees": 36238.02}], ["Focus Legacy"],
                           {"district": "EAST JAINTIA HILLS"})
    assert "the average is ₹36,238.02 per producer group" in a


# ── review 2026-11-15: shapes that are NOT one money-per-thing figure ──
@pytest.mark.parametrize("q", [
    "Average Focus Legacy amount per producer group per year in Ri Bhoi across all financial years",
    "Focus Legacy amount per producer group per block in Ri Bhoi in FY 2023-24",
    "Focus Legacy amount per producer group in each district",
    "Yearly Focus Legacy amount per producer group",
])
def test_not_a_single_ratio(catalogue, q):
    assert p._c16_ratio_pair(q, list(catalogue["metrics"].values())) is None, q


def test_a_rate_is_never_the_money_numerator():
    rate = mc.Metric(key="mgnrega_cost_per_person_day", scheme="MGNREGA", display_name="x", expression="SUM(a)/SUM(b)",
                     base_object="v", unit="rupees per person-day", notes="", alias="cost_per_person_day_rupees",
                     phrases=(), columns=frozenset())
    assert mc.money_scale(rate) is None
