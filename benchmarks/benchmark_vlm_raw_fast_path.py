"""Synthetic, offline SHA-256 RGB fast-path vs JPEG identical-frame baseline.

Run from the repository root:
    PYTHONPATH=. python benchmarks/benchmark_vlm_raw_fast_path.py

No screen capture, real model inference, game, OBS, microphone, filesystem
output or private pixels. Changed-frame responses use a fake local callback.
Numbers cover host CPU preprocessing, NOT neural inference.
"""
from __future__ import annotations

import json
import math
import statistics
from time import perf_counter_ns

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * fraction) - 1]


def measure(width: int = 1280, height: int = 720, repeats: int = 48):
    if not (128 <= width <= 1920 and 96 <= height <= 1080 and 20 <= repeats <= 120):
        raise ValueError("bounded synthetic benchmarking only")
    # Immutable, synthetic RGB frames with no user content. Each worker has
    # an independent initial JPEG reference.
    rgb = bytes((36, 58, 76)) * (width * height)
    scenes = {
        "exact_static": (rgb,),
        "changed_every_second_frame": (rgb, bytes((36, 58, 77)) * (width * height)),
    }
    outcomes = {}
    reply = json.dumps({"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps({"findings": [{
            "kind": "scene_change", "region": "world", "confidence": 0.8,
        }]})
    }}]}).encode()
    for scenario, images in scenes.items():
        for label, fast in (("jpeg_identical_gate", False), ("raw_sha256_gate", True)):
            calls = []
            def transport(_):
                calls.append(True)
                if scenario == "exact_static":
                    raise AssertionError("static synthetic frames must not invoke inference")
                return 200, reply
            worker = LocalLlamaComparisonWorker(
                model="offline-no-model", skip_identical=True,
                raw_exact_fast_path=fast, transport=transport,
            )
            worker.enable(owner_approved=True, local_model_approved=True)
            assert worker(CapturedVisionFrame(memoryview(images[0]), width, height, 1000)).succeeded
            durations = []
            for i in range(repeats):
                pixels = images[0] if scenario == "exact_static" else images[(i + 1) % 2]
                frame = CapturedVisionFrame(memoryview(pixels), width, height, 1500 + 500 * i)
                began = perf_counter_ns()
                report = worker(frame)
                durations.append((perf_counter_ns() - began) / 1_000_000)
                assert report.stopped and report.succeeded
                if scenario == "exact_static":
                    assert report.perception is None
            meta = worker.metrics()
            assert meta["requests"] == len(calls)
            if scenario == "exact_static":
                assert meta["requests"] == 0 and meta["identical_pairs_skipped"] == repeats
            outcomes[f"{scenario}_{label}"] = {
                "median_ms": round(statistics.median(durations), 3),
                "p95_ms": round(percentile(durations, .95), 3),
                "raw_fast_skips": meta["raw_exact_fast_skips"],
                "simulated_model_calls": meta["requests"],
            }
            worker.disable()
    base = outcomes["exact_static_jpeg_identical_gate"]["median_ms"]
    quick = outcomes["exact_static_raw_sha256_gate"]["median_ms"]
    return {
        "scope": "synthetic exact-static and alternating RGB; CPU preprocessing with fake VLM reply; no gameplay",
        "resolution": f"{width}x{height}",
        "samples_per_configuration": repeats,
        "variants": outcomes,
        "exact_static_median_cpu_ratio": round(base / quick, 2) if quick > 0 else None,
    }


if __name__ == "__main__":
    print(json.dumps(measure(), indent=2, sort_keys=True))
