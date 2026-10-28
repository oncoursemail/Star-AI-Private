"""Synthetic comparison of full-window and host-selected ROI VLM preparation.

No real gameplay, HTTP, neural inference, TTS or viewer data. All measured
times are CPU-only and MUST NOT be advertised as end-to-end inference latency.

Run from repo root:
  python -m benchmarks.benchmark_stream_roi_vlm
"""
from __future__ import annotations

from statistics import median
from time import perf_counter

from PIL import Image, ImageDraw

from star.stream_local_vlm import LocalLlamaComparisonWorker
from star.stream_windows_game_capture import CapturedVisionFrame

# Bounded, fixed "unknown" completion from the stub transport only.
_COMPLETION = (
    b'{"choices":[{"finish_reason":"stop","message":'
    b'{"content":"{\\"findings\\":[{\\"kind\\":\\"unknown\\",'
    b'\\"region\\":\\"hud\\",\\"confidence\\":0.5}]}"}}]}'
)


def scene(*, changed: bool = False, size=(1280, 720)) -> bytes:
    image = Image.new("RGB", size, (45, 59, 71))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 12, 450, 90), fill=(30, 33, 45))
    draw.rectangle((30, 30, 370 if not changed else 180, 70),
                   fill=(19, 195, 84))
    draw.rectangle((600, 340, 680, 600), fill=(100, 110, 140))
    return image.tobytes()


def trial(*, focus=None, identical=False, samples=12):
    before = scene()
    after = before if identical else scene(changed=True)
    times = []
    request_sizes = []

    def transport(payload: bytes):
        request_sizes.append(len(payload))
        return 200, _COMPLETION

    worker = LocalLlamaComparisonWorker(
        model="synthetic-stub", transport=transport,
        max_image_side=512, focus_box=focus, skip_identical=True,
    )
    worker.enable(owner_approved=True, local_model_approved=True)
    for i in range(samples):
        start = perf_counter()
        t = 1000.0 + i * 2000
        first = worker(CapturedVisionFrame(memoryview(before), 1280, 720, t))
        second = worker(CapturedVisionFrame(memoryview(after), 1280, 720, t + 500))
        times.append((perf_counter() - start) * 1000)
        assert first.stopped and second.stopped
        assert second.succeeded
    counts = worker.metrics()
    worker.disable()
    return {
        "median_cpu_pair_ms": round(median(times), 3),
        "model_calls": counts["requests"],
        "identical_pairs_skipped": counts["identical_pairs_skipped"],
        "median_request_bytes": int(median(request_sizes)) if request_sizes else 0,
    }


def main():
    print("Synthetic CPU-only paired-image preparation; 1280x720, 12 pairs")
    for name, options in (
        ("full", {}),
        ("focused_hud", {"focus": (0, 0, 400, 300)}),
        ("full_static", {"identical": True}),
        ("focused_static", {"focus": (0, 0, 400, 300), "identical": True}),
    ):
        print(f"{name}: {trial(**options)}")
    print("NOT measured: VLM accuracy, neural inference, Windows FPS or TTS.")


if __name__ == "__main__":
    main()
