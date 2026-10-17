"""A cross-scheme answer already carries its full per-scheme tables in the
answer text. The chat UI skips its own pivot table for it (Messages.jsx,
`response.cross_scheme`); without that it drew a second table of "—" and 0
under the real one (reported 2026-10-15). A reopened thread is redrawn from
the stored payload, so the flag must be stored too — this calls the real
conversation_store._persist_turn with the database stubbed out."""
import asyncio
import json

from app import conversation_store, db


def _stored_payload(monkeypatch, result: dict) -> dict:
    calls: list = []

    async def fake_fetchval(sql, params):
        return 1

    async def fake_execute(sql, params):
        calls.append((sql, params))

    monkeypatch.setattr(db, "fetchval", fake_fetchval)
    monkeypatch.setattr(db, "execute", fake_execute)
    asyncio.run(conversation_store._persist_turn(
        "t1", 1, "s1", result, "district wise beneficiaries and amount of all schemes", 10.0, "u", "127.0.0.1"))
    turn_sql, params = next(c for c in calls if "conversation_turns" in c[0])
    return json.loads(params[-1])


def test_cross_scheme_flag_is_stored(monkeypatch):
    payload = _stored_payload(monkeypatch, {
        "route": "data", "intent": "DATA", "answer": "**Cross-scheme comparison by district**",
        "cross_scheme": True, "data": [{"district": "EAST KHASI HILLS", "scheme": "MGNREGA", "count": 5.0},
                                       {"district": "EAST KHASI HILLS", "scheme": "MGNREGA", "money": 9.0}],
        "row_count": 2, "schemes": ["MGNREGA"]})
    assert payload["cross_scheme"] is True


def test_ordinary_answer_is_not_flagged(monkeypatch):
    payload = _stored_payload(monkeypatch, {
        "route": "data", "intent": "DATA", "answer": "42 houses", "data": [{"n": 42}],
        "row_count": 1, "schemes": ["PMAY-G"]})
    assert payload["cross_scheme"] is False
