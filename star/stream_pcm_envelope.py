"""Low-cost, real PCM16 -> lip-motion envelopes for Star's local VTuber.

An authorized local TTS host supplies the exact PCM16 little-endian bytes that
will be sent to its own output device. This converter deliberately performs NO
capture, microphone monitoring, file access, playback, inference, or streaming.
It does not infer emotions or phonemes. Output is suitable for StarPlayoutClock,
which separately requires a *consumed-device-sample* cursor: planned audio is
never mistaken for audible audio.

The incremental builder accepts arbitrary byte chunk boundaries, stays under
15 seconds, never saves PCM, uses only Python's standard library, and tags
each RMS window at its END to prevent looking ahead of the playback cursor.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
import math
import sys

from .stream_motion import AudioLevel, MAX_AUDIO_SAMPLES, MAX_DURATION_S


@dataclass(frozen=True)
class PcmEnvelope:
    sample_rate_hz: int
    channels: int
    frames: int
    duration_s: float
    audio_levels: tuple[AudioLevel, ...]


class PcmEnvelopeBuilder:
    """Single-writer, bounded PCM16LE converter, never a device or audio sink.

    RMS uses energy from ALL channels, not an average of left/right samples:
    phase-inverted stereo therefore does not collapse into fake silence.
    The gain controls only animation; it never modifies the audio itself.
    """

    def __init__(
        self, *, sample_rate_hz: int, channels: int = 1,
        window_ms: int = 20, gain: float = 4.0,
        noise_floor: float = 0.012,
    ) -> None:
        if type(sample_rate_hz) is not int or not 8000 <= sample_rate_hz <= 192000:
            raise ValueError("PCM sample rate must be 8000..192000 Hz")
        if type(channels) is not int or channels not in (1, 2):
            raise ValueError("PCM channels must be mono or stereo")
        if type(window_ms) is not int or window_ms not in (10, 20, 40):
            raise ValueError("PCM window must be 10, 20, or 40 ms")
        for name, value, lower, upper in (
            ("gain", gain, 0.5, 12.0),
            ("noise_floor", noise_floor, 0.0, 0.20),
        ):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite numeric value")
            if not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}")
        self.rate = sample_rate_hz
        self.channels = channels
        self.window_ms = window_ms
        self.gain = float(gain)
        self.noise_floor = float(noise_floor)
        self._byte_tail = b""
        self._frame_count = 0
        self._window_index = 0
        self._next_frame = self._boundary(1)
        self._sum_squares = 0
        self._count = 0
        self._levels: list[AudioLevel] = [AudioLevel(0.0, 0.0)]
        self._finished = False

    def _boundary(self, index: int) -> int:
        # Fractional-window scheduling prevents drift at 11,025/44,100 Hz.
        return (index * self.rate * self.window_ms + 500) // 1000

    @property
    def frames(self) -> int:
        return self._frame_count

    def _emit(self) -> None:
        assert self._count
        rms = math.sqrt(self._sum_squares / self._count) / 32768.0
        level = 0.0 if rms < self.noise_floor else min(1.0, rms * self.gain)
        self._levels.append(AudioLevel(self._frame_count / self.rate, level))
        if len(self._levels) > MAX_AUDIO_SAMPLES:
            # At 15 s of 10-ms windows, 1500 measured points already fill
            # the legacy planner's budget. Its _audio_at() returns zero before
            # the first timestamp, so dropping ONLY the redundant t=0 silence
            # sentinel cannot create anticipatory movement.
            if self._levels[0] != AudioLevel(0.0, 0.0):
                raise ValueError("too many audio envelope points")
            del self._levels[0]
        self._sum_squares = 0
        self._count = 0

    def feed(self, chunk: bytes) -> int:
        """Accept bounded PCM; arbitrary chunk boundaries may split frames."""
        if self._finished:
            raise RuntimeError("PCM envelope is finalized")
        if type(chunk) is not bytes or len(chunk) > 1_048_576:
            raise ValueError("PCM chunks must be bytes no larger than 1 MiB")
        if not chunk:
            return 0
        data = self._byte_tail + chunk
        frame_bytes = 2 * self.channels
        complete = len(data) // frame_bytes * frame_bytes
        self._byte_tail = data[complete:]
        count_frames = complete // frame_bytes
        if self._frame_count + count_frames > MAX_DURATION_S * self.rate:
            raise ValueError("PCM duration exceeds 15 seconds")
        if not complete:
            return 0
        pcm = array("h")
        pcm.frombytes(data[:complete])
        if sys.byteorder != "little":
            pcm.byteswap()
        if self.channels == 1:
            for sample in pcm:
                self._sum_squares += sample * sample
                self._count += 1
                self._frame_count += 1
                if self._frame_count == self._next_frame:
                    self._emit()
                    self._window_index += 1
                    self._next_frame = self._boundary(self._window_index + 1)
        else:
            for index in range(0, len(pcm), 2):
                left, right = pcm[index], pcm[index + 1]
                self._sum_squares += left * left + right * right
                self._count += 2
                self._frame_count += 1
                if self._frame_count == self._next_frame:
                    self._emit()
                    self._window_index += 1
                    self._next_frame = self._boundary(self._window_index + 1)
        return count_frames

    def finish(self) -> PcmEnvelope:
        """Refuse trailing half-frames; return only metadata and RMS envelopes."""
        if self._finished:
            raise RuntimeError("PCM envelope is already finalized")
        self._finished = True
        if self._byte_tail:
            raise ValueError("truncated final PCM sample/frame")
        if not self._frame_count:
            raise ValueError("PCM audio is empty")
        if self._count:
            self._emit()
        return PcmEnvelope(
            self.rate, self.channels, self._frame_count,
            self._frame_count / self.rate, tuple(self._levels),
        )


def pcm16_to_envelope(
    pcm16le: bytes, *, sample_rate_hz: int, channels: int = 1,
    gain: float = 4.0, noise_floor: float = 0.012,
    window_ms: int = 20,
) -> PcmEnvelope:
    """One-shot adapter for TTS bytes, chunked so the builder stays bounded."""
    if type(pcm16le) is not bytes:
        raise TypeError("expected PCM16LE bytes from an authorized TTS host")
    builder = PcmEnvelopeBuilder(
        sample_rate_hz=sample_rate_hz, channels=channels,
        gain=gain, noise_floor=noise_floor, window_ms=window_ms,
    )
    for offset in range(0, len(pcm16le), 262_144):
        builder.feed(pcm16le[offset:offset + 262_144])
    return builder.finish()
