"""
POST /api/query/stream (app/api/routers/query.py) — the same turn as
/api/query, delivered as Server-Sent Events.

Starlette's TestClient against the real app (same pattern as
tests/unit/test_query_langgraph_wiring.py), auth dependency overridden. The
stub sits at pipeline._run_pipeline, so the REAL answer_question runs — its
answer_stream binding, the stage listener, the central "replace" and the
post-answer context layer — and, where a section composes, the REAL
compose_response with only the two model calls mocked. No DB, no gateway.
The durable writes (conversation_store / conversation_memory / auth.audit)
are captured instead of performed, so /api/query and /api/query/stream can be
compared call for call. Disconnect handling drives the handler's own body
iterator with a synthetic Request.

`python tests/unit/test_query_stream.py`, exit code 0 = all pass.
"""
import asyncio
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.update(
    ENV="prod",
    AUTH_ENABLED="true",
    JWT_SECRET="test-secret-at-least-32-characters-long",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from starlette.requests import Request  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app.api.routers import query as query_router  # noqa: E402
from app.caching.cache import metrics, response_cache  # noqa: E402
from app.clients import llm  # noqa: E402
from app.clients.llm import ModelBusyError  # noqa: E402
from app.conversation import conversation_memory, conversation_store  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402
from app.core import auth as auth_mod  # noqa: E402
from app.core import request_trace  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.database.db import UnsafeSQLError  # noqa: E402
from app.main import app  # noqa: E402
from app.orchestration import langgraph_followup, pipeline  # noqa: E402
from app.orchestration.pipeline import ClarificationNeeded  # noqa: E402
from app.response import answer_stream  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_SCOPE = UserScope(user_id="stream-u1", role="admin", granularity_cap="village",
                   schemes=["MGNREGA"], geographies="all", tenant_id=1,
                   db_user_id=1, username="stream-tester")
app.dependency_overrides[query_router._identity] = lambda: _SCOPE

# ── everything patched below is restored in the final `finally` ─────────────
_saved = {
    "run_pipeline": pipeline._run_pipeline,
    "cache_get": response_cache.get,
    "ping": query_router._SSE_PING_SECONDS,
    "stream": llm.stream_response_composer,
    "call": llm.call_response_composer,
    "persist_turn": conversation_store.persist_turn,
    "save_state": conversation_store.save_context_state,
    "load_state": conversation_store.load_context_state,
    "index_turn": conversation_memory.index_turn,
    "audit": auth_mod.audit,
    "run_with_pause": langgraph_followup.run_with_pause,
    "is_paused": langgraph_followup.is_paused,
    "settings": {k: getattr(settings, k) for k in (
        "LANGGRAPH_FOLLOWUP_ENABLED", "PIPELINE_GRAPH_ENABLED", "PIPELINE_GRAPH_CANARY_PERCENT",
        "RESPONSE_CACHE_ENABLED", "SEMANTIC_CACHE_ENABLED")},
}

# This file tests the answer_question branch of _answer_turn (the one that
# streams); the two checkpointer-resume branches are pinned off the same way
# tests/unit/test_query_langgraph_wiring.py pins them — section 12 covers the
# LANGGRAPH_FOLLOWUP_ENABLED branch on its own. Caches are off unless a section
# turns them on, so every request really runs the (stubbed) pipeline.
settings.LANGGRAPH_FOLLOWUP_ENABLED = False
settings.PIPELINE_GRAPH_ENABLED = False
settings.PIPELINE_GRAPH_CANARY_PERCENT = 0
settings.RESPONSE_CACHE_ENABLED = False
settings.SEMANTIC_CACHE_ENABLED = False

# Durable writes are captured, not performed.
CAPTURED: list[tuple[str, dict]] = []


async def _no_state(session_id):
    return {}
conversation_store.persist_turn = lambda **kw: CAPTURED.append(("persist_turn", copy.deepcopy(kw)))
conversation_store.save_context_state = lambda **kw: CAPTURED.append(("save_context_state", copy.deepcopy(kw)))
conversation_store.load_context_state = _no_state
conversation_memory.index_turn = lambda **kw: CAPTURED.append(("index_turn", copy.deepcopy(kw)))
auth_mod.audit = lambda record: CAPTURED.append(("audit", copy.deepcopy(record)))


def parse_sse(text: str) -> "tuple[list[tuple[str, object]], list[str]]":
    """(events, comments) from a raw SSE body."""
    events, comments = [], []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        if block.startswith(":"):
            comments.append(block)
            continue
        name = data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        events.append((name, data))
    return events, comments


def stream(body: dict):
    with client.stream("POST", "/api/query/stream", json=body) as r:
        return r, "".join(r.iter_text())


def names(events):
    return [n for n, _ in events]


def mock_models(stream_chunks=(), call_answers=()):
    answers = list(call_answers)

    async def fake_stream(prompt):
        for c in stream_chunks:
            yield c

    async def fake_call(prompt):
        return answers.pop(0) if answers else "".join(stream_chunks)
    llm.stream_response_composer = fake_stream
    llm.call_response_composer = fake_call


ROWS = [{"houses_completed": 170981}]


async def data_turn(question, session=None, scope=None):
    """A DATA turn through the real stage markers and the real composer."""
    with request_trace.stage("understand"):
        pass
    with request_trace.stage("intent"):
        pass
    with request_trace.stage("entities"):
        pass
    with request_trace.stage("sql_generation"):
        pass
    with request_trace.stage("execute"):
        pass
    with request_trace.stage("compose"):
        answer = await pipeline.compose_response(question, "SELECT 1", ROWS)
    return {"route": "data", "intent": "DATA", "confidence": "high", "schemes": ["PMAY-G"],
            "resolved_entities": {"district": "WEST GARO HILLS"}, "sql": "SELECT 1",
            "sql_query": "SELECT 1", "row_count": 1, "rows": ROWS, "data": ROWS, "answer": answer}


def without(d: dict, *keys) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


try:
    # ── 1. stage… -> token… -> done ─────────────────────────────────────────
    print("1. EVENT ORDER: stage... -> token... -> done")
    pipeline._run_pipeline = data_turn
    mock_models(stream_chunks=["**1,70,981** ", "PMAY-G houses ", "were completed."])
    r, text = stream({"question": "houses completed in west garo hills", "session_id": "st-1"})
    events, _ = parse_sse(text)
    check("200 + text/event-stream + X-Accel-Buffering: no",
          r.status_code == 200 and r.headers.get("content-type", "").startswith("text/event-stream")
          and r.headers.get("x-accel-buffering") == "no", f"{r.status_code} {dict(r.headers)}")
    check("rate-limit + security-headers middleware applied",
          "x-ratelimit-limit" in r.headers and "x-request-id" in r.headers)
    n = names(events)
    first_token = n.index("token") if "token" in n else -1
    check("stages first, then tokens, then exactly one done at the end",
          first_token > 0 and all(x == "stage" for x in n[:first_token])
          and n[-1] == "done" and n.count("done") == 1
          and all(x in ("token", "replace") for x in n[first_token:-1]), str(n))
    labels = [d["label"] for k, d in events if k == "stage"]
    check("stage labels in pipeline order, 'Understanding' once (understand+intent deduped)",
          labels == ["Understanding your question…", "Finding the districts, blocks and years…",
                     "Generating SQL…", "Running the query…", "Writing the answer…"], str(labels))
    check("no stage event after the first token", "stage" not in n[first_token:], str(n))

    # the client's view after replaying token/replace equals the done answer
    shown = ""
    for k, d in events:
        if k == "token":
            shown += d["t"]
        elif k == "replace":
            shown = d["answer"]
    done1 = events[-1][1]
    check("replayed tokens/replace == done.answer", shown == done1.get("answer"),
          f"{shown!r} vs {done1.get('answer')!r}")

    # ── 2. replace when the final answer differs from the streamed text ─────
    print("2. 'replace' WHEN THE FINAL ANSWER DIFFERS FROM THE STREAM")
    mock_models(stream_chunks=["**17,098** ", "houses."],                       # misquoted
                call_answers=["**1,70,981** PMAY-G houses were completed."])    # strict retry
    r, text = stream({"question": "houses completed misquote", "session_id": "st-2"})
    events, _ = parse_sse(text)
    n = names(events)
    rep = [d["answer"] for k, d in events if k == "replace"]
    check("a replace event follows the tokens", "replace" in n and n.index("replace") > n.index("token"), str(n))
    check("replace carries the corrected figure, done agrees",
          rep and "17,098" not in rep[-1] and "170981" in rep[-1].replace(",", "")
          and rep[-1] == events[-1][1]["answer"], str(rep))

    mock_models(stream_chunks=["**1,70,981** PMAY-G houses were completed."])
    r, text = stream({"question": "houses completed identical", "session_id": "st-2b"})
    events, _ = parse_sse(text)
    check("no replace when the streamed text already IS the final answer",
          "replace" not in names(events) and events[-1][1]["answer"] == "**1,70,981** PMAY-G houses were completed.",
          str(events))

    # ── 3. done == /api/query for the same stub ─────────────────────────────
    print("3. 'done' MATCHES /api/query FOR THE SAME STUB")
    mock_models(stream_chunks=["**1,70,981** ", "PMAY-G houses ", "were completed."])
    CAPTURED.clear()
    r, text = stream({"question": "parity question", "session_id": "par-stream"})
    events, _ = parse_sse(text)
    done_s = events[-1][1]
    cap_stream = list(CAPTURED)
    CAPTURED.clear()
    rq = client.post("/api/query", json={"question": "parity question", "session_id": "par-query"})
    done_q = rq.json()
    cap_query = list(CAPTURED)
    check("/api/query 200", rq.status_code == 200, rq.text[:300])
    check("identical result dicts (except session_id / execution_time_ms)",
          without(done_s, "session_id", "execution_time_ms") == without(done_q, "session_id", "execution_time_ms"),
          f"\n    stream: {without(done_s, 'session_id', 'execution_time_ms')}"
          f"\n    query:  {without(done_q, 'session_id', 'execution_time_ms')}")

    # ── 4. same audit row, conversation turn and session memory ─────────────
    print("4. SAME DURABLE WRITES AS /api/query")
    check("same write calls, same order", [c for c, _ in cap_stream] == [c for c, _ in cap_query],
          f"{[c for c, _ in cap_stream]} vs {[c for c, _ in cap_query]}")
    VOLATILE = ("session_id", "latency_ms", "trace", "ts", "execution_time_ms")

    def norm(kind, kw):
        kw = without(kw, *VOLATILE)
        if isinstance(kw.get("result"), dict):
            kw["result"] = without(kw["result"], *VOLATILE)
        return kind, kw
    for (ks, a), (kq, b) in zip(cap_stream, cap_query):
        check(f"{ks}: same payload", norm(ks, a) == norm(kq, b), f"\n    stream: {norm(ks, a)}\n    query:  {norm(kq, b)}")
    ts = next((kw.get("trace") for k, kw in cap_stream if k == "persist_turn"), None) or {}
    tq = next((kw.get("trace") for k, kw in cap_query if k == "persist_turn"), None) or {}
    check("audit trace records the same stages", set(ts.get("stages_ms", {})) == set(tq.get("stages_ms", {})),
          f"{ts.get('stages_ms')} vs {tq.get('stages_ms')}")
    ss, sq = session_store.get("par-stream"), session_store.get("par-query")
    check("same L1 conversation turn", ss and sq and len(ss.turns) == len(sq.turns) == 1
          and ss.turns[0].question == sq.turns[0].question and ss.turns[0].answer == sq.turns[0].answer
          and ss.turns[0].route == sq.turns[0].route)
    check("same structured context state (context layer ran for the streamed turn)",
          ss.state.to_dict() == sq.state.to_dict(), f"{ss.state.to_dict()} vs {sq.state.to_dict()}")

    # ── 5. a follow-up after a streamed answer ──────────────────────────────
    print("5. FOLLOW-UP AFTER A STREAMED ANSWER")
    seen_prev = {}

    async def followup_turn(question, session=None, scope=None):
        prev = session.last_turn if session is not None else None
        seen_prev["q"] = prev.question if prev else None
        seen_prev["entities"] = prev.resolved_entities if prev else None
        return await data_turn(question, session, scope)
    pipeline._run_pipeline = followup_turn
    mock_models(stream_chunks=["**1,70,981** PMAY-G houses were completed."])
    r, text = stream({"question": "what about east garo hills", "session_id": "par-stream"})
    events, _ = parse_sse(text)
    check("follow-up answered", names(events)[-1] == "done", str(names(events)))
    check("pipeline saw the streamed turn as the antecedent",
          seen_prev.get("q") == "parity question" and seen_prev.get("entities") == {"district": "WEST GARO HILLS"},
          str(seen_prev))
    check("session now holds both turns", len(session_store.get("par-stream").turns) == 2)
    pipeline._run_pipeline = data_turn

    # ── 6. cache hit -> only done ───────────────────────────────────────────
    print("6. CACHE HIT -> ONLY 'done'")
    ran = {"n": 0}

    async def must_not_run(question, session=None, scope=None):
        ran["n"] += 1
        return await data_turn(question, session, scope)

    async def cached_get(question, scope_key=""):
        return {**done_q, "answer": "cached answer"}
    settings.RESPONSE_CACHE_ENABLED = True
    response_cache.get = cached_get
    pipeline._run_pipeline = must_not_run
    try:
        r, text = stream({"question": "PMAY-G houses completed by district", "session_id": "st-6"})  # standalone (follow-ups are never cached)
    finally:
        response_cache.get = _saved["cache_get"]
        settings.RESPONSE_CACHE_ENABLED = False
        pipeline._run_pipeline = data_turn
    events, comments = parse_sse(text)
    check("exactly one event: done, with the cached answer",
          names(events) == ["done"] and events[0][1]["answer"] == "cached answer", str(events))
    check("pipeline not run", ran["n"] == 0)
    check("cache hit still recorded as a turn", len(session_store.get("st-6").turns) == 1)

    # ── 7. ClarificationNeeded -> done with intent CLARIFY + options ────────
    print("7. ClarificationNeeded -> 'done' WITH intent CLARIFY AND OPTIONS")
    OPTS = [{"label": "West Garo Hills", "question": "expenditure for West Garo Hills"},
            {"label": "All of Meghalaya", "question": "expenditure for all of Meghalaya"}]

    PAUSE = {"frame": {"rewritten_question": "total MGNREGA expenditure"}, "slot": "area",
             "rule": "scope-not-specified", "asked": "Which area?", "options": OPTS,
             "base_question": "total MGNREGA expenditure", "level": None, "kind": "pause"}

    async def clarify(question, session=None, scope=None):
        with request_trace.stage("understand"):
            pass
        e = ClarificationNeeded("Which area?", options=OPTS, rule="scope-not-specified")
        e.pending_frame = PAUSE          # what frame_merge.on_pause records
        raise e
    pipeline._run_pipeline = clarify
    r, text = stream({"question": "total MGNREGA expenditure", "session_id": "st-7"})
    events, _ = parse_sse(text)
    check("stage then a single done (no error)", names(events) == ["stage", "done"], str(names(events)))
    d = events[-1][1]
    check("done: intent CLARIFY, needs_clarification, options passed through",
          d.get("intent") == "CLARIFY" and d.get("needs_clarification") is True
          and d["clarification"]["options"] == OPTS and d["clarification"]["rule"] == "scope-not-specified", str(d))
    check("pause remembered for the next turn (the frame + its slot)",
          session_store.get("st-7").state.pending_frame == PAUSE)
    rq = client.post("/api/query", json={"question": "total MGNREGA expenditure", "session_id": "st-7q"})
    check("same clarification dict as /api/query", without(d, "session_id") == without(rq.json(), "session_id"),
          f"{d} vs {rq.json()}")
    pipeline._run_pipeline = data_turn

    # ── 8. errors -> 'error' with /api/query's status + detail + metrics ────
    print("8. ERRORS -> 'error' WITH THE SAME STATUS/DETAIL AS /api/query")
    for exc, status, counter in [(ModelBusyError("busy"), 503, "busy_rejections"),
                                 (asyncio.TimeoutError(), 504, "errors"),
                                 (UnsafeSQLError("drop"), 500, "errors"),
                                 (RuntimeError("gateway 500"), 502, "model_errors")]:
        async def boom(question, session=None, scope=None, _e=exc):
            raise _e
        pipeline._run_pipeline = boom
        before = getattr(metrics, counter)
        r, text = stream({"question": "anything", "session_id": f"st-err-{status}"})
        events, _ = parse_sse(text)
        rq = client.post("/api/query", json={"question": "anything", "session_id": f"q-err-{status}"})
        check(f"{type(exc).__name__}: error {{status: {status}}} with /api/query's detail",
              events == [("error", {"status": status, "detail": rq.json().get("detail")})] and rq.status_code == status,
              f"{events} / {rq.status_code} {rq.text[:200]}")
        check(f"{type(exc).__name__}: metrics.{counter} counted by both endpoints",
              getattr(metrics, counter) == before + 2, f"{before} -> {getattr(metrics, counter)}")
    pipeline._run_pipeline = data_turn

    # ── 9. errors before the stream opens stay real HTTP errors ─────────────
    print("9. SESSION OWNERSHIP -> 403 BEFORE ANY EVENT")
    session_store.ensure("st-owned", "someone-else")
    r, text = stream({"question": "hi", "session_id": "st-owned"})
    check("403, not an SSE body", r.status_code == 403 and "event:" not in text, f"{r.status_code} {text[:200]}")

    # ── 10. keep-alive ping while idle ──────────────────────────────────────
    print("10. ': ping' WHILE THE PIPELINE IS QUIET")
    query_router._SSE_PING_SECONDS = 0.1

    async def slow(question, session=None, scope=None):
        await asyncio.sleep(0.35)
        return await data_turn(question, session, scope)
    pipeline._run_pipeline = slow
    mock_models(stream_chunks=["**1,70,981** PMAY-G houses were completed."])
    r, text = stream({"question": "slow one", "session_id": "st-10"})
    events, comments = parse_sse(text)
    check("at least one ping comment", any(c.strip() == ": ping" for c in comments), text[:300])
    check("still ends with done", events and events[-1][0] == "done", str(names(events)))
    pipeline._run_pipeline = data_turn

    # ── 11. client disconnect cancels the pipeline task ─────────────────────
    print("11. DISCONNECT CANCELS THE TURN")
    seen = {"cancelled": 0}

    async def long_turn(question, session=None, scope=None):
        try:
            await answer_stream.emit(answer_stream.current(), "token", {"t": "partial"})
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            seen["cancelled"] += 1
            raise
    pipeline._run_pipeline = long_turn

    def make_request(disconnected: bool) -> Request:
        async def receive():
            if disconnected:
                return {"type": "http.disconnect"}
            await asyncio.sleep(3600)
        return Request({"type": "http", "method": "POST", "path": "/api/query/stream",
                        "headers": [], "query_string": b"", "client": ("127.0.0.1", 1)}, receive)

    async def idle_disconnect():
        req = query_router.QueryRequest(question="long", session_id="st-11a")
        resp = await query_router.query_stream(req, make_request(True), _SCOPE)
        chunks = [c async for c in resp.body_iterator]
        await asyncio.sleep(0.05)
        return chunks
    chunks = asyncio.run(idle_disconnect())
    check("idle disconnect noticed at the ping -> turn cancelled", seen["cancelled"] == 1, str(seen))
    check("nothing sent after the disconnect",
          not any("event: done" in c or "event: error" in c for c in chunks), str(chunks))

    async def close_midstream():
        req = query_router.QueryRequest(question="long", session_id="st-11b")
        resp = await query_router.query_stream(req, make_request(False), _SCOPE)
        it = resp.body_iterator
        first = await it.__anext__()
        await it.aclose()          # what the server does when the client goes away
        await asyncio.sleep(0.05)
        return first
    first = asyncio.run(close_midstream())
    check("a token arrived before the close", "event: token" in first, first)
    check("closing the stream cancelled the turn", seen["cancelled"] == 2, str(seen))
    check("no turn recorded for a cancelled stream",
          session_store.get("st-11b") is None or not session_store.get("st-11b").turns)
    pipeline._run_pipeline = data_turn

    # ── 12. LANGGRAPH_FOLLOWUP_ENABLED: same turn, no live tokens ───────────
    print("12. LANGGRAPH_FOLLOWUP_ENABLED BRANCH -> ONE 'done', NO TOKENS")
    settings.LANGGRAPH_FOLLOWUP_ENABLED = True
    lf_calls = {"n": 0}

    async def not_paused(session_id):
        return False

    async def fake_run_with_pause(*, session_id, question, scope, resume=None):
        lf_calls["n"] += 1
        if "area" in question:
            return {"paused": True, "clarification": {"question": "Which area?", "options": None,
                                                        "rule": "scope-not-specified"}}
        return {**done_q, "answer": "via run_with_pause"}
    langgraph_followup.is_paused = not_paused
    langgraph_followup.run_with_pause = fake_run_with_pause
    pipeline._run_pipeline = must_not_run
    ran["n"] = 0
    r, text = stream({"question": "how many houses lf", "session_id": "st-12a"})
    events, _ = parse_sse(text)
    check("answer: single done, routed via run_with_pause",
          names(events) == ["done"] and events[0][1]["answer"] == "via run_with_pause"
          and lf_calls["n"] == 1 and ran["n"] == 0, str(events))
    r, text = stream({"question": "which area lf", "session_id": "st-12b"})
    events, _ = parse_sse(text)
    check("pause: single done with the clarification shape",
          names(events) == ["done"] and events[0][1].get("needs_clarification") is True, str(events))
finally:
    for k, v in _saved["settings"].items():
        setattr(settings, k, v)
    pipeline._run_pipeline = _saved["run_pipeline"]
    response_cache.get = _saved["cache_get"]
    query_router._SSE_PING_SECONDS = _saved["ping"]
    llm.stream_response_composer = _saved["stream"]
    llm.call_response_composer = _saved["call"]
    conversation_store.persist_turn = _saved["persist_turn"]
    conversation_store.save_context_state = _saved["save_state"]
    conversation_store.load_context_state = _saved["load_state"]
    conversation_memory.index_turn = _saved["index_turn"]
    auth_mod.audit = _saved["audit"]
    langgraph_followup.run_with_pause = _saved["run_with_pause"]
    langgraph_followup.is_paused = _saved["is_paused"]
    app.dependency_overrides.pop(query_router._identity, None)

if _fails:
    print(f"\n{len(_fails)} FAILED")
    sys.exit(1)
print("\nALL PASS")
