"""
CTX-13 + CTX-14 (2026-10-29), through the real router and the real graph.

  stop      a typed "stop" with nothing running was recorded as the last turn,
            so it became the follow-up antecedent: after MGNREGA -> "stop",
            "What about FY 2023-24?" reached the data path with no scheme (with
            "thanks" in between it correctly read "... under MGNREGA").
  offer     after an idle expiry, a first reply that PAUSES returned before the
            "Continue with ..." chip was attached, and the next message dropped
            the set-aside context. Tapping the chip must also abandon that pause.
  cache     a Khasi / Garo question's own words (translated_from) were written to
            the shared answer cache and served to the next asker in that scope.

The data path is stubbed at the scope_scheme stage (tests/_graph_turn.py) and
records the question it receives; the model is unreachable on purpose, as
offline. No DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_stop_offer_cache_2026_10_29.py -q
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, conversation_layer as cl, entity_resolver, llm, session_sync  # noqa: E402
from app import pipeline as p, translate  # noqa: E402
from app.config import settings  # noqa: E402
from app.pipeline import ClarificationNeeded  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.session_store import session_store  # noqa: E402
from _graph_turn import stub_data_path  # noqa: E402

Q = "How many person-days were generated under MGNREGA in East Khasi Hills in FY 2022-23?"
VAGUE = "How many beneficiaries are there?"


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


@pytest.fixture
def chat(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED", "CONVERSATION_LAYER_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "PIPELINE_GRAPH_CHECKPOINTER_DSN", "memory")
    seen: list = []
    puts: list = []

    async def data(question, scope=None, **kw):
        seen.append(question)
        if question == VAGUE:
            raise ClarificationNeeded("Which area should I use?", rule=next(iter(router.SCOPE_MERGE_RULES)))
        return {"route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1",
                "sql_query": "SELECT 1", "resolved_entities": {"district": "EAST KHASI HILLS", "year_key": 2022},
                "rows": [{"n": 1}], "data": [{"n": 1}], "row_count": 1, "answer": "MGNREGA answer.",
                "confidence": "high"}
    stub_data_path(monkeypatch, data)

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")

    async def noop(*a, **k):
        return None

    async def miss(*a, **k):
        return None, None

    async def put(q, result, scope_key):
        puts.append(result)
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    monkeypatch.setattr(router.response_cache, "get", noop)
    monkeypatch.setattr(router.response_cache, "put", put)
    monkeypatch.setattr(router.semantic_cache, "lookup", miss)
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(session_sync, "sync_in", noop)
    monkeypatch.setattr(session_sync, "sync_out", noop)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    monkeypatch.setattr(router.context_manager, "maybe_update_summary", noop)
    monkeypatch.setattr(cl, "_drop_paused_run", noop)
    scope = SimpleNamespace(user_id="u", db_user_id=None, tenant_id=None, username="",
                            cache_fingerprint=lambda: "fp")
    return SimpleNamespace(scope=scope, seen=seen, puts=puts)


def _post(chat, question, sid, language="en"):
    return asyncio.run(router._answer(router.QueryRequest(question=question, session_id=sid, language=language),
                                      _request(), chat.scope))


# ── CTX-13: "stop" ──────────────────────────────────────────────────────────

def test_stop_with_nothing_running_keeps_the_follow_up_on_its_scheme(chat):
    sid = "ctx13-stop"
    _post(chat, Q, sid)
    out = _post(chat, "stop", sid)
    assert out["edge_type"] == cl.NOTHING_RUNNING_EDGE
    assert session_store.ensure(sid, "u").last_turn.schemes == ["MGNREGA"]   # not the stop reply
    _post(chat, "What about FY 2023-24?", sid)
    assert "MGNREGA" in chat.seen[-1]


def test_stop_keeps_every_topic(chat):
    from app import topic_memory as tm
    sid = "ctx13-topics"
    _post(chat, Q, sid)
    s = session_store.ensure(sid, "u")
    s.topics.setdefault("items", {})
    tm.checkpoint(s)
    _post(chat, "stop", sid)
    _post(chat, "What about FY 2023-24?", sid)
    assert "MGNREGA" in s.topics["items"]


# ── CTX-13: the Continue offer after an idle expiry ─────────────────────────

def test_a_paused_first_reply_after_expiry_carries_the_offer_and_the_tap_drops_the_pause(chat, monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 60)
    sid = "ctx13-expiry"
    _post(chat, Q, sid)
    s = session_store.ensure(sid, "u")
    s.context_at -= 61
    paused = _post(chat, VAGUE, sid)                  # expired, then the pipeline pauses
    assert paused["route"] == "clarification"
    chip = paused.get("continue_offer")
    assert chip and chip.startswith("Continue with MGNREGA")
    assert s.pending_scope_q                           # the pause is remembered ...
    _post(chat, chip, sid)                             # ... until the officer taps the chip
    assert s.pending_scope_q is None
    _post(chat, "What about FY 2023-24?", sid)
    assert "MGNREGA" in chat.seen[-1] and "beneficiaries" not in chat.seen[-1].lower()


# ── CTX-14: no translated_from in the shared caches ─────────────────────────

def test_the_officers_own_words_are_not_cached(chat, monkeypatch):
    lang = next(iter(translate.LANGUAGE_NAMES))

    async def to_english(text, language):
        return Q
    monkeypatch.setattr(translate, "to_english", to_english)
    out = _post(chat, "<the same question in Khasi>", "ctx14-cache", language=lang)
    assert out["translated_from"] == "<the same question in Khasi>"      # shown to the asker
    assert chat.puts and all("translated_from" not in r for r in chat.puts)


def test_pipeline_namespace_untouched():
    # nothing in this task adds a pipeline name; the router helpers live in the router
    assert not hasattr(p, "_answer_turn")
