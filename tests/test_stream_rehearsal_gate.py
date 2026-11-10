import hashlib
import unittest
from dataclasses import replace

from star.stream_rehearsal_gate import (
    LaneReceipt,
    RehearsalManifest,
    SessionReceipt,
    evaluate_rehearsal,
    seal_lane_receipt,
    seal_session_receipt,
)

KEY = b"star-rehearsal-test-key-32-bytes!!"
ENV = hashlib.sha256(b"fixed test environment").hexdigest()
EVIDENCE = hashlib.sha256(b"lane evidence").hexdigest()
REV = "abcdef0123456789"


def metrics_for(lane):
    values = {
        "inference": {
            "ttft_p50_ms": 300, "ttft_p95_ms": 600, "tpot_p50_ms": 40,
            "completion_p95_ms": 3000, "quality_pass_rate": 0.9,
        },
        "speech": {
            "first_audible_p50_ms": 450, "first_audible_p95_ms": 800,
            "audio_underruns": 0, "false_interruption_rate": 0.02,
            "grounding_pass_rate": 0.95,
        },
        "turn_taking": {
            "addressee_accuracy": 0.9, "silence_precision": 0.95,
            "false_interruption_rate": 0.02, "missed_turn_rate": 0.03,
            "multiparty_comprehension": 0.8,
        },
        "gameplay": {
            "fps_p10": 58, "action_ack_p95_ms": 100,
            "objective_success_rate": 0.8, "scenario_diversity": 4,
            "stale_action_rate": 0.0,
        },
        "obs": {
            "dropped_frames_pct": 0.1, "render_lag_p95_ms": 15,
            "encode_lag_p95_ms": 20, "reconnects": 0,
        },
        "avatar": {
            "lip_sync_error_p95_ms": 30, "avatar_frame_drop_pct": 0.1,
            "tracking_lost_pct": 0.0,
        },
        "memory": {
            "transfer_gain": 0.1, "interference_rate": 0.02,
            "retention_rate": 0.9, "retrieval_p95_ms": 120,
        },
        "creator": {
            "build_pass_rate": 0.9, "playtest_pass_rate": 0.8,
            "regression_count": 0, "visual_check_pass_rate": 0.85,
        },
    }
    return values[lane]


def build_campaign(status_overrides=None, sample_count=10):
    manifest = RehearsalManifest(
        campaign_id="campaign-1",
        environment_sha256=ENV,
        source_revision=REV,
        min_duration_ms=60_000,
        max_duration_ms=120_000,
        min_samples_per_lane=8,
        edge_coverage_tolerance_ms=5_000,
    )
    session = seal_session_receipt(SessionReceipt(
        campaign_id="campaign-1", session_id="session-1",
        environment_sha256=ENV, source_revision=REV,
        started_ms=1_000_000, ended_ms=1_090_000,
    ), KEY)
    receipts = []
    for lane in manifest.required_lanes:
        receipt = LaneReceipt(
            campaign_id="campaign-1", session_id="session-1",
            environment_sha256=ENV, source_revision=REV,
            lane=lane, status=(status_overrides or {}).get(lane, "pass"),
            sample_count=sample_count, window_start_ms=1_001_000,
            window_end_ms=1_089_000, evidence_sha256=EVIDENCE,
            metrics=metrics_for(lane),
        )
        receipts.append(seal_lane_receipt(receipt, KEY))
    return manifest, session, receipts


class StreamRehearsalGateTests(unittest.TestCase):
    def test_complete_signed_campaign_is_eligible_only_for_owner_review(self):
        manifest, session, receipts = build_campaign()
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "eligible_for_owner_review")
        self.assertTrue(result.eligible_for_owner_review)
        self.assertEqual(len(result.lane_status), 8)
        self.assertEqual(result.duration_ms, 90_000)

    def test_missing_lane_is_inconclusive(self):
        manifest, session, receipts = build_campaign()
        result = evaluate_rehearsal(manifest, session, receipts[:-1], signing_key=KEY)
        self.assertEqual(result.status, "inconclusive")
        self.assertTrue(any(x.startswith("missing_lanes:") for x in result.reasons))

    def test_failed_lane_blocks_campaign(self):
        manifest, session, receipts = build_campaign({"gameplay": "fail"})
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "blocked")
        self.assertIn("lane_failed:gameplay", result.reasons)

    def test_inconclusive_lane_keeps_campaign_inconclusive(self):
        manifest, session, receipts = build_campaign({"speech": "inconclusive"})
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "inconclusive")

    def test_short_session_is_inconclusive(self):
        manifest, session, receipts = build_campaign()
        short = seal_session_receipt(
            replace(session, ended_ms=session.started_ms + 30_000, signature=""), KEY
        )
        result = evaluate_rehearsal(manifest, short, receipts, signing_key=KEY)
        self.assertEqual(result.status, "inconclusive")

    def test_bad_session_signature_blocks_campaign(self):
        manifest, session, receipts = build_campaign()
        bad = replace(session, signature="0" * 64)
        result = evaluate_rehearsal(manifest, bad, receipts, signing_key=KEY)
        self.assertEqual(result.status, "blocked")
        self.assertIn("session_receipt_signature_invalid", result.reasons)

    def test_bad_lane_signature_blocks_campaign(self):
        manifest, session, receipts = build_campaign()
        receipts[0] = replace(receipts[0], signature="0" * 64)
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "blocked")

    def test_wrong_environment_binding_blocks_campaign(self):
        manifest, session, receipts = build_campaign()
        receipts[0] = seal_lane_receipt(
            replace(receipts[0], environment_sha256=hashlib.sha256(b"other").hexdigest(), signature=""), KEY
        )
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "blocked")

    def test_duplicate_lane_blocks_campaign(self):
        manifest, session, receipts = build_campaign()
        duplicated = receipts[:-1] + [receipts[0]]
        result = evaluate_rehearsal(manifest, session, duplicated, signing_key=KEY)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any(x.startswith("duplicate_lane:") for x in result.reasons))

    def test_insufficient_samples_is_inconclusive(self):
        manifest, session, receipts = build_campaign(sample_count=3)
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "inconclusive")

    def test_incomplete_lane_window_is_inconclusive(self):
        manifest, session, receipts = build_campaign()
        receipts[0] = seal_lane_receipt(
            replace(receipts[0], window_end_ms=1_050_000, signature=""), KEY
        )
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=KEY)
        self.assertEqual(result.status, "inconclusive")

    def test_wrong_signing_key_blocks_campaign(self):
        manifest, session, receipts = build_campaign()
        result = evaluate_rehearsal(manifest, session, receipts, signing_key=b"x" * 32)
        self.assertEqual(result.status, "blocked")

    def test_raw_media_metric_names_are_rejected(self):
        with self.assertRaises(ValueError):
            LaneReceipt(
                campaign_id="campaign-1", session_id="session-1",
                environment_sha256=ENV, source_revision=REV,
                lane="speech", status="pass", sample_count=10,
                window_start_ms=1_001_000, window_end_ms=1_089_000,
                evidence_sha256=EVIDENCE, metrics={"transcript": "hello"},
            )

    def test_boolean_is_not_a_numeric_metric(self):
        values = metrics_for("obs")
        values["dropped_frames_pct"] = True
        with self.assertRaises(ValueError):
            LaneReceipt(
                campaign_id="campaign-1", session_id="session-1",
                environment_sha256=ENV, source_revision=REV,
                lane="obs", status="pass", sample_count=10,
                window_start_ms=1_001_000, window_end_ms=1_089_000,
                evidence_sha256=EVIDENCE, metrics=values,
            )

    def test_signing_key_must_be_trusted_length(self):
        manifest, session, receipts = build_campaign()
        with self.assertRaises(ValueError):
            evaluate_rehearsal(manifest, session, receipts, signing_key=b"short")


if __name__ == "__main__":
    unittest.main()
