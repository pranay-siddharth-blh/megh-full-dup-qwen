"""KI-399 / KI-400 — context-memory audit 2026-10-23, F1 and F2.

KI-399: /api/query used the client's session_id as is, so another signed-in user
sending the same id continued that conversation (in-process session, durable
context_state and graph thread are all keyed on the id). Closed by CTX-01: the
router refuses another user's conversation with a 403 (tests below point to its tests).

KI-400: topic_memory.checkpoint dropped every topic when the revision jumped by more
than one, but cache hits, edges, resets and stops move the revision without a graph
turn — one cached answer wiped the topics. CTX-02 (Main) removed the reset.

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
# Closed by CTX-01 (Main, PR #21): a request on another user's conversation is REFUSED
# with a 403 ("start a new chat") — tests/test_ownership_turns_2026_10_29.py and
# tests/test_conversation_layer.py cover the in-memory and durable owners. The open-bug
# sweep's silent swap to a new "own-…" id (routers.query._owned_session_id) ran before
# that check and hid it; it was removed after Bitbucket pipeline #87 (2026-10-29).
def test_the_silent_new_id_swap_is_gone_ctx01_refuses_instead():
    assert not hasattr(query, "_owned_session_id")
    assert hasattr(query, "_refuse_foreign")


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


def test_a_revision_jump_keeps_the_topics():
    # CTX-02 / KI-400 as merged on Main (PR #21, 2026-10-29): checkpoint() no longer resets the
    # topics on a revision jump — cache hits, small talk and "stop" save a revision without a
    # graph turn, and the reset wiped every topic; the topics travel in the durable snapshot.
    s = Session(session_id="t", user_id="u", created=time.time(), last_seen=time.time())
    s.rev = 9
    s.topics = {"active": "MGNREGA", "order": ["MGNREGA"], "ack": None, "rev": 4,
                "items": {"MGNREGA": {"schemes": ["MGNREGA"], "state": None, "last_turn": None,
                                      "questions": [], "turns": 1, "summary": "MGNREGA"}}}
    topic_memory.checkpoint(s)
    assert "MGNREGA" in s.topics["items"]
