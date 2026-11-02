"""Adversarial offline tests for delayed VTuber owner VAD callbacks."""
from __future__ import annotations

import unittest

from star.stream_director import StreamSignal
from star.stream_interrupt_host import StreamInterruptionHost
from star.stream_stage import StarStage
from star.stream_turntaking import TurnTakingGate, VoiceFrame


def owner(at: float) -> VoiceFrame:
    return VoiceFrame(at, 30.0, 1.0, 0.0, True)


class FreshOwnerTurnTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = TurnTakingGate()
        self.gate.enable(owner_approved=True, require_verified_quiet=True)
        for at in (100, 130, 160, 190):
            self.assertTrue(self.gate.observe(owner(at)))

    def test_stale_owner_frames_must_not_interrupt_playback(self) -> None:
        for now in (266, 300, 390, 440):
            with self.subTest(now=now):
                advice = self.gate.advise(now_ms=now, star_speaking=True)
                self.assertEqual(advice.action, "hold")
                self.assertFalse(advice.should_interrupt)
                self.assertEqual(advice.reason, "voice_frame_not_recent")
        self.assertEqual(self.gate.metrics()["owner_yields"], 0)

    def test_fresh_owner_barge_in_remains_fast(self) -> None:
        for now in (190, 265):
            with self.subTest(now=now):
                advice = self.gate.advise(now_ms=now, star_speaking=True)
                self.assertEqual(advice.action, "yield_owner")
                self.assertTrue(advice.should_interrupt)
        self.assertEqual(self.gate.metrics()["owner_yields"], 1)

    def test_fresh_owner_update_restores_interruption(self) -> None:
        self.assertEqual(
            self.gate.advise(now_ms=390, star_speaking=True).action, "hold"
        )
        # A 210-ms capture hole broke the original confirmation. The fresh
        # utterance needs its own four contiguous observations.
        for at in (400, 430, 460, 490):
            self.gate.observe(owner(at))
        self.assertTrue(
            self.gate.advise(now_ms=490, star_speaking=True).should_interrupt
        )
        self.assertEqual(self.gate.metrics()["owner_yields"], 1)

    def test_opt_out_retains_previous_reaction_window(self) -> None:
        self.gate.disable()
        self.gate.enable(owner_approved=True)
        for at in (100, 130, 160, 190):
            self.gate.observe(owner(at))
        self.assertTrue(
            self.gate.advise(now_ms=390, star_speaking=True).should_interrupt
        )


class FreshOwnerHostTests(unittest.TestCase):
    def test_host_does_not_stop_audio_on_200ms_old_owner_event(self) -> None:
        now = [1000.0]
        stage = StarStage(clock=lambda: now[0] / 1000.0)
        stage.enable(owner_approved=True)
        self.assertTrue(stage.offer(
            StreamSignal("q1", "viewer_question", 1.0, "How?", speaker_id="mod",
                         evidence="reported"), now=1.0, moderated=True,
        ))
        plan = stage.prepare(now=1.0)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertTrue(stage.queue_audio(plan, now=1.0))
        self.assertTrue(stage.acknowledge_audible(plan, now=1.0))
        stops: list[str] = []
        host = StreamInterruptionHost(
            stage=stage, turns=TurnTakingGate(),
            stop_epoch=lambda epoch: (stops.append(epoch) or True),
            flush_animation=lambda epoch: True,
            clock_ms=lambda: now[0], owner_approved=True,
        )
        host.enable(owner_approved=True, require_verified_quiet=True)
        for at in range(1000, 1360, 30):
            now[0] = float(at)
            host.observe(VoiceFrame(float(at), 30.0, 0.0, 0.0, True))
        self.assertTrue(host.arm(plan, playback_epoch="one"))
        # Four owner-labeled PCM windows arrive 200ms late from the backend.
        for at in (1360, 1390, 1420, 1450):
            now[0] = float(at + 200)
            response = host.observe(owner(at))
            self.assertNotEqual(response.status, "interrupted")
        self.assertTrue(host.metrics()["active"])
        self.assertEqual(stops, [])
        self.assertEqual(host.metrics()["interruptions"], 0)
        # Emergency stop is a separate trusted host capability.
        self.assertEqual(host.emergency_stop().status, "interrupted")
        self.assertEqual(stops, ["one"])


if __name__ == "__main__":
    unittest.main()
