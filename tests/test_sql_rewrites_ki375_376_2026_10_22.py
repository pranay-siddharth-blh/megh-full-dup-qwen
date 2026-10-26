"""
Two model-SQL faults found in the D-062 cross-scheme live check (2026-10-22), both
also reachable from a single-scheme question:

KI-375  CM Elevate Legacy: `SUM(sanctioned_amount) - SUM(total_disbursement) AS
        pending_cr` (no ÷1e7) was answered "₹74,976,008.70 crore pending".
KI-376  `GROUP BY lgd_village_name` alone (v_pmay) summed same-named villages of
        different blocks into one row.

Every test calls the real rewrite; nothing needs the DB or a model.
"""
from app import pipeline as p
from app import sql_ast

CML = ["CM Elevate Legacy"]


# ── KI-375 ───────────────────────────────────────────────────────────────────

def test_a_rupee_difference_named_crore_is_divided():
    sql = ("SELECT COUNT(*) AS records, ROUND(SUM(sanctioned_amount) - SUM(total_disbursement), 2) AS pending_cr "
           "FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'EAST KHASI HILLS'")
    out = p._cm_legacy_crore_alias_on_rupees(CML, sql)
    assert "ROUND((SUM(sanctioned_amount) - SUM(total_disbursement)) / 1e7, 2) AS pending_cr" in out
    assert "COUNT(*) AS records" in out


def test_columns_already_in_crore_or_shares_are_left_alone():
    sql = ("SELECT ROUND(SUM(sanctioned_amount) / 1e7, 2) AS sanctioned_cr, "
           "ROUND(100.0 * SUM(total_disbursement) / NULLIF(SUM(sanctioned_amount), 0), 1) AS disbursed_pct, "
           "SUM(total_disbursement) AS total_disbursed FROM curated.v_cm_elevate_disbursement")
    assert p._cm_legacy_crore_alias_on_rupees(CML, sql) == sql


def test_only_cm_elevate_legacy():
    sql = "SELECT SUM(total_disbursement) AS total_cr FROM curated.v_cm_elevate_disbursement"
    assert p._cm_legacy_crore_alias_on_rupees(["PMAY-G"], sql) == sql
    assert "/ 1e7" in p._cm_legacy_crore_alias_on_rupees(CML, sql)


# ── KI-376 ───────────────────────────────────────────────────────────────────

def test_a_village_ranking_by_name_also_groups_by_code_and_block():
    sql = "SELECT lgd_village_name, COUNT(*) AS houses FROM curated.v_pmay GROUP BY lgd_village_name " \
          "ORDER BY houses DESC LIMIT 10"
    out = p._village_rows_by_code(sql)
    assert sql_ast.groups_by(out, "village_code") and sql_ast.groups_by(out, "lgd_block")
    assert {"village_code", "lgd_block"} <= set(sql_ast.output_names(out))
    assert sql_ast.outer_limit(out) == 10


def test_a_ranking_by_code_gets_names_and_leaves_out_the_unmapped_buckets():
    # live 2026-10-22: Focus Plus "top 5 villages" ranked -900010, -900004, ... (Unresolved buckets)
    sql = ("SELECT village_code, SUM(amount_disbursed) AS total_disbursed FROM curated.v_focus_plus "
           "GROUP BY village_code ORDER BY total_disbursed DESC LIMIT 5")
    out = p._village_rows_by_code(sql)
    assert "entity_type <> 'Unresolved'" in out
    assert {"lgd_village_name", "lgd_block"} <= set(sql_ast.output_names(out))


def test_a_placeholder_filter_already_there_is_not_doubled():
    sql = ("SELECT lgd_village_name, village_code, lgd_block, SUM(person_days) AS pd FROM curated.v_employment "
           "WHERE entity_type <> 'Unresolved' GROUP BY lgd_village_name, village_code, lgd_block "
           "ORDER BY pd DESC LIMIT 10")
    assert p._village_rows_by_code(sql) == sql
    by_code = ("SELECT village_code, lgd_village_name, lgd_block, COUNT(*) AS n FROM curated.v_cm_elevate_disbursement "
               "WHERE village_code > 0 GROUP BY village_code, lgd_village_name, lgd_block ORDER BY n DESC")
    assert p._village_rows_by_code(by_code) == by_code


def test_pmay_has_no_placeholder_bucket_and_a_list_is_not_filtered():
    pm = "SELECT lgd_village_name, COUNT(*) AS houses FROM curated.v_pmay GROUP BY lgd_village_name ORDER BY houses DESC"
    assert "entity_type" not in p._village_rows_by_code(pm)
    plain = "SELECT lgd_village_name, COUNT(*) AS n FROM curated.v_focus_legacy GROUP BY lgd_village_name"
    assert "entity_type" not in p._village_rows_by_code(plain)        # no ranking: the c11 rules decide


def test_a_join_keeps_the_names_own_table():
    sql = ("SELECT p.lgd_village_name, COUNT(*) AS n FROM curated.v_pmay p JOIN curated.dim_geography g "
           "ON g.geography_key = p.geography_key GROUP BY p.lgd_village_name")
    out = p._village_rows_by_code(sql)
    assert "p.village_code" in out and "p.lgd_block" in out
    unqualified = sql.replace("p.lgd_village_name", "lgd_village_name")
    assert p._village_rows_by_code(unqualified) == unqualified        # whose village_code: not guessed


def test_no_village_grouping_is_unchanged():
    for sql in ("SELECT lgd_block, COUNT(*) FROM curated.v_pmay GROUP BY lgd_block",
                "SELECT COUNT(*) FROM curated.v_pmay",
                "SELECT DISTINCT lgd_village_name FROM curated.v_pmay"):
        assert p._village_rows_by_code(sql) == sql
