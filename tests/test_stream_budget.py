"""Deterministic offline tests for the stream resource advisory layer."""
import math
import unittest

from star.stream_budget import StreamTelemetry, advise_workload


def telemetry(*, live=True, game_active=True, free=3500, total=8192,
              fps=75, backlog=50, rehearsal=False):
    return StreamTelemetry(live, game_active, free, total, fps, backlog,
                           private_stream_rehearsal=rehearsal)


class BudgetTests(unittest.TestCase):
    def test_fail_conservative_on_missing_measurements(self):
        self.assertFalse(advise_workload("vision", None).allowed)
        self.assertFalse(advise_workload("training", None).allowed)
        self.assertTrue(advise_workload("speech", None).allowed)

    def test_live_stream_protects_game(self):
        t = telemetry()
        for job in ("training", "render", "research"):
            with self.subTest(job=job):
                self.assertFalse(advise_workload(job, t).allowed)
        self.assertTrue(advise_workload("speech", t).allowed)
        self.assertTrue(advise_workload("gameplay", t).allowed)

    def test_live_vision_is_explicitly_bounded(self):
        result = advise_workload("vision", telemetry())
        self.assertTrue(result.allowed)
        self.assertEqual(result.sample_fps, 1.0)
        self.assertEqual(result.profile, "economical")

    def test_fps_drop_defers_vision(self):
        self.assertFalse(advise_workload("vision", telemetry(fps=44.9)).allowed)

    def test_memory_pressure_defers_vision(self):
        self.assertFalse(advise_workload("vision", telemetry(free=1024)).allowed)

    def test_voice_backlog_defers_vision(self):
        self.assertFalse(advise_workload("vision", telemetry(backlog=351)).allowed)

    def test_offline_training_with_enough_headroom(self):
        self.assertTrue(advise_workload("training", telemetry(live=False, game_active=False)).allowed)
        self.assertFalse(advise_workload("training", telemetry(live=False, free=900)).allowed)

    def test_private_rehearsal_protects_game_even_when_not_broadcasting(self):
        # A private OBS rehearsal is still a latency-sensitive gaming session.
        t = telemetry(live=False, game_active=True, rehearsal=True)
        vision = advise_workload("vision", t)
        self.assertTrue(vision.allowed)
        self.assertEqual(vision.sample_fps, 1.0)
        self.assertEqual(vision.profile, "economical")
        for kind in ("research", "training", "render"):
            with self.subTest(kind=kind):
                self.assertFalse(advise_workload(kind, t).allowed)
        for kind in ("speech", "gameplay"):
            self.assertTrue(advise_workload(kind, t).allowed)

    def test_private_rehearsal_defers_vision_when_contended(self):
        for changes in ({"free": 500}, {"fps": 44.9}, {"backlog": 351}):
            with self.subTest(changes=changes):
                t = telemetry(live=False, game_active=True, rehearsal=True, **changes)
                self.assertFalse(advise_workload("vision", t).allowed)

    def test_offline_idle_vision_uses_faster_cap_only_with_headroom(self):
        idle = telemetry(live=False, game_active=False, free=3500)
        advice = advise_workload("vision", idle)
        self.assertTrue(advice.allowed)
        self.assertEqual(advice.sample_fps, 4.0)
        self.assertEqual(advice.profile, "offline")
        self.assertFalse(advise_workload(
            "vision", telemetry(live=False, game_active=False, free=500)
        ).allowed)

    def test_normal_offline_game_still_supports_training_between_trials(self):
        t = telemetry(live=False, game_active=True)
        self.assertTrue(advise_workload("training", t).allowed)
        self.assertTrue(advise_workload("research", t).allowed)
        self.assertEqual(advise_workload("vision", t).sample_fps, 1.0)

    def test_private_rehearsal_flag_must_be_trusted_explicit_boolean(self):
        with self.assertRaises(ValueError):
            telemetry(live=False, rehearsal=1)
        with self.assertRaises(ValueError):
            telemetry(live=True, rehearsal=True)

    def test_oversized_integer_telemetry_is_rejected_as_invalid_input(self):
        with self.assertRaises(ValueError):
            telemetry(free=10 ** 1000, total=10 ** 1000)

    def test_invalid_telemetry(self):
        cases = [
            {"live": 1}, {"game_active": None}, {"free": -1},
            {"free": 9000}, {"total": 0}, {"fps": math.nan},
            {"backlog": math.inf}, {"fps": True}, {"free": "high"}
        ]
        for changes in cases:
            kwargs = {"live": True, "game_active": True, "free": 3500,
                      "total": 8192, "fps": 75, "backlog": 50}
            kwargs.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                telemetry(**kwargs)

    def test_unknown_workload_and_telemetry_type(self):
        with self.assertRaises(ValueError):
            advise_workload("execute_host_command", telemetry())
        with self.assertRaises(TypeError):
            advise_workload("vision", object())


if __name__ == "__main__":
    unittest.main()
