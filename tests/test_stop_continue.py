"""
"stop" while a question runs, then "continue" answers it (user request
2026-10-18): the router remembers the question it cancelled
(routers.query._remember_stopped, durable via Session.stopped_ctx) and the
conversation layer runs it on the next "continue". No model, DB or VPN.
    .venv/Scripts/python.exe -m pytest tests/test_stop_continue.py -q
"""
import asyncio
import sys
import time
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import conversation_layer as cl, session_sync, turn_events  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.session_store import Session, session_store  # noqa: E402

Q = "How many MGNREGA beneficiaries are there in East Khasi Hills?"


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "CONVERSATION_LAYER_ENABLED", True)
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 1800)

    async def drop(_sid):
        return None
    monkeypatch.setattr(cl, "_drop_paused_run", drop)


def _session(sid="stop-1"):
    return Session(session_id=sid, user_id="u", created=time.time(), last_seen=time.time())


def _prep(s, q):
    return asyncio.run(cl.prepare_turn(s, q))


# ── The words ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["continue", "Continue.", "ok continue", "please continue", "go on", "resume",
                               "carry on", "continue with the previous query", "continue where you left off",
                               "yes, go ahead", "contiue"])
def test_continue_requests(q):
    assert cl.is_continue_request(q)


@pytest.mark.parametrize("q", ["continue with MGNREGA", "Continue with MGNREGA (East Khasi Hills, FY 2022-23)",
                               "continue with MGNREGA beneficiaries in East Khasi Hills", "How do I continue?",
                               "stop", ""])
def test_not_continue_requests(q):
    assert not cl.is_continue_request(q)


@pytest.mark.parametrize("q", ["stop", "Stop!", "stop it", "please stop", "cancel", "ok stop now", "ruko"])
def test_stop_requests(q):
    assert cl.is_stop_request(q)


@pytest.mark.parametrize("q", ["stop the MGNREGA payments?", "bus stop", "How many beneficiaries?", "continue"])
def test_not_stop_requests(q):
    assert not cl.is_stop_request(q)


# ── The conversation layer ──────────────────────────────────────────────────

def test_continue_runs_the_stopped_question_and_is_never_cached():
    s = _session()
    cl.remember_stopped(s, Q)
    lt = _prep(s, "continue")
    assert lt.question == Q and lt.action == "continue-stopped" and lt.changed and lt.response is None
    assert s.stopped_ctx is None
    assert _prep(s, "continue").question == "continue"          # once only


def test_any_other_message_drops_the_stopped_question():
    s = _session()
    cl.remember_stopped(s, Q)
    _prep(s, "How many PMAY-G houses were completed?")
    assert s.stopped_ctx is None
    assert _prep(s, "continue").question == "continue"


def test_an_old_stop_is_not_continued():
    s = _session()
    cl.remember_stopped(s, Q)
    s.stopped_ctx["at"] = time.time() - settings.CONTEXT_IDLE_EXPIRY_SECONDS - 5
    assert _prep(s, "continue").question == "continue"


def test_a_stopped_continue_is_not_remembered():
    s = _session()
    cl.remember_stopped(s, "continue")
    assert s.stopped_ctx is None


def test_stop_with_nothing_running_is_answered_and_keeps_the_topic():
    s = _session()
    lt = _prep(s, "stop")
    assert lt.response["edge_type"] == cl.NOTHING_RUNNING_EDGE and lt.changed


def test_the_stopped_question_survives_the_snapshot():
    s = _session()
    cl.remember_stopped(s, Q)
    other = _session()
    other.apply_snapshot(s.to_snapshot())
    assert _prep(other, "go on").question == Q


# ── The router: a cancelled stream remembers its question ───────────────────

def test_stop_on_the_stream_remembers_the_question(monkeypatch):
    saved = []

    async def fake_sync_out(session, sid, **kw):
        saved.append((sid, (session.stopped_ctx or {}).get("question")))
        return True
    monkeypatch.setattr(session_sync, "sync_out", fake_sync_out)

    async def slow(req, request, scope):
        turn_events.emit({"type": "step", "node": "sql_generate"})
        await asyncio.sleep(30)
        return {"answer": "never"}
    monkeypatch.setattr(router, "_answer", slow)
    scope = types.SimpleNamespace(user_id="u", tenant_id=1, db_user_id=7)
    req = router.QueryRequest(question=Q, session_id="stop-thread-1")

    async def go():
        from tests.test_query_stream import _request
        resp = await router.query_stream(req, _request(), scope=scope)
        it = resp.body_iterator
        await it.__anext__()
        await it.aclose()               # the client went away (Stop)
        for _ in range(3):
            await asyncio.sleep(0)
    asyncio.run(go())
    assert session_store.ensure("stop-thread-1", "u").stopped_ctx["question"] == Q
    assert saved == [("stop-thread-1", Q)]


# ── D-051 (user decision 2026-10-18): 50 turns, 20 questions per topic, 4 h idle ──
from app.config import Settings  # noqa: E402
from app.session_store import Turn  # noqa: E402


def test_the_decided_defaults():
    d = Settings.model_fields
    assert d["SESSION_MAX_TURNS"].default == 50
    assert d["CONTEXT_LEDGER_PER_TOPIC"].default == 20
    # 8 h idle window: user decision 2026-10-19 (was 4 h in D-051)
    assert d["CONTEXT_IDLE_EXPIRY_SECONDS"].default == 8 * 3600
    assert d["SESSION_TTL_SECONDS"].default == 8 * 3600


def test_a_stopped_question_lives_as_long_as_the_idle_window(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 4 * 3600)
    s = _session()
    cl.remember_stopped(s, Q)
    s.stopped_ctx["at"] = time.time() - 3 * 3600           # 3 h ago: still inside 4 h
    assert _prep(s, "continue").question == Q


def test_the_snapshot_keeps_as_many_questions_as_the_session(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_MAX_TURNS", 50)
    s = _session()
    s.turns = [Turn(question=f"q{i}", raw_question=f"q{i}", route="data") for i in range(60)]
    snap = s.to_snapshot()
    assert len(snap["_session"]["recent_questions"]) == 50
    other = _session()
    other.apply_snapshot(snap)
    assert len(other.turns) == 50 and other.turns[-1].question == "q59"
