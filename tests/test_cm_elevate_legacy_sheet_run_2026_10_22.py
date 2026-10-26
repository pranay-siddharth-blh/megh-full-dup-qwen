"""CM Elevate Legacy sheet re-test 2026-10-22 (raw_uc/Use_Cases_-_CM_Elevate.xlsx, TC-01..36):
regression tests for KI-381 (constituency), KI-382 (briefing overview), KI-383 (no records),
KI-384 (ROLLUP total row), against the real functions. The D-064 routing tests are in
test_cm_elevate_legacy.py §2."""
import pytest

from app import entity_resolver, pipeline as p, sql_ast

L = ["CM Elevate Legacy"]
AC = {"resolved": {"assembly_constituency": "DADENGGRE"}}


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()


# ── KI-381: a resolved constituency filtered as a district / block ──────────
@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) AS records\nFROM curated.v_cm_elevate_disbursement\nWHERE UPPER(lgd_district) = UPPER('DADENGGRE')\nLIMIT 1",
    "SELECT ROUND(SUM(total_disbursement) / 1e7, 2) AS total_disbursed_cr FROM curated.v_cm_elevate_disbursement v "
    "WHERE UPPER(lgd_block) = UPPER('DADENGGRE') AND financial_year_short = '2024-25' LIMIT 1",
    "SELECT lgd_block, COUNT(*) AS records FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'DADENGGRE' "
    "GROUP BY lgd_block",
])
def test_constituency_as_place_filter_is_rewritten_to_the_ac_join(sql):
    out = p._cm_legacy_qualify_shared_geo_cols(L, p._cm_legacy_ac_as_place_filter(L, AC, sql))
    assert sql_ast.tables(out, qualified=True) == {"curated.v_cm_elevate_disbursement", "curated.dim_geography"}
    assert "DADENGGRE" in {v.upper() for v in sql_ast.filter_values(out, "ac_name")}
    assert not sql_ast.filter_values(out, "lgd_district", "lgd_block")
    assert p._cm_legacy_ac_filter_missing(L, AC, out) is None
    # the year filter is kept
    if "2024-25" in sql:
        assert "2024-25" in sql_ast.filter_values(out, "financial_year_short")


def test_a_dropped_constituency_is_sent_back_to_repair():
    # in a chat the statewide FY 2025-26 figures were given as Mahendraganj's
    sql = "SELECT COUNT(*) AS records FROM curated.v_cm_elevate_disbursement WHERE financial_year_short = '2025-26'"
    issue = p._cm_legacy_ac_filter_missing(L, {"resolved": {"assembly_constituency": "MAHENDRAGANJ"}}, sql)
    assert issue and "MAHENDRAGANJ" in issue and "ac_name" in issue


def test_the_rewrite_is_cm_elevate_legacy_only():
    sql = "SELECT COUNT(*) FROM curated.v_focus_legacy WHERE lgd_district = 'DADENGGRE'"
    assert p._cm_legacy_ac_as_place_filter(["Focus Legacy"], AC, sql) == sql
    other = "SELECT COUNT(*) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'RI BHOI'"
    assert p._cm_legacy_ac_as_place_filter(L, AC, other) == other          # not the constituency's name


def test_verifier_join_complaint_is_discarded_only_for_the_documented_query():
    doc = ("SELECT COUNT(*) AS records FROM curated.v_cm_elevate_disbursement v JOIN curated.dim_geography g "
           "ON g.geography_key = v.geography_key WHERE UPPER(g.ac_name) = 'DADENGGRE'")
    assert p._cm_legacy_ac_verifier_complaint_is_false("Check 1: prohibited join path to dim_geography", L, AC, doc)
    assert not p._cm_legacy_ac_verifier_complaint_is_false("Check 3 fails: the metric should be SUM", L, AC, doc)
    bad = doc.replace("g.geography_key = v.geography_key", "g.lgd_district = v.lgd_district")
    assert not p._cm_legacy_ac_verifier_complaint_is_false("Check 1: prohibited join", L, AC, bad)


def test_ac_name_is_compared_case_insensitively():
    sql = ("SELECT 1 FROM curated.v_cm_elevate_disbursement v JOIN curated.dim_geography g "
           "ON g.geography_key = v.geography_key WHERE g.ac_name = 'Dadenggre'")
    assert "UPPER(g.ac_name) = 'DADENGGRE'" in p._cm_legacy_ac_name_case(L, sql)


# ── KI-384: the ROLLUP total row is a total, not a category ─────────────────
_ROLLUP = ("SELECT COALESCE(lgd_district, 'ALL DISTRICTS') AS lgd_district, COUNT(*) AS records "
           "FROM curated.v_cm_elevate_disbursement GROUP BY ROLLUP (lgd_district) "
           "ORDER BY GROUPING(lgd_district), records DESC")
_ROWS = [{"lgd_district": "WEST GARO HILLS", "records": 493}, {"lgd_district": "RI BHOI", "records": 486},
         {"lgd_district": "EAST JAINTIA HILLS", "records": 35}, {"lgd_district": "ALL DISTRICTS", "records": 1014}]


def test_rollup_total_row_is_split_off():
    detail, totals = p._c12s_rollup_split(_ROLLUP, _ROWS)
    assert [r["lgd_district"] for r in totals] == ["ALL DISTRICTS"] and len(detail) == 3
    shape = p._answer_shape("district-wise summary of applications", _ROLLUP, detail)
    text = p._shaped_fallback(shape, detail, L, {})
    assert "1,014" in text and "3 districts" in text and "ALL DISTRICTS" not in text


def test_a_multi_measure_breakdown_lists_every_measure():
    # TC-36 "summary of applications, sanctioned cases and total disbursement" listed the records only
    rows = [{"lgd_district": "A", "records": 5, "sanctioned_records": 4, "total_disbursed_cr": 1.25},
            {"lgd_district": "B", "records": 3, "sanctioned_records": 3, "total_disbursed_cr": 0.5},
            {"lgd_district": "C", "records": 1, "sanctioned_records": 1, "total_disbursed_cr": 0.1}]
    sql = ("SELECT lgd_district, COUNT(*) AS records, COUNT(sanctioned_amount) AS sanctioned_records, "
           "ROUND(SUM(total_disbursement)/1e7, 2) AS total_disbursed_cr FROM curated.v_cm_elevate_disbursement "
           "GROUP BY lgd_district")
    shape = p._answer_shape("district-wise summary", sql, rows)
    text = p._shaped_fallback(shape, rows, L, {})
    line_a = next(ln for ln in text.splitlines() if "**A**" in ln)
    assert "5" in line_a and "4" in line_a and "1.25" in line_a


def test_no_rollup_no_split():
    sql = "SELECT lgd_district, COUNT(*) AS records FROM curated.v_cm_elevate_disbursement GROUP BY lgd_district"
    assert p._c12s_rollup_split(sql, _ROWS) == (_ROWS, [])


def test_rollup_with_a_bare_null_key():
    sql = "SELECT lgd_district, COUNT(*) AS n FROM curated.v_cm_elevate_disbursement GROUP BY ROLLUP (lgd_district)"
    rows = [{"lgd_district": "A", "n": 2}, {"lgd_district": "B", "n": 1}, {"lgd_district": None, "n": 3}]
    assert p._c12s_rollup_split(sql, rows) == (rows[:2], rows[2:])


# ── "which / across / each schemes" inside a CM Elevate Legacy chat (one-chat run TC-13/19/25) ──
@pytest.mark.parametrize("q", ["Which schemes have the highest number of applications?",
                               "How many sanctioned applications are there for each scheme?",
                               "Compare the number of applications across schemes for FY 2024-25."])
def test_scheme_words_in_a_legacy_chat_mean_its_sub_schemes(q):
    from types import SimpleNamespace as NS
    s = NS(last_turn=NS(schemes=L, route="data", raw_question="x", question="x"))
    out = p._each_scheme_in_cm_thread(q, s)
    assert "under CM Elevate Legacy" in out
    from app import cross_scheme
    assert cross_scheme.detect(out, [n for n, m in p._SCHEME_NAME_MATCHER.items() if m.search(out)]) is None


def test_scheme_words_outside_a_cm_chat_stay_cross_scheme():
    from types import SimpleNamespace as NS
    s = NS(last_turn=NS(schemes=["PMAY-G"], route="data", raw_question="PMAY-G houses", question="x"))
    q = "Which schemes have the highest number of applications?"
    assert p._each_scheme_in_cm_thread(q, s) == q
    q2 = "Which schemes does MGNREGA cover?"
    assert p._each_scheme_in_cm_thread(q2, NS(last_turn=NS(schemes=L, route="data", raw_question="x",
                                                            question="x"))) == q2


# ── KI-383: nothing recorded is said plainly ────────────────────────────────
def test_no_records_sentence():
    s = p._cml_no_records_sentence([{"total_disbursed_cr": None}], {"constituency": "MAHENDRAGANJ", "year": "FY 2025-26"})
    assert s.startswith("No CM Elevate Legacy records") and "Mahendraganj" in s and "FY 2025-26" in s
    assert "null" not in s.lower() and "₹0" not in s
    assert p._cml_no_records_sentence([{"records": 0, "total_cr": None}], {"block": "UMLING"})
    assert p._cml_no_records_sentence([{"records": 5, "total_cr": None}], {}) is None     # records exist
    assert p._cml_no_records_sentence([{"records": 0}], {}) is None                        # a plain 0 count
    assert p._cml_no_records_sentence([{"a": None}, {"a": None}], {}) is None


# ── KI-382: a scheme overview for a briefing is knowledge ───────────────────
@pytest.mark.parametrize("q, knowledge", [
    ("Give me a short overview of CM-ELEVATE that I can use for an official briefing.", True),
    ("Give me a briefing note on MGNREGA for my meeting", True),
    ("Give me an overview of Ri Bhoi", False),                    # a place: figures (D-052)
    ("overview of PMAY-G in Mawsynram", False),
    ("Give me a briefing on MGNREGA performance in 2023-24", False),
])
def test_overview_request_routing_rule(q, knowledge):
    is_kb = (bool(p._OVERVIEW_REQUEST.search(q)) and not p._C14_COUNT_WORDS.search(q)
             and not p._C14_FIGURE_WORDS.search(q) and not p.named_places(q)
             and not p._overview_names_a_place(q))
    assert is_kb is knowledge
