"""Deterministic offline QoS policy tests; no streaming/GPU measurements."""
import unittest

from star.stream_load_governor import (
    Admission, GovernorPolicy, StreamLoadGovernor, StreamSample, WorkRequest,
)


def sample(seq=1, ts=None, streaming=True, gaming=True, fps=60,
           voice=100, dropped=0, vram=2048, underruns=0):
    return StreamSample(seq, seq * 100 if ts is None else ts, streaming,
                        gaming, fps, voice, dropped, vram, underruns)


class StreamGovernorTests(unittest.TestCase):
    def setUp(self):
        self.g = StreamLoadGovernor(GovernorPolicy(recover_windows=2))

    def admit(self, kind="research", now=200, ok=True, vram=0):
        return self.g.admit(WorkRequest(kind, vram), now_ms=now,
                            owner_approved=ok)

    def test_untrusted_telemetry_denied(self):
        with self.assertRaises(PermissionError):
            self.g.observe(sample())

    def test_cold_start_fail_closed(self):
        decision = self.admit("voice")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "telemetry_unavailable")
        self.assertEqual(decision.tier, "unknown")

    def test_owner_approval_required(self):
        self.g.observe(sample(), trusted_host=True)
        self.assertEqual(self.admit("voice", ok=False).reason, "owner_approval_required")

    def test_live_foreground_allowed_even_under_pressure(self):
        self.g.observe(sample(fps=20, vram=2048), trusted_host=True)
        for kind in ("voice", "game_control", "game_vision", "chat"):
            self.assertTrue(self.admit(kind).allowed)
        self.assertEqual(self.admit("chat").chat_token_ceiling, 64)
        self.assertEqual(self.admit("game_vision").vision_stride, 4)

    def test_active_stream_blocks_background(self):
        self.g.observe(sample(), trusted_host=True)
        for kind in ("night_school", "research", "asset_render"):
            d = self.admit(kind)
            self.assertFalse(d.allowed)
            self.assertEqual(d.reason, "interactive_workload_priority")

    def test_game_only_blocks_background(self):
        self.g.observe(sample(streaming=False), trusted_host=True)
        self.assertFalse(self.admit("asset_render").allowed)

    def test_stream_only_blocks_background(self):
        self.g.observe(sample(gaming=False), trusted_host=True)
        self.assertFalse(self.admit("research").allowed)

    def test_idle_recovers_and_admits_background(self):
        self.g.observe(sample(streaming=False, gaming=False), trusted_host=True)
        self.g.observe(sample(seq=2, streaming=False, gaming=False), trusted_host=True)
        d = self.admit("night_school", now=220)
        self.assertTrue(d.allowed)
        self.assertEqual(d.reason, "idle_advisory")
        self.assertEqual(d.tier, "normal")

    def test_idle_but_under_pressure_blocks_background(self):
        self.g.observe(sample(streaming=False, gaming=False, vram=600), trusted_host=True)
        self.assertEqual(self.admit("research").reason, "resource_pressure")

    def test_pressure_enters_immediately_after_normal(self):
        self.g.observe(sample(), trusted_host=True)
        self.g.observe(sample(seq=2), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "normal")
        self.g.observe(sample(seq=3, fps=12), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "pressure")

    def test_recovery_has_hysteresis(self):
        self.g.observe(sample(fps=5), trusted_host=True)
        self.g.observe(sample(seq=2), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "pressure")
        self.g.observe(sample(seq=3), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "normal")

    def test_voice_latency_trips_only_while_streaming(self):
        self.g.observe(sample(voice=1500), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "pressure")
        self.g.observe(sample(seq=2, streaming=False, voice=1500), trusted_host=True)
        self.g.observe(sample(seq=3, streaming=False, voice=1500), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "normal")

    def test_dropped_frames_and_underruns_pressure(self):
        self.g.observe(sample(dropped=1.2), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "pressure")
        self.g.observe(sample(seq=2, underruns=1), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "pressure")

    def test_stale_telemetry_denies_even_game(self):
        self.g.observe(sample(), trusted_host=True)
        self.assertEqual(self.admit("voice", now=3101).reason, "telemetry_unavailable")

    def test_sample_timestamp_regression_rejected(self):
        self.g.observe(sample(seq=1, ts=100), trusted_host=True)
        with self.assertRaises(ValueError):
            self.g.observe(sample(seq=2, ts=100), trusted_host=True)
        self.assertEqual(self.g.summary()["sample_seq"], 1)

    def test_replayed_samples_rejected(self):
        self.g.observe(sample(), trusted_host=True)
        with self.assertRaises(ValueError):
            self.g.observe(sample(), trusted_host=True)

    def test_clock_regression_rejected(self):
        self.g.observe(sample(), trusted_host=True)
        self.admit("voice", now=350)
        with self.assertRaises(ValueError):
            self.admit("voice", now=349)

    def test_vram_reserve_blocks_overallocation(self):
        self.g.observe(sample(vram=1000), trusted_host=True)
        self.assertEqual(self.admit("voice", vram=600).reason,
                         "insufficient_vram_headroom")
        self.assertTrue(self.admit("voice", vram=400).allowed)

    def test_reserve_exact_boundary(self):
        self.g.observe(sample(vram=1024), trusted_host=True)
        self.assertTrue(self.admit("voice", vram=512).allowed)

    def test_background_idle_pressure_from_low_vram(self):
        self.g.observe(sample(streaming=False, gaming=False, vram=500), trusted_host=True)
        self.assertEqual(self.admit("night_school").reason, "insufficient_vram_headroom")

    def test_bounded_request_and_unknown_denial(self):
        for kind in ("", "internet", "sudo", "OBS.start"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                WorkRequest(kind)
        for bad in (-1, True, 65537, 1.0):
            with self.subTest(vram=bad), self.assertRaises(ValueError):
                WorkRequest("voice", bad)

    def test_samples_reject_nan_inf_bool_and_bad_ranges(self):
        for bad in (float("nan"), float("inf"), -1, 501, True):
            with self.subTest(fps=bad), self.assertRaises(ValueError):
                sample(fps=bad)
        for kw in ({"dropped": 101}, {"voice": -1}, {"underruns": True},
                   {"ts": -1}, {"streaming": 3}, {"vram": -3}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                sample(**kw)

    def test_policy_rejects_invalid_ranges(self):
        for kw in ({"min_game_fps": float("nan")}, {"max_voice_p95_ms": 0},
                   {"stale_after_ms": True}, {"recover_windows": 0},
                   {"vram_reserve_mb": -1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                GovernorPolicy(**kw)

    def test_no_claim_of_executing_jobs(self):
        self.g.observe(sample(), trusted_host=True)
        self.assertIsInstance(self.admit("voice"), Admission)
        self.assertEqual(self.g.summary()["admitted_requests"], 1)
        self.assertEqual(self.g.summary()["rejected_requests"], 0)

    def test_boolean_not_timestamp_or_sequence(self):
        with self.assertRaises(ValueError):
            sample(seq=True)
        with self.assertRaises(ValueError):
            sample(ts=True)
        with self.assertRaises(ValueError):
            self.g.admit(WorkRequest("voice"), now_ms=True, owner_approved=True)

    def test_late_host_sample_cannot_go_back_in_time(self):
        self.g.observe(sample(), trusted_host=True)
        self.admit("voice", now=500)
        with self.assertRaises(ValueError):
            self.g.observe(sample(seq=2, ts=200), trusted_host=True)

    def test_recovery_does_not_grant_permission(self):
        self.g.observe(sample(streaming=False, gaming=False), trusted_host=True)
        self.g.observe(sample(seq=2, streaming=False, gaming=False), trusted_host=True)
        self.assertFalse(self.admit("night_school", ok=False).allowed)

    def test_game_fps_only_matters_when_gaming(self):
        self.g.observe(sample(streaming=False, gaming=False, fps=0), trusted_host=True)
        self.g.observe(sample(seq=2, streaming=False, gaming=False, fps=0), trusted_host=True)
        self.assertEqual(self.g.summary()["tier"], "normal")


if __name__ == "__main__":
    unittest.main()
