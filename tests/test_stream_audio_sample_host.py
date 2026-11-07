"""Deterministic, device-free tests for consumed-PCM-to-avatar synchronization."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import unittest

from star.stream_audio_sample_host import DeviceAudibleSampleHost
from star.stream_director import StreamSignal
from star.stream_motion import AudioLevel, neutral_frame
from star.stream_playout_clock import StarPlayoutClock
from star.stream_stage import StarStage


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def fixture(*, enabled=True):
    clk = Clock()
    stage = StarStage(clock=clk)
    stage.enable(owner_approved=True, mode="cat")
    assert stage.offer(StreamSignal(
        "game-1", "game_success", clk.now, "Real checkpoint", evidence="observed",
    ), now=clk.now)
    plan = stage.prepare(now=clk.now)
    assert plan is not None
    assert stage.queue_audio(plan, now=clk.now)
    assert stage.acknowledge_audible(plan, now=clk.now)
    playout = StarPlayoutClock(stage, clock=clk)
    playout.enable(owner_approved=True)
    assert playout.arm(plan, duration_s=1.0, audio_levels=[
        AudioLevel(0, .72), AudioLevel(.1, .65),
        AudioLevel(.2, .4), AudioLevel(.4, 0.0),
    ])
    host = DeviceAudibleSampleHost(playout)
    if enabled:
        host.enable(owner_approved=True)
    return clk, stage, plan, playout, host


def bind(host, plan, *, sample_rate_hz=48000, total_samples=48000):
    return host.bind(plan, sample_rate_hz=sample_rate_hz, total_samples=total_samples)


def played(host, ticket, *, samples=2400, clock=None, playing=True):
    return host.report_played(
        ticket, played_samples=samples,
        sampled_at=clock.now, playing=playing,
    )


class DeviceAudibleSampleHostTests(unittest.TestCase):
    def test_disabled_by_default_and_owner_opt_in(self):
        _, _, plan, playout, host = fixture(enabled=False)
        self.assertIsNone(bind(host, plan))
        with self.assertRaises(PermissionError):
            host.enable()
        with self.assertRaises(PermissionError):
            host.enable(owner_approved=1)
        host.enable(owner_approved=True)
        self.assertIsNotNone(bind(host, plan))
        self.assertEqual(playout.duration_if_armed(plan), 1)

    def test_previously_armed_track_is_required(self):
        _, _, plan, playout, host = fixture()
        playout.reset()
        self.assertIsNone(bind(host, plan))

    def test_identity_bound_to_exact_plan(self):
        clk, stage, plan, playout, host = fixture()
        other = StarStage(clock=clk)
        other.enable(owner_approved=True)
        self.assertTrue(other.offer(StreamSignal(
            "game-2", "game_success", clk.now, "Another", evidence="observed",
        ), now=clk.now))
        other_plan = other.prepare(now=clk.now)
        self.assertIsNone(bind(host, other_plan))
        self.assertIsNotNone(bind(host, plan))

    def test_first_zero_frame_does_not_animate_queued_speech(self):
        clk, _, plan, playout, host = fixture()
        ticket = bind(host, plan)
        self.assertTrue(played(host, ticket, samples=0, clock=clk))
        self.assertIsNone(host.sample(ticket))
        clk.advance(.03)
        self.assertTrue(played(host, ticket, samples=1440, clock=clk))
        frame = host.sample(ticket)
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(frame.playhead_s, .03)
        self.assertTrue(host.current(ticket, frame))

    def test_exact_pcm_cursor_controls_mouth_and_expression(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        self.assertTrue(played(host, ticket, clock=clk))
        frame = host.sample(ticket)
        self.assertIsNotNone(frame)
        self.assertAlmostEqual(frame.playhead_s, .05)
        self.assertGreater(frame.motion.mouth_open, 0)
        self.assertTrue(host.current(ticket, frame))

    def test_sampled_frame_requires_fresh_render_boundary(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        a = host.sample(ticket)
        clk.advance(.05)
        played(host, ticket, samples=4800, clock=clk)
        self.assertFalse(host.current(ticket, a))
        b = host.sample(ticket)
        self.assertTrue(host.current(ticket, b))
        self.assertFalse(host.current(ticket, replace(b)))
        clk.advance(.151)
        self.assertFalse(host.current(ticket, b))

    def test_pause_and_resume_do_not_force_fake_movement(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        self.assertIsNotNone(host.sample(ticket))
        clk.advance(.04)
        self.assertTrue(played(host, ticket, samples=2400, clock=clk, playing=False))
        self.assertIsNone(host.sample(ticket))
        clk.advance(.5)
        self.assertTrue(played(host, ticket, samples=4800, clock=clk))
        self.assertIsNotNone(host.sample(ticket))

    def test_stale_device_callback_cannot_keep_animating(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        clk.advance(.21)
        self.assertIsNone(host.sample(ticket))

    def test_stuck_device_counter_is_not_playing_audio(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        clk.advance(.12)
        self.assertTrue(played(host, ticket, clock=clk))
        clk.advance(.10)
        self.assertTrue(played(host, ticket, clock=clk))
        self.assertIsNone(host.sample(ticket))

    def test_drain_neutralizes_last_phoneme(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        self.assertTrue(played(host, ticket, samples=2400, clock=clk))
        clk.advance(.95)
        self.assertTrue(played(host, ticket, samples=48000, clock=clk))
        self.assertIsNone(host.sample(ticket))
        self.assertEqual(host.metrics()["finished"], 1)
        self.assertTrue(played(host, ticket, samples=48000, clock=clk))
        self.assertEqual(host.metrics()["finished"], 1)

    def test_disallow_second_epoch_without_physical_stop(self):
        _, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        self.assertIsNone(bind(host, plan))
        self.assertEqual(host.metrics()["bound"], 1)
        self.assertIsNotNone(ticket)

    def test_stale_epoch_does_not_cancel_new_voice(self):
        clk, _, plan, playout, host = fixture()
        old = bind(host, plan)
        self.assertEqual(host.stop(old, output_stopped_and_flushed=True), neutral_frame())
        self.assertTrue(playout.arm(plan, duration_s=1, audio_levels=[
            AudioLevel(0, .6), AudioLevel(.1, .4),
        ]))
        new = bind(host, plan)
        self.assertIsNotNone(new)
        self.assertFalse(played(host, old, clock=clk))
        self.assertTrue(played(host, new, clock=clk))
        self.assertTrue(host.current(new, host.sample(new)))
        self.assertFalse(host.current(old, host.sample(new)))
        self.assertEqual(host.metrics()["stale_epochs"], 1)

    def test_stop_requires_actual_device_acknowledgement(self):
        _, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        with self.assertRaises(RuntimeError):
            host.stop(ticket, output_stopped_and_flushed=False)
        self.assertTrue(host.metrics()["active"])
        self.assertEqual(host.stop(ticket, output_stopped_and_flushed=True), neutral_frame())
        self.assertFalse(host.metrics()["active"])

    def test_disable_requires_flush_and_clears_all_authorizations(self):
        clk, _, plan, playout, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        frame = host.sample(ticket)
        with self.assertRaises(RuntimeError):
            host.disable()
        self.assertTrue(host.current(ticket, frame))
        self.assertEqual(host.disable(output_stopped_and_flushed=True), neutral_frame())
        self.assertFalse(playout.metrics()["enabled"])
        self.assertFalse(host.current(ticket, frame))
        self.assertFalse(played(host, ticket, clock=clk))

    def test_invalid_samples_fail_closed(self):
        for value in (-1, 48001, 1.0, True, None, "500", float("nan")):
            with self.subTest(value=value):
                clk, _, plan, _, host = fixture()
                ticket = bind(host, plan)
                self.assertFalse(played(host, ticket, samples=value, clock=clk))
                self.assertFalse(host.metrics()["active"])

    def test_missing_boolean_playing_fails_closed(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        self.assertFalse(host.report_played(
            ticket, played_samples=2000,
            sampled_at=clk.now, playing=1,
        ))
        self.assertIsNone(host.sample(ticket))

    def test_backward_hardware_sample_counter_fails_closed(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        clk.advance(.01)
        self.assertFalse(played(host, ticket, samples=2300, clock=clk))
        self.assertIsNone(host.sample(ticket))

    def test_implausible_consumption_rate_fails_closed(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, samples=500, clock=clk)
        clk.advance(.001)
        self.assertFalse(played(host, ticket, samples=15000, clock=clk))
        self.assertEqual(host.metrics()["rejected"], 1)

    def test_stale_or_future_device_timestamps_fail_closed(self):
        for offset in (-1, 1):
            with self.subTest(offset=offset):
                clk, _, plan, _, host = fixture()
                ticket = bind(host, plan)
                self.assertFalse(host.report_played(
                    ticket, played_samples=1000,
                    sampled_at=clk.now + offset,
                ))
                self.assertIsNone(host.sample(ticket))

    def test_old_plan_does_not_survive_stage_interrupt(self):
        clk, stage, plan, _, host = fixture()
        ticket = bind(host, plan)
        stage.interrupt(now=clk.now)
        self.assertFalse(played(host, ticket, clock=clk))
        self.assertIsNone(host.sample(ticket))

    def test_no_pcm_count_mismatch_or_unbounded_allocations(self):
        for samples in (47000, 0, -1, 2880001, True, 1.5):
            with self.subTest(samples=samples):
                _, _, plan, _, host = fixture()
                with self.assertRaises(ValueError):
                    bind(host, plan, total_samples=samples)

    def test_reject_invalid_sample_rates(self):
        for rate in (-1, 0, 7999, 192001, True, 48000.0, "48000"):
            with self.subTest(rate=rate):
                _, _, plan, _, host = fixture()
                with self.assertRaises(ValueError):
                    bind(host, plan, sample_rate_hz=rate)

    def test_valid_non_48k_source(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan, sample_rate_hz=44100, total_samples=44100)
        self.assertTrue(played(host, ticket, samples=2205, clock=clk))
        self.assertAlmostEqual(host.sample(ticket).playhead_s, .05)

    def test_forged_identical_epoch_is_not_valid_authorization(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        fake = replace(ticket)
        self.assertFalse(played(host, fake, clock=clk))
        self.assertTrue(played(host, ticket, clock=clk))

    def test_no_bogus_truth_claim_in_metrics(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        played(host, ticket, clock=clk)
        metrics = host.metrics()
        self.assertEqual(metrics["observed"], 1)
        self.assertNotIn("transcript", metrics)
        self.assertNotIn("played_samples", metrics)
        self.assertTrue(metrics["active"])

    def test_stale_thread_does_not_touch_new_episode(self):
        clk, _, plan, _, host = fixture()
        ticket = bind(host, plan)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(pool.map(
                lambda _: played(host, ticket, clock=clk), range(12),
            )))
        self.assertTrue(host.metrics()["active"])
        self.assertEqual(host.metrics()["observed"], 12)


if __name__ == "__main__":
    unittest.main()
