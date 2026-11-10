from __future__ import annotations

import json
import unittest

from star.stream_event_timeline import StreamEventTimeline, TimelineEvent


class StreamEventTimelineTests(unittest.TestCase):
    def setUp(self):
        self.timeline = StreamEventTimeline()
        self.session = self.timeline.enable(owner_approved=True, now_ms=1000.0)

    def event(self, *, modality="game", source="game0", seq=1, captured=1000.0,
              kind="damage", session=None, epoch=None, confidence=0.9, uncertainty=10.0):
        return TimelineEvent(
            session_id=session or self.session.session_id,
            clock_epoch=epoch or self.session.clock_epoch,
            source_id=source,
            modality=modality,
            sequence=seq,
            captured_ms=captured,
            kind=kind,
            evidence_sha256="a" * 64,
            confidence=confidence,
            uncertainty_ms=uncertainty,
        )

    def test_requires_owner_approval(self):
        other = StreamEventTimeline()
        with self.assertRaises(PermissionError):
            other.enable(now_ms=0.0)
        self.assertFalse(other.stats()["enabled"])

    def test_fresh_cross_modal_events_are_aligned(self):
        game = self.event(captured=1000.0)
        audio = self.event(modality="audio", source="audio0", captured=1080.0,
                           kind="speech_start", uncertainty=10.0)
        self.assertTrue(self.timeline.ingest(game, now_ms=1100.0).accepted)
        self.assertTrue(self.timeline.ingest(audio, now_ms=1100.0).accepted)
        snap = self.timeline.snapshot(now_ms=1100.0)
        self.assertEqual(set(snap.fresh_modalities), {"audio", "game"})
        self.assertEqual(len(snap.aligned_pairs), 1)
        self.assertEqual(snap.aligned_pairs[0].skew_ms, 80.0)
        self.assertTrue(snap.aligned_pairs[0].relative_order_confident)

    def test_uncertainty_prevents_confident_ordering(self):
        self.timeline.ingest(self.event(captured=1000.0, uncertainty=50.0), now_ms=1100.0)
        self.timeline.ingest(self.event(modality="vision", source="screen0",
                                        captured=1040.0, kind="visual_hazard",
                                        uncertainty=30.0), now_ms=1100.0)
        pair = self.timeline.snapshot(now_ms=1100.0).aligned_pairs[0]
        self.assertFalse(pair.relative_order_confident)

    def test_same_modality_events_do_not_form_cross_modal_pair(self):
        self.timeline.ingest(self.event(captured=1000.0), now_ms=1100.0)
        self.timeline.ingest(self.event(source="game1", seq=1, captured=1010.0), now_ms=1100.0)
        self.assertEqual(self.timeline.snapshot(now_ms=1100.0).aligned_pairs, ())

    def test_rejects_stale_and_future_events(self):
        stale = self.timeline.ingest(self.event(captured=0.0), now_ms=3000.0)
        future = self.timeline.ingest(self.event(source="game1", captured=1200.0), now_ms=1000.0)
        self.assertEqual(stale.reason, "stale_event")
        self.assertEqual(future.reason, "future_dated")

    def test_allows_small_clock_jitter(self):
        result = self.timeline.ingest(self.event(captured=1010.0), now_ms=1000.0)
        self.assertTrue(result.accepted)
        self.assertEqual(self.timeline.snapshot(now_ms=1000.0).events[0].age_ms, 0.0)

    def test_rejects_old_session_and_clock_epoch(self):
        old = self.event()
        self.timeline.disable()
        new_session = self.timeline.enable(owner_approved=True, now_ms=2000.0)
        self.assertEqual(self.timeline.ingest(old, now_ms=2000.0).reason, "stale_session")
        self.assertNotEqual(old.session_id, new_session.session_id)
        wrong_epoch = self.event(epoch="f" * 16, session=new_session.session_id)
        self.assertEqual(self.timeline.ingest(wrong_epoch, now_ms=2000.0).reason, "clock_epoch_mismatch")

    def test_rejects_duplicate_and_out_of_order_sequences(self):
        self.assertTrue(self.timeline.ingest(self.event(seq=4), now_ms=1000.0).accepted)
        for seq in (4, 3):
            result = self.timeline.ingest(self.event(seq=seq), now_ms=1000.0)
            self.assertEqual(result.reason, "replayed_or_out_of_order_sequence")

    def test_rejects_source_capture_clock_regression(self):
        self.timeline.ingest(self.event(seq=1, captured=1000.0), now_ms=1000.0)
        result = self.timeline.ingest(self.event(seq=2, captured=999.0), now_ms=1000.0)
        self.assertEqual(result.reason, "source_clock_reversed")

    def test_host_clock_regression_faults_and_clears_session(self):
        self.timeline.ingest(self.event(), now_ms=1100.0)
        result = self.timeline.ingest(self.event(source="game1"), now_ms=1099.0)
        self.assertEqual(result.reason, "host_clock_untrusted")
        snap = self.timeline.snapshot(now_ms=1100.0)
        self.assertTrue(snap.faulted)
        self.assertEqual(snap.events, ())
        self.assertEqual(self.timeline.stats()["buffered_events"], 0)

    def test_new_session_clears_clock_fault(self):
        self.timeline.ingest(self.event(), now_ms=1000.0)
        self.timeline.ingest(self.event(source="game1"), now_ms=999.0)
        self.timeline.disable()
        self.timeline.enable(owner_approved=True, now_ms=2000.0)
        self.assertFalse(self.timeline.stats()["faulted"])

    def test_source_and_event_limits_are_enforced(self):
        small = StreamEventTimeline(max_sources=1, max_events=8)
        sess = small.enable(owner_approved=True, now_ms=1000.0)
        first = TimelineEvent(sess.session_id, sess.clock_epoch, "a", "game", 1,
                              1000.0, "damage", "a" * 64)
        second = TimelineEvent(sess.session_id, sess.clock_epoch, "b", "audio", 1,
                               1000.0, "speech_start", "b" * 64)
        self.assertTrue(small.ingest(first, now_ms=1000.0).accepted)
        self.assertEqual(small.ingest(second, now_ms=1000.0).reason, "source_limit_reached")

    def test_event_buffer_is_bounded(self):
        small = StreamEventTimeline(max_events=8)
        sess = small.enable(owner_approved=True, now_ms=1000.0)
        for seq in range(1, 11):
            event = TimelineEvent(sess.session_id, sess.clock_epoch, "game0", "game",
                                  seq, 1000.0 + seq, "damage", "c" * 64)
            small.ingest(event, now_ms=1010.0)
        snap = small.snapshot(now_ms=1010.0)
        self.assertEqual(len(snap.events), 8)
        self.assertEqual(snap.accepted_total, 10)

    def test_snapshot_prunes_stale_events_but_keeps_replay_watermark(self):
        self.timeline.ingest(self.event(seq=1, captured=1000.0), now_ms=1000.0)
        snap = self.timeline.snapshot(now_ms=4000.0)
        self.assertEqual(snap.events, ())
        self.assertEqual(snap.stale_pruned, 1)
        replay = self.timeline.ingest(self.event(seq=1, captured=4000.0), now_ms=4000.0)
        self.assertEqual(replay.reason, "replayed_or_out_of_order_sequence")

    def test_disable_clears_session_and_events(self):
        self.timeline.ingest(self.event(), now_ms=1000.0)
        self.timeline.disable()
        self.assertFalse(self.timeline.stats()["enabled"])
        self.assertEqual(self.timeline.stats()["buffered_events"], 0)
        self.assertEqual(self.timeline.stats()["sources"], 0)

    def test_rejects_invalid_modality_kind_pair(self):
        with self.assertRaises(ValueError):
            self.event(modality="audio", kind="damage")

    def test_rejects_nonfinite_and_boolean_numeric_values(self):
        with self.assertRaises(ValueError):
            self.event(confidence=float("nan"))
        with self.assertRaises(ValueError):
            self.event(confidence=True)
        with self.assertRaises(ValueError):
            self.event(captured=True)

    def test_context_contains_metadata_only(self):
        self.timeline.ingest(self.event(), now_ms=1000.0)
        snap = self.timeline.snapshot(now_ms=1000.0)
        payload = json.loads(snap.context_json())
        encoded = json.dumps(payload)
        self.assertEqual(payload["type"], "star_stream_timeline_metadata")
        for forbidden in ("transcript", "audio_bytes", "viewer_name", "prompt",
                          "game0", self.session.session_id, self.session.clock_epoch):
            self.assertNotIn(forbidden, encoded)

    def test_context_is_bounded(self):
        small = StreamEventTimeline(max_events=128)
        sess = small.enable(owner_approved=True, now_ms=1000.0)
        for source in range(1, 17):
            for seq in range(1, 9):
                event = TimelineEvent(sess.session_id, sess.clock_epoch, f"s{source}", "game",
                                      seq, 1000.0 + seq, "damage", f"{source:032x}{seq:032x}")
                small.ingest(event, now_ms=1010.0)
        self.assertLessEqual(len(small.snapshot(now_ms=1010.0).context_json().encode()), 16384)

    def test_alignment_pair_count_is_bounded(self):
        small = StreamEventTimeline(max_sources=16, max_alignment_pairs=3)
        sess = small.enable(owner_approved=True, now_ms=1000.0)
        modalities = [
            ("game", "damage"), ("audio", "speech_start"),
            ("vision", "visual_hazard"), ("chat", "viewer_question"),
        ]
        for index, (modality, kind) in enumerate(modalities):
            event = TimelineEvent(sess.session_id, sess.clock_epoch, f"src{index}", modality,
                                  1, 1000.0 + index, kind, f"{index + 1:064x}")
            small.ingest(event, now_ms=1010.0)
        self.assertEqual(len(small.snapshot(now_ms=1010.0).aligned_pairs), 3)

    def test_equal_capture_times_are_allowed_when_sequence_advances(self):
        self.assertTrue(self.timeline.ingest(self.event(seq=1), now_ms=1000.0).accepted)
        self.assertTrue(self.timeline.ingest(self.event(seq=2), now_ms=1000.0).accepted)

    def test_rejected_stale_event_does_not_advance_watermark(self):
        self.timeline.ingest(self.event(seq=1), now_ms=1000.0)
        stale = self.timeline.ingest(self.event(seq=2, captured=0.0), now_ms=3000.0)
        fresh = self.timeline.ingest(self.event(seq=2, captured=3000.0), now_ms=3000.0)
        self.assertEqual(stale.reason, "stale_event")
        self.assertTrue(fresh.accepted)

    def test_invalid_host_clock_fails_closed(self):
        self.timeline.ingest(self.event(), now_ms=1000.0)
        result = self.timeline.ingest(self.event(source="game1"), now_ms=float("nan"))
        self.assertEqual(result.reason, "host_clock_untrusted")
        snap = self.timeline.snapshot(now_ms=1000.0)
        self.assertTrue(snap.faulted)
        self.assertEqual(snap.events, ())

    def test_oversized_confidence_is_rejected(self):
        with self.assertRaises(ValueError):
            self.event(confidence=10**10000)

    def test_event_keys_are_opaque_and_do_not_expose_source_or_evidence(self):
        result = self.timeline.ingest(self.event(source="possibly-sensitive-source"), now_ms=1000.0)
        self.assertTrue(result.accepted)
        self.assertEqual(len(result.event_key), 20)
        self.assertNotIn("possibly-sensitive-source", result.event_key)
        self.assertNotIn("a" * 64, result.event_key)


if __name__ == "__main__":
    unittest.main()
