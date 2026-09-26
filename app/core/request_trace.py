"""
app/core/request_trace.py — one request's diagnostic trace for the audit record.

The /api/query router starts a trace per request; pipeline code adds to it
(stage latencies, rules fired, verifier results, repairs, fallbacks, the
QueryFrame before/after normalise, the clarification asked). The router then
writes it, as one JSON object, to app.query_audit.trace and to the JSONL
mirror (logs/query_audit.jsonl). Failures are read back from it by the admin
"today's failures" view and tests/eval/export_failures.py (see
app/conversation/failures.py).

A ContextVar holding a MUTABLE dict: tasks spawned inside the request
(asyncio.wait_for, LangGraph nodes) copy the context and so share the same
dict. Every helper is a no-op when no trace is active (unit tests, scripts,
startup work), and none of them can raise into the answer path.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar, Token

_trace: "ContextVar[dict | None]" = ContextVar("request_trace", default=None)
# Optional per-request callback told the NAME of each stage as it starts — how a
# streaming client gets "Running query…" progress (app/response/answer_stream.py
# binds it). Independent of the trace itself; unset => stage() only times.
_stage_listener: "ContextVar[Callable[[str], None] | None]" = ContextVar(
    "request_trace_stage_listener", default=None)


def start(raw_question: str) -> Token:
    return _trace.set({"raw_question": raw_question, "stages_ms": {}, "_t0": time.monotonic()})


def reset(token: Token) -> None:
    _trace.reset(token)


def current() -> "dict | None":
    return _trace.get()


def note(key: str, value) -> None:
    t = _trace.get()
    if t is not None:
        t[key] = value


def append(key: str, value) -> None:
    t = _trace.get()
    if t is not None:
        t.setdefault(key, []).append(value)


def incr(key: str, by: int = 1) -> None:
    t = _trace.get()
    if t is not None:
        t[key] = int(t.get(key) or 0) + by


def set_stage_listener(fn: "Callable[[str], None] | None") -> Token:
    return _stage_listener.set(fn)


def reset_stage_listener(token: Token) -> None:
    _stage_listener.reset(token)


@contextmanager
def stage(name: str):
    """Time a pipeline stage; repeated stages (e.g. several SQL attempts) add up."""
    t = _trace.get()
    listener = _stage_listener.get()
    if listener is not None:
        try:
            listener(name)
        except Exception:  # noqa: BLE001 — progress reporting never costs the answer
            pass
    started = time.monotonic()
    try:
        yield
    finally:
        if t is not None:
            ms = (time.monotonic() - started) * 1000
            t["stages_ms"][name] = round(t["stages_ms"].get(name, 0) + ms, 1)


def snapshot() -> "dict | None":
    """The trace as it goes into the audit record (JSON-safe, total time added)."""
    t = _trace.get()
    if t is None:
        return None
    out = {k: v for k, v in t.items() if not k.startswith("_")}
    out["stages_ms"] = dict(t.get("stages_ms") or {})
    out["stages_ms"]["total"] = round((time.monotonic() - t["_t0"]) * 1000, 1)
    return out
