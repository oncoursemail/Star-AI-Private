"""Deterministic host-boundary tests; never open devices or send audio."""
from __future__ import annotations

import unittest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_epoch_pcm_sink import LocalEpochPCMSink
from star.stream_load_governor import StreamLoadGovernor, StreamLoadSample
from star.stream_preplay_gate import PreplayDecision, StreamPreplayGate
from star.stream_preplay_pcm_bridge import StreamPreplayPCMBridge
from star.stream_turntaking import TurnTakingGate, VoiceFrame


class DummyPCM:
    sample_rate = 24_000

    def __init__(self):
        self.pending = 0.0
        self.queued = []
        self.stops = 0
        self.fail_stop = False

    def pending_seconds(self):
        return self.pending

    def play(self, pcm, sample_rate):
        assert sample_rate == self.sample_rate
        self.queued.append(pcm)
        self.pending += len(pcm) / (2 * sample_rate)

    def stop(self):
        self.stops += 1
        if self.fail_stop:
            raise OSError("test injected PortAudio failure")
        self.pending = 0.0


class PCMBridgeTests(unittest.TestCase):
    def setUp(self):
        director = StreamDirector()
        director.enable(owner_approved=True)
        turns = TurnTakingGate()
        turns.enable(owner_approved=True)
        load = StreamLoadGovernor()
        load.enable(owner_approved=True)
        for i in range(3):
            self.assertTrue(load.ingest(StreamLoadSample(
                sample_id=f"healthy{i}", measured_at_s=10.0 + i,
                game_p95_frame_ms=12.0, game_target_fps=60.0,
                obs_render_missed_pct=0.0, obs_encode_skipped_pct=0.0,
                obs_network_dropped_pct=0.0,
                gpu_vram_used_mb=4000.0, gpu_vram_total_mb=8192.0,
                tts_first_audio_p95_ms=150.0,
            ), now_s=10.0 + i, host_verified=True))
        turns.observe(VoiceFrame(12000.0, 30.0, 0.0, 0.0, True))
        self.director = director
        self.gate = StreamPreplayGate(director, turns, load)
        self.gate.enable(owner_approved=True)
        self.speaker = DummyPCM()
        self.sink = LocalEpochPCMSink(self.speaker)
        self.sink.enable(owner_approved=True)
        self.bridge = StreamPreplayPCMBridge(self.gate, self.sink)
        self.director.offer(StreamSignal(
            "q1", "viewer_question", 12.0, "How did you win?",
            speaker_id="viewer1", evidence="reported",
        ), now=12.0)
        candidate = self.gate.preflight(
            now_s=12.0, star_speaking=False, gameplay_critical=False)
        self.assertEqual(candidate.status, "candidate")
        self.intent = candidate.intent
        self.review = self.gate.revalidate(
            self.intent, now_s=12.05,
            star_speaking=False, gameplay_critical=False)
        self.assertEqual(self.review.status, "reviewed")

    def admit(self, epoch="voice_1", at=12.06, quiet=True):
        return self.bridge.admit(
            self.review, epoch=epoch, now_s=at, independently_quiet=quiet)

    def test_disabled_by_default_and_owner_opt_in(self):
        self.assertEqual(self.admit().state, "disabled")
        with self.assertRaises(PermissionError):
            self.bridge.enable()
        self.bridge.enable(owner_approved=True)
        self.assertEqual(self.admit().state, "ready")
        self.assertFalse(self.bridge.submit(self.intent, epoch="voice_2", pcm16=b"xy"))

    def test_stale_review_and_fake_review_cannot_bind(self):
        self.bridge.enable(owner_approved=True)
        bad = PreplayDecision("reviewed", "fake", None)
        self.assertEqual(self.bridge.admit(bad, epoch="fake", now_s=12.06,
                                           independently_quiet=True).state, "held")
        self.assertEqual(self.admit(at=12.31).state, "held")
        self.assertEqual(self.sink.metrics()["unique_epochs"], 0)

    def test_fresh_review_and_native_quiet_required(self):
        self.bridge.enable(owner_approved=True)
        self.assertEqual(self.admit(quiet=False).state, "held")
        self.assertEqual(self.admit().state, "ready")
        self.assertEqual(self.admit(epoch="another").state, "held")
        self.assertFalse(self.bridge.metrics()["stop_outstanding"])

    def test_pcm_only_on_exact_reviewed_intent_epoch(self):
        self.bridge.enable(owner_approved=True)
        self.assertEqual(self.admit().state, "ready")
        self.assertFalse(self.bridge.submit(self.intent, epoch="other", pcm16=b"aa"))
        self.assertFalse(self.bridge.submit(self.intent, epoch="voice_1", pcm16=b"a"))
        self.assertTrue(self.bridge.submit(self.intent, epoch="voice_1", pcm16=b"aa"))
        self.assertEqual(self.speaker.queued, [b"aa"])
        self.assertEqual(self.bridge.metrics()["pcm_rejected"], 2)

    def test_utterance_budget_stops_runaway_tts_and_requires_native_quiet(self):
        bridge = StreamPreplayPCMBridge(
            self.gate, self.sink, max_turn_pcm_ms=1_000,
        )
        bridge.enable(owner_approved=True)
        self.assertEqual(bridge.admit(
            self.review, epoch="voice_limit", now_s=12.06,
            independently_quiet=True).state, "ready")
        # Five 200-ms chunks total exactly one second. Simulated native
        # playback frees the application buffer, not the lifetime budget.
        for _ in range(5):
            self.speaker.pending = 0.0
            self.assertTrue(bridge.submit(
                self.intent, epoch="voice_limit", pcm16=b"aa" * 4800))
        self.assertEqual(bridge.metrics()["turn_pcm_ms_submitted"], 1000)
        self.speaker.pending = 0.0
        self.assertFalse(bridge.submit(
            self.intent, epoch="voice_limit", pcm16=b"aa"))
        self.assertEqual(bridge.metrics()["utterance_budget_stops"], 1)
        self.assertTrue(bridge.metrics()["stop_outstanding"])
        self.assertEqual(self.speaker.stops, 1)
        self.assertEqual(len(self.speaker.queued), 5)
        self.assertFalse(bridge.submit(
            self.intent, epoch="voice_limit", pcm16=b"aa"))
        with self.assertRaises(RuntimeError):
            bridge.enable(owner_approved=True)
        self.assertEqual(bridge.attest_quiet(
            self.intent, epoch="voice_limit", now_s=12.11,
            host_verified=False, native_output_flushed=True).state, "held")
        self.assertEqual(bridge.attest_quiet(
            self.intent, epoch="voice_limit", now_s=12.12,
            host_verified=True, native_output_flushed=True).state, "quiet")
        self.assertEqual(bridge.metrics()["turn_pcm_ms_submitted"], 0)
        self.assertFalse(bridge.metrics()["stop_outstanding"])
        self.gate.enable(owner_approved=True)
        bridge.enable(owner_approved=True)

    def test_budget_validation_and_invalid_pcm_do_not_consume_allowance(self):
        for invalid in (0, True, 999, 60_001, 3.5, "30000", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                StreamPreplayPCMBridge(
                    self.gate, self.sink, max_turn_pcm_ms=invalid)
        bridge = StreamPreplayPCMBridge(
            self.gate, self.sink, max_turn_pcm_ms=1_000)
        self.assertEqual(self.sink.sample_rate, 24_000)
        bridge.enable(owner_approved=True)
        self.assertEqual(bridge.admit(
            self.review, epoch="voice_invalid", now_s=12.06,
            independently_quiet=True).state, "ready")
        self.assertFalse(bridge.submit(
            self.intent, epoch="voice_invalid", pcm16=b"odd"))
        self.assertFalse(bridge.submit(
            self.intent, epoch="voice_invalid", pcm16="audio"))
        self.assertEqual(bridge.metrics()["turn_pcm_ms_submitted"], 0)
        self.assertEqual(bridge.metrics()["utterance_budget_stops"], 0)
        self.assertEqual(self.speaker.stops, 0)
        self.assertTrue(bridge.submit(
            self.intent, epoch="voice_invalid", pcm16=b"aa"))
        self.assertEqual(bridge.metrics()["turn_pcm_ms_submitted"], 0)
        self.assertEqual(bridge.disable().state, "stop_requested")

    def test_normal_spoken_completion_requires_independent_playout_evidence(self):
        self.bridge.enable(owner_approved=True)
        self.assertEqual(self.admit().state, "ready")
        self.assertEqual(self.bridge.complete_turn(
            self.intent, epoch="voice_1", now_s=12.07,
            host_verified=True, independent_audible_pcm=True,
            native_output_flushed=True).reason,
            "independent_audible_quiet_receipts_missing")
        self.assertTrue(self.bridge.submit(
            self.intent, epoch="voice_1", pcm16=b"aa" * 2400))
        self.assertGreater(self.sink.buffered_ms(), 0)
        self.assertEqual(self.bridge.complete_turn(
            self.intent, epoch="voice_1", now_s=12.08,
            host_verified=True, independent_audible_pcm=True,
            native_output_flushed=True).reason, "app_pcm_not_naturally_drained")
        self.assertEqual(self.speaker.stops, 0)
        # Simulated buffer draining is not itself native audible receipt.
        self.speaker.pending = 0.0
        for flags in [
            dict(host_verified=False, independent_audible_pcm=True,
                 native_output_flushed=True),
            dict(host_verified=True, independent_audible_pcm=False,
                 native_output_flushed=True),
            dict(host_verified=True, independent_audible_pcm=True,
                 native_output_flushed=False),
        ]:
            self.assertEqual(self.bridge.complete_turn(
                self.intent, epoch="voice_1", now_s=12.09, **flags).state,
                "held")
        self.assertEqual(self.director.metrics()["completed"], 0)
        self.assertEqual(self.bridge.complete_turn(
            self.intent, epoch="wrong", now_s=12.09, host_verified=True,
            independent_audible_pcm=True, native_output_flushed=True).state,
            "held")
        self.assertEqual(self.bridge.complete_turn(
            self.intent, epoch="voice_1", now_s=12.10,
            host_verified=True, independent_audible_pcm=True,
            native_output_flushed=True).reason,
            "host_witnessed_audible_turn_completed")
        self.assertEqual(self.speaker.stops, 1)
        self.assertEqual(self.director.metrics()["completed"], 1)
        self.assertEqual(self.bridge.metrics()["spoken_completions"], 1)
        self.assertFalse(self.bridge.metrics()["native_epoch_active"])
        self.assertEqual(self.bridge.complete_turn(
            self.intent, epoch="voice_1", now_s=12.11,
            host_verified=True, independent_audible_pcm=True,
            native_output_flushed=True).state, "held")

    def test_completion_failed_physical_stop_requires_manual_recovery(self):
        self.bridge.enable(owner_approved=True)
        self.admit()
        self.assertTrue(self.bridge.submit(
            self.intent, epoch="voice_1", pcm16=b"aa"))
        self.speaker.pending = 0.0
        self.speaker.fail_stop = True
        self.assertEqual(self.bridge.complete_turn(
            self.intent, epoch="voice_1", now_s=12.10,
            host_verified=True, independent_audible_pcm=True,
            native_output_flushed=True).state, "fault")
        self.assertEqual(self.director.metrics()["completed"], 0)
        with self.assertRaises(RuntimeError):
            self.bridge.enable(owner_approved=True)

    def test_invalid_normal_completion_receipts_cannot_be_used(self):
        self.bridge.enable(owner_approved=True)
        self.admit()
        self.assertTrue(self.bridge.submit(
            self.intent, epoch="voice_1", pcm16=b"aa"))
        for bad in (1, "yes", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.bridge.complete_turn(
                    self.intent, epoch="voice_1", now_s=12.10,
                    host_verified=bad,
                    independent_audible_pcm=True, native_output_flushed=True)
        self.assertFalse(self.bridge.metrics()["faulted"])

    def test_stop_requires_native_flush_before_unlock(self):
        self.bridge.enable(owner_approved=True)
        self.admit()
        self.bridge.submit(self.intent, epoch="voice_1", pcm16=b"aa")
        self.assertEqual(self.bridge.disable().state, "stop_requested")
        self.assertEqual(self.speaker.stops, 1)
        self.assertFalse(self.bridge.submit(self.intent, epoch="voice_1", pcm16=b"bb"))
        with self.assertRaises(RuntimeError):
            self.bridge.enable(owner_approved=True)
        with self.assertRaises(RuntimeError):
            self.gate.enable(owner_approved=True)
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="voice_1", now_s=12.10,
            host_verified=True, native_output_flushed=False).state, "held")
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="voice_1", now_s=12.11,
            host_verified=False, native_output_flushed=True).state, "held")
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="voice_1", now_s=12.12,
            host_verified=True, native_output_flushed=True).state, "quiet")
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="voice_1", now_s=12.13,
            host_verified=True, native_output_flushed=True).state, "held")
        self.assertEqual(self.bridge.metrics()["stops_verified"], 1)
        self.gate.enable(owner_approved=True)
        self.bridge.enable(owner_approved=True)
        self.assertEqual(self.director.metrics()["completed"], 0)

    def test_wrong_epoch_and_reused_receipts_cannot_release_quarantine(self):
        self.bridge.enable(owner_approved=True)
        self.admit()
        self.bridge.disable()
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="other", now_s=12.10,
            host_verified=True, native_output_flushed=True).state, "held")
        self.assertTrue(self.gate.lifecycle_metrics()["restart_quarantined"])
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="voice_1", now_s=12.10,
            host_verified=True, native_output_flushed=True).state, "quiet")
        self.assertEqual(self.bridge.disable().state, "disabled")

    def test_stop_failure_latches_fault_no_restart(self):
        self.bridge.enable(owner_approved=True)
        self.admit()
        self.speaker.fail_stop = True
        self.assertEqual(self.bridge.disable().state, "fault")
        self.assertTrue(self.bridge.metrics()["faulted"])
        self.assertEqual(self.bridge.attest_quiet(
            self.intent, epoch="voice_1", now_s=12.12,
            host_verified=True, native_output_flushed=True).state, "held")
        with self.assertRaises(RuntimeError):
            self.bridge.enable(owner_approved=True)
        with self.assertRaises(RuntimeError):
            self.gate.enable(owner_approved=True)

    def test_revoked_review_cannot_submit_after_external_disable(self):
        self.bridge.enable(owner_approved=True)
        self.admit()
        self.gate.disable()
        self.assertFalse(self.bridge.submit(self.intent, epoch="voice_1", pcm16=b"aa"))
        self.assertEqual(self.speaker.queued, [])

    def test_monotonic_clock_reversal_is_rejected(self):
        self.bridge.enable(owner_approved=True)
        with self.assertRaises(ValueError):
            self.admit(at=12.01)

    def test_invalid_quiet_evidence_types_rejected(self):
        self.bridge.enable(owner_approved=True)
        with self.assertRaises(ValueError):
            self.bridge.admit(self.review, epoch="e", now_s=12.06,
                              independently_quiet=1)
        self.admit()
        self.bridge.disable()
        with self.assertRaises(ValueError):
            self.bridge.attest_quiet(self.intent, epoch="voice_1",
                                      now_s=12.10, host_verified=1,
                                      native_output_flushed=True)


if __name__ == "__main__":
    unittest.main()
