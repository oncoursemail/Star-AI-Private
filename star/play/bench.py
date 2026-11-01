"""Latency bench for the play loop on fake frames (and, with --real-capture, this PC's real screen grab).

    python -m star.play.bench [--frames 300] [--size 1280x720] [--real-capture] [--concurrency]

compute    every stage of one fast tick on a synthetic obby frame, back to back: frame make -> colour detect ->
           decide -> human-input planning (machine latency only; the deliberate human reaction delay is separate)
human      the deliberate delays the input layer adds (reaction time, aim time) - the point is to be human, not fast
concurrency  the fast loop at 20 Hz on its own thread while a slow "planner" takes 0.8 s per call on another:
           tick-interval p50/p95 shows whether talking/planning disturbs play
real_capture GDI (Pillow ImageGrab) grab of a region of the real screen (CPU; dxcam would be the fast path)
Prints one JSON object. Uses one CPU core, no model, no GPU.
"""
from __future__ import annotations

import argparse
import json
import random
import threading
import time

from .capture import FakeFrames
from .humanlike import Actuator, HumanInput, HumanProfile, RecordingSink, movement_time, reaction_delay
from .loop import FastLoop, InputActor, LatencyStats, SlowLoop
from .planner import LLMPlanner
from .roblox import ObbyController, ScreenObserver


def obby_frame(index: int, width: int = 1280, height: int = 720):
    """Sky, a green platform drifting left/right, a red kill brick, sometimes a gold checkpoint pad."""
    import numpy as np
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:] = (110, 160, 230)
    image[int(height * 0.75):] = (90, 90, 90)
    x = int(width * (0.3 + 0.4 * ((index % 120) / 120)))
    image[int(height * 0.45):int(height * 0.6), x:x + width // 6] = (60, 210, 60)
    image[int(height * 0.9):, int(width * 0.4):int(width * 0.6)] = (60, 210, 60)
    if index % 3 == 0:
        image[int(height * 0.78):int(height * 0.86), int(width * 0.45):int(width * 0.55)] = (230, 30, 30)
    if index % 50 == 0:
        image[int(height * 0.93):, int(width * 0.35):int(width * 0.65)] = (240, 200, 40)
    return image


class _SlowBrain:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def stream(self, messages):
        time.sleep(self.delay)
        yield '{"goal": "advance", "say": "okay, next jump!"}'


def bench_compute(frames: int, width: int, height: int) -> dict:
    rng = random.Random(7)
    pre = [obby_frame(i, width, height) for i in range(min(frames, 120))]
    controller = ObbyController()
    observer = ScreenObserver(FakeFrames(lambda i: pre[i % len(pre)]), controller.detector())
    actuator = Actuator(RecordingSink())
    fast = FastLoop(observer, controller, InputActor(HumanInput(rng=rng), actuator), hz=1000)
    for _ in range(frames):
        fast.tick()
        actuator.pump(time.perf_counter() + 10)            # fire everything planned (no waiting in the bench)
    return {"frames": frames, "size": f"{width}x{height}", "stages_ms": fast.stats.summary(),
            "input_events_fired": actuator.fired}


def bench_human(samples: int = 5000) -> dict:
    rng, p = random.Random(3), HumanProfile()
    stats = LatencyStats(keep=samples)
    for _ in range(samples):
        stats.add("reaction", reaction_delay(rng, p) * 1000)
    for dist, width in ((100, 40), (400, 40), (800, 20)):
        stats.add(f"aim_{dist}px_w{width}", movement_time(dist, width, p) * 1000)
    return stats.summary()


def bench_concurrency(seconds: float, width: int, height: int) -> dict:
    pre = [obby_frame(i, width, height) for i in range(60)]
    controller = ObbyController()
    observer = ScreenObserver(FakeFrames(lambda i: pre[i % len(pre)]), controller.detector())
    actuator = Actuator(RecordingSink())
    fast = FastLoop(observer, controller, InputActor(HumanInput(rng=random.Random(5)), actuator), hz=20)
    stamps: list[float] = []
    original = fast.tick

    def tick() -> None:
        stamps.append(time.perf_counter())
        original()

    fast.tick = tick                                    # type: ignore[method-assign]
    said: list[str] = []
    slow = SlowLoop(LLMPlanner(_SlowBrain(0.8), controller.goals, deadline_s=5), fast,
                    speak=lambda text: said.append(text) or True, period=0.2, min_say_gap_s=0)
    threads = [threading.Thread(target=t, daemon=True) for t in (fast.run, slow.run, actuator.run)]
    for thread in threads:
        thread.start()
    time.sleep(seconds)
    for part in (slow, fast, actuator):
        part.stop()
    for thread in threads:
        thread.join(3)
    gaps = LatencyStats()
    for a, b in zip(stamps, stamps[1:]):
        gaps.add("tick_interval", (b - a) * 1000)
    return {"seconds": seconds, "fast_ticks": len(stamps), "planner_calls": slow.planner.calls, "spoken": len(said),
            "fast_overruns": fast.overruns, **gaps.summary()}


def bench_real_capture(frames: int, width: int, height: int) -> dict:  # pragma: no cover - reads the real screen
    from .capture import GdiCapture
    source = GdiCapture((0, 0, width, height))
    stats = LatencyStats()
    detector = ObbyController().detector()
    for _ in range(frames):
        t0 = time.perf_counter()
        frame = source.grab()
        assert frame is not None          # the synthetic source always yields a frame
        t1 = time.perf_counter()
        detector.detect(frame.image)
        t2 = time.perf_counter()
        stats.add("gdi_grab", (t1 - t0) * 1000)
        stats.add("detect", (t2 - t1) * 1000)
        stats.add("grab_plus_detect", (t2 - t0) * 1000)
    return stats.summary()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.play.bench")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--size", default="1280x720")
    parser.add_argument("--real-capture", action="store_true")
    parser.add_argument("--concurrency", type=float, default=0.0, help="seconds of the threaded 20 Hz + planner run")
    args = parser.parse_args(argv)
    width, height = (int(v) for v in args.size.lower().split("x"))
    out = {"compute": bench_compute(args.frames, width, height), "human_ms": bench_human()}
    if args.concurrency:
        out["concurrency"] = bench_concurrency(args.concurrency, width, height)
    if args.real_capture:
        out["real_capture"] = bench_real_capture(min(args.frames, 100), width, height)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
