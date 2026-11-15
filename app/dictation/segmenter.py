"""Cut points for dictation (D-111): a segment closes at a pause of >= 500 ms or at 12 s.

Every sample is transcribed: pauses are only where the audio is cut, never what is thrown away (D-019, "no
VAD gating": qwen3-asr reads speech that an energy detector cannot see). The energy is read on 20 ms
pieces of the 16 kHz PCM16 the page streams. "Voice" = louder than three times the room's own floor (the
quietest tenth of the last 3 s), and never quieter than 0.004 full scale. A segment closes when it has held
at least 0.25 s of voice and then 0.5 s without any. A segment that reaches 12 s is cut at its quietest
20 ms in the last 3 s, so a word is not cut in half.

Pure logic, no I/O: feed(bytes) -> closed segments; flush() -> the rest.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

RATE = 16000
SUB = 320                   # 20 ms
BYTES = 2                   # PCM16


@dataclass
class Segment:
    index: int
    start_s: float
    end_s: float
    pcm: bytes
    voiced_s: float
    lead_quiet_s: float
    trail_quiet_s: float

    @property
    def seconds(self) -> float:
        return self.end_s - self.start_s


class Segmenter:
    def __init__(self, pause_s: float = 0.5, max_s: float = 12.0, min_voice_s: float = 0.25):
        self.pause_n = max(1, int(round(pause_s * RATE / SUB)))
        self.max_n = max(self.pause_n + 1, int(max_s * RATE / SUB))
        self.min_voice_n = max(1, int(round(min_voice_s * RATE / SUB)))
        self.pcm = bytearray()          # every sample of the dictation (memory only)
        self.levels: list = []          # RMS of each 20 ms piece, whole dictation
        self.voiced: list = []          # bool per piece
        self.rest = b""                 # bytes not yet a whole 20 ms piece
        self.seg_start = 0              # piece index where the open segment starts
        self.count = 0
        self.first_voice_s: "float | None" = None

    # ── reading ──────────────────────────────────────────────────────────
    @property
    def total_s(self) -> float:
        return (len(self.pcm) // BYTES) / RATE

    def _floor(self) -> float:
        recent = self.levels[-150:]                     # the last 3 s
        if not recent:
            return 0.0
        return float(np.percentile(recent, 10))

    def _threshold(self) -> float:
        return max(0.004, 3.0 * self._floor())

    def open_pcm(self) -> bytes:
        return bytes(self.pcm[self.seg_start * SUB * BYTES:])

    def open_voiced_s(self) -> float:
        return sum(self.voiced[self.seg_start:]) * SUB / RATE

    def open_seconds(self) -> float:
        return (len(self.levels) - self.seg_start) * SUB / RATE

    def all_pcm(self) -> bytes:
        return bytes(self.pcm)

    def voiced_total_s(self) -> float:
        return sum(self.voiced) * SUB / RATE

    # ── cutting ──────────────────────────────────────────────────────────
    def _cut(self, end: int) -> Segment:
        v = self.voiced[self.seg_start:end]
        lead = 0
        while lead < len(v) and not v[lead]:
            lead += 1
        trail = 0
        while trail < len(v) and not v[len(v) - 1 - trail]:
            trail += 1
        seg = Segment(self.count, self.seg_start * SUB / RATE, end * SUB / RATE,
                      bytes(self.pcm[self.seg_start * SUB * BYTES:end * SUB * BYTES]),
                      sum(v) * SUB / RATE, lead * SUB / RATE, trail * SUB / RATE)
        self.count += 1
        self.seg_start = end
        return seg

    def feed(self, data: bytes) -> list:
        out = []
        self.pcm += data
        buf = self.rest + data
        whole = len(buf) - len(buf) % (SUB * BYTES)
        self.rest = buf[whole:]
        if not whole:
            return out
        x = np.frombuffer(buf[:whole], dtype="<i2").astype(np.float32) / 32768.0
        for piece in x.reshape(-1, SUB):
            rms = float(np.sqrt(np.mean(piece * piece)))
            voiced = rms > self._threshold()
            self.levels.append(rms)
            self.voiced.append(voiced)
            if voiced and self.first_voice_s is None:
                self.first_voice_s = len(self.levels) * SUB / RATE
            n = len(self.levels)
            open_v = self.voiced[self.seg_start:]
            if (len(open_v) > self.pause_n and not any(open_v[-self.pause_n:])
                    and sum(open_v) >= self.min_voice_n):
                out.append(self._cut(n))
            elif n - self.seg_start >= self.max_n:
                lo = max(self.seg_start + 1, n - 150)
                window = self.levels[lo:n]
                k = int(np.argmin(window[::-1]))            # the latest of the quietest
                out.append(self._cut(n - k))
        return out

    def flush(self) -> "Segment | None":
        n = len(self.levels)
        if self.rest:                                       # the last partial 20 ms piece is kept too
            self.rest = b""
        end_bytes = len(self.pcm)
        if n <= self.seg_start and end_bytes <= self.seg_start * SUB * BYTES:
            return None
        seg = self._cut(n)
        # include a trailing part-piece in the pcm
        tail = bytes(self.pcm[n * SUB * BYTES:end_bytes])
        if tail:
            seg.pcm += tail
            seg.end_s = (end_bytes // BYTES) / RATE
        return seg
