"""Offline end-to-end checks for PCM-locked text overlay suggestions.

These tests do not speak, record, use OBS/VTube Studio or control games.
"""
from __future__ import annotations

import unittest

from star.stream_audible_captions import AudibleCaptionLane, CaptionSegment, CaptionRender
from star.stream_audio_sample_host import DeviceAudibleSampleHost
from star.stream_director import StreamSignal
from star.stream_motion import AudioLevel
from star.stream_playout_clock import StarPlayoutClock
from star.stream_stage import StarStage


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def setup():
    clock = FakeClock()
    stage = StarStage(clock=clock)
    stage.enable(owner_approved=True)
    assert stage.offer(
        StreamSignal("caption-test", "game_success", clock.now,
                     "Trusted win", evidence="observed"),
        now=clock.now,
    )
    plan = stage.prepare(now=clock.now)
    assert plan is not None
    assert stage.queue_audio(plan, now=clock.now)
    assert stage.acknowledge_audible(plan, now=clock.now)
    playout = StarPlayoutClock(stage, clock=clock)
    playout.enable(owner_approved=True)
    assert playout.arm(plan, duration_s=1.0, audio_levels=(
        AudioLevel(0, .2), AudioLevel(.1, .4), AudioLevel(.25, .1),
    ))
    device = DeviceAudibleSampleHost(playout)
    device.enable(owner_approved=True)
    epoch = device.bind(plan, sample_rate_hz=48000, total_samples=48000)
    assert epoch is not None
    lane = AudibleCaptionLane(stage, device)
    segments = (
        CaptionSegment("I made it!", 0, 12000),
        CaptionSegment("That was close.", 12000, 42000),
    )
    return clock, stage, plan, device, epoch, lane, segments


class AudibleCaptionTests(unittest.TestCase):
    def ready(self):
        fixture = setup()
        _, _, plan, _, epoch, lane, segments = fixture
        lane.enable(owner_approved=True)
        self.assertTrue(lane.bind(
            plan, epoch, segments, text_approved_for_broadcast=True,
        ))
        return fixture

    def test_off_by_default_and_explicit_owner_permission(self):
        _, _, plan, _, epoch, lane, segments = setup()
        with self.assertRaises(PermissionError):
            lane.enable()
        with self.assertRaises(PermissionError):
            lane.enable(owner_approved=1)
        with self.assertRaises(PermissionError):
            lane.bind(plan, epoch, segments)
        self.assertFalse(lane.bind(
            plan, epoch, segments, text_approved_for_broadcast=True,
        ))
        lane.enable(owner_approved=True)
        self.assertTrue(lane.bind(
            plan, epoch, segments, text_approved_for_broadcast=True,
        ))

    def test_device_and_stage_must_share_exact_identity(self):
        _, _, _, device, _, _, _ = setup()
        another = StarStage()
        with self.assertRaises(ValueError):
            AudibleCaptionLane(another, device)

    def test_never_caption_generated_but_unplayed_audio(self):
        _, _, _, device, epoch, lane, _ = self.ready()
        self.assertIsNone(lane.sample(epoch, None))
        self.assertFalse(device.report_played(
            epoch, played_samples=-1, sampled_at=100.0,
        ))
        self.assertIsNone(lane.sample(epoch, device.sample(epoch)))

    def test_exact_active_phrase_from_played_pcm(self):
        clock, _, _, device, epoch, lane, _ = self.ready()
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        rig1 = device.sample(epoch)
        self.assertIsNotNone(rig1)
        first = lane.sample(epoch, rig1)
        self.assertIsInstance(first, CaptionRender)
        self.assertEqual(first.text, "I made it!")
        self.assertTrue(lane.current(epoch, first))
        clock.advance(.35)
        self.assertTrue(device.report_played(
            epoch, played_samples=24000, sampled_at=clock.now,
        ))
        rig2 = device.sample(epoch)
        second = lane.sample(epoch, rig2)
        self.assertIsNotNone(second)
        self.assertEqual(second.text, "That was close.")
        self.assertFalse(lane.current(epoch, first))
        self.assertTrue(lane.current(epoch, second))

    def test_stage_interruption_revokes_caption_immediately(self):
        clock, stage, _, device, epoch, lane, _ = self.ready()
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        render = lane.sample(epoch, device.sample(epoch))
        self.assertTrue(lane.current(epoch, render))
        stage.disable()
        self.assertFalse(lane.current(epoch, render))
        self.assertIsNone(lane.sample(epoch, device.sample(epoch)))

    def test_pause_and_resume_do_not_repeat_stale_caption(self):
        clock, _, _, device, epoch, lane, _ = self.ready()
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        prior = lane.sample(epoch, device.sample(epoch))
        self.assertIsNotNone(prior)
        clock.advance(.04)
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now, playing=False,
        ))
        self.assertIsNone(lane.sample(epoch, device.sample(epoch)))
        self.assertFalse(lane.current(epoch, prior))
        clock.advance(.05)
        self.assertTrue(device.report_played(
            epoch, played_samples=3600, sampled_at=clock.now, playing=True,
        ))
        latest = lane.sample(epoch, device.sample(epoch))
        self.assertIsNotNone(latest)
        self.assertTrue(lane.current(epoch, latest))

    def test_old_epoch_does_not_clear_new_one(self):
        _, _, _, _, epoch, lane, _ = self.ready()
        lane.stop(epoch)
        self.assertFalse(lane.metrics()["active"])
        # The same generation cannot be rebound after clearing.
        self.assertFalse(lane.bind(
            lane._stage._plan, epoch, (CaptionSegment("repeat", 0, 500),),
            text_approved_for_broadcast=True,
        ))
        lane.stop(epoch)
        self.assertFalse(lane.metrics()["active"])

    def test_clear_and_disable_invalidate_render_without_closing_audio(self):
        clock, _, _, device, epoch, lane, _ = self.ready()
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        render = lane.sample(epoch, device.sample(epoch))
        self.assertTrue(lane.current(epoch, render))
        lane.clear()
        self.assertFalse(lane.current(epoch, render))
        lane.disable()
        self.assertFalse(lane.metrics()["enabled"])
        self.assertTrue(device.active_for(epoch, lane._stage._plan))

    def test_hold_bound_hides_old_phrases(self):
        clock, stage, plan, device, epoch, _, _ = setup()
        lane = AudibleCaptionLane(stage, device, max_hold_s=.1)
        lane.enable(owner_approved=True)
        self.assertTrue(lane.bind(
            plan, epoch, (CaptionSegment("Short.", 1000, 3000),),
            text_approved_for_broadcast=True,
        ))
        clock.advance(.5)
        self.assertTrue(device.report_played(
            epoch, played_samples=24000, sampled_at=clock.now,
        ))
        self.assertIsNone(lane.sample(epoch, device.sample(epoch)))

    def test_cannot_copy_a_valid_render_to_another_lane(self):
        clock, stage, plan, device, epoch, lane, segments = self.ready()
        other = AudibleCaptionLane(stage, device)
        other.enable(owner_approved=True)
        self.assertTrue(other.bind(
            plan, epoch, segments, text_approved_for_broadcast=True,
        ))
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        render = lane.sample(epoch, device.sample(epoch))
        self.assertFalse(other.current(epoch, render))

    def test_invalid_plain_text_is_rejected(self):
        for text in ("", " hello", "hello ", "bad\nline", "<img>", "a" * 101,
                     "bad\tthing", "\x1b[31m"):
            with self.subTest(text=repr(text)), self.assertRaises(ValueError):
                CaptionSegment(text, 0, 100)

    def test_invalid_timings_are_rejected(self):
        for start, end in ((-1, 10), (3, 3), (5, 4), (True, 5),
                           (1, 2.0), (2, 0)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                CaptionSegment("okay", start, end)

    def test_out_of_bounds_and_overlaps_are_rejected(self):
        _, _, plan, _, epoch, lane, _ = setup()
        lane.enable(owner_approved=True)
        for chunks in (
            (CaptionSegment("a", 0, 2000), CaptionSegment("b", 1999, 3000)),
            (CaptionSegment("a", 0, 48001),),
            (),
            (CaptionSegment("many", 0, 100),) * 49,
        ):
            with self.subTest(chunks=len(chunks)), self.assertRaises(ValueError):
                lane.bind(plan, epoch, chunks, text_approved_for_broadcast=True)

    def test_strict_epoch_identity(self):
        clock, _, _, device, epoch, lane, _ = self.ready()
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        rig = device.sample(epoch)
        fake_epoch = type(epoch)(epoch.sequence, epoch.generation,
                                 epoch.sample_rate_hz, epoch.total_samples)
        self.assertIsNone(lane.sample(fake_epoch, rig))
        self.assertFalse(lane.current(fake_epoch, lane.sample(epoch, rig)))

    def test_no_reuse_after_physical_audio_stop(self):
        clock, _, _, device, epoch, lane, _ = self.ready()
        self.assertTrue(device.report_played(
            epoch, played_samples=2400, sampled_at=clock.now,
        ))
        render = lane.sample(epoch, device.sample(epoch))
        device.stop(epoch, output_stopped_and_flushed=True)
        self.assertFalse(lane.current(epoch, render))
        self.assertIsNone(lane.sample(epoch, render._rig))

    def test_invalid_hold_configuration(self):
        _, stage, _, device, _, _, _ = setup()
        for hold in (0, -1, 10, float("nan"), float("inf"), True, "1"):
            with self.subTest(hold=hold), self.assertRaises(ValueError):
                AudibleCaptionLane(stage, device, max_hold_s=hold)
