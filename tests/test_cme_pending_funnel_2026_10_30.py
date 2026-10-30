"""
CM Elevate "pending" = Valid -> forward or sendback -> file_status Pending / Send Back (user decision
2026-10-30, D-B1-CME-01), superseding the KI-074 On Hold reading.

file_status lives inside curated.v_cm_elevate.scheme_specific, which the chatbot's database
role has not been allowed to read since 2026-10-16 (KI-624). Every change is therefore gated
on schema_introspect.cme_file_status_readable(): the live columns the read-only role may
SELECT include scheme_specific. These tests open the gate by patching live_columns(); with
it closed (the default here, no DB) the older tests in test_cmelevate_usecase_fixes.py,
test_cme_sheet_fixes.py and test_db_changes_2026_10_26.py still pin the locked behaviour.

No model or DB.
    python -m pytest tests/test_cme_pending_funnel_2026_10_30.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402
from app import schema_introspect as si  # noqa: E402

CME = ["CM Elevate"]
SEED = "PRIME Small Enterprise Empowerment and Development (SEED)"
PIG = "Meghalaya Piggery Development Scheme"
FUNNEL_TAIL = "->> 'file_status' IN ('Pending', 'Send Back')"
OPEN = {"curated.v_cm_elevate": [{"column": "request_id"}, {"column": "scheme_specific"}]}
LOCKED = {"curated.v_cm_elevate": [{"column": "request_id"}, {"column": "data_verified"}]}
WF = "/* cme-sector-workflow */ SELECT 1"
ONE = {"pending": 7338, "sent_back": 90, "on_hold": 911, "forward": 8942, "resubmit": 3, "sendback": 3,
       "applications": 8948}


@pytest.fixture
def readable(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: OPEN)


# ── the gate ─────────────────────────────────────────────────────────────────
def test_gate_is_closed_without_the_live_schema(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: {})
    assert not si.cme_file_status_readable()
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    assert not si.cme_file_status_readable()


def test_gate_opens_when_scheme_specific_is_readable(readable):
    assert si.cme_file_status_readable()
    assert p._cme_pending_target().startswith("data_verified = 'Valid' AND (LOWER(current_file_status) = 'forward' OR")
    assert "LIKE 'sendback%')" in p._cme_pending_target() and "resubmit" not in p._cme_pending_target()


def test_target_is_on_hold_while_locked(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    assert p._cme_pending_target() == "data_verified = 'On Hold'"


# ── the fixed workflow query and its answer ──────────────────────────────────
def test_workflow_query_counts_the_funnel_first(readable):
    sql, params, _ = p._cme_workflow_query("How many CM Elevate applications are pending?", {})
    assert "cme-sector-workflow" in sql and params == []
    assert ("FILTER (WHERE data_verified = 'Valid' AND (LOWER(current_file_status) = 'forward' "
            "OR LOWER(current_file_status) LIKE 'sendback%') "
            "AND scheme_specific ->> 'file_status' IN ('Pending', 'Send Back')) AS pending") in sql
    assert "FILTER (WHERE scheme_specific ->> 'file_status' = 'Send Back') AS sent_back" in sql
    assert sql.index("AS pending") < sql.index("AS on_hold")


def test_workflow_query_has_no_file_status_while_locked(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    sql, _, _ = p._cme_workflow_query("How many CM Elevate applications are pending?", {})
    assert "scheme_specific" not in sql and "AS pending" not in sql and "AS on_hold" in sql


def test_pending_answer_states_the_count_the_rule_and_the_leftovers(readable):
    a = p._cme_sector_answer("How many CM Elevate applications are pending?", WF, [dict(ONE)], {})
    assert a.startswith("7,338 CM Elevate applications are pending across Meghalaya (of 8,948).")
    assert "Pending means: data verified Valid, file forwarded or sent back (not resubmitted), and file status Pending or Send Back." in a
    assert "911 on hold at data verification" in a and "Invalid or Wrong" in a
    assert "doesn't record" not in a


def test_pending_answer_in_a_place_under_a_programme(readable):
    row = dict(ONE, pending=1463, applications=1944)
    a = p._cme_sector_answer("How many applications are pending under Piggery in Ri Bhoi?", WF, [row],
                             {"district": "Ri Bhoi", "cm_scheme": PIG})
    assert a.startswith(f"1,463 CM Elevate applications are pending in Ri Bhoi under {PIG} (of 1,944).")


def test_pending_ranked_by_programme(readable):
    q = "Which CM ELEVATE programs have the highest number of pending applications?"
    sql, _, _ = p._cme_workflow_query(q, {})
    assert "scheme_name AS grp" in sql and "ORDER BY 2 DESC, 1" in sql and sql.index("AS pending") < sql.index("AS on_hold")
    rows = [dict(ONE, grp=SEED, pending=3146), dict(ONE, grp=PIG, pending=2429)]
    a = p._cme_sector_answer(q, sql, rows, {})
    assert a.startswith("Pending CM Elevate applications across Meghalaya, by programme (highest first):")
    assert a.index("3,146") < a.index("2,429") and "Total 5,575." in a and "Pending means:" in a


def test_sent_back_is_the_file_status_decision(readable):
    a = p._cme_sector_answer("How many applications were sent back?", WF, [dict(ONE)], {})
    assert a.startswith("90 CM Elevate applications across Meghalaya have the file status Send Back (of 8,948)")
    assert "counted among the 7,338 pending" in a


def test_the_locked_answer_is_unchanged(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    rows = [{"on_hold": 903, "forward": 8837, "resubmit": 2, "sendback": 1, "applications": 8840}]
    a = p._cme_sector_answer("How many CM Elevate applications are pending?", WF, rows, {})
    assert 'doesn\'t record a "pending" status' in a and "903 applications are on hold" in a


# ── pending by sector ────────────────────────────────────────────────────────
def test_sector_pending_counts_the_funnel(readable):
    sql, params, _ = p._cme_sector_query("How many applications are pending in each sector in Eastern West Khasi Hills?",
                                         CME, {"district": "EASTERN WEST KHASI HILLS"})
    assert "cme-sector-pending" in sql and f"scheme_specific {FUNNEL_TAIL}) AS pending" in sql and "On Hold" not in sql
    a = p._cme_sector_answer("q", sql, [{"sector": "(not recorded)", "pending": 289, "applications": 306}],
                             {"district": "Eastern West Khasi Hills"})
    assert a.startswith("Pending CM Elevate applications by sector in Eastern West Khasi Hills: (not recorded) 289. Total 289.")
    assert "Pending means:" in a


# ── the model-SQL guards ─────────────────────────────────────────────────────
def test_on_hold_written_for_pending_becomes_the_funnel(readable):
    sql = ("SELECT COUNT(DISTINCT request_id) AS pending_applications FROM curated.v_cm_elevate "
           "WHERE lgd_district = 'RI BHOI' AND data_verified = 'On Hold'")
    out = p._cm_elevate_pending_funnel("How many applications are pending in Ri Bhoi?", CME, sql)
    assert "On Hold" not in out and FUNNEL_TAIL in out and "lgd_district = 'RI BHOI'" in out


def test_on_hold_inside_a_filter_becomes_the_funnel(readable):
    sql = ("SELECT lgd_district, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'On Hold') AS pending "
           "FROM curated.v_cm_elevate GROUP BY 1 ORDER BY 2 DESC")
    out = p._cm_elevate_pending_funnel("Which districts have the most pending applications?", CME, sql)
    assert "On Hold" not in out and FUNNEL_TAIL in out and "GROUP BY 1" in out


def test_a_pending_query_with_no_status_test_gets_the_funnel(readable):
    sql = "SELECT COUNT(DISTINCT request_id) AS applications FROM curated.v_cm_elevate WHERE LOWER(current_level) = 'level2'"
    out = p._cm_elevate_pending_funnel("How many CM ELEVATE applications are pending at level 2?", CME, sql)
    assert "LOWER(current_level) = 'level2'" in out and FUNNEL_TAIL in out and " AND " in out


def test_a_query_already_on_the_funnel_is_left_alone(readable):
    sql = ("SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'Valid' AND (LOWER(current_file_status) = 'forward' "
           "OR LOWER(current_file_status) LIKE 'sendback%') AND scheme_specific ->> 'file_status' IN ('Pending', 'Send Back')")
    assert p._cm_elevate_pending_funnel("How many applications are pending?", CME, sql) == sql


@pytest.mark.parametrize("q,sql", [
    ("How many pending applications are on hold?", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'On Hold'"),
    ("pending applications marked invalid", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'Invalid'"),
    ("applications pending verification", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified IS NULL"),
    ("How many applications are forwarded?", "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_file_status) = 'forward'"),
])
def test_an_explicit_state_is_left_alone(readable, q, sql):
    assert p._cm_elevate_pending_funnel(q, CME, sql) == sql


def test_locked_leaves_the_model_sql_alone(monkeypatch):
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    sql = "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE data_verified = 'On Hold'"
    assert p._cm_elevate_pending_funnel("How many applications are pending?", CME, sql) == sql
    assert p._cm_elevate_pending_funnel("How many applications are pending?", ["CM Elevate Legacy"], sql) == sql


def test_plain_pending_on_a_level_restores_the_funnel(readable):
    sql = ("SELECT scheme_name, COUNT(*) AS pending_applications FROM curated.v_cm_elevate "
           "WHERE LOWER(current_level) = 'level1' GROUP BY scheme_name")
    out = p._cm_elevate_pending_without_level("Which programs have the highest number of pending applications?", CME, sql)
    assert "current_level" not in out and FUNNEL_TAIL in out


def test_pending_without_level_leaves_a_funnel_query_alone(readable):
    sql = ("SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_level) = 'level1' "
           "AND scheme_specific ->> 'file_status' IN ('Pending', 'Send Back')")
    assert p._cm_elevate_pending_without_level("pending applications", CME, sql) == sql


def test_file_status_pending_literal_becomes_the_funnel(readable):
    out = p._cm_elevate_decision_status_column(
        CME, "SELECT COUNT(*) FROM curated.v_cm_elevate WHERE LOWER(current_file_status) = 'pending'")
    assert FUNNEL_TAIL in out and "On Hold" not in out


# ── wording and prompt ───────────────────────────────────────────────────────
def test_level_answer_keeps_the_word_pending(readable):
    q = "How many CM Elevate applications are pending at level 2?"
    a = "There are 309 pending applications at level 2."
    assert p._cme_level_pending_wording(q, CME, a) == a


def test_prompt_rule_and_vocabulary_follow_the_gate(monkeypatch):
    from app import schema_context as sc
    monkeypatch.setattr(si, "live_columns", lambda: OPEN)
    open_ = sc.build_schema_context(CME)
    assert "the PENDING RULE (user decision 2026-10-30)" in open_ and "IN ('Pending', 'Send Back')" in open_
    assert "The ONLY key you may read is file_status" in open_ and "<<CME_" not in open_
    assert "on hold is NOT pending" in open_
    monkeypatch.setattr(si, "live_columns", lambda: LOCKED)
    locked = sc.build_schema_context(CME)
    assert "is LOCKED from the chatbot's database role" in locked and "a pending count is NOT AVAILABLE" in locked
    assert '"pending" -> NOT AVAILABLE for now' in locked and "<<CME_" not in locked
    assert "PENDING RULE (user decision" not in locked


def test_the_live_pending_token_has_its_own_query():
    from app import data_facts as df
    assert "cm_elevate_pending" in df._QUERIES and "scheme_specific ->> 'file_status'" in df._QUERIES["cm_elevate_pending"]
    assert df.FACTS["cme_pending"][0] == "7,338"
    assert df.render("[[cme_pending]] pending") == "7,338 pending"
