"""KI-399 / KI-400 — context-memory audit 2026-10-23, F1 and F2.

KI-399: /api/query used the client's session_id as is, so another signed-in user
sending the same id continued that conversation (in-process session, durable
context_state and graph thread are all keyed on the id). routers.query._owned_session_id
now gives a caller a NEW conversation when the id belongs to someone else.

KI-400: topic_memory.checkpoint drops every topic when the revision jumped by more
than one since it last ran, but every saved turn (cache hit, edge, reset, stop) moves
the revision while checkpoint runs only on graph turns — one cached answer between two
graph turns wiped the topics. session_sync.sync_out now stamps the revision it wrote
into the topic memory.

OFFLINE: the real functions; a fake storage backend and owner lookup.
    .venv/Scripts/python.exe -m pytest tests/test_session_ownership_topics_ki399_ki400_2026_10_29.py -q
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import conversation_store, session_sync, topic_memory  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query  # noqa: E402
from app.session_store import Session  # noqa: E402


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── KI-399 ────────────────────────────────────────────────────────────────────
def _scope(user, db_id):
    return SimpleNamespace(user_id=user, db_user_id=db_id)


def _request():
    return SimpleNamespace(state=SimpleNamespace())


@pytest.fixture
def owners(monkeypatch):
    stored = {}

    async def owner(sid):
        return stored.get(sid)
    monkeypatch.setattr(conversation_store, "conversation_owner", owner)
    return stored


def test_a_conversation_of_another_user_is_not_continued(owners):
    owners["chat-123"] = {"tenant_id": 1, "user_id": 7}
    req = _request()
    sid = _run(query._owned_session_id("chat-123", req, _scope("bob", 9)))
    assert sid != "chat-123" and sid.startswith("own-")
    assert req.state.megh_session_id == sid                # the stop handler sees the same id


def test_the_owner_and_a_new_id_keep_their_conversation(owners):
    owners["chat-123"] = {"tenant_id": 1, "user_id": 7}
    assert _run(query._owned_session_id("chat-123", _request(), _scope("alice", 7))) == "chat-123"
    assert _run(query._owned_session_id("fresh-1", _request(), _scope("bob", 9))) == "fresh-1"
    assert _run(query._owned_session_id("api-abc", _request(), _scope("bob", 9))) == "api-abc"


def test_a_live_in_process_session_of_another_user_is_not_continued(owners, monkeypatch):
    monkeypatch.setattr(query.session_store, "owner", lambda sid: "alice" if sid == "mem-1" else None)
    assert _run(query._owned_session_id("mem-1", _request(), _scope("bob", None))).startswith("own-")


# ── KI-400 ────────────────────────────────────────────────────────────────────
class Store:
    def __init__(self):
        self.stored = None

    async def load(self, session_id):
        return None

    async def save(self, **kw):
        self.stored = {**kw["snapshot"], "rev": kw["rev"]}
        return True


def test_a_cached_turn_between_graph_turns_keeps_the_topics(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_STATE_SHARED", True)
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.rev = 4
    s.topics = {"active": "MGNREGA", "order": ["MGNREGA"], "ack": None, "rev": 4,
                "items": {"MGNREGA": {"schemes": ["MGNREGA"], "state": None, "last_turn": None,
                                      "questions": [], "turns": 1, "summary": "MGNREGA"}}}
    store = Store()
    # a cache hit (no graph turn, so no checkpoint) is saved: rev 4 -> 5
    _run(session_sync.sync_out(s, "t", tenant_id=1, user_id=1, backend=store))
    # the graph turn after it saves again: rev 5 -> 6, then checkpoint runs on the next turn
    _run(session_sync.sync_out(s, "t", tenant_id=1, user_id=1, backend=store))
    topic_memory.checkpoint(s)
    assert "MGNREGA" in s.topics["items"], "one cached turn wiped the topics"


def test_a_jump_from_another_worker_still_resets_stale_topics():
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.rev = 9                                           # another worker wrote 5..9; this copy saw 4
    s.topics = {"active": "MGNREGA", "order": ["MGNREGA"], "ack": None, "rev": 4,
                "items": {"MGNREGA": {"schemes": ["MGNREGA"], "state": None, "last_turn": None,
                                      "questions": [], "turns": 1, "summary": "MGNREGA"}}}
    topic_memory.checkpoint(s)
    assert s.topics["items"] == {}
