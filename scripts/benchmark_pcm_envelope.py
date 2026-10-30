"""Reproducible CPU-only benchmark of Star's PCM16->rig envelope path.

Run from repo root: python3 -m scripts.benchmark_pcm_envelope
Reports synthetic audio-processing speed, NOT TTS inference latency or OBS FPS.
"""
from __future__ import annotations

from array import array
import argparse
import math
import statistics
import sys
import time

from star.stream_motion import AudioLevel
from star.stream_pcm_envelope import pcm16_to_envelope


def _legacy_scalar(data: bytes, *, rate: int, channels: int) -> tuple[AudioLevel, ...]:
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    points = [AudioLevel(0., 0.)]
    sample_count = frames = window_index = energy = 0
    boundary = (rate * 20 + 500) // 1000
    for index in range(0, len(samples), channels):
        if channels == 1:
            x = samples[index]
            energy += x * x
            sample_count += 1
        else:
            x, y = samples[index], samples[index + 1]
            energy += x * x + y * y
            sample_count += 2
        frames += 1
        if frames == boundary:
            rms = math.sqrt(energy / sample_count) / 32768.0
            points.append(AudioLevel(frames / rate, 0. if rms < .012
                                     else min(1., rms * 4.)))
            sample_count = energy = 0
            window_index += 1
            boundary = ((window_index + 1) * rate * 20 + 500) // 1000
    if sample_count:
        rms = math.sqrt(energy / sample_count) / 32768.0
        points.append(AudioLevel(frames / rate,
                                 0. if rms < .012 else min(1., rms * 4.)))
    return tuple(points)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=5, choices=range(1, 11))
    parser.add_argument("--repeats", type=int, default=9, choices=range(3, 31))
    args = parser.parse_args()
    rate, channels = 48000, 2
    samples = array("h", (((i * 71) % 62001) - 31000
                           for i in range(rate * args.seconds * channels)))
    if sys.byteorder != "little":
        samples.byteswap()
    data = samples.tobytes()
    baseline = _legacy_scalar(data, rate=rate, channels=channels)
    result = pcm16_to_envelope(data, sample_rate_hz=rate, channels=channels)
    if baseline != result.audio_levels:
        raise SystemExit("FAILED: optimized envelope differs from scalar reference")
    times = {}
    for label, fn in (
        ("legacy", lambda: _legacy_scalar(data, rate=rate, channels=channels)),
        ("optimized", lambda: pcm16_to_envelope(
            data, sample_rate_hz=rate, channels=channels).audio_levels),
    ):
        fn()  # warmup
        trials = []
        for _ in range(args.repeats):
            before = time.perf_counter()
            fn()
            trials.append(1000 * (time.perf_counter() - before))
        times[label] = statistics.median(trials)
    speedup = times["legacy"] / times["optimized"]
    print(f"Python {sys.version.split()[0]}, {args.seconds}s 48kHz stereo PCM16, "
          f"{args.repeats} trials/arm, {len(baseline)} RMS points")
    print(f"legacy median: {times['legacy']:.3f} ms")
    print(f"optimized median: {times['optimized']:.3f} ms")
    print(f"processing speedup: {speedup:.2f}x (not neural inference speed)")


if __name__ == "__main__":
    main()
