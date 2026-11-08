"""Synthetic CPU-only microbenchmark for STAR's cross-stage game coordinator.

Measures coordinator overhead *only* (no camera, real game, model, OBS,
stream, input device or signed learning result). Do not advertise this output
as faster AI inference or improved gameplay.
Run: python -m scripts.bench_game_realtime_loop --iterations 1000
"""
from __future__ import annotations

import argparse
import json
import math
from statistics import median
from time import perf_counter_ns

from star.game_action_gate import GameActionGate, GameActionHint, GameFrame, GameScope
from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.stream_budget import StreamTelemetry


def _p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(0.95 * len(values)) - 1]


def benchmark(iterations: int = 1000) -> dict[str, int | float | str]:
    """Repeat one safe mocked scene->lease->permit->release transaction."""
    if type(iterations) is not int or not 10 <= iterations <= 100_000:
        raise ValueError("iterations must be 10..100000")
    scope = GameScope("test_game", "version_1", "episode_1")
    loop = RealtimeGameLoop(
        router=GameDeadlineRouter(minimum_samples=5),
        action_gate=GameActionGate(minimum_gap_ms=50, max_per_minute=120),
    )
    loop.start(scope, ["jump"], owner_approved=True)
    telemetry = StreamTelemetry(
        live=False, game_active=True,
        free_vram_mib=4000, total_vram_mib=8192,
        game_fps=60, speech_backlog_ms=0,
    )
    for i in range(1, 6):
        assert loop.record_reactive_latency(
            sample_id=i, duration_ms=45, sample_host_ms=i * 100,
            host_measured=True,
        )
    times_us: list[float] = []
    for i in range(iterations):
        # Synthetic monotonic timestamps 600ms apart keep the existing
        # action/minute budget valid without waiting in real time.
        now = float(1_000 + i * 600)
        capture = now - 40
        frame = GameFrame(
            scope, i + 1, capture, "a" * 64, True, True, 0.95,
        )
        hint = GameActionHint("jump", frame.sequence, frame.evidence_sha256,
                              capture + 5, 30)
        assert loop.record_reactive_latency(
            sample_id=i + 6, duration_ms=45,
            sample_host_ms=now - 5, host_measured=True,
        )
        start = perf_counter_ns()
        lease = loop.offer(
            frame, now_ms=now, host_verified=True,
            telemetry=telemetry,
        )
        if lease.route != "reactive":
            raise RuntimeError(f"simulated route blocked: {lease.reason}")
        permit = loop.finish(
            lease, frame, hint, now_ms=now + 65,
            host_verified=True, telemetry=telemetry,
        )
        if not permit.offered:
            raise RuntimeError(f"simulated permit blocked: {permit.reason}")
        if not loop.claim(
            permit, now_ms=now + 70,
            host_focus_and_permission=True,
        ):
            raise RuntimeError("simulated host claim failed")
        if not loop.release(
            permit, now_ms=now + 75,
            host_confirmed_released=True,
        ):
            raise RuntimeError("simulated host release failed")
        times_us.append((perf_counter_ns() - start) / 1000)
    return {
        "kind": "synthetic_controller_cpu_microbenchmark_not_inference",
        "iterations": iterations,
        "median_us": round(median(times_us), 3),
        "p95_us": round(_p95(times_us), 3),
        "max_us": round(max(times_us), 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(benchmark(args.iterations), sort_keys=True))


if __name__ == "__main__":
    main()
