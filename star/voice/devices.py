"""Real microphone and loudspeaker through the optional `sounddevice` package (PortAudio).

Not exercised by the automated tests: they use the virtual devices in filecall.py. The speaker here
follows the same Speaker interface as the virtual one, so the call logic above it is identical.
"""
from __future__ import annotations

import collections
import logging
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


class SoundSpeaker:
    """Loudspeaker with an interruptible queue. stop() silences within one audio block (a few ms)."""

    def __init__(self, sample_rate: int = 24000, device=None) -> None:
        sd = _sounddevice()
        self.sample_rate = sample_rate
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._played = 0                    # samples played since reset()
        self._first_output_callback_at: float | None = None  # host monotonic; not proof of hearing
        self._levels: collections.deque = collections.deque(maxlen=64)     # (time, rms) of recent output blocks
        self._stream = sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype="int16", device=_device(device),
                                          callback=self._callback)

    def _callback(self, out, frames, _time, _status) -> None:
        wanted = frames * 2
        with self._lock:
            chunk = bytes(self._buffer[:wanted])
            del self._buffer[:wanted]
            self._played += len(chunk) // 2
            # Only the first non-silent output callback needs a timestamp;
            # all subsequent realtime callbacks avoid the extra scan.
            if self._first_output_callback_at is None and chunk and any(chunk):
                self._first_output_callback_at = time.monotonic()
        out[:len(chunk)] = chunk
        if len(chunk) < wanted:
            out[len(chunk):] = b"\x00" * (wanted - len(chunk))
        if chunk:
            import numpy as np
            block = np.frombuffer(chunk, dtype="<i2").astype(np.float32)
            self._levels.append((time.monotonic(), float(np.sqrt(np.mean(block * block))) / 32768.0))

    def __enter__(self) -> "SoundSpeaker":
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
            self._first_output_callback_at = None

    def first_output_callback_at(self) -> float | None:
        """First nonzero PCM returned by PortAudio's host output callback.

        Same monotonic clock as CallSession's default. This callback can run
        ahead of DAC playback. It is not proof that speakers, OBS, or a
        virtual microphone were audible to anyone.
        """
        with self._lock:
            return self._first_output_callback_at

    def pending_seconds(self) -> float:
        with self._lock:
            return len(self._buffer) / 2 / self.sample_rate

    def played_seconds(self) -> float:
        with self._lock:
            return self._played / self.sample_rate

    def level(self) -> float:
        """Loudest output block of the last 0.4 s (peak-held so the echo gate can compare against it)."""
        cutoff = time.monotonic() - 0.4
        return max((level for at, level in list(self._levels) if at >= cutoff), default=0.0)
