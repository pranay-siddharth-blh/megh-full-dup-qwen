"""The SQLGlot read-only guard on model-generated SQL (app/sql_guard.py, used by
app/db.run_readonly). Replaced the keyword regex in db._assert_safe, which
rejected 'delete pending' inside a string literal, missed a DELETE inside a
CTE, and skipped the row cap whenever "limit" appeared anywhere in the text
(a credit_limit column, a subquery's LIMIT)."""
import pytest

from app import db
from app.sql_guard import UnsafeSQLError, assert_readonly, prepare_readonly

CAP = 1000

ALLOWED = [
    "SELECT a FROM t",
    "SELECT a FROM t;",
    "SELECT a FROM t; -- done",
    "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT status FROM t WHERE note = 'delete pending'",
    "SELECT created_at, updated_by FROM t",
    "SELECT x->>'k', y::numeric, COUNT(*) FILTER (WHERE z) FROM t "
    "WHERE n ILIKE '%a%' GROUP BY 1, 2 ORDER BY 3 DESC NULLS LAST",
    "SELECT scheme_name FROM v WHERE scheme_name = 'Chief Minister''s Green Taxi Scheme'",
    # curated / semantic, qualified or through the pool's search_path
    "SELECT COUNT(*) FROM curated.v_cm_elevate",
    "SELECT * FROM semantic.metric_catalog",
    "SELECT * FROM CURATED.V_FOCUS_PLUS",
    "SELECT g.lgd_district FROM curated.dim_geography g JOIN curated.v_focus_plus f USING (village_code)",
    "WITH pg_counts AS (SELECT 1 AS n) SELECT * FROM pg_counts",
    "SELECT * FROM generate_series(1, 3) AS s(n)",
    "SELECT unnest(ARRAY[1, 2])",
]


def test_schema_check_can_be_skipped():
    # data/cm_elevate/prompt_assembler.py reports schemas with its own rules
    assert_readonly("SELECT * FROM meta.v_reconciliation_cm_elevate", schemas=None)

BLOCKED = {
    "multiple_statements": ["SELECT 1; DROP TABLE t", "SELECT 1; SELECT 2"],
    "not_a_select": ["DROP TABLE t", "INSERT INTO t VALUES (1)", "UPDATE t SET a = 1",
                     "DELETE FROM t", "VACUUM", "EXPLAIN SELECT 1", "COPY t TO '/tmp/x'",
                     "GRANT SELECT ON t TO u", "BEGIN", "SET ROLE postgres",
                     "REFRESH MATERIALIZED VIEW v", "CALL p()"],
    "write_operation": ["WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
                        "SELECT * INTO newt FROM t", "SELECT a FROM t FOR UPDATE"],
    "forbidden_function": ["SELECT pg_sleep(10)",
                           "SELECT query_to_xml('DELETE FROM t', true, true, '')",
                           "SELECT pg_terminate_backend(1)"],
    "schema_not_allowed": ["SELECT * FROM app.users",
                           "SELECT * FROM meta.v_reconciliation_cm_elevate",
                           "SELECT * FROM raw.source_rows",
                           "SELECT * FROM staging.quarantine",
                           "SELECT * FROM pg_catalog.pg_roles",
                           "SELECT * FROM information_schema.tables",
                           "SELECT * FROM pg_roles",
                           "SELECT usename FROM pg_stat_activity",
                           "SELECT * FROM otherdb.curated.v_focus_plus",
                           "SELECT * FROM curated.v_focus_plus f JOIN app.users u ON u.user_id = f.beneficiary_key",
                           "WITH x AS (SELECT * FROM app.users) SELECT * FROM x",
                           "SELECT * FROM curated.v_focus_plus WHERE beneficiary_key IN (SELECT user_id FROM app.users)"],
    "empty": ["", "   ;  "],
    "parse_error": ["SELECT FROM WHERE (",
                    "SELECT a FROM t WHERE s = 'Chief Minister's Green Taxi Scheme'"],
}


@pytest.mark.parametrize("sql", ALLOWED)
def test_read_only_queries_pass(sql):
    assert_readonly(sql)


@pytest.mark.parametrize("rule,sql", [(r, s) for r, sqls in BLOCKED.items() for s in sqls])
def test_unsafe_queries_are_blocked_with_their_rule(rule, sql):
    with pytest.raises(UnsafeSQLError) as e:
        assert_readonly(sql)
    assert e.value.rule == rule


def test_db_still_exports_the_error():
    assert db.UnsafeSQLError is UnsafeSQLError
    assert not db.is_connection_error(UnsafeSQLError("x"))


@pytest.mark.parametrize("sql,expected", [
    ("SELECT a FROM t", f"SELECT a FROM t\nLIMIT {CAP}"),
    ("SELECT a FROM t;", f"SELECT a FROM t\nLIMIT {CAP}"),
    ("SELECT a FROM t ORDER BY a -- trailing comment", f"SELECT a FROM t ORDER BY a\nLIMIT {CAP}"),
    # "limit" in a column name or a subquery used to suppress the cap
    ("SELECT credit_limit FROM t", f"SELECT credit_limit FROM t\nLIMIT {CAP}"),
    ("SELECT * FROM (SELECT a FROM t LIMIT 5) s", f"SELECT * FROM (SELECT a FROM t LIMIT 5) s\nLIMIT {CAP}"),
    ("WITH x AS (SELECT a FROM t LIMIT 5) SELECT * FROM x",
     f"WITH x AS (SELECT a FROM t LIMIT 5) SELECT * FROM x\nLIMIT {CAP}"),
    # an outer limit within the cap is left alone
    ("SELECT a FROM t LIMIT 50", "SELECT a FROM t LIMIT 50"),
    ("SELECT a FROM t LIMIT 50;", "SELECT a FROM t LIMIT 50"),
    ("SELECT a FROM t FETCH FIRST 10 ROWS ONLY", "SELECT a FROM t FETCH FIRST 10 ROWS ONLY"),
    ("SELECT 1 UNION SELECT 2 LIMIT 3", "SELECT 1 UNION SELECT 2 LIMIT 3"),
    # one above the cap, or not a plain number, is wrapped and capped
    ("SELECT a FROM t LIMIT 5000", f"SELECT * FROM (\nSELECT a FROM t LIMIT 5000\n) AS _capped LIMIT {CAP}"),
    ("SELECT a FROM t LIMIT ALL", f"SELECT * FROM (\nSELECT a FROM t LIMIT ALL\n) AS _capped LIMIT {CAP}"),
])
def test_row_cap(sql, expected):
    assert prepare_readonly(sql, CAP) == expected


def test_capped_text_is_itself_valid():
    for sql in ("SELECT a FROM t", "SELECT a FROM t LIMIT 5000", "SELECT a FROM t; -- x"):
        assert_readonly(prepare_readonly(sql, CAP))
