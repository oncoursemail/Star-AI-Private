"""Small numpy helpers for the senses: PCM16 <-> float, down-mixing and resampling live blocks to 16 kHz mono."""
from __future__ import annotations

import numpy as np

RATE = 16000
FRAME = 512            # samples per 32 ms frame, same as star.voice.pcm


def pcm_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm(x) -> bytes:
    return (np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def db(level: float) -> float:
    return 20.0 * np.log10(max(float(level), 1e-9))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x), dtype=np.float64))) if len(x) else 0.0


class StreamResampler:
    """Any block of interleaved float32 audio -> mono 16 kHz. Box low-pass, then linear interpolation, with the phase
    carried across blocks so there is no seam. Good enough for recognition and classification, not for playback."""

    def __init__(self, source_rate: int, channels: int = 1) -> None:
        self.rate, self.channels = int(source_rate), int(channels)
        self.step = self.rate / RATE
        self._tail = np.zeros(0, dtype=np.float32)
        self._hist = np.zeros(max(0, int(round(self.step)) - 1), dtype=np.float32)
        self._phase = 0.0

    def process(self, block) -> np.ndarray:
        x = np.asarray(block, dtype=np.float32)
        if self.channels > 1:
            x = x.reshape(-1, self.channels).mean(axis=1)
        if self.rate == RATE:
            return x
        width = max(1, int(round(self.step)))
        if width > 1:
            joined = np.concatenate([self._hist, x])
            self._hist = joined[-(width - 1):]
            x = np.convolve(joined, np.full(width, 1.0 / width, dtype=np.float32), mode="valid")
        x = np.concatenate([self._tail, x])
        last = len(x) - 1
        positions = np.arange(self._phase, last, self.step)
        out = np.interp(positions, np.arange(len(x)), x).astype(np.float32)
        used = int(positions[-1] + self.step) if len(positions) else 0
        next_pos = (positions[-1] + self.step) if len(positions) else self._phase
        self._tail = x[min(used, len(x)):]
        self._phase = float(next_pos - min(used, len(x)))
        return out


class Rechunker:
    """Collects float samples and hands out exact 512-sample PCM16 frames."""

    def __init__(self, frame: int = FRAME) -> None:
        self.frame = frame
        self._pending = np.zeros(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list[bytes]:
        self._pending = np.concatenate([self._pending, samples])
        out = []
        while len(self._pending) >= self.frame:
            out.append(float_to_pcm(self._pending[: self.frame]))
            self._pending = self._pending[self.frame:]
        return out
