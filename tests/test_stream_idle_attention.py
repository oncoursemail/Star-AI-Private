"""Quiet-time animation is nonverbal, opt-in and invalidated on stage changes."""
from __future__ import annotations

import dataclasses
import math
import unittest

from star.stream_idle_attention import QuietAttention
from star.stream_director import StreamSignal
from star.stream_stage import StarStage


class QuietAttentionTests(unittest.TestCase):
    def test_silence_can_blink_without_faking_speech_or_emotions(self):
        a = QuietAttention()
        frames = [a.sample(now=i / 60, mode="cat") for i in range(60 * 15)]
        self.assertTrue(any(frame.eye_open_left < 0.5 for frame in frames))
        self.assertTrue(all(frame.mouth_open == frame.smile == frame.brow_raise == 0 for frame in frames))
        self.assertTrue(all(frame.at_s == 0 for frame in frames))
        self.assertTrue(all(frame.eye_open_left == frame.eye_open_right for frame in frames))
        self.assertTrue(any(abs(frame.tail_sway) > 0.01 for frame in frames))

    def test_attention_targets_and_smoothing(self):
        a = QuietAttention()
        game = a.sample(now=100, game_active=True)
        self.assertLess(game.gaze_x, 0)
        transitioning = a.sample(now=100.05, viewer_speaking=True)
        self.assertLess(transitioning.gaze_x, 0)  # eyes do not snap to chat
        listening = a.sample(now=101.0, viewer_speaking=True)
        self.assertGreater(listening.gaze_x, 0)
        critical = a.sample(now=102.0, viewer_speaking=True, gameplay_critical=True)
        self.assertLess(critical.gaze_x, 0)
        self.assertEqual(critical.tail_sway, 0)

    def test_reduced_motion_keeps_blink_only(self):
        a = QuietAttention()
        for i in range(600):
            f = a.sample(now=i / 30, game_active=True, mode="puppy", reduced_motion=True)
            self.assertEqual(
                (f.mouth_open, f.gaze_x, f.head_x, f.head_y, f.body_lean, f.hair_sway,
                 f.tail_sway, f.shoulder_lift, f.smile, f.brow_raise),
                (0,) * 10,
            )
        self.assertTrue(0 <= f.eye_open_left <= 1)

    def test_consistent_replay_and_reset(self):
        a, b = QuietAttention(), QuietAttention()
        times = [100, 100.04, 100.1, 103.3, 104.2, 20000]
        one = [a.sample(now=t, mode="cat", game_active=True) for t in times]
        two = [b.sample(now=t, mode="cat", game_active=True) for t in times]
        self.assertEqual(one, two)
        a.reset()
        self.assertEqual(a.sample(now=200, mode="cat", game_active=True),
                         b.__class__().sample(now=200, mode="cat", game_active=True))

    def test_rejects_invalid_or_reversing_clock_and_untrusted_flags(self):
        for now in (-1, float("nan"), float("inf"), 1e15, True, "5"):
            with self.subTest(now=now), self.assertRaises(ValueError):
                QuietAttention().sample(now=now)
        a = QuietAttention()
        a.sample(now=10)
        with self.assertRaises(ValueError):
            a.sample(now=9)
        for kwargs in ({"viewer_speaking": 1}, {"game_active": "false"},
                       {"gameplay_critical": 0}, {"reduced_motion": "no"},
                       {"mode": "dragon"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                QuietAttention().sample(now=10, **kwargs)

    def test_all_outputs_finite_and_bounded_after_large_clock_gap(self):
        a = QuietAttention()
        a.sample(now=0)
        for mode in ("normal", "cat", "puppy"):
            f = a.sample(now=1e12, mode=mode, game_active=True)
            for name, value in dataclasses.asdict(f).items():
                self.assertTrue(math.isfinite(value), name)
                self.assertLessEqual(abs(value), 1, name)


class QuietStageTests(unittest.TestCase):
    def make_stage(self):
        stage = StarStage(clock=lambda: 10.0)
        stage.enable(owner_approved=True)
        return stage

    def test_idle_opt_in_and_superseded_frame(self):
        stage = StarStage(clock=lambda: 10.0)
        self.assertIsNone(stage.idle_motion(now=10))
        stage.enable(owner_approved=True)
        first = stage.idle_motion(now=10.0, game_active=True)
        self.assertIsNotNone(first)
        self.assertTrue(stage.current_idle(first))
        second = stage.idle_motion(now=10.1, viewer_speaking=True)
        self.assertFalse(stage.current_idle(first))
        self.assertTrue(stage.current_idle(second, now=10.1))
        self.assertEqual(second.motion.mouth_open, 0)
        stage.disable()
        self.assertFalse(stage.current_idle(second))

    def test_current_audio_plan_blocks_quiet_frames(self):
        stage = self.make_stage()
        quiet = stage.idle_motion(now=10)
        self.assertTrue(stage.current_idle(quiet))
        self.assertTrue(stage.offer(
            StreamSignal("comment1", "game_success", 10.0,
                         "Host-verified success", evidence="observed"),
            now=10,
        ))
        plan = stage.prepare(now=10)
        self.assertIsNotNone(plan)
        self.assertFalse(stage.current_idle(quiet))
        self.assertIsNone(stage.idle_motion(now=10.1))
        self.assertTrue(stage.queue_audio(plan, now=10.2))
        self.assertTrue(stage.acknowledge_audible(plan, now=10.3))
        self.assertTrue(stage.finish(plan, now=10.5, played_to_end=True))
        next_idle = stage.idle_motion(now=11)
        self.assertTrue(stage.current_idle(next_idle, now=11))
        self.assertFalse(stage.current_idle(quiet))

    def test_configure_and_interrupt_revoke_quiet_authority(self):
        stage = self.make_stage()
        old = stage.idle_motion(now=10)
        stage.configure(mode="cat", reduced_motion=True)
        self.assertFalse(stage.current_idle(old))
        current = stage.idle_motion(now=10)
        self.assertEqual(current.motion.tail_sway, 0)
        self.assertTrue(stage.current_idle(current))
        stage.interrupt(now=10.2)
        self.assertFalse(stage.current_idle(current))

    def test_stage_rejects_invalid_clock_without_authorizing_output(self):
        stage = self.make_stage()
        fresh = stage.idle_motion(now=20)
        self.assertTrue(stage.current_idle(fresh, now=20.1))
        self.assertFalse(stage.current_idle(fresh, now=20.201))
        fresh = stage.idle_motion(now=20.3)
        self.assertFalse(stage.current_idle(fresh, now=20.2))
        fresh = stage.idle_motion(now=20.4)
        with self.assertRaises(ValueError):
            stage.idle_motion(now=19)
        self.assertFalse(stage.current_idle(fresh, now=20.4))
        with self.assertRaises(ValueError):
            stage.idle_motion(now=20.5, viewer_speaking=1)


if __name__ == "__main__":
    unittest.main()
