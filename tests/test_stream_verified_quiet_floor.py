"""Regressions for opt-in evidence-backed quiet windows in Star's live turn gate."""
from __future__ import annotations

import unittest

from star.stream_turntaking import TurnTakingGate, VoiceFrame
from star.stream_interrupt_host import StreamInterruptionHost
from star.stream_director import StreamSignal
from star.stream_stage import StarStage


def voice(at: int, *, owner: float = 0.0, guest: float = 0.0,
          echo: bool = True, duration: int = 30) -> VoiceFrame:
    return VoiceFrame(at, duration, owner, guest, echo)


class StrictQuietFloorTests(unittest.TestCase):
    def setUp(self):
        self.gate = TurnTakingGate()
        self.gate.enable(owner_approved=True, require_verified_quiet=True)

    def test_first_short_silent_frame_cannot_claim_a_quiet_floor(self):
        self.gate.observe(voice(1000))
        decision = self.gate.advise(now_ms=1000, star_speaking=False)
        self.assertTrue(decision.hold)
        self.assertEqual(decision.reason, "quiet_window_unverified")

    def test_unobserved_time_cannot_masquerade_as_verified_silence(self):
        self.gate.observe(voice(100, guest=1))
        self.gate.observe(voice(600))
        self.assertEqual(
            self.gate.advise(now_ms=600, star_speaking=False).reason,
            "quiet_window_unverified",
        )

    def test_twelve_contiguous_quiet_frames_release_the_floor(self):
        for at in range(1000, 1330, 30):
            self.gate.observe(voice(at))
        self.assertEqual(
            self.gate.advise(now_ms=1300, star_speaking=False).action, "hold"
        )
        self.gate.observe(voice(1330))
        self.assertEqual(
            self.gate.advise(now_ms=1330, star_speaking=False).action, "speak"
        )

    def test_partial_quiet_then_uncleared_echo_restarts_confirmation(self):
        for at in range(1000, 1210, 30):
            self.gate.observe(voice(at))
        self.gate.observe(voice(1210, echo=False))
        for at in range(1240, 1480, 30):
            self.gate.observe(voice(at))
        self.assertEqual(
            self.gate.advise(now_ms=1450, star_speaking=False).reason,
            "quiet_window_unverified",
        )

    def test_uncertain_audio_cannot_accumulate_silence(self):
        for at in range(100, 310, 30):
            self.gate.observe(voice(at))
        self.gate.observe(voice(310, owner=0.4))
        for at in range(340, 580, 30):
            self.gate.observe(voice(at))
        self.assertEqual(
            self.gate.advise(now_ms=550, star_speaking=False).reason,
            "quiet_window_unverified",
        )

    def test_a_10_ms_capture_gap_breaks_continuous_quiet(self):
        for at in range(100, 280, 30):
            self.gate.observe(voice(at))
        for at in range(320, 500, 30):  # a 10 ms missing capture interval
            self.gate.observe(voice(at))
        self.assertEqual(
            self.gate.advise(now_ms=470, star_speaking=False).reason,
            "quiet_window_unverified",
        )

    def test_long_poll_gap_requires_new_frame_before_speech(self):
        for at in range(100, 460, 30):
            self.gate.observe(voice(at))
        self.assertEqual(self.gate.advise(now_ms=430, star_speaking=False).action, "speak")
        self.assertEqual(
            self.gate.advise(now_ms=520, star_speaking=False).reason,
            "quiet_frame_not_recent",
        )

    def test_owner_barge_in_remains_fast(self):
        for at in (100, 130, 160, 190):
            self.gate.observe(voice(at, owner=1))
        advice = self.gate.advise(now_ms=190, star_speaking=True)
        self.assertEqual(advice.action, "yield_owner")
        self.assertTrue(advice.should_interrupt)

    def test_disabled_legacy_mode_remains_compatible(self):
        self.gate.disable()
        self.gate.enable(owner_approved=True)
        self.gate.observe(voice(900))
        self.assertEqual(self.gate.advise(now_ms=900, star_speaking=False).action, "speak")


class StrictHostIntegrationTests(unittest.TestCase):
    def test_host_cannot_arm_audible_epoch_until_verified_quiet(self):
        now = [1000.]
        stage = StarStage(clock=lambda: now[0] / 1000)
        stage.enable(owner_approved=True)
        stage.offer(StreamSignal("evt", "viewer_question", 1., "How?", speaker_id="mod", evidence="reported"),
                    now=1., moderated=True)
        plan = stage.prepare(now=1.)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertTrue(stage.queue_audio(plan, now=1.))
        self.assertTrue(stage.acknowledge_audible(plan, now=1.))
        host = StreamInterruptionHost(
            stage=stage, turns=TurnTakingGate(),
            stop_epoch=lambda epoch: True, flush_animation=lambda epoch: True,
            clock_ms=lambda: now[0], owner_approved=True,
        )
        host.enable(owner_approved=True, require_verified_quiet=True)
        self.assertEqual(host.observe(voice(1000)).status, "hold")
        self.assertFalse(host.arm(plan, playback_epoch="epoch-1"))
        for at in range(1030, 1360, 30):
            now[0] = float(at)
            host.observe(voice(at))
        self.assertTrue(host.arm(plan, playback_epoch="epoch-1"))
        self.assertTrue(host.metrics()["active"])
        host.disable()


if __name__ == "__main__":
    unittest.main()
