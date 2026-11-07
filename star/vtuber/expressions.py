"""Short cosmetic expression cues layered over the live rig, separate from speech.

No emotion-engine writes, chat parsing, network or device access. A trusted host
selects typed events; loopback delivery is not authentication or moderation.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from collections import deque
import math
import re
import threading
import time
from types import MappingProxyType
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .rig import Pose

MIN_DURATION_S = 0.4
MAX_DURATION_S = 4.0
MIN_GAP_S = 0.6
SAME_CUE_COOLDOWN_S = 2.5
MAX_CUES_PER_WINDOW = 8
CUE_WINDOW_S = 20.0


@dataclass(frozen=True)
class _Style:
    face: str
    smile: float
    brow: float
    eye_scale: float = 1.0
    gaze_x: float | None = None
    gaze_y: float | None = None
    duration: float = 1.8


_STYLES = MappingProxyType({
    "smile": _Style("happy", 0.6, 0.12, 0.90),
    "laugh": _Style("happy", 0.85, 0.16, 0.60, duration=1.6),
    "surprise": _Style("stopped", 0.02, 0.85, duration=1.15),
    "thinking": _Style("thinking", 0.08, 0.22, 0.96, -0.18, 0.10, 2.2),
    "reading_chat": _Style("listening", 0.18, 0.12, 0.96, -0.35, 0.12, 2.4),
    "concerned": _Style("oops", 0.0, 0.30, 0.92, duration=1.8),
    "proud": _Style("happy", 0.70, 0.18, 0.88, duration=2.0),
})
EXPRESSION_NAMES = ("neutral", *_STYLES)
EVENT_EXPRESSIONS = MappingProxyType({
    "viewer_question": ("reading_chat", 20),
    "viewer_comment": ("reading_chat", 10),
    "chat_reading": ("reading_chat", 20),
    "chat_reply": ("smile", 25),
    "game_danger": ("surprise", 60),
    "game_success": ("proud", 45),
    "game_win": ("proud", 45),
    "game_fail": ("concerned", 35),
    "game_observation": ("thinking", 15),
    "video_funny": ("laugh", 45),
    "video_surprise": ("surprise", 55),
    "video_nice": ("smile", 30),
    "friend_joined": ("smile", 30),
    "call_greeting": ("smile", 30),
})


def _finite(value: object, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expression values must be bounded finite numbers")
    try:
        number = float(value)
    except (ValueError, OverflowError):
        raise ValueError("Expression values must be bounded finite numbers") from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError("Expression values must be bounded finite numbers")
    return number


def encode_expression(name: str, duration_s: float | None = None) -> str:
    """Encode a bounded cosmetic cue in the existing <=40-character event field."""
    if not isinstance(name, str) or name not in EXPRESSION_NAMES:
        raise ValueError("Unknown avatar expression")
    if name == "neutral":
        if duration_s is not None and (type(duration_s) not in (int, float) or duration_s != 0):
            raise ValueError("Neutral clears immediately and has no duration")
        return "expression:neutral:0"
    duration = _STYLES[name].duration if duration_s is None else _finite(duration_s, MIN_DURATION_S, MAX_DURATION_S)
    return f"expression:{name}:{round(duration * 1000)}"


@dataclass(frozen=True)
class _Active:
    name: str
    strength: float
    start: float
    duration: float
    priority: int


class ExpressionTimeline:
    """One active cue, no backlog, fixed release, bounded repetition and interruption.

    Stamp events at receipt (camera._on_event), not the next render tick, so a
    stalled frame loop cannot make a stale expression new again.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._lock = threading.RLock()
        self._active: _Active | None = None
        self._last_time = 0.0
        self._last_start = float("-inf")
        self._seen: dict[str, float] = {}
        self._starts: deque[float] = deque()
        self._accepted = self._dropped = self._cleared = 0

    def clear(self) -> None:
        with self._lock:
            self._active = None
            self._cleared += 1

    def _expire(self, now: float) -> None:
        if self._active is not None and now >= self._active.start + self._active.duration:
            self._active = None

    def event(self, kind: str, strength: float = 1.0, *, now: float | None = None) -> bool:
        """Accept only fixed event IDs or an encoded expression. Raw chat is not an input."""
        if kind in ("owner_interrupt", "expression:neutral:0"):
            self.clear()
            return True
        try:
            current = _finite(self.clock() if now is None else now, 0.0, 10**12)
            strength = _finite(strength, 0.0, 1.0)
            if not isinstance(kind, str) or len(kind) > 40 or strength == 0:
                return False
            if kind == "chat_reading_end":
                with self._lock:
                    if self._active is not None and self._active.name == "reading_chat":
                        self.clear()
                return True
            if kind.startswith("expression:"):
                match = re.fullmatch(r"expression:([a-z_]+):([0-9]{3,4})", kind)
                if match is None:
                    return False
                name = match[1]
                duration = int(match[2]) / 1000.0
                if encode_expression(name, duration) != kind:
                    return False
                priority = 100
            else:
                mapped = EVENT_EXPRESSIONS.get(kind)
                if mapped is None:
                    return False
                name, priority = mapped
                duration = _STYLES[name].duration
        except (ValueError, TypeError, OverflowError):
            return False
        with self._lock:
            if current < self._last_time:
                self._dropped += 1
                return False
            self._last_time = current
            self._expire(current)
            active = self._active
            while self._starts and current - self._starts[0] >= CUE_WINDOW_S:
                self._starts.popleft()
            if (current - self._seen.get(name, float("-inf")) < SAME_CUE_COOLDOWN_S
                    or (active is not None and name == active.name)
                    or len(self._starts) >= MAX_CUES_PER_WINDOW
                    or (active is not None and priority < active.priority)
                    or (current - self._last_start < MIN_GAP_S and (active is None or priority <= active.priority))):
                self._dropped += 1
                return False
            self._active = _Active(name, strength, current, duration, priority)
            self._seen[name] = self._last_start = current
            self._starts.append(current)
            self._accepted += 1
            return True

    def apply(self, pose: Pose, *, now: float | None = None) -> Pose:
        """Blend face/eyes/brows/gaze only. Mouth opening, visemes and body pose stay intact."""
        from .rig import Pose

        if not isinstance(pose, Pose):
            raise TypeError("Expression overlays require a live rig Pose")
        try:
            current = _finite(pose.t if now is None else now, 0.0, 10**12)
        except (ValueError, TypeError, OverflowError):
            self.clear()
            return pose
        with self._lock:
            if current < self._last_time:
                self._active = None
                return pose
            self._last_time = current
            self._expire(current)
            active = self._active
        if active is None:
            return pose
        age = current - active.start
        attack, release = min(0.15, active.duration * 0.25), min(0.45, active.duration * 0.35)
        weight = max(0.0, min(1.0, age / attack, (active.duration - age) / release))
        weight = (weight * weight * (3.0 - 2.0 * weight)) * active.strength
        style = _STYLES[active.name]

        def blend(base: float, target: float) -> float:
            return base + (target - base) * weight

        return replace(pose, face=style.face if weight >= 0.15 else pose.face,
                       smile=blend(pose.smile, style.smile), brow_raise=blend(pose.brow_raise, style.brow),
                       eye_open_left=pose.eye_open_left * blend(1.0, style.eye_scale),
                       eye_open_right=pose.eye_open_right * blend(1.0, style.eye_scale),
                       gaze_x=pose.gaze_x if style.gaze_x is None else blend(pose.gaze_x, style.gaze_x),
                       gaze_y=pose.gaze_y if style.gaze_y is None else blend(pose.gaze_y, style.gaze_y))

    def status(self, *, now: float | None = None) -> dict:
        current = _finite(self.clock() if now is None else now, 0.0, 10**12)
        with self._lock:
            self._expire(current)
            active = self._active
            return {"active": active.name if active else "neutral", "accepted": self._accepted,
                    "dropped": self._dropped, "cleared": self._cleared,
                    "remaining_s": round(max(0.0, active.start + active.duration - current), 3) if active else 0.0}
