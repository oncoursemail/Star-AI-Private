"""Offline microbenchmark: legacy vs. sliding-window expression-cue scanning.

Reports only CPU time spent determining which prevalidated cues apply to each
frame, NOT whole VTuber animation time, voice latency, gaming FPS or model speed.
No network, GPU, OBS, user input, files, or extra dependencies.

Run:
    python scripts/bench_stream_motion_cues.py
"""
from __future__ import annotations

import statistics
import time


def full_scan(frames: tuple[float, ...], cues: tuple[float, ...]) -> tuple[float, int]:
    total = 0.0
    inspected = 0
    for t in frames:
        for at_s in cues:
            inspected += 1
            age = t - at_s
            if 0 <= age <= 1.5:
                total += age
    return total, inspected


def active_window(frames: tuple[float, ...], cues: tuple[float, ...]) -> tuple[float, int]:
    total = 0.0
    inspected = 0
    begin = end = 0
    count = len(cues)
    for t in frames:
        while end < count and cues[end] <= t:
            end += 1
        while begin < end and t - cues[begin] > 1.5:
            begin += 1
        for index in range(begin, end):
            inspected += 1
            age = t - cues[index]
            if 0 <= age <= 1.5:
                total += age
    return total, inspected


def measure(fn, frames: tuple[float, ...], cues: tuple[float, ...], repeats: int = 51) -> float:
    values: list[float] = []
    for _ in range(repeats):
        begin = time.perf_counter()
        for _ in range(30):
            fn(frames, cues)
        values.append((time.perf_counter() - begin) * 1000 / 30)
    return statistics.median(values)


def main() -> None:
    frames = tuple(index / 60 for index in range(901))
    cases = {
        "no cues": (),
        "evenly spaced 32": tuple(index * (15 / 32) for index in range(32)),
        "front-loaded 32": tuple(index * (1.49 / 32) for index in range(32)),
    }
    for label, cues in cases.items():
        old = full_scan(frames, cues)
        new = active_window(frames, cues)
        if abs(old[0] - new[0]) > 1e-8:
            raise AssertionError(f"cue window disagrees with full scan: {label}")
        old_ms = measure(full_scan, frames, cues)
        new_ms = measure(active_window, frames, cues)
        ratio = old_ms / new_ms if new_ms else float("inf")
        print(
            f"{label}: full scan {old_ms:.3f} ms; active window {new_ms:.3f} ms; "
            f"ratio {ratio:.2f}x; inspected ages {old[1]} -> {new[1]}"
        )


if __name__ == "__main__":
    main()
