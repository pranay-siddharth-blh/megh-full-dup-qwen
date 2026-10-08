"""
Live events for one streamed turn (POST /api/query/stream, D-039).

The streaming endpoint binds a sink for the duration of the turn; everything
that runs inside that turn may emit to it:
  * {"type": "step", "node": ...}   pipeline_graph._observed, as each graph node starts;
  * {"type": "draft_reset"}         llm.call_response_composer, before it streams;
  * {"type": "token", "text": ...}  llm.call_response_composer, each piece the model writes.

The sink lives in a ContextVar, so it reaches the graph's nodes (LangGraph
copies the context into the tasks it starts) and is never shared across
requests. With no sink bound (POST /api/query, tests, scripts) every emit is a
no-op and the composer makes its ordinary, non-streamed call.

Streamed tokens are a DRAFT. Every check that runs on the composer's text
(number faithfulness, the strict retry, the per-scheme guarantees) still runs
on the full text afterwards, and the final `done` event carries the checked
answer, which the UI shows in place of the draft.
"""
import contextvars
import logging
from typing import Callable

logger = logging.getLogger(__name__)

_sink: "contextvars.ContextVar[Callable[[dict], None] | None]" = contextvars.ContextVar(
    "turn_events_sink", default=None)


def bind(sink: "Callable[[dict], None] | None") -> contextvars.Token:
    return _sink.set(sink)


def unbind(token: contextvars.Token) -> None:
    _sink.reset(token)


def streaming() -> bool:
    """True when this turn has a live client to stream composer text to."""
    return _sink.get() is not None


def emit(event: dict) -> None:
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # noqa: BLE001 — a live event never costs an answer
        logger.debug("turn event dropped", exc_info=True)
