"""
KI-314 (2026-10-18): a snapshot load / save that fails once (a brief DB drop)
is retried once, so the next request on another worker does not answer in a
stale scope. Fake backend, no DB.
    .venv/Scripts/python.exe -m pytest tests/test_session_sync_retry.py -q
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import conversation_store, session_sync  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import Session  # noqa: E402


class Flaky:
    """Fails the first `fail` calls of each kind, then works."""

    def __init__(self, fail=1):
        self.fail = {"load": fail, "save": fail}
        self.calls = {"load": 0, "save": 0}
        self.stored = None

    async def load(self, session_id):
        self.calls["load"] += 1
        if self.fail["load"] > 0:
            self.fail["load"] -= 1
            raise ConnectionError("connection was closed in the middle of operation")
        return {"context_state": self.stored, "summary": None} if self.stored else None

    async def save(self, **kw):
        self.calls["save"] += 1
        if self.fail["save"] > 0:
            self.fail["save"] -= 1
            raise ConnectionError("connection was closed in the middle of operation")
        self.stored = {**kw["snapshot"], "rev": kw["rev"]}
        return True


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_STATE_SHARED", True)
    monkeypatch.setattr(settings, "CONTEXT_STATE_SYNC_RETRY_SECONDS", 0.01)


def _session():
    return Session(session_id="s", user_id="u", created=time.time(), last_seen=time.time())


def test_a_save_that_fails_once_is_retried_and_stored():
    be = Flaky(fail=1)
    s = _session()
    ok = asyncio.run(session_sync.sync_out(s, "s", tenant_id=1, user_id=1, backend=be))
    assert ok and be.calls["save"] == 2 and s.rev == 1 and be.stored["rev"] == 1


def _flaky_fetchrow(monkeypatch, fail):
    """The REAL PostgresBackend -> conversation_store.load_context_state, over a
    db.fetchrow that fails `fail` times (CTX-12: load_context_state swallowed
    the error into {}, so the retry never ran; a fake backend that raised hid
    that)."""
    calls = {"n": 0, "fail": fail}

    async def fetchrow(sql, params):
        calls["n"] += 1
        if calls["fail"] > 0:
            calls["fail"] -= 1
            raise ConnectionError("connection was closed in the middle of operation")
        return {"context_state": json.dumps({"rev": 1, "scheme": "MGNREGA"}), "summary": None, "user_id": None}
    monkeypatch.setattr(conversation_store.db, "fetchrow", fetchrow)
    return calls


def test_a_load_that_fails_once_is_retried_and_applied(monkeypatch):
    calls = _flaky_fetchrow(monkeypatch, fail=1)
    other = _session()
    assert asyncio.run(session_sync.sync_in(other, "s", backend=session_sync.PostgresBackend())) == "applied"
    assert calls["n"] == 2 and other.rev == 1 and other.state.scheme == "MGNREGA"


def test_two_failures_in_a_row_still_give_up_quietly(monkeypatch):
    be = Flaky(fail=2)
    s = _session()
    assert asyncio.run(session_sync.sync_out(s, "s", tenant_id=1, user_id=1, backend=be)) is False
    assert be.calls["save"] == 2 and s.rev == 0
    calls = _flaky_fetchrow(monkeypatch, fail=2)
    assert asyncio.run(session_sync.sync_in(_session(), "s", backend=session_sync.PostgresBackend())) \
        == "unavailable"
    assert calls["n"] == 2
