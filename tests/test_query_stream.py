"""
Streamed answers, live progress steps, Stop and Regenerate (D-039).

  * llm.stream_model reads the gateway's SSE deltas, sends each as a "token"
    event and returns the full text; call_response_composer streams only when
    a live client is bound, and falls back to the plain call if the stream fails;
  * every graph node announces itself ("step") as it starts;
  * POST /api/query/stream frames step / token / done / error events, and a
    client that goes away (Stop) cancels the turn;
  * skip_cache (Regenerate) answers afresh instead of from the caches.

Nothing here needs the VPN.
    .venv/Scripts/python.exe -m pytest tests/test_query_stream.py -q
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import llm, turn_events  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query as router  # noqa: E402
from _graph_turn import graph_turn  # noqa: E402


def _sse(*chunks: dict) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return "".join(lines).encode()


def _delta(text):
    return {"choices": [{"delta": {"content": text}}]}


@pytest.fixture
def gateway(monkeypatch):
    """llm's shared client and slot gate, served by `gateway.handler`."""
    g = SimpleNamespace(requests=[], handler=None)

    def handle(request: httpx.Request) -> httpx.Response:
        g.requests.append(json.loads(request.content))
        return g.handler(request)

    monkeypatch.setattr(llm, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(llm, "_gate", asyncio.Semaphore(4))
    return g


def _collect():
    events: list[dict] = []
    return events, turn_events.bind(events.append)


# ── the model client ────────────────────────────────────────────────────────

def test_stream_model_emits_each_piece_and_returns_the_full_text(gateway):
    gateway.handler = lambda r: httpx.Response(200, content=_sse(
        _delta("East Khasi Hills had "), _delta("**42**"), _delta(" applications."),
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 7}}))
    events, tok = _collect()
    try:
        text = asyncio.run(llm.call_response_composer("prompt"))
    finally:
        turn_events.unbind(tok)
    assert text == "East Khasi Hills had **42** applications."
    assert events[0] == {"type": "draft_reset"}
    assert [e["text"] for e in events if e["type"] == "token"] == [
        "East Khasi Hills had ", "**42**", " applications."]
    assert gateway.requests[0]["stream"] is True


def test_composer_makes_the_plain_call_without_a_live_client(gateway):
    gateway.handler = lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "plain answer"}}], "usage": {}})
    assert asyncio.run(llm.call_response_composer("prompt")) == "plain answer"
    assert "stream" not in gateway.requests[0]


def test_composer_stream_off_switch(gateway, monkeypatch):
    monkeypatch.setattr(settings, "STREAM_COMPOSER_ENABLED", False)
    gateway.handler = lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "plain"}}]})
    events, tok = _collect()
    try:
        assert asyncio.run(llm.call_response_composer("prompt")) == "plain"
    finally:
        turn_events.unbind(tok)
    assert "stream" not in gateway.requests[0] and not events


def test_a_failed_stream_falls_back_to_the_plain_call_and_clears_the_draft(gateway):
    def handler(r):
        if json.loads(r.content).get("stream"):
            return httpx.Response(400, json={"error": "stream not supported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "plain answer"}}]})
    gateway.handler = handler
    events, tok = _collect()
    try:
        assert asyncio.run(llm.call_response_composer("prompt")) == "plain answer"
    finally:
        turn_events.unbind(tok)
    assert events[-1] == {"type": "draft_reset"}
    assert len(gateway.requests) == 2


def test_busy_gateway_is_not_hidden_by_the_fallback(gateway, monkeypatch):
    monkeypatch.setattr(llm, "_gate", asyncio.Semaphore(0))
    monkeypatch.setattr(settings, "MODEL_QUEUE_TIMEOUT_SECONDS", 0.01)
    gateway.handler = lambda r: httpx.Response(200, content=_sse(_delta("x")))
    _, tok = _collect()
    try:
        with pytest.raises(llm.ModelBusyError):
            asyncio.run(llm.call_response_composer("prompt"))
    finally:
        turn_events.unbind(tok)


def test_emit_without_a_sink_is_a_no_op():
    assert not turn_events.streaming()
    turn_events.emit({"type": "step", "node": "context"})   # must not raise


# ── progress steps from the graph ───────────────────────────────────────────

def test_every_graph_node_announces_itself_in_order():
    events, tok = _collect()
    try:
        result = asyncio.run(graph_turn("hello"))
    finally:
        turn_events.unbind(tok)
    steps = [e["node"] for e in events if e["type"] == "step"]
    assert result.get("answer")
    assert steps[:2] == ["context", "edge"]
    assert steps[-2:] == ["finalize", "context_update"]


# ── the endpoint ────────────────────────────────────────────────────────────

def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query/stream", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


def _frames(chunks):
    out = []
    for c in chunks:
        for frame in c.split("\n\n"):
            if frame.startswith("data: "):
                out.append(json.loads(frame[6:]))
    return out


async def _drain(resp, limit=None):
    chunks = []
    async for c in resp.body_iterator:
        chunks.append(c)
        if limit and len(chunks) >= limit:
            break
    return chunks


def test_stream_frames_steps_tokens_and_the_same_result(monkeypatch):
    async def fake_answer(req, request, scope):
        turn_events.emit({"type": "step", "node": "compose"})
        turn_events.emit({"type": "token", "text": "42 "})
        return {"answer": "42 applications.", "route": "data", "row_count": 1}
    monkeypatch.setattr(router, "_answer", fake_answer)

    async def go():
        resp = await router.query_stream(router.QueryRequest(question="q"), _request(), scope=None)
        assert resp.media_type == "text/event-stream"
        assert resp.headers["x-accel-buffering"] == "no"
        return _frames(await _drain(resp))
    frames = asyncio.run(go())
    assert frames == [{"type": "step", "node": "compose"}, {"type": "token", "text": "42 "},
                      {"type": "done", "result": {"answer": "42 applications.", "route": "data", "row_count": 1}}]


def test_stream_reports_the_status_plain_query_would_raise(monkeypatch):
    async def busy(req, request, scope):
        raise router.HTTPException(503, "The service is busy right now. Please retry in a few seconds.")
    monkeypatch.setattr(router, "_answer", busy)

    async def go():
        resp = await router.query_stream(router.QueryRequest(question="q"), _request(), scope=None)
        return _frames(await _drain(resp))
    assert asyncio.run(go()) == [{"type": "error", "status": 503,
                                  "detail": "The service is busy right now. Please retry in a few seconds."}]


def test_stop_cancels_the_turn(monkeypatch):
    state = {}

    async def slow(req, request, scope):
        turn_events.emit({"type": "step", "node": "sql_generate"})
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        return {"answer": "never"}
    monkeypatch.setattr(router, "_answer", slow)

    async def go():
        resp = await router.query_stream(router.QueryRequest(question="q"), _request(), scope=None)
        it = resp.body_iterator
        first = await it.__anext__()
        await it.aclose()              # what Starlette does when the client goes away
        await asyncio.sleep(0)
        return first
    first = asyncio.run(go())
    assert json.loads(first[6:]) == {"type": "step", "node": "sql_generate"}
    assert state.get("cancelled") is True


def test_the_turn_body_is_shared_by_both_endpoints():
    import inspect
    assert "return await _answer(req, request, scope)" in inspect.getsource(router.query)
    assert "await _answer(req, request, scope)" in inspect.getsource(router.query_stream)


# ── Regenerate: skip_cache ──────────────────────────────────────────────────

@pytest.fixture
def plain_turn(monkeypatch):
    """_answer with every side effect stubbed: the caches report what they
    were asked, and the pipeline returns a fresh answer."""
    seen = SimpleNamespace(cache_reads=0, pipeline=0, puts=0)

    async def cache_get(q, scope_key):
        seen.cache_reads += 1
        return {"answer": "cached", "route": "data"}

    async def answer_question(q, session=None, scope=None):
        seen.pipeline += 1
        return {"answer": "fresh", "route": "data"}

    async def put(*a, **k):
        seen.puts += 1

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(router.response_cache, "get", cache_get)
    monkeypatch.setattr(router.response_cache, "put", put)
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.session_sync, "sync_in", noop)
    monkeypatch.setattr(router.session_sync, "sync_out", noop)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    seen.scope = SimpleNamespace(user_id="u", db_user_id=None, tenant_id=None, username="",
                                 cache_fingerprint=lambda: "fp")
    return seen


def test_a_normal_question_is_served_from_the_cache(plain_turn):
    out = asyncio.run(router._answer(router.QueryRequest(question="How many houses in Ri Bhoi?",
                                                         session_id="s-cache-1"),
                                     _request(), plain_turn.scope))
    assert out["answer"] == "cached" and plain_turn.pipeline == 0


def test_regenerate_skips_the_cache_and_refreshes_it(plain_turn):
    out = asyncio.run(router._answer(router.QueryRequest(question="How many houses in Ri Bhoi?",
                                                         session_id="s-cache-2", skip_cache=True),
                                     _request(), plain_turn.scope))
    assert out["answer"] == "fresh"
    assert plain_turn.cache_reads == 0 and plain_turn.pipeline == 1
    assert plain_turn.puts == 1           # the fresh answer replaces the cached one


def test_skip_cache_defaults_off():
    assert router.QueryRequest(question="q").skip_cache is False
