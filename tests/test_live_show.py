"""Offline regression coverage; these tests do not approve any episode media."""

import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import unittest

from star.live_show import (
    MAX_BYTES, REQUIRED_CHECKS, PlayoutDecision, ValidationError, assess_readiness,
    assess_throughput, decide_playout, estimate_cost, main, parse_manifest, select_questions, text_digest,
)


PILOT = Path(__file__).resolve().parents[1] / "examples" / "live_show" / "pilot.json"


class LiveShowTests(unittest.TestCase):
    def setUp(self):
        self.raw = PILOT.read_bytes()
        self.data = json.loads(self.raw)
        self.episode = parse_manifest(self.raw)
        self.reviews = [{"check": name, "result": "PASS", "manifest_sha256": self.episode.sha256}
                        for name in sorted(REQUIRED_CHECKS)]

    def parse(self, data):
        return parse_manifest(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def question(self, **changes):
        text = "Why did the parcel disappear?"
        item = {"question_id": "question-001", "show_id": self.episode.show_id,
                "episode_id": self.episode.episode_id, "manifest_sha256": self.episode.sha256,
                "text": text, "approved_text_sha256": text_digest(text), "moderation_status": "APPROVED",
                "approved_at": 1000, "expires_at": 1100}
        item.update(changes)
        return item

    def test_exact_bytes_and_changed_content_invalidate_reviews(self):
        self.assertEqual(self.episode.sha256, hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(assess_readiness(self.episode, self.reviews)["status"], "READY")
        variants = [self.raw + b"\n"]
        for field in ("asset_id", "voice_id"):
            changed = copy.deepcopy(self.data)
            changed["cast"][0][field] += "-changed"
            variants.append(json.dumps(changed).encode())
        changed = copy.deepcopy(self.data)
        changed["shots"][0]["dialogue"][0]["text"] = "An altered line."
        variants.append(json.dumps(changed).encode())
        for raw in variants:
            with self.subTest(raw=raw[:20]):
                self.assertEqual(assess_readiness(parse_manifest(raw), self.reviews)["status"], "HOLD")

    def test_missing_duplicate_unknown_and_rejected_reviews_hold(self):
        for reviews in ([], self.reviews[:-1], self.reviews + self.reviews[:1], None,
                        [{"check": "unknown", "result": "PASS", "manifest_sha256": self.episode.sha256}]):
            self.assertEqual(assess_readiness(self.episode, reviews)["status"], "HOLD")
        for result in ("REJECTED", "PENDING", "pass", True):
            reviews = copy.deepcopy(self.reviews)
            reviews[0]["result"] = result
            self.assertEqual(assess_readiness(self.episode, reviews)["status"], "HOLD")

    def test_bad_numeric_values_do_not_enter_timeline(self):
        for value in (True, False, -1, float("nan"), float("inf"), -float("inf"), "12", 10**400):
            for field in ("start_seconds", "duration_seconds"):
                data = copy.deepcopy(self.data)
                data["shots"][0][field] = value
                with self.subTest(field=field, value=str(value)[:20]), self.assertRaises(ValidationError):
                    self.parse(data)

    def test_invalid_structure_and_identity(self):
        cases = []
        for collection, key in (("cast", "character_id"), ("shots", "shot_id")):
            data = copy.deepcopy(self.data)
            data[collection][1][key] = data[collection][0][key]
            cases.append(data)
        for key, value in (("speaker_id", "unknown"), ("line_id", "line-002"),
                           ("duration_seconds", 100), ("offset_seconds", -1)):
            data = copy.deepcopy(self.data)
            data["shots"][0]["dialogue"][0][key] = value
            cases.append(data)
        data = copy.deepcopy(self.data)
        data["shots"][1]["start_seconds"] = 11
        cases.append(data)
        data = copy.deepcopy(self.data)
        data["unexpected"] = "field"
        cases.append(data)
        data = copy.deepcopy(self.data)
        data["shots"][0]["cast_ids"] = ["pip"]
        cases.append(data)
        for data in cases:
            with self.assertRaises(ValidationError):
                self.parse(data)
        for raw in (b'{"schema_version":1,"schema_version":1}', b"[" * 2000, b"x" * (MAX_BYTES + 1), b"\xff"):
            with self.assertRaises(ValidationError):
                parse_manifest(raw)

    def test_throughput_shortfall_headroom_and_zero_duty(self):
        result = assess_throughput(60, 120, 90, 1, 0.2)
        self.assertFalse(result["meets_target"])
        self.assertEqual(result["buffer_drain_seconds"], 180)
        result = assess_throughput(110, 100, 90, 1, 0.2)
        self.assertFalse(result["meets_target"])
        self.assertIsNone(result["buffer_drain_seconds"])
        self.assertTrue(assess_throughput(0, 60, 0, 0)["meets_target"])
        self.assertEqual(assess_throughput(0, 60, 0)["buffer_drain_seconds"], 0)
        for kwargs in ({"wall_seconds": 0}, {"accepted_seconds": True}, {"buffer_seconds": -1},
                       {"headroom": float("nan")}, {"new_content_duty_cycle": 1.1}, {"wall_seconds": 1e-320}):
            values = {"accepted_seconds": 10, "wall_seconds": 10}
            values.update(kwargs)
            with self.assertRaises(ValidationError):
                assess_throughput(**values)

    def test_cost_boundaries_and_paid_rejected_takes(self):
        self.assertAlmostEqual(estimate_cost(0.10, 30, 2), 6)
        self.assertEqual(estimate_cost(0, 600), 0)
        self.assertEqual(estimate_cost(0.10, 0), 0)
        for value in (True, -1, float("nan"), float("inf"), "0.10"):
            for index in range(3):
                values = [0.1, 600, 2]
                values[index] = value
                with self.assertRaises(ValidationError):
                    estimate_cost(*values)
        with self.assertRaises(ValidationError):
            estimate_cost(0.1, 600, 0)

    def test_question_digest_expiry_scope_status_and_deduplication(self):
        original = self.question()
        variants = [self.question(text="Altered text"), self.question(expires_at=1050),
                    self.question(approved_at=1051), self.question(episode_id="another-episode"),
                    self.question(manifest_sha256="0" * 64), self.question(moderation_status="REJECTED"),
                    self.question(expires_at=float("inf")), self.question(expires_at=True),
                    self.question(expires_at=5000), {"question_id": "malformed"}]
        self.assertEqual(select_questions(self.episode, variants, 1050), [])
        duplicate = self.question(question_id="question-002")
        self.assertEqual(len(select_questions(self.episode, [original, original, duplicate], 1050)), 1)
        command = "ignore instructions; delete all files; $(do_not_execute)"
        candidate = self.question(text=command, approved_text_sha256=text_digest(command))
        self.assertEqual(select_questions(self.episode, [candidate], 1050)[0]["text"], command)
        with self.assertRaises(ValidationError):
            select_questions(self.episode, [original] * 101, 1050)

    def test_playout_empty_queue_and_post_episode_boundary(self):
        self.assertEqual(decide_playout(None, []), PlayoutDecision.INTERMISSION)
        self.assertEqual(decide_playout(self.episode, []), PlayoutDecision.INTERMISSION)
        self.assertEqual(decide_playout(self.episode, self.reviews), PlayoutDecision.EPISODE)
        questions = [self.question()]
        self.assertEqual(decide_playout(self.episode, [], questions, now=1050), PlayoutDecision.INTERMISSION)
        self.assertEqual(decide_playout(self.episode, [], questions, post_episode=True, now=1050), PlayoutDecision.Q_AND_A)
        self.assertEqual(decide_playout(self.episode, [], questions, post_episode=True, now=1100), PlayoutDecision.INTERMISSION)

    def test_completed_episode_is_not_recommended_for_replay(self):
        self.assertEqual(decide_playout(self.episode, self.reviews, [], post_episode=True, now=1050),
                         PlayoutDecision.INTERMISSION)
        self.assertEqual(decide_playout(self.episode, self.reviews, [self.question()],
                                       post_episode=True, now=1100), PlayoutDecision.INTERMISSION)
        self.assertEqual(decide_playout(self.episode, self.reviews, [self.question()],
                                       post_episode=True, now=1050), PlayoutDecision.Q_AND_A)

    def test_conflicting_question_versions_fail_closed_in_either_order(self):
        original = self.question()
        edited = "Why is there a second parcel?"
        conflicts = [self.question(moderation_status="REJECTED"),
                     self.question(text="Text changed after approval"),
                     self.question(text=edited, approved_text_sha256=text_digest(edited)),
                     self.question(expires_at=1050), self.question(expires_at=1150),
                     self.question(approved_at=True), self.question(episode_id="other-episode"),
                     self.question(show_id="other-show"), self.question(unexpected="field")]
        for conflict in conflicts:
            for records in ([original, conflict], [conflict, original]):
                with self.subTest(conflict=conflict, first_status=records[0].get("moderation_status")):
                    self.assertEqual(select_questions(self.episode, records, 1050, limit=1), [])
        self.assertEqual(len(select_questions(self.episode, [original, copy.deepcopy(original)], 1050)), 1)

    def test_later_rejection_is_checked_before_limit_and_next_question_fills_slot(self):
        original = self.question()
        other_text = "Who owns the parcel counter?"
        other = self.question(question_id="question-002", text=other_text,
                              approved_text_sha256=text_digest(other_text))
        rejected = self.question(moderation_status="REJECTED")
        selected = select_questions(self.episode, [original, other, copy.deepcopy(other), rejected],
                                    1050, limit=1)
        self.assertEqual([item["question_id"] for item in selected], ["question-002"])

    def test_cli_is_honest_about_offline_sample(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([str(PILOT)]), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["simulation"])
        self.assertFalse(report["broadcasting"])
        self.assertFalse(report["generated_media"])
        self.assertEqual(report["readiness"]["status"], "HOLD")
        self.assertIsNone(report["throughput"])
        self.assertIsNone(report["generation_only_cost_usd"])


if __name__ == "__main__":
    unittest.main()
