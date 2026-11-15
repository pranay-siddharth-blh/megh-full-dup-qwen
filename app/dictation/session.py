"""One dictation: frames in, live text and the final text out (D-111). No socket code here (router.py).

Flow
  * feed(): the segmenter cuts the stream at pauses >= 0.5 s or at 12 s. Each closed segment is heard by the
    BatchEar (one request, retried once), guarded (clean.why_not) and committed. The committed segments, in
    order and up to the first one still being heard, are the STABLE text.
  * live words (DICTATE_PARTIALS=asr): the open segment is heard again as it grows, first once it holds
    0.35 s of voice, then every 1.0 s of audio, one request at a time; those words are the TENTATIVE text.
  * finish(): the rest is flushed and heard. When the dictation had two or more voiced segments and lasted
    at most DICTATE_WHOLE_PASS_SECONDS, the whole recording is heard once more AT THE SAME TIME (so the
    final waits for one request, not two in a row) and that text is taken unless it lost a scheme, a
    district or a year the segments had (Full Duplex fdx/relisten.py merge_ears, 10 Nov). Then clean().

Every message goes through `send` (an async callable taking a dict). Audio stays in this object only and is
dropped with it. Logs carry counts and timings, never words.
"""
from __future__ import annotations

import asyncio
import logging
import time

from app import asr_guard
from app.config import settings
from app.dictation import clean as cleaner
from app.dictation.segmenter import Segment, Segmenter
from app.dictation.words import Chunk, join, split

logger = logging.getLogger(__name__)

PARTIAL_FIRST_VOICE_S = 0.35
TAIL_SKIP_S = 1.0
PARTIAL_EVERY_S = 1.0
JOIN_PAUSE_S = 1.0          # a full stop the model put at a cut shorter than this is a mid-sentence pause


class _Part:
    __slots__ = ("seg", "raw", "state", "heard_live", "why")

    def __init__(self, seg: Segment):
        self.seg = seg
        self.raw = ""
        self.state = "hearing"          # hearing | done | failed
        self.heard_live = ""            # its last live words, shown until it is committed
        self.why = ""


# ── joining segments ────────────────────────────────────────────────────────

_NAME_WORDS: set = set()


def _name_words() -> set:
    if not _NAME_WORDS:
        for ws, _, _ in cleaner._names():
            _NAME_WORDS.update(ws)
        _NAME_WORDS.update({"i", "megh", "meghalaya"})
    return _NAME_WORDS


def _lowerable(core: str) -> bool:
    return (core[:1].isupper() and core.isalpha() and core[1:] == core[1:].lower()
            and core.lower() not in _name_words())


def join_parts(parts: list) -> str:
    """Segment texts in order -> one text. parts: [(text, pause_before_s)]. A full stop the model wrote at
    a short pause is dropped and the next word goes back to lower case ("How many houses." + "Were
    completed?" -> "How many houses were completed?")."""
    chunks: list = []
    for text, pause in parts:
        nxt = split(text)
        if not nxt:
            continue
        if chunks and pause < JOIN_PAUSE_S and chunks[-1].trail.endswith(".") and not chunks[-1].trail.endswith(".."):
            last = chunks[-1]
            chunks[-1] = Chunk(last.lead, last.core, last.trail[:-1])
            if _lowerable(nxt[0].core):
                nxt[0] = Chunk(nxt[0].lead, nxt[0].core[:1].lower() + nxt[0].core[1:], nxt[0].trail)
        chunks += nxt
    return join(chunks)


# ── facts (what the whole-recording pass must not lose) ─────────────────────

def facts(text: str) -> set:
    """Schemes, districts and years / financial years named in a CLEANED text (lower case)."""
    low = " " + " ".join(cleaner.letters(w) for w in text.lower().replace("-", " ").split()) + " "
    out = set()
    for ws, _, canon in cleaner._names():
        if " " + " ".join(ws) + " " in low:
            out.add(canon.lower())
    for w in text.replace(",", " ").replace("?", " ").replace(".", " ").split():
        c = w.lower()
        if c.startswith("fy"):
            c = c[2:]
        if len(c) >= 4 and c[:2] == "20" and c[:4].isdigit():
            out.add(c)
    # a name inside a longer name ("CM Elevate" in "CM Elevate Legacy") is not a fact of its own
    return {f for f in out if not any(f != g and f in g for g in out)}


def merge(whole: str, segments: str) -> "tuple[str, str]":
    """(text, which): the whole-recording words unless they lost a fact the segment words had."""
    if not whole.strip():
        return segments, "segments"
    if not segments.strip():
        return whole, "whole"
    if facts(segments) - facts(whole):
        return segments, "segments"
    return whole, "whole"


# ── the session ─────────────────────────────────────────────────────────────

class DictationSession:
    def __init__(self, send, ear, *, lang: str = "en", prompt: "str | None" = None, partials: str = "asr"):
        self.send_raw = send
        self.ear = ear
        self.lang = lang or "en"
        self.prompt = settings.ASR_PROMPT if prompt is None else prompt
        self.partials = partials
        self.seg = Segmenter()
        self.parts: list = []
        self.tasks: set = set()
        self.live_task: "asyncio.Task | None" = None
        self.live_at_s = -1.0               # open-segment length when its last live hearing started
        self.live_seg = -1                  # which segment that hearing was for
        self.live_text = ""
        self.seq = 0
        self.last_sent = ("", "")
        self.lock = asyncio.Lock()
        self.closed = False
        self.t0 = time.monotonic()
        self.stats = {"partials": 0, "asr_calls": 0, "asr_failures": 0, "dropped": 0, "frames": 0,
                      "first_partial_ms": None}

    # ── sending ─────────────────────────────────────────────────────────
    async def send(self, msg: dict) -> None:
        if self.closed and msg.get("type") == "partial":
            return
        async with self.lock:
            await self.send_raw(msg)

    def _stable_and_tentative(self) -> "tuple[str, str]":
        stable_parts, rest = [], []
        prefix = True
        for p in self.parts:
            pause = (p.seg.lead_quiet_s + (self.parts[p.seg.index - 1].seg.trail_quiet_s if p.seg.index else 0.0))
            if prefix and p.state in ("done", "failed"):
                if p.raw:
                    stable_parts.append((p.raw, pause))
            else:
                prefix = False
                live = p.raw or p.heard_live
                if live:
                    rest.append((live, pause))
        if self.live_text and self.live_seg == self.seg.count:
            rest.append((self.live_text, 0.0))
        stable = cleaner.clean(join_parts(stable_parts)).text if stable_parts else ""
        tentative = cleaner.clean(join_parts(rest), spelling=False).text if rest else ""
        return stable, tentative

    async def push_partial(self) -> None:
        if self.closed:
            return
        stable, tentative = self._stable_and_tentative()
        if (stable, tentative) == self.last_sent:
            return
        self.last_sent = (stable, tentative)
        self.seq += 1
        self.stats["partials"] += 1
        if self.stats["first_partial_ms"] is None and (stable or tentative):
            self.stats["first_partial_ms"] = round((time.monotonic() - self.t0) * 1000)
        await self.send({"type": "partial", "seq": self.seq, "stable": stable, "tentative": tentative})

    # ── hearing ─────────────────────────────────────────────────────────
    async def _hear(self, pcm: bytes, queue_timeout: float) -> str:
        self.stats["asr_calls"] += 1
        return await self.ear.transcribe(pcm, self.prompt, self.lang, queue_timeout=queue_timeout)

    async def _commit(self, part: _Part) -> None:
        seg = part.seg
        for attempt in (1, 2):
            try:
                raw = await self._hear(seg.pcm, 10.0)
                why = cleaner.why_not(raw, self.prompt, seg.voiced_s, seg.seconds)
                if why:
                    self.stats["dropped"] += 1
                    part.why = why
                    raw = ""
                part.raw, part.state = raw, "done"
                break
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.stats["asr_failures"] += 1
                part.why = type(e).__name__
                if attempt == 2:
                    part.state = "failed"
        await self.push_partial()

    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    async def _live(self, seg_index: int, pcm: bytes, voiced_s: float, seconds: float) -> None:
        try:
            raw = await self._hear(pcm, 0.5)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — live words are best effort; the committed words decide
            return
        if cleaner.why_not(raw, self.prompt, voiced_s, seconds):
            return
        if seg_index == self.seg.count:
            self.live_text, self.live_seg = raw, seg_index
        elif seg_index < len(self.parts) and self.parts[seg_index].state == "hearing":
            self.parts[seg_index].heard_live = raw
        else:
            return
        await self.push_partial()

    def _maybe_live(self) -> None:
        if self.partials != "asr" or self.closed:
            return
        if self.live_task is not None and not self.live_task.done():
            return
        if sum(1 for p in self.parts if p.state == "hearing") > 1:
            return                                   # the ears are behind: commits first
        voiced, length = self.seg.open_voiced_s(), self.seg.open_seconds()
        if voiced < PARTIAL_FIRST_VOICE_S:
            return
        if self.live_seg == self.seg.count and length - self.live_at_s < PARTIAL_EVERY_S:
            return
        if self.live_seg != self.seg.count:
            self.live_text = ""
        self.live_seg, self.live_at_s = self.seg.count, length
        self.live_task = self._spawn(self._live(self.seg.count, self.seg.open_pcm(), voiced, length))

    # ── the page's input ────────────────────────────────────────────────
    async def audio(self, data: bytes) -> None:
        if self.closed:
            return
        self.stats["frames"] += 1
        for seg in self.seg.feed(data):
            part = _Part(seg)
            if self.live_seg == seg.index:
                part.heard_live = self.live_text
                self.live_text = ""
            self.parts.append(part)
            self._spawn(self._commit(part))
        self._maybe_live()

    @property
    def seconds(self) -> float:
        return self.seg.total_s

    async def finish(self, reason: str = "stop") -> dict:
        """The final message ({type: final | no_speech | error}); it is also sent."""
        if self.closed:
            return {}
        self.closed = True
        started = time.monotonic()
        if self.live_task is not None and not self.live_task.done():
            self.live_task.cancel()
        tail = self.seg.flush()
        # the room quiet between the last word and the tap on Stop (no voice at all, under 1 s): on the 240-clip
        # bank (15 Nov) every such tail came back as the vocabulary prompt (an echo) and only made the final
        # wait for it. A tail with any voice in it, or longer, is heard (D-019: pauses are cut points only).
        if tail is not None and not (tail.voiced_s == 0 and tail.seconds < TAIL_SKIP_S):
            part = _Part(tail)
            part.heard_live = self.live_text
            self.parts.append(part)
            self._spawn(self._commit(part))
        voiced_parts = sum(1 for p in self.parts if p.seg.voiced_s > 0)
        total = self.seg.total_s
        short_enough = total <= settings.DICTATE_WHOLE_PASS_SECONDS
        whole_task = None
        if voiced_parts >= 2 and short_enough:          # at the same time as the last segment, not after it
            whole_task = asyncio.create_task(self._whole(self.seg.all_pcm(), total))
        pending = [t for t in list(self.tasks) if t is not self.live_task]
        if pending:
            await asyncio.wait(pending, timeout=settings.DICTATE_ASR_TIMEOUT_SECONDS * 2 + 5)
        if whole_task is None and short_enough and any(p.state == "failed" for p in self.parts):
            # a segment the ears could not hear (twice): the whole recording is the last try
            whole_task = asyncio.create_task(self._whole(self.seg.all_pcm(), total))
        whole = ""
        if whole_task is not None:
            try:
                whole = await asyncio.wait_for(whole_task, settings.DICTATE_ASR_TIMEOUT_SECONDS + 5)
            except Exception:  # noqa: BLE001
                whole = ""
        segs = cleaner.clean(join_parts([(p.raw, p.seg.lead_quiet_s + (self.parts[i - 1].seg.trail_quiet_s
                                                                        if i else 0.0))
                                         for i, p in enumerate(self.parts) if p.raw]))
        chosen_text, which = segs.text, "segments"
        corrections = segs.corrections
        if whole:
            w = cleaner.clean(whole)
            chosen_text, which = merge(w.text, segs.text)
            if which == "whole":
                corrections = w.corrections
        final_ms = round((time.monotonic() - started) * 1000)
        failed = any(p.state == "failed" for p in self.parts)
        if chosen_text.strip():
            msg = {"type": "final", "text": chosen_text, "corrections": corrections,
                   "seconds": round(total, 2)}
            if reason in ("max length", "idle"):
                msg["ended"] = reason
        elif failed:
            msg = {"type": "error", "reason": "asr"}
        else:
            msg = {"type": "no_speech"}
        await self.send(msg)
        logger.info("dictation: %s audio_s=%.1f segments=%d voiced_segments=%d partials=%d asr_calls=%d "
                    "asr_failures=%d dropped=%d chose=%s final_ms=%d first_partial_ms=%s words=%d ended=%s",
                    msg["type"], total, len(self.parts), voiced_parts, self.stats["partials"],
                    self.stats["asr_calls"], self.stats["asr_failures"], self.stats["dropped"], which,
                    final_ms, self.stats["first_partial_ms"], len(chosen_text.split()), reason)
        self.drop()
        return msg

    async def _whole(self, pcm: bytes, total: float) -> str:
        try:
            raw = await self._hear(pcm, 10.0)
        except Exception:  # noqa: BLE001
            self.stats["asr_failures"] += 1
            return ""
        if cleaner.why_not(raw, self.prompt, self.seg.voiced_total_s(), total):
            return ""
        return raw

    async def cancel(self) -> None:
        self.closed = True
        for t in list(self.tasks):
            t.cancel()
        logger.info("dictation: cancelled audio_s=%.1f segments=%d asr_calls=%d", self.seg.total_s,
                    len(self.parts), self.stats["asr_calls"])
        self.drop()

    def drop(self) -> None:
        """Forget the audio and the words (privacy: memory only, gone at the end)."""
        for t in list(self.tasks):
            if not t.done():
                t.cancel()
        self.seg = Segmenter()
        for p in self.parts:
            p.seg.pcm = b""
            p.raw = p.heard_live = ""
        self.parts = []
        self.live_text = ""


__all__ = ["DictationSession", "join_parts", "merge", "facts", "asr_guard"]
