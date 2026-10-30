"""Bounded, offline regression tests for cooperative avatar rendering cancellation.

The tests intentionally block a synthetic audio sampler, not any audio device,
game input, network, model or OBS process.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

import star.stream_motion as motion_module
from star.stream_director import StreamDirector, StreamSignal
from star.stream_motion import AudioLevel, plan_motion
from star.stream_stage import StarStage


def _start_audible() -> tuple[StarStage, object]:
    stage = StarStage(director=StreamDirector(gap_seconds=0), clock=lambda: 100.0)
    stage.enable(owner_approved=True, mode="cat")
    event = StreamSignal(
        "game-observation-1", "game_observation", 100.0,
        "host observed a new obstacle", evidence="observed",
    )
    assert stage.offer(event, now=100.0)
    plan = stage.prepare(now=100.0)
    assert plan is not None
    assert stage.queue_audio(plan, now=100.0)
    assert stage.acknowledge_audible(plan, now=100.0)
    return stage, plan


def test_uncancelled_planner_remains_byte_for_byte_deterministic():
    levels = [AudioLevel(0, 0.8), AudioLevel(0.1, 0.5)]
    baseline = plan_motion(duration_s=0.3, audio_levels=levels, mode="cat")
    calls = []
    actual = plan_motion(
        duration_s=0.3, audio_levels=levels, mode="cat",
        cancelled=lambda: calls.append(1) or False,
    )
    assert actual == baseline
    assert len(actual) == 10
    assert len(calls) >= 2


def test_cancelled_planner_returns_no_partial_motion_frames():
    count = 0

    def cancel_after_two_checks() -> bool:
        nonlocal count
        count += 1
        return count >= 3

    frames = plan_motion(
        duration_s=15.0, audio_levels=[AudioLevel(0, 0.5)],
        fps=60, cancelled=cancel_after_two_checks,
    )
    assert frames == ()
    # The first check precedes rendering, the second is on the first frame,
    # and the third occurs at frame 8. No 900-frame work should complete.
    assert count == 3


def test_cancel_before_rendering_and_reject_invalid_inputs():
    assert plan_motion(
        duration_s=15, audio_levels=[], cancelled=lambda: True,
    ) == ()
    with pytest.raises(TypeError, match="cancelled"):
        plan_motion(duration_s=1, audio_levels=[], cancelled=True)
    with pytest.raises(ValueError, match="duration"):
        plan_motion(duration_s=-1, audio_levels=[], cancelled=lambda: True)
    with pytest.raises(ValueError, match="timestamps"):
        plan_motion(
            duration_s=1, audio_levels=[AudioLevel(0.7, 0.4), AudioLevel(0.1, 0.2)],
            cancelled=lambda: True,
        )


def test_interrupted_stage_stops_computation_within_eight_frames():
    stage, plan = _start_audible()
    entered, release = Event(), Event()
    observed_audio_samples = 0
    original = motion_module._audio_at

    def slow_first_frame(t, levels, cursor):
        nonlocal observed_audio_samples
        observed_audio_samples += 1
        if observed_audio_samples == 1:
            entered.set()
            assert release.wait(timeout=8), "must release synthetic rendering"
        return original(t, levels, cursor)

    with patch.object(motion_module, "_audio_at", side_effect=slow_first_frame):
        with ThreadPoolExecutor(max_workers=2) as pool:
            worker = pool.submit(
                stage.motion, plan, duration_s=15.0, fps=60,
                audio_levels=[AudioLevel(0, 0.8)],
            )
            assert entered.wait(timeout=3), "render worker did not start"
            try:
                neutral = stage.interrupt_if_current(plan, now=100.1)
                assert neutral is not None
                assert neutral.mouth_open == 0
                assert not stage.current(plan)
            finally:
                release.set()
            assert worker.result(timeout=5) == ()
    assert 1 <= observed_audio_samples <= 8
    assert stage.metrics()["motion_requests"] == 0
    assert stage.metrics()["director"]["completed"] == 0
    assert stage.metrics()["interrupted"] == 1
