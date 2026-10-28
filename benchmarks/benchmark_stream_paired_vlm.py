"""Reproducible CPU serialization benchmark for Star's optional paired VLM.

Pure synthetic frames, no model, no HTTP, no game, no personal screenshots.
Measures JPEG downsample + JSON/base64 preparation, not token generation or
end-to-end gaming/streaming latency. Run from repository root:
    python -m benchmarks.benchmark_stream_paired_vlm
"""
from __future__ import annotations

from collections.abc import Sequence
from statistics import median
from time import perf_counter

from PIL import Image, ImageDraw

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame


_REPLY = (
    b'{"choices":[{"finish_reason":"stop",'
    b'"message":{"content":"{\\"findings\\":[{\\"kind\\":'
    b'\\"hud_change\\",\\"region\\":\\"hud\\",\\"confidence\\":0.9}]}"}}]}'
)


def synthetic_frame(w: int, h: int, *, at_ms: float, shifted: bool) -> CapturedVisionFrame:
    im = Image.new("RGB", (w, h), (25, 35, 70))
    try:
        draw = ImageDraw.Draw(im)
        for n in range(36):
            left = (n * 173 + (13 if shifted else 0)) % max(1, w - 100)
            top = (n * 67) % max(1, h - 55)
            draw.rectangle((left, top, left + 70, top + 35),
                           fill=((n * 27) % 255, 75, 210))
        return CapturedVisionFrame(
            memoryview(im.tobytes()), w, h, at_ms,
        )
    finally:
        im.close()


def percentile(samples: Sequence[float], p: float) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * p))
    return ordered[index]


def run(*, width: int = 1280, height: int = 720, rounds: int = 12) -> None:
    if not 1 <= rounds <= 200:
        raise ValueError("rounds must be 1..200")
    frames = (
        synthetic_frame(width, height, at_ms=1000, shifted=False),
        synthetic_frame(width, height, at_ms=1600, shifted=True),
    )
    for side in (256, 512, 768):
        payload_bytes = []

        def fake_transport(payload: bytes):
            payload_bytes.append(len(payload))
            return 200, _REPLY

        worker = LocalLlamaComparisonWorker(
            model="local-synthetic-model", max_image_side=side,
            transport=fake_transport,
        )
        worker.enable(owner_approved=True, local_model_approved=True)
        samples = []
        for _ in range(rounds):
            start = perf_counter()
            baseline = worker(frames[0])
            prediction = worker(frames[1])
            samples.append((perf_counter() - start) * 1000)
            assert baseline.stopped and prediction.stopped
        worker.disable()
        print(
            f"{width}x{height} max_side={side}: "
            f"pair CPU p50={median(samples):.2f} ms, "
            f"p95={percentile(samples, .95):.2f} ms, "
            f"max JSON request={max(payload_bytes)} bytes"
        )


if __name__ == "__main__":
    run()
