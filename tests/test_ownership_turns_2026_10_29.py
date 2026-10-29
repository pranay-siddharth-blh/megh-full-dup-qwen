"""
CTX-01 + CTX-10 + REL-02b (2026-10-29): who owns a conversation, one turn at a
time per conversation, and a session left as the turn found it when the turn
fails or is stopped.

  owner     a session id is not a secret: another logged-in user holding it
            got the chat's context and overwrote its state. Now 403, from this
            worker's copy (login) or the durable row (app.users id), and the
            owner's state is untouched. The SQL upserts refuse another owner too.
  lock      two requests on one id interleaved their reads and writes of the
            Session (only the graph run was locked). Now serialised per id.
  restore   a turn that failed (503 / 504 / 5xx) or was stopped kept a half-
            changed Session on its worker (a pending clarification already
            cleared): the retry behaved differently on that worker.
  deadline  the plain /api/query is capped below nginx's 120 s.

Real router._answer / query / _remember_stopped, real session_sync over a fake
app.conversations, real conversation_store functions over a fake db. The graph
is stubbed per test. No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_ownership_turns_2026_10_29.py -q
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import conversation_layer as cl, conversation_store, session_sync  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import ModelBusyError  # noqa: E402
from app.pipeline import ClarificationNeeded  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.session_store import session_store  # noqa: E402

Q = "How many person-days were generated under MGNREGA in East Khasi Hills in FY 2022-23?"


class FakeBackend:
    """app.conversations: JSON round trip, the revision guard, the owner."""

    def __init__(self):
        self.rows: dict = {}

    async def load(self, session_id):
        row = self.rows.get(session_id)
        return {} if row is None else {"context_state": json.loads(row["state"]), "summary": row["summary"],
                                       "user_id": row["user_id"]}

    async def save(self, *, tenant_id, user_id, session_id, title, snapshot, rev, summary):
        cur = self.rows.get(session_id)
        if cur and (int(json.loads(cur["state"]).get("rev") or 0) >= rev or cur["user_id"] != user_id):
            return False
        self.rows[session_id] = {"state": json.dumps({**snapshot, "rev": rev}, default=str),
                                 "summary": summary, "user_id": user_id}
        return True


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


def _scope(login, db_id):
    return SimpleNamespace(user_id=login, db_user_id=db_id, tenant_id=1, username=login,
                           cache_fingerprint=lambda: f"fp-{login}")


def _data(question):
    return {"route": "data", "intent": "DATA", "schemes": ["MGNREGA"], "sql": "SELECT 1", "sql_query": "SELECT 1",
            "resolved_entities": {"district": "EAST KHASI HILLS", "year_key": 2022}, "row_count": 1,
            "rows": [{"n": 1}], "data": [{"n": 1}], "answer": "MGNREGA answer.", "confidence": "high"}


@pytest.fixture
def env(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED", "CONVERSATION_LAYER_ENABLED",
                 "CONTEXT_STATE_SHARED"):
        monkeypatch.setattr(settings, flag, True)
    backend = FakeBackend()
    monkeypatch.setattr(session_sync, "_default_backend", backend)
    state = SimpleNamespace(pipeline=None, backend=backend)

    async def answer_question(q, session=None, scope=None):
        if state.pipeline is not None:
            return await state.pipeline(q, session)
        from app import context_manager as cm
        result = _data(q)
        cm.update_state(session, q, q, result)
        return result

    async def noop(*a, **k):
        return None

    async def miss(*a, **k):
        return None, None
    monkeypatch.setattr(router.response_cache, "get", noop)
    monkeypatch.setattr(router.response_cache, "put", noop)
    monkeypatch.setattr(router.semantic_cache, "lookup", miss)
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    monkeypatch.setattr(router.context_manager, "maybe_update_summary", noop)
    monkeypatch.setattr(cl, "_drop_paused_run", noop)
    return state


def _post(scope, question, sid, request=None):
    return asyncio.run(router._answer(router.QueryRequest(question=question, session_id=sid),
                                      request or _request(), scope))


# ── Ownership ───────────────────────────────────────────────────────────────

def test_another_user_on_the_same_id_gets_403_and_the_owner_is_untouched(env):
    sid = "own-mem-1"
    alice, bob = _scope("alice", 1), _scope("bob", 2)
    _post(alice, Q, sid)
    s = session_store.ensure(sid, "alice")
    before_state, before_row = s.state.to_dict(), dict(env.backend.rows[sid])
    with pytest.raises(HTTPException) as e:
        _post(bob, "What about FY 2023-24?", sid)
    assert e.value.status_code == 403
    assert s.state.to_dict() == before_state and env.backend.rows[sid] == before_row
    assert s.user_id == "alice"


def test_the_durable_owner_is_checked_on_a_worker_that_never_saw_the_chat(env):
    sid = "own-durable-1"
    alice, bob = _scope("alice", 1), _scope("bob", 2)
    _post(alice, Q, sid)
    row = dict(env.backend.rows[sid])
    session_store.drop(sid)                                 # another worker: no local copy
    with pytest.raises(HTTPException) as e:
        _post(bob, "What did we discuss?", sid)
    assert e.value.status_code == 403
    assert env.backend.rows[sid] == row
    # the empty copy made for bob is gone, so the owner is not refused on this worker
    assert session_store.get(sid) is None
    out = _post(alice, "What about FY 2023-24?", sid)
    assert out["session_id"] == sid


def test_the_owner_continues_and_unknown_owners_are_not_checked(env):
    sid = "own-ok-1"
    alice = _scope("alice", 1)
    _post(alice, Q, sid)
    _post(alice, "What about FY 2023-24?", sid)
    # a row stored before owners were recorded (or a dev run without logins)
    env.backend.rows["own-legacy-1"] = {"state": json.dumps({"rev": 3}), "summary": None, "user_id": None}
    assert asyncio.run(session_sync.sync_in(session_store.ensure("own-legacy-1", "alice"), "own-legacy-1",
                                            user_id=1)) != "foreign"


def test_sync_in_does_not_apply_a_foreign_snapshot(env):
    env.backend.rows["own-sync-1"] = {"state": json.dumps({"rev": 5, "scheme": "PMAY-G"}), "summary": "theirs",
                                      "user_id": 7}
    s = session_store.ensure("own-sync-1", "me")
    assert asyncio.run(session_sync.sync_in(s, "own-sync-1", user_id=8)) == "foreign"
    assert s.rev == 0 and s.state.scheme is None and s.summary is None


def test_a_refused_request_records_no_stopped_question(env):
    sid = "own-stop-1"
    alice, bob = _scope("alice", 1), _scope("bob", 2)
    _post(alice, Q, sid)
    req, request = router.QueryRequest(question="What about Ri Bhoi?", session_id=sid), _request()
    with pytest.raises(HTTPException):
        asyncio.run(router._answer(req, request, bob))
    router._remember_stopped(req, request, bob)
    assert session_store.ensure(sid, "alice").stopped_ctx is None


def test_the_upserts_refuse_another_owner(monkeypatch):
    calls = []

    async def fetchval(sql, params):
        calls.append(("fetchval", sql))
        return None                                         # the owner clause refused the update

    async def execute(sql, params):
        calls.append(("execute", sql))
    monkeypatch.setattr(conversation_store.db, "fetchval", fetchval)
    monkeypatch.setattr(conversation_store.db, "execute", execute)
    asyncio.run(conversation_store._persist_turn(1, 2, "own-sql-1", _data(Q), Q, 10.0, "bob", "127.0.0.1"))
    assert "IS NOT DISTINCT FROM EXCLUDED.user_id" in calls[0][1]
    inserts = [sql for kind, sql in calls if kind == "execute"]
    assert not any("conversation_turns" in sql for sql in inserts)      # not added to the owner's history
    assert any("query_audit" in sql for sql in inserts)                 # the audit row is still written

    seen = {}

    async def fetchrow(sql, params):
        seen["sql"] = sql
        return None
    monkeypatch.setattr(conversation_store.db, "fetchrow", fetchrow)
    assert asyncio.run(conversation_store.save_session_state(
        tenant_id=1, user_id=2, session_id="own-sql-1", title="t", snapshot={}, rev=1, summary=None)) is False
    assert "IS NOT DISTINCT FROM EXCLUDED.user_id" in seen["sql"]


def test_load_context_state_returns_the_owner(monkeypatch):
    async def fetchrow(sql, params):
        return {"context_state": json.dumps({"rev": 2}), "summary": None, "user_id": 4}
    monkeypatch.setattr(conversation_store.db, "fetchrow", fetchrow)
    assert asyncio.run(conversation_store.load_context_state("x"))["user_id"] == 4


# ── One turn at a time per conversation ─────────────────────────────────────

def test_two_turns_on_one_id_are_serialised_and_other_ids_are_not(env):
    live, peak = {}, {}

    async def slow(q, session):
        sid = session.session_id
        live[sid] = live.get(sid, 0) + 1
        peak[sid] = max(peak.get(sid, 0), live[sid])
        await asyncio.sleep(0.05)
        live[sid] -= 1
        return _data(q)
    env.pipeline = slow
    alice = _scope("alice", 1)

    async def main():
        def one(q, sid):
            return router._answer(router.QueryRequest(question=q, session_id=sid), _request(), alice)
        await asyncio.gather(one(Q, "lock-a"), one(Q + " ", "lock-a"), one(Q, "lock-b"))
    asyncio.run(main())
    assert peak["lock-a"] == 1
    assert router._TURN_LOCKS == {}                         # nothing left behind


# ── The session as the turn found it ────────────────────────────────────────

def _paused(env, sid):
    """data -> a scope pause: the session waits for the reply."""
    alice = _scope("alice", 1)
    paused_q = "How many MGNREGA person-days?"

    async def pause(q, session):
        raise ClarificationNeeded("Which area?", rule=next(iter(router.SCOPE_MERGE_RULES)))
    env.pipeline = pause
    _post(alice, paused_q, sid)
    s = session_store.ensure(sid, "alice")
    assert s.pending_scope_q == paused_q
    return alice, s, paused_q


@pytest.mark.parametrize("error,status", [(ModelBusyError("busy"), 503), (asyncio.TimeoutError(), 504),
                                          (RuntimeError("boom"), 502)])
def test_a_failed_reply_keeps_the_pending_question(env, error, status):
    sid = f"restore-{status}"
    alice, s, paused_q = _paused(env, sid)

    async def fail(q, session):
        # what the context stage does first: the reply resumes the pause
        session.pending_scope_q = None
        session.state.district = "WEST GARO HILLS"
        raise error
    env.pipeline = fail
    with pytest.raises(HTTPException) as e:
        _post(alice, "West Garo Hills", sid)
    assert e.value.status_code == status
    assert s.pending_scope_q == paused_q and s.state.district is None
    # and the retry is a reply to the same pause, on this worker as on any other
    seen = {}

    async def resume(q, session):
        seen["pending"] = session.pending_scope_q
        return _data(q)
    env.pipeline = resume
    _post(alice, "West Garo Hills", sid)
    assert seen["pending"] == paused_q


def test_a_stop_restores_the_session_and_records_the_question(env):
    sid = "restore-stop"
    alice = _scope("alice", 1)
    _post(alice, Q, sid)
    s = session_store.ensure(sid, "alice")
    before = s.state.to_dict()
    reached = {}

    async def runs_long(q, session):
        session.state.district = "RI BHOI"            # a change made before the Stop
        session.state.year = 2019
        reached["yes"] = True
        await asyncio.sleep(3600)

    env.pipeline = runs_long

    async def main():
        req, request = router.QueryRequest(question="What about Ri Bhoi?", session_id=sid), _request()
        task = asyncio.create_task(router._answer(req, request, alice))
        while not reached:
            await asyncio.sleep(0.01)
        task.cancel()                                  # what the stream does when the client leaves
        router._remember_stopped(req, request, alice)
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(main())
    assert s.state.to_dict() == before
    assert s.stopped_ctx and s.stopped_ctx["question"] == "What about Ri Bhoi?"
    assert router._TURN_LOCKS == {}


# ── REL-02b: the plain request's deadline ───────────────────────────────────

def test_the_plain_request_is_capped_and_the_stream_is_not(env, monkeypatch):
    monkeypatch.setattr(settings, "QUERY_NONSTREAM_MAX_SECONDS", 0.05)
    monkeypatch.setattr(settings, "REQUEST_TIMEOUT_SECONDS", 5)

    async def slow(q, session):
        await asyncio.sleep(0.2)
        return _data(q)
    env.pipeline = slow
    alice = _scope("alice", 1)
    with pytest.raises(HTTPException) as e:
        asyncio.run(router.query(router.QueryRequest(question=Q, session_id="cap-1"), _request(), alice))
    assert e.value.status_code == 504
    out = _post(alice, Q, "cap-2")                         # the streamed route's body: not capped
    assert out["answer"] == "MGNREGA answer."
