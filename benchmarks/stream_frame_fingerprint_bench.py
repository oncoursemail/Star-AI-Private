"""Reproducible synthetic CPU-frame fingerprint timing; no game or recording.

Usage: python benchmarks/stream_frame_fingerprint_bench.py --samples 200
SHA-256 is a whole-buffer reference, NOT a perceptually equivalent algorithm.
The median/p95 concern only sampled signatures on existing bytes, never capture,
image decoding, model inference, recognition correctness, voice or game FPS.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from star.frame_fingerprint import visual_fingerprint  # noqa: E402


def timing(fn, count: int) -> tuple[float, float]:
    for _ in range(20):
        fn()
    samples = []
    for _ in range(count):
        begin = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - begin) / 1e6)
    samples.sort()
    return (statistics.median(samples),
            samples[min(len(samples) - 1, (95 * len(samples) + 99) // 100 - 1)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200)
    args = parser.parse_args()
    if not 20 <= args.samples <= 3000:
        parser.error("samples must be within 20..3000")
    for width, height in ((1280, 720), (1920, 1080), (3840, 2160)):
        # Identical synthetic BGRA frames, reused across all samples.
        pixels = bytes((38, 71, 122, 255)) * (width * height)
        local = lambda: visual_fingerprint(
            pixels, width=width, height=height, pixel_format="BGRA",
        )
        whole = lambda: hashlib.sha256(pixels).digest()
        fp50, fp95 = timing(local, args.samples)
        sha50, sha95 = timing(whole, args.samples)
        print(f"{width}x{height}  sampled edge+tone p50={fp50:.4f}ms "
              f"p95={fp95:.4f}ms  SHA256-whole-frame p50={sha50:.4f}ms "
              f"p95={sha95:.4f}ms")
    print("Caution: sampled edge+tone is NOT an exact hash, object detector, "
          "or game-event verifier; synthetic timing is not Windows FPS.")


if __name__ == "__main__":
    main()
