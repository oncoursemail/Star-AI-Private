"""Playback-clock-locked VTuber motion for Star's opt-in live stage.

The game stream, TTS engine and renderer operate at different rates. TTS
*generated* time is not audible time: a backlog, pause or cancellation can
otherwise make the avatar react before speech is actually played.

An authorized host must supply the actual output-device playout cursor in
seconds, measured on its own monotonic clock. This module never captures sound,
controls OBS, VTube Studio, Windows, or starts streaming. All frames are
suggestions, and the host MUST call current() at the final render boundary.
An untrusted viewer, model result, or game's overlay must never supply cursors.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, fields
import math
from threading import RLock
import time
from typing import Callable, Sequence

from .stream_motion import AudioLevel, MotionFrame, neutral_frame
from .stream_stage import StagePlan, StarStage


def _seconds(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return result


@dataclass(frozen=True)
class PlayoutRigFrame:
    """Identity-bound, short-lived recommendation, not permission to render."""

    sequence: int
    tick: int
    sampled_at: float
    playhead_s: float
    motion: MotionFrame


_MOTION_CHANNELS = tuple(field.name for field in fields(MotionFrame)
                         if field.name != "at_s")


def _interpolate(
    frames: tuple[MotionFrame, ...], timestamps: tuple[float, ...], at_s: float,
) -> MotionFrame:
    """O(log n) seek, then two-frame interpolation (no speculative mouth)."""
    idx = bisect_right(timestamps, at_s)
    if idx == 0:
        return frames[0]
    if idx == len(frames):
        return frames[-1]
    a, b = frames[idx - 1], frames[idx]
    fraction = (at_s - a.at_s) / (b.at_s - a.at_s)
    channels = [getattr(a, name) + fraction * (
        getattr(b, name) - getattr(a, name)
    ) for name in _MOTION_CHANNELS]
    return MotionFrame(at_s, *channels)


class StarPlayoutClock:
    """Bounded, fail-closed adapter from heard audio positions to avatar frames.

    This is intentionally separate from StarStage: the host controls the
    playback device, so only the host can attest that a position was heard.
    Enabling this class does NOT enable StarStage, recording or broadcasting.
    The host must neutralize the rig when sample() returns None.
    """

    def __init__(
        self, stage: StarStage, *,
        clock: Callable[[], float] = time.monotonic,
        max_age_s: float = 0.16,
        stall_after_s: float = 0.20,
        max_playback_rate: float = 1.4,
    ) -> None:
        if not isinstance(stage, StarStage):
            raise TypeError("stage must be a StarStage")
        self._max_age = _seconds(max_age_s, "max_age_s")
        self._stall_after = _seconds(stall_after_s, "stall_after_s")
        self._max_rate = _seconds(max_playback_rate, "max_playback_rate")
        if not (0.03 <= self._max_age <= 0.5
                and 0.05 <= self._stall_after <= 1.0
                and 1.0 <= self._max_rate <= 2.0):
            raise ValueError("unsafe playback clock bounds")
        self._stage = stage
        self._clock = clock
        self._lock = RLock()
        self._enabled = False
        self._plan: StagePlan | None = None
        self._frames: tuple[MotionFrame, ...] = ()
        self._timestamps: tuple[float, ...] = ()
        self._duration = 0.0
        self._armed_at = 0.0
        self._sampled_at: float | None = None
        self._position = 0.0
        self._progress_at = 0.0
        self._playing = False
        self._issued: PlayoutRigFrame | None = None
        self._tick = 0
        self._counts = {
            "armed": 0, "playheads": 0, "rejected": 0,
            "frames": 0, "stale": 0, "resets": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit authorized host approval required")
        with self._lock:
            self._enabled = True

    def _clear(self) -> None:
        self._plan = None
        self._frames = ()
        self._timestamps = ()
        self._duration = 0.0
        self._sampled_at = None
        self._position = 0.0
        self._playing = False
        self._issued = None

    def reset(self) -> MotionFrame:
        """Host must stop old animation and send this neutral rig frame."""
        with self._lock:
            self._clear()
            self._counts["resets"] += 1
            return neutral_frame()

    def disable(self) -> MotionFrame:
        with self._lock:
            self._enabled = False
            return self.reset()

    def arm(
        self, plan: StagePlan, *, duration_s: float,
        audio_levels: Sequence[AudioLevel], fps: int = 30, seed: int = 7,
    ) -> bool:
        """Bind exactly one *audible* stage plan to a precomputed motion track.

        Never arm from TTS enqueue, text completion or unverified game events.
        This method samples only existing StarStage cues; it cannot add one.
        """
        if not isinstance(plan, StagePlan):
            raise TypeError("expected StagePlan")
        if not self._stage.current(plan):
            return False
        duration = _seconds(duration_s, "duration_s")
        frames = self._stage.motion(
            plan, duration_s=duration, audio_levels=audio_levels,
            fps=fps, seed=seed,
        )
        if not frames:
            return False
        with self._lock:
            if not self._enabled or not self._stage.current(plan):
                return False
            if self._plan is not None and self._stage.current(self._plan):
                return False  # no silent replacement of an active speech turn
            self._clear()
            self._plan = plan
            self._frames = frames
            self._timestamps = tuple(frame.at_s for frame in frames)
            self._duration = duration
            self._armed_at = _seconds(self._clock(), "clock")
            self._counts["armed"] += 1
            return True

    def observe_playhead(
        self, plan: StagePlan, *, position_s: float,
        sampled_at: float, playing: bool = True,
    ) -> bool:
        """Accept a host-attested output audio cursor, never an estimate.

        Reject rollbacks, future timestamps and implausible audio jumps.
        A rejected cursor clears the current rig lease. A stale previous plan
        cannot cancel a newer plan's lease.
        """
        with self._lock:
            if not self._enabled or self._plan is not plan:
                return False
            if not self._stage.current(plan):
                self._clear()
                return False
            try:
                position = _seconds(position_s, "position_s")
                stamp = _seconds(sampled_at, "sampled_at")
                now = _seconds(self._clock(), "clock")
                if type(playing) is not bool:
                    raise ValueError("playing must be a boolean")
                if (stamp > now + 0.02
                        or stamp < self._armed_at - 0.02
                        or position > self._duration + 0.001):
                    raise ValueError("invalid playout position or clock")
                if self._sampled_at is None:
                    # An initial jump cannot create unearned earlier lip cues.
                    if position > 0.25:
                        raise ValueError("first cursor too far into speech")
                    self._progress_at = stamp
                else:
                    elapsed = stamp - self._sampled_at
                    progressed = position - self._position
                    if elapsed < 0 or progressed < -0.015:
                        raise ValueError("playout cursor moved backward")
                    if progressed > self._max_rate * elapsed + 0.08:
                        raise ValueError("playout cursor advanced implausibly")
                    if progressed > 0.002 or (playing and not self._playing):
                        self._progress_at = stamp
                self._position = max(self._position, position)
                self._sampled_at = stamp
                self._playing = playing
                self._issued = None  # old frame must not be dispatched later
                self._counts["playheads"] += 1
                return True
            except ValueError:
                self._counts["rejected"] += 1
                self._clear()
                return False

    def sample(self, plan: StagePlan, *, now: float | None = None) -> PlayoutRigFrame | None:
        """Interpolate a rig pose at the *heard* playhead, not generated text."""
        with self._lock:
            if not self._enabled or self._plan is not plan:
                return None
            if not self._stage.current(plan):
                self._clear()
                return None
            current = _seconds(self._clock() if now is None else now, "clock")
            if (self._sampled_at is None or not self._playing
                    or not 0 <= current - self._sampled_at <= self._max_age
                    or not 0 <= current - self._progress_at <= self._stall_after):
                self._issued = None
                self._counts["stale"] += 1
                return None
            motion = _interpolate(self._frames, self._timestamps, self._position)
            self._tick += 1
            frame = PlayoutRigFrame(
                sequence=plan.sequence, tick=self._tick,
                sampled_at=current, playhead_s=self._position, motion=motion,
            )
            self._issued = frame
            self._counts["frames"] += 1
            return frame

    def current(self, frame: PlayoutRigFrame, *, now: float | None = None) -> bool:
        """Host MUST call immediately before writing parameters to the rig.

        Rechecking prevents old queued batches from surviving stage interruption,
        a fresh audio cursor, or a newer rendered frame.
        """
        with self._lock:
            if not (self._enabled and isinstance(frame, PlayoutRigFrame)
                    and self._issued is frame and self._plan is not None
                    and frame.sequence == self._plan.sequence
                    and self._stage.current(self._plan)):
                return False
            try:
                current = _seconds(self._clock() if now is None else now, "clock")
            except ValueError:
                self._issued = None
                return False
            if not 0 <= current - frame.sampled_at <= min(self._max_age, 0.15):
                self._issued = None
                return False
            return True

    def duration_if_armed(self, plan: StagePlan) -> float | None:
        """Return the exact active audio-track duration, never inferred from TTS."""
        with self._lock:
            if (not self._enabled or self._plan is not plan
                    or not self._stage.current(plan)):
                return None
            return self._duration

    def metrics(self) -> dict[str, object]:
        """Only aggregate counts and the current phase; no audio or chat data."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "active": self._plan is not None,
                    "playing": self._playing}


__all__ = ["PlayoutRigFrame", "StarPlayoutClock"]
