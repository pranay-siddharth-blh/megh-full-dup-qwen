"""The sovereign model keys, read at run time from the RDPR POC's settings file (read-only; never copied, written or
printed). Every service of this project gets its keys through `env()` and nothing else.

  RDPR name            -> our name(s)
  SQL_VERIFY_API_KEY   -> FDX_LLM_KEY, FDX_VLM_KEY        (qwen4-deploy: brain + letters)
  ASR_API_KEY          -> FDX_ASR_KEY                     (qwen3-asr: the interim ears)
  TTS_API_KEY          -> FDX_TTS_KEY                     (qwen3-tts: the side voice)
The gateway base URL comes with them (FDX_GATEWAY_URL). Values already set in the calling environment win.

`describe()` returns names and whether each is set (for status lines); it never returns a value."""
from __future__ import annotations

import os
import re
from pathlib import Path

SOURCE = Path(r"D:\RDPR POC\RDPR POC\ai_app\.env")   # read-only: opened for reading only, never written
MAP = {"SQL_VERIFY_API_KEY": ["FDX_LLM_KEY", "FDX_VLM_KEY"], "ASR_API_KEY": ["FDX_ASR_KEY"], "TTS_API_KEY": ["FDX_TTS_KEY"]}
URLS = {"SQL_VERIFY_BASE_URL": "FDX_GATEWAY_URL"}


def _read() -> dict:
    vals = {}
    try:
        text = SOURCE.read_text(encoding="utf-8")
    except OSError:
        return vals
    for row in text.splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*?)\s*$", row)
        if m:
            vals[m.group(1)] = m.group(2).strip("\"'")
    return vals


def env() -> dict:
    """{our name: value} for every key / URL found; the calling environment wins. Never print the result."""
    src, out = _read(), {}
    for theirs, ours in MAP.items():
        for name in ours:
            v = os.environ.get(name) or src.get(theirs, "")
            if v:
                out[name] = v
    for theirs, name in URLS.items():
        v = os.environ.get(name) or src.get(theirs, "")
        if v:
            out[name] = v.rstrip("/")
    return out


def describe() -> str:
    e = env()
    names = [n for ours in MAP.values() for n in ours] + list(URLS.values())
    return ", ".join(f"{n}({'set' if e.get(n) else 'missing'})" for n in names)


if __name__ == "__main__":
    print(describe())
