"""
QA-03 (2026-10-29): the conversation harness can now catch what it missed.

  * the in-process driver round-trips the durable snapshot on every turn
    (session_sync.sync_in before, sync_out after), and --fresh-worker starts
    each turn from a new Session, as a turn landing on another worker does —
    KI-400's topic wipe could not show up without this;
  * a turn can be asked by another account on the same chat (`as_account`),
    and its HTTP status checked (`expect.status`), for the ownership scenario;
  * a scenario can name the drivers it runs on (`drivers:`).
Offline: the pipeline and session_sync are stubbed; the live runs need the VPN.
    .venv/Scripts/python.exe -m pytest tests/test_harness_qa03_2026_10_29.py -q
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline, session_sync  # noqa: E402
from tests.conversation_harness.checks import TurnRecord, check_turn, validate_scenario  # noqa: E402
from tests.conversation_harness.drivers import InProcessDriver  # noqa: E402


def test_status_is_checked():
    rec = TurnRecord(say="x", route="error", answer="", status=403)
    assert check_turn({"route": "error", "status": 403}, rec, []) == []
    assert check_turn({"status": 200}, rec, []) == ["status 403, expected 200"]


def test_as_account_and_drivers_are_valid_keys():
    sc = {"name": "n", "account": "superadmin", "drivers": ["http"],
          "turns": [{"say": "q", "as_account": "state-rd", "expect": {"status": 403}}]}
    assert validate_scenario(sc) == []


def _stub(monkeypatch):
    calls = []

    async def sync_in(session, sid, backend=None, **kw):
        calls.append(("in", id(session)))
        return "none"

    async def sync_out(session, sid, **kw):
        calls.append(("out", id(session)))
        return True

    async def answer(q, session=None, scope=None):
        return {"route": "data", "answer": "a", "schemes": ["MGNREGA"]}
    monkeypatch.setattr(session_sync, "sync_in", sync_in)
    monkeypatch.setattr(session_sync, "sync_out", sync_out)
    monkeypatch.setattr(pipeline, "answer_question", answer)
    return calls


def test_every_inprocess_turn_round_trips_the_durable_snapshot(monkeypatch):
    calls = _stub(monkeypatch)
    conv = InProcessDriver().new_conversation()
    asyncio.run(conv.ask("How many MGNREGA job cards?"))
    asyncio.run(conv.ask("and in 2023-24?"))
    assert [c[0] for c in calls] == ["in", "out", "in", "out"]
    assert len({c[1] for c in calls}) == 1                       # one worker: the same Session


def test_fresh_worker_starts_each_turn_from_a_new_session(monkeypatch):
    calls = _stub(monkeypatch)
    conv = InProcessDriver(fresh_worker=True).new_conversation()
    asyncio.run(conv.ask("How many MGNREGA job cards?"))
    asyncio.run(conv.ask("and in 2023-24?"))
    ins = [c[1] for c in calls if c[0] == "in"]
    assert ins[0] != ins[1]                                      # another worker's copy each turn
