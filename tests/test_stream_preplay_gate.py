"""Offline cross-component safety regressions for the preplay speech gate.

No live audio, OS devices, games, OBS, network, viewer text or model calls.
"""
from __future__ import annotations

import unittest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_load_governor import StreamLoadGovernor, StreamLoadSample
from star.stream_preplay_gate import StreamPreplayGate
from star.stream_turntaking import TurnTakingGate, VoiceFrame


def sample(ident: str, at: float, **changes: float) -> StreamLoadSample:
    kwargs = dict(
        sample_id=ident, measured_at_s=at,
        game_p95_frame_ms=12.0, game_target_fps=60.0,
        obs_render_missed_pct=0.0, obs_encode_skipped_pct=0.0,
        obs_network_dropped_pct=0.0,
        gpu_vram_used_mb=4000.0, gpu_vram_total_mb=8192.0,
        tts_first_audio_p95_ms=150.0,
    )
    kwargs.update(changes)
    return StreamLoadSample(**kwargs)


class PreplayGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.director = StreamDirector()
        self.director.enable(owner_approved=True)
        self.turns = TurnTakingGate()
        self.turns.enable(owner_approved=True)
        self.load = StreamLoadGovernor()
        self.load.enable(owner_approved=True)
        for i in range(3):
            self.assertTrue(self.load.ingest(
                sample(f"healthy-{i}", 10.0 + i), now_s=10.0 + i,
                host_verified=True,
            ))
        self.turns.observe(VoiceFrame(12000.0, 30.0, 0.0, 0.0, True))
        self.gate = StreamPreplayGate(self.director, self.turns, self.load)
        self.gate.enable(owner_approved=True)

    def offer(self, kind="viewer_question", identifier="question") -> None:
        signal = StreamSignal(identifier, kind, 12.0, "What happened there?",
                              speaker_id="viewer1" if kind.startswith("viewer") else "",
                              evidence="reported")
        self.assertTrue(self.director.offer(signal, now=12.0))

    def plan(self, kind="viewer_question"):
        self.offer(kind)
        decision = self.gate.preflight(
            now_s=12.0, star_speaking=False, gameplay_critical=False)
        self.assertEqual(decision.status, "candidate")
        self.assertIsNotNone(decision.intent)
        return decision.intent

    def recheck(self, intent, now=12.05, **changes):
        kwargs = dict(star_speaking=False, gameplay_critical=False)
        kwargs.update(changes)
        return self.gate.revalidate(intent, now_s=now, **kwargs)

    def test_owner_gate_does_not_enable_underlying_components(self):
        naked = StreamPreplayGate(StreamDirector(), TurnTakingGate(),
                                  StreamLoadGovernor())
        with self.assertRaises(PermissionError):
            naked.enable()
        naked.enable(owner_approved=True)
        self.assertEqual(
            naked.preflight(now_s=12.0, star_speaking=False,
                            gameplay_critical=False).status, "hold"
        )
        naked.disable()
        self.assertEqual(
            naked.preflight(now_s=12.0, star_speaking=False,
                            gameplay_critical=False).status, "disabled"
        )

    def test_live_happy_path_requires_final_freshness_and_receipt(self):
        intent = self.plan()
        self.assertFalse(self.gate.preflight(
            now_s=12.02, star_speaking=False, gameplay_critical=False).intent)
        decision = self.recheck(intent)
        self.assertEqual(decision.status, "reviewed")
        self.assertFalse(decision.authorizes_playback)
        self.assertFalse(decision.authorizes_broadcast)
        self.assertFalse(decision.authorizes_game_input)
        self.assertEqual(self.recheck(intent).reason, "speech_plan_already_checked")
        self.assertTrue(self.gate.settle(intent, now_s=12.10, audible_confirmed=True))
        self.assertEqual(self.director.metrics()["completed"], 1)
        self.assertFalse(self.gate.settle(intent, now_s=12.10, audible_confirmed=True))

    def test_without_final_recheck_claimed_audio_cannot_commit(self):
        intent = self.plan()
        self.assertTrue(self.gate.settle(intent, now_s=12.10, audible_confirmed=True))
        self.assertEqual(self.director.metrics()["completed"], 0)
        self.assertEqual(self.director.metrics()["abandoned"], 1)

    def test_owner_interrupt_during_pending_speech(self):
        intent = self.plan()
        for at in (12030, 12060, 12090, 12120):
            self.turns.observe(VoiceFrame(at, 30, 0.99, 0.0, True))
        decision = self.recheck(
            intent, now=12.12, star_speaking=True)
        self.assertEqual(decision.status, "yield_owner")
        self.assertTrue(decision.request_physical_stop)
        self.assertFalse(decision.authorizes_playback)
        self.assertEqual(self.gate.preflight(
            now_s=12.12, star_speaking=True,
            gameplay_critical=False).status, "yield_owner")
        self.assertTrue(self.gate.settle(intent, now_s=12.14, audible_confirmed=False))
        self.assertEqual(self.director.metrics()["completed"], 0)

    def test_guest_hold_and_echo_failure_prevent_preplay(self):
        intent = self.plan()
        self.turns.observe(VoiceFrame(12040, 40, 0, 0.9, False))
        self.assertEqual(self.recheck(intent, 12.04).status, "hold")

    def test_stale_vad_blocks_every_speech(self):
        self.offer()
        decision = self.gate.preflight(
            now_s=12.26, star_speaking=False, gameplay_critical=False)
        self.assertEqual(decision.reason, "vad_missing_or_stale")

    def test_plan_expires_even_if_vad_is_fresh(self):
        intent = self.plan()
        self.turns.observe(VoiceFrame(12270, 30, 0, 0, True))
        self.assertEqual(self.recheck(intent, now=12.27).reason,
                         "speech_plan_timed_out")

    def test_hardware_pressure_cancels_optional_commentary(self):
        intent = self.plan(kind="game_observation")
        self.load.ingest(sample("pressure", 12.04, gpu_vram_used_mb=7300),
                         now_s=12.04, host_verified=True)
        self.assertEqual(self.load.recommend(now_s=12.04).profile, "constrained")
        self.turns.observe(VoiceFrame(12040, 30, 0, 0, True))
        self.assertEqual(self.recheck(intent, now=12.04).reason,
                         "optional_commentary_suppressed")

    def test_critical_obs_pressure_blocks_even_danger(self):
        intent = self.plan(kind="game_danger")
        self.load.ingest(sample("encoder", 12.04, obs_encode_skipped_pct=7.0),
                         now_s=12.04, host_verified=True)
        self.turns.observe(VoiceFrame(12040, 30, 0, 0, True))
        self.assertEqual(self.recheck(intent, now=12.04).reason,
                         "live_load_critical")

    def test_gameplay_critical_after_plan_suppresses_questions(self):
        intent = self.plan()
        self.turns.observe(VoiceFrame(12030, 30, 0, 0, True))
        self.assertEqual(
            self.recheck(intent, 12.03, gameplay_critical=True).reason,
            "critical_gameplay_focus",
        )

    def test_critical_game_danger_is_eligible_with_normal_host(self):
        self.offer(kind="game_danger")
        plan = self.gate.preflight(
            now_s=12, star_speaking=False, gameplay_critical=True)
        self.assertEqual(plan.status, "candidate")
        self.assertEqual(self.recheck(
            plan.intent, 12.03, gameplay_critical=True).status, "reviewed")

    def test_invalid_clocks_and_fake_flags_fail_closed(self):
        for now in (True, -1, float("inf"), float("nan"), 1e99, "12"):
            with self.subTest(now=now), self.assertRaises(ValueError):
                self.gate.preflight(now_s=now, star_speaking=False,
                                    gameplay_critical=False)
        with self.assertRaises(ValueError):
            self.gate.preflight(now_s=12, star_speaking=1, gameplay_critical=False)
        self.gate.preflight(now_s=12, star_speaking=False, gameplay_critical=False)
        with self.assertRaises(ValueError):
            self.gate.preflight(now_s=11, star_speaking=False, gameplay_critical=False)

    def test_identity_and_receipt_replay_cannot_mark_spoken(self):
        intent = self.plan()
        self.assertFalse(self.gate.settle(object(), now_s=12.01,
                                          audible_confirmed=True))
        with self.assertRaises(ValueError):
            self.gate.settle(intent, now_s=12.01, audible_confirmed=1)
        self.gate.disable()
        self.assertFalse(self.gate.settle(intent, now_s=12.02,
                                          audible_confirmed=True))


if __name__ == "__main__":
    unittest.main()
