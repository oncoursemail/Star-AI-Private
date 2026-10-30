"""PCM16 window accelerator parity: no early mouth motion or silent overflow."""
from __future__ import annotations

from array import array
import math
import random
import sys
import unittest
from unittest.mock import patch

from star.stream_motion import AudioLevel
from star.stream_pcm_envelope import PcmEnvelopeBuilder, pcm16_to_envelope


def _pcm(values: list[int]) -> bytes:
    data = array("h", values)
    if sys.byteorder != "little":
        data.byteswap()
    return data.tobytes()


def _scalar_reference(data: bytes, rate: int, channels: int,
                      window_ms: int, gain: float, floor: float
                      ) -> tuple[AudioLevel, ...]:
    """Independent scalar reference copied from the previous PCM algorithm."""
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    levels = [AudioLevel(0, 0)]
    total = 0
    sum_squares = 0
    count = 0
    boundary_index = 1
    boundary = (boundary_index * rate * window_ms + 500) // 1000
    for pos in range(0, len(samples), channels):
        for c in range(channels):
            value = samples[pos + c]
            sum_squares += value * value
            count += 1
        total += 1
        if total == boundary:
            rms = math.sqrt(sum_squares / count) / 32768.0
            levels.append(AudioLevel(total / rate,
                                     0 if rms < floor else min(1., rms * gain)))
            sum_squares = count = 0
            boundary_index += 1
            boundary = (boundary_index * rate * window_ms + 500) // 1000
    if count:
        rms = math.sqrt(sum_squares / count) / 32768.0
        levels.append(AudioLevel(total / rate,
                                 0 if rms < floor else min(1., rms * gain)))
    if len(levels) > 1500:
        levels.pop(0)
    return tuple(levels)


class WindowFastPathTests(unittest.TestCase):
    def test_exact_scalar_parity_for_rates_channels_and_chunking(self) -> None:
        randomizer = random.Random(20261029)
        for rate in (8000, 11025, 24000, 44100, 96000, 192000):
            for channels in (1, 2):
                for window_ms in (10, 20, 40):
                    # Adversarial 16-bit peaks, phase-inverted stereo and an
                    # incomplete final window at non-divisible sample rates.
                    frames = rate // 7 + 17
                    mono = [randomizer.randint(-32768, 32767)
                            for _ in range(frames)]
                    values = ([v for sample in mono for v in
                               (sample, -sample if sample != -32768 else 32767)]
                              if channels == 2 else mono)
                    data = _pcm(values)
                    expected = _scalar_reference(
                        data, rate, channels, window_ms, 4., .012
                    )
                    result = pcm16_to_envelope(
                        data, sample_rate_hz=rate, channels=channels,
                        window_ms=window_ms,
                    )
                    with self.subTest(rate=rate, channels=channels,
                                      window_ms=window_ms):
                        self.assertEqual(result.audio_levels, expected)
                        self.assertEqual(result.frames, frames)
                        self.assertEqual(result.duration_s, frames / rate)
                    # Cross a partial *stereo* frame and many window edges.
                    chunk = 3 if channels == 2 else 7
                    builder = PcmEnvelopeBuilder(
                        sample_rate_hz=rate, channels=channels,
                        window_ms=window_ms,
                    )
                    for start in range(0, len(data), chunk):
                        builder.feed(data[start:start + chunk])
                    self.assertEqual(builder.finish(), result)

    def test_without_sumprod_uses_exact_fallback(self) -> None:
        data = _pcm([-32768, 32767, 0, 100, -101, 777] * 803)
        reference = pcm16_to_envelope(
            data, sample_rate_hz=44100, channels=2, window_ms=10,
        )
        # Exercised on both Python 3.11 (no sumprod) and 3.12+.
        with patch("star.stream_pcm_envelope.math.sumprod", None, create=True):
            fallback = pcm16_to_envelope(
                data, sample_rate_hz=44100, channels=2, window_ms=10,
            )
        self.assertEqual(fallback, reference)

    def test_maximum_window_count_and_replay_guard(self) -> None:
        data = _pcm([0] * (8000 * 15))
        result = pcm16_to_envelope(
            data, sample_rate_hz=8000, window_ms=10,
        )
        self.assertEqual(len(result.audio_levels), 1500)
        self.assertEqual(result.audio_levels[0].at_s, .01)
        self.assertEqual(result.audio_levels[-1].at_s, 15.)
        for sample in result.audio_levels:
            self.assertEqual(sample.rms, 0)
        builder = PcmEnvelopeBuilder(sample_rate_hz=8000)
        builder.feed(data)
        builder.finish()
        with self.assertRaises(RuntimeError):
            builder.feed(data)

    def test_no_future_energy_on_window_boundary(self) -> None:
        # Complete first 20ms of silence, then ONE loud sample in next window.
        result = pcm16_to_envelope(
            _pcm([0] * 160 + [32767]),
            sample_rate_hz=8000, window_ms=20,
        )
        self.assertEqual([point.at_s for point in result.audio_levels],
                         [0., .02, 161 / 8000])
        self.assertEqual(result.audio_levels[1].rms, 0)
        self.assertGreater(result.audio_levels[-1].rms, 0)


if __name__ == "__main__":
    unittest.main()
