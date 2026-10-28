"""Reproducible, offline CPU overhead benchmark for opt-in visual recall.

Run:
  python -m tools.benchmark_stream_visual_recall

Synthetic frames only: no game/window capture, model, voice or network.
Numbers measure incremental CPU JPEG storage + inspection, NOT model FPS,
inference tokens/sec, game skill or actual live-streaming performance.
"""
from __future__ import annotations

import json
from io import BytesIO
from statistics import median
from time import perf_counter

from PIL import Image, ImageDraw

from star.stream_visual_recall import VisualRecallHost
from star.stream_windows_game_capture import CapturedVisionFrame, WorkerReport


def _frames(count: int = 30) -> list[CapturedVisionFrame]:
    result = []
    for index in range(count):
        image = Image.new("RGB", (960, 540), (24, 32, 52))
        pen = ImageDraw.Draw(image)
        left = index * 13 % 800
        pen.rectangle((left, 45, left + 90, 125),
                      fill=(30 + index % 180, 220, 45))
        pen.text((35, 350), f"synthetic scene {index:03d}", fill=(220, 230, 240))
        result.append(CapturedVisionFrame(
            memoryview(image.tobytes()), 960, 540, 1000.0 + index * 500,
        ))
        image.close()
    return result


def _ms(func, frames: list[CapturedVisionFrame]) -> list[float]:
    samples = []
    for frame in frames:
        start = perf_counter()
        func(frame)
        samples.append(1000 * (perf_counter() - start))
    return samples


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "median_ms": round(median(samples), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(.95 * len(ordered)))], 3),
    }


def main() -> None:
    frames = _frames()
    passthrough = lambda _: WorkerReport(True, True)
    baseline = _ms(passthrough, frames)
    disabled = VisualRecallHost(passthrough)
    disabled_cost = _ms(disabled, frames)
    history = VisualRecallHost(passthrough, max_frames=5, max_bytes=1000000)
    history.enable(owner_approved=True, game_capture_approved=True)
    active_cost = _ms(history, frames)
    marks = history.recent(now_ms=frames[-1].captured_ms)
    first = perf_counter()
    if marks:
        snapshot = history.inspect(
            marks[-1].frame_id, focus_box=(0, 0, 400, 500),
            now_ms=frames[-1].captured_ms,
            owner_approved=True, inspection_approved=True,
        )
        if snapshot is not None:
            with Image.open(BytesIO(snapshot.jpeg)) as image:
                image.load()
            snapshot.erase()
    inspect_ms = 1000 * (perf_counter() - first)
    output = {
        "scenario": "30 synthetic 960x540 RGB frames with tiny motion",
        "synthetic_worker": _summary(baseline),
        "recall_disabled": _summary(disabled_cost),
        "recall_enabled": _summary(active_cost),
        "inspect_last_roi_ms": round(inspect_ms, 3),
        "cache_bytes_after_30": history.metrics()["bytes_cached"],
        "cached_frames_after_30": history.metrics()["frames_cached"],
        "requests_to_vlm": 0,
    }
    history.disable()
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
