"""Rolling buffer of recent audio (PCM16, 16 kHz mono) with a sample clock, thread-safe."""
from __future__ import annotations

import threading

import numpy as np

from .audio import RATE, pcm_to_float


class RollingBuffer:
    def __init__(self, seconds: float = 30.0) -> None:
        self.capacity = int(seconds * RATE)
        self._data = np.zeros(0, dtype=np.float32)
        self.total = 0                       # samples ever appended: the stream's own clock
        self._lock = threading.Lock()

    def append(self, pcm: bytes) -> None:
        x = pcm_to_float(pcm)
        with self._lock:
            self._data = np.concatenate([self._data, x])[-self.capacity:]
            self.total += len(x)

    def tail(self, seconds: float) -> np.ndarray:
        with self._lock:
            return self._data[-int(seconds * RATE):].copy()

    def __len__(self) -> int:
        return len(self._data)
