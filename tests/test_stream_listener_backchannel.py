"""Regression tests for content-free, host-verified listener micro-cues."""
import unittest

from star.stream_listener_backchannel import (
    ListenerIntentSignal,
    StreamListenerBackchannel,
)
from star.stream_motion import neutral_frame
from star.stream_stage import StarStage


def signal(event_id=1, **overrides):
    values = dict(
        event_id=event_id,
        kind="acknowledge",
        observed_at_s=1.0,
        confidence=0.95,
        guest_speaking=True,
        owner_speaking=False,
        star_speaking=False,
        gameplay_critical=False,
        stream_pressure=False,
        host_verified=True,
    )
    values.update(overrides)
    return ListenerIntentSignal(**values)


class StreamListenerBackchannelTests(unittest.TestCase):
    def make_gate(self):
        gate = StreamListenerBackchannel()
        gate.enable(owner_approved=True)
        return gate

    def overlay(self, gate, now=1.2, **overrides):
        values = dict(
            now_s=now,
            host_context_verified=True,
            viewer_speaking=True,
            owner_speaking=False,
            gameplay_critical=False,
            stream_pressure=False,
            reduced_motion=False,
        )
        values.update(overrides)
        return gate.overlay(neutral_frame(), **values)

    def test_requires_explicit_owner_opt_in(self):
        gate = StreamListenerBackchannel()
        with self.assertRaises(PermissionError):
            gate.enable()
        self.assertFalse(gate.observe(signal(), now_s=1.0))
        self.assertFalse(gate.metrics()["enabled"])

    def test_fresh_acknowledgement_creates_small_nonverbal_overlay_only(self):
        gate = self.make_gate()
        self.assertTrue(gate.observe(signal(), now_s=1.0))
        frame = self.overlay(gate)
        self.assertLess(frame.head_y, 0)
        self.assertGreater(frame.body_lean, 0)
        self.assertEqual(frame.mouth_open, 0)
        self.assertEqual(frame.smile, 0)
        self.assertEqual(frame.tail_sway, 0)
        self.assertFalse(gate.metrics()["accepted"] == 0)

    def test_considering_and_clarifying_have_distinct_subtle_cues(self):
        for kind in ("considering", "clarifying"):
            gate = self.make_gate()
            self.assertTrue(gate.observe(signal(kind=kind), now_s=1.0))
            frame = self.overlay(gate)
            self.assertGreater(frame.brow_raise, 0)
            self.assertNotEqual(frame.head_x, 0)
            self.assertEqual(frame.mouth_open, 0)

    def test_stale_or_future_events_are_rejected(self):
        for observed in (0.0, 1.3):
            gate = self.make_gate()
            self.assertFalse(gate.observe(
                signal(observed_at_s=observed), now_s=1.0,
            ))
            self.assertEqual(gate.metrics()["stale"], 1)

    def test_untrusted_or_unsafe_context_is_suppressed(self):
        cases = (
            {"host_verified": False},
            {"guest_speaking": False},
            {"owner_speaking": True},
            {"star_speaking": True},
            {"gameplay_critical": True},
            {"stream_pressure": True},
            {"confidence": 0.81},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                gate = self.make_gate()
                self.assertFalse(gate.observe(signal(**changes), now_s=1.0))
                self.assertEqual(gate.metrics()["suppressed"] + gate.metrics()["rejected"], 1)
                self.assertEqual(self.overlay(gate), neutral_frame())

    def test_event_ids_are_single_use_and_cooldown_is_enforced(self):
        gate = self.make_gate()
        self.assertTrue(gate.observe(signal(1), now_s=1.0))
        self.assertFalse(gate.observe(signal(1, observed_at_s=1.2), now_s=1.2))
        self.assertFalse(gate.observe(signal(2, observed_at_s=1.5), now_s=1.5))
        self.assertTrue(gate.observe(signal(3, observed_at_s=2.2), now_s=2.2))
        self.assertEqual(gate.metrics()["duplicate"], 1)
        self.assertEqual(gate.metrics()["rate_limited"], 1)

    def test_ten_per_minute_cap_blocks_catchphrase_like_repetition(self):
        gate = self.make_gate()
        for index in range(10):
            at = 1.0 + index * 1.2
            self.assertTrue(gate.observe(
                signal(index + 1, observed_at_s=at), now_s=at,
            ))
        at = 1.0 + 10 * 1.2
        self.assertFalse(gate.observe(
            signal(11, observed_at_s=at), now_s=at,
        ))
        self.assertEqual(gate.metrics()["rate_limited"], 1)

    def test_cue_expires_and_is_not_replayed(self):
        gate = self.make_gate()
        self.assertTrue(gate.observe(signal(), now_s=1.0))
        self.assertEqual(self.overlay(gate, now=1.49), neutral_frame())
        self.assertEqual(gate.metrics()["expired"], 1)
        self.assertEqual(self.overlay(gate, now=1.50), neutral_frame())

    def test_lost_host_context_pause_or_reduced_motion_cancels_cue(self):
        cases = (
            {"host_context_verified": False},
            {"viewer_speaking": False},
            {"owner_speaking": True},
            {"gameplay_critical": True},
            {"stream_pressure": True},
            {"reduced_motion": True},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                gate = self.make_gate()
                self.assertTrue(gate.observe(signal(), now_s=1.0))
                self.assertEqual(self.overlay(gate, **changes), neutral_frame())
                self.assertEqual(self.overlay(gate, now=1.25), neutral_frame())

    def test_clock_reversal_clears_cue(self):
        gate = self.make_gate()
        self.assertTrue(gate.observe(signal(), now_s=1.0))
        self.assertEqual(self.overlay(gate, now=0.9), neutral_frame())
        self.assertEqual(gate.metrics()["clock_reversed"], 1)

    def test_disable_and_reset_revoke_pending_cues(self):
        gate = self.make_gate()
        self.assertTrue(gate.observe(signal(), now_s=1.0))
        gate.reset()
        self.assertEqual(self.overlay(gate), neutral_frame())
        self.assertTrue(gate.observe(
            signal(event_id=1, observed_at_s=1.3), now_s=1.3,
        ))
        gate.disable()
        self.assertEqual(self.overlay(gate, now=1.4), neutral_frame())
        self.assertFalse(gate.metrics()["enabled"])

    def test_stage_exposes_opt_in_content_free_listener_cues(self):
        stage = StarStage(clock=lambda: 1.0)
        stage.enable(owner_approved=True)
        with self.assertRaises(PermissionError):
            stage.enable_listener_backchannels()
        stage.enable_listener_backchannels(owner_approved=True)
        self.assertTrue(stage.observe_listener_intent(signal(), now=1.0))
        frame = stage.idle_motion(
            now=1.2, viewer_speaking=True, listener_context_verified=True,
        )
        self.assertIsNotNone(frame)
        self.assertLess(frame.motion.head_y, 0)
        self.assertTrue(stage.current_idle(frame, now=1.2))
        stage.disable_listener_backchannels()
        self.assertFalse(stage.observe_listener_intent(
            signal(event_id=2, observed_at_s=1.3), now=1.3,
        ))
        stage.disable()
        self.assertFalse(stage.metrics()["listener_backchannel"]["enabled"])


if __name__ == "__main__":
    unittest.main()

[executed on device: starai (04f6aa98-0095-4f4d-8546-724e7fb588fa)]