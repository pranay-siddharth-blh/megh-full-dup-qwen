"""
KI-319 (2026-10-18): an answer served from the shared answer cache skips the
graph, so its context_update node never ran — the structured state, the
ledger scope, the idle "continue?" chip and the scope banner were missing
after a cache hit. The router now folds a cached answer into the session
exactly as the graph does for a computed one. Real router._answer; the cache
returns a canned data result; the pipeline must not be called.
    .venv/Scripts/python.exe -m pytest tests/test_cache_hit_context.py -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import conversation_layer as cl, topic_memory as tm  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.session_store import session_store  # noqa: E402

Q = "How many person-days were generated under MGNREGA in East Khasi Hills in FY 2022-23?"
CACHED = {"answer": "East Khasi Hills generated 3,408,697 person-days under MGNREGA in FY 2022-23.",
          "route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1", "sql_query": "SELECT 1",
          "resolved_entities": {"district": "EAST KHASI HILLS", "year_key": 2022}, "row_count": 1,
          "rows": [{"person_days": 3408697}], "data": [{"person_days": 3408697}]}


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


@pytest.fixture
def cached(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_LAYER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_STATE_ENABLED", True)
    monkeypatch.setattr(settings, "CONVERSATION_LAYER_ENABLED", True)

    async def cache_get(q, scope_key):
        return dict(CACHED)

    async def answer_question(q, session=None, scope=None):
        raise AssertionError("the pipeline must not run on a cache hit")

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(router.response_cache, "get", cache_get)
    monkeypatch.setattr(router.response_cache, "put", noop)
    monkeypatch.setattr(router.semantic_cache, "lookup", noop)
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.session_sync, "sync_in", noop)
    monkeypatch.setattr(router.session_sync, "sync_out", noop)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    monkeypatch.setattr(router.context_manager, "maybe_update_summary", noop)
    return SimpleNamespace(user_id="u", db_user_id=None, tenant_id=None, username="",
                           cache_fingerprint=lambda: "fp")


def _post(scope, question, sid):
    return asyncio.run(router._answer(router.QueryRequest(question=question, session_id=sid), _request(), scope))


def test_a_cached_answer_updates_the_structured_state_and_carries_the_banner(cached):
    out = _post(cached, Q, "cache-ctx-1")
    s = session_store.ensure("cache-ctx-1", "u")
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", "EAST KHASI HILLS", 2022)
    assert out["scope_banner"] == "MGNREGA · East Khasi Hills · FY 2022-23"
    assert s.last_turn is not None and s.last_turn.schemes == ["MGNREGA"]


def test_the_next_turn_files_the_cached_answer_with_its_scope(cached):
    _post(cached, Q, "cache-ctx-2")
    s = session_store.ensure("cache-ctx-2", "u")
    s.turn_context = {}
    tm.checkpoint(s)                                     # what the next turn's context stage does first
    e = s.topics["items"]["MGNREGA"]["ledger"][-1]
    assert e["state"]["district"] == "EAST KHASI HILLS" and e["state"]["year"] == 2022


def test_idle_expiry_after_a_cached_answer_still_offers_the_chip(cached, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 60)

    async def drop(_sid):
        return None
    monkeypatch.setattr(cl, "_drop_paused_run", drop)
    _post(cached, Q, "cache-ctx-3")
    s = session_store.ensure("cache-ctx-3", "u")
    s.context_at -= 61
    assert cl._set_aside(s) == "Continue with MGNREGA (East Khasi Hills, FY 2022-23)"
