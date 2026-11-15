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


def _finish(sql, rows, answer):
    r = {"route": "data", "answer": answer, "rows": rows, "data": rows, "schemes": ["Focus Plus"], "sql": sql,
         "resolved_entities": {"district": "RI BHOI"}}
    p._finish_data_result(r)
    return r["answer"]


def test_a_counted_column_is_not_money_whatever_its_name():
    """Decided from the SQL (review 2026-11-15), not the alias: COUNT(*) AS disbursements is a count."""
    out = _finish("SELECT COUNT(*) AS disbursements, COUNT(DISTINCT lgd_district) AS districts FROM curated.v_focus_plus",
                  [{"disbursements": 385671, "districts": 12}],
                  "Focus Plus recorded ₹3,85,671 (≈ ₹3.86 lakh) disbursements in 12 districts.")
    assert "3,85,671 disbursements" in out and "₹3,85,671" not in out and "lakh" not in out


def test_a_rupee_sum_named_disbursements_keeps_its_rupees():
    out = _finish("SELECT SUM(amount_disbursed) AS disbursements FROM curated.v_focus_plus WHERE lgd_district = 'RI BHOI'",
                  [{"disbursements": 38567100}], "Focus Plus disbursements in Ri Bhoi total ₹3,85,67,100.")
    assert "₹3,85,67,100 (≈ ₹3.86 crore)" in out


def test_count_columns_read_from_the_sql():
    assert p._c12_count_columns("SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE x) AS m, SUM(a) AS s FROM t") == {"n", "m"}
    assert p._c12_count_columns("not sql") == frozenset()


def test_real_money_keeps_its_rupees():
    out = p._c12_normalise_figures("Focus Plus paid ₹1,19,74,00,000 in all.", [{"amount_disbursed": 1197400000}],
                                   ["Focus Plus"])
    assert out == "Focus Plus paid ₹1,19,74,00,000 (≈ ₹119.74 crore) in all."


def test_a_misplaced_filter_complaint_is_kept():
    """review 2026-11-15: 'does not correctly / properly filter' means the filter is in the wrong place."""
    sql = ("SELECT COUNT(*) FILTER (WHERE lgd_district='WEST GARO HILLS') AS registered_wgh, "
           "COUNT(*) FILTER (WHERE house_status='Completed') AS completed FROM curated.v_pmay WHERE year_key=2023")
    for issue in ("The SQL does not correctly filter the completed count to West Garo Hills (WEST GARO HILLS).",
                  "The SQL does not properly apply the WEST GARO HILLS district filter to the completed count."):
        assert not p._verifier_missing_geo_is_false(issue, {"district": "WEST GARO HILLS"}, sql), issue
