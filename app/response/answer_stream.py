"""
app/response/answer_stream.py — optional live answer events for a streaming client.

A caller that wants the answer as it is written passes `on_event` to
`pipeline.answer_question`, which binds it here for the whole turn. The
composer calls (pipeline.compose_response, rag.answer_from_kb /
answer_from_kb_multi) read it back with `current()` and, when it is set,
stream their FIRST model call as "token" events. Every post-check still runs
on the complete text afterwards; whenever the final answer differs from what
the client has been shown (a strict retry, a deterministic fallback, answer
formatting, an "Understood as" prefix, or an answer path with no composer at
all), a single "replace" event carries the final text.

Events: on_event(kind, data), sync or async —
  "stage"   {"label": "<progress>"} what the pipeline is doing ("Running the
                                    query…"), from request_trace.stage(); only
                                    before the answer starts, each label once
  "token"   {"t": "<text delta>"}   append to the answer being shown
  "replace" {"answer": "<text>"}    discard what was shown, show this instead

A ContextVar rather than a parameter threaded through every function: the
LangGraph path runs compose_response inside `node_compose`, and graph state
goes through the checkpointer, which cannot hold a callable. Context is
copied into LangGraph nodes and asyncio tasks, so they all see the same
binding and the same mutable "shown" record (the pattern
app/core/request_trace.py uses). With no binding (the /api/query endpoint,
tests, the eval harness) every helper here is a no-op and the composer calls
are exactly the non-streaming ones they always were.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from app.clients import llm
from app.core import request_trace

logger = logging.getLogger(__name__)

OnEvent = Callable[[str, dict], Any]

# request_trace.stage() names -> what the user sees while waiting. Stages not
# listed (e.g. "normalise" repeats "understand") map to a label already shown or
# to nothing, and consecutive duplicates are dropped.
STAGE_LABELS = {
    "understand": "Understanding your question…",
    "normalise": "Understanding your question…",
    "intent": "Understanding your question…",
    "entities": "Finding the districts, blocks and years…",
    "kb_search": "Searching the scheme documents…",
    "sql_generation": "Generating SQL…",
    "verify_model": "Checking the query…",
    "execute": "Running the query…",
    "compose": "Writing the answer…",
}

_on_event: "ContextVar[OnEvent | None]" = ContextVar("answer_stream_on_event", default=None)
# What the client is currently showing — a mutable dict so child tasks share it.
_shown: "ContextVar[dict | None]" = ContextVar("answer_stream_shown", default=None)


def _stage_listener(on_event: OnEvent, shown: dict) -> Callable[[str], None]:
    def listen(name: str) -> None:
        label = STAGE_LABELS.get(name)
        # Nothing once the answer is on screen: a stage label would sit under it.
        if not label or label == shown.get("stage") or shown["text"]:
            return
        shown["stage"] = label
        _emit_nowait(on_event, "stage", {"label": label})
    return listen


def _emit_nowait(on_event: OnEvent, kind: str, data: dict) -> None:
    """emit() for synchronous call sites (request_trace.stage is a plain
    context manager). A sync callback runs in order; an async one is scheduled."""
    try:
        r = on_event(kind, data)
        if inspect.isawaitable(r):
            asyncio.ensure_future(r)
    except Exception:  # noqa: BLE001
        logger.warning("answer_stream: on_event(%r) failed (non-fatal)", kind, exc_info=True)


@contextmanager
def bind(on_event: "OnEvent | None"):
    """Make `on_event` the turn's event sink (None binds nothing)."""
    shown = {"text": "", "stage": None} if on_event is not None else None
    t_event = _on_event.set(on_event)
    t_shown = _shown.set(shown)
    t_stage = request_trace.set_stage_listener(
        _stage_listener(on_event, shown) if on_event is not None else None)
    try:
        yield
    finally:
        request_trace.reset_stage_listener(t_stage)
        _on_event.reset(t_event)
        _shown.reset(t_shown)


def current() -> "OnEvent | None":
    return _on_event.get()


def shown_text() -> "str | None":
    s = _shown.get()
    return s["text"] if s is not None else None


async def emit(on_event: "OnEvent | None", kind: str, data: dict) -> None:
    """Send one event. Never raises into the answer path: a broken client
    callback costs the live view, not the answer."""
    if on_event is None:
        return
    s = _shown.get()
    if s is not None:
        if kind == "token":
            s["text"] += data.get("t") or ""
        elif kind == "replace":
            s["text"] = data.get("answer") or ""
    try:
        r = on_event(kind, data)
        if inspect.isawaitable(r):
            await r
    except Exception:  # noqa: BLE001
        logger.warning("answer_stream: on_event(%r) failed (non-fatal)", kind, exc_info=True)


async def compose(prompt: str, on_event: "OnEvent | None") -> str:
    """The FIRST composer call of an answer. No sink: exactly
    llm.call_response_composer(prompt). With a sink: streamed as "token"
    events and joined. A stream that fails partway falls back to the
    non-streaming call, and its result replaces whatever was shown."""
    if on_event is None:
        return await llm.call_response_composer(prompt)
    parts: list[str] = []
    try:
        async for chunk in llm.stream_response_composer(prompt):
            parts.append(chunk)
            await emit(on_event, "token", {"t": chunk})
    except llm.ModelBusyError:
        raise  # raised before any token; a non-streaming retry would just queue again
    except Exception:  # noqa: BLE001
        logger.warning("answer_stream: composer stream failed after %d chunk(s) — "
                       "non-streaming fallback", len(parts), exc_info=True)
        answer = await llm.call_response_composer(prompt)
        await emit(on_event, "replace", {"answer": answer})
        return answer
    return "".join(parts)


async def settle(on_event: "OnEvent | None", final: str) -> None:
    """Emit "replace" with `final` when it differs from what was shown."""
    if on_event is None:
        return
    if shown_text() != final:
        await emit(on_event, "replace", {"answer": final})
