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
