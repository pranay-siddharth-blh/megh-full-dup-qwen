"""The voice relay's own settings.

They are NOT in app/config.py and must never go into .env: the app's Settings
reads .env with extra='forbid', so an unknown key there would stop the live app
from starting. They are read from the process environment first, then from
the file named by MEGH_VOICE_ENV (default certs/voice.env, which git already
ignores), then the defaults below.

Keys:
  GEMINI_API_KEY        the Gemini key (the voice is off without it, unless VOICE_LIVE_URL names a test server)
  VOICE_ENGINE          gemini (default) | off
  VOICE_LIVE_MODEL      the Gemini Live model, e.g. gemini-3.8-live
  VOICE_NAME            the prebuilt voice, e.g. Kore
  VOICE_LIVE_URL        a ws:// test server speaking the Gemini Live protocol (tests/voice/fake_live.py); no key is sent to it
  VOICE_IDLE_SECONDS    the browser closes a session after this much quiet (sent to it in `ready`)
  VOICE_MAX_SESSIONS    live sessions per worker
  VOICE_TOOL_TIMEOUT    seconds the relay waits for the page to return an answer before saying it is still coming
  VOICE_BLOCK_UNSOURCED on (default) | off: a sentence the voice says with a number no answer supports is cut (its
                        audio and caption) and replaced; off = logged only, as before 14 Nov 2026
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

GEMINI_LIVE_URL = ("wss://generativelanguage.googleapis.com/ws/"
                   "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent")


def _read_file(path: Path) -> dict:
    out: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


@dataclass(frozen=True)
class VoiceSettings:
    api_key: str
    engine: str
    model: str
    voice: str
    live_url: str
    idle_seconds: int
    max_sessions: int
    tool_timeout: float
    block_unsourced: bool = True

    @property
    def enabled(self) -> bool:
        return self.engine == "gemini" and bool(self.api_key or self.live_url)

    def url(self) -> str:
        """Where the relay connects. A test server gets no key."""
        if self.live_url:
            return self.live_url
        return f"{GEMINI_LIVE_URL}?key={self.api_key}"


def load() -> VoiceSettings:
    """Read on every new session, so a key change needs no restart."""
    f = _read_file(Path(os.environ.get("MEGH_VOICE_ENV", "certs/voice.env")))

    def get(k: str, default: str = "") -> str:
        v = os.environ.get(k)
        if v not in (None, ""):
            return str(v)
        v = f.get(k)
        return v if v not in (None, "") else default

    def num(k: str, default: float) -> float:
        try:
            return float(get(k, str(default)))
        except ValueError:
            return default

    return VoiceSettings(
        api_key=get("GEMINI_API_KEY"),
        engine=get("VOICE_ENGINE", "gemini").lower(),
        model=get("VOICE_LIVE_MODEL", "gemini-3.8-live"),
        voice=get("VOICE_NAME", "Kore"),
        live_url=get("VOICE_LIVE_URL"),
        idle_seconds=int(num("VOICE_IDLE_SECONDS", 120)),
        max_sessions=int(num("VOICE_MAX_SESSIONS", 40)),
        tool_timeout=num("VOICE_TOOL_TIMEOUT", 100.0),
        block_unsourced=get("VOICE_BLOCK_UNSOURCED", "on").strip().lower() not in ("off", "0", "false", "no"),
    )
