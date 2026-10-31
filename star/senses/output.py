"""Glitch-free playback: a jitter buffer with click-free starts, stops and joins, behind the Speaker interface.

PlaybackBuffer is the device-side half and is pure (the sound card callback calls read(); the call code calls
write()/stop()), so everything below is tested with a jittery fake producer and a fake clock.

  prefill        playback starts when `prefill_ms` of audio is queued, or when the first chunk has waited that long
                 (so a short word is never stuck waiting), never on a single tiny chunk of a long sentence
  underrun       if the callback finds less than a block queued, the tail is faded out over `fade_ms` instead of
                 stopping dead, the gap is recorded, and playback only resumes after the buffer has refilled, with a
                 fade-in. Gaps are counted separately from the normal end of a reply
  stop()         fades what is queued out over `fade_ms` inside the next callback (one device block, ten
                 milliseconds) and drops the rest: she is silent well inside 200 ms of an interruption, with no click
  chunk joins    when the first sample of a chunk jumps further from the last sample of the previous one than the signal's own
                 step there (plus a threshold), the first
                 `join_ms` of the new chunk are blended from the old value; chunks that already join smoothly are not
                 touched, so no audio is altered or lost where it is already clean
  resampling     chunks are resampled once, on the way in, with odd-reflected padding (an FFT resample of a bare chunk
                 rings at both ends, which would be an audible tick at every sentence)
"""
from __future__ import annotations

import collections
import threading
import time

import numpy as np

from .audio import pcm_to_float


def resample_chunk(x: np.ndarray, source_rate: int, target_rate: int, pad: int = 512) -> np.ndarray:
    """Band-limited resampling of one chunk without edge ringing (odd-reflect-pad, FFT resample, trim)."""
    if source_rate == target_rate or not len(x):
        return x.astype(np.float32)
    from ..voice.engines import resample
    p = min(pad, max(1, len(x) - 1))
    # odd reflection about each end point keeps both the value and the slope continuous (an even one leaves a kink)
    padded = np.concatenate([2 * x[0] - x[1:p + 1][::-1], x, 2 * x[-1] - x[-p - 1:-1][::-1]])
    out = resample(padded, source_rate, target_rate)
    lead = int(round(p * target_rate / source_rate))
    want = int(round(len(x) * target_rate / source_rate))
    return out[lead:lead + want].astype(np.float32)


class PlaybackBuffer:
    def __init__(self, rate: int = 24000, *, prefill_ms: int = 60, fade_ms: float = 4.0, join_ms: float = 1.5,
                 join_threshold: float = 0.05, clock=time.monotonic) -> None:
        self.rate = rate
        self.prefill = int(rate * prefill_ms / 1000)
        self.fade = max(2, int(rate * fade_ms / 1000))
        self.join = max(2, int(rate * join_ms / 1000))
        self.join_threshold = join_threshold
        self.clock = clock
        self._lock = threading.Lock()
        self._chunks: collections.deque[np.ndarray] = collections.deque()
        self._queued = 0
        self._first_write: float | None = None
        self._playing = False
        self._fade_in = False
        self._tail: np.ndarray | None = None  # the faded-out remainder of what was playing when stop() came
        self._last_in = 0.0                  # last sample written, for join smoothing
        self._gap_start: float | None = None
        self._played = 0
        self._levels: collections.deque = collections.deque(maxlen=64)
        self.gaps: list[float] = []          # seconds of silence each time playback ran dry and later resumed
        self.underruns = 0                   # times the callback found the queue short while playing
        self.joins_smoothed = 0

    # -- producer side -------------------------------------------------------------------------
    def write(self, pcm: bytes, rate: int | None = None) -> None:
        x = pcm_to_float(pcm)
        if rate and rate != self.rate:
            x = resample_chunk(x, rate, self.rate)
        if not len(x):
            return
        with self._lock:
            tail = self._chunks[-1][-1] if self._chunks else (self._last_in if self._playing else 0.0)
            if self._queued or self._playing:
                local = abs(float(x[1]) - float(x[0])) if len(x) > 1 else 0.0       # the signal's own step here
                if abs(float(x[0]) - float(tail)) > self.join_threshold + 2.0 * local:
                    k = min(self.join, len(x))
                    ramp = np.linspace(0.0, 1.0, k, endpoint=False, dtype=np.float32)
                    x = x.copy()
                    x[:k] = tail * (1.0 - ramp) + x[:k] * ramp
                    self.joins_smoothed += 1
            self._last_in = float(x[-1])
            self._chunks.append(x)
            self._queued += len(x)
            if self._first_write is None:
                self._first_write = self.clock()

    def stop(self) -> None:
        """Silence now: what was about to play is faded out over fade_ms, everything else is dropped at once, so
        audio written after stop() (the next reply) can never be preceded by the old one."""
        with self._lock:
            if self._playing and self._queued:
                head = np.zeros(min(self.fade, self._queued), dtype=np.float32)
                self._take(len(head), head)
                head *= np.linspace(1.0, 0.0, len(head), dtype=np.float32)
                self._tail = head
            self._chunks.clear()
            self._queued = 0
            self._playing, self._first_write, self._gap_start = False, None, None

    def reset(self) -> None:
        with self._lock:
            self._played = 0

    def pending_seconds(self) -> float:
        with self._lock:
            return self._queued / self.rate

    def played_seconds(self) -> float:
        with self._lock:
            return self._played / self.rate

    def level(self) -> float:
        cutoff = self.clock() - 0.4
        return max((v for t, v in list(self._levels) if t >= cutoff), default=0.0)

    # -- device side ---------------------------------------------------------------------------
    def read(self, frames: int) -> np.ndarray:
        """Exactly `frames` float32 samples for the sound card callback; silence when there is nothing to play."""
        out = np.zeros(frames, dtype=np.float32)
        with self._lock:
            if self._tail is not None:
                k = min(frames, len(self._tail))
                out[:k] = self._tail[:k]
                self._tail = self._tail[k:] if k < len(self._tail) else None
                if self._tail is not None and not len(self._tail):
                    self._tail = None
                self._played += k
                self._record(out)
                return out
            if not self._playing:
                waited = (self.clock() - self._first_write) if self._first_write is not None else 0.0
                if self._queued and (self._queued >= self.prefill or waited >= self.prefill / self.rate):
                    self._playing, self._fade_in = True, True
                    if self._gap_start is not None:
                        self.gaps.append(self.clock() - self._gap_start)
                        self._gap_start = None
                else:
                    return out
            got = self._take(frames, out)
            if self._fade_in and got:
                k = min(self.fade, got)
                out[:k] *= np.linspace(0.0, 1.0, k, endpoint=False, dtype=np.float32)
                self._fade_in = False
            if got < frames:                 # ran dry: fade the tail out instead of cutting it
                if got:
                    k = min(self.fade, got)
                    out[got - k:got] *= np.linspace(1.0, 0.0, k, dtype=np.float32)
                self._playing, self._first_write = False, None
                self._gap_start = self.clock()
                self.underruns += 1
            self._played += got
            self._record(out)
        return out

    def _take(self, n: int, out: np.ndarray) -> int:
        got = 0
        while got < n and self._chunks:
            chunk = self._chunks[0]
            k = min(n - got, len(chunk))
            out[got:got + k] = chunk[:k]
            got += k
            if k == len(chunk):
                self._chunks.popleft()
            else:
                self._chunks[0] = chunk[k:]
        self._queued -= got
        return got

    def _record(self, block: np.ndarray) -> None:
        if len(block):
            self._levels.append((self.clock(), float(np.sqrt(np.mean(block * block)))))

    @property
    def glitch_gaps(self) -> list[float]:
        """Gaps shorter than 0.4 s: the kind that happen mid-sentence. Longer ones are pauses between replies."""
        return [g for g in self.gaps if g < 0.4]


class BufferSpeaker:
    """The Speaker interface over a PlaybackBuffer (rate-converting play())."""

    def __init__(self, buffer: PlaybackBuffer) -> None:
        self.buffer = buffer

    def play(self, pcm: bytes, sample_rate: int) -> None:
        self.buffer.write(pcm, sample_rate)

    def stop(self) -> None:
        self.buffer.stop()

    def reset(self) -> None:
        self.buffer.reset()

    def pending_seconds(self) -> float:
        return self.buffer.pending_seconds()

    def played_seconds(self) -> float:
        return self.buffer.played_seconds()

    def level(self) -> float:
        return self.buffer.level()


class SoundOutput(BufferSpeaker):
    """A real output device (PortAudio): 10 ms blocks pulled from the PlaybackBuffer. Mono or duplicated to stereo.
    `device` is a sounddevice index or name; `rate` should be the device's own rate so Windows does not resample."""

    def __init__(self, device=None, rate: int = 48000, channels: int = 2, block_ms: int = 10,
                 prefill_ms: int = 60) -> None:
        from ..voice.devices import _device, _sounddevice
        sd = _sounddevice()
        super().__init__(PlaybackBuffer(rate, prefill_ms=prefill_ms))
        self.channels, self.rate = channels, rate
        self._stream = sd.OutputStream(samplerate=rate, channels=channels, dtype="float32", device=_device(device),
                                       blocksize=rate * block_ms // 1000, latency="low", callback=self._callback)

    def _callback(self, out, frames, _time, _status) -> None:
        block = self.buffer.read(frames)
        out[:] = block[:, None] if self.channels == 1 else np.repeat(block[:, None], self.channels, axis=1)

    def __enter__(self) -> "SoundOutput":
        self._stream.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
