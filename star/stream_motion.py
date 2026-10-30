"""Bounded, offline audio-to-avatar motion planner for Star's original rig.

Inputs are HOST-PROVIDED timestamps and audio envelopes, not microphone access,
emotion recognition, voice generation or body physics. All results are *suggested*
normalized rig controls; only an authorized host may map them to a specific
Live2D/3D model. No audio, OBS, websocket or device I/O occurs here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import random


MAX_DURATION_S = 15.0
MAX_AUDIO_SAMPLES = 1500
MAX_CUES = 32
MODES = frozenset({"normal", "cat", "puppy"})
CUES = frozenset({"surprise", "joy", "laugh", "focus", "nod"})


def _finite(value: object, name: str, lower: float, upper: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be finite within [{lower}, {upper}]")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be finite within [{lower}, {upper}]") from exc
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{name} must be finite within [{lower}, {upper}]")
    return value


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class AudioLevel:
    at_s: float
    rms: float  # caller-normalized audible signal envelope, zero means silence

    def __post_init__(self) -> None:
        _finite(self.at_s, "audio timestamp", 0, MAX_DURATION_S)
        _finite(self.rms, "audio energy", 0, 1)


@dataclass(frozen=True)
class ExpressionCue:
    at_s: float
    kind: str
    strength: float = 1.0
    target_x: float = 0.0  # only used by 'focus'; normalized visual target

    def __post_init__(self) -> None:
        _finite(self.at_s, "cue timestamp", 0, MAX_DURATION_S)
        if not isinstance(self.kind, str) or self.kind not in CUES:
            raise ValueError("unknown expression cue")
        _finite(self.strength, "cue strength", 0, 1)
        _finite(self.target_x, "focus target", -1, 1)


@dataclass(frozen=True)
class MotionFrame:
    at_s: float
    mouth_open: float
    eye_open_left: float
    eye_open_right: float
    smile: float
    brow_raise: float
    head_x: float
    head_y: float
    body_lean: float
    shoulder_lift: float
    gaze_x: float
    ear_left: float
    ear_right: float
    tail_sway: float
    hair_sway: float


def neutral_frame(at_s: float = 0.0) -> MotionFrame:
    """Immediate neutral reset after an interrupted/cancelled utterance.

    The host must stop transmitting old queued frames and issue a neutral reset;
    returning one here does not control VTube Studio or stop audible TTS.
    """
    return MotionFrame(_finite(at_s, "neutral timestamp", 0, MAX_DURATION_S),
                       0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def _ordered(values: object, cls: type, maximum: int, duration_s: float, name: str) -> tuple:
    if not isinstance(values, (tuple, list)) or len(values) > maximum:
        raise ValueError(f"{name} must be a bounded sequence")
    previous = -1.0
    for value in values:
        if not isinstance(value, cls) or value.at_s <= previous or value.at_s > duration_s:
            raise ValueError(f"{name} must have unique, ascending in-range timestamps")
        previous = value.at_s
    return tuple(values)


def _blink_intervals(duration_s: float, seed: int) -> tuple[tuple[float, float], ...]:
    # Seed only selects *subtle idle timing*, never speech or event content.
    rng = random.Random(seed)
    starts = []
    t = 1.8 + rng.uniform(0.0, 1.5)
    while t < duration_s:
        starts.append((t, min(duration_s, t + 0.15)))
        t += rng.uniform(2.4, 4.4)
    return tuple(starts)


def _audio_at(t: float, samples: tuple[AudioLevel, ...], cursor: int) -> tuple[float, int]:
    # Past data only. A delayed or dropped audio envelope must NOT animate future speech.
    while cursor + 1 < len(samples) and samples[cursor + 1].at_s <= t:
        cursor += 1
    if not samples or t < samples[0].at_s or t - samples[cursor].at_s > 0.11:
        return 0.0, cursor
    return samples[cursor].rms, cursor


def plan_motion(*, duration_s: float, audio_levels: tuple[AudioLevel, ...] | list[AudioLevel],
                cues: tuple[ExpressionCue, ...] | list[ExpressionCue] = (),
                mode: str = "normal", fps: int = 30,
                reduced_motion: bool = False, seed: int = 7,
                cancelled: Callable[[], bool] | None = None) -> tuple[MotionFrame, ...]:
    """Generate deterministic local rig targets at 15/30/60 Hz, max 15 seconds.

    For live playback, synchronize returned timestamps with *actual output
    audio*, not wall clock or model text-generation timestamps. This heuristic
    does not produce phoneme-perfect lipsync or simulate Live2D hair physics.
    """
    duration_s = _finite(duration_s, "duration", 0.001, MAX_DURATION_S)
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("mode must be normal, cat, or puppy")
    if type(fps) is not int or fps not in (15, 30, 60):
        raise ValueError("fps must be 15, 30 or 60")
    if type(reduced_motion) is not bool or type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("reduced_motion must be bool and seed must be a 32-bit unsigned int")
    audio_levels = _ordered(audio_levels, AudioLevel, MAX_AUDIO_SAMPLES, duration_s, "audio_levels")
    cues = _ordered(cues, ExpressionCue, MAX_CUES, duration_s, "cues")
    if cancelled is not None and not callable(cancelled):
        raise TypeError("cancelled must be callable or None")
    # Keep invalid caller inputs observable even if the turn was revoked.
    # This avoids treating corrupt sample envelopes as harmless interruptions.
    if cancelled is not None and cancelled():
        return ()

    blink_intervals = _blink_intervals(duration_s, seed)
    cursor, blink_cursor = 0, 0
    mouth = 0.0
    phase = (seed % 997) / 997.0 * 2 * math.pi
    frames: list[MotionFrame] = []
    count = math.floor(duration_s * fps)
    for index in range(count + 1):
        # Revoke obsolete work promptly, not just obsolete output. At most
        # seven more frames are computed after a successful sampled check.
        # Never return partially generated frames from a cancelled turn.
        if cancelled is not None and index % 8 == 0 and cancelled():
            return ()
        t = min(index / fps, duration_s)
        level, cursor = _audio_at(t, audio_levels, cursor)
        target = _clamp((level - 0.07) * 1.2, 0, 1)
        # Smooth attack/release: stable speaking mouth, no rapid frame-to-frame pops.
        tau = 0.045 if target > mouth else 0.085
        factor = 1 - math.exp(-1 / (fps * tau))
        mouth += (target - mouth) * factor
        if mouth < 0.001:
            mouth = 0.0

        smile = brow = gaze = nod = laugh = surprise = 0.0
        for cue in cues:
            age = t - cue.at_s
            if age < 0 or age > 1.5:
                continue
            strength = cue.strength
            if cue.kind == "joy":
                smile = max(smile, strength * 0.60 * math.exp(-age / 1.0))
            elif cue.kind == "laugh":
                pulse = math.exp(-age / 0.65)
                laugh = max(laugh, strength * pulse)
                smile = max(smile, 0.8 * strength * pulse)
            elif cue.kind == "surprise":
                surprise = max(surprise, strength * math.exp(-age / 0.45))
                brow = max(brow, 0.85 * strength * math.exp(-age / 0.45))
            elif cue.kind == "focus":
                gaze = cue.target_x * strength * math.exp(-age / 1.1)
            elif cue.kind == "nod":
                nod += strength * math.exp(-age / 0.5) * math.sin(age * math.pi * 3)

        while blink_cursor < len(blink_intervals) and t > blink_intervals[blink_cursor][1]:
            blink_cursor += 1
        closing = 0.0
        if blink_cursor < len(blink_intervals):
            start, end = blink_intervals[blink_cursor]
            if start <= t <= end:
                center = (start + end) / 2
                closing = max(0, 1 - abs(t - center) / ((end - start) / 2))
        eye_open = _clamp(1 - closing, 0, 1)
        if reduced_motion:
            head_x = head_y = lean = shoulder = ear_l = ear_r = tail = hair = 0.0
        else:
            head_x = 0.035 * math.sin(2 * math.pi * t / 5.2 + phase) + gaze * 0.09
            head_y = 0.018 * math.sin(2 * math.pi * t / 7 + phase) + 0.13 * nod
            head_y += 0.035 * laugh * math.sin(2 * math.pi * 4 * t)
            lean = 0.42 * head_x
            shoulder = 0.09 * laugh + 0.03 * surprise
            hair = 0.07 * math.sin(2 * math.pi * t / 5.2 + phase - 0.45) + 0.11 * head_x
            if mode == "cat":
                tail = 0.25 * math.sin(2 * math.pi * t / 2.2 + phase) + 0.12 * laugh
                ear_l = _clamp(0.28 * surprise - 0.14 * laugh)
                ear_r = _clamp(0.23 * surprise - 0.10 * laugh)
            elif mode == "puppy":
                tail = 0.35 * math.sin(2 * math.pi * t / 1.4 + phase) * (0.25 + smile)
                ear_l = _clamp(-0.15 * laugh + 0.14 * surprise)
                ear_r = _clamp(-0.12 * laugh + 0.12 * surprise)
            else:
                ear_l = ear_r = tail = 0.0
        frames.append(MotionFrame(t, _clamp(mouth, 0, 1), eye_open, eye_open,
                                  _clamp(smile, 0, 1), _clamp(brow, 0, 1),
                                  _clamp(head_x), _clamp(head_y), _clamp(lean),
                                  _clamp(shoulder, 0, 1), _clamp(gaze),
                                  _clamp(ear_l), _clamp(ear_r), _clamp(tail),
                                  _clamp(hair)))
    if cancelled is not None and cancelled():
        return ()
    return tuple(frames)
