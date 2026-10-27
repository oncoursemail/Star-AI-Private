"""Reproducible offline CPU microbenchmark for host-selected foveal HUD ROIs.

Run from repo root:
    PYTHONPATH=. python3 benchmarks/stream_foveated_attention.py

Never captures a screen, queries a model, loads a game or streams audio.
Numbers are per FrameCue.from_pixels() operation, not end-to-end FPS or
inference latency. Hardware and Python-runtime specific; avoid ratio claims.
"""
from __future__ import annotations

import argparse
import statistics
import time

from star.stream_observe import FrameCue


def measure(*, repetitions: int = 75, width: int = 1920, height: int = 1080):
    if not 10 <= repetitions <= 500:
        raise ValueError("repetitions must be 10..500")
    if (width, height) != (1920, 1080):
        raise ValueError("benchmark is intentionally fixed at 1920x1080")

    # Flat BGRA frames allow exact repeatability while exercising all raw
    # strides and sampling positions on already-resident page-cache memory.
    raw = bytes((10, 15, 20, 255)) * (width * height)
    game = (0, 0, 1440, height)
    hud = (1440, 0, 480, height)
    crops = tuple(
        (1450 + (index % 2) * 215, 20 + (index // 2) * 220, 80, 50)
        for index in range(8)
    )
    output = {}
    for count in (0, 1, 4, 8):
        region_list = crops[:count]
        samples = []
        for iteration in range(repetitions + 5):
            start = time.perf_counter_ns()
            event = FrameCue.from_pixels(
                1000 + iteration, raw, width=width, height=height,
                pixel_format="BGRA", game_region=game, hud_region=hud,
                focus_regions=region_list,
            )
            elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
            assert len(event.focus_samples) == count
            if iteration >= 5:
                samples.append(elapsed_ms)
        output[count] = {
            "median_ms": statistics.median(samples),
            "p90_ms": sorted(samples)[int(0.9 * (len(samples) - 1))],
        }
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=75)
    args = parser.parse_args()
    print("Synthetic 1920x1080 BGRA; sample 9x8 (+ 2x2 pixels) per ROI")
    for regions, result in measure(repetitions=args.repetitions).items():
        print(f"{regions} focus ROIs: median={result['median_ms']:.4f} ms; "
              f"p90={result['p90_ms']:.4f} ms")
