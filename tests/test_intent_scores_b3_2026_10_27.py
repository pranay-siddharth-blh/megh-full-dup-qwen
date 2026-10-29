"""B3 (RAG plan) — retrieval scores as a narrow safety net on a DATA verdict.

Measured live 2026-10-27 (tests/intent_scores/run_eval.py, 70 labelled questions):
the rules route 67/70 right, scores alone only 57/70. The two clear misroutes ("How
many days of work does MGNREGA guarantee?", "Can a woman apply for a job card?") have
the nearest knowledge passage ahead of the nearest worked data example by 0.175 /
0.221; every real data question has the example ahead (+0.021 or more). With the
safety net: 69/70.

OFFLINE: the real classify_intent; the classifier, the embedding and both searches
are faked.
    .venv/Scripts/python.exe -m pytest tests/test_intent_scores_b3_2026_10_27.py -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import llm, pipeline as p, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402


def _intent(q):
    return asyncio.new_event_loop().run_until_complete(p.classify_intent(q))


@pytest.fixture
def scores(monkeypatch):
    """Set kb / example scores per test: scores["kb"], scores["ex"]."""
    s = {"kb": 0.80, "ex": 0.60, "calls": 0}
    monkeypatch.setattr(settings, "INTENT_SCORE_TIEBREAK", True)

    async def classifier(*_a, **_kw):
        return '{"intent": "DATA"}'

    async def embed(texts):
        s["calls"] += 1
        return [[0.0] for _ in texts]

    async def kb_search(_vec, _k, scheme=None, sparse=None):
        return [{"score": s["kb"]}]

    class _Client:
        async def query_points(self, **_kw):
            return SimpleNamespace(points=[SimpleNamespace(score=s["ex"])])

    monkeypatch.setattr(llm, "call_classifier", classifier)
    monkeypatch.setattr(llm, "call_embedding", embed)
    monkeypatch.setattr(vectorstore, "search", kb_search)
    monkeypatch.setattr(vectorstore, "get_client", lambda: _Client())
    return s


def test_knowledge_clearly_closer_overturns_data(scores):
    scores["kb"], scores["ex"] = 0.84, 0.67
    assert _intent("How many days of work does MGNREGA guarantee?") == "KNOWLEDGE"


def test_a_small_margin_keeps_data(scores):
    scores["kb"], scores["ex"] = 0.73, 0.70
    assert _intent("How many days of work does MGNREGA guarantee?") == "DATA"


@pytest.mark.parametrize("q", [
    "How many person-days in 2023-24?",                  # a year
    "Which block has the most job cards?",               # a ranking
    "Show women person-days by district",                 # a breakdown
])
def test_a_figure_question_never_reaches_the_score_check(scores, q):
    scores["kb"], scores["ex"] = 0.95, 0.10                # would overturn if checked
    assert _intent(q) == "DATA" and scores["calls"] == 0


def test_a_failed_search_keeps_data(scores, monkeypatch):
    async def broken(*_a, **_kw):
        raise RuntimeError("qdrant down")
    monkeypatch.setattr(vectorstore, "search", broken)
    assert _intent("How many days of work does MGNREGA guarantee?") == "DATA"


def test_switched_off_no_check(scores, monkeypatch):
    monkeypatch.setattr(settings, "INTENT_SCORE_TIEBREAK", False)
    scores["kb"], scores["ex"] = 0.95, 0.10
    assert _intent("How many days of work does MGNREGA guarantee?") == "DATA" and scores["calls"] == 0
