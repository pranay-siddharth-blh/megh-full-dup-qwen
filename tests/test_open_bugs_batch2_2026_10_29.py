"""Open-bug batch 2 (2026-10-29) — each live-reproduced or code-verified first:

KI-003  a repair that returns the failed query unchanged is asked once more (_c11_same_sql).
KI-012  a refused / dropped gateway connection is retried once (llm._post_retry_connect).
KI-013  no SQL repair starts past REPAIR_TIME_BUDGET_SECONDS (turn_trace.elapsed).
KI-036  "Tura" (an HQ town) asks district vs the places named after it (_c09_hq_alias_readings).
KI-037  a follow-up rewrite keeps "<name> block" after a block answer (_c14_keep_block_level).
KI-290  a bare FOCUS beside Focus+ is Focus Legacy on the knowledge path (_c14_bare_focus_beside_plus).
KI-365  a Focus Plus zero for a 12.5K-only field says why (_fp_cohort_zero_answer).
KI-398  the cross-scheme worked examples no longer teach WHERE NOT is_placeholder for houses.

OFFLINE: the real functions; gateway, DB and catalogue faked.
    .venv/Scripts/python.exe -m pytest tests/test_open_bugs_batch2_2026_10_29.py -q
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_policy as cp, entity_resolver, llm, pipeline as p, turn_trace  # noqa: E402
from app.config import settings  # noqa: E402
from app.schema_context import build_schema_context  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── KI-003 ───────────────────────────────────────────────────────────────────
def test_the_same_query_is_recognised_whatever_its_formatting():
    assert p._c11_same_sql("SELECT  SUM(x) FROM t WHERE a=1", "select sum(x) from t where a = 1")
    assert not p._c11_same_sql("SELECT 1", "SELECT 2")


def test_an_unchanged_repair_is_asked_once_more(monkeypatch):
    calls = []

    async def gen(prompt, **_kw):
        calls.append(prompt)
        return "SELECT 1" if len(calls) == 1 else "SELECT 2"
    monkeypatch.setattr(llm, "call_sql_generator", gen)
    turn_trace.start("t")
    out = _run(p._repair_sql("q", ["MGNREGA"], {"resolved": {}}, "SELECT 1", "boom"))
    assert out == "SELECT 2" and len(calls) == 2 and "EXACTLY the failed query" in calls[1]


# ── KI-012 ───────────────────────────────────────────────────────────────────
class _Client:
    def __init__(self, fail):
        self.n, self.fail = 0, fail

    async def post(self, url, **kw):
        self.n += 1
        if self.n <= self.fail:
            raise httpx.ConnectError("down")
        return "OK"


def test_one_dropped_connection_is_retried_once(monkeypatch):
    monkeypatch.setattr(llm, "_client", _Client(1))
    assert _run(llm._post_retry_connect("u", json={})) == "OK"
    monkeypatch.setattr(llm, "_client", _Client(2))
    with pytest.raises(httpx.ConnectError):
        _run(llm._post_retry_connect("u", json={}))


# ── KI-013 ───────────────────────────────────────────────────────────────────
def test_no_repair_past_the_time_budget(monkeypatch):
    async def gen(prompt, **_kw):
        raise AssertionError("the model must not be called past the budget")
    monkeypatch.setattr(llm, "call_sql_generator", gen)
    t = turn_trace.start("t")
    t["started"] = time.monotonic() - settings.REPAIR_TIME_BUDGET_SECONDS - 5
    with pytest.raises(ValueError, match="repair time budget"):
        _run(p._repair_sql("q", ["MGNREGA"], {"resolved": {}}, "SELECT 1", "boom"))


# ── KI-036 ───────────────────────────────────────────────────────────────────
def test_an_hq_town_name_asks_which_place(monkeypatch):
    monkeypatch.setattr(entity_resolver, "_catalog", {"Focus Plus": {
        "block": [{"canonical": "TURA MUNICIPAL BOARD"}, {"canonical": "DALU"}],
        "assembly_constituency": [{"canonical": "NORTH TURA"}, {"canonical": "SOUTH TURA"}]}})
    q = "How many Focus Plus beneficiaries are there in Tura in FY 2025-26?"
    ask = p._c09_hq_alias_readings(q, "tura", "WEST GARO HILLS", "Focus Plus")
    labels = [o["label"] for o in ask.options]
    assert labels[0].startswith("West Garo Hills district") and "Tura Municipal Board block" in labels
    assert "“Tura”" in ask.question
    assert ask.options[1]["question"].startswith("How many Focus Plus beneficiaries are there in ")
    assert p._c09_hq_alias_readings("…in Jowai", "jowai", "WEST JAINTIA HILLS", "Focus Plus") is None


# ── KI-037 ───────────────────────────────────────────────────────────────────
def test_a_block_answer_keeps_its_level_in_the_rewrite():
    prev = SimpleNamespace(resolved_entities={"block": "MAWKYRWAT", "year_key": 2023})
    plan = cp.plan_state_merge("What about FY 2022-23?", None, prev=prev)
    q = "How many households were employed under MGNREGA in Mawkyrwat in FY 2022-23?"
    assert "in Mawkyrwat block in FY 2022-23" in p._c14_keep_block_level(q, prev, plan)
    already = q.replace("Mawkyrwat in", "Mawkyrwat block in")
    assert p._c14_keep_block_level(already, prev, plan) == already
    village = SimpleNamespace(resolved_entities={"block": "MAWKYRWAT", "village_code": 277399})
    assert p._c14_keep_block_level(q, village, plan) == q


# ── KI-290 ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("q,expected", [
    ("Give me a summary comparing MGNREGA, Focus+, FOCUS and CM-ELEVATE", True),
    ("What is Focus Plus?", False),
    ("How does Focus+ work?", False),
])
def test_a_bare_focus_beside_focus_plus(q, expected):
    assert p._c14_bare_focus_beside_plus(q) is expected


# ── KI-365 ───────────────────────────────────────────────────────────────────
def test_a_zero_for_a_cohort_only_field_is_explained():
    q = "How many Focus Plus women beneficiaries were there during FY 2022-23?"
    out = p._fp_cohort_zero_answer(q, ["Focus Plus"], [{"women_beneficiaries": 0}], "x")
    assert "12.5K registration cohort" in out and "not recorded" in out
    assert p._fp_cohort_zero_answer(q, ["Focus Plus"], [{"women_beneficiaries": 7}], "7") == "7"


# ── KI-398 ───────────────────────────────────────────────────────────────────
def test_cross_scheme_examples_count_every_house():
    text = build_schema_context(["MGNREGA", "PMAY-G"])
    assert "FROM curated.v_pmay) p" in text
    for line in text.splitlines():
        assert line.strip() != "WHERE NOT is_placeholder"
