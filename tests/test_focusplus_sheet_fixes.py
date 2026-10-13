"""Focus + sheet test run 2026-10-10 (Test Case Results - 30th Sep 26.xlsx, FOCUS-001..030):
regression tests for the failures, against the real functions."""
from app import pipeline as p


# ── status breakdown for a tranche or a batch (FOCUS-018 / 019) ────────────
def test_status_breakdown_for_a_tranche_is_a_fixed_query():
    sql, params, _ = p._fp_status_cohort_query("Give me the Focus+ status breakdown for Tranch 1.", ["Focus Plus"],
                                               {"tranche_label": "Tranch 1"})
    assert "fp-status-cohort" in sql and "tranche_label = ANY($1::text[])" in sql
    assert "COUNT(DISTINCT beneficiary_key)" in sql and params == [["Tranch 1"]]


def test_status_breakdown_for_a_batch_counts_people_not_payments():
    sql, params, _ = p._fp_status_cohort_query("Give me the Focus+ status breakdown for the 93K batch.",
                                               ["Focus Plus"], {})
    assert "batch_label = ANY($1::text[])" in sql and params == [["93K"]]
    a = p._fp_status_cohort_answer(sql, [{"focus_status": "(not recorded)", "beneficiaries": 93286}], params)
    assert "the 93K batch — 93,286 beneficiaries" in a and "373,144" not in a


def test_tranche4_breakdown_states_both_cohorts():
    sql, params, _ = p._fp_status_cohort_query("Give me the Focus+ status breakdown for Tranche 4.", ["Focus Plus"],
                                               {"tranche_label": "Tranch 4 - Feb-March"})
    a = p._fp_status_cohort_answer(sql, [{"focus_status": "(not recorded)", "beneficiaries": 93286},
                                         {"focus_status": "Pending", "beneficiaries": 11812},
                                         {"focus_status": "Approved", "beneficiaries": 714}], params)
    assert "105,812 beneficiaries" in a and "Pending 11,812" in a and "status not recorded 93,286" in a


def test_status_query_not_for_other_shapes():
    assert p._fp_status_cohort_query("Give me the status-wise breakdown of Focus+ beneficiaries.",
                                     ["Focus Plus"], {}) is None   # no tranche / batch: the model path
    assert p._fp_status_cohort_query("Give me the verification status breakdown for Tranch 4.", ["Focus Plus"],
                                     {"tranche_label": "Tranch 4 - Feb-March"}) is None
    assert p._fp_status_cohort_query("Give me the status breakdown for Tranch 4.", ["CM Elevate"],
                                     {"tranche_label": "x"}) is None
