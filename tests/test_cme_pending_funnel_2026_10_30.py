"""
CM Elevate "pending" (user decision 2026-10-30, D-B1-CME-01): data verified Valid -> file status
Pending or Send Back; every CM Elevate count is valid-only by default. "On hold" questions mean the same
and NEVER read data_verified; level-wise questions are the rule by current_level. The rule is READ
FROM THE KNOWLEDGE BASE (cmelevate_pending_rule.yaml) through app/cme_pending_rule.py — nothing is
typed into code, so these tests read the rule the same way and also prove that changing the YAML
steps changes the SQL.

file_status lived inside curated.v_cm_elevate.scheme_specific, which the chatbot's database role
has not been allowed to read since 2026-10-16 (KI-624). Since 2026-11-11 the DB team exposes a plain
file_status column (readable; KI-707) and the YAML points at it. Every change is gated on
cme_pending_rule.readable(): every column the rule needs is among the live columns the read-only
role may SELECT. These tests open the gate by patching schema_introspect.live_columns(). With it
closed, a pending / on-hold question gets "not available" + the rule + the recorded workflow
figures — no guard and no answer falls back to data_verified = 'On Hold'.

No model or DB.
    python -m pytest tests/test_cme_pending_funnel_2026_10_30.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cme_pending_rule as rule  # noqa: E402
from app import pipeline as p  # noqa: E402
from app import schema_introspect as si  # noqa: E402

CME = ["CM Elevate"]
SEED = "PRIME Small Enterprise Empowerment and Development (SEED)"
PIG = "Meghalaya Piggery Development Scheme"
RULE_SQL = rule.sql()                       # from the YAML, not typed here
RULE_TEXT = rule.text()
OPEN = {"curated.v_cm_elevate": [{"column": c} for c in ("request_id", "data_verified", "current_file_status",
                                                         "current_level", "file_status")]}
# the view before the plain file_status column existed (only the locked JSON column held it)
NO_FS = {"curated.v_cm_elevate": [{"column": c} for c in ("request_id", "data_verified", "current_file_status",
                                                          "current_level")]}
LOCKED = {"curated.v_cm_elevate": [{"column": c} for c in ("request_id", "data_verified", "current_file_status")]}
WF = "/* cme-sector-workflow */ SELECT 1"
ONE = {"pending": 7341, "sent_back": 90, "forward": 8942, "resubmit": 3, "sendback": 3, "applications": 8948}
REC = {"forward": 8942, "resubmit": 3, "sendback": 3, "applications": 8948}          # a locked row


@pytest.fixture
def readable(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: OPEN)


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)


# ── the rule comes from the knowledge base ───────────────────────────────────
def test_rule_is_read_from_the_yaml_steps():
    steps = rule.steps()
    # KI-707 (2026-11-11): the knowledge base points at the plain file_status column the DB team exposed
    assert [s["column"] for s in steps] == ["data_verified", "file_status"]
    assert RULE_SQL == "data_verified = 'Valid' AND file_status IN ('Pending', 'Send Back')"
    assert RULE_TEXT == "Pending means: data verified Valid, and file status Pending or Send Back."
    assert rule.columns() == {"data_verified", "file_status"}
    assert rule.default_sql() == "data_verified = 'Valid'" and rule.default_text() == "valid"
    assert rule.verification_states() == ("data_verified", ["Valid", "On Hold", "Wrong", "Invalid"])
    assert rule.json_keys() == set() and rule.file_status_column() == "file_status"


def test_changing_the_yaml_steps_changes_the_sql(monkeypatch, readable):
    plain = [{"column": "data_verified", "label": "data verified", "values": ["Valid"]},
             {"column": "file_status", "label": "file status", "values": ["Pending"]}]
    monkeypatch.setattr(rule, "steps", lambda: plain)
    assert rule.sql() == "data_verified = 'Valid' AND file_status = 'Pending'"
    assert rule.text() == "Pending means: data verified Valid, and file status Pending."
    assert rule.columns() == {"data_verified", "file_status"} and rule.json_keys() == set()
    # the gate follows the rule: a plain file_status column is not in the live columns -> closed
    monkeypatch.setattr(si, "live_columns", lambda: NO_FS)
    assert not rule.readable()
    monkeypatch.setattr(si, "live_columns", lambda: {"curated.v_cm_elevate": NO_FS["curated.v_cm_elevate"] + [{"column": "file_status"}]})
    assert rule.readable()
    sql, _, _ = p._cme_workflow_query("How many applications are pending?", {})
    assert "FILTER (WHERE data_verified = 'Valid' AND file_status = 'Pending') AS pending" in sql
    assert "FILTER (WHERE file_status = 'Send Back') AS sent_back" in sql


def test_no_rule_means_nothing_is_pending(monkeypatch, readable):
    monkeypatch.setattr(rule, "steps", lambda: [])
    assert rule.sql() == "FALSE" and not rule.readable()


def test_a_malformed_or_missing_yaml_is_survived(monkeypatch, tmp_path):
    monkeypatch.setattr(rule, "RULE_FILE", tmp_path / "missing.yaml")
    monkeypatch.setattr(rule, "_cache", {"mtime": None, "steps": []})
    assert rule.steps() == [] and rule.sql() == "FALSE" and rule.text() == "No pending rule is defined."
    f = tmp_path / "rules.yaml"
    f.write_text("pending_rule:\n- { column: x, values: [1] }\n- { nonsense: 1 }\n", encoding="utf-8")
    monkeypatch.setattr(rule, "RULE_FILE", f)
    monkeypatch.setattr(rule, "_cache", {"mtime": None, "steps": []})
    assert [s["column"] for s in rule.steps()] == ["x"] and rule.sql() == "x = '1'"


# ── the gate ─────────────────────────────────────────────────────────────────
def test_gate_is_closed_without_the_live_schema(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: {})
    assert not si.cme_file_status_readable()
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    assert not si.cme_file_status_readable() and p._cme_pending_target() is None     # never On Hold


def test_gate_opens_when_every_rule_column_is_readable(readable):
    assert si.cme_file_status_readable() and p._cme_pending_target() == RULE_SQL


# ── the fixed workflow query and its answer ──────────────────────────────────
def test_workflow_query_counts_the_rule_first(readable):
    sql, params, _ = p._cme_workflow_query("How many CM Elevate applications are pending?", {})
    assert "cme-sector-workflow" in sql and params == []
    assert f"COUNT(DISTINCT request_id) FILTER (WHERE {RULE_SQL}) AS pending" in sql
    assert "FILTER (WHERE file_status = 'Send Back') AS sent_back" in sql
    assert sql.index("AS pending") < sql.index("AS forward") and "data_verified = 'On Hold'" not in sql


def test_workflow_query_never_reads_data_verified_while_locked(locked):
    for q in ("How many CM Elevate applications are pending?", "How many CM Elevate applications are on hold?"):
        sql, _, _ = p._cme_workflow_query(q, {})
        assert sql is not None and "cme-sector-workflow" in sql
        assert RULE_SQL not in sql and "AS pending" not in sql and "'On Hold'" not in sql


def test_on_hold_is_the_same_query_once_readable(readable):
    sql, params, _ = p._cme_workflow_query("How many CM Elevate applications are on hold in Ri Bhoi?",
                                           {"district": "RI BHOI"})
    assert f"FILTER (WHERE {RULE_SQL}) AS pending" in sql and params == ["RI BHOI"] and "data_verified = 'On Hold'" not in sql
    a = p._cme_sector_answer("How many CM Elevate applications are on hold in Ri Bhoi?", sql,
                             [dict(ONE, pending=2024, applications=2500)], {"district": "Ri Bhoi"})
    assert a.startswith("2,024 CM Elevate applications are pending (on hold) in Ri Bhoi (of 2,500 valid applications).")
    assert RULE_TEXT in a


def test_on_hold_under_a_programme_in_a_district(readable):
    # the live question of 2026-10-30 13:48 ("on hold under poultry scheme in wgh"): the rule, not data_verified
    q = "How many applications are currently on hold under poultry scheme in wgh?"
    sql, params, _ = p._cme_workflow_query(q, {"district": "WEST GARO HILLS", "cm_scheme": "Meghalaya Poultry Farming Scheme"})
    assert params == ["WEST GARO HILLS", ["Meghalaya Poultry Farming Scheme"]]
    assert f"FILTER (WHERE {RULE_SQL}) AS pending" in sql and "data_verified = 'On Hold'" not in sql


def test_pending_answer_states_the_count_the_rule_and_the_leftovers(readable):
    a = p._cme_sector_answer("How many CM Elevate applications are pending?", WF, [dict(ONE)], {})
    assert a.startswith("7,341 CM Elevate applications are pending across Meghalaya (of 8,948 valid applications).")
    assert RULE_TEXT in a and "data verification is On Hold, Invalid or Wrong" in a and "doesn't record" not in a


def test_pending_answer_in_a_place_under_a_programme(readable):
    a = p._cme_sector_answer("How many applications are pending under Piggery in Ri Bhoi?", WF,
                             [dict(ONE, pending=1463, applications=1944)], {"district": "Ri Bhoi", "cm_scheme": PIG})
    assert a.startswith(f"1,463 CM Elevate applications are pending in Ri Bhoi under {PIG} (of 1,944 valid applications).")


def test_pending_ranked_by_programme(readable):
    q = "Which CM ELEVATE programs have the highest number of pending applications?"
    sql, _, _ = p._cme_workflow_query(q, {})
    assert "scheme_name AS grp" in sql and "ORDER BY 2 DESC, 1" in sql and sql.index("AS pending") < sql.index("AS forward")
    a = p._cme_sector_answer(q, sql, [dict(ONE, grp=SEED, pending=3146), dict(ONE, grp=PIG, pending=2430)], {})
    assert a.startswith("Pending CM Elevate applications across Meghalaya, by programme (highest first):")
    assert a.index("3,146") < a.index("2,430") and "Total 5,576." in a and RULE_TEXT in a


def test_pending_at_a_level_filters_the_level(readable):
    sql, params, _ = p._cme_workflow_query("How many CM ELEVATE applications are pending at level 2?", {})
    assert "LOWER(current_level) = $1" in sql and params == ["level2"] and "AS grp" not in sql
    assert f"FILTER (WHERE {RULE_SQL}) AS pending" in sql
    sql2, params2, _ = p._cme_workflow_query("pending applications in level-1 in Ri Bhoi", {"district": "RI BHOI"})
    assert params2 == ["RI BHOI", "level1"]


def test_level_wise_pending_groups_by_level(readable):
    q = "Show the level-wise pending CM Elevate applications"
    sql, _, _ = p._cme_workflow_query(q, {})
    assert "LOWER(current_level) AS grp" in sql and "GROUP BY 1 ORDER BY 1" in sql
    rows = [dict(ONE, grp="level0", pending=3), dict(ONE, grp="level1", pending=7025), dict(ONE, grp="level2", pending=309)]
    a = p._cme_sector_answer(q, sql, rows, {})
    assert a.startswith("Pending CM Elevate applications across Meghalaya, by level: Level 0 3; Level 1 7,025; Level 2 309. Total 7,337.")


def test_level_questions_take_the_pending_path_while_locked_too(locked):
    sql, params, _ = p._cme_workflow_query("How many applications are pending at level 2?", {})
    assert sql is not None and params == ["level2"] and "'On Hold'" not in sql


def test_sent_back_is_the_file_status_decision(readable):
    a = p._cme_sector_answer("How many applications were sent back?", WF, [dict(ONE)], {})
    assert a.startswith("90 CM Elevate applications across Meghalaya have the file status Send Back (of 8,948 valid applications)")
    assert "counted among the 7,341 pending" in a


def test_the_locked_answer_says_not_available_and_never_on_hold(locked):
    a = p._cme_sector_answer("How many CM Elevate applications are pending?", WF, [dict(REC)], {})
    assert a.startswith(RULE_TEXT) and "pending count is not available across Meghalaya" in a
    assert "8,948 valid applications" in a and "8,942 forward" in a and "3 resubmit" in a
    assert "data verification" not in a and "doesn't record" not in a
    b = p._cme_sector_answer("How many applications are currently on hold under poultry scheme in wgh?", WF,
                             [dict(REC, applications=120, forward=118, resubmit=1, sendback=1)],
                             {"district": "West Garo Hills", "cm_scheme": "Meghalaya Poultry Farming Scheme"})
    assert "on-hold count is not available in West Garo Hills under Meghalaya Poultry Farming Scheme" in b
    assert "120 valid applications" in b and "On Hold" not in b


def test_the_locked_grouped_answer_lists_applications_per_group(locked):
    q = "Which CM ELEVATE programs have the highest number of pending applications?"
    rows = [dict(REC, grp=SEED, applications=3500), dict(REC, grp=PIG, applications=2600)]
    a = p._cme_sector_answer(q, "/* cme-sector-workflow */ SELECT scheme_name AS grp", rows, {})
    assert "pending count is not available" in a and "by programme:" in a and "3,500" in a and "Total 6,100." in a


# ── pending by sector ────────────────────────────────────────────────────────
def test_sector_pending_counts_the_rule(readable):
    sql, params, _ = p._cme_sector_query("How many applications are pending in each sector in Eastern West Khasi Hills?",
                                         CME, {"district": "EASTERN WEST KHASI HILLS"})
    assert "cme-sector-pending" in sql and f"FILTER (WHERE {RULE_SQL}) AS pending" in sql and "On Hold" not in sql
    a = p._cme_sector_answer("q", sql, [{"sector": "(not recorded)", "pending": 289, "applications": 306}],
                             {"district": "Eastern West Khasi Hills"})
    assert a.startswith("Pending CM Elevate applications by sector in Eastern West Khasi Hills: (not recorded) 289. Total 289.")
    assert RULE_TEXT in a


def test_sector_pending_while_locked_never_reads_data_verified(locked):
    sql, _, _ = p._cme_sector_query("How many applications are pending in each sector in Ri Bhoi?", CME, {"district": "RI BHOI"})
    assert "cme-sector-pending" in sql and "'On Hold'" not in sql and "AS applications" in sql
    a = p._cme_sector_answer("q", sql, [{"sector": "(not recorded)", "applications": 2000}], {"district": "Ri Bhoi"})
    assert "pending by sector is not available in Ri Bhoi" in a and "(not recorded) 2,000" in a and RULE_TEXT in a


# ── the model-SQL guards ─────────────────────────────────────────────────────
TAIL = " file_status IN ('Pending', 'Send Back')"


def test_on_hold_written_for_pending_becomes_the_rule(readable):
    sql = ("SELECT COUNT(DISTINCT request_id) AS pending_applications FROM curated.v_cm_elevate "
           "WHERE lgd_district = 'RI BHOI' AND data_verified = 'On Hold'")
    out = p._cm_elevate_pending_funnel("How many applications are pending in Ri Bhoi?", CME, sql)
    assert "On Hold" not in out and TAIL in out and "lgd_district = 'RI BHOI'" in out


def test_an_on_hold_question_gets_the_rule_too(readable):
    sql = "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'On Hold'"
    out = p._cm_elevate_pending_funnel("How many CM Elevate applications are on hold?", CME, sql)
    assert "On Hold" not in out and TAIL in out


def test_on_hold_inside_a_filter_becomes_the_rule(readable):
    sql = ("SELECT lgd_district, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'On Hold') AS pending "
           "FROM curated.v_cm_elevate GROUP BY 1 ORDER BY 2 DESC")
    out = p._cm_elevate_pending_funnel("Which districts have the most pending applications?", CME, sql)
    assert "On Hold" not in out and TAIL in out and "GROUP BY 1" in out


def test_a_pending_query_with_no_status_test_gets_the_rule(readable):
    sql = "SELECT COUNT(DISTINCT request_id) AS applications FROM curated.v_cm_elevate WHERE LOWER(current_level) = 'level2'"
    out = p._cm_elevate_pending_funnel("How many CM ELEVATE applications are pending at level 2?", CME, sql)
    assert "LOWER(current_level) = 'level2'" in out and TAIL in out and "WHERE" in out and "FILTER" not in out


def test_a_grouped_query_gets_the_rule_inside_the_count_filter(readable):
    sql = ("SELECT LOWER(current_level) AS level, COUNT(DISTINCT request_id) AS pending "
           "FROM curated.v_cm_elevate GROUP BY 1 ORDER BY 1")
    out = p._cm_elevate_pending_funnel("level-wise pending applications", CME, sql)
    assert "FILTER(WHERE data_verified = 'Valid' AND" in out and TAIL in out
    assert "GROUP BY 1" in out and out.index("FILTER") < out.index("GROUP BY")      # not in the WHERE


def test_a_query_already_on_the_rule_is_left_alone(readable):
    sql = f"SELECT COUNT(*) FROM curated.v_cm_elevate WHERE {RULE_SQL}"
    assert p._cm_elevate_pending_funnel("How many applications are pending?", CME, sql) == sql


@pytest.mark.parametrize("q,sql", [
    ("pending applications marked invalid", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'Invalid'"),
    ("applications pending verification", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified IS NULL"),
    ("How many applications are forwarded?", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_file_status) = 'forward'"),
    ("How many are on hold at verification?", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'On Hold'"),
])
def test_an_explicit_state_is_left_alone(readable, q, sql):
    assert p._cm_elevate_pending_funnel(q, CME, sql) == sql


def test_locked_guards_leave_the_model_sql_and_never_write_on_hold(locked):
    sql = "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'On Hold'"
    assert p._cm_elevate_pending_funnel("How many applications are pending?", CME, sql) == sql
    assert p._cm_elevate_pending_funnel("How many applications are pending?", ["CM Elevate Legacy"], sql) == sql
    lvl = "SELECT scheme_name, COUNT(*) AS n FROM curated.v_cm_elevate WHERE LOWER(current_level) = 'level1' GROUP BY scheme_name"
    assert p._cm_elevate_pending_without_level("Which programs have the most pending applications?", CME, lvl) == lvl
    fs = "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_file_status) = 'pending'"
    assert p._cm_elevate_decision_status_column(CME, fs) == fs


def test_plain_pending_on_a_level_restores_the_rule(readable):
    sql = ("SELECT scheme_name, COUNT(*) AS pending_applications FROM curated.v_cm_elevate "
           "WHERE LOWER(current_level) = 'level1' GROUP BY scheme_name")
    out = p._cm_elevate_pending_without_level("Which programs have the highest number of pending applications?", CME, sql)
    assert "current_level" not in out and TAIL in out


def test_pending_without_level_leaves_a_rule_query_alone(readable):
    sql = f"SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_level) = 'level1' AND {RULE_SQL}"
    assert p._cm_elevate_pending_without_level("pending applications", CME, sql) == sql


def test_file_status_pending_literal_becomes_the_rule(readable):
    out = p._cm_elevate_decision_status_column(
        CME, "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_file_status) = 'pending'")
    assert TAIL in out and "On Hold" not in out


# ── wording and prompt ───────────────────────────────────────────────────────
def test_level_answer_keeps_the_word_pending(readable):
    q = "How many CM Elevate applications are pending at level 2?"
    a = "There are 309 pending applications at level 2."
    assert p._cme_level_pending_wording(q, CME, a) == a


def test_prompt_rule_and_vocabulary_follow_the_gate_and_the_yaml(monkeypatch):
    from app import schema_context as sc
    monkeypatch.setattr(si, "live_columns", lambda: OPEN)
    open_ = sc.build_schema_context(CME)
    assert "the PENDING RULE (user decision 2026-10-30): " + RULE_SQL in open_ and RULE_TEXT in open_
    assert '"on hold" / "held" -> the PENDING RULE' in open_
    # KI-707: the rule reads the plain file_status column; scheme_specific itself stays locked
    assert "file_status is a plain column" in open_ and "Never write scheme_specific" in open_
    assert "Level-wise = the rule grouped by LOWER(current_level)" in open_ and "<<CME_" not in open_
    assert "[[cme_pending]]" not in open_ and "7,33" not in open_
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    locked = sc.build_schema_context(CME)
    assert "is LOCKED from the chatbot's database role" in locked and "a PENDING / ON-HOLD count is NOT AVAILABLE" in locked
    assert '"pending" / "pendency" / "on hold" / "held" -> NOT AVAILABLE for now' in locked and RULE_TEXT in locked
    assert "NEVER answer pending or on hold from data_verified = 'On Hold'" in locked
    assert '"on hold" / "held" -> data_verified' not in locked and "PENDING RULE (user decision" not in locked
    assert "<<CME_" not in locked


def test_no_typed_in_pending_figure_remains():
    from app import data_facts as df
    assert "cme_pending" not in df.FACTS and "cm_elevate_pending" not in df._QUERIES
