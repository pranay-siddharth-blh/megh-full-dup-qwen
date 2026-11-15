"""Fixes from the first model-on gold bank on the merged code (merged-1, 15 Nov 2026), offline.

- W3-RT-03: the verifier's "does not EXPLICITLY filter … in the WHERE clause" about a share computed with
  FILTER (WHERE lgd_district = …) was not recognised as a false complaint; the repair moved the district into the
  WHERE clause and the share became 100.0% (truth 19.4%).
- RAG-D10: COUNT(*) AS disbursements was read as money by its name: "₹3,85,671 (≈ ₹3.86 lakh) disbursements".
"""
from app import pipeline as p

SHARE_SQL = ("SELECT ROUND(CAST(100.0 * COUNT(*) FILTER(WHERE lgd_district = 'WEST GARO HILLS') / NULLIF(COUNT(*), 0) "
             "AS DECIMAL), 1) AS pct_in_west_garo_hills FROM curated.v_pmay")
ISSUE = ("Check 2: The RESOLVED ENTITIES block specifies lgd_district = 'WEST GARO HILLS', but the SQL does not "
         "explicitly filter on this resolved entity in the WHERE clause. Instead, it uses a FILTER clause.")


def test_share_with_filter_clause_is_not_repaired_into_a_where():
    assert p._verifier_missing_geo_is_false(ISSUE, {"district": "WEST GARO HILLS"}, SHARE_SQL)


def test_a_really_missing_district_still_raises():
    assert not p._verifier_missing_geo_is_false(ISSUE, {"district": "WEST GARO HILLS"},
                                                "SELECT COUNT(*) FROM curated.v_pmay")


def test_count_of_disbursements_is_not_money():
    assert p._c17_unit_by_name("disbursements", "Focus Plus") is None
    for money in ("total_disbursements", "disbursement_amount", "amount_disbursed", "total_disbursed"):
        assert p._c17_unit_by_name(money, "Focus Plus") == "rupees", money
    a = "Focus Plus recorded ₹3,85,671 (≈ ₹3.86 lakh) disbursements in 12 districts."
    out = p._c12_normalise_figures(a, [{"disbursements": 385671, "districts": 12}], ["Focus Plus"])
    assert out == "Focus Plus recorded 3,85,671 disbursements in 12 districts."


def test_real_money_keeps_its_rupees():
    out = p._c12_normalise_figures("Focus Plus paid ₹1,19,74,00,000 in all.", [{"amount_disbursed": 1197400000}],
                                   ["Focus Plus"])
    assert out == "Focus Plus paid ₹1,19,74,00,000 (≈ ₹119.74 crore) in all."
