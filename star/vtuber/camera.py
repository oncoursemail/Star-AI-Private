"""The camera loop: one thread, a fixed frame clock, and a pipeline of small pieces.

  mouth   = Timeline.at(now)             what her voice is doing at this instant (lipsync.py)
  mood    = mood_source()  (every 1 s)   emotion.current()["avatar"], normally; the face and one-shot cues
  pose    = LiveRig.step(now, mouth)     smoothing, blinks, idle motion, cues (rig.py)
  frame   = AvatarModel.render(pose)     the layered 2D model (model.py)
  sinks   = virtual camera(s), VMC receiver(s)

Frame pacing: frame n is due at start + n/fps; if a frame is late the next due time is moved forward (frames are
dropped, never queued), so a busy PC makes the avatar choppier, never late behind her voice. When the average render time
stays above 85 % of the frame budget the camera first drops model quality to "fast", then halves the frame rate (to a
floor of 10 fps) and records both in stats(). Her game and her voice models come first.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .lipsync import LocalFeed, Timeline
from .expressions import ExpressionTimeline
from .model import AvatarModel
from .rig import LiveRig

log = logging.getLogger("star.vtuber")


class StarCamera:
    def __init__(self, model: AvatarModel, sinks, *, timeline: Timeline | None = None, rig: LiveRig | None = None,
                 fps: float = 30.0, pose_sinks=(), mood_source: Callable[[], dict | None] | None = None,
                 mood_every_s: float = 1.0, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, adaptive: bool = True) -> None:
        self.model = model
        self.sinks = list(sinks)
        self.pose_sinks = list(pose_sinks)
        self.timeline = timeline or Timeline(clock)
        self.rig = rig or LiveRig()
        self.expressions = ExpressionTimeline(clock=clock)
        self.feed = LocalFeed(self.timeline, on_event=self._on_event)
        self.fps = float(fps)
        self.base_fps = float(fps)
        self.mood_source, self.mood_every_s = mood_source, mood_every_s
        self.clock, self.sleep = clock, sleep
        self.adaptive = adaptive
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_mood = 0.0
        self._lock = threading.Lock()
        self._events: list[tuple[str, float, float]] = []
        self._pending_mode: str | None = None
        self._render_ms: list[float] = []
        self.frames = 0
        self.dropped = 0
        self.sink_errors = 0
        self.degraded: list[str] = []
        self.last_pose = None

    # events may come from any thread (a UDP listener): they are applied on the camera thread
    def set_mode(self, mode: str) -> None:
        if mode not in ("normal", "cat", "puppy"):
            raise ValueError("unknown avatar motion mode")
        with self._lock:
            self._pending_mode = mode

    def _on_event(self, kind: str, strength: float) -> None:
        if self._stop.is_set():
            return
        received_at = self.clock()
        self.expressions.event(kind, strength, now=received_at)
        with self._lock:
            if self._stop.is_set():
                self.expressions.clear()
                return
            self._events.append((kind, strength, received_at))
            del self._events[:-16]

    def tick(self, now: float | None = None):
        """Render and send one frame for time `now` (default: the clock). Returns the Pose."""
        now = self.clock() if now is None else now
        with self._lock:
            events, self._events = self._events, []
            mode, self._pending_mode = self._pending_mode, None
        if mode is not None:
            self.rig.mode = mode
        for kind, strength, received_at in events:
            if kind == "owner_interrupt":
                self.rig.neutral(now)
            else:
                self.rig.react(kind, strength, now=received_at)
        if self.mood_source is not None and now >= self._next_mood:
            self._next_mood = now + self.mood_every_s
            try:
                state = self.mood_source()
            except Exception as why:                # a mood problem must never freeze the camera
                log.warning("mood source failed: %s", type(why).__name__)
                state = None
            self.rig.set_mood(state)
        pose = self.rig.step(now, self.timeline.at(now))
        pose = self.expressions.apply(pose, now=now)
        began = self.clock()
        frame = self.model.render(pose)
        for sink in self.sinks:
            try:
                sink.send(frame)
            except Exception as why:
                self.sink_errors += 1
                if self.sink_errors in (1, 10, 100):
                    log.warning("frame sink failed (%s)", type(why).__name__)
        for sink in self.pose_sinks:
            try:
                sink.send_pose(pose)
            except Exception:
                self.sink_errors += 1
        self.frames += 1
        self.last_pose = pose
        self._adapt((self.clock() - began) * 1000.0)
        return pose

    def _adapt(self, ms: float) -> None:
        self._render_ms.append(ms)
        if len(self._render_ms) < 30:
            return
        average = sum(self._render_ms) / len(self._render_ms)
        self._render_ms.clear()
        if not self.adaptive or average < 0.85 * 1000.0 / self.fps:
            return
        if self.model.quality == "high":
            self.model.quality = "fast"
            self.degraded.append(f"quality fast (avg {average:.0f} ms at {self.fps:g} fps)")
        elif self.fps > 10:
            self.fps = max(10.0, self.fps / 2)
            self.degraded.append(f"{self.fps:g} fps (avg {average:.0f} ms)")

    def run(self) -> None:
        """Blocks until stop(). Frame n is due at start + n / fps (re-based when the frame rate changes)."""
        origin, count, rate = self.clock(), 0, self.fps
        while not self._stop.is_set():
            self.tick()
            if self.fps != rate:
                origin, count, rate = self.clock(), 0, self.fps
            count += 1
            due = origin + count / rate
            now = self.clock()
            if now > due:                                   # late: drop what we missed instead of racing to catch up
                behind = int((now - due) * rate)
                self.dropped += behind
                count += behind
                due = origin + count / rate
                continue
            self.sleep(due - now)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, daemon=True, name="star-camera")
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self.expressions.clear()
        with self._lock:
            self._events.clear()
        if self._thread:
            self._thread.join(timeout)
        for sink in [*self.sinks, *self.pose_sinks]:
            try:
                sink.close()
            except Exception:
                pass

    def stats(self) -> dict:
        bound = {rule["param"] for layer in getattr(self.model, "layers", ()) for rule in layer.bind.values()}
        return {"frames": self.frames, "dropped": self.dropped, "fps": self.fps, "quality": self.model.quality,
                "mode": self.rig.mode, "ear_layers_bound": {"ear_left", "ear_right"}.issubset(bound),
                "tail_layer_bound": "tail_sway" in bound,
                "expression": self.expressions.status(),
                "degraded": list(self.degraded), "sink_errors": self.sink_errors}
