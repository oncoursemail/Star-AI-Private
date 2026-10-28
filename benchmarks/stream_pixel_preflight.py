"""Synthetic 1080p raw-frame rejection vs CPU fingerprint cost.

Run: PYTHONPATH=. python benchmarks/stream_pixel_preflight.py
No screen capture, real inference, audio, external services, or player data.
The two functions perform DIFFERENT amounts of work; their ratio measures
work avoided when the host cannot admit a request, not neural speedup.
"""
from __future__ import annotations

import json
from statistics import median
from time import perf_counter_ns

from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_observe import FrameCue, ObservationGovernor
from star.stream_vision_host import StreamVisionHost


def benchmark() -> dict[str, float | int | str]:
    width, height = 1920, 1080
    # Synthetic pixel buffer, not a screen image.
    pixels = bytes(width * height * 4)
    regions = (
        (50, 50, 120, 50),
        (1600, 50, 200, 65),
        (50, 950, 180, 80),
        (1500, 900, 200, 90),
    )
    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 2000},
        memory_probe=lambda: (32768, 12000),
        cpu_probe=lambda: (100, 1000),
        clock_ms=lambda: 1000.0,
    )
    # Intentionally never create complete device telemetry.
    host = StreamVisionHost(
        telemetry=hardware, governor=ObservationGovernor(),
        clock_ms=lambda: 1000.0,
    )
    host.enable(owner_approved=True, capture_approved=True)

    def fingerprint():
        return FrameCue.from_pixels(
            1000.0, pixels, width=width, height=height, pixel_format="BGRA",
            focus_regions=regions,
        )

    def preflight():
        return host.consider_pixels(
            pixels, captured_ms=1000.0, width=width, height=height,
            pixel_format="BGRA", focus_regions=regions,
        )

    assert preflight().reason == "trusted_hardware_game_audio_missing"
    for _ in range(4):
        fingerprint()
        preflight()

    def measure(fn, repetitions):
        samples = []
        for _ in range(repetitions):
            start = perf_counter_ns()
            fn()
            samples.append((perf_counter_ns() - start) / 1e6)
        return median(samples)

    fingerprint_ms = measure(fingerprint, 30)
    preflight_ms = measure(preflight, 500)
    return {
        "case": "missing verified device telemetry",
        "frame": "synthetic 1920x1080 BGRA",
        "focus_regions": len(regions),
        "fingerprint_only_median_ms": round(fingerprint_ms, 5),
        "early_rejection_median_ms": round(preflight_ms, 5),
        "work_avoided_per_ineligible_frame_median_ms": round(
            max(0, fingerprint_ms - preflight_ms), 5
        ),
        "suppressed_raw_fingerprints": host.status()["pixel_preflight_skipped"],
        "actual_game_fps_gain_measured": False,
        "neural_inference_gain_measured": False,
    }


if __name__ == "__main__":
    print(json.dumps(benchmark(), sort_keys=True))
