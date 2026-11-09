"""Offline simulated playout tests: zero real PCM, OBS, mic or games."""
from __future__ import annotations

import unittest

from star.stream_director import StreamSignal
from star.stream_preplay_fence import PreplayWitness, assess_preplay
from star.stream_stage import StarStage
from star.stream_turntaking import TurnAdvice

QUIET = TurnAdvice("speak", False, "trusted_silence")
BUSY = TurnAdvice("hold", False, "confirmed_guest_voice")
YIELD = TurnAdvice("yield_owner", True, "confirmed_authenticated_owner_voice")


def witness(at: float = 1.02, **overrides: object) -> PreplayWitness:
    data = {
        "observed_at_s": at, "turn": QUIET, "game_scope": "obby_round1",
        "gameplay_critical": False, "stream_pressure": False,
        "pcm_output_ready": True, "host_verified": True,
    }
    data.update(overrides)
    return PreplayWitness(**data)  # type: ignore[arg-type]


def preplay(*, kind: str = "viewer_question", evidence: str = "unknown",
            game_scope: str = "", w: PreplayWitness | None = None,
            now: float = 1.04):
    return assess_preplay(
        kind=kind, evidence=evidence, game_scope=game_scope,
        witness=w if w is not None else witness(), now_s=now,
    )


def stage_with_plan(kind: str = "viewer_question", evidence: str = "unknown"):
    stage = StarStage(clock=lambda: 1.0)
    stage.enable(owner_approved=True, require_preplay_witness=True)
    signal = StreamSignal(
        "turn-1", kind, 1.0, "A short host-curated observation",
        speaker_id="viewer1" if kind.startswith("viewer") else "",
        evidence=evidence, game_scope="obby_round1" if kind.startswith("game_") else "",
    )
    assert stage.offer(signal, now=1.0, moderated=True)
    plan = stage.prepare(now=1.0)
    assert plan is not None
    assert stage.queue_audio(plan, now=1.01)
    return stage, plan


class TestPreplayWitness(unittest.TestCase):
    def test_fresh_quiet_is_advice_never_permission(self):
        result = preplay()
        self.assertTrue(result.eligible)
        self.assertFalse(result.authorizes_audio_output)
        self.assertFalse(result.authorizes_broadcast)

    def test_unattested_and_stale_and_future_fail_quiet(self):
        self.assertEqual(preplay(w=witness(host_verified=False)).reason,
                         "trusted_host_snapshot_missing")
        self.assertEqual(preplay(w=witness(at=0.9)).reason,
                         "snapshot_stale_or_future")
        self.assertEqual(preplay(w=witness(at=1.05)).reason,
                         "snapshot_stale_or_future")
        self.assertEqual(preplay(w=witness(pcm_output_ready=False)).reason,
                         "pcm_device_not_ready")

    def test_viewer_speaking_and_owner_barge_in_block_planned_audio(self):
        self.assertEqual(
            preplay(w=witness(turn=BUSY)).reason,
            "another_speaker_or_uncertain_quiet",
        )
        self.assertEqual(
            preplay(w=witness(turn=YIELD)).reason, "owner_barge_in_yield",
        )
        self.assertFalse(preplay(kind="owner_interrupt", w=witness(turn=YIELD)).eligible)

    def test_critical_gameplay_suppresses_chatter_not_verified_danger(self):
        self.assertEqual(preplay(w=witness(gameplay_critical=True)).reason,
                         "critical_gameplay_requires_silence")
        self.assertTrue(preplay(
            kind="game_danger", evidence="observed", game_scope="obby_round1",
            w=witness(gameplay_critical=True),
        ).eligible)
        self.assertFalse(preplay(
            kind="game_danger", evidence="reported", game_scope="obby_round1",
            w=witness(gameplay_critical=True),
        ).eligible)

    def test_stream_pressure_and_game_epoch_change(self):
        self.assertEqual(preplay(
            kind="game_success", evidence="observed", game_scope="obby_round1",
            w=witness(game_scope="another_scene"),
        ).reason, "game_scene_changed_or_unpinned")
        self.assertFalse(preplay(
            kind="game_success", evidence="observed", game_scope="",
        ).eligible)
        self.assertEqual(preplay(w=witness(stream_pressure=True)).reason,
                         "stream_audio_or_render_pressure")
        self.assertTrue(preplay(
            kind="owner_interrupt", w=witness(stream_pressure=True),
        ).eligible)

    def test_invalid_values_fail_before_any_side_effect(self):
        for bad in (False, float("inf"), float("nan"), -1, 10**1000):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                witness(observed_at_s=bad)
        with self.assertRaises(ValueError):
            witness(game_scope="user message with spaces")
        with self.assertRaises(ValueError):
            witness(voice_route_id="voice route with spaces")
        with self.assertRaises(TypeError):
            witness(turn="quiet")
        with self.assertRaises(ValueError):
            witness(host_verified=1)
        with self.assertRaises(ValueError):
            preplay(kind="untrusted_superuser")
        with self.assertRaises(ValueError):
            preplay(now=-1)
        with self.assertRaises(ValueError):
            assess_preplay(kind="viewer_question", evidence="unknown",
                           game_scope="", witness=witness(), now_s=1.04,
                           max_witness_age_s=5)


class TestStageStrictPreplay(unittest.TestCase):
    def test_strict_preplay_requires_clearance_before_audible_pcm(self):
        stage, plan = stage_with_plan()
        self.assertFalse(stage.acknowledge_audible(plan, now=1.02))
        self.assertEqual(stage.metrics()["phase"], "idle")
        self.assertEqual(stage.metrics()["preplay_blocked"], 1)

    def test_clearance_and_playback_start_success(self):
        stage, plan = stage_with_plan()
        self.assertTrue(stage.preplay_clearance(
            plan, witness=witness(at=1.02), now=1.02,
        ).eligible)
        self.assertTrue(stage.acknowledge_audible(plan, now=1.04))
        self.assertTrue(stage.current(plan))
        self.assertFalse(stage.acknowledge_audible(plan, now=1.05))
        self.assertTrue(stage.finish(plan, now=1.07, played_to_end=True))
        self.assertEqual(stage.metrics()["director"]["completed"], 1)

    def test_stale_clearance_cannot_launder_late_pcm(self):
        stage, plan = stage_with_plan()
        self.assertTrue(stage.preplay_clearance(
            plan, witness=witness(at=1.02), now=1.02,
        ).eligible)
        self.assertFalse(stage.acknowledge_audible(plan, now=1.13))
        self.assertEqual(stage.metrics()["phase"], "idle")

    def test_interruption_revokes_old_playout_even_when_new_turn_queued(self):
        stage, plan = stage_with_plan()
        self.assertTrue(stage.preplay_clearance(
            plan, witness=witness(at=1.02), now=1.02,
        ).eligible)
        stage.interrupt(now=1.025)
        self.assertFalse(stage.acknowledge_audible(plan, now=1.03))
        self.assertEqual(stage.metrics()["phase"], "idle")

    def test_voice_barge_in_and_scene_mismatch_block(self):
        stage, plan = stage_with_plan("game_success", "observed")
        self.assertEqual(stage.preplay_clearance(
            plan, witness=witness(turn=YIELD), now=1.02,
        ).reason, "owner_barge_in_yield")
        self.assertEqual(stage.metrics()["phase"], "idle")
        stage, plan = stage_with_plan("game_success", "observed")
        self.assertEqual(stage.preplay_clearance(
            plan, witness=witness(game_scope="new_round"), now=1.025,
        ).reason, "game_scene_changed_or_unpinned")
        self.assertEqual(stage.metrics()["phase"], "idle")
        self.assertFalse(stage.acknowledge_audible(plan, now=1.03))

    def test_host_can_retry_with_fresh_quiet_after_hold(self):
        stage, plan = stage_with_plan()
        self.assertFalse(stage.preplay_clearance(
            plan, witness=witness(turn=BUSY), now=1.02,
        ).eligible)
        self.assertTrue(stage.preplay_clearance(
            plan, witness=witness(at=1.05), now=1.06,
        ).eligible)
        self.assertTrue(stage.acknowledge_audible(plan, now=1.07))

    def test_expired_speech_is_never_played(self):
        stage, plan = stage_with_plan("game_danger", "observed")
        self.assertFalse(stage.preplay_clearance(
            plan, witness=witness(at=3.55), now=3.55,
        ).eligible)
        self.assertEqual(stage.metrics()["phase"], "idle")

    def test_legacy_default_remains_explicitly_opt_out(self):
        stage = StarStage(clock=lambda: 1.0)
        stage.enable(owner_approved=True)
        stage.offer(StreamSignal("legacy1", "viewer_question", 1.0,
                                 "A viewer question", speaker_id="viewer1"),
                    now=1.0, moderated=True)
        plan = stage.prepare(now=1.0)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertTrue(stage.queue_audio(plan, now=1.01))
        self.assertTrue(stage.acknowledge_audible(plan, now=1.02))
        self.assertFalse(stage.metrics()["require_preplay_witness"])

    def test_disable_resets_strict_mode(self):
        stage, plan = stage_with_plan()
        stage.preplay_clearance(plan, witness=witness(at=1.02), now=1.02)
        stage.disable()
        self.assertFalse(stage.metrics()["require_preplay_witness"])
        self.assertFalse(stage.acknowledge_audible(plan, now=1.03))


if __name__ == "__main__":
    unittest.main()