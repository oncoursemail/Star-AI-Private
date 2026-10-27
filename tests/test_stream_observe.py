"""Offline checks for bounded, opt-in game-observation admission."""
import math
import unittest

from star.stream_budget import StreamTelemetry
from star.stream_observe import FrameCue, ObservationGovernor


def telemetry(*, live=True, free=3500, fps=60, backlog=70):
    return StreamTelemetry(live, True, free, 8192, fps, backlog)


class ObservationGovernorTests(unittest.TestCase):
    def test_off_by_default_and_no_capture_permission(self):
        governor = ObservationGovernor()
        frame = FrameCue(1000, 12)
        self.assertFalse(governor.consider(frame, telemetry(), now_ms=1000,
                                           capture_authorized=True).admitted)
        with self.assertRaises(PermissionError):
            governor.enable()
        governor.enable(owner_approved=True)
        self.assertFalse(governor.consider(frame, telemetry(), now_ms=1000).admitted)
        self.assertEqual(governor.stats()["admitted"], 0)

    def test_valid_initial_frame_and_complete(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        d = g.consider(FrameCue(1000, 1), telemetry(), now_ms=1000,
                       capture_authorized=True)
        self.assertTrue(d.admitted)
        self.assertIsInstance(d.ticket, int)
        self.assertEqual(d.target_fps, 1)
        self.assertTrue(g.stats()["pending"])
        self.assertTrue(g.complete(ticket=d.ticket, now_ms=1300, succeeded=True))
        self.assertEqual(g.stats()["completed"], 1)
        self.assertFalse(g.stats()["pending"])

    def test_opt_in_revocation_invalidates_inflight_ticket(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        first = g.consider(FrameCue(0, 1), telemetry(), now_ms=0,
                           capture_authorized=True)
        g.disable()
        # Revoking the grant does not imply the physical GPU worker stopped.
        with self.assertRaises(RuntimeError):
            g.enable(owner_approved=True)
        self.assertFalse(g.complete(ticket=first.ticket, now_ms=10001, succeeded=True))
        self.assertFalse(g.acknowledge_worker_stopped(
            ticket=first.ticket, now_ms=10001, worker_stopped=False))
        self.assertTrue(g.acknowledge_worker_stopped(
            ticket=first.ticket, now_ms=10002, worker_stopped=True))
        g.enable(owner_approved=True)
        next_ticket = g.consider(FrameCue(10000, 1), telemetry(), now_ms=10000,
                                 capture_authorized=True)
        self.assertNotEqual(first.ticket, next_ticket.ticket)
        self.assertFalse(g.complete(ticket=first.ticket, now_ms=10001, succeeded=True))
        self.assertTrue(g.complete(ticket=next_ticket.ticket, now_ms=10002, succeeded=True))

    def test_no_parallel_inference_admissions(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        one = g.consider(FrameCue(0, 0), telemetry(), now_ms=0,
                         capture_authorized=True)
        two = g.consider(FrameCue(0, 2**64 - 1, "win"), telemetry(), now_ms=200,
                         capture_authorized=True)
        self.assertTrue(one.admitted)
        self.assertFalse(two.admitted)
        self.assertEqual(two.reason, "vision_request_already_in_flight")

    def test_repeated_hash_ignored_until_refresh(self):
        g = ObservationGovernor(refresh_ms=6000)
        g.enable(owner_approved=True)
        one = g.consider(FrameCue(0, 7), telemetry(), now_ms=0,
                         capture_authorized=True)
        self.assertTrue(g.complete(ticket=one.ticket, now_ms=100, succeeded=True))
        repeated = g.consider(FrameCue(1500, 7), telemetry(), now_ms=1500,
                              capture_authorized=True)
        self.assertEqual(repeated.reason, "low_visual_novelty")
        refreshed = g.consider(FrameCue(6100, 7), telemetry(), now_ms=6100,
                               capture_authorized=True)
        self.assertTrue(refreshed.admitted)

    def test_near_duplicate_skipped_but_scene_change_admitted(self):
        g = ObservationGovernor(novelty_bits=8)
        g.enable(owner_approved=True)
        first = g.consider(FrameCue(0, 0), telemetry(), now_ms=0, capture_authorized=True)
        g.complete(ticket=first.ticket, now_ms=100, succeeded=True)
        almost_same = g.consider(FrameCue(1500, 0b1111), telemetry(), now_ms=1500,
                                 capture_authorized=True)
        self.assertFalse(almost_same.admitted)
        changed = g.consider(FrameCue(2200, 0b111111111), telemetry(), now_ms=2200,
                             capture_authorized=True)
        self.assertTrue(changed.admitted)

    def test_urgent_cues_skip_novelty_but_not_spacing(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        first = g.consider(FrameCue(0, 0), telemetry(), now_ms=0, capture_authorized=True)
        g.complete(ticket=first.ticket, now_ms=10, succeeded=True)
        too_soon = g.consider(FrameCue(200, 0, "death"), telemetry(), now_ms=200,
                              capture_authorized=True)
        self.assertEqual(too_soon.reason, "minimum_sampling_interval")
        urgent = g.consider(FrameCue(1100, 0, "death"), telemetry(), now_ms=1100,
                            capture_authorized=True)
        self.assertTrue(urgent.admitted)

    def test_minute_budget_is_real_even_for_repeated_urgent_cues(self):
        g = ObservationGovernor(calls_per_minute=1, burst=1)
        g.enable(owner_approved=True)
        t = telemetry()
        approved = []
        for ms in (0, 1000, 2000, 3000):
            decision = g.consider(FrameCue(ms, ms, "win"), t, now_ms=ms,
                                  capture_authorized=True)
            approved.append(decision.admitted)
            if decision.admitted:
                g.complete(ticket=decision.ticket, now_ms=ms + 10, succeeded=True)
        self.assertEqual(approved, [True, False, False, False])
        again = g.consider(FrameCue(60000, 1, "win"), t, now_ms=60000,
                           capture_authorized=True)
        self.assertTrue(again.admitted)

    def test_resource_pressure_defers_even_urgent(self):
        for metrics in (None, telemetry(free=600), telemetry(fps=20),
                        telemetry(backlog=700)):
            with self.subTest(metrics=metrics):
                g = ObservationGovernor()
                g.enable(owner_approved=True)
                d = g.consider(FrameCue(0, 0, "damage"), metrics,
                               now_ms=0, capture_authorized=True)
                self.assertFalse(d.admitted)
                self.assertEqual(d.reason, "realtime_headroom_unavailable")

    def test_offline_pressure_still_blocks_vision(self):
        for metrics in (telemetry(live=False, free=500),
                        telemetry(live=False, fps=20),
                        telemetry(live=False, backlog=700)):
            with self.subTest(metrics=metrics):
                g = ObservationGovernor()
                g.enable(owner_approved=True)
                d = g.consider(FrameCue(0, 1, "death"), metrics,
                               now_ms=0, capture_authorized=True)
                self.assertEqual(d.reason, "insufficient_game_or_voice_headroom")

    def test_offline_sampling_is_at_most_four_per_second(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        a = g.consider(FrameCue(0, 0), telemetry(live=False), now_ms=0,
                       capture_authorized=True)
        g.complete(ticket=a.ticket, now_ms=1, succeeded=True)
        self.assertFalse(g.consider(FrameCue(200, 2**64-1), telemetry(live=False),
                                    now_ms=200, capture_authorized=True).admitted)
        b = g.consider(FrameCue(250, 2**64-1), telemetry(live=False),
                       now_ms=250, capture_authorized=True)
        self.assertEqual(b.target_fps, 4)
        self.assertTrue(b.admitted)

    def test_failed_request_does_not_advance_duplicate_baseline(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        a = g.consider(FrameCue(0, 1), telemetry(), now_ms=0, capture_authorized=True)
        g.complete(ticket=a.ticket, now_ms=1, succeeded=False)
        b = g.consider(FrameCue(1100, 1), telemetry(), now_ms=1100, capture_authorized=True)
        self.assertTrue(b.admitted)
        self.assertEqual(g.stats()["failed"], 1)

    def test_timeout_quarantines_physical_gpu_worker_until_stopped(self):
        g = ObservationGovernor(ticket_timeout_ms=2000)
        g.enable(owner_approved=True)
        a = g.consider(FrameCue(0, 1), telemetry(), now_ms=0, capture_authorized=True)
        b = g.consider(FrameCue(2001, 2), telemetry(), now_ms=2001, capture_authorized=True)
        self.assertFalse(b.admitted)
        self.assertEqual(b.reason, "vision_worker_stop_unconfirmed")
        self.assertTrue(g.stats()["quarantined"])
        self.assertFalse(g.complete(ticket=a.ticket, now_ms=2002, succeeded=True))
        self.assertFalse(g.acknowledge_worker_stopped(
            ticket=a.ticket + 1, now_ms=2003, worker_stopped=True))
        self.assertFalse(g.acknowledge_worker_stopped(
            ticket=a.ticket, now_ms=2004, worker_stopped=False))
        self.assertTrue(g.acknowledge_worker_stopped(
            ticket=a.ticket, now_ms=2005, worker_stopped=True))
        self.assertFalse(g.acknowledge_worker_stopped(
            ticket=a.ticket, now_ms=2006, worker_stopped=True))
        self.assertFalse(g.stats()["quarantined"])
        next_ = g.consider(FrameCue(2006, 2), telemetry(), now_ms=2006,
                           capture_authorized=True)
        self.assertTrue(next_.admitted)
        self.assertEqual(g.stats()["expired"], 1)
        self.assertEqual(g.stats()["stop_confirmed"], 1)
        self.assertNotEqual(a.ticket, next_.ticket)

    def test_latency_feedback_reduces_sampling_pressure_without_faking_fps(self):
        # Offline nominal sampling is 4 Hz, but a vision call taking 800 ms
        # should not cause another request 250 ms after its admission.
        g = ObservationGovernor(latency_safety_factor=2.0)
        g.enable(owner_approved=True)
        first = g.consider(FrameCue(0, 1), telemetry(live=False), now_ms=0,
                           capture_authorized=True)
        self.assertEqual(first.target_fps, 4.0)
        self.assertTrue(g.complete(ticket=first.ticket, now_ms=800, succeeded=True))
        early = g.consider(FrameCue(1000, 2, "new_scene"), telemetry(live=False),
                           now_ms=1000, capture_authorized=True)
        self.assertEqual(early.reason, "minimum_sampling_interval")
        later = g.consider(FrameCue(1600, 2, "new_scene"), telemetry(live=False),
                           now_ms=1600, capture_authorized=True)
        self.assertTrue(later.admitted)
        self.assertAlmostEqual(later.target_fps, 0.625)
        self.assertTrue(g.complete(ticket=later.ticket, now_ms=1610, succeeded=False))

    def test_timeout_and_consent_revoke_across_sessions_preserve_quarantine(self):
        g = ObservationGovernor(ticket_timeout_ms=2000)
        g.enable(owner_approved=True)
        slow = g.consider(FrameCue(0, 100), telemetry(), now_ms=0,
                          capture_authorized=True)
        # A late successful inference cannot become the freshness baseline.
        self.assertFalse(g.complete(ticket=slow.ticket, now_ms=2001, succeeded=True))
        g.disable()
        with self.assertRaises(RuntimeError):
            g.enable(owner_approved=True)
        self.assertTrue(g.stats()["quarantined"])
        self.assertTrue(g.acknowledge_worker_stopped(
            ticket=slow.ticket, now_ms=2002, worker_stopped=True))
        g.enable(owner_approved=True)
        next_ = g.consider(FrameCue(3000, 100), telemetry(), now_ms=3000,
                           capture_authorized=True)
        self.assertTrue(next_.admitted)
        self.assertFalse(g.complete(ticket=slow.ticket, now_ms=3001, succeeded=True))

    def test_vision_timeouts_never_leak_multiple_inflight_gpu_jobs(self):
        g = ObservationGovernor(ticket_timeout_ms=1000, calls_per_minute=120)
        g.enable(owner_approved=True)
        old = g.consider(FrameCue(0, 1), telemetry(), now_ms=0,
                         capture_authorized=True)
        for at in (1000, 2000, 3000, 5000, 10000):
            blocked = g.consider(FrameCue(at, at), telemetry(), now_ms=at,
                                 capture_authorized=True)
            self.assertFalse(blocked.admitted)
            self.assertEqual(blocked.reason, "vision_worker_stop_unconfirmed")
        self.assertEqual(g.stats()["admitted"], 1)
        self.assertTrue(g.acknowledge_worker_stopped(
            ticket=old.ticket, now_ms=10001, worker_stopped=True))
        self.assertTrue(g.consider(FrameCue(11000, 2), telemetry(), now_ms=11000,
                                   capture_authorized=True).admitted)

    def test_stale_and_future_captured_frames(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        too_old = g.consider(FrameCue(1, 1), telemetry(), now_ms=2000,
                             capture_authorized=True)
        self.assertEqual(too_old.reason, "frame_stale_or_future_dated")
        future = g.consider(FrameCue(4000, 1), telemetry(), now_ms=2050,
                            capture_authorized=True)
        self.assertEqual(future.reason, "frame_stale_or_future_dated")

    def test_monotonic_clock_mandatory(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        g.consider(FrameCue(2, 0), telemetry(), now_ms=2)
        with self.assertRaises(ValueError):
            g.consider(FrameCue(1, 0), telemetry(), now_ms=1)

    def test_frame_validation(self):
        for kwargs in ({"captured_ms": math.nan, "perceptual_hash": 0},
                       {"captured_ms": -1, "perceptual_hash": 0},
                       {"captured_ms": 1, "perceptual_hash": True},
                       {"captured_ms": 1, "perceptual_hash": -1},
                       {"captured_ms": 1, "perceptual_hash": 2**64},
                       {"captured_ms": 1, "perceptual_hash": 0, "cue": "run_shell"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                FrameCue(**kwargs)

    def test_bad_config_and_bad_arguments(self):
        for kwargs in ({"calls_per_minute": 0}, {"burst": 100},
                       {"novelty_bits": -2}, {"ticket_timeout_ms": 5},
                       {"frame_max_age_ms": 0}, {"refresh_ms": math.inf},
                       {"latency_safety_factor": 0},
                       {"latency_safety_factor": 9},
                       {"latency_safety_factor": math.nan}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ObservationGovernor(**kwargs)
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        with self.assertRaises(ValueError):
            g.consider(FrameCue(0, 0), telemetry(), now_ms=0, capture_authorized="yes")
        with self.assertRaises(ValueError):
            g.complete(ticket=True, now_ms=0, succeeded=True)
        with self.assertRaises(TypeError):
            g.consider(object(), telemetry(), now_ms=0)
        for invalid in (True, 0, "1"):
            with self.assertRaises(ValueError):
                g.acknowledge_worker_stopped(
                    ticket=invalid, now_ms=1, worker_stopped=True)
        with self.assertRaises(ValueError):
            g.acknowledge_worker_stopped(
                ticket=1, now_ms=1, worker_stopped="yes")

    def test_counter_output_does_not_expose_frame_fingerprint(self):
        g = ObservationGovernor()
        g.enable(owner_approved=True)
        ticket = g.consider(FrameCue(0, 0xdeadbeef), telemetry(), now_ms=0,
                            capture_authorized=True)
        g.complete(ticket=ticket.ticket, now_ms=1, succeeded=True)
        self.assertTrue(set(g.stats()) <= {"admitted", "completed", "failed",
                                            "expired", "deferred", "pending", "enabled",
                                            "quarantined", "stop_confirmed"})


if __name__ == "__main__":
    unittest.main()
