"""CM Elevate sheet test run 2026-10-10 (Test Case Results - 30th Sep 26.xlsx,
CM-ELEVATE-OFF-001..030): regression tests for the failures, against the real functions."""
import pytest

from app import pipeline as p


# ── "applicants" never rephrased to "applications" (OFF-005) ───────────────
def test_rephrase_keeps_applicants():
    assert p._rephrase_violation("How many applicants are there under each CM ELEVATE program?",
                                 "How many applications are there under each CM Elevate program?") == "measure"


# ── CM Elevate-only vocabulary pins the scheme (OFF-022 / OFF-028) ─────────
@pytest.mark.parametrize("q", ["How many applicants have completed data verification in East Khasi Hills?",
                               "How many applications are pending in each sector in East Khasi Hills?"])
def test_cm_elevate_vocabulary(q):
    assert p._infer_scheme_from_terms(q) == ["CM Elevate"]


# ── a count over a named programme is a figure question (OFF-013) ──────────
def test_programme_count_overrules_scope():
    assert p._overrules_scope_verdict("How many applicants under Meghalaya Dairy Development Scheme belong to "
                                      "Piggery sector?")
    assert not p._overrules_scope_verdict("Who won the last IPL final?")


# ── status distribution is a figure summary (OFF-015) ──────────────────────
def test_status_distribution_is_a_figure_summary():
    assert p._FIGURE_SUMMARY_RE.search("What is the current application status distribution across CM ELEVATE?")


# ── deterministic sector queries (OFF-012 / 014 / 028) ─────────────────────
def test_sector_count_across_programmes():
    sql, params, _ = p._cme_sector_query("How many applicants are associated with the Piggery sector in North Garo Hills?",
                                         ["CM Elevate"], {"district": "NORTH GARO HILLS", "cm_scheme": "x"})
    assert "cme-sector-count" in sql and "scheme_name =" not in sql and params == ["NORTH GARO HILLS", "piggery"]
    a = p._cme_sector_answer("…Piggery sector…", sql, [
        {"scheme_name": "Meghalaya Dairy Development Scheme", "sector_applicants": 1, "sector_recorded": 2},
        {"scheme_name": "Meghalaya Poultry Farming Scheme", "sector_applicants": 2, "sector_recorded": 2}],
        {"district": "North Garo Hills"})
    assert a.startswith("3 CM Elevate applicants in North Garo Hills") and "Poultry Farming 2" in a


def test_sector_pending_every_group():
    sql, params, _ = p._cme_sector_query("How many applications are pending in each sector in East Khasi Hills?",
                                         ["CM Elevate"], {"district": "EAST KHASI HILLS"})
    assert "cme-sector-pending" in sql and "FILTER (WHERE data_verified = 'On Hold')" in sql
    a = p._cme_sector_answer("q", sql, [{"sector": "(not recorded)", "pending_on_hold": 90},
                                        {"sector": "Poultry", "pending_on_hold": 0}], {"district": "East Khasi Hills"})
    assert "(not recorded) 90; Poultry 0" in a and "Total 90" in a


def test_sector_named_programmes_each_stated():
    q = ("How many applicants under Meghalaya Dairy Development Scheme and Meghalaya Poultry Farming Scheme are "
         "associated with Poultry sector in West Khasi Hills?")
    sql, params, _ = p._cme_sector_query(q, ["CM Elevate"], {"district": "WEST KHASI HILLS"})
    assert "cme-sector-programmes" in sql and "UPPER(v.lgd_district) = UPPER($1)" in sql
    assert set(params[1]) == {"Meghalaya Dairy Development Scheme", "Meghalaya Poultry Farming Scheme"}
    a = p._cme_sector_answer(q, sql, [
        {"scheme_name": "Meghalaya Dairy Development Scheme", "sector_applicants": 0, "sector_recorded": 4,
         "programme_total": 15},
        {"scheme_name": "Meghalaya Poultry Farming Scheme", "sector_applicants": 8, "sector_recorded": 11,
         "programme_total": 81}], {"district": "West Khasi Hills"})
    assert "**Dairy Development**: 0" in a and "**Poultry Farming**: 8" in a and "Combined: 8" in a


def test_sector_query_not_for_programme_only_questions():
    assert p._cme_sector_query("How many applicants are there under Piggery scheme in Ri Bhoi?",
                               ["CM Elevate"], {"district": "RI BHOI"}) is None


# ── two named districts are both kept (OFF-027) ───────────────────────────
def test_scan_districts_keeps_both_and_skips_nested_names():
    from app.entity_resolver import load_all, scan_districts
    load_all()
    q = ("Compare applicant counts for PRIME Small Enterprise Empowerment and Development (SEED) and Meghalaya "
         "Piggery Development Scheme across Eastern West Khasi Hills and East Garo Hills.")
    assert [d.upper() for d in scan_districts(q, "CM Elevate")] == ["EASTERN WEST KHASI HILLS", "EAST GARO HILLS"]
    assert len(scan_districts("How many applicants are there in South West Garo Hills?", "CM Elevate")) == 1


# ── programme x sector rows state each programme's total (OFF-025) ─────────
def test_programme_sector_answer_states_programme_totals():
    rows = [{"scheme_name": "Meghalaya Piggery Development Scheme", "sector": "(not recorded)",
             "applicant_count": 1935, "pending_applications": 395},
            {"scheme_name": "Meghalaya Poultry Farming Scheme", "sector": "(not recorded)",
             "applicant_count": 233, "pending_applications": 46},
            {"scheme_name": "Meghalaya Poultry Farming Scheme", "sector": "Poultry",
             "applicant_count": 8, "pending_applications": 2}]
    a = p._cme_programme_sector_answer(rows, {"district": "Ri Bhoi"})
    assert "**Poultry Farming** — total applicant count 241, pending applications 48" in a
    assert "**Piggery Development** — applicant count 1,935, pending applications 395" in a
    # one row per programme, or another label column: not this shape
    assert p._cme_programme_sector_answer(rows[:2], {}) is None
    assert p._cme_programme_sector_answer([dict(r, lgd_district="RI BHOI") for r in rows], {}) is None
