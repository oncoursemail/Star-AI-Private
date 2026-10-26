"""Offline host-milestone and p95 speech latency regression tests."""
import dataclasses
import math
import unittest

from star.stream_latency import LatencyWindow, LiveTurn


def sample(elapsed=800, *, started=10000):
    return LiveTurn(started_ms=started, perception_done_ms=started + elapsed * .25,
                    first_token_ms=started + elapsed * .5,
                    tts_chunk_ms=started + elapsed * .75,
                    first_audible_ms=started + elapsed)


class StreamLatencyTests(unittest.TestCase):
    def test_completed_trace_has_end_to_end_latency(self):
        window = LatencyWindow(minimum_samples=1)
        window.add(sample(800))
        report = window.summary()
        self.assertEqual(report["first_audible_p50_ms"], 800)
        self.assertEqual(report["first_audible_p95_ms"], 800)
        self.assertEqual(report["stage_p95_ms"]["language"], 200)
        self.assertEqual(report["stage_p95_ms"]["voice_generation"], 200)
        self.assertEqual(report["assessment"], "first_audible_latency_within_target")
        self.assertEqual(report["largest_measured_stage_p95"], "perception")

    def test_direct_speech_to_speech_needs_no_text_stages(self):
        window = LatencyWindow(minimum_samples=1)
        window.add(LiveTurn(started_ms=100, first_audible_ms=250))
        report = window.summary()
        self.assertEqual(report["first_audible_p95_ms"], 150)
        self.assertIsNone(report["largest_measured_stage_p95"])

    def test_incomplete_records_and_interruptions_excluded_from_latency(self):
        window = LatencyWindow(minimum_samples=1)
        window.add(LiveTurn(started_ms=100, status="cancelled", perception_done_ms=200))
        window.add(LiveTurn(started_ms=200, status="failed"))
        report = window.summary()
        self.assertEqual(report["cancelled"], 1)
        self.assertEqual(report["failed"], 1)
        self.assertIsNone(report["first_audible_p95_ms"])
        self.assertEqual(report["assessment"], "insufficient_completed_samples")

    def test_p95_nearest_rank_and_outlier_detection(self):
        window = LatencyWindow(minimum_samples=20, speech_budget_ms=900)
        for i in range(20):
            window.add(sample(400 if i < 18 else (1000 if i == 18 else 1500)))
        report = window.summary()
        self.assertEqual(report["first_audible_p50_ms"], 400)
        self.assertEqual(report["first_audible_p95_ms"], 1000)
        self.assertEqual(report["first_audible_over_budget"], 2)
        self.assertEqual(report["assessment"], "first_audible_latency_above_target")

    def test_small_samples_are_never_certified(self):
        window = LatencyWindow(minimum_samples=20)
        for _ in range(19):
            window.add(sample(40))
        self.assertEqual(window.summary()["assessment"], "insufficient_completed_samples")

    def test_stage_p95_requires_stage_coverage(self):
        window = LatencyWindow(minimum_samples=2)
        window.add(sample())
        window.add(LiveTurn(started_ms=100, first_audible_ms=450))
        report = window.summary()
        self.assertEqual(report["stage_samples"]["language"], 1)
        self.assertIsNone(report["largest_measured_stage_p95"])

    def test_capacity_is_hard_bound_and_old_turns_evict(self):
        window = LatencyWindow(capacity=10, minimum_samples=5)
        for i in range(30):
            window.add(sample(elapsed=i * 10 + 100))
        report = window.summary()
        self.assertEqual(report["turns"], 10)
        self.assertEqual(report["first_audible_p95_ms"], 390)
        window.clear()
        self.assertEqual(window.summary()["turns"], 0)

    def test_no_text_audio_viewer_ids_in_models_or_report(self):
        names = {f.name for f in dataclasses.fields(LiveTurn)}
        self.assertEqual(names, {"started_ms", "first_audible_ms", "perception_done_ms",
                                 "first_token_ms", "tts_chunk_ms", "status"})
        self.assertNotIn("secret", repr(LatencyWindow().summary()))

    def test_invalid_types_on_turn(self):
        for value in (-1, "100", True, math.inf, math.nan, 1e15):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LiveTurn(started_ms=value, first_audible_ms=100)
        with self.assertRaises(ValueError):
            LiveTurn(started_ms=0, first_audible_ms=1, status="unknown")
        with self.assertRaises(ValueError):
            LiveTurn(started_ms=0, status="completed")

    def test_timestamp_regression_and_max_horizon_rejected(self):
        with self.assertRaises(ValueError):
            LiveTurn(started_ms=100, first_audible_ms=99)
        with self.assertRaises(ValueError):
            LiveTurn(started_ms=0, first_audible_ms=120001)
        with self.assertRaises(ValueError):
            LiveTurn(started_ms=0, perception_done_ms=300, first_token_ms=299,
                     first_audible_ms=400)

    def test_cross_machine_unsynced_stamps_are_invalid_when_out_of_order(self):
        with self.assertRaises(ValueError):
            LiveTurn(started_ms=1000000, first_audible_ms=120, status="completed")

    def test_fast_survivors_do_not_hide_failed_and_cancelled_turns(self):
        window = LatencyWindow(minimum_samples=20, minimum_completion_ratio=0.95)
        for _ in range(20):
            window.add(sample(100))
        for _ in range(10):
            window.add(LiveTurn(started_ms=100, status="failed"))
        for _ in range(10):
            window.add(LiveTurn(started_ms=100, status="cancelled"))
        report = window.summary()
        self.assertEqual(report["first_audible_p95_ms"], 100)
        self.assertEqual(report["completion_ratio"], 0.5)
        self.assertEqual(report["first_audible_budget_success_ratio"], 0.5)
        self.assertEqual(report["assessment"], "incomplete_audible_coverage")
        self.assertIn("conditional on completed", report["basis"])

    def test_one_acceptable_interruption_does_not_disqualify_reliable_session(self):
        window = LatencyWindow(minimum_samples=20, minimum_completion_ratio=.95)
        for _ in range(20):
            window.add(sample(200))
        window.add(LiveTurn(started_ms=123, status="cancelled"))
        report = window.summary()
        self.assertEqual(report["assessment"], "first_audible_latency_within_target")
        self.assertEqual(report["completion_ratio"], 0.9524)
        self.assertEqual(report["first_audible_budget_success_ratio"], 0.9524)

    def test_budget_success_ratio_counts_slow_audible_and_failed_attempts(self):
        window = LatencyWindow(minimum_samples=2, minimum_completion_ratio=.5)
        window.add(sample(100))
        window.add(sample(1200))
        window.add(LiveTurn(started_ms=10, status="failed"))
        window.add(LiveTurn(started_ms=10, status="cancelled"))
        report = window.summary()
        self.assertEqual(report["completion_ratio"], .5)
        self.assertEqual(report["first_audible_budget_success_ratio"], .25)
        self.assertEqual(report["assessment"], "first_audible_latency_above_target")

    def test_completion_reliability_requires_nonempty_actual_observations(self):
        report = LatencyWindow(minimum_samples=1).summary()
        self.assertEqual(report["completion_ratio"], 0.0)
        self.assertEqual(report["first_audible_budget_success_ratio"], 0.0)
        self.assertEqual(report["assessment"], "insufficient_completed_samples")

    def test_invalid_window_params(self):
        for kwargs in ({"capacity": 0}, {"capacity": True},
                       {"minimum_samples": 0}, {"minimum_samples": 9999},
                       {"speech_budget_ms": math.inf}, {"speech_budget_ms": 0},
                       {"minimum_completion_ratio": math.nan},
                       {"minimum_completion_ratio": math.inf},
                       {"minimum_completion_ratio": True},
                       {"minimum_completion_ratio": .49},
                       {"minimum_completion_ratio": 1.01}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LatencyWindow(**kwargs)
        with self.assertRaises(TypeError):
            LatencyWindow().add({"started_ms": 0})


if __name__ == "__main__":
    unittest.main()
