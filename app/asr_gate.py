"""The speech-to-text concurrency gate (D-111, 15 Nov 2026).

Before dictation, /api/query/transcribe held one of the LLM's slots
(llm._slot, MODEL_MAX_CONCURRENCY): with 24 chat answers in flight the mic
waited behind them, and a burst of voice uploads queued chat answers. Speech
now has gates of its own, one per caller kind, so neither can starve the other:

    "upload"   /api/query/transcribe       ASR_MAX_CONCURRENCY
    "dictate"  /ws/dictate (segments)      DICTATE_ASR_CONCURRENCY

`slot(kind, timeout)` holds one for the duration of a gateway call; past the
timeout the caller gets llm.ModelBusyError, exactly as the LLM gate does.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from app.config import settings

_gates: dict = {}           # (kind, event loop id) -> asyncio.Semaphore


def _size(kind: str) -> int:
    n = settings.DICTATE_ASR_CONCURRENCY if kind == "dictate" else settings.ASR_MAX_CONCURRENCY
    return max(1, int(n or 1))


def _gate(kind: str) -> asyncio.Semaphore:
    # one per event loop: the test client runs the app on its own loop
    key = (kind, id(asyncio.get_running_loop()))
    g = _gates.get(key)
    if g is None:
        g = _gates[key] = asyncio.Semaphore(_size(kind))
    return g


def in_use(kind: str) -> int:
    """Slots held right now (for /health and tests)."""
    try:
        g = _gate(kind)
    except RuntimeError:
        return 0
    return _size(kind) - g._value  # noqa: SLF001 — a read-only gauge


@asynccontextmanager
async def slot(kind: str = "upload", timeout: float = 20.0):
    from app.llm import ModelBusyError
    g = _gate(kind)
    try:
        await asyncio.wait_for(g.acquire(), timeout=timeout)
    except asyncio.TimeoutError as e:
        raise ModelBusyError("speech-to-text saturated — try again shortly") from e
    try:
        yield
    finally:
        g.release()
