"""
CTX-11 (2026-10-29): "start a new topic" and the idle expiry clear the rolling
summary on the worker that served them (conversation_layer.clear_context), but
the durable upsert kept the old one (summary = COALESCE(new, old)) and a fresh
worker's sync_in restored it, so the follow-up rewrite there was primed with
the cleared chat's scheme, place and year ("Conversation summary so far: …").

Real conversation_layer.prepare_turn, real session_sync.sync_in / sync_out over
a fake app.conversations that copies the upsert (summary = EXCLUDED.summary,
the revision guard), real context_manager.build_followup_context. No model,
DB or VPN. CTX-12 (the load retry) is in tests/test_session_sync_retry.py.
    .venv/Scripts/python.exe -m pytest tests/test_summary_reset_2026_10_29.py -q
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_manager as cm, conversation_layer as cl, conversation_store, session_sync  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import Session, Turn  # noqa: E402

OLD = "The chat was about MGNREGA person-days in East Khasi Hills in FY 2022-23."


class UpsertBackend:
    """app.conversations as save_session_state now writes it."""

    def __init__(self):
        self.rows: dict = {}

    async def load(self, session_id):
        row = self.rows.get(session_id)
        return {} if row is None else {"context_state": json.loads(row["state"]), "summary": row["summary"]}

    async def save(self, *, tenant_id, user_id, session_id, title, snapshot, rev, summary):
        cur = self.rows.get(session_id)
        if cur and int(json.loads(cur["state"]).get("rev") or 0) >= rev:
            return False
        self.rows[session_id] = {"state": json.dumps({**snapshot, "rev": rev}, default=str), "summary": summary}
        return True


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    for flag in ("CONTEXT_STATE_SHARED", "CONTEXT_LAYER_ENABLED", "CONTEXT_SUMMARY_ENABLED",
                 "CONVERSATION_LAYER_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", False)

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(cl, "_drop_paused_run", noop)


def _session():
    return Session(session_id="sum-1", user_id="u", created=time.time(), last_seen=time.time())


def _chat_with_summary(be):
    """A worker whose chat has a summary, saved."""
    s = _session()
    s.state.scheme, s.state.district, s.state.year = "MGNREGA", "EAST KHASI HILLS", 2022
    s.turns.append(Turn(question="MGNREGA person-days in East Khasi Hills in FY 2022-23", raw_question="",
                        route="data", schemes=["MGNREGA"]))
    s.summary = OLD
    s.context_at = time.time()
    assert asyncio.run(session_sync.sync_out(s, "sum-1", tenant_id=1, user_id=1, backend=be))
    return s


def _fresh_worker(be):
    other = _session()
    asyncio.run(session_sync.sync_in(other, "sum-1", backend=be))
    return other


def _window(session):
    return asyncio.run(cm.build_followup_context(session, "what about Ri Bhoi?"))


def test_a_reset_clears_the_summary_on_every_worker():
    be = UpsertBackend()
    s = _chat_with_summary(be)
    asyncio.run(cl.prepare_turn(s, "start a new topic"))
    assert s.summary is None
    asyncio.run(session_sync.sync_out(s, "sum-1", tenant_id=1, user_id=1, backend=be))
    other = _fresh_worker(be)
    assert other.summary is None
    assert cm.SUMMARY_HEADER not in _window(other)


def test_an_idle_expiry_clears_the_summary_on_every_worker(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 60)
    be = UpsertBackend()
    s = _chat_with_summary(be)
    s.context_at -= 61
    asyncio.run(cl.prepare_turn(s, "How many PMAY-G houses?"))
    assert s.summary is None
    asyncio.run(session_sync.sync_out(s, "sum-1", tenant_id=1, user_id=1, backend=be))
    other = _fresh_worker(be)
    assert other.summary is None and cm.SUMMARY_HEADER not in _window(other)


def test_a_worker_that_held_the_old_summary_drops_it_too():
    be = UpsertBackend()
    s = _chat_with_summary(be)
    stale = _fresh_worker(be)                        # another worker, summary loaded
    assert stale.summary == OLD
    asyncio.run(cl.prepare_turn(s, "start a new topic"))
    asyncio.run(session_sync.sync_out(s, "sum-1", tenant_id=1, user_id=1, backend=be))
    stale.turns = []                                 # its copy is behind the durable revision
    asyncio.run(session_sync.sync_in(stale, "sum-1", backend=be))
    assert stale.summary is None and stale.summary_turn_count == 0


def test_a_summary_written_after_the_reset_survives():
    be = UpsertBackend()
    s = _chat_with_summary(be)
    asyncio.run(cl.prepare_turn(s, "start a new topic"))
    s.summary = "PMAY-G houses in Ri Bhoi."
    asyncio.run(session_sync.sync_out(s, "sum-1", tenant_id=1, user_id=1, backend=be))
    other = _fresh_worker(be)
    assert other.summary == "PMAY-G houses in Ri Bhoi."
    assert "PMAY-G houses in Ri Bhoi." in _window(other)


def test_the_upsert_writes_the_summary_as_given(monkeypatch):
    seen = {}

    async def fetchrow(sql, params):
        seen["sql"], seen["params"] = sql, params
        return {"conv_id": 1}
    monkeypatch.setattr(conversation_store.db, "fetchrow", fetchrow)
    assert asyncio.run(conversation_store.save_session_state(
        tenant_id=1, user_id=1, session_id="sum-1", title="t", snapshot={}, rev=2, summary=None))
    assert "summary = EXCLUDED.summary" in seen["sql"]
    assert "COALESCE(EXCLUDED.summary" not in seen["sql"]
    assert seen["params"][5] is None


def test_a_db_error_on_load_reaches_the_retry(monkeypatch):
    async def fetchrow(sql, params):
        raise ConnectionError("db down")
    monkeypatch.setattr(conversation_store.db, "fetchrow", fetchrow)
    with pytest.raises(ConnectionError):
        asyncio.run(conversation_store.load_context_state("sum-1"))
