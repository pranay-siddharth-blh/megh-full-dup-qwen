"""
CTX-04a + CTX-14 memory part (2026-10-29).

  delete     deleting a chat removed only its two DB tables. Its turns stayed in
             conversation memory (Qdrant), a paused graph run stayed in the
             checkpointer, and this worker's Session stayed in memory, so the
             same id did not start empty. The delete route now removes all three,
             after the ownership-checked DB delete succeeded; the Qdrant filter
             always names the session and its owner.
  retention  conversations, their turns and the query audit never expired.
             CONVERSATION_RETENTION_DAYS / QUERY_AUDIT_RETENTION_DAYS (0 = keep,
             the default until the user picks a period), purged once a day by
             the existing conversation_memory.purge_loop.
  memory ts  a turn was stamped when its embedding came back, so a slow gateway
             could stamp turn N-1 after a quick "start a new topic" and it came
             back past memory_since. Stamped when answered now.

Real routers.history.delete_my_conversation, conversation_memory,
pipeline_graph (in-process checkpointer) and appdb functions; Qdrant and the
DB are fakes. No VPN.
    .venv/Scripts/python.exe -m pytest tests/test_delete_retention_2026_10_29.py -q
"""
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import appdb, conversation_memory as cmem, llm, pipeline_graph as pg, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import history  # noqa: E402
from app.session_store import Turn, session_store  # noqa: E402


class FakeQdrant:
    """Holds points per collection; count / delete apply a must-filter of
    MatchValue conditions, as the real client does for these filters."""

    def __init__(self, points):
        self.points = points            # {collection: [payload, ...]}
        self.deletes = []

    @staticmethod
    def _match(payload, flt):
        return all(payload.get(c.key) == c.match.value for c in flt.must)

    async def collection_exists(self, name):
        return name in self.points

    async def count(self, name, count_filter=None, exact=True):
        return SimpleNamespace(count=sum(1 for p in self.points[name] if self._match(p, count_filter)))

    async def delete(self, collection_name, points_selector, wait=True):
        flt = points_selector.filter
        self.deletes.append((collection_name, flt))
        self.points[collection_name] = [p for p in self.points[collection_name] if not self._match(p, flt)]


def _points(sid_a="del-1"):
    mine = {"session_id": sid_a, "user_id": 5, "tenant_id": 1}
    return {settings.CONTEXT_MEMORY_COLLECTION: [dict(mine), dict(mine),
                                                 {"session_id": sid_a, "user_id": 6, "tenant_id": 1},
                                                 {"session_id": "other", "user_id": 5, "tenant_id": 1}]}


# ── delete ──────────────────────────────────────────────────────────────────

def test_delete_session_removes_only_that_owners_chat(monkeypatch):
    q = FakeQdrant(_points())
    monkeypatch.setattr(vectorstore, "get_client", lambda: q)
    n = asyncio.run(cmem.delete_session(tenant_id=1, user_id=5, session_id="del-1"))
    left = q.points[settings.CONTEXT_MEMORY_COLLECTION]
    assert n == 2
    assert {(p["session_id"], p["user_id"]) for p in left} == {("del-1", 6), ("other", 5)}
    keys = {c.key for c in q.deletes[0][1].must}
    assert keys == {"session_id", "user_id", "tenant_id"}


@pytest.mark.parametrize("kw", [{"tenant_id": 1, "user_id": None, "session_id": "del-1"},
                                {"tenant_id": 1, "user_id": 5, "session_id": ""}])
def test_delete_session_without_an_owner_or_session_deletes_nothing(monkeypatch, kw):
    q = FakeQdrant(_points())
    monkeypatch.setattr(vectorstore, "get_client", lambda: q)
    assert asyncio.run(cmem.delete_session(**kw)) is None
    assert q.deletes == []


def test_delete_session_covers_every_memory_collection(monkeypatch):
    other = "megh_conversation_memory_rollback"
    monkeypatch.setattr(settings, "CONTEXT_MEMORY_PURGE_ALSO", f"{settings.CONTEXT_MEMORY_COLLECTION},{other}")
    pts = _points()
    pts[other] = [{"session_id": "del-1", "user_id": 5, "tenant_id": 1}]
    q = FakeQdrant(pts)
    monkeypatch.setattr(vectorstore, "get_client", lambda: q)
    asyncio.run(cmem.delete_session(tenant_id=1, user_id=5, session_id="del-1"))
    assert q.points[other] == []


def _route_env(monkeypatch, *, owned=True):
    calls = []

    async def delete_conversation(*, session_id, user_id):
        calls.append(("db", session_id, user_id))
        return owned

    async def delete_session(**kw):
        calls.append(("memory", kw["session_id"], kw["user_id"]))

    monkeypatch.setattr(history.conversation_store, "delete_conversation", delete_conversation)
    monkeypatch.setattr(history.conversation_memory, "delete_session", delete_session)
    return calls


def test_the_delete_route_removes_memory_checkpoint_and_session(monkeypatch):
    from app.pipeline import ClarificationNeeded
    from app.routers.query import SCOPE_MERGE_RULES
    from _graph_turn import stub_data_path
    monkeypatch.setattr(settings, "PIPELINE_GRAPH_CHECKPOINTER_DSN", "memory")
    sid = "del-route-1"
    calls = _route_env(monkeypatch)
    s = session_store.ensure(sid, "alice")
    s.turns.append(Turn(question="q", raw_question="q", route="data", schemes=["MGNREGA"]))

    async def pause(question, scope=None, **kw):
        raise ClarificationNeeded("Which area?", rule=next(iter(SCOPE_MERGE_RULES)))
    stub_data_path(monkeypatch, pause)
    scope = SimpleNamespace(user_id="alice", db_user_id=5, tenant_id=1, username="alice")

    async def main():
        try:
            with pytest.raises(ClarificationNeeded):
                await pg.answer_question_via_graph("How many MGNREGA person-days?", session=s, scope=None)
            assert await pg.pending_pause(sid) is not None            # a paused run is stored
            out = await history.delete_my_conversation(sid, scope=scope)
            assert out == {"deleted": sid}
            assert await pg.pending_pause(sid) is None                # the checkpoint is gone
        finally:
            await pg.close()
    asyncio.run(main())
    assert ("memory", sid, 5) in calls
    assert session_store.get(sid) is None
    assert session_store.ensure(sid, "alice").turns == []             # the same id starts empty


def test_a_refused_delete_touches_nothing_else(monkeypatch):
    calls = _route_env(monkeypatch, owned=False)
    s = session_store.ensure("del-route-2", "bob")
    s.turns.append(Turn(question="q", raw_question="q", route="data"))
    scope = SimpleNamespace(user_id="mallory", db_user_id=9, tenant_id=1, username="mallory")
    with pytest.raises(history.HTTPException) as e:
        asyncio.run(history.delete_my_conversation("del-route-2", scope=scope))
    assert e.value.status_code == 404
    assert [c[0] for c in calls] == ["db"]
    assert session_store.get("del-route-2") is s


# ── retention ───────────────────────────────────────────────────────────────

def _fake_db(monkeypatch):
    sql = []

    async def execute(q, params=None):
        sql.append((q, params))
        return "DELETE 3"
    monkeypatch.setattr(appdb.db, "execute", execute)
    return sql


def test_a_zero_period_purges_nothing(monkeypatch):
    sql = _fake_db(monkeypatch)
    assert asyncio.run(appdb.purge_old_conversations(conversation_days=0, audit_days=0)) == \
        {"conversations": 0, "audit": 0}
    assert sql == []


def test_the_purge_deletes_turns_with_their_conversations_and_the_audit_on_its_own_period(monkeypatch):
    sql = _fake_db(monkeypatch)
    out = asyncio.run(appdb.purge_old_conversations(conversation_days=180, audit_days=0))
    assert out == {"conversations": 3, "audit": 0}
    (q, params), = sql
    assert "DELETE FROM app.conversation_turns" in q and "DELETE FROM app.conversations" in q
    assert params == [180]
    sql.clear()
    out = asyncio.run(appdb.purge_old_conversations(conversation_days=0, audit_days=365))
    assert out == {"conversations": 0, "audit": 3}
    assert "app.query_audit" in sql[0][0] and sql[0][1] == [365]


def test_the_daily_loop_runs_the_purge_only_when_a_period_is_set(monkeypatch):
    seen = []

    async def purge(**kw):
        seen.append(kw)
        return {}
    monkeypatch.setattr(appdb, "purge_old_conversations", purge)
    monkeypatch.setattr(settings, "CONVERSATION_RETENTION_DAYS", 0)
    monkeypatch.setattr(settings, "QUERY_AUDIT_RETENTION_DAYS", 0)
    asyncio.run(cmem._purge_old_conversations())
    assert seen == []
    monkeypatch.setattr(settings, "CONVERSATION_RETENTION_DAYS", 90)
    asyncio.run(cmem._purge_old_conversations())
    assert seen == [{"conversation_days": 90, "audit_days": 0}]


# ── the memory timestamp ────────────────────────────────────────────────────

def test_a_turn_is_stamped_when_answered_not_when_embedded(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_SEMANTIC_MEMORY_ENABLED", True)
    stored = []

    async def slow_embedding(text):
        await asyncio.sleep(0.2)                    # a slow gateway
        return [[0.1, 0.2]]

    async def ready(dim):
        return True

    class Client:
        async def upsert(self, collection_name, points, wait=False):
            stored.extend(points)
    monkeypatch.setattr(llm, "call_embedding", slow_embedding)
    monkeypatch.setattr(cmem, "_ensure_collection", ready)
    monkeypatch.setattr(vectorstore, "get_client", lambda: Client())

    async def main():
        cmem.index_turn(tenant_id=1, user_id=5, session_id="ts-1", question="MGNREGA in Ri Bhoi",
                        standalone_question="MGNREGA in Ri Bhoi", answer="a")
        await asyncio.sleep(0.05)
        memory_since = time.time()                  # "start a new topic" while the embedding runs
        await asyncio.gather(*list(cmem._bg))
        return memory_since
    memory_since = asyncio.run(main())
    assert stored and stored[0].payload["ts"] < memory_since
