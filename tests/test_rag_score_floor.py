"""RAG_MIN_SCORE is enforced (2026-10-16): pieces below the floor never reach the
composer, and when none passes, retrieve() returns nothing instead of falling
back to the unfiltered top pieces (audit 2026-10-15: made-up rate 16%)."""
import asyncio

from app import llm, rag
from app.config import settings


def _run(monkeypatch, scores, reranker=False):
    async def fake_embed(texts):
        return [[0.0] * 4 for _ in texts]

    async def fake_search(vec, q, k, scheme):
        return [{"text": f"piece {i}", "doc": "d", "heading": "h", "score": s} for i, s in enumerate(scores)]

    async def fake_rerank(question, texts):
        return [(i, s) for i, s in enumerate(scores)]

    monkeypatch.setattr(llm, "call_embedding", fake_embed)
    monkeypatch.setattr(rag, "_search_one", fake_search)
    monkeypatch.setattr(llm, "call_reranker", fake_rerank)
    monkeypatch.setattr(settings, "RAG_LOCAL_RERANKER", "")
    monkeypatch.setattr(settings, "RERANKER_ENABLED", reranker)
    monkeypatch.setattr(settings, "RAG_MIN_SCORE", 0.30)
    return asyncio.run(rag.retrieve("an unrelated question"))


def test_all_below_floor_returns_nothing(monkeypatch):
    assert _run(monkeypatch, [0.29, 0.21, 0.10]) == []


def test_only_pieces_at_or_above_the_floor_are_kept(monkeypatch):
    kept = _run(monkeypatch, [0.62, 0.31, 0.29, 0.05])
    assert [c["score"] for c in kept] == [0.62, 0.31]


def test_reranker_path_has_no_fallback_either(monkeypatch):
    assert _run(monkeypatch, [0.2, 0.1], reranker=True) == []


def test_answer_from_kb_says_not_covered_when_nothing_passes(monkeypatch):
    async def nothing(*a, **k):
        return []
    monkeypatch.setattr(rag, "retrieve", nothing)
    assert asyncio.run(rag.answer_from_kb("an unrelated question")) is None
