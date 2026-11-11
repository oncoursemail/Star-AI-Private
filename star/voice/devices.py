"""Real microphone and loudspeaker through the optional `sounddevice` package (PortAudio).

Not exercised by the automated tests: they use the virtual devices in filecall.py. The speaker here
follows the same Speaker interface as the virtual one, so the call logic above it is identical.
"""
from __future__ import annotations

import collections
import logging
import math
import queue
import threading
import time

from .pcm import FRAME_SAMPLES, SAMPLE_RATE

log = logging.getLogger(__name__)


def _sounddevice():
    try:
        import sounddevice
    except (ImportError, OSError) as exc:
        log.warning("Audio devices unavailable (%s); install with: pip install -r requirements-voice.txt", exc)
        raise RuntimeError("Voice features are not set up on this computer yet.") from exc
    return sounddevice


def _device(value):
    if value in (None, ""):
        return None
    return int(value) if str(value).isdigit() else str(value)


def _device_output_monotonic(host_now: float, time_info: object) -> float | None:
    """Map PortAudio's scheduled DAC time onto the host monotonic clock.

    This estimates when the first sample in an output callback buffer reaches
    the device DAC. It is not acoustic loopback and cannot prove a remote viewer
    heard the sound.
    """
    try:
        now = float(host_now)
        current = float(getattr(time_info, "currentTime"))
        output = float(getattr(time_info, "outputBufferDacTime"))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(now) or not math.isfinite(current) or not math.isfinite(output):
        return None
    delay = output - current
    # Reject a broken stream-clock mapping rather than inventing a timestamp.
    if delay < -0.05 or delay > 1.0:
        return None
    return now + max(0.0, delay)


def list_devices() -> list[dict]:
    """Microphones and speakers as plain dicts (for the settings screen)."""
    sd = _sounddevice()
    default_in, default_out = sd.default.device
    # Windows lists every device once per audio API (MME, DirectSound, WASAPI, ...). Show only the default
    # API's copies: that is the one the call opens, and it converts sample rates by itself.
    try:
        host_api = sd.query_devices(default_in if default_in >= 0 else default_out)["hostapi"]
    except Exception:
        host_api = None
    found = []
    for index, info in enumerate(sd.query_devices()):
        if host_api is not None and info["hostapi"] != host_api:
            continue
        if info["max_input_channels"] > 0:
            found.append({"index": index, "kind": "input", "name": info["name"], "default": index == default_in})
        if info["max_output_channels"] > 0:
            found.append({"index": index, "kind": "output", "name": info["name"], "default": index == default_out})
    return found


class Microphone:
    """Default (or chosen) microphone as an iterator of 32 ms, 16 kHz, mono PCM16 frames."""

    def __init__(self, device=None) -> None:
        sd = _sounddevice()
        self._frames: queue.Queue = queue.Queue(maxsize=300)       # about 10 s; older audio is dropped beyond that
        self._closed = threading.Event()
        self.dropped = 0
        self._stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES, channels=1, dtype="int16",
                                         device=_device(device), callback=self._callback)

    def _callback(self, data, _frames, _time, _status) -> None:
        try:
            self._frames.put_nowait(bytes(data))
        except queue.Full:
            self.dropped += 1

    def __enter__(self) -> "Microphone":
        self._stream.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        self._closed.set()
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass

    def __iter__(self):
        while not self._closed.is_set():
            try:
                yield self._frames.get(timeout=0.2)
            except queue.Empty:
                continue


def _pcm_rms(pcm: bytes) -> float:
    """RMS for native-endian PCM16. Called by the metrics worker, never the PortAudio callback."""
    if len(pcm) < 2 or len(pcm) % 2:
        return 0.0
    samples = memoryview(pcm).cast("h")
    if not samples:
        return 0.0
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return math.sqrt(mean_square) / 32768.0


_LEVEL_QUEUE_CAPACITY = 64


class SoundSpeaker:
    """Interruptible PortAudio speaker; level metering runs outside the audio callback."""

    def __init__(self, sample_rate: int = 24000, device=None) -> None:
        sd = _sounddevice()
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._played = 0                    # samples played since reset()
        self._first_device_output_at: float | None = None
        self._levels: collections.deque[tuple[float, float]] = collections.deque(maxlen=64)
        self._levels_lock = threading.Lock()
        # A bounded deque keeps telemetry separate from PCM delivery. CPython's deque
        # append/popleft operations are thread-safe and avoid queue.Queue's callback lock.
        self._level_queue: collections.deque[tuple[int, float, bytes]] = collections.deque(
            maxlen=_LEVEL_QUEUE_CAPACITY
        )
        self._level_stop = threading.Event()
        self._level_worker: threading.Thread | None = None
        self._level_submitted_seq = 0
        self._level_processed_seq = 0
        self._level_overflow_until = float("-inf")
        self.dropped_level_blocks = 0
        self._closed = threading.Event()
        self._stream = sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16", device=_device(device),
                                          callback=self._callback)
        self._level_worker = threading.Thread(
            target=self._process_levels, name="star-speaker-levels", daemon=True
        )
        self._level_worker.start()

    def _process_levels(self) -> None:
        """Compute echo-meter RMS away from PortAudio's high-priority callback thread."""
        while True:
            try:
                sequence, at, chunk = self._level_queue.popleft()
            except IndexError:
                if self._level_stop.is_set():
                    return
                time.sleep(0.01)
                continue
            try:
                value = _pcm_rms(chunk)
            except Exception:
                # An unknown meter value must not be mistaken for silence by the echo gate.
                value = 1.0
                self._level_overflow_until = max(self._level_overflow_until, time.monotonic() + 0.4)
            with self._levels_lock:
                self._levels.append((at, value))
                self._level_processed_seq = max(self._level_processed_seq, sequence)

    def _callback(self, out, frames, time_info, _status) -> None:
        wanted = frames * 2
        host_now = time.monotonic()
        with self._lock:
            chunk = bytes(self._buffer[:wanted])
            del self._buffer[:wanted]
            self._played += len(chunk) // 2
            if chunk and self._first_device_output_at is None:
                self._first_device_output_at = _device_output_monotonic(host_now, time_info)
        out[:len(chunk)] = chunk
        if len(chunk) < wanted:
            out[len(chunk):] = b"\x00" * (wanted - len(chunk))
        if chunk:
            # Metering is best-effort and bounded. If the worker falls behind, the
            # oldest meter sample is discarded, never PCM; level() fails conservative.
            if len(self._level_queue) >= _LEVEL_QUEUE_CAPACITY:
                self.dropped_level_blocks += 1
                self._level_overflow_until = max(self._level_overflow_until, host_now + 0.4)
            sequence = self._level_submitted_seq + 1
            self._level_queue.append((sequence, host_now, chunk))
            self._level_submitted_seq = sequence

    def __enter__(self) -> "SoundSpeaker":
        self._stream.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        if self._closed.is_set():
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        self._closed.set()
        self._level_stop.set()
        worker = self._level_worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1.0)

    # -- Speaker interface --------------------------------------------------------------------
    def play(self, pcm: bytes, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            from .engines import float_to_pcm16, pcm16_to_float, resample
            pcm = float_to_pcm16(resample(pcm16_to_float(pcm), sample_rate, self.sample_rate))
        with self._lock:
            self._buffer.extend(pcm)

    def stop(self) -> None:
        with self._lock:
            self._buffer.clear()

    def reset(self) -> None:
        with self._lock:
            self._played = 0
            self._first_device_output_at = None

    def pending_seconds(self) -> float:
        with self._lock:
            return len(self._buffer) / 2 / self.sample_rate

    def played_seconds(self) -> float:
        with self._lock:
            return self._played / self.sample_rate

    def first_device_output_at(self) -> float | None:
        """Host-monotonic estimate of the first non-empty callback buffer's DAC time."""
        with self._lock:
            return self._first_device_output_at

    def level(self) -> float:
        """Peak-held output level; unknown/pending meter data is treated conservatively as audible."""
        now = time.monotonic()
        with self._levels_lock:
            levels = tuple(self._levels)
            processed = self._level_processed_seq
        if self._level_submitted_seq > processed or now < self._level_overflow_until:
            return 1.0
        cutoff = now - 0.4
        return max((value for at, value in levels if at >= cutoff), default=0.0)
