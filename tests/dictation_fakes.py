"""Shared pieces of the dictation tests (D-111): spoken-like audio whose words a fake ear can read back, the
fake ears, and /ws/dictate on a real uvicorn server on a free port (never 8401).

The audio: each word is 300 ms of a 220 Hz tone whose loudness encodes the word's place in VOCAB, words
120 ms apart; a phrase break is a 700 ms silence (a pause the segmenter cuts at). The fake ear finds the
loud runs in whatever audio it is sent and says their words, so a segment, a live re-hearing and the
whole-recording pass all get the words actually in that audio, in order.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import numpy as np
import uvicorn
from fastapi import FastAPI

from app.dictation import ears, router

RATE = 16000
VOCAB = ["how", "many", "houses", "in", "reply", "district", "were", "completed", "mgnrega", "person", "dies",
         "west", "garo", "hills", "during", "2023", "24", "okay", "the", "show"]
GOOD = "good-token"
WORD_S, GAP_S, PAUSE_S = 0.30, 0.12, 0.70


def _amp(i: int) -> float:
    return 0.06 + 0.012 * i


def speech(phrases: list, lead_s: float = 0.3, tail_s: float = 0.3) -> np.ndarray:
    """phrases: [[word, ...], ...] -> int16 PCM."""
    t = np.arange(int(WORD_S * RATE)) / RATE
    tone = np.sin(2 * np.pi * 220 * t)
    out = [np.zeros(int(lead_s * RATE))]
    for k, ph in enumerate(phrases):
        if k:
            out.append(np.zeros(int(PAUSE_S * RATE)))
        for j, w in enumerate(ph):
            if j:
                out.append(np.zeros(int(GAP_S * RATE)))
            out.append(tone * _amp(VOCAB.index(w)))
    out.append(np.zeros(int(tail_s * RATE)))
    x = np.concatenate(out)
    return (np.clip(x, -1, 1) * 32767).astype("<i2")


def frames(pcm: np.ndarray, n: int = 1280) -> list:
    return [pcm[i:i + n].tobytes() for i in range(0, len(pcm), n)]


def read_words(pcm16: bytes) -> list:
    x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
    words, run = [], []
    for k in range(0, len(x) - 159, 160):           # 10 ms
        piece = x[k:k + 160]
        rms = float(np.sqrt(np.mean(piece * piece)))
        if rms > 0.02:
            run.append(rms)
        elif run:
            if len(run) >= 8:
                amp = float(np.median(run)) * np.sqrt(2)
                i = int(round((amp - 0.06) / 0.012))
                if 0 <= i < len(VOCAB):
                    words.append(VOCAB[i])
            run = []
    if len(run) >= 8:
        amp = float(np.median(run)) * np.sqrt(2)
        i = int(round((amp - 0.06) / 0.012))
        if 0 <= i < len(VOCAB):
            words.append(VOCAB[i])
    return words


class FakeEar(ears.BatchEar):
    """BatchEar with the gateway replaced: the speech gate (asr_gate "dictate") is still held."""

    calls: list = []

    def __init__(self, delay: float = 0.02, fail: bool = False, silence: str = "Okay."):
        super().__init__(url="http://fake", model="fake", key="k")
        self.delay, self.fail, self.silence = delay, fail, silence

    async def _post(self, wav: bytes, prompt: str, language: str) -> str:
        FakeEar.calls.append(len(wav))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("gateway down")
        ws = read_words(wav[44:])
        if not ws:
            return self.silence
        s = " ".join(ws)
        return s[:1].upper() + s[1:] + "."


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server():
    app = FastAPI()
    app.include_router(router.router)
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    t0 = time.time()
    while time.time() - t0 < 10:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    return srv, th, f"ws://127.0.0.1:{port}/ws/dictate"


class User:
    def __init__(self, key: str):
        self.key, self.username, self.name = key, "u" + key, "User " + key


async def fake_identify(token: str):
    if token == GOOD:
        return User("7")
    if token.startswith("user-"):
        return User(token[5:])
    return None


async def dictate(url: str, pcm: "np.ndarray | None", *, token: str = GOOD, end: str = "stop",
                  realtime: float = 0.0, hello: "dict | None" = None, extra_frames: "list | None" = None,
                  wait_close: float = 20.0) -> dict:
    """Open /ws/dictate, send the audio, then `end` ('stop' | 'cancel' | 'none'); every message and the close code."""
    import websockets
    msgs: list = []
    code = None
    t_stop = None
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps(hello if hello is not None else {"type": "hello", "token": token, "lang": "en"}))

        async def reader():
            nonlocal code
            try:
                async for raw in ws:
                    msgs.append((time.monotonic(), json.loads(raw)))
            except Exception:  # noqa: BLE001
                pass
            code = ws.close_code
        rt = asyncio.create_task(reader())
        for _ in range(100):
            if msgs:
                break
            await asyncio.sleep(0.02)
        if msgs and msgs[0][1].get("type") == "ready":
            for f in (extra_frames or []):
                await ws.send(f)
            if pcm is not None:
                for f in frames(pcm):
                    try:
                        await ws.send(f)
                    except Exception:  # noqa: BLE001
                        break
                    if realtime:
                        await asyncio.sleep(0.08 * realtime)
                    else:
                        await asyncio.sleep(0)
            t_stop = time.monotonic()
            if end in ("stop", "cancel"):
                try:
                    await ws.send(json.dumps({"type": end}))
                except Exception:  # noqa: BLE001
                    pass
        try:
            await asyncio.wait_for(rt, wait_close)
        except asyncio.TimeoutError:
            rt.cancel()
        code = ws.close_code
    return {"msgs": [m for _, m in msgs], "times": [t for t, _ in msgs], "code": code, "t_stop": t_stop}
