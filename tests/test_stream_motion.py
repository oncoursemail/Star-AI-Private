"""Offline tests for bounded, audio-driven original Star avatar rig targets."""
import dataclasses
import math
import unittest

from star.stream_motion import (
    AudioLevel, ExpressionCue, MAX_AUDIO_SAMPLES, MAX_CUES,
    neutral_frame, plan_motion,
)


def make(**overrides):
    kwargs = {"duration_s": 3.5, "audio_levels": (AudioLevel(0.0, 0.0),)}
    kwargs.update(overrides)
    return plan_motion(**kwargs)


class StreamMotionTests(unittest.TestCase):
    def test_silence_never_moves_mouth(self):
        frames = make()
        self.assertTrue(all(frame.mouth_open == 0 for frame in frames))
        self.assertTrue(all(frame.ear_left == frame.ear_right == frame.tail_sway == 0 for frame in frames))

    def test_audio_started_later_cannot_preanimate(self):
        frames = make(duration_s=2, audio_levels=(AudioLevel(0.5, 1),))
        self.assertTrue(all(frame.mouth_open == 0 for frame in frames if frame.at_s < 0.5))
        self.assertGreater(frames[15].mouth_open, 0)
        self.assertLess(frames[-1].mouth_open, 0.03)

    def test_audio_dropout_falls_to_silence(self):
        frames = make(audio_levels=(AudioLevel(0, 1),))
        self.assertGreater(frames[0].mouth_open, 0.4)
        self.assertEqual(frames[-1].mouth_open, 0.0)

    def test_smoothing_avoids_instantaneous_open_close(self):
        frames = make(duration_s=1, audio_levels=(AudioLevel(0, 1), AudioLevel(0.2, 0)))
        self.assertTrue(0 < frames[0].mouth_open < 1)
        self.assertLess(frames[7].mouth_open, frames[1].mouth_open)

    def test_laughter_has_lift_only_with_cue(self):
        plain = make(cues=())
        laughing = make(cues=(ExpressionCue(0, "laugh"),))
        self.assertGreater(laughing[0].smile, plain[0].smile)
        self.assertGreater(laughing[0].shoulder_lift, plain[0].shoulder_lift)
        self.assertLess(laughing[-1].smile, 0.05)

    def test_surprise_and_joy_independent(self):
        surprise = make(cues=(ExpressionCue(0, "surprise"),))
        joy = make(cues=(ExpressionCue(0, "joy"),))
        self.assertGreater(surprise[0].brow_raise, 0)
        self.assertEqual(surprise[0].smile, 0)
        self.assertGreater(joy[0].smile, 0)
        self.assertEqual(joy[0].brow_raise, 0)

    def test_focus_is_bounded_gaze_not_camera_control(self):
        frames = make(cues=(ExpressionCue(0, "focus", target_x=-1),))
        self.assertLess(frames[0].gaze_x, 0)
        self.assertEqual(frames[0].ear_left, 0)

    def test_cat_and_puppy_mode_do_not_affect_normal_rig(self):
        normal = make(cues=(ExpressionCue(0, "surprise"),))
        cat = make(mode="cat", cues=(ExpressionCue(0, "surprise"),))
        puppy = make(mode="puppy", cues=(ExpressionCue(0, "surprise"),))
        self.assertEqual(normal[0].ear_left, 0)
        self.assertGreater(cat[0].ear_left, 0)
        self.assertGreater(puppy[0].ear_left, 0)
        self.assertNotEqual(cat[20].tail_sway, 0)
        self.assertNotEqual(puppy[20].tail_sway, 0)

    def test_reduced_motion_keeps_lips_and_expression_without_sway(self):
        frames = make(mode="cat", reduced_motion=True,
                      audio_levels=(AudioLevel(0, 0.9),),
                      cues=(ExpressionCue(0, "laugh"),))
        self.assertGreater(frames[0].mouth_open, 0)
        self.assertGreater(frames[0].smile, 0)
        for f in frames:
            self.assertEqual((f.head_x, f.head_y, f.body_lean, f.shoulder_lift,
                              f.ear_left, f.ear_right, f.tail_sway, f.hair_sway),
                             (0,) * 8)

    def test_determinism_is_local(self):
        one = make(mode="puppy", seed=73)
        two = make(mode="puppy", seed=73)
        other = make(mode="puppy", seed=74)
        self.assertEqual(one, two)
        self.assertNotEqual(one, other)

    def test_blink_is_subtle_and_not_random_per_call(self):
        frames = make(duration_s=12)
        self.assertTrue(any(f.eye_open_left < 0.9 for f in frames))
        self.assertEqual([f.eye_open_left for f in frames],
                         [f.eye_open_right for f in frames])
        self.assertTrue(all(0 <= f.eye_open_left <= 1 for f in frames))

    def test_frame_count_and_no_extrapolation(self):
        frames = make(duration_s=15, fps=60)
        self.assertEqual(len(frames), 901)
        self.assertEqual(frames[-1].at_s, 15.0)

    def test_neutral_reset_suppresses_physics_and_mouth(self):
        neutral = neutral_frame(1.2)
        self.assertEqual(neutral.mouth_open, 0)
        self.assertEqual(neutral.eye_open_left, 1)
        self.assertEqual(neutral.tail_sway, 0)

    def test_invalid_duration_types_and_values(self):
        for value in (0, -1, 16, True, "1", math.nan, math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                make(duration_s=value)

    def test_invalid_settings(self):
        for changes in ({"fps": 0}, {"fps": 29}, {"fps": True}, {"mode": "bird"},
                        {"reduced_motion": 1}, {"seed": -1}, {"seed": 2**33},
                        {"seed": 1.5}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                make(**changes)

    def test_audio_validation_and_ordering(self):
        for samples in (
            (AudioLevel(0, 0), AudioLevel(0, 1)),
            (AudioLevel(0.3, 0), AudioLevel(0.2, 1)),
            (AudioLevel(3.6, 0),),
            ("not-a-sample",),
            tuple(AudioLevel(i / 100, 0) for i in range(MAX_AUDIO_SAMPLES + 1)),
        ):
            with self.subTest(length=len(samples)), self.assertRaises(ValueError):
                make(audio_levels=samples)
        for args in ((-1, 0), (0, 1.1), (math.nan, 0), (0, True)):
            with self.assertRaises(ValueError):
                AudioLevel(*args)

    def test_cue_validation_and_ordering(self):
        for cues in (
            (ExpressionCue(0.1, "joy"), ExpressionCue(0.1, "laugh")),
            (ExpressionCue(0.5, "joy"), ExpressionCue(0.1, "laugh")),
            (ExpressionCue(3.6, "joy"),),
            (None,),
            tuple(ExpressionCue(i / 100, "joy") for i in range(MAX_CUES + 1)),
        ):
            with self.subTest(length=len(cues)), self.assertRaises(ValueError):
                make(cues=cues)
        for kwargs in ({"at_s": 0, "kind": "invented"},
                       {"at_s": 0, "kind": "joy", "strength": math.nan},
                       {"at_s": 0, "kind": "joy", "target_x": 2}):
            with self.assertRaises(ValueError):
                ExpressionCue(**kwargs)

    def test_every_parameter_bounded_and_finite(self):
        frames = make(mode="cat", audio_levels=(AudioLevel(0, 1),),
                      cues=(ExpressionCue(0, "laugh"), ExpressionCue(0.2, "nod"),
                            ExpressionCue(0.4, "surprise")))
        for f in frames:
            for name, value in dataclasses.asdict(f).items():
                self.assertTrue(math.isfinite(value), name)
                if name != "at_s":
                    self.assertTrue(-1 <= value <= 1, name)


if __name__ == "__main__":
    unittest.main()
