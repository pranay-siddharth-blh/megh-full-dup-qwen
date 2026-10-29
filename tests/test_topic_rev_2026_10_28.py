"""
CTX-02 (KI-400, 2026-10-29): topic memory was wiped by any turn that saved a
revision without passing through topic_memory.checkpoint — a cache hit, small
talk answered by the conversation layer, a typed "stop", a "Continue with …"
tap after an idle expiry. checkpoint() read the revision jump of two as "another
worker served turns" and dropped every topic, so "go back to MGNREGA", the topic
chips and digression recovery stopped working. And "go back to Mawphlang" never
reached the ledger: parse_backward wanted "the Mawphlang one".

Real router._answer, real session_sync.sync_in / sync_out over a fake
app.conversations that applies the same revision rule as
conversation_store.save_session_state, real topic_memory. The data path is
stubbed the way the graph runs it: the context stage's resolve_turn (which
checkpoints first) and the context_update node's update_state. No model, DB or
VPN. (tests/test_cache_hit_context.py stubs sync_out to a no-op, which is why
this was not caught.)
    .venv/Scripts/python.exe -m pytest tests/test_topic_rev_2026_10_28.py -q
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_manager as cm, conversation_layer as cl, entity_resolver, llm  # noqa: E402
from app import session_sync, topic_memory as tm  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import Session, session_store  # noqa: E402

EKH, WGH = "EAST KHASI HILLS", "WEST GARO HILLS"
Q_MG = "How many person-days were generated under MGNREGA in East Khasi Hills in FY 2022-23?"
Q_PM = "How many PMAY-G houses were completed in West Garo Hills in FY 2023-24?"
Q_MG2 = "How many job cards were issued under MGNREGA in East Khasi Hills in FY 2022-23?"
ANSWERS = {
    Q_MG: ("MGNREGA", {"district": EKH, "year_key": 2022}),
    Q_PM: ("PMAY-G", {"district": WGH, "year_key": 2023}),
    Q_MG2: ("MGNREGA", {"district": EKH, "year_key": 2022}),
}


class FakeBackend:
    """app.conversations for one test: JSON round trip, and the upsert's
    `WHERE stored rev < new rev` guard."""

    def __init__(self):
        self.rows: dict = {}

    async def load(self, session_id):
        row = self.rows.get(session_id)
        return {} if row is None else {"context_state": json.loads(row["state"]), "summary": row["summary"]}

    async def save(self, *, tenant_id, user_id, session_id, title, snapshot, rev, summary):
        cur = self.rows.get(session_id)
        if cur and int(json.loads(cur["state"]).get("rev") or 0) >= rev:
            return False
        self.rows[session_id] = {"state": json.dumps({**snapshot, "rev": rev}, default=str),
                                 "summary": summary if summary is not None else (cur or {}).get("summary")}
        return True


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


def _data_result(question):
    scheme, resolved = ANSWERS[question]
    return {"route": "data", "intent": "DATA", "schemes": [scheme], "sql": "SELECT 1", "sql_query": "SELECT 1",
            "resolved_entities": dict(resolved), "row_count": 1, "rows": [{"n": 1}], "data": [{"n": 1}],
            "answer": f"{scheme} answer.", "confidence": "high"}


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()


@pytest.fixture
def chat(monkeypatch):
    """The router with a fake durable store, a cache that can be primed, and a
    stubbed graph."""
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED", "CONVERSATION_LAYER_ENABLED",
                 "CONTEXT_STATE_SHARED", "BACKWARD_RESOLVER_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    backend = FakeBackend()
    monkeypatch.setattr(session_sync, "_default_backend", backend)
    cache: dict = {}

    async def cache_get(q, scope_key):
        return dict(cache[q]) if q in cache else None

    async def answer_question(q, session=None, scope=None):
        # the graph: context stage (resolve_turn checkpoints first), then
        # the data path, then the context_update node
        session.turn_context = {}
        t = tm.resolve_turn(session, q)
        if t.response is not None:
            return t.response
        result = _data_result(t.question)
        cm.update_state(session, q, t.question, result)
        return result

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(router.response_cache, "get", cache_get)
    monkeypatch.setattr(router.response_cache, "put", noop)
    monkeypatch.setattr(router.semantic_cache, "lookup", lambda *a, **k: _none_pair())
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    monkeypatch.setattr(router.context_manager, "maybe_update_summary", noop)
    monkeypatch.setattr(cl, "_drop_paused_run", noop)
    scope = SimpleNamespace(user_id="u", db_user_id=None, tenant_id=None, username="",
                            cache_fingerprint=lambda: "fp")
    return SimpleNamespace(scope=scope, cache=cache, backend=backend)


async def _none_pair():
    return None, None


def _post(chat, question, sid):
    return asyncio.run(router._answer(router.QueryRequest(question=question, session_id=sid), _request(),
                                      chat.scope))


def _two_topics(chat, sid):
    _post(chat, Q_MG, sid)
    _post(chat, Q_PM, sid)
    s = session_store.ensure(sid, "u")
    return s


def _topics_after_next_graph_turn(chat, sid):
    _post(chat, Q_MG2, sid)          # its context stage runs checkpoint()
    return set(session_store.ensure(sid, "u").topics["items"])


def test_a_cache_hit_keeps_every_topic(chat):
    sid = "ctx02-cache"
    _two_topics(chat, sid)
    chat.cache[Q_MG] = _data_result(Q_MG)
    out = _post(chat, Q_MG, sid)                       # served from the cache: no checkpoint
    assert out["answer"] == "MGNREGA answer."
    assert _topics_after_next_graph_turn(chat, sid) >= {"MGNREGA", "PMAY-G"}


def test_layer_small_talk_keeps_every_topic(chat):
    sid = "ctx02-smalltalk"
    _two_topics(chat, sid)
    out = _post(chat, "how are you?", sid)            # answered by the conversation layer
    assert out["route"] != "data"
    assert _topics_after_next_graph_turn(chat, sid) >= {"MGNREGA", "PMAY-G"}


def test_continue_after_idle_expiry_keeps_every_topic(chat, monkeypatch):
    sid = "ctx02-expiry"
    monkeypatch.setattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 60)
    s = _two_topics(chat, sid)
    tm.checkpoint(s)                                  # both topics on record, as the next turn would file them
    s.context_at -= 61
    first = _post(chat, "hello", sid)                  # the expiry sets the context aside and offers the chip
    chip = first.get("continue_offer")
    assert chip and chip.startswith("Continue with ")
    _post(chat, chip, sid)                             # the tap restores the set-aside copy
    assert _topics_after_next_graph_turn(chat, sid) >= {"MGNREGA", "PMAY-G"}


def test_go_back_to_a_topic_works_after_a_cache_hit(chat):
    sid = "ctx02-goback"
    _two_topics(chat, sid)
    chat.cache[Q_PM] = _data_result(Q_PM)
    _post(chat, Q_PM, sid)                             # cache hit on PMAY-G
    out = _post(chat, "go back to MGNREGA", sid)
    s = session_store.ensure(sid, "u")
    assert out.get("edge_type") == tm.TOPIC_SWITCH_EDGE
    assert (s.state.scheme, s.state.district, s.state.year) == ("MGNREGA", EKH, 2022)


def test_the_revision_still_moves_on_every_saved_turn(chat):
    sid = "ctx02-rev"
    _two_topics(chat, sid)
    s = session_store.ensure(sid, "u")
    before = s.rev
    _post(chat, "how are you?", sid)
    assert s.rev == before + 1                         # sync_out still writes each turn


# ── "go back to <place>" (parse_backward) ───────────────────────────────────

def _ledger_session():
    return Session(session_id="ctx02-ledger", user_id="u", created=time.time(), last_seen=time.time())


def _ask(s, question, scheme, resolved):
    s.turn_context = {}
    t = tm.resolve_turn(s, question)
    if t.response is not None:
        return t
    result = {"route": "data", "intent": "DATA", "schemes": [scheme], "sql": "SELECT 1",
              "resolved_entities": resolved, "answer": f"{scheme} answer"}
    cm.update_state(s, question, t.question, result)
    s.turns.append(build_turn(question, result))
    return t


@pytest.fixture
def ledger_on(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED", "BACKWARD_RESOLVER_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "CONTEXT_LEDGER_PER_TOPIC", 6)


def _seeded():
    s = _ledger_session()
    _ask(s, "How many MGNREGA person-days were generated in Mawphlang block in FY 2023-24?", "MGNREGA",
         {"district": EKH, "block": "MAWPHLANG", "year_key": 2023})
    _ask(s, "How many PMAY-G houses were completed in West Garo Hills in FY 2022-23?", "PMAY-G",
         {"district": WGH, "year_key": 2022})
    return s


def test_go_back_to_a_bare_place_restores_that_question(ledger_on):
    s = _seeded()
    s.turn_context = {}
    t = tm.resolve_turn(s, "go back to Mawphlang")
    assert t.action == "restore" and t.topic == "MGNREGA"
    # the scope the data path then runs in
    assert (s.state.scheme, s.state.block, s.state.year) == ("MGNREGA", "MAWPHLANG", 2023)
    assert t.question.startswith("How many MGNREGA person-days")      # the earlier question re-runs


def test_go_back_to_a_bare_place_with_a_question_runs_it_there(ledger_on):
    s = _seeded()
    s.turn_context = {}
    t = tm.resolve_turn(s, "go back to Mawphlang, what about FY 2024-25?")
    assert t.action == "restore" and t.question == "what about FY 2024-25?"
    assert (s.state.scheme, s.state.block, s.state.year) == ("MGNREGA", "MAWPHLANG", 2023)


def test_parse_backward_reads_a_place_target_only():
    assert tm.parse_backward("go back to Mawphlang") is not None
    assert tm.parse_backward("go back to East Khasi Hills please") is not None
    assert tm.parse_backward("go back to work") is None               # no place: not a reference
    assert tm.parse_backward("go back to Mawphlang and Ri Bhoi") is None   # two places: not one question
    assert tm.parse_switch("go back to MGNREGA") is not None          # a scheme is still a topic switch
    assert tm.parse_backward("go back to the Mawphlang one") is not None


def test_a_place_never_asked_about_runs_as_before_without_a_model_call(ledger_on, monkeypatch):
    s = _seeded()

    async def no_model(*a, **k):
        raise AssertionError("no model call for a bare place with no ledger match")
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    t = tm.resolve_turn(s, "go back to Ri Bhoi")
    assert t.action != "restore"
    assert asyncio.run(tm.resolve_reference(s, "go back to Ri Bhoi")) is None
