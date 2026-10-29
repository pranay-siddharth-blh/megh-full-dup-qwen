"""D-083 (2026-10-29, user rule): every knowledge question is re-ranked by
qwen3-reranker on the gateway, and there is no setting that turns it off.

The re-ranker had been off since 2026-08-29 (D-005) and the local jina one since
2026-10-15; each new session and teammate read "off" in config and docs and kept
it that way. These tests fail if an off switch, the local re-ranker, the 4B
fallback scorer or the bare (format-less) call ever comes back. Read D-083 before
"fixing" one of them."""
import asyncio
from pathlib import Path

import httpx
import pydantic
import pytest

from app import config, llm, local_rank, rag, vectorstore
from app.config import Settings, settings

ROOT = Path(__file__).resolve().parents[1]
REMOVED = ("RERANKER_ENABLED", "RAG_LOCAL_RERANKER", "RAG_RERANK_CHARS")


@pytest.mark.parametrize("name", REMOVED)
def test_no_switch_exists(name):
    assert name not in Settings.model_fields
    assert not hasattr(settings, name)


@pytest.mark.parametrize("name", REMOVED)
def test_an_old_env_line_fails_startup_instead_of_switching_it_off(tmp_path, name):
    env = tmp_path / ".env"
    env.write_text(f"{name}=false\n", encoding="utf-8")
    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=str(env))


@pytest.mark.parametrize("path", ["app/rag.py", "app/llm.py", "app/local_rank.py", "app/config.py"])
def test_source_has_no_way_back(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    for code in ("settings.RERANKER_ENABLED", "settings.RAG_LOCAL_RERANKER", "TextCrossEncoder",
                 "local_rank.rerank", "call_classifier(prompt)"):
        assert code not in src, f"{code} is back in {path} (D-083)"


def test_local_rank_keeps_only_keyword_search():
    assert not hasattr(local_rank, "rerank")
    assert hasattr(local_rank, "sparse_query") and hasattr(local_rank, "sparse_docs")


def _pieces(n):
    return [{"score": 0.8 - i / 100, "text": f"piece {i}", "doc": "d.md", "heading": f"h{i}"} for i in range(n)]


@pytest.mark.parametrize("hybrid", [True, False])
def test_retrieve_always_calls_the_reranker(monkeypatch, hybrid):
    calls = []

    async def embed(q):
        return [[0.1] for _ in q]

    async def search(vector, top_k, scheme=None, sparse=None):
        return _pieces(5)

    async def sparse(q):
        return None

    async def rerank(q, texts):
        calls.append((q, len(texts)))
        return [(i, 0.5) for i in range(len(texts))]

    monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", hybrid)
    monkeypatch.setattr(llm, "call_embedding", embed)
    monkeypatch.setattr(vectorstore, "search", search)
    monkeypatch.setattr(local_rank, "sparse_query", sparse)
    monkeypatch.setattr(llm, "call_reranker", rerank)
    out = asyncio.run(rag.retrieve("documents for PMAY-G?", scheme="PMAY-G", expand=False))
    assert calls == [("documents for PMAY-G?", 5)]
    assert all("rerank_score" in c for c in out)


class _FakeClient:
    def __init__(self, status=200):
        self.status, self.sent = status, None

    async def post(self, url, headers=None, json=None, timeout=None):
        self.sent = {"url": url, **json}
        req = httpx.Request("POST", url)
        body = {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}
        return httpx.Response(self.status, json=body, request=req)


def _with_fake_client(monkeypatch, client):
    monkeypatch.setattr(llm, "_client", client)
    monkeypatch.setattr(llm, "_gate", asyncio.Semaphore(1), raising=False)


def test_call_reranker_sends_the_qwen3_format(monkeypatch):
    client = _FakeClient()
    _with_fake_client(monkeypatch, client)
    out = asyncio.run(llm.call_reranker("what documents?", ["a", "b"]))
    assert out == [(1, 0.9), (0, 0.2)]
    assert client.sent["url"].endswith("/rerank") and client.sent["model"] == settings.RERANKER_MODEL
    assert "<Instruct>:" in client.sent["query"] and "<Query>: what documents?" in client.sent["query"]
    assert client.sent["documents"][0].startswith("<Document>: a")


def test_call_reranker_raises_instead_of_a_hidden_fallback(monkeypatch):
    _with_fake_client(monkeypatch, _FakeClient(status=500))

    async def must_not_run(*a, **k):
        raise AssertionError("4B fallback scorer used (removed by D-083)")

    monkeypatch.setattr(llm, "call_classifier", must_not_run)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(llm.call_reranker("q", ["a", "b"]))


def test_startup_check_reports_a_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "RERANKER_API_KEY", "")
    assert "RERANKER_API_KEY" in config.reranker_problem()
    monkeypatch.setattr(settings, "RERANKER_API_KEY", "CHANGE_ME")
    assert "RERANKER_API_KEY" in config.reranker_problem()
    monkeypatch.setattr(settings, "RERANKER_API_KEY", "a-real-key")
    assert config.reranker_problem() == ""
