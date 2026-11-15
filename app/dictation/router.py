"""/ws/dictate — the composer mic's socket (D-111, 15 Nov 2026).

Protocol (JSON text messages; audio as binary messages):
  page   -> {"type": "hello", "token": <the chat's JWT>, "lang": "en"}      within 5 s of opening
  server -> {"type": "ready", "max_s": 120, "partials": "asr"}
  page   -> binary: PCM16 little-endian, 16 kHz mono (the page's worklet sends 80 ms = 2,560 bytes);
            a frame over 8 KB is dropped
  page   -> {"type": "stop"}  (insert what was said)  |  {"type": "cancel"}  (forget it)
  server -> {"type": "partial", "seq": n, "stable": "...", "tentative": "..."}   (both are the WHOLE text so far)
  server -> {"type": "final", "text": "...", "corrections": [{"heard", "wrote", "kind"}], "seconds": s}
            | {"type": "no_speech"} | {"type": "error", "reason": "asr" | "busy" | "off" | ...}
  server -> {"type": "closed", "reason": "done" | "cancelled" | "replaced" | "idle" | "max length" | ...}

Close codes: 4400 no / bad hello, 4401 not signed in, 4429 too many connections from this address in a
minute (DICTATE_HELLO_PER_MINUTE). Limits: DICTATE_MAX_SECONDS (finished there, the text kept),
DICTATE_IDLE_SECONDS without frames (finished), DICTATE_MAX_SESSIONS per worker (busy), one dictation per
user (a newer one replaces the older). The HTTP rate limiter does not see WebSockets, hence the hello limit.

Privacy: audio only in memory, dropped when the session ends; ASR_DEBUG_DIR never applies here; logs carry
counts and timings, never words.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.dictation import ears
from app.dictation.session import DictationSession

logger = logging.getLogger(__name__)
router = APIRouter()

HELLO_SECONDS = 5.0
MAX_FRAME_BYTES = 8192

STATS = {"sessions": 0, "active": 0, "refused": 0, "replaced": 0, "frames_dropped": 0, "finals": 0,
         "no_speech": 0, "errors": 0, "cancelled": 0}
_ACTIVE: dict = {}          # user key -> _Live
_HELLOS: dict = {}          # address -> [monotonic times]


async def identify(token: str):
    """The same check as the live voice's hello (app/voice/relay.py identify): a valid JWT, an active user."""
    from app.voice.relay import identify as _identify
    return await _identify(token)


def over_hello_limit(address: str, per_minute: int, now: float) -> bool:
    if per_minute <= 0:
        return False
    for a in [a for a, ts in _HELLOS.items() if not ts or now - ts[-1] > 60]:
        del _HELLOS[a]
    recent = [t for t in _HELLOS.get(address, []) if now - t <= 60]
    if len(recent) >= per_minute:
        _HELLOS[address] = recent
        return True
    _HELLOS[address] = recent + [now]
    return False


class _Live:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.ended = asyncio.Event()
        self.reason = ""

    def end(self, reason: str) -> None:
        if not self.ended.is_set():
            self.reason = reason
            self.ended.set()


async def _close(ws: WebSocket, msg: dict, code: int) -> None:
    try:
        await ws.send_json(msg)
        await ws.close(code)
    except Exception:  # noqa: BLE001
        pass


@router.websocket("/ws/dictate")
async def ws_dictate(ws: WebSocket):
    await ws.accept()
    address = ws.client.host if ws.client else "?"
    if over_hello_limit(address, settings.DICTATE_HELLO_PER_MINUTE, time.monotonic()):
        STATS["refused"] += 1
        await _close(ws, {"type": "error", "reason": "rate"}, 4429)
        return
    try:
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), HELLO_SECONDS))
    except Exception:  # noqa: BLE001 — no hello in time, binary first, not JSON, closed
        await _close(ws, {"type": "error", "reason": "no hello"}, 4400)
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await _close(ws, {"type": "error", "reason": "no hello"}, 4400)
        return
    user = await identify(str(hello.get("token") or ""))
    if user is None:
        STATS["refused"] += 1
        await _close(ws, {"type": "error", "reason": "auth"}, 4401)
        return
    if (settings.DICTATE_ENGINE or "on").strip().lower() == "off":
        await _close(ws, {"type": "error", "reason": "off"}, 1000)
        return
    old = _ACTIVE.get(user.key)
    if old is not None:
        STATS["replaced"] += 1
        old.end("replaced")                     # a second tab / a quick restart: the newest dictation wins
    if len(_ACTIVE) - (1 if old is not None else 0) >= max(1, settings.DICTATE_MAX_SESSIONS):
        await _close(ws, {"type": "error", "reason": "busy"}, 1013)
        return
    live = _Live(ws)
    _ACTIVE[user.key] = live
    STATS["sessions"] += 1
    STATS["active"] = len(_ACTIVE)
    ear = ears.batch_ear()
    sess = DictationSession(ws.send_json, ear, lang=str(hello.get("lang") or "en"), partials=ears.partials_mode())
    try:
        await ws.send_json({"type": "ready", "max_s": settings.DICTATE_MAX_SECONDS, "partials": sess.partials})
        reason = await _run(ws, sess, live)
        if reason not in ("gone",):
            try:
                await ws.send_json({"type": "closed", "reason": reason})
                await ws.close(1000)
            except Exception:  # noqa: BLE001
                pass
    finally:
        if not sess.closed:
            await sess.cancel()
        if _ACTIVE.get(user.key) is live:
            del _ACTIVE[user.key]
        STATS["active"] = len(_ACTIVE)
        aclose = getattr(ear, "aclose", None)
        if aclose:
            try:
                await aclose()
            except Exception:  # noqa: BLE001
                pass


async def _finish(sess: DictationSession, why: str) -> str:
    msg = await sess.finish(why)
    kind = msg.get("type")
    STATS["finals" if kind == "final" else "no_speech" if kind == "no_speech" else "errors"] += 1
    return "done" if why == "stop" else why


async def _run(ws: WebSocket, sess: DictationSession, live: _Live) -> str:
    """Read the page until stop / cancel / a limit; the close reason."""
    idle = max(1.0, float(settings.DICTATE_IDLE_SECONDS))
    max_s = float(settings.DICTATE_MAX_SECONDS)
    ended = asyncio.create_task(live.ended.wait())
    try:
        while True:
            recv = asyncio.create_task(ws.receive())
            done, _ = await asyncio.wait({recv, ended}, timeout=idle, return_when=asyncio.FIRST_COMPLETED)
            if ended in done:
                recv.cancel()
                await sess.cancel()
                return live.reason or "replaced"
            if not done:
                recv.cancel()
                return await _finish(sess, "idle")
            msg = recv.result()
            if msg.get("type") == "websocket.disconnect":
                await sess.cancel()
                return "gone"
            data = msg.get("bytes")
            if data is not None:
                if len(data) > MAX_FRAME_BYTES or len(data) % 2:
                    STATS["frames_dropped"] += 1
                    continue
                await sess.audio(data)
                if sess.seconds >= max_s:
                    return await _finish(sess, "max length")
                continue
            try:
                m = json.loads(msg.get("text") or "")
            except ValueError:
                continue
            kind = m.get("type") if isinstance(m, dict) else None
            if kind == "stop":
                return await _finish(sess, "stop")
            if kind == "cancel":
                await sess.cancel()
                STATS["cancelled"] += 1
                return "cancelled"
    except WebSocketDisconnect:
        await sess.cancel()
        return "gone"
    finally:
        ended.cancel()
