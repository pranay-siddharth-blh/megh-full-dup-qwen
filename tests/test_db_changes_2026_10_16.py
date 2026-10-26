"""The ingestion team's database changes of 2026-10-15/16 (CHATBOT_DB_CHANGES_2026-10-16.md):
units and exact VALUES lists in semantic.column_catalog, metric definitions, never-row-join
rules (semantic.v_join_rules), scheme_specific locked from megh_readonly, CM Elevate
applications = COUNT(DISTINCT request_id), no meta.* access. Regression tests against the
real functions."""
import asyncio

import pytest

from app import annotations, schema_introspect, sql_guard
from app import pipeline as p


@pytest.fixture
def catalog(monkeypatch):
    """A loaded catalog cache, restored afterwards."""
    saved = dict(schema_introspect._cache)
    monkeypatch.setattr(schema_introspect, "_cache", {**saved, "loaded": True, "tables": [], "glossary": [],
                                                      "metrics": [], "columns": [], "join_rules": {},
                                                      "coverage": {}, "denied": set()})
    return schema_introspect._cache


# ── UNIT / VALUES / metric definitions reach the SQL prompt ──────────────────
def test_catalog_block_carries_unit_and_values(catalog):
    catalog["columns"] = [
        {"table_schema": "curated", "table_name": "v_expenditure", "column_name": "total_exp",
         "description": None, "data_quality_note": None, "unit": "lakh rupees", "sample_values": None},
        {"table_schema": "curated", "table_name": "v_cm_elevate", "column_name": "current_file_status",
         "description": None, "data_quality_note": "API DRIFT …", "unit": None,
         "sample_values": ["forward", "resubmit", "sendback to vdv/citizen"]},
    ]
    mg = schema_introspect.catalog_block(["MGNREGA"])
    assert "v_expenditure.total_exp: UNIT: lakh rupees." in mg
    ce = schema_introspect.catalog_block(["CM Elevate"])
    assert "VALUES (complete list, use these exact literals): 'forward', 'resubmit', " \
           "'sendback to vdv/citizen'" in ce and "API DRIFT" in ce


def test_catalog_block_reads_the_real_metric_columns(catalog):
    # metric_key / sql_expression: the old reader looked for metric / formula and printed nothing
    catalog["metrics"] = [
        {"metric_key": "cm_elevate_applications", "sql_expression": "COUNT(DISTINCT request_id)",
         "base_object": "curated.v_cm_elevate", "unit": "applications", "subject_area": "cm_elevate",
         "filters_required": "Count with COUNT(DISTINCT request_id), never COUNT(*).", "is_active": True},
        {"metric_key": "nrlm_shgs", "sql_expression": "COUNT(*)", "subject_area": "nrlm", "is_active": True},
    ]
    ce = schema_introspect.catalog_block(["CM Elevate"])
    assert "cm_elevate_applications = COUNT(DISTINCT request_id) FROM curated.v_cm_elevate [applications]" in ce
    assert "nrlm_shgs" not in ce                       # another scheme's metric stays out
    assert "cm_elevate_applications" not in schema_introspect.catalog_block(["PMAY-G"])


def test_catalog_block_skips_fact_private_and_locked_columns(catalog):
    catalog["denied"] = {("curated", "v_cm_elevate", "scheme_specific")}
    catalog["columns"] = [
        {"table_schema": "curated", "table_name": t, "column_name": c, "description": None,
         "data_quality_note": "NOTE " + c, "unit": None, "sample_values": None}
        for t, c in (("v_cm_elevate", "scheme_specific"), ("fact_cm_elevate_application", "request_id"),
                     ("v_cm_elevate", "data_verified"))]
    ce = schema_introspect.catalog_block(["CM Elevate"])
    assert "NOTE data_verified" in ce and "NOTE scheme_specific" not in ce and "fact_cm_elevate" not in ce


def test_join_rules_are_loaded_symmetric(monkeypatch, catalog):
    async def rows(sql, params=None):
        return [{"object_ref": "curated.v_employment", "never_row_join_with": ["curated.v_expenditure"]}]
    monkeypatch.setattr(schema_introspect.db, "fetch_rows_readonly", rows)
    asyncio.run(schema_introspect._load_join_rules())
    r = schema_introspect.never_row_join()
    assert "curated.v_expenditure" in r["curated.v_employment"]
    assert "curated.v_employment" in r["curated.v_expenditure"]


def test_live_schema_hides_private_tables_and_locked_columns(monkeypatch, catalog):
    async def rows(sql, params=None):
        if "has_column_privilege" in sql:
            return [{"s": "curated", "t": "v_cm_elevate", "col": "scheme_specific"}]
        if "information_schema.columns" in sql:
            return [{"table_schema": "curated", "table_name": t, "column_name": c, "data_type": "text",
                     "is_nullable": "YES"}
                    for t, c in (("v_cm_elevate", "request_id"), ("v_cm_elevate", "scheme_specific"),
                                 ("bridge_pg_bank_history", "account_no"))]
        return []
    monkeypatch.setattr(schema_introspect.db, "fetch_rows_readonly", rows)
    asyncio.run(schema_introspect._load_live_schema())
    live = schema_introspect.live_columns()
    assert [c["column"] for c in live["curated.v_cm_elevate"]] == ["request_id"]
    assert "curated.bridge_pg_bank_history" not in live


# ── privacy tables refused by the SQL guard (KI-004) ─────────────────────────
@pytest.mark.parametrize("sql", ["SELECT account_no FROM curated.bridge_pg_bank_history",
                                 "SELECT COUNT(*) FROM fact_cm_elevate_disbursement",
                                 "SELECT f.amount FROM curated.v_focus_legacy v "
                                 "JOIN curated.fact_focus_legacy_disbursement f USING (pg_id)"])
def test_private_tables_refused(sql):
    with pytest.raises(sql_guard.UnsafeSQLError) as e:
        sql_guard.assert_readonly(sql)
    assert e.value.rule == "private_table"


def test_view_is_not_refused():
    sql_guard.assert_readonly("SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy")


# ── fan-out joins (semantic.v_join_rules) ────────────────────────────────────
_FANOUT = ("SELECT e.lgd_district, SUM(e.person_days), SUM(x.total_exp) FROM curated.v_employment e "
           "JOIN curated.v_expenditure x ON x.year_key = e.year_key AND x.lgd_district = e.lgd_district "
           "GROUP BY 1")
_SAFE = ("WITH e AS (SELECT lgd_district, SUM(person_days) pd FROM curated.v_employment GROUP BY 1), "
         "x AS (SELECT lgd_district, SUM(total_exp) te FROM curated.v_expenditure GROUP BY 1) "
         "SELECT e.lgd_district, pd, te FROM e FULL JOIN x USING (lgd_district)")


def test_fanout_join_flagged_with_fallback_rules(catalog):
    assert p._prohibited_row_join(_FANOUT) == ("curated.v_employment", "curated.v_expenditure")
    assert p._prohibited_row_join(_SAFE) is None
    assert p._prohibited_row_join(
        "SELECT COUNT(*) FROM curated.v_pmay h JOIN curated.v_focus_plus f ON f.village_code = h.village_code")
    # a dimension join is not a fact pair
    assert p._prohibited_row_join("SELECT COUNT(DISTINCT v.request_id) FROM curated.v_cm_elevate v "
                                  "JOIN curated.dim_geography g ON g.geography_key = v.geography_key") is None


def test_fanout_join_uses_loaded_rules(catalog):
    catalog["join_rules"] = {"curated.v_pmay": {"curated.v_nrlm"}, "curated.v_nrlm": {"curated.v_pmay"}}
    assert p._prohibited_row_join("SELECT 1 FROM curated.v_pmay a JOIN curated.v_nrlm b USING (village_code)")
    # with loaded rules, only listed pairs count
    assert p._prohibited_row_join(_FANOUT) is None


def test_locked_column_flagged(catalog):
    catalog["denied"] = {("curated", "v_cm_elevate", "scheme_specific")}
    sql = "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE scheme_specific ->> 'gender_id' = 'Female'"
    assert p._readonly_denied_column_in(sql) == ("v_cm_elevate", "scheme_specific")
    assert p._readonly_denied_column_in("SELECT COUNT(*) FROM curated.v_cm_elevate WHERE sector_id = 'x'") is None


# ── CM Elevate: an application is a distinct request_id ──────────────────────
def test_applications_count_distinct_request_id():
    out = p._cm_elevate_applicants_distinct(
        "How many applications in Ri Bhoi?", ["CM Elevate"],
        "SELECT COUNT(*) AS applications FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'")
    assert "COUNT(DISTINCT request_id)" in out and "COUNT(*)" not in out


def test_scheme_count_on_dimension_untouched():
    sql = ("SELECT (SELECT COUNT(*) FROM curated.dim_cm_elevate_scheme) AS schemes, "
           "COUNT(*) FILTER (WHERE data_verified = 'On Hold') AS on_hold FROM curated.v_cm_elevate")
    out = p._cm_elevate_applicants_distinct("how many schemes and on hold", ["CM Elevate"], sql)
    assert "SELECT COUNT(*) FROM curated.dim_cm_elevate_scheme" in out
    assert "COUNT(DISTINCT request_id) FILTER" in out


# ── CM Elevate: Approved / Rejected and gender are not available; pending is On Hold ──
def test_pending_on_file_status_becomes_on_hold():
    out = p._cm_elevate_decision_status_column(
        ["CM Elevate"], "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_file_status) = 'pending'")
    assert "data_verified = 'On Hold'" in out and "scheme_specific" not in out


def test_approved_is_never_pointed_at_scheme_specific():
    out = p._cm_elevate_decision_status_column(
        ["CM Elevate"], "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE current_file_status = 'approved'")
    assert "scheme_specific" not in out


@pytest.mark.parametrize("q", ["How many CM Elevate applications were approved?",
                               "How many applications were rejected in Ri Bhoi?",
                               "What is the gender split of CM Elevate applicants?",
                               "How many women applied?"])
def test_locked_fields_answered_not_held(q):
    c = p._measure_not_held_gap(q, ["CM Elevate"])
    assert c is not None and c.rule == "measure-not-held"


@pytest.mark.parametrize("q,schemes", [("How many applications are pending?", ["CM Elevate"]),
                                       ("How many applications are on hold?", ["CM Elevate"]),
                                       ("How many Focus Plus applications were approved?", ["Focus Plus"]),
                                       ("How many women got MGNREGA work?", ["MGNREGA"])])
def test_held_fields_still_answered(q, schemes):
    assert p._measure_not_held_gap(q, schemes) is None


def test_sector_queries_use_the_sector_id_column():
    for q, resolved in (("How many applicants are associated with the Piggery sector in North Garo Hills?",
                         {"district": "NORTH GARO HILLS"}),
                        ("How many applications are pending in each sector in East Khasi Hills?",
                         {"district": "EAST KHASI HILLS"})):
        sql, _, _ = p._cme_sector_query(q, ["CM Elevate"], resolved)
        assert "scheme_specific" not in sql and "sector_id" in sql
        assert "COUNT(*) AS" not in sql


# ── the few-shot pool fits the database the chatbot can read ────────────────
def test_few_shots_never_read_meta_or_scheme_specific():
    annotations.load_all()
    for scheme, pool in annotations._few_shot_cache.items():
        for e in pool:
            sql = e.get("sql") or ""
            assert "meta." not in sql and "staging." not in sql, (scheme, e.get("question"))
            if scheme == "CM Elevate":
                assert "scheme_specific" not in sql, e.get("question")
