"""Cheap, event-grounded quiet-time animation for STAR's original VTuber rig.

The speaking stage already samples audible TTS for lip movement. Without a
separate quiet path, the avatar freezes whenever STAR is listening, thinking,
or focusing on a game. This module emits *only* a subdued rig suggestion, not
speech, a claim about a viewer's emotion, a camera feed, or a tool action.

Only trusted host booleans and a monotonic clock may select the attention
state. No chat text, audio, personal data, random global state, or network
access is read here. The authorized stage decides whether a frame is current.
"""
from __future__ import annotations

import math

from .stream_motion import MODES, MotionFrame


def _time(value: object) -> float:
    if type(value) not in (float, int):
        raise ValueError("quiet animation needs a finite monotonic time")
    try:
        now = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("quiet animation time overflow") from exc
    if not math.isfinite(now) or not 0 <= now <= 1e13:
        raise ValueError("quiet animation needs a finite monotonic time")
    return now


def _blink_open(elapsed: float) -> float:
    """O(1) deterministic irregular blink; no timer loops over long sessions."""
    cycle = math.floor(elapsed / 3.1)
    phase = elapsed - cycle * 3.1
    # Repeatable variation makes blinking less clockwork without reading RNG
    # or inspecting a viewer. Sub-second width is independent of sampling FPS.
    jitter = ((1103515245 * (cycle + 19) + 12345) & 0xFFFFFFFF) % 101
    start = 0.65 + jitter / 450.0
    opening = 1.0
    for offset in ((0.0, 0.32) if cycle % 11 == 7 else (0.0,)):
        middle = start + offset + 0.082
        closing = max(0.0, 1.0 - abs(phase - middle) / 0.082)
        opening = min(opening, 1.0 - closing)
    return opening


class QuietAttention:
    """A stateful, session-local nonverbal frame sampler (no output device).

    Call reset() whenever the stream session, avatar or playback epoch changes.
    Playing a game has priority over chatting for gaze; a critical game moment
    suppresses exaggerated movement. This does not infer emotions or attention
    from viewer content. Frames use at_s=0 because each is an instantaneous
    target, not an audio clip timed from generated TTS.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._origin: float | None = None
        self._last: float | None = None
        self._gaze = 0.0

    def sample(
        self, *, now: float, viewer_speaking: bool = False,
        game_active: bool = False, gameplay_critical: bool = False,
        mode: str = "normal", reduced_motion: bool = False,
    ) -> MotionFrame:
        now = _time(now)
        if any(type(value) is not bool for value in (
            viewer_speaking, game_active, gameplay_critical, reduced_motion,
        )):
            raise ValueError("attention states and accessibility flag must be bool")
        if type(mode) is not str or mode not in MODES:
            raise ValueError("unknown original character rig mode")
        if self._last is not None and now < self._last:
            raise ValueError("quiet animation monotonic clock moved backwards")

        if gameplay_critical:
            target = -0.28
        elif viewer_speaking:
            target = 0.10
        elif game_active:
            target = -0.18
        else:
            target = 0.0

        if self._origin is None:
            self._origin = now
            self._gaze = target
        elif self._last is not None:
            dt = now - self._last
            self._gaze += (target - self._gaze) * (1 - math.exp(-dt / 0.40))
        self._last = now
        elapsed = now - self._origin
        blink = _blink_open(elapsed)

        if reduced_motion:
            gaze = head_x = head_y = body = hair = tail = 0.0
        else:
            gaze = self._gaze
            # No glances toward chat during tense gameplay. Idle movement is
            # deliberately tiny; body and twin-tail/hair are coupled to head.
            idle = 0.0 if gameplay_critical else 1.0
            head_x = 0.13 * gaze + 0.008 * idle * math.sin(elapsed / 3.6)
            head_y = 0.008 * idle * math.sin(elapsed / 4.2)
            body = head_x * 0.24
            hair = head_x * 0.15 + 0.010 * idle * math.sin(elapsed / 3.6 - 0.35)
            if gameplay_critical:
                tail = 0.0
            elif mode == "cat":
                tail = 0.10 * math.sin(elapsed / 1.8)
            elif mode == "puppy":
                tail = 0.13 * math.sin(elapsed / 1.3)
            else:
                tail = 0.0

        return MotionFrame(
            at_s=0.0, mouth_open=0.0, eye_open_left=blink,
            eye_open_right=blink, smile=0.0, brow_raise=0.0,
            head_x=head_x, head_y=head_y, body_lean=body,
            shoulder_lift=0.0, gaze_x=gaze, ear_left=0.0, ear_right=0.0,
            tail_sway=tail, hair_sway=hair,
        )


__all__ = ["QuietAttention"]
