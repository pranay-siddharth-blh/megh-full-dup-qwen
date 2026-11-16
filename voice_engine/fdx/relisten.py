"""A second, vocabulary-primed listen for a short turn the streaming recogniser got wrong (4 Nov 2026).

Kyutai STT 1B has no custom vocabulary: inside a dashboard's scope, "and Hunsur" came back as "An answer." and the
follow-up was lost (atlas multi_turn on the real STT). For such a turn the relay sends the turn's own audio to the
gateway's qwen3-asr once, primed with the place names and terms in play, and uses the new words only when they decide
to something the first ones did not. One request, ~0.4 s, only on short turns that failed to parse.

  await transcribe(pcm24, prompt) -> text or None (never raises)

The call shape and the guards (prompt echo, a lone filler over long voice, impossibly dense text) are sideears/server.py's.
Keys from the environment the stack gives the service (FDX_ASR_KEY, FDX_GATEWAY_URL; ops/keys.py), never from a file."""
from __future__ import annotations

import asyncio
import time
import io
import os
import re
import wave

import numpy as np

STATS = {"calls": 0, "used": 0, "failures": 0, "dropped": 0, "last_error": ""}
_NORM = re.compile(r"[^a-z0-9]+")
FILLERS = {"okay", "ok", "oh", "uh", "um", "hmm", "mm", "yes", "no", "thank you", "thanks", "bye"}
_client = None


def available() -> bool:
    return bool(os.environ.get("FDX_ASR_KEY") and os.environ.get("FDX_GATEWAY_URL"))


def _http():
    global _client
    if _client is None:
        import httpx
        from fdx.protocol.auth import httpx_verify          # FDX_CA_BUNDLE turns verification on (14 Nov)
        _client = httpx.AsyncClient(timeout=6.0, verify=httpx_verify())
    return _client


def _wav16k(pcm24: np.ndarray) -> bytes:
    n = int(len(pcm24) * 16000 / 24000)
    x = np.interp(np.linspace(0, len(pcm24) - 1, n), np.arange(len(pcm24)), pcm24) if len(pcm24) else np.zeros(0)
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return b.getvalue()


def _longest_run(a: list[str], b: list[str]) -> int:
    """The longest stretch of words that a and b share, in the same order."""
    best = 0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0] * (len(b) + 1)
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def _ok(text: str, prompt: str, voiced_s: float, echo: str = "bag") -> bool:
    return _why_not(text, prompt, voiced_s, echo) == ""


def _why_not(text: str, prompt: str, voiced_s: float, echo: str = "bag") -> str:
    """'' when the transcript is usable, else the reason it is not (logged by the caller)."""
    toks = [t for t in _NORM.sub(" ", (text or "").lower()).split() if t]
    if not toks:
        return "empty"
    if echo == "run":
        # 12 Nov (Megh): a question made of the domain's own words ("MGNREGA person-days in West Garo Hills in 2023-24")
        # is mostly prompt vocabulary, so the bag-of-words test threw correct transcripts away; an echo repeats the
        # prompt IN ORDER, so only a long shared run (6+ words, or nearly the whole transcript) is an echo
        plist = [t for t in _NORM.sub(" ", prompt.lower()).split() if t]
        run = _longest_run(toks, plist)
        if run >= 6 or (len(toks) >= 4 and run >= 0.8 * len(toks)):
            return f"prompt echo (a run of {run} prompt words)"
    else:
        ptok = {t for t in _NORM.sub(" ", prompt.lower()).split() if t}
        if len(toks) >= 4 and sum(t in ptok for t in toks) / len(toks) >= 0.8:
            return "prompt echo (80% prompt words)"   # the vocabulary prompt echoed back
    if " ".join(toks) in FILLERS and voiced_s > 1.5:
        return "a filler for a long stretch of voice"
    if sum(len(t) for t in toks) / max(voiced_s, 0.05) > 25:
        return "too many letters for the voice heard"   # more characters than anyone can say in that time
    return ""


_ID = re.compile(r"\b(?:GR|SK)-[A-Z0-9]*\d", re.I)


def merge_ears(kyutai: str, asr: str) -> str:
    """Dual ears (10 Nov): qwen3-asr's words for the turn, unless the streaming words clearly hold something they
    lost: a case id, or a known place when qwen3-asr names none. Shared by the relay and voicekit/evaluate.py."""
    from fdx import lexicon
    kc, _ = lexicon.correct(kyutai or "")
    ac, _ = lexicon.correct(asr or "")
    ac, _ = lexicon.prefer_bigger(ac)
    if not ac.strip():
        return kyutai
    if _ID.search(kc) and not _ID.search(ac):
        return kyutai
    if lexicon.places_in(kc) and not lexicon.places_in(ac):
        return kyutai
    return ac


async def names_pass(text: str, pcm24: np.ndarray, rate: int = 24000) -> str:
    """Hybrid ears (6 Nov): a turn whose words hold a DOUBTFUL place name (lexicon.doubtful_words) is heard once more,
    primed with the gazetteer names that sound closest to the doubtful words; the new words (after lexicon.correct) win
    only when they name a known place the first words did not. Shared by the relay and voicekit/evaluate.py."""
    from fdx import lexicon
    doubt = lexicon.doubtful_words(text)
    if not doubt:
        return text
    cands: list[str] = []
    for w in doubt[:3]:
        cands += [c for c in lexicon.candidates(w) if c not in cands]
    prompt = ("Karnataka grievance assistant. Place names that may be said: " + ", ".join(cands[:18])
              + ". Also: Hunsur, Piriyapatna, Mysuru, Tahsildar, PDO, L1, L2, L3.")
    new = await transcribe(pcm24, prompt, voiced_s=len(pcm24) / rate)
    if not new:
        return text
    new, _ = lexicon.correct(new)
    new, _ = lexicon.prefer_bigger(new)            # "Hunur" (a village) for "Hunsur" (the taluk): the taluk
    before, after = lexicon.places_in(text), lexicon.places_in(new)
    gained = [p for p in after if p not in before]
    lost = [p for p in before if p not in after]
    # never trade a place the first words had for a new one: "... periopatna? Sorry, I mean Mysuru." came back as
    # "... Piriyapatna? Sorry, I mean my." (6 Nov atlas v14): it gained Piriyapatna and lost the place that was meant
    return new if gained and not lost else text


async def transcribe(pcm24: np.ndarray, prompt: str, voiced_s: float = 1.0, echo: str = "bag",
                     info: dict | None = None) -> str | None:
    """echo: "bag" (default; Mitra's place-list prompt) or "run" (a prompt of the domain's whole vocabulary: Megh).
    info (optional): filled with {"why": "ok" | "dropped: <reason>" | "failed: <error>", "text": raw words, "s": secs}."""
    info = info if info is not None else {}
    t0 = time.monotonic()
    if not available() or len(pcm24) < 2400:
        info.update(why="skipped", text="", s=0.0)
        return None
    url = os.environ["FDX_GATEWAY_URL"].rstrip("/") + "/audio/transcriptions"
    data = {"model": os.environ.get("FDX_ASR_MODEL", "qwen3-asr"), "language": "en", "prompt": prompt[:600]}
    STATS["calls"] += 1
    try:
        r = await asyncio.wait_for(_http().post(url, headers={"Authorization": f"Bearer {os.environ['FDX_ASR_KEY']}"},
                                                data=data, files={"file": ("turn.wav", _wav16k(pcm24), "audio/wav")}), 6.0)
        if r.status_code != 200:
            STATS["failures"] += 1
            STATS["last_error"] = f"HTTP {r.status_code}"
            info.update(why=f"failed: HTTP {r.status_code}", text="", s=time.monotonic() - t0)
            return None
        text = str((r.json() or {}).get("text") or "").strip()
        why = _why_not(text, prompt, voiced_s, echo)
        if why:
            STATS["dropped"] += 1
            STATS["last_drop"] = f"{why}: {text[:80]!r}"
            info.update(why=f"dropped: {why}", text=text, s=time.monotonic() - t0)
            return None
        info.update(why="ok", text=text, s=time.monotonic() - t0)
        return text
    except Exception as e:  # noqa: BLE001
        STATS["failures"] += 1
        STATS["last_error"] = type(e).__name__
        info.update(why=f"failed: {type(e).__name__}", text="", s=time.monotonic() - t0)
        return None
