"""Opt-in, synthetic CPU prefilter comparison; NO model/FPS/OBS benchmark.

From repo root:
  PYTHONPATH=. python benchmarks/benchmark_vlm_adaptive_sparse.py

48 pre-built 1280x720 RGB frames per sequence. Stubbed local response; no
network, screenshots, real streaming or owner data. Hardware contention can
substantially change timings. This is an A/B replay, not proof of live gains.
"""
from __future__ import annotations

import json
import statistics
import time

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame

REPETITIONS = 3
WIDTH, HEIGHT = 1280, 720
REPLY = (200, json.dumps({"choices": [{
    "finish_reason": "stop",
    "message": {"content": json.dumps({"findings": [
        {"kind": "scene_change", "region": "world", "confidence": 0.91}
    ]})}
}]}).encode())


def run(colors: tuple[int, ...], adaptive: bool) -> tuple[float, dict[str, int | bool]]:
    worker = LocalLlamaComparisonWorker(
        model="bench-local", skip_identical=True,
        raw_exact_fast_path=True, raw_sparse_prescreen=True,
        adaptive_sparse_prescreen=adaptive, transport=lambda _request: REPLY,
    )
    worker.enable(owner_approved=True, local_model_approved=True)
    # Color buffers exist before timing; per-frame SHA, pixel sample, JPEG,
    # payload assembly and stub callback are all measured.
    rgb = {
        color: memoryview(bytes([color]) * (WIDTH * HEIGHT * 3))
        for color in set(colors)
    }
    start = time.perf_counter_ns()
    for i, color in enumerate(colors):
        frame = CapturedVisionFrame(rgb[color], WIDTH, HEIGHT, 1000 + i * 200)
        report = worker(frame)
        assert report.stopped
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    counts = worker.metrics()
    worker.disable()
    return elapsed, counts


def main() -> None:
    scenarios = {
        "stationary": tuple([30] * 48),
        "moving": tuple((20 + i * 5) % 255 for i in range(48)),
        "alternating_bursts": tuple(
            [30] * 8 + list(range(35, 155, 5))[:12] +
            [90] * 12 + list(range(110, 190, 5))[:8] + [10] * 8
        ),
    }
    print("Scenario | fixed_sparse_ms | adaptive_sparse_ms | delta_% | model_requests | adaptive_samples")
    for name, colors in scenarios.items():
        measurements: dict[bool, list[float]] = {False: [], True: []}
        stats = {}
        for rep in range(REPETITIONS):
            for adaptive in (False, True) if rep % 2 == 0 else (True, False):
                elapsed, metrics = run(colors, adaptive)
                measurements[adaptive].append(elapsed)
                stats[adaptive] = metrics
        fixed = statistics.median(measurements[False])
        auto = statistics.median(measurements[True])
        assert stats[True]["requests"] == stats[False]["requests"]
        assert stats[True]["identical_pairs_skipped"] == stats[False]["identical_pairs_skipped"]
        print(f"{name} | {fixed:.3f} | {auto:.3f} | "
              f"{(auto / fixed - 1) * 100:+.1f}% | "
              f"{stats[True]['requests']} | {stats[True]['sparse_checks']} "
              f"(fixed {stats[False]['sparse_checks']})")


if __name__ == "__main__":
    main()
