"""
CTX-08 (2026-10-29): context_budget.log_decision promises that no question,
prompt or result text reaches the decision log, but seven call sites passed
question=... (conversation_layer compare-earlier / counterpart-swap /
measure-after-knowledge; c14 chart-view / compare-with-scheme / rollup /
overview), so officers' questions sat in the logs. log_decision now keeps the
promise itself: a text value under a text fact is logged as a short hash and
its length. Every current and future call site is covered; none was edited.

A real call site is driven through the graph (the overview route, c14) and
every pipeline_decision record of the turn is checked. No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_decision_log_text_2026_10_29.py -q
"""
import asyncio
import hashlib
import logging
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, context_budget, entity_resolver, llm  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import Session  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402

OVERVIEW = "Give me an overview of Ri Bhoi under MGNREGA"


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


def test_text_facts_are_logged_as_a_fingerprint():
    rec = context_budget.log_decision("followup", rewrite="chart-view", question="How many houses in Mawphlang?",
                                      questions=3)
    assert "Mawphlang" not in str(rec)
    want = hashlib.sha256("How many houses in Mawphlang?".encode("utf-8")).hexdigest()[:12]
    assert rec["question"] == {"sha256": want, "chars": len("How many houses in Mawphlang?")}
    assert rec["questions"] == 3 and rec["rewrite"] == "chart-view"      # labels and numbers untouched


def test_a_real_turn_logs_no_question_text(monkeypatch, caplog):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED"):
        monkeypatch.setattr(settings, flag, True)

    async def data(question, scope=None, **kw):
        return {"route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1",
                "resolved_entities": {"district": "RI BHOI"}, "rows": [], "data": [], "row_count": 0,
                "answer": "MGNREGA answer."}
    stub_data_path(monkeypatch, data)

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    s = Session(session_id="ctx08-1", user_id="u", created=time.time(), last_seen=time.time())
    with caplog.at_level(logging.INFO, logger="app.context_budget"):
        try:
            asyncio.run(graph_turn(OVERVIEW, session=s))
        except Exception:  # noqa: BLE001 — whatever the turn ends in, its log is what is checked
            pass
    lines = [r.getMessage() for r in caplog.records if "pipeline_decision" in r.getMessage()]
    assert lines
    assert any('"rewrite": "overview"' in ln for ln in lines)          # the c14 call site ran
    assert not any("Ri Bhoi" in ln or "overview of" in ln for ln in lines)
