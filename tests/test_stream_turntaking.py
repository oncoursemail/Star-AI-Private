"""Adversarial offline tests for opt-in, echo-aware Star VTuber turn-taking."""
from __future__ import annotations

import unittest

from star.stream_director import StreamSignal
from star.stream_stage import StarStage
from star.stream_turntaking import TurnAdvice, TurnTakingGate, VoiceFrame


def frame(at: float, *, owner: float = 0.0, guest: float = 0.0,
          echo: bool = True, ms: float = 30.0) -> VoiceFrame:
    return VoiceFrame(at, ms, owner, guest, echo)


class TurnTakingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = TurnTakingGate()

    def test_default_disabled_and_explicit_host_consent(self):
        self.assertFalse(self.gate.observe(frame(100)))
        self.assertEqual(self.gate.advise(now_ms=100, star_speaking=True).action, "hold")
        with self.assertRaises(PermissionError):
            self.gate.enable()
        with self.assertRaises(PermissionError):
            self.gate.enable(owner_approved=1)
        self.gate.enable(owner_approved=True)
        self.assertTrue(self.gate.observe(frame(100)))
        self.assertEqual(self.gate.advise(now_ms=100, star_speaking=False).action, "speak")
        self.gate.disable()
        self.assertEqual(self.gate.advise(now_ms=100, star_speaking=True).action, "hold")
        self.assertFalse(self.gate.metrics()["enabled"])

    def test_single_spike_is_not_an_owner_barge_in(self):
        self.gate.enable(owner_approved=True)
        self.gate.observe(frame(100, owner=1))
        decision = self.gate.advise(now_ms=100, star_speaking=True)
        self.assertEqual(decision.action, "hold")
        self.assertFalse(decision.should_interrupt)
        self.gate.observe(frame(130))
        self.assertFalse(self.gate.advise(now_ms=130, star_speaking=True).should_interrupt)

    def test_sustained_authenticated_owner_requires_host_to_do_interrupt(self):
        self.gate.enable(owner_approved=True)
        for at in (100, 130, 160, 190):
            self.gate.observe(frame(at, owner=.99))
        self.assertEqual(self.gate.advise(now_ms=190, star_speaking=False).action,
                         "yield_owner")
        decision = self.gate.advise(now_ms=190, star_speaking=True)
        self.assertTrue(decision.should_interrupt)
        self.assertEqual(decision.reason, "confirmed_authenticated_owner_voice")
        self.assertEqual(self.gate.metrics()["owner_yields"], 1)

    def test_barge_in_metric_is_once_per_confirmed_utterance_not_per_poll(self):
        self.gate.enable(owner_approved=True)
        for at in (100, 130, 160, 190):
            self.gate.observe(frame(at, owner=1))
        # The host may poll faster than VAD emits frames. The advice must
        # remain actionable if an earlier interruption wasn't yet performed.
        for _ in range(10):
            decision = self.gate.advise(now_ms=200, star_speaking=True)
            self.assertTrue(decision.should_interrupt)
            self.assertEqual(decision.action, "yield_owner")
        self.assertEqual(self.gate.metrics()["owner_yields"], 1)
        # A genuinely new utterance is counted only after another 120ms of
        # verified speech, not from a stale owner probability.
        self.gate.observe(frame(220))
        for at in (250, 280, 310, 340):
            self.gate.observe(frame(at, owner=1))
        self.assertTrue(
            self.gate.advise(now_ms=340, star_speaking=True).should_interrupt
        )
        self.assertEqual(self.gate.metrics()["owner_yields"], 2)
        self.gate.disable()
        self.gate.enable(owner_approved=True)
        self.assertEqual(self.gate.metrics()["owner_yields"], 2)
        # Counters are cumulative; utterance state, not counters, resets.
        for at in (600, 630, 660, 690):
            self.gate.observe(frame(at, owner=1))
        self.assertTrue(
            self.gate.advise(now_ms=690, star_speaking=True).should_interrupt
        )
        self.assertEqual(self.gate.metrics()["owner_yields"], 3)

    def test_guest_voice_holds_speech_without_owner_privilege(self):
        self.gate.enable(owner_approved=True)
        for at in (100, 130, 160, 190):
            self.gate.observe(frame(at, guest=.99))
        decision = self.gate.advise(now_ms=190, star_speaking=True)
        self.assertEqual(decision.action, "hold")
        self.assertFalse(decision.should_interrupt)
        # Recent activity needs a quiet hangover; no immediate talk-over.
        for at in (220, 250, 280, 310, 340, 370, 400, 430, 460, 490, 520, 550):
            self.gate.observe(frame(at))
        self.assertEqual(self.gate.advise(now_ms=520, star_speaking=False).action, "hold")
        self.assertEqual(self.gate.advise(now_ms=550, star_speaking=False).action, "speak")

    def test_uncleared_echo_and_mixed_speakers_never_forge_owner(self):
        self.gate.enable(owner_approved=True)
        for at in (100, 130, 160, 190):
            self.gate.observe(frame(at, owner=1, echo=False))
        decision = self.gate.advise(now_ms=190, star_speaking=True)
        self.assertFalse(decision.should_interrupt)
        self.assertEqual(decision.reason, "echo_not_cleared")
        for at in (220, 250, 280, 310):
            self.gate.observe(frame(at, owner=1, guest=1))
        self.assertFalse(self.gate.advise(now_ms=310, star_speaking=True).should_interrupt)

    def test_gap_and_staleness_prevent_forged_confirmation(self):
        self.gate.enable(owner_approved=True)
        self.gate.observe(frame(100, owner=1))
        self.gate.observe(frame(300, owner=1))  # disconnected samples
        self.gate.observe(frame(500, owner=1))
        self.assertFalse(self.gate.advise(now_ms=500, star_speaking=True).should_interrupt)
        self.assertEqual(self.gate.advise(now_ms=751, star_speaking=True).reason,
                         "vad_missing_or_stale")
        self.assertEqual(self.gate.advise(now_ms=800, star_speaking=False).action, "hold")

    def test_sparse_short_voice_bursts_do_not_become_a_barge_in(self):
        self.gate.enable(owner_approved=True)
        # Each 30-ms frame is separated by 50 ms of unobserved silence.
        # Comparing only frame end timestamps (80 ms < 150 ms) used to
        # incorrectly accumulate 120 ms of apparent continuous owner voice.
        for at in (100, 180, 260, 340):
            self.gate.observe(frame(at, owner=.99))
        advice = self.gate.advise(now_ms=340, star_speaking=True)
        self.assertFalse(advice.should_interrupt)
        self.assertEqual(self.gate.metrics()["owner_yields"], 0)
        # Four genuinely contiguous 30-ms frames still interrupt.
        for at in (370, 400, 430):
            self.gate.observe(frame(at, owner=.99))
        self.assertTrue(
            self.gate.advise(now_ms=430, star_speaking=True).should_interrupt
        )
        self.assertEqual(self.gate.metrics()["owner_yields"], 1)

    def test_sparse_guest_frames_do_not_fake_sustained_guest_speech(self):
        self.gate.enable(owner_approved=True)
        for at in (100, 180, 260, 340):
            self.gate.observe(frame(at, guest=.99))
        decision = self.gate.advise(now_ms=340, star_speaking=False)
        self.assertFalse(decision.should_interrupt)
        self.assertNotEqual(decision.reason, "confirmed_guest_voice")

    def test_reverse_duplicate_and_overlapping_frames_rejected(self):
        self.gate.enable(owner_approved=True)
        self.gate.observe(frame(100))
        for new in (frame(100), frame(90), frame(110, ms=50)):
            with self.subTest(at=new.at_ms), self.assertRaises(ValueError):
                self.gate.observe(new)
        self.assertEqual(self.gate.metrics()["rejected"], 3)
        self.gate.observe(frame(130))
        self.assertEqual(self.gate.metrics()["accepted"], 2)

    def test_invalid_fields_rejected_without_state_changes(self):
        for invalid in (
            dict(at_ms=True), dict(at_ms=float("nan")),
            dict(duration_ms=0), dict(duration_ms=101),
            dict(owner_probability=-.1), dict(guest_probability=float("inf")),
            dict(owner_probability=True), dict(echo_cleared=1),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                VoiceFrame(**(dict(at_ms=100, duration_ms=30,
                                   owner_probability=0, guest_probability=0,
                                   echo_cleared=True) | invalid))
        self.gate.enable(owner_approved=True)
        with self.assertRaises(TypeError):
            self.gate.observe({"at_ms": 100})
        for now in (-1, True, float("nan"), float("inf")):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.gate.advise(now_ms=now, star_speaking=True)
        with self.assertRaises(ValueError):
            self.gate.advise(now_ms=100, star_speaking=1)

    def test_host_driven_stage_stays_silent_then_responds_and_yields(self):
        stage = StarStage(clock=lambda: 100.0)
        stage.enable(owner_approved=True)
        self.gate.enable(owner_approved=True)
        viewer = StreamSignal("question1", "viewer_question", 100.0,
                              "How did you do that?", speaker_id="mod-approved",
                              evidence="unknown")
        self.assertTrue(stage.offer(viewer, now=100.0, moderated=True))
        for at in (100, 130, 160, 190):
            self.gate.observe(frame(at, guest=.95))
        hold = self.gate.advise(now_ms=190, star_speaking=False)
        self.assertIsNone(stage.prepare(now=100.19, turn=hold))
        self.gate.observe(frame(600))  # quiet and far beyond hangover
        speak = self.gate.advise(now_ms=600, star_speaking=False)
        self.assertFalse(speak.hold)
        plan = stage.prepare(now=100.6, turn=speak)
        self.assertIsNotNone(plan)
        self.assertTrue(stage.queue_audio(plan, now=100.6))
        self.assertTrue(stage.acknowledge_audible(plan, now=100.6))
        for at in (630, 660, 690, 720):
            self.gate.observe(frame(at, owner=1.0))
        barge = self.gate.advise(now_ms=720, star_speaking=True)
        self.assertTrue(barge.should_interrupt)
        # Host policy responds by silencing the device and invalidating stage.
        stage.interrupt(now=100.72)
        self.assertFalse(stage.current(plan))
        self.assertFalse(stage.finish(plan, now=100.8, played_to_end=True))
        self.assertEqual(stage.metrics()["director"]["completed"], 0)
        self.assertGreater(stage.metrics()["interrupted"], 0)

    def test_stage_refuses_arbitrary_turn_payload(self):
        stage = StarStage(clock=lambda: 100.0)
        stage.enable(owner_approved=True)
        with self.assertRaises(TypeError):
            stage.prepare(now=100, turn={"action": "speak"})
        self.assertIsNone(stage.prepare(now=100,
                                        turn=TurnAdvice("hold", False, "quiet")))

    def test_only_counts_leave_metrics(self):
        self.gate.enable(owner_approved=True)
        self.gate.observe(frame(100, owner=.98765))
        metrics = self.gate.metrics()
        self.assertEqual(set(metrics), {"accepted", "rejected", "owner_yields",
                                        "enabled"})
        self.assertNotIn("0.98765", str(metrics))


if __name__ == "__main__":
    unittest.main()
