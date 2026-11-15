"""The speech engines dictation hears with (D-111). Only our own self-hosted models.

    BatchEar.transcribe(pcm16: bytes, prompt: str, language="en") -> str
        qwen3-asr through the gateway's OpenAI-compatible /audio/transcriptions (16 kHz mono WAV), primed with
        the vocabulary prompt (config.ASR_PROMPT). Holds one slot of the speech gate (app/asr_gate.py, kind
        "dictate"), never the LLM's. Raises on failure; the session decides what a failure means.

    StreamEar (optional, DICTATE_PARTIALS=kyutai): Kyutai's streaming STT protocol (Full Duplex
        fdx/protocol/kstt.py: MessagePack over a WebSocket, 24 kHz frames, words ~0.5 s after they are said,
        semantic pause heads). It needs the `msgpack` package, which this app's environment does not have
        today, so it ships DISABLED: available() is False and the session uses BatchEar re-hearing for live
        words. The seam is here so turning it on is a port of one module, not a redesign.

Settings (app/config.py): DICTATE_ASR_URL / DICTATE_ASR_MODEL / DICTATE_ASR_API_KEY (blank = the ASR_*
ones), DICTATE_ASR_TIMEOUT_SECONDS, DICTATE_ASR_CONCURRENCY, DICTATE_PARTIALS, DICTATE_KYUTAI_URL.
Audio is never written anywhere (ASR_DEBUG_DIR does not apply), never logged.
"""
from __future__ import annotations

import importlib.util
import struct

import httpx

from app import asr_gate
from app.config import settings

RATE = 16000


def wav16k(pcm16: bytes) -> bytes:
    """A 44-byte RIFF header + the samples (16 kHz, mono, signed 16-bit little endian)."""
    n = len(pcm16)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE,
            RATE * 2, 2, 16) + b"data" + struct.pack("<I", n) + pcm16)


class BatchEar:
    """qwen3-asr, one request per piece of audio."""

    name = "qwen3-asr"

    def __init__(self, url: str = "", model: str = "", key: str = "", timeout: float = 0.0):
        self.url = (url or settings.DICTATE_ASR_URL or settings.ASR_BASE_URL).rstrip("/")
        self.model = model or settings.DICTATE_ASR_MODEL or settings.ASR_MODEL
        self.key = key or settings.DICTATE_ASR_API_KEY or settings.ASR_API_KEY
        self.timeout = timeout or settings.DICTATE_ASR_TIMEOUT_SECONDS
        self._own: "httpx.AsyncClient | None" = None

    def _client(self) -> httpx.AsyncClient:
        from app import llm
        if llm._client is not None:                       # the app's shared client (its TLS settings)
            return llm._client
        if self._own is None:
            self._own = httpx.AsyncClient(verify=llm._get_ssl_verify())
        return self._own

    async def transcribe(self, pcm16: bytes, prompt: str = "", language: str = "en",
                         queue_timeout: float = 10.0) -> str:
        async with asr_gate.slot("dictate", queue_timeout):
            return await self._post(wav16k(pcm16), prompt, language)

    async def _post(self, wav: bytes, prompt: str, language: str) -> str:
        from app.llm import _asr_language
        form = {"model": self.model, "language": _asr_language(language)}
        if prompt:
            form["prompt"] = prompt
        r = await self._client().post(f"{self.url}/audio/transcriptions",
                                      headers={"Authorization": f"Bearer {self.key}"}, data=form,
                                      files={"file": ("dictation.wav", wav, "audio/wav")}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return str((data.get("text") if isinstance(data, dict) else data) or "").strip()

    async def aclose(self) -> None:
        if self._own is not None:
            await self._own.aclose()
            self._own = None


class StreamEar:
    """Kyutai streaming STT (see the module note). Disabled until msgpack and a Kyutai server are present."""

    name = "kyutai-stt"

    @staticmethod
    def available() -> bool:
        return (settings.DICTATE_PARTIALS == "kyutai" and bool(settings.DICTATE_KYUTAI_URL)
                and importlib.util.find_spec("msgpack") is not None and _PORTED)


_PORTED = False             # the Kyutai client is not ported yet (msgpack missing in this venv, 15 Nov 2026)


def batch_ear() -> BatchEar:
    """The ear a new dictation uses (tests replace this function)."""
    return BatchEar()


def partials_mode() -> str:
    """'asr' (re-hear the open segment), 'kyutai' (only when StreamEar is available) or 'off'."""
    mode = (settings.DICTATE_PARTIALS or "asr").strip().lower()
    if mode == "kyutai" and not StreamEar.available():
        return "asr"
    return mode if mode in ("asr", "kyutai", "off") else "asr"
