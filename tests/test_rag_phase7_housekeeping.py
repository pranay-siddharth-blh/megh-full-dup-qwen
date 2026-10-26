"""RAG upgrade Phase 7 (2026-10-15): security and housekeeping.

- KI-224: after "start a new topic", reset or idle expiry, semantic memory
  returns only turns indexed after that moment (Session.memory_since).
- Conversation memory older than CONTEXT_MEMORY_RETENTION_DAYS is never
  returned and is deleted (conversation_memory.purge_old_turns).
- An empty QDRANT_API_KEY is reported by insecure_secrets() at startup."""
import asyncio
import time
from types import SimpleNamespace

import pytest

from app import config, conversation_layer, conversation_memory, llm, vectorstore
from app.config import settings
from app.session_store import Session


class FakeClient:
    def __init__(self, exists=True, old=0):
        self.queries, self.deleted, self.counted = [], [], []
        self._exists, self._old = exists, old

    async def query_points(self, collection_name, query, query_filter, limit, with_payload,
                           search_params=None):
        self.queries.append(query_filter)
        self.search_params = search_params
        return SimpleNamespace(points=[])

    async def collection_exists(self, name):
        return self._exists

    async def count(self, name, count_filter, exact):
        self.counted.append(count_filter)
        return SimpleNamespace(count=self._old)

    async def delete(self, collection_name, points_selector, wait):
        self.deleted.append(points_selector)


@pytest.fixture
def client(monkeypatch):
    c = FakeClient()

    async def embed(q):
        return [[0.1, 0.2]]

    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", True)
    monkeypatch.setattr(llm, "call_embedding", embed)
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    return c


def _ts_floor(flt):
    conds = [m for m in flt.must if m.key == "ts"]
    return conds[0].range.gte if conds else None


def test_search_returns_only_turns_after_the_last_clear(monkeypatch, client):
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 30)
    since = time.time() - 60
    asyncio.run(conversation_memory.search_relevant_turns(
        question="what about tura?", tenant_id=1, user_id=7, session_id="s1", since=since))
    assert _ts_floor(client.queries[0]) == pytest.approx(since)


def test_search_never_returns_turns_older_than_the_retention_window(monkeypatch, client):
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 30)
    asyncio.run(conversation_memory.search_relevant_turns(
        question="what about tura?", tenant_id=1, user_id=7, session_id="s1"))
    assert _ts_floor(client.queries[0]) == pytest.approx(time.time() - 30 * 86400, abs=5)


def test_memory_search_is_exact(monkeypatch, client):
    """HNSW under a user/session filter missed a usable turn (2026-10-24, 1 of 300);
    one officer's 30-day turns are few, so the search is exact at the same speed."""
    asyncio.run(conversation_memory.search_relevant_turns(
        question="what about tura?", tenant_id=1, user_id=7, session_id="s1"))
    assert client.search_params is not None and client.search_params.exact is True


def test_a_new_memory_collection_gets_its_filter_indexes(monkeypatch):
    made = []

    class NewClient:
        async def get_collection(self, name):
            raise RuntimeError("not found")

        async def create_collection(self, collection_name, vectors_config):
            pass

        async def create_payload_index(self, collection_name, field_name, field_schema, wait):
            made.append((field_name, field_schema))

    monkeypatch.setattr(conversation_memory, "_collection_ready", False)
    monkeypatch.setattr(conversation_memory, "_collection_wrong_size", False)
    monkeypatch.setattr(vectorstore, "get_client", lambda: NewClient())
    assert asyncio.run(conversation_memory._ensure_collection(1024)) is True
    assert made == [("tenant_id", "integer"), ("user_id", "integer"),
                    ("session_id", "keyword"), ("ts", "float")]


def test_retention_zero_and_no_clear_means_no_time_filter(monkeypatch, client):
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 0)
    asyncio.run(conversation_memory.search_relevant_turns(
        question="what about tura?", tenant_id=1, user_id=7, session_id="s1"))
    assert _ts_floor(client.queries[0]) is None


def test_purge_deletes_only_turns_older_than_the_window(monkeypatch):
    c = FakeClient(old=42)
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 30)
    assert asyncio.run(conversation_memory.purge_old_turns()) == 42
    cond = c.deleted[0].filter.must[0]
    assert cond.key == "ts" and cond.range.lt == pytest.approx(time.time() - 30 * 86400, abs=5)


def test_purge_does_nothing_when_nothing_is_old_or_retention_is_off(monkeypatch):
    c = FakeClient(old=0)
    monkeypatch.setattr(vectorstore, "get_client", lambda: c)
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 30)
    assert asyncio.run(conversation_memory.purge_old_turns()) == 0 and not c.deleted
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 0)
    assert asyncio.run(conversation_memory.purge_old_turns()) is None


def test_a_purge_failure_never_raises(monkeypatch):
    class Broken(FakeClient):
        async def collection_exists(self, name):
            raise RuntimeError("qdrant down")
    monkeypatch.setattr(vectorstore, "get_client", lambda: Broken())
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_RETENTION_DAYS", 30)
    assert asyncio.run(conversation_memory.purge_old_turns()) is None


def test_clearing_the_context_records_when(monkeypatch):
    s = Session(session_id="s1", user_id="u", created=time.time(), last_seen=time.time())
    assert s.memory_since == 0.0
    before = time.time()
    conversation_layer.clear_context(s)
    assert s.memory_since >= before


def test_memory_since_survives_the_durable_snapshot():
    s = Session(session_id="s1", user_id="u", created=time.time(), last_seen=time.time())
    s.memory_since = 1_760_000_000.5
    snap = s.to_snapshot()
    assert snap["_session"]["memory_since"] == 1_760_000_000.5
    t = Session(session_id="s1", user_id="u", created=time.time(), last_seen=time.time())
    t.apply_snapshot(snap)
    assert t.memory_since == 1_760_000_000.5


def test_an_empty_qdrant_key_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "QDRANT_API_KEY", "")
    assert any("QDRANT_API_KEY" in p for p in config.insecure_secrets())
    monkeypatch.setattr(settings, "QDRANT_API_KEY", "set-by-infra")
    assert not any("QDRANT_API_KEY" in p for p in config.insecure_secrets())
