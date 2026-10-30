"""
CM Elevate application counts are valid-only by default (user decision 2026-10-30, D-B1-CME-01):
`applications_default` in data/cm_elevate/cmelevate_pending_rule.yaml, read at runtime by
app/cme_pending_rule.py. A question that names a verification state is answered exactly as
asked; one that asks for ALL applications gets every application and a single total split by
`verification_states` plus "not recorded". The fixed CM Elevate queries carry the same default
and their answers say "valid applications".

No model or DB.
    python -m pytest tests/test_cme_valid_default_2026_10_30.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cme_pending_rule as rule  # noqa: E402
from app import pipeline as p  # noqa: E402

CME = ["CM Elevate"]
DEFAULT = rule.default_sql()                 # from the YAML: data_verified = 'Valid'
V = "curated.v_cm_elevate"


def test_default_comes_from_the_yaml():
    assert DEFAULT == "data_verified = 'Valid'" and rule.default_column() == "data_verified"
    assert rule.default_text() == "valid"
    assert rule.verification_states() == ("data_verified", ["Valid", "On Hold", "Wrong", "Invalid"])


def test_changing_the_yaml_changes_the_default(monkeypatch):
    monkeypatch.setattr(rule, "_load", lambda: {"applications_default": {"column": "data_verified", "label": "checked",
                                                                          "values": ["Valid", "Wrong"]},
                                                 "verification_states": None, "pending_rule": []})
    assert rule.default_sql() == "data_verified IN ('Valid', 'Wrong')" and rule.default_text() == "checked"
    sql = f"SELECT COUNT(DISTINCT request_id) AS applications FROM {V} WHERE lgd_district = 'RI BHOI'"
    out = p._cm_elevate_valid_default("How many applications in Ri Bhoi?", CME, sql)
    assert "data_verified IN ('Valid', 'Wrong')" in out
    monkeypatch.setattr(rule, "_load", lambda: {"applications_default": None, "verification_states": None, "pending_rule": []})
    assert rule.default_sql() == "" and p._cm_elevate_valid_default("How many applications?", CME, sql) == sql


# ── the model-SQL guard ──────────────────────────────────────────────────────
def test_a_simple_count_gets_the_default_in_its_where():
    sql = f"SELECT COUNT(DISTINCT request_id) AS applications FROM {V} WHERE lgd_district = 'RI BHOI'"
    out = p._cm_elevate_valid_default("How many CM Elevate applications are there in Ri Bhoi?", CME, sql)
    assert "lgd_district = 'RI BHOI' AND data_verified = 'Valid'" in out


def test_a_grouped_count_gets_the_default_too():
    sql = f"SELECT scheme_name, COUNT(DISTINCT request_id) AS applications FROM {V} GROUP BY scheme_name ORDER BY 2 DESC"
    out = p._cm_elevate_valid_default("Applications by scheme", CME, sql)
    assert "WHERE data_verified = 'Valid'" in out and "GROUP BY scheme_name" in out


def test_a_join_reads_the_view_through_a_valid_only_subquery():
    sql = (f"SELECT g.ac_name, COUNT(DISTINCT v.request_id) AS applicants FROM {V} v "
           "JOIN curated.dim_geography g ON g.geography_key = v.geography_key GROUP BY g.ac_name")
    out = p._cm_elevate_valid_default("Applicants by assembly constituency", CME, sql)
    assert "(SELECT * FROM curated.v_cm_elevate WHERE data_verified = 'Valid') AS v" in out
    assert "JOIN curated.dim_geography" in out and out.count("data_verified") == 1


def test_a_cte_reads_the_view_through_a_valid_only_subquery():
    sql = (f"WITH t AS (SELECT lgd_district, COUNT(*) AS n FROM {V} GROUP BY 1) "
           "SELECT lgd_district, n FROM t ORDER BY n DESC LIMIT 3")
    out = p._cm_elevate_valid_default("Top 3 districts by applications", CME, sql)
    assert "(SELECT * FROM curated.v_cm_elevate WHERE data_verified = 'Valid') AS v_cm_elevate" in out


def test_a_query_that_already_tests_verification_is_left_alone():
    for sql in (f"SELECT COUNT(*) FROM {V} WHERE data_verified = 'On Hold'",
                f"SELECT data_verified, COUNT(*) FROM {V} GROUP BY 1",
                f"SELECT COUNT(*) FILTER (WHERE data_verified = 'Valid') AS valid FROM {V}"):
        assert p._cm_elevate_valid_default("How many applications?", CME, sql) == sql


@pytest.mark.parametrize("q", ["How many applications are on hold?",          # on hold is pending: the rule carries the default
                               "How many invalid applications are there?",
                               "How many applications have the verification outcome Wrong?",
                               "How many applications were verified?",
                               "Show all CM Elevate applications by district",
                               "How many applications including invalid ones?",
                               "Applications irrespective of verification status"])
def test_a_verification_state_or_all_applications_skips_the_default(q):
    sql = f"SELECT COUNT(DISTINCT request_id) AS applications FROM {V}"
    if "on hold" in q:
        assert p._cme_names_verification_state(q) is False       # pending path, not a state question
    else:
        assert p._cm_elevate_valid_default(q, CME, sql) == sql


def test_not_for_other_schemes_or_non_counts():
    sql = f"SELECT COUNT(*) FROM {V}"
    assert p._cm_elevate_valid_default("How many applications?", ["CM Elevate Legacy"], sql) == sql
    listing = f"SELECT DISTINCT scheme_name FROM {V} ORDER BY 1"
    assert p._cm_elevate_valid_default("Which schemes are there?", CME, listing) == listing


# ── all applications asked ───────────────────────────────────────────────────
def test_all_applications_drops_the_default_and_splits_the_total():
    sql = f"SELECT COUNT(DISTINCT request_id) AS applications FROM {V} WHERE lgd_district = 'RI BHOI' AND data_verified = 'Valid'"
    out = p._cm_elevate_all_applications("How many applications are there in Ri Bhoi, including invalid ones?", CME, sql)
    assert "data_verified = 'Valid') AS valid" in out and "'On Hold') AS on_hold" in out
    assert "'Wrong') AS wrong" in out and "'Invalid') AS invalid" in out and "IS NULL) AS not_recorded" in out
    assert out.count("WHERE lgd_district = 'RI BHOI'") == 1 and "RI BHOI' AND data_verified" not in out


def test_all_applications_on_a_grouped_query_only_drops_the_default():
    sql = f"SELECT scheme_name, COUNT(*) AS n FROM {V} WHERE data_verified = 'Valid' GROUP BY scheme_name"
    out = p._cm_elevate_all_applications("all CM Elevate applications by scheme", CME, sql)
    assert "data_verified" not in out and "GROUP BY scheme_name" in out


def test_all_applications_leaves_an_ordinary_question_alone():
    sql = f"SELECT COUNT(*) FROM {V} WHERE data_verified = 'Valid'"
    assert p._cm_elevate_all_applications("How many applications are there?", CME, sql) == sql


def test_the_two_guards_together():
    """The c11 order: all-applications first, then the default — an "all" question ends with no
    default; an ordinary one ends with it."""
    sql = f"SELECT COUNT(DISTINCT request_id) AS applications FROM {V}"
    q_all = "How many CM Elevate applications in all, valid and invalid?"
    out = p._cm_elevate_valid_default(q_all, CME, p._cm_elevate_all_applications(q_all, CME, sql))
    assert "AS valid" in out and "v_cm_elevate WHERE" not in out
    q = "How many CM Elevate applications are there?"
    out = p._cm_elevate_valid_default(q, CME, p._cm_elevate_all_applications(q, CME, sql))
    assert out.endswith("WHERE data_verified = 'Valid'")


# ── the fixed queries carry the default ──────────────────────────────────────
def test_fixed_queries_carry_the_default():
    sql, params, _ = p._cme_workflow_query("How many CM Elevate applications are pending in Ri Bhoi?", {"district": "RI BHOI"})
    assert f"WHERE lgd_district = $1 AND {DEFAULT}" in sql and params == ["RI BHOI"]
    sql, params, _ = p._cme_sector_query("How many applicants are associated with the Piggery sector in North Garo Hills?",
                                         CME, {"district": "NORTH GARO HILLS"})
    assert f"AND {DEFAULT}" in sql
    sql, params, _ = p._cme_sector_query(
        "How many applicants under Meghalaya Dairy Development Scheme and Meghalaya Poultry Farming Scheme are "
        "associated with Poultry sector in West Khasi Hills?", CME, {"district": "WEST KHASI HILLS"})
    assert "AND v.data_verified = 'Valid'" in sql
    sql, params, _ = p._cme_notime_query("Show the monthly totals of CM Elevate applications in Ri Bhoi", {"district": "RI BHOI"})
    assert sql is not None and DEFAULT in sql


def test_fixed_queries_drop_the_default_when_all_or_a_state_is_asked():
    sql, _, _ = p._cme_workflow_query("How many of all CM Elevate applications are pending?", {})
    assert f" AND {DEFAULT}" not in sql.split("FROM curated.v_cm_elevate")[1]
    assert p._cme_unit("How many of all CM Elevate applications are pending?") == "applications"
    assert p._cme_unit("How many applications are pending?") == "valid applications"
