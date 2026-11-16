"""The duplex core's wire protocol, exactly as Kyutai's Moshi server and NVIDIA's PersonaPlex server speak it,
plus the Mitra extension frames.

Base protocol (both servers, `/api/chat`, binary WebSocket frames, first byte = kind):
  server -> client  0x00            handshake, once, after the persona / voice prompt has been processed
  client -> server  0x01 + bytes    Ogg-Opus audio of the person, 24 kHz mono
  server -> client  0x01 + bytes    Ogg-Opus audio, 24 kHz mono, one frame (80 ms) per model step
  server -> client  0x02 + utf-8    one text piece of the model's inner monologue ('▁' already replaced by a space)
PersonaPlex reads `text_prompt`, `voice_prompt` and `seed` from the query string; Moshi ignores them.

The core is INPUT-CLOCKED. Both servers' opus_loop decodes the person's audio, buffers it, and runs one model step per
1920 received samples (80 ms at 24 kHz); each step sends one audio frame (a silent frame when there is nothing to say)
and at most one text piece. No input, no step, no output: the core never speaks on a clock of its own. So the RELAY
keeps the input continuous: whenever the page sends nothing (muted, stalled, a test page with no microphone) it sends
silence in its place, or Mitra stops mid-word and the recogniser stops too.

Mitra extension v1.1 (our server fork implements it; the fake core does already):
  client -> server  0x10 + JSON {"id": n, "text": "..."}   speak this line now, in your own voice, while listening
  client -> server  0x11 + JSON {"id": n} | {}             stop that line (or every queued line)
  server -> client  0x12 + JSON {"id": n, "event": "start" | "done" | "cancelled"}
A server without the extension ignores 0x10 / 0x11 (both log an unknown kind and carry on), so the relay can always
send them; `settings.core_ext = False` tells the relay to use the side voice instead.
v1.1 over v1 (review findings 32, 48): forced lines are never self-yielded; `done` comes right after the line's last
VOICED frame, so no voiced frame of the line follows it; the input clock above.

Ordering rules a server implementing the extension must keep (the conformance suite checks them):
  * `start` for a line is sent BEFORE the first audio frame (and the first text piece) of that line;
  * `done` is sent right after the line's LAST VOICED frame: no voiced frame of a line comes after its done (at most
    the one frame already in flight on the wire), so the acoustic tail is never cut off or left to run on;
  * lines are said in the order received, one after another; a line queued behind another waits;
  * `cancel` ({}) stops the line being said within one step and drops every queued line (each gets `cancelled`);
  * forced lines are NEVER self-yielded: the person's voice over a line does not end it, because the relay owns
    barge-in and sends 0x11. A line ends with `done`, or with `cancelled` only after a cancel. Only the core's own
    free words may yield to the person;
  * text pieces of a forced line are the line's own words, in order, as they are spoken (each no later than the first
    audio frame of its word), all of them between the line's `start` and its `done`. The core's own words never fall
    inside that window: a fork holds them until after `done`. Whatever follows `done` is the core's own speech, which
    the relay's firewall judges (the fake's runon mode makes it carry on at once, with no quiet frame between);
  * the audio stream never pauses while input arrives: every step sends a frame, a silent one when there is nothing
    to say, exactly as in the base protocol."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.parse

import numpy as np
import sphn
import websockets

from .auth import connect_kwargs

HANDSHAKE, AUDIO, TEXT = 0x00, 0x01, 0x02
EXT_SPEAK, EXT_CANCEL, EXT_EVENT = 0x10, 0x11, 0x12
KINDS = {HANDSHAKE: "handshake", AUDIO: "audio", TEXT: "text", EXT_SPEAK: "speak", EXT_CANCEL: "cancel", EXT_EVENT: "event"}


def frame(kind: int, payload: bytes = b"") -> bytes:
    return bytes([kind]) + payload


def parse(msg: bytes) -> tuple[int, bytes]:
    if not msg:
        raise ValueError("empty frame")
    return msg[0], msg[1:]


def core_url(base: str, text_prompt: str = "", voice_prompt: str = "", seed: int = -1) -> str:
    q = {"text_prompt": text_prompt}
    if voice_prompt:
        q["voice_prompt"] = voice_prompt
    if seed is not None and seed >= 0:
        q["seed"] = str(seed)
    return base + ("&" if "?" in base else "?") + urllib.parse.urlencode(q)


class CoreClient:
    """One session with the duplex core. Feed it 24 kHz float PCM; read (kind, value) events from `events`:
    ('audio', np.float32 array) every step, ('text', str), ('event', dict), ('closed', reason)."""

    def __init__(self, url: str, rate: int = 24000, api_key: str | None = None, auth: str | None = None):
        self.url, self.rate = url, rate
        # a gateway in front of the core may want a key (FDX_CORE_API_KEY, presented as FDX_CORE_AUTH says)
        self.api_key = api_key if api_key is not None else os.environ.get("FDX_CORE_API_KEY", "")
        self.auth = auth if auth is not None else os.environ.get("FDX_CORE_AUTH", "none")
        self.ws = None
        self.writer = sphn.OpusStreamWriter(rate)
        self.reader = sphn.OpusStreamReader(rate)
        self.events: asyncio.Queue = asyncio.Queue()
        self._task = None
        self.handshake_s = None

    async def connect(self, timeout: float = 15.0):
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        url, kw = connect_kwargs(self.url, self.api_key, self.auth)   # wss + a gateway key style (fdx/protocol/auth.py)
        self.ws = await websockets.connect(url, max_size=None, open_timeout=timeout, ping_interval=20, **kw)
        first = await asyncio.wait_for(self.ws.recv(), timeout)
        if not isinstance(first, (bytes, bytearray)) or first[:1] != b"\x00":
            raise RuntimeError(f"core: expected the 0x00 handshake, got {first[:8]!r}")
        self.handshake_s = loop.time() - t0
        self._task = asyncio.create_task(self._recv())
        return self

    async def _recv(self):
        try:
            async for msg in self.ws:
                if not isinstance(msg, (bytes, bytearray)) or not msg:
                    continue
                kind, payload = msg[0], bytes(msg[1:])
                if kind == AUDIO:
                    pcm = self.reader.append_bytes(payload)
                    if pcm is not None and len(pcm):
                        await self.events.put(("audio", np.asarray(pcm, dtype=np.float32)))
                elif kind == TEXT:
                    await self.events.put(("text", payload.decode("utf-8", "replace")))
                elif kind == EXT_EVENT:
                    try:
                        await self.events.put(("event", json.loads(payload)))
                    except ValueError:
                        pass
            await self.events.put(("closed", "server closed"))
        except Exception as e:  # noqa: BLE001
            await self.events.put(("closed", f"{type(e).__name__}: {str(e)[:120]}"))

    async def send_pcm(self, pcm: np.ndarray):
        b = self.writer.append_pcm(np.asarray(pcm, dtype=np.float32))
        if b:
            await self.ws.send(frame(AUDIO, b))

    async def speak(self, sid: int, text: str):
        await self.ws.send(frame(EXT_SPEAK, json.dumps({"id": sid, "text": text}).encode()))

    async def cancel(self, sid: int | None = None):
        await self.ws.send(frame(EXT_CANCEL, json.dumps({} if sid is None else {"id": sid}).encode()))

    async def close(self):
        if self._task:
            self._task.cancel()
        if self.ws:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass
