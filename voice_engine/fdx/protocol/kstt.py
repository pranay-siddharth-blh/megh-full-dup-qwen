"""Kyutai's streaming speech-to-text server protocol (`/api/asr-streaming`, as used by kyutai-labs/delayed-streams-modeling).

Auth: header `kyutai-api-key: <key>` (or `?auth_id=<key>`). Every message is MessagePack.
  client -> server  {"type": "Audio", "pcm": [float, ...]}     24 kHz mono, 1920 samples (80 ms) per message
  client -> server  {"type": "Marker", "id": n}                 echoed back once everything before it is processed
  server -> client  {"type": "Word", "text": str, "start_time": float}
  server -> client  {"type": "EndWord", "stop_time": float}
  server -> client  {"type": "Step", "step_idx": int, "prs": [p_0.5s, p_1s, p_2s, p_3s]}   semantic pause heads
  server -> client  {"type": "Marker", "id": n}, {"type": "Ready"}
The words arrive about 0.5 s after they are spoken (the model's fixed delay)."""
from __future__ import annotations

import asyncio
import os

import msgpack
import numpy as np
import websockets

from .auth import connect_kwargs

FRAME = 1920


class STTClient:
    """Events in `events`: ('word', text, start_time), ('endword', stop_time), ('step', prs), ('marker', id),
    ('closed', reason)."""

    def __init__(self, url: str, api_key: str = "public_token", auth: str | None = None):
        self.url, self.api_key = url, api_key
        # how the key is presented: Kyutai's own header unless the gateway wants another style (FDX_STT_AUTH)
        self.auth = auth if auth is not None else (os.environ.get("FDX_STT_AUTH") or "header:kyutai-api-key")
        self.ws = None
        self.events: asyncio.Queue = asyncio.Queue()
        self.buf = np.zeros(0, dtype=np.float32)
        self._task = None

    async def connect(self, timeout: float = 10.0):
        gw = os.environ.get("FDX_STT_GATEWAY_KEY", "")                # the team gateway's own key (header apikey)
        extra = [(gw, os.environ.get("FDX_STT_GATEWAY_AUTH") or "header:apikey")] if gw else []
        url, kw = connect_kwargs(self.url, self.api_key, self.auth, extra)   # wss + key styles (fdx/protocol/auth.py)
        self.ws = await websockets.connect(url, max_size=None, open_timeout=timeout, ping_interval=20, **kw)
        self._task = asyncio.create_task(self._recv())
        return self

    async def _recv(self):
        try:
            async for msg in self.ws:
                if not isinstance(msg, (bytes, bytearray)):
                    continue
                d = msgpack.unpackb(msg, raw=False)
                t = d.get("type")
                if t == "Word":
                    await self.events.put(("word", d.get("text", ""), float(d.get("start_time", 0.0))))
                elif t == "EndWord":
                    await self.events.put(("endword", float(d.get("stop_time", 0.0))))
                elif t == "Step":
                    await self.events.put(("step", list(d.get("prs") or [])))
                elif t == "Marker":
                    await self.events.put(("marker", d.get("id")))
            await self.events.put(("closed", "server closed"))
        except Exception as e:  # noqa: BLE001
            await self.events.put(("closed", f"{type(e).__name__}: {str(e)[:120]}"))

    async def send_pcm(self, pcm: np.ndarray):
        """Any length in; whole 80 ms messages out (the remainder waits for the next call)."""
        self.buf = np.concatenate([self.buf, np.asarray(pcm, dtype=np.float32)])
        while len(self.buf) >= FRAME:
            chunk, self.buf = self.buf[:FRAME], self.buf[FRAME:]
            await self.ws.send(msgpack.packb({"type": "Audio", "pcm": [float(x) for x in chunk]}, use_bin_type=True, use_single_float=True))

    async def marker(self, mid: int):
        await self.ws.send(msgpack.packb({"type": "Marker", "id": mid}, use_bin_type=True))

    async def close(self):
        if self._task:
            self._task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass
