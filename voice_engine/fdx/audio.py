"""Audio helpers for the relay: PCM conversion, a stateful 16 kHz -> 24 kHz resampler (no clicks between chunks),
a 24 kHz -> 16 kHz one for test tools, a running noise floor, and frame RMS. NumPy and SciPy only."""
from __future__ import annotations

import numpy as np
from scipy.signal import firwin, lfilter


def pcm16_to_f32(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768.0


def f32_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


class Resampler:
    """Rational resampler up/down with a persistent low-pass filter state, so a stream cut into arbitrary chunks
    comes out identical to the whole stream resampled at once."""

    def __init__(self, up: int, down: int, taps: int = 96):
        self.up, self.down = up, down
        cutoff = 1.0 / max(up, down)
        self.h = firwin(taps, cutoff * 0.92) * up
        self.zi = np.zeros(len(self.h) - 1)
        self.phase = 0                         # position in the upsampled stream, modulo `down`

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if not len(x):
            return np.zeros(0, dtype=np.float32)
        u = np.zeros(len(x) * self.up)
        u[:: self.up] = x
        y, self.zi = lfilter(self.h, 1.0, u, zi=self.zi)
        start = (-self.phase) % self.down
        out = y[start:: self.down]
        self.phase = (self.phase + len(u)) % self.down
        return out.astype(np.float32)


def up16to24() -> Resampler:
    return Resampler(3, 2)


def down24to16() -> Resampler:
    return Resampler(2, 3)


class NoiseFloor:
    """A slow running estimate of the room's quiet level; it only learns from frames that are not speech."""

    def __init__(self, init: float = 0.004, alpha: float = 0.05):
        self.v, self.alpha = init, alpha

    def update(self, level: float, speech: bool):
        if not speech:
            self.v = (1 - self.alpha) * self.v + self.alpha * min(level, 0.05)
        return self.v
