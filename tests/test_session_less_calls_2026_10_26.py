"""A call that sends no session id gets a conversation of its own (RAG plan E3, 2026-10-26).

Every session-less API call by one user on one day shared the bucket "day-<user>-<date>",
so an unrelated question was read as a follow-up of the previous one and inherited its
scheme, place and year. Now each such call gets "api-<random>"; the id comes back in the
response, and sending it back continues that conversation. "api-" threads are kept for
audit but left out of the user's own history list and search, so scripts do not flood it."""
import asyncio
from types import SimpleNamespace

from app import conversation_store
from app.routers import query as router


def _req(session_id=None, headers=None):
    req = SimpleNamespace(session_id=session_id)
    request = SimpleNamespace(headers=headers or {}, state=SimpleNamespace())
    return req, request


def _scope(db_user_id=7):
    return SimpleNamespace(db_user_id=db_user_id)


def test_each_session_less_call_gets_its_own_conversation():
    a = router._session_id(*_req(), _scope())
    b = router._session_id(*_req(), _scope())
    assert a.startswith("api-") and b.startswith("api-") and a != b
    assert not a.startswith("day-")


def test_one_request_keeps_one_id():
    """The stream's stop handler asks again; it must get the id that answered."""
    req, request = _req()
    assert router._session_id(req, request, _scope()) == router._session_id(req, request, _scope())


def test_a_client_session_id_is_used_as_sent():
    assert router._session_id(*_req("sess-123"), _scope()) == "sess-123"
    assert router._session_id(*_req(headers={"x-session-id": "hdr-9"}), _scope()) == "hdr-9"


def test_a_call_with_no_user_stays_a_one_off():
    assert router._session_id(*_req(), _scope(db_user_id=None)).startswith("one-")


def test_api_threads_are_not_in_the_users_history_list_or_search(monkeypatch):
    seen = []

    async def fetch_rows(sql, params=None):
        seen.append(sql)
        return []

    monkeypatch.setattr(conversation_store.db, "fetch_rows", fetch_rows)
    asyncio.run(conversation_store.list_my_conversations(7))
    asyncio.run(conversation_store.search_my_conversations(user_id=7, q="houses"))
    assert all("left(" in s and "'api-'" in s for s in seen), seen


def test_voice_throwaway_sessions_are_not_in_the_history_list_or_search(monkeypatch):
    """2026-11-15: the voice stage's explaining breakdown runs in a voice_explain_* session that the page deletes 4 s
    later; when the page closed first (or the request was cancelled while the server still saved it) the thread was
    left in the officer's history. The list and search never show that prefix."""
    seen = []

    async def fetch_rows(sql, params=None):
        seen.append(sql)
        return []

    monkeypatch.setattr(conversation_store.db, "fetch_rows", fetch_rows)
    asyncio.run(conversation_store.list_my_conversations(7))
    asyncio.run(conversation_store.search_my_conversations(user_id=7, q="houses"))
    assert len(seen) == 2 and all("'voice_explain_'" in s and "left(" in s for s in seen), seen
