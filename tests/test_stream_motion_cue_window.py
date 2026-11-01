"""Reference checks for the bounded sliding expression-cue window.

The oracle intentionally uses the previous O(frames * cues) scan, independent
of the production window pointers. This guards exact expression semantics,
event freshness, focus precedence, and time boundaries during CPU tuning.
"""
from __future__ import annotations

import math

import pytest

from star.stream_motion import ExpressionCue, plan_motion


def _legacy_channels(t: float, cues: tuple[ExpressionCue, ...]) -> tuple[float, ...]:
    """Original per-frame full scan, retained only as a test oracle."""
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
    return smile, brow, gaze, nod, laugh, surprise


@pytest.mark.parametrize("fps", [15, 30, 60])
@pytest.mark.parametrize("mode", ["normal", "cat", "puppy"])
def test_sliding_window_matches_legacy_expression_channels(fps: int, mode: str) -> None:
    # At full length these span past, future, overlapping, 1.5-second boundaries
    # and periods without any active cue.
    kinds = ("joy", "focus", "surprise", "laugh", "nod")
    cues = tuple(
        ExpressionCue(
            at_s=round(i * 0.45, 4), kind=kinds[i % len(kinds)],
            strength=0.25 + (i % 4) * 0.2,
            target_x=(-0.8 if i % 2 else 0.7),
        )
        for i in range(32)
    )
    seed = 491
    frames = plan_motion(duration_s=15.0, audio_levels=(), cues=cues, mode=mode, fps=fps, seed=seed)
    assert len(frames) == 15 * fps + 1
    phase = (seed % 997) / 997.0 * 2 * math.pi
    for frame in frames:
        smile, brow, gaze, nod, laugh, surprise = _legacy_channels(frame.at_s, cues)
        expected_y = 0.018 * math.sin(2 * math.pi * frame.at_s / 7 + phase) + 0.13 * nod
        expected_y += 0.035 * laugh * math.sin(2 * math.pi * 4 * frame.at_s)
        expected_x = 0.035 * math.sin(2 * math.pi * frame.at_s / 5.2 + phase) + gaze * 0.09
        # Use tight numeric comparisons, not qualitative "looks similar" assertions.
        assert frame.smile == pytest.approx(max(0.0, min(1.0, smile)), abs=1e-12)
        assert frame.brow_raise == pytest.approx(max(0.0, min(1.0, brow)), abs=1e-12)
        assert frame.gaze_x == pytest.approx(max(-1.0, min(1.0, gaze)), abs=1e-12)
        assert frame.head_x == pytest.approx(max(-1.0, min(1.0, expected_x)), abs=1e-12)
        assert frame.head_y == pytest.approx(max(-1.0, min(1.0, expected_y)), abs=1e-12)
        assert frame.shoulder_lift == pytest.approx(
            max(0.0, min(1.0, 0.09 * laugh + 0.03 * surprise)), abs=1e-12
        )


def test_exact_age_cutoff_is_inclusive_and_old_cues_expire() -> None:
    cues = (ExpressionCue(0.0, "joy", strength=1.0),)
    frames = plan_motion(duration_s=2.0, fps=60, cues=cues, audio_levels=())
    assert frames[90].at_s == 1.5
    assert frames[90].smile == pytest.approx(0.6 * math.exp(-1.5), abs=1e-12)
    assert frames[91].smile == 0.0


def test_later_focus_takes_precedence_over_earlier_focus() -> None:
    cues = (ExpressionCue(0.2, "focus", target_x=1.0),
            ExpressionCue(0.5, "focus", target_x=-1.0))
    frames = plan_motion(duration_s=2.5, fps=30, cues=cues, audio_levels=())
    assert frames[30].gaze_x == pytest.approx(-math.exp(-0.5 / 1.1), abs=1e-12)
    assert frames[61].gaze_x == 0.0  # both older than 1.5 s at t = 61/30


def test_future_cue_never_animates_early() -> None:
    frames = plan_motion(
        duration_s=1.0, fps=60, audio_levels=(),
        cues=(ExpressionCue(0.9, "surprise", strength=1.0),),
    )
    assert all(frame.brow_raise == 0.0 for frame in frames if frame.at_s < 0.9)
    assert frames[54].brow_raise > 0.0
