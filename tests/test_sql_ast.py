"""app/sql_ast.py (SQLGlot inspection / rewriting) and the authorization checks
built on it. The SQL path reads queries on the parsed tree, never with regex;
these cases are the ones the old text patterns got wrong (2026-10-15 audit):
UPPER(lgd_district), every value of an IN / ANY list, an OR branch, and words
inside string literals or comments."""
from app import auth, sql_ast


def _officer(districts=("EAST KHASI HILLS",), blocks=()):
    return auth.UserScope(user_id="u", role="district_officer", granularity_cap="village",
                          schemes=["MGNREGA", "PMAY-G"],
                          geographies={"districts": list(districts), "blocks": list(blocks)})


# ── helpers ─────────────────────────────────────────────────────────────────

def test_filter_values_sees_every_form():
    q = ("SELECT 1 FROM curated.v WHERE UPPER(lgd_district) = 'A' AND lgd_district IN ('B', 'C') "
         "OR lgd_district = ANY(ARRAY['D']) OR TRIM(lgd_district) LIKE 'E%'")
    assert sorted(sql_ast.filter_values(q, "lgd_district")) == ["A", "B", "C", "D", "E%"]


def test_literal_and_comment_are_not_columns():
    q = "SELECT 'lgd_village_name' AS label, COUNT(*) FROM curated.v -- village_code\n"
    assert not sql_ast.references_column(q, "lgd_village_name", "village_code")


def test_structure_helpers():
    q = ("WITH t AS (SELECT lgd_block, SUM(total_exp) s FROM curated.v_expenditure GROUP BY lgd_block) "
         "SELECT * FROM t ORDER BY s DESC LIMIT 5")
    assert sql_ast.has_cte(q) and sql_ast.groups_by(q, "lgd_block")
    assert sql_ast.tables(q) == {"v_expenditure"} and sql_ast.reads_table(q, "curated.v_expenditure")
    assert sql_ast.has_aggregate(q, "sum") and sql_ast.outer_limit(q) == 5
    assert sql_ast.first_keyword(q) == "WITH"


def test_numeric_filter_values():
    q = "SELECT 1 FROM curated.v WHERE year_key BETWEEN 2021 AND 2023 OR year_key IN (2019)"
    assert sorted(sql_ast.filter_values(q, "year_key", numeric=True)) == ["2019", "2021", "2023"]


def test_rewrites_keep_unchanged_text_and_edit_the_tree():
    q = "select  *  from curated.v where lgd_district = 'east khasi hills'"
    assert sql_ast.replace_string_literals(q, lambda v: None) == q          # no change, no reformat
    out = sql_ast.replace_string_literals(q, str.upper, ["lgd_district"])
    assert sql_ast.filter_values(out, "lgd_district") == ["EAST KHASI HILLS"]
    assert sql_ast.outer_limit(sql_ast.set_limit(q, 10)) == 10
    assert sql_ast.filter_values(sql_ast.add_condition(q, "year_key = 2023"), "year_key", numeric=True) == ["2023"]


def test_unparseable_text_is_not_a_tree():
    assert sql_ast.parse("SELECT FROM WHERE ((((") == [] or not sql_ast.is_parseable("((((")
    assert sql_ast.replace_string_literals("((((", str.upper) == "(((("


# ── authorization on the tree ───────────────────────────────────────────────

def _check(sql, resolved=None, scope=None):
    return auth.authorize(scope or _officer(), schemes=["MGNREGA"], resolved_entities=resolved or {}, sql=sql)


def test_upper_district_filter_is_seen():
    d = _check("SELECT SUM(total_exp) FROM curated.v_expenditure WHERE UPPER(lgd_district) = 'WEST GARO HILLS'")
    assert not d.allow and d.check == "geography" and "WEST GARO HILLS" in d.reason


def test_second_value_of_in_list_is_checked():
    d = _check("SELECT SUM(total_exp) FROM curated.v_expenditure "
               "WHERE lgd_district IN ('EAST KHASI HILLS', 'WEST GARO HILLS')")
    assert not d.allow and "WEST GARO HILLS" in d.reason


def test_or_branch_is_checked():
    d = _check("SELECT SUM(total_exp) FROM curated.v_expenditure WHERE lgd_district = 'EAST KHASI HILLS' "
               "OR UPPER(lgd_district) = 'RI BHOI'")
    assert not d.allow and "RI BHOI" in d.reason


def test_own_district_is_allowed():
    d = _check("SELECT SUM(total_exp) FROM curated.v_expenditure WHERE UPPER(lgd_district) = 'EAST KHASI HILLS'")
    assert d.allow and d.query_granularity == "district"


def test_unparseable_sql_is_refused_for_a_restricted_user():
    d = _check("SELECT SUM(total_exp FROM curated.v_expenditure WHERE lgd_district = 'X'")
    assert not d.allow and d.check == "geography"


def test_granularity_from_columns_not_text():
    assert auth.infer_granularity({}, "SELECT lgd_block, COUNT(*) FROM curated.v GROUP BY lgd_block") == "block"
    assert auth.infer_granularity({}, "SELECT 'lgd_block' AS x FROM curated.v") == "state"
    assert auth.infer_granularity({}, "SELECT COUNT(*) FROM curated.v GROUP BY geography_key") == "village"
