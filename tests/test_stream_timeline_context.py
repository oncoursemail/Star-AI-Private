"""Event-bound stream context: bounded metadata, freshness and stage correlation."""
from __future__ import annotations

from dataclasses import replace
import json
import unittest

from star.stream_director import StreamSignal
from star.stream_event_timeline import StreamEventTimeline, TimelineEvent
from star.stream_stage import StarStage
from star.stream_timeline_context import (
    MAX_CONTEXT_BYTES,
    TimelineContextPacket,
    build_timeline_context,
)


def make_packet(*, modality="game", kind="victory", captured_ms=1000.0,
                with_pair=True, snapshot_ms=1050.0, max_age_ms=1000.0):
    timeline = StreamEventTimeline()
    session = timeline.enable(owner_approved=True, now_ms=1000.0)
    event = TimelineEvent(
        session.session_id, session.clock_epoch, "game0", modality, 1,
        captured_ms, kind, "a" * 64, 0.95, 10.0,
    )
    receipt = timeline.ingest(event, now_ms=max(1000.0, captured_ms))
    if with_pair:
        pair = TimelineEvent(
            session.session_id, session.clock_epoch, "audio0", "audio", 1,
            1040.0, "speech_start", "b" * 64, 0.90, 10.0,
        )
        timeline.ingest(pair, now_ms=max(1040.0, captured_ms))
    snapshot = timeline.snapshot(now_ms=snapshot_ms)
    packet = build_timeline_context(snapshot, receipt.event_key, max_age_ms=max_age_ms)
    return timeline, receipt, snapshot, packet


class TimelineContextTests(unittest.TestCase):
    def test_builds_compact_event_and_only_its_aligned_metadata(self):
        _, _, _, packet = make_packet()
        self.assertIsNotNone(packet)
        self.assertEqual(packet.modality, "game")
        self.assertEqual(packet.kind, "victory")
        self.assertEqual(packet.pair_count, 1)
        self.assertLessEqual(len(packet.context_record.encode("utf-8")), MAX_CONTEXT_BYTES)
        payload = json.loads(packet.context_record.split("\n", 1)[1])
        self.assertEqual(payload["event"]["kind"], "victory")
        self.assertEqual(payload["aligned"][0]["other_kind"], "speech_start")
        self.assertEqual(payload["fresh_modalities"], ["audio", "game"])

    def test_never_copies_source_session_media_chat_or_evidence_identifiers(self):
        _, _, _, packet = make_packet()
        self.assertIsNotNone(packet)
        for forbidden in (
            "game0", "audio0", "session_id", "clock_epoch", "evidence_sha256",
            "transcript", "viewer_name", "source_id", "raw_chat",
        ):
            self.assertNotIn(forbidden, packet.context_record)

    def test_stale_or_missing_event_returns_no_packet(self):
        timeline, receipt, _, _ = make_packet()
        stale = timeline.snapshot(now_ms=2001.0)
        self.assertIsNone(build_timeline_context(stale, receipt.event_key))
        self.assertIsNone(build_timeline_context(stale, "f" * 20))

    def test_faulted_clock_returns_no_packet(self):
        timeline, receipt, _, _ = make_packet()
        faulted = timeline.snapshot(now_ms=999.0)
        self.assertTrue(faulted.faulted)
        self.assertIsNone(build_timeline_context(faulted, receipt.event_key))

    def test_inconsistent_event_age_is_rejected(self):
        _, receipt, snapshot, _ = make_packet()
        changed = replace(snapshot.events[0], age_ms=900.0)
        altered = replace(snapshot, events=(changed, *snapshot.events[1:]))
        self.assertIsNone(build_timeline_context(altered, receipt.event_key))

    def test_alignment_must_reference_exact_fresh_snapshot_summaries(self):
        _, receipt, snapshot, _ = make_packet()
        pair = snapshot.aligned_pairs[0]
        forged_other = replace(pair.later, event_key="f" * 20)
        forged_pair = replace(pair, later=forged_other)
        forged_snapshot = replace(snapshot, aligned_pairs=(forged_pair,))
        self.assertIsNone(build_timeline_context(forged_snapshot, receipt.event_key))

        stale_other = replace(pair.later, age_ms=900.0)
        stale_pair = replace(pair, later=stale_other)
        stale_snapshot = replace(
            snapshot,
            events=(snapshot.events[0], stale_other),
            aligned_pairs=(stale_pair,),
        )
        self.assertIsNone(build_timeline_context(stale_snapshot, receipt.event_key))

        duplicate_snapshot = replace(
            snapshot, events=(*snapshot.events, snapshot.events[0]),
        )
        self.assertIsNone(build_timeline_context(duplicate_snapshot, receipt.event_key))


    def test_caps_aligned_pairs(self):
        timeline = StreamEventTimeline()
        session = timeline.enable(owner_approved=True, now_ms=1000.0)
        primary = TimelineEvent(
            session.session_id, session.clock_epoch, "game0", "game", 1,
            1000.0, "victory", "a" * 64, 0.95, 5.0,
        )
        receipt = timeline.ingest(primary, now_ms=1000.0)
        sources = (
            ("audio", "audio0", "speech_start"),
            ("vision", "screen0", "scene_change"),
            ("chat", "chat0", "viewer_reaction"),
            ("avatar", "avatar0", "expression_started"),
            ("host", "host0", "session_marker"),
        )
        for index, (modality, source, kind) in enumerate(sources, 1):
            item = TimelineEvent(
                session.session_id, session.clock_epoch, source, modality, 1,
                1000.0 + index, kind, str(index) * 64, 0.8, 5.0,
            )
            timeline.ingest(item, now_ms=1000.0 + index)
        snapshot = timeline.snapshot(now_ms=1010.0)
        packet = build_timeline_context(snapshot, receipt.event_key, max_pairs=2)
        self.assertIsNotNone(packet)
        self.assertEqual(packet.pair_count, 2)

    def test_max_pairs_cannot_exceed_packet_schema_limit(self):
        _, receipt, snapshot, _ = make_packet()
        with self.assertRaises(ValueError):
            build_timeline_context(snapshot, receipt.event_key, max_pairs=5)

    def test_packet_constructor_rejects_private_fields_even_with_valid_header(self):
        _, _, _, packet = make_packet()
        self.assertIsNotNone(packet)
        payload = json.loads(packet.context_record.split("\n", 1)[1])
        payload["event"]["source_id"] = "private-viewer-id"
        from star.stream_timeline_context import _HEADER
        forged = _HEADER + "\n" + json.dumps(payload, separators=(",", ":"))
        with self.assertRaises(ValueError):
            replace(packet, context_record=forged)

    def test_invalid_event_key_and_packet_shape_are_rejected(self):
        _, _, snapshot, _ = make_packet()
        with self.assertRaises(ValueError):
            build_timeline_context(snapshot, "not-an-event")
        with self.assertRaises(ValueError):
            TimelineContextPacket(
                "a" * 20, "game", "victory", 1050.0, 1000.0, 50.0,
                0, "untrusted prompt",
            )


class TimelineStageIntegrationTests(unittest.TestCase):
    def stage_for(self, packet, *, signal_id=None, kind="game_success", now=1.05):
        stage = StarStage(clock=lambda: now)
        stage.enable(owner_approved=True)
        event_id = packet.event_key if signal_id is None else signal_id
        signal = StreamSignal(
            event_id, kind, 1.05, "Star observed a game event",
            evidence="observed",
        )
        self.assertTrue(stage.offer(signal, now=now))
        return stage

    def test_stage_attaches_only_the_exact_matching_current_game_event(self):
        _, _, _, packet = make_packet()
        stage = self.stage_for(packet)
        plan = stage.prepare(now=1.05, timeline_context=packet)
        self.assertIsNotNone(plan)
        self.assertIn("STAR LIVE EVENT METADATA", plan.context_record)
        self.assertEqual(stage.metrics()["timeline_context_attached"], 1)
        self.assertEqual(stage.metrics()["timeline_context_rejected"], 0)

    def test_mismatched_event_key_is_not_injected(self):
        _, _, _, packet = make_packet()
        stage = self.stage_for(packet, signal_id="f" * 20)
        plan = stage.prepare(now=1.05, timeline_context=packet)
        self.assertIsNotNone(plan)
        self.assertNotIn("STAR LIVE EVENT METADATA", plan.context_record)
        self.assertEqual(stage.metrics()["timeline_context_rejected"], 1)

    def test_event_kind_must_match_the_selected_speech_intent(self):
        _, _, _, packet = make_packet(kind="damage")
        stage = self.stage_for(packet, kind="game_success")
        plan = stage.prepare(now=1.05, timeline_context=packet)
        self.assertIsNotNone(plan)
        self.assertNotIn("STAR LIVE EVENT METADATA", plan.context_record)
        self.assertEqual(stage.metrics()["timeline_context_rejected"], 1)

    def test_snapshot_must_be_fresh_at_the_actual_stage_use_time(self):
        _, _, _, packet = make_packet()
        stage = self.stage_for(packet, now=1.31)
        plan = stage.prepare(now=1.31, timeline_context=packet)
        self.assertIsNotNone(plan)
        self.assertNotIn("STAR LIVE EVENT METADATA", plan.context_record)
        self.assertEqual(stage.metrics()["timeline_context_rejected"], 1)

    def test_unmoderated_viewer_signal_cannot_receive_timeline_context(self):
        _, _, _, packet = make_packet(modality="chat", kind="viewer_question")
        stage = StarStage(clock=lambda: 1.05)
        stage.enable(owner_approved=True)
        signal = StreamSignal(
            packet.event_key, "viewer_question", 1.05, "Where is the objective?",
            speaker_id="viewer-A", evidence="unknown",
        )
        self.assertFalse(stage.offer(signal, now=1.05, moderated=False))
        self.assertIsNone(stage.prepare(now=1.05, timeline_context=packet))

    def test_context_argument_requires_the_validated_packet_type(self):
        stage = StarStage(clock=lambda: 1.05)
        stage.enable(owner_approved=True)
        with self.assertRaises(TypeError):
            stage.prepare(now=1.05, timeline_context=object())


if __name__ == "__main__":
    unittest.main()
