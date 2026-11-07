"""Offline regression tests for Star's heard-audio VTuber synchronization."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
import unittest

from star.stream_director import StreamSignal
from star.stream_motion import AudioLevel
from star.stream_playout_clock import StarPlayoutClock
from star.stream_stage import StarStage


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_stage(clock=None, *, kind="game_success", evidence="observed"):
    clock = clock or Clock()
    stage = StarStage(clock=clock)
    stage.enable(owner_approved=True, mode="cat")
    signal = StreamSignal("game-1", kind, clock.now, "Host-observed checkpoint",
                          evidence=evidence)
    assert stage.offer(signal, now=clock.now)
    plan = stage.prepare(now=clock.now)
    assert plan is not None
    return clock, stage, plan


def audible(stage, plan, clock):
    assert stage.queue_audio(plan, now=clock.now)
    assert stage.acknowledge_audible(plan, now=clock.now)


def make_host(*, audible_first=True, kind="game_success", evidence="observed"):
    clock, stage, plan = make_stage(kind=kind, evidence=evidence)
    host = StarPlayoutClock(stage, clock=clock)
    host.enable(owner_approved=True)
    if audible_first:
        audible(stage, plan, clock)
    return clock, stage, plan, host


def arm(host, plan):
    return host.arm(plan, duration_s=1.0, audio_levels=[
        AudioLevel(0.0, .75), AudioLevel(.10, .20),
        AudioLevel(.20, .65), AudioLevel(.40, .0),
    ], fps=30, seed=7)


class StarPlayoutClockTests(unittest.TestCase):
    def test_disabled_by_default_and_requires_explicit_approval(self):
        clock, stage, plan = make_stage()
        audible(stage, plan, clock)
        host = StarPlayoutClock(stage, clock=clock)
        with self.assertRaises(PermissionError):
            host.enable()
        with self.assertRaises(PermissionError):
            host.enable(owner_approved=1)
        self.assertFalse(arm(host, plan))
        host.enable(owner_approved=True)
        self.assertTrue(arm(host, plan))
        self.assertTrue(host.metrics()["enabled"])

    def test_tts_queued_but_not_audible_cannot_arm(self):
        clock, stage, plan, host = make_host(audible_first=False)
        self.assertFalse(arm(host, plan))
        self.assertTrue(stage.queue_audio(plan, now=clock.now))
        self.assertFalse(arm(host, plan))
        self.assertTrue(stage.acknowledge_audible(plan, now=clock.now))
        self.assertTrue(arm(host, plan))

    def test_regular_playback_interpolates_heard_position(self):
        clock, stage, plan, host = make_host()
        self.assertTrue(arm(host, plan))
        self.assertTrue(host.observe_playhead(
            plan, position_s=0.0, sampled_at=clock.now,
        ))
        frame = host.sample(plan)
        self.assertIsNotNone(frame)
        self.assertTrue(host.current(frame))
        self.assertEqual(frame.sequence, plan.sequence)
        self.assertEqual(frame.playhead_s, 0.0)
        self.assertGreater(frame.motion.mouth_open, 0)
        clock.advance(.05)
        self.assertTrue(host.observe_playhead(
            plan, position_s=.05, sampled_at=clock.now,
        ))
        later = host.sample(plan)
        self.assertIsNotNone(later)
        self.assertAlmostEqual(later.motion.at_s, .05)
        self.assertGreater(later.motion.mouth_open, 0)
        self.assertFalse(host.current(frame))  # previous batch revoked
        self.assertTrue(host.current(later))

    def test_no_fabricated_emotion_unverified_game_success(self):
        clock, stage, plan, host = make_host(evidence="unknown")
        self.assertIsNone(plan.expression)
        self.assertTrue(arm(host, plan))
        self.assertTrue(host.observe_playhead(
            plan, position_s=0.0, sampled_at=clock.now,
        ))
        first = host.sample(plan)
        self.assertEqual(first.motion.smile, 0.0)

    def test_no_live_emission_without_audio_position(self):
        _, _, plan, host = make_host()
        self.assertTrue(arm(host, plan))
        self.assertIsNone(host.sample(plan))
        self.assertFalse(host.metrics()["playing"])

    def test_paused_output_produces_no_frames_and_resume_works(self):
        clock, _, plan, host = make_host()
        self.assertTrue(arm(host, plan))
        self.assertTrue(host.observe_playhead(
            plan, position_s=0, sampled_at=clock.now,
        ))
        self.assertIsNotNone(host.sample(plan))
        clock.advance(.1)
        self.assertTrue(host.observe_playhead(
            plan, position_s=.1, sampled_at=clock.now, playing=False,
        ))
        self.assertIsNone(host.sample(plan))
        clock.advance(1.0)
        self.assertTrue(host.observe_playhead(
            plan, position_s=.1, sampled_at=clock.now, playing=True,
        ))
        self.assertIsNotNone(host.sample(plan))

    def test_stalled_output_suppresses_stuck_mouth(self):
        clock, _, plan, host = make_host()
        self.assertTrue(arm(host, plan))
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        self.assertIsNotNone(host.sample(plan))
        clock.advance(.11)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        self.assertIsNotNone(host.sample(plan))
        clock.advance(.11)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        self.assertIsNone(host.sample(plan))
        self.assertGreaterEqual(host.metrics()["stale"], 1)

    def test_old_sample_expires_even_if_last_playhead_nonzero(self):
        clock, _, plan, host = make_host()
        arm(host, plan)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        clock.advance(.161)
        self.assertIsNone(host.sample(plan))

    def test_late_render_batches_rejected(self):
        clock, _, plan, host = make_host()
        arm(host, plan)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        frame = host.sample(plan)
        clock.advance(.151)
        self.assertFalse(host.current(frame))

    def test_rig_reset_after_interrupt_and_stage_disable(self):
        clock, stage, plan, host = make_host()
        arm(host, plan)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        frame = host.sample(plan)
        stage.interrupt(now=clock.now)
        self.assertFalse(host.current(frame))
        self.assertIsNone(host.sample(plan))
        self.assertEqual(host.reset().mouth_open, 0)
        self.assertFalse(host.metrics()["active"])
        self.assertEqual(host.disable().mouth_open, 0)
        self.assertFalse(host.metrics()["enabled"])

    def test_false_playhead_types_and_nan_fail_closed(self):
        bad = (True, -1.0, float("nan"), float("inf"), "0", 1000000)
        for value in bad:
            with self.subTest(value=value):
                clock, _, plan, host = make_host()
                arm(host, plan)
                self.assertFalse(host.observe_playhead(
                    plan, position_s=value, sampled_at=clock.now,
                ))
                self.assertIsNone(host.sample(plan))
                self.assertFalse(host.metrics()["active"])

    def test_future_or_backdated_host_samples_rejected(self):
        for delta in (-1.0, 1.0):
            with self.subTest(delta=delta):
                clock, _, plan, host = make_host()
                arm(host, plan)
                self.assertFalse(host.observe_playhead(
                    plan, position_s=0, sampled_at=clock.now + delta,
                ))
                self.assertIsNone(host.sample(plan))

    def test_playhead_jump_rejected_without_speech_fast_forward(self):
        clock, _, plan, host = make_host()
        arm(host, plan)
        self.assertTrue(host.observe_playhead(
            plan, position_s=0, sampled_at=clock.now,
        ))
        clock.advance(.01)
        self.assertFalse(host.observe_playhead(
            plan, position_s=.7, sampled_at=clock.now,
        ))
        self.assertIsNone(host.sample(plan))

    def test_backward_playhead_rejected_but_minor_audio_jitter_clamped(self):
        clock, _, plan, host = make_host()
        arm(host, plan)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        clock.advance(.12)
        self.assertTrue(host.observe_playhead(
            plan, position_s=.12, sampled_at=clock.now,
        ))
        clock.advance(.01)
        self.assertTrue(host.observe_playhead(
            plan, position_s=.115, sampled_at=clock.now,
        ))
        self.assertAlmostEqual(host.sample(plan).playhead_s, .12)
        clock.advance(.01)
        self.assertFalse(host.observe_playhead(
            plan, position_s=.02, sampled_at=clock.now,
        ))

    def test_repeated_audio_position_clock_reversal_rejected(self):
        clock, _, plan, host = make_host()
        arm(host, plan)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        clock.advance(.01)
        self.assertFalse(host.observe_playhead(
            plan, position_s=0, sampled_at=clock.now - .02,
        ))
        self.assertIsNone(host.sample(plan))

    def test_rearm_while_active_is_rejected(self):
        _, _, plan, host = make_host()
        self.assertTrue(arm(host, plan))
        self.assertFalse(arm(host, plan))
        self.assertTrue(host.metrics()["active"])
        host.reset()
        self.assertTrue(arm(host, plan))

    def test_stale_plan_does_not_reset_replacement(self):
        clock, stage, old, host = make_host()
        arm(host, old)
        stage.interrupt(now=clock.now)
        clock.advance(3.0)
        signal = StreamSignal("game-2", "viewer_question", clock.now,
                              "What's happening?", evidence="unknown")
        self.assertTrue(stage.offer(signal, now=clock.now, moderated=True))
        new = stage.prepare(now=clock.now)
        self.assertIsNotNone(new)
        audible(stage, new, clock)
        self.assertTrue(arm(host, new))
        self.assertFalse(host.observe_playhead(
            old, position_s=0, sampled_at=clock.now,
        ))
        self.assertTrue(host.metrics()["active"])
        self.assertTrue(host.observe_playhead(
            new, position_s=0, sampled_at=clock.now,
        ))
        self.assertIsNotNone(host.sample(new))

    def test_host_opt_in_does_not_override_stage_permission(self):
        clock, stage, plan, host = make_host()
        stage.disable()
        self.assertFalse(arm(host, plan))
        self.assertIsNone(host.sample(plan))

    def test_invalid_settings_and_repeated_invalid_arguments(self):
        clock, stage, plan, host = make_host()
        for settings in (
            {"max_age_s": float("nan")}, {"stall_after_s": 0},
            {"max_playback_rate": 4}, {"max_age_s": True},
        ):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    StarPlayoutClock(stage, clock=clock, **settings)
        arm(host, plan)
        self.assertFalse(host.observe_playhead(
            plan, position_s=0, sampled_at=clock.now, playing=1,
        ))

    def test_concurrent_sample_and_interrupt_cannot_reauthorize_frames(self):
        clock, stage, plan, host = make_host()
        arm(host, plan)
        host.observe_playhead(plan, position_s=0, sampled_at=clock.now)
        with ThreadPoolExecutor(max_workers=6) as pool:
            frames = list(pool.map(lambda _: host.sample(plan), range(70)))
            stage.interrupt(now=clock.now)
            results = list(pool.map(host.current, (f for f in frames if f)))
        self.assertTrue(frames)
        self.assertTrue(all(not x for x in results))


if __name__ == "__main__":
    unittest.main()
