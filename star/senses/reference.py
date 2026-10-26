"""Her own voice, excluded from what she hears.

Whatever STAR plays is also what the loopback capture hears (and, through loudspeakers, what the microphone hears).
Three parts:

PlaybackReference   a record of exactly what was sent to the speaker, on a 16 kHz timeline that follows the speaker's
                    queue (audio queued behind earlier audio starts when that ends; stop() cuts the future off).
ReferenceSpeaker    wraps any Speaker and records every play()/stop() into a PlaybackReference.
EchoCanceller       finds where the reference sits in a captured stream (cross-correlation, ties the stream's own
                    sample clock to the reference timeline), fits a short FIR filter (gain, fractional delay, a little
                    coupling) by least squares on the last second, and subtracts it from each new block. What is left
                    is everyone else: the game, the music, the other people in the call.

Subtraction is never trusted alone: when the cancelled block still holds less than half the energy the echo had, the
block counts as "that was STAR" and is dropped, so a leftover of her own words is never transcribed. Another voice that
is as loud as hers during her speech passes through.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np

from .audio import RATE, pcm_to_float, rms


class PlaybackReference:
    def __init__(self, keep_seconds: float = 40.0, clock=None) -> None:
        self.clock = clock or time.monotonic
        self.keep = int(keep_seconds * RATE)
        self._segments: list[tuple[int, np.ndarray]] = []     # (absolute start index at 16 kHz, samples)
        self._end = 0
        self._lock = threading.Lock()

    def add(self, pcm: bytes, sample_rate: int) -> None:
        from ..voice.engines import resample
        x = pcm_to_float(pcm)
        if sample_rate != RATE:
            x = resample(x, sample_rate, RATE)
        if not len(x):
            return
        now = int(round(self.clock() * RATE))
        with self._lock:
            start = max(now, self._end)
            self._segments.append((start, np.asarray(x, dtype=np.float32)))
            self._end = start + len(x)
            floor = now - self.keep
            self._segments = [(s, a) for s, a in self._segments if s + len(a) > floor]

    def stop(self) -> None:
        """The speaker was silenced: nothing queued will play."""
        now = int(round(self.clock() * RATE))
        with self._lock:
            kept = []
            for start, samples in self._segments:
                if start >= now:
                    continue
                kept.append((start, samples[: max(0, now - start)]))
            self._segments, self._end = kept, min(self._end, now)

    def samples(self, i0: int, i1: int) -> np.ndarray:
        """The reference over absolute 16 kHz indexes [i0, i1); zeros where nothing was playing."""
        out = np.zeros(max(0, i1 - i0), dtype=np.float32)
        with self._lock:
            for start, samples in self._segments:
                a, b = max(i0, start), min(i1, start + len(samples))
                if a < b:
                    out[a - i0:b - i0] = samples[a - start:b - start]
        return out

    def index_now(self) -> int:
        return int(round(self.clock() * RATE))

    def playing(self, lookback: float = 3.0) -> bool:
        """Was anything queued to play in the last `lookback` seconds, or is still queued?"""
        with self._lock:
            return bool(self._segments) and self._end > self.index_now() - int(lookback * RATE)


class ReferenceSpeaker:
    """Speaker wrapper: everything it plays and stops is recorded in the reference, then passed on unchanged."""

    def __init__(self, speaker, reference: PlaybackReference) -> None:
        self._speaker, self.reference = speaker, reference

    def play(self, pcm: bytes, sample_rate: int) -> None:
        self.reference.add(pcm, sample_rate)
        self._speaker.play(pcm, sample_rate)

    def stop(self) -> None:
        self.reference.stop()
        self._speaker.stop()

    def __getattr__(self, name):                      # reset, pending_seconds, played_seconds, level, close...
        return getattr(self._speaker, name)


@dataclass
class CancelInfo:
    echo_rms: float = 0.0          # level of what was subtracted
    residual_rms: float = 0.0
    own_voice: bool = False        # the whole block is STAR herself: do not listen to it


class EchoCanceller:
    def __init__(self, reference: PlaybackReference, *, taps: int = 96, history: float = 1.0, max_lag: float = 0.6,
                 refresh: float = 0.4, min_corr: float = 0.25, clock=None) -> None:
        self.reference = reference
        self.clock = clock or time.monotonic
        self.taps, self.half = int(taps), int(taps) // 2
        self.history, self.max_lag = int(history * RATE), int(max_lag * RATE)
        self.refresh, self.min_corr = refresh, min_corr
        self._x = np.zeros(0, dtype=np.float32)           # recent input
        self._count = 0                                   # input samples seen: this stream's clock
        self._shift: int | None = None                    # reference index = input index + shift
        self._w: np.ndarray | None = None
        self._last_fit = float("-inf")
        self._active_start: int | None = None             # input index where the reference became audible
        self._fits = 0
        self.lag_seconds: float | None = None
        self.explained = 0.0

    def _rows(self, s0: int, s1: int, shift: int) -> np.ndarray:
        """Row n holds the reference taps that make up the echo of input sample s0 + n."""
        a = s0 + shift + self.half - (self.taps - 1)
        r = self.reference.samples(a, s1 + shift + self.half)
        return np.lib.stride_tricks.sliding_window_view(r, self.taps)

    def process(self, frame: np.ndarray, now: float | None = None) -> tuple[np.ndarray, CancelInfo]:
        now = self.clock() if now is None else now
        s0, s1 = self._count, self._count + len(frame)
        self._count = s1
        self._x = np.concatenate([self._x, frame])[-self.history:]
        if self._shift is None:
            self._shift = int(round(now * RATE)) - s1
        if not self.reference.playing():
            self._w, self._active_start, self._fits = None, None, 0
            return frame, CancelInfo(residual_rms=rms(frame))
        if self._active_start is None:
            self._active_start = s0
        # Fit as soon as 130 ms are there, every 150 ms while the fit is young, then every `refresh` seconds.
        every = self.refresh if self._fits >= 4 else 0.15
        if now - self._last_fit >= every and len(self._x) >= int(0.13 * RATE):
            self._last_fit = now
            self._fit(now)
        if self._w is None and s1 - self._active_start < int(0.16 * RATE):
            return frame * 0.0, CancelInfo(own_voice=True)    # her first syllable, before the filter exists
        echo_rms = 0.0
        out = frame
        if self._w is not None:
            echo = self._rows(s0, s1, self._shift) @ self._w
            out = frame - echo.astype(np.float32)
            echo_rms = rms(echo)
        residual = rms(out)
        own = echo_rms > 0.002 and residual < 0.5 * echo_rms
        return out, CancelInfo(echo_rms, residual, own)

    def _fit(self, now: float) -> None:
        x = self._x
        n = len(x)
        s1 = self._count
        s0 = s1 - n
        anchor = int(round(now * RATE)) - s1               # where the two clocks say the shift is
        lo = anchor - self.max_lag
        ahead = int(0.1 * RATE)
        r = self.reference.samples(s0 + lo, s1 + anchor + ahead)
        if float(np.max(np.abs(r), initial=0.0)) < 1e-4 or rms(x) < 1e-5:
            self._w = None
            return
        size = 1 << int(np.ceil(np.log2(len(r) + n)))
        cc = np.fft.irfft(np.fft.rfft(r, size) * np.conj(np.fft.rfft(x, size)), size)[: len(r) - n + 1]
        energy = np.concatenate([[0.0], np.cumsum(np.square(r, dtype=np.float64))])
        seg = energy[n:n + len(cc)] - energy[:len(cc)]
        ncc = cc / (np.sqrt(seg * float(np.sum(np.square(x, dtype=np.float64)))) + 1e-12)
        ncc[seg < 1e-3 * float(seg.max())] = 0.0           # a window with no reference in it proves nothing
        best = int(np.argmax(ncc))
        if ncc[best] < self.min_corr:
            self._w = None
            return
        shift = lo + best
        rows = self._rows(s0, s1, shift)
        ata = rows.T @ rows
        ata[np.diag_indices_from(ata)] += 1e-4 * float(np.trace(ata)) / self.taps + 1e-9
        w = np.linalg.solve(ata, rows.T @ x)
        echo = rows @ w
        explained = 1.0 - float(np.sum(np.square(x - echo))) / (float(np.sum(np.square(x))) + 1e-12)
        self.explained = explained
        if explained < 0.1:
            self._w = None
            return
        self._shift, self._w = shift, w.astype(np.float32)
        self._fits += 1
        self.lag_seconds = (anchor - shift) / RATE
