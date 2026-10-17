"""Execution checks first, then the 30B verifier (2026-10-15).

_execute_one_attempt used to ask the verifier before the query touched the
database. Now: the free code guards, then the query runs on the read-only pool
(a Postgres error goes to repair with no model call), then the result checks,
then the verifier on the SQL. It is not shown the rows: a result-shape check
by the 30B wrongly flagged 23 of 57 correct queries (prompt_builder.build_verify_prompt)."""
import asyncio
import json

import pytest

from app import pipeline as p
from app.config import settings

Q = "How many houses were sanctioned under PMAY-G?"
SCHEMES = ["PMAY-G"]
ENTITIES = {"resolved": {}, "unresolved": []}
SQL = "SELECT COUNT(*) AS houses_sanctioned FROM curated.v_pmay"


@pytest.fixture
def calls(monkeypatch):
    log = {"order": [], "prompt": None, "verdict": {"ok": True}, "rows": [{"houses_sanctioned": 12}],
           "db_error": None}

    async def run_readonly(sql):
        log["order"].append("db")
        if log["db_error"]:
            raise log["db_error"]
        return log["rows"]

    async def verifier(prompt, **_k):
        log["order"].append("verifier")
        log["prompt"] = prompt
        return json.dumps(log["verdict"])

    monkeypatch.setattr(p, "run_readonly", run_readonly)
    monkeypatch.setattr(p.llm, "call_sql_verifier", verifier)
    monkeypatch.setattr(settings, "SQL_VERIFY_ENABLED", True)
    return log


def _attempt():
    return asyncio.run(p._execute_one_attempt(Q, SCHEMES, ENTITIES, SQL))


def test_the_query_runs_before_the_verifier(calls):
    assert _attempt() == [{"houses_sanctioned": 12}]
    assert calls["order"] == ["db", "verifier"]
    assert "ONLY these four things" in calls["prompt"]
    assert "houses_sanctioned=12" not in calls["prompt"]   # judges the SQL, not the rows


def test_a_database_error_goes_to_repair_without_a_model_call(calls):
    calls["db_error"] = RuntimeError('column "houses" does not exist')
    with pytest.raises(RuntimeError, match="does not exist"):
        _attempt()
    assert calls["order"] == ["db"]


def test_a_flagged_result_goes_to_repair(calls):
    calls["verdict"] = {"ok": False, "issue": "check 4: it sums a column unrelated to the question"}
    with pytest.raises(ValueError, match="semantic verifier flagged this query: check 4"):
        _attempt()
    assert calls["order"] == ["db", "verifier"]


def test_an_empty_result_still_reaches_the_verifier_and_passes(calls):
    calls["rows"] = []
    assert _attempt() == []
    assert calls["order"] == ["db", "verifier"]


def test_a_verifier_outage_never_blocks_the_rows(calls, monkeypatch):
    async def down(*_a, **_k):
        raise TimeoutError("gateway")
    monkeypatch.setattr(p.llm, "call_sql_verifier", down)
    assert _attempt() == [{"houses_sanctioned": 12}]
