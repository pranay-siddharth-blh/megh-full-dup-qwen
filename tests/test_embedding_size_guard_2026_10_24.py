"""D-067 follow-up (2026-10-24): the 1024-dim embedding switch must not fail silently.

- kb_ingest.ingest_kb rebuilds a KB collection whose vector size differs from the
  embedding model's (it skipped on count / schemes / BM25 only, so a provider
  change without a new QDRANT_COLLECTION answered "not covered" for good).
- conversation_memory never writes into, or deletes, a memory collection of
  another size: memory goes off with one ERROR instead.
- purge_old_turns also purges the other memory collection (CONTEXT_MEMORY_PURGE_ALSO),
  so the 384-dim chats kept for rollback still go after the retention window."""
import asyncio
from types import SimpleNamespace

import pytest

from app import conversation_memory, kb_ingest, llm, vectorstore
from app.config import settings


def _info(size, named=False):
    vec = SimpleNamespace(size=size)
    return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(
        vectors={"": vec} if named else vec)))


def test_vector_size_reads_plain_and_hybrid_collections():
    assert vectorstore.vector_size(_info(384)) == 384
    assert vectorstore.vector_size(_info(1024, named=True)) == 1024
    assert vectorstore.vector_size(SimpleNamespace()) is None


@pytest.fixture
def kb(monkeypatch):
    """A KB that passes every old skip check: enough points, all schemes, BM25."""
    chunks = [{"scheme": "MGNREGA", "text": f"piece {i}"} for i in range(10)]
    built = []

    async def embed(texts):
        return [[0.0] * 1024 for _ in (texts if isinstance(texts, list) else [texts])]

    async def recreate(dim, sparse=False):
        built.append(dim)
        raise RuntimeError("stop after the rebuild decision")

    async def count():
        return 10

    async def schemes():
        return {"MGNREGA"}

    async def sparse():
        return True

    monkeypatch.setattr(kb_ingest, "_collect_chunks", lambda: chunks)
    monkeypatch.setattr(kb_ingest, "_sme_sources", lambda: [])
    monkeypatch.setattr(kb_ingest, "_web_sources", lambda: [])
    monkeypatch.setattr(settings, "RAG_SPARSE_MODEL", "")
    monkeypatch.setattr(llm, "call_embedding", embed)
    monkeypatch.setattr(vectorstore, "collection_count", count)
    monkeypatch.setattr(vectorstore, "distinct_schemes", schemes)
    monkeypatch.setattr(vectorstore, "has_sparse", sparse)
    monkeypatch.setattr(vectorstore, "recreate_collection", recreate)
    return built


def _dim(monkeypatch, size):
    async def collection_dim(name=None):
        return size
    monkeypatch.setattr(vectorstore, "collection_dim", collection_dim)


def test_a_kb_of_another_vector_size_is_rebuilt(monkeypatch, kb):
    _dim(monkeypatch, 384)
    with pytest.raises(RuntimeError, match="stop after the rebuild"):
        asyncio.run(kb_ingest.ingest_kb())
    assert kb == [1024]


def test_a_kb_of_the_right_size_is_still_skipped(monkeypatch, kb):
    _dim(monkeypatch, 1024)
    assert asyncio.run(kb_ingest.ingest_kb()) == {"ingested": 0, "skipped": True, "points": 10}
    assert kb == []


def test_an_unknown_size_keeps_the_old_skip(monkeypatch, kb):
    _dim(monkeypatch, None)
    assert asyncio.run(kb_ingest.ingest_kb())["skipped"] is True

    async def down(texts):
        raise RuntimeError("gateway down")
    _dim(monkeypatch, 384)
    monkeypatch.setattr(llm, "call_embedding", down)
    assert asyncio.run(kb_ingest.ingest_kb())["skipped"] is True


class MemClient:
    def __init__(self, size=None, old=None):
        self.size, self.created, self.deleted = size, [], []
        self.old = old or {}

    async def get_collection(self, name):
        if self.size is None:
            raise RuntimeError("not found")
        return _info(self.size)

    async def create_collection(self, collection_name, vectors_config):
        self.created.append(vectors_config.size)

    async def collection_exists(self, name):
        return name in self.old

    async def count(self, name, count_filter, exact):
        return SimpleNamespace(count=self.old[name])

    async def delete(self, collection_name, points_selector, wait):
        self.deleted.append(collection_name)


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(conversation_memory, "_collection_ready", False)
    monkeypatch.setattr(conversation_memory, "_collection_wrong_size", False)


def test_memory_refuses_a_collection_of_another_size_and_never_deletes_it(monkeypatch, fresh):
    c = MemClient(size=384)
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    assert asyncio.run(conversation_memory._ensure_collection(1024)) is False
    assert asyncio.run(conversation_memory._ensure_collection(1024)) is False
    assert c.created == [] and c.deleted == []


def test_memory_uses_a_collection_of_the_right_size(monkeypatch, fresh):
    c = MemClient(size=1024)
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    assert asyncio.run(conversation_memory._ensure_collection(1024)) is True
    assert c.created == []


def test_memory_creates_a_missing_collection_at_the_model_size(monkeypatch, fresh):
    c = MemClient(size=None)
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    assert asyncio.run(conversation_memory._ensure_collection(1024)) is True
    assert c.created == [1024]


def test_purge_also_cleans_the_rollback_memory_collection(monkeypatch):
    c = MemClient(old={"mem_1024": 3, "mem_384": 5})
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 30)
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_COLLECTION", "mem_1024")
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_PURGE_ALSO", "mem_384, mem_1024, missing")
    assert asyncio.run(conversation_memory.purge_old_turns()) == 3
    assert c.deleted == ["mem_1024", "mem_384"]


def test_the_default_purge_list_names_both_memory_collections():
    names = {s.strip() for s in type(settings)().CONTEXT_MEMORY_PURGE_ALSO.split(",")}
    assert {"megh_conversation_memory", "megh_conversation_memory_1024"} <= names
