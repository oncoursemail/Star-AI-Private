"""Offline concurrency checks for STAR's responsive audio/avatar preemption.

A deliberately blocked motion planner represents CPU work, not real VTS/OBS
output. No game controls, media files, network or microphones are used.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import star.stream_stage as stage_module
from star.stream_director import StreamDirector, StreamSignal
from star.stream_motion import AudioLevel, MotionFrame
from star.stream_stage import StagePlan, StarStage


def _audible_stage() -> tuple[StarStage, StagePlan]:
    s = StarStage(director=StreamDirector(gap_seconds=0), clock=lambda: 100.0)
    s.enable(owner_approved=True, mode="cat")
    assert s.offer(StreamSignal(
        "witnessed-a", "game_success", 100.0, "host saw a checkpoint",
        evidence="observed",
    ), now=100.0)
    p = s.prepare(now=100.0)
    assert p is not None
    assert s.queue_audio(p, now=100.0)
    assert s.acknowledge_audible(p, now=100.0)
    return s, p


def test_owner_interrupt_does_not_wait_for_slow_motion_generation():
    s, p = _audible_stage()
    started, release = Event(), Event()
    original = stage_module.plan_motion

    def delayed_motion(**kwargs):
        started.set()
        assert release.wait(timeout=8), "test must unblock the worker"
        return original(**kwargs)

    with patch.object(stage_module, "plan_motion", side_effect=delayed_motion):
        with ThreadPoolExecutor(max_workers=2) as pool:
            worker = pool.submit(
                s.motion, p, duration_s=1.0,
                audio_levels=[AudioLevel(0, 0.8)],
            )
            assert started.wait(timeout=3), "render worker did not start"
            stop = pool.submit(s.interrupt_if_current, p, now=100.2)
            try:
                # This must complete while the expensive frame planner is
                # deliberately blocked, not after it has been released.
                neutral = stop.result(timeout=3)
                assert isinstance(neutral, MotionFrame)
                assert neutral.mouth_open == 0
                assert not s.current(p)
            finally:
                release.set()
            assert worker.result(timeout=5) == ()
    assert s.metrics()["motion_requests"] == 0
    assert s.metrics()["director"]["completed"] == 0
    assert s.metrics()["interrupted"] == 1


def test_new_turn_cannot_receive_old_frame_generation_result():
    s, p = _audible_stage()
    entered, release = Event(), Event()
    original = stage_module.plan_motion

    def delayed_motion(**kwargs):
        entered.set()
        assert release.wait(timeout=8)
        return original(**kwargs)

    with patch.object(stage_module, "plan_motion", side_effect=delayed_motion):
        with ThreadPoolExecutor(max_workers=2) as pool:
            old_worker = pool.submit(
                s.motion, p, duration_s=0.2,
                audio_levels=[AudioLevel(0, 0.5)],
            )
            assert entered.wait(timeout=3)
            try:
                s.interrupt(now=100.1)
                assert s.offer(StreamSignal(
                    "danger-next", "game_danger", 100.2,
                    "host saw a hazard", evidence="observed",
                ), now=100.2)
                successor = s.prepare(now=100.2)
                assert successor is not None and successor is not p
                assert s.queue_audio(successor, now=100.2)
                assert s.acknowledge_audible(successor, now=100.2)
            finally:
                release.set()
            assert old_worker.result(timeout=5) == ()
            assert s.current(successor)
    assert s.metrics()["motion_requests"] == 0
    assert s.metrics()["director"]["completed"] == 0
    assert s.finish(successor, now=100.3, played_to_end=True)


def test_valid_motion_still_returns_frames_and_bad_envelopes_do_not_commit():
    s, p = _audible_stage()
    frames = s.motion(p, duration_s=0.2, fps=30,
                      audio_levels=[AudioLevel(0, 0.6)])
    assert len(frames) == 7
    assert any(frame.mouth_open > 0 for frame in frames)
    assert s.metrics()["motion_requests"] == 1
    try:
        s.motion(p, duration_s=-1, audio_levels=[])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid duration must remain rejected")
    assert s.current(p)
    assert s.metrics()["motion_requests"] == 1
    assert s.finish(p, now=100.3, played_to_end=True)
