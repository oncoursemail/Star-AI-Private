"""Roblox fast layer for one kind of experience: a classic obby (jump-and-run course), played from the screen.

Perception: ColorDetector finds the course's coloured parts in each frame (next platforms, checkpoint pads, red
kill bricks). The profile holds those colours; they differ per experience, so a new obby needs its colours set
(and checked on a few screenshots) before she plays it. Control, at 20 Hz:
  * no target in view: turn the camera (right-drag, Roblox's default camera) to look for one;
  * target far to the side: turn the camera toward it; otherwise hold W and strafe A/D to keep it centred;
  * a kill brick right in front, or the ground ends under the next step: jump (after a human reaction time);
  * standing on a checkpoint pad: report a "checkpoint" moment (voice context + emotion).
Only ordinary keyboard/mouse input to the Roblox window (winput.SendInputSink checks the window is in front).
No memory reading, no scripts or executors, nothing around anti-cheat. Roblox's Terms restrict automated play,
so this carries account risk (accepted by the owner, 2026-10-26).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .humanlike import Hold, Look, Release, Tap
from .percept import Percept
from .planner import Goal

GOALS = {"advance": "follow the course to the next platform",
         "reach_checkpoint": "head for the checkpoint pad in view",
         "look_around": "stop and turn the camera to look around",
         "wait": "stand still (talking, or waiting for a friend)"}


@dataclass(frozen=True)
class ObbyProfile:
    name: str = "obby"
    place_id: int = 0                   # set per experience (from her experience list), 0 = not chosen yet
    window: str = "Roblox"
    colors: dict = field(default_factory=lambda: {
        "platform": ((20, 150, 20), (120, 255, 120)),      # bright green parts (common for "safe" platforms)
        "checkpoint": ((200, 160, 0), (255, 230, 90)),      # yellow/gold spawn pads
        "hazard": ((170, 0, 0), (255, 60, 60)),             # red kill bricks / lava
    })
    turn_px: float = 420.0              # relative mouse pixels for a half-screen camera turn
    search_turn_px: float = 260.0


class ObbyController:
    game = "roblox"
    goals = GOALS

    def __init__(self, profile: ObbyProfile | None = None) -> None:
        self.profile = profile or ObbyProfile()
        self.last_jump = -1e9
        self.last_search = -1e9
        self.last_turn = -1e9
        self.last_checkpoint = -1e9
        self.moving = False
        self._moments: list[str] = []

    def detector(self):
        from .perception import ColorDetector
        return ColorDetector(self.profile.colors)

    def _target(self, p: Percept, goal: Goal):
        """The next thing to head for: ahead of her feet (bottom above the lowest 12 %), biggest first."""
        labels = ("checkpoint",) if goal.name == "reach_checkpoint" else ("checkpoint", "platform")
        ahead = [d for d in p.detections if d.label in labels and d.bottom < p.height * 0.88]
        return max(ahead, key=lambda d: d.area_frac, default=None)

    def _ground_ahead(self, p: Percept) -> bool:
        lo, hi = p.width * 0.4, p.width * 0.6
        return any(d.label in ("platform", "checkpoint") and d.bottom >= p.height * 0.9 and d.x < hi and d.x + d.w > lo
                   for d in p.detections)

    def _hazard_ahead(self, p: Percept) -> bool:
        lo, hi = p.width * 0.35, p.width * 0.65
        return any(d.label == "hazard" and d.bottom >= p.height * 0.7 and d.x < hi and d.x + d.w > lo
                   for d in p.detections)

    def decide(self, p: Percept, goal: Goal, now: float) -> list:
        self._note_checkpoint(p, now)
        if goal.name == "wait":
            return self._stop()
        if goal.name == "look_around":
            if now - self.last_search > 1.5:
                self.last_search = now
                return self._stop() + [Look(self.profile.search_turn_px, 0, drag="right")]
            return self._stop()
        target = self._target(p, goal)
        if target is None:
            if now - self.last_search > 1.2:
                self.last_search = now
                return self._stop() + [Look(self.profile.search_turn_px, 0, drag="right")]
            return self._stop()
        error = (target.cx - p.width / 2) / (p.width / 2)
        if abs(error) > 0.45:
            if now - self.last_turn > 0.5:
                self.last_turn = now
                return self._stop() + [Look(error * self.profile.turn_px, 0, drag="right")]
            return self._stop()
        out: list = [Hold("w", 0.25)]
        self.moving = True
        if error > 0.12:
            out.append(Hold("d", 0.12))
        elif error < -0.12:
            out.append(Hold("a", 0.12))
        if now - self.last_jump > 0.7 and (self._hazard_ahead(p) or not self._ground_ahead(p)):
            self.last_jump = now
            out.append(Tap("space"))
        return out

    def _stop(self) -> list:
        if not self.moving:
            return []
        self.moving = False
        return [Release("w"), Release("a"), Release("d")]

    def _note_checkpoint(self, p: Percept, now: float) -> None:
        lo, hi = p.width * 0.3, p.width * 0.7
        under = any(d.label == "checkpoint" and d.bottom >= p.height * 0.92 and d.x < hi and d.x + d.w > lo
                    and d.area_frac > 0.015 for d in p.detections)
        if under and now - self.last_checkpoint > 8.0:
            self.last_checkpoint = now
            self._moments.append("checkpoint")

    def moments(self, p: Percept) -> list[str]:
        out, self._moments = self._moments, []
        return out

    def describe(self, p: Percept) -> str:
        parts = []
        for label in ("platform", "checkpoint", "hazard"):
            found = p.of(label)
            if found:
                biggest = max(found, key=lambda d: d.area_frac)
                side = "left" if biggest.cx < p.width * 0.4 else "right" if biggest.cx > p.width * 0.6 else "ahead"
                parts.append(f"{label} {side}")
        if p.chat:
            parts.append(f"{len(p.chat)} new chat line(s)")
        return ", ".join(parts) or "no course parts in view"


class ScreenObserver:
    """Frame source + detector (+ chat OCR every `ocr_every` frames) -> Percept, with stage timings."""

    def __init__(self, source, detector, *, chat_ocr=None, ocr_every: int = 10, clock=None) -> None:
        import time
        self.source, self.detector, self.chat_ocr, self.ocr_every = source, detector, chat_ocr, ocr_every
        self.clock = clock or time.perf_counter

    def __call__(self) -> Percept | None:
        t0 = self.clock()
        frame = self.source.grab()
        if frame is None:
            return None
        t1 = self.clock()
        detections = self.detector.detect(frame.image)
        t2 = self.clock()
        chat = []
        if self.chat_ocr is not None and frame.index % self.ocr_every == 0:
            chat = self.chat_ocr.read(frame.image)
        t3 = self.clock()
        width, height = frame.size
        return Percept(frame.index, frame.t, width, height, detections, chat,
                       {"grab": (t1 - t0) * 1000, "detect": (t2 - t1) * 1000, "ocr": (t3 - t2) * 1000})
