"""RAG upgrade Phase 3 (2026-10-14): keyword (BM25) search fused with meaning
search, and a local cross-encoder that re-orders the candidates. The order may
change, but `score` stays the meaning similarity the confidence tiers use."""
import asyncio

import pytest

from app import llm, local_rank, rag, vectorstore
from app.config import settings


def _pieces(*scores):
    return [{"score": s, "text": f"piece {i}", "doc": "d.md", "heading": f"h{i}", "scheme": "PMAY-G"}
            for i, s in enumerate(scores)]


@pytest.fixture
def stubs(monkeypatch):
    calls = {}

    async def fake_embedding(q):
        return [[0.1, 0.2, 0.3]]

    async def fake_search(vector, top_k, scheme=None, sparse=None):
        calls["top_k"], calls["sparse"], calls["scheme"] = top_k, sparse, scheme
        return _pieces(0.80, 0.70, 0.60)

    async def fake_sparse(q):
        return ([1, 2], [0.5, 0.5])

    monkeypatch.setattr(llm, "call_embedding", fake_embedding)
    monkeypatch.setattr(vectorstore, "search", fake_search)
    monkeypatch.setattr(local_rank, "sparse_query", fake_sparse)
    monkeypatch.setattr(settings, "RERANKER_ENABLED", False)
    return calls


def test_hybrid_sends_the_keyword_vector_and_a_wider_pool(monkeypatch, stubs):
    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_LOCAL_RERANKER", "")
    asyncio.run(rag.retrieve("What is SECC?", scheme="PMAY-G"))
    assert stubs["sparse"] == ([1, 2], [0.5, 0.5])
    assert stubs["top_k"] == settings.RAG_CANDIDATES


def test_hybrid_off_is_meaning_only(monkeypatch, stubs):
    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_LOCAL_RERANKER", "")
    asyncio.run(rag.retrieve("What is SECC?", scheme="PMAY-G"))
    assert stubs["sparse"] is None and stubs["top_k"] == settings.RAG_TOP_K


def test_the_reranker_reorders_but_keeps_the_meaning_score(monkeypatch, stubs):
    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_LOCAL_RERANKER", "some/model")

    async def fake_rerank(q, texts):
        return [0.1, 0.2, 9.0]          # the third piece answers the question best

    monkeypatch.setattr(local_rank, "rerank", fake_rerank)
    out = asyncio.run(rag.retrieve("documents for PMAY-G?", scheme="PMAY-G"))
    assert [c["heading"] for c in out] == ["h2", "h1", "h0"]
    assert [c["score"] for c in out] == [0.60, 0.70, 0.80]
    assert out[0]["rerank_score"] == 9.0


def test_a_reranker_that_fails_keeps_the_search_order(monkeypatch, stubs):
    monkeypatch.setattr(settings, "RAG_LOCAL_RERANKER", "some/model")

    async def broken(q, texts):
        return None

    monkeypatch.setattr(local_rank, "rerank", broken)
    out = asyncio.run(rag.retrieve("documents?", scheme="PMAY-G"))
    assert [c["heading"] for c in out] == ["h0", "h1", "h2"]


def test_enough_to_answer_is_judged_on_the_strongest_piece(monkeypatch):
    # The re-ranker put a 0.50 piece first; a 0.70 piece is also kept. Medium
    # confidence (0.55) is met by the strongest piece, so an answer is composed.
    async def fake_retrieve(q, scheme=None):
        return _pieces(0.50, 0.70)

    async def fake_compose(prompt):
        return "Aadhaar and bank details are required."

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(llm, "call_response_composer", fake_compose)
    out = asyncio.run(rag.answer_from_kb("documents for PMAY-G?", scheme="PMAY-G"))
    assert out is not None and "Aadhaar" in out["answer"] and out["confidence"] == "medium"


def test_a_piece_is_shown_verbatim_only_when_the_first_piece_itself_is_near_exact(monkeypatch):
    async def fake_retrieve(q, scheme=None):
        return _pieces(0.60, 0.90)       # the near-exact piece is NOT first

    async def fake_compose(prompt):
        return "Composed answer."

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(llm, "call_response_composer", fake_compose)
    out = asyncio.run(rag.answer_from_kb("what is a job card", scheme="MGNREGA"))
    assert out["answer"] == "Composed answer."


def test_cosine():
    assert vectorstore._cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert vectorstore._cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert vectorstore._cosine([1, 0], []) == 0.0


def test_switched_off_steps_return_none(monkeypatch):
    monkeypatch.setattr(settings, "RAG_SPARSE_MODEL", "")
    monkeypatch.setattr(settings, "RAG_LOCAL_RERANKER", "")
    assert asyncio.run(local_rank.sparse_query("what is secc")) is None
    assert asyncio.run(local_rank.sparse_docs(["a"])) is None
    assert asyncio.run(local_rank.rerank("q", ["a", "b"])) is None
