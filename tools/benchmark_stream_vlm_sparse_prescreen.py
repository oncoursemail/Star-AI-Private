"""Synthetic paired-frame CPU benchmark (no local model, camera, OBS or gameplay).

Example:
 PYTHONPATH=. python tools/benchmark_stream_vlm_sparse_prescreen.py --frames 48

Compare opt-in full RGB SHA on every frame to the additional opt-in 64-byte
negative prescreen. Full SHA is still mandatory before any raw-identity skip.
This benchmark intentionally does *not* claim model inference or FPS gains.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame

WIDTH, HEIGHT = 1280, 720
_FRAME_SIZE = WIDTH * HEIGHT * 3
_RESPONSE = json.dumps({"choices": [{"finish_reason": "stop",
                                     "message": {"content": json.dumps({
                                         "findings": [{"kind": "unknown",
                                                       "region": "world",
                                                       "confidence": 0.51}]
                                     })}}]}).encode()


def make_views(frames: int, scenario: str) -> list[CapturedVisionFrame]:
    # Precompute synthetic 720p bytes OUTSIDE the timed region.
    colors = [bytes((20, 60, 100)), bytes((180, 70, 20)),
              bytes((55, 210, 110)), bytes((201, 22, 190))]
    pixel_buffers = [memoryview(color * (WIDTH * HEIGHT)) for color in colors]
    result = []
    for i in range(frames):
        if scenario == "static":
            index = 0
        elif scenario == "active":
            index = i % len(pixel_buffers)
        elif scenario == "mixed":
            index = (i % len(pixel_buffers)) if i < frames // 2 else 3
        else:
            raise ValueError(scenario)
        result.append(CapturedVisionFrame(pixel_buffers[index], WIDTH, HEIGHT,
                                          1000 + i * 200))
    return result


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, int((len(ordered) * 0.95 + .99999)) - 1)]


def one_trial(frames: list[CapturedVisionFrame], *, sparse: bool) -> dict[str, float | int]:
    host = LocalLlamaComparisonWorker(
        model="synthetic-test", skip_identical=True,
        raw_exact_fast_path=True, raw_sparse_prescreen=sparse,
        transport=lambda _: (200, _RESPONSE),
    )
    host.enable(owner_approved=True, local_model_approved=True)
    elapsed = []
    for frame in frames:
        start = time.perf_counter_ns()
        host(frame)
        elapsed.append((time.perf_counter_ns() - start) / 1e6)
    metrics = host.metrics()
    return {
        "median_ms": round(statistics.median(elapsed), 3),
        "p95_ms": round(p95(elapsed), 3),
        "sum_ms": round(sum(elapsed), 3),
        "raw_sha_computations": metrics["raw_sha_computations"],
        "sparse_mismatch_hash_skips": metrics["sparse_mismatch_hash_skips"],
        "raw_exact_fast_skips": metrics["raw_exact_fast_skips"],
        "model_requests_stubbed": metrics["requests"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=48)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if not 8 <= args.frames <= 200 or not 1 <= args.repeats <= 8:
        parser.error("frames must be 8..200, repeats 1..8")
    datasets = {scenario: make_views(args.frames, scenario)
                for scenario in ("static", "active", "mixed")}
    trials = [(scenario, sparse, n)
              for scenario in datasets for sparse in (False, True)
              for n in range(args.repeats)]
    random.Random(25).shuffle(trials)
    out = {}
    for scenario, sparse, _ in trials:
        key = scenario + ("/sparse" if sparse else "/baseline")
        out.setdefault(key, []).append(one_trial(datasets[scenario], sparse=sparse))
    for scenario in datasets:
        print(scenario)
        for sparse in (False, True):
            key = scenario + ("/sparse" if sparse else "/baseline")
            values = out[key]
            print(" ", key, json.dumps({
                "median_ms": round(statistics.median(v["median_ms"] for v in values), 3),
                "p95_ms": round(statistics.median(v["p95_ms"] for v in values), 3),
                "sum_ms": round(statistics.median(v["sum_ms"] for v in values), 3),
                "raw_sha_computations": values[-1]["raw_sha_computations"],
                "sparse_mismatch_hash_skips": values[-1]["sparse_mismatch_hash_skips"],
                "raw_exact_fast_skips": values[-1]["raw_exact_fast_skips"],
                "model_requests_stubbed": values[-1]["model_requests_stubbed"],
            }, sort_keys=True))
    print("Scope: synthetic RGB frames, PIL/JPEG CPU and stub transport only;"
          " no local VLM, OBS, Windows game capture, TTS or gameplay FPS.")


if __name__ == "__main__":
    main()
