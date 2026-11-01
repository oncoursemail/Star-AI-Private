"""Independent paired-stream quality gate; synthetic records only."""
import math
import unittest

from star.stream_quality import StreamAuditTurn, compare_stream_profiles

SHA = "c" * 64


def turn(case="case0", *, route="baseline", needed=True, outcome="spoken",
         grade="supported", first=1000, overlap=0, stall=0,
         digest=SHA, reviewed=True):
    return StreamAuditTurn(case, digest, route, needed, outcome, grade,
                           first if outcome == "spoken" else None, overlap, stall, reviewed)


def pairs(n=20, *, before=1000, after=600):
    rows = []
    for idx in range(n):
        case = f"trial_{idx}"
        rows.append(turn(case, first=before))
        rows.append(turn(case, route="candidate", first=after))
    return tuple(rows)


class StreamQualityTests(unittest.TestCase):
    def test_faster_grounded_preserved_output_is_review_candidate(self):
        report = compare_stream_profiles(pairs())
        self.assertEqual(report["decision"], "candidate_for_independent_review")
        self.assertFalse(report["promoted"])
        self.assertTrue(report["owner_review_required"])
        self.assertEqual(report["baseline"]["useful_replies"], 20)
        self.assertEqual(report["candidate"]["useful_replies"], 20)
        self.assertEqual(report["p95_relative_latency_gain"], .4)

    def test_speed_only_from_silence_cannot_win(self):
        source = list(pairs())
        for idx, record in enumerate(source):
            if record.route == "candidate" and int(record.case_id.split("_")[1]) >= 9:
                source[idx] = turn(record.case_id, route="candidate", outcome="silent",
                                   grade="not_applicable")
        report = compare_stream_profiles(tuple(source))
        self.assertEqual(report["decision"], "do_not_promote")
        self.assertIn("fewer_grounded_replies", report["reasons"])
        self.assertIn("insufficient_audible_samples", report["reasons"])

    def test_speed_cannot_hide_low_absolute_answer_quality(self):
        source = []
        for idx in range(20):
            case = f"trial_{idx}"
            # 16 genuinely useful responses, four failed in both profiles.
            supported = idx < 16
            source.append(turn(case, outcome="spoken" if supported else "failed",
                               grade="supported" if supported else "not_applicable"))
            source.append(turn(case, route="candidate", first=200,
                               outcome="spoken" if supported else "failed",
                               grade="supported" if supported else "not_applicable"))
        report = compare_stream_profiles(tuple(source))
        self.assertEqual(report["baseline"]["useful_reply_ratio"], .8)
        self.assertEqual(report["candidate"]["useful_reply_ratio"], .8)
        self.assertEqual(report["decision"], "do_not_promote")
        self.assertIn("useful_reply_coverage_below_target", report["reasons"])

    def test_added_failed_opportunities_are_explicit_regression(self):
        source = list(pairs())
        for idx, record in enumerate(source):
            if record.route == "candidate" and record.case_id == "trial_1":
                source[idx] = turn(record.case_id, route="candidate",
                                   outcome="failed", grade="not_applicable")
        report = compare_stream_profiles(tuple(source), min_useful_reply_ratio=.8)
        self.assertIn("increased_failed_reply_opportunities", report["reasons"])
        self.assertEqual(report["candidate"]["failed_reply_opportunities"], 1)

    def test_intentional_cancellation_is_reported_not_called_slow(self):
        source = list(pairs())
        for idx, record in enumerate(source):
            if record.route == "candidate" and record.case_id == "trial_1":
                source[idx] = turn(record.case_id, route="candidate",
                                   outcome="cancelled", grade="not_applicable")
        report = compare_stream_profiles(tuple(source), min_useful_reply_ratio=.8)
        self.assertEqual(report["candidate"]["cancelled_reply_opportunities"], 1)
        self.assertIn("increased_cancelled_reply_opportunities", report["reasons"])

    def test_ungrounded_claims_block_even_if_fast(self):
        source = list(pairs())
        for idx, record in enumerate(source):
            if record.route == "candidate" and record.case_id == "trial_7":
                source[idx] = turn(record.case_id, route="candidate", grade="unsupported", first=20)
        report = compare_stream_profiles(tuple(source))
        self.assertIn("increased_unsupported_speech", report["reasons"])

    def test_talking_over_user_is_regression(self):
        source = list(pairs())
        for idx, record in enumerate(source):
            if record.route == "candidate" and record.case_id == "trial_7":
                source[idx] = turn(record.case_id, route="candidate", first=20, overlap=200)
        report = compare_stream_profiles(tuple(source))
        self.assertIn("increased_speech_overlaps", report["reasons"])
        self.assertIn("increased_total_overlap_ms", report["reasons"])

    def test_game_stall_regression_blocks(self):
        source = list(pairs())
        for idx, record in enumerate(source):
            if record.route == "candidate" and record.case_id == "trial_7":
                source[idx] = turn(record.case_id, route="candidate", first=20, stall=55)
        report = compare_stream_profiles(tuple(source))
        self.assertIn("increased_game_stalls_over_50ms", report["reasons"])

    def test_no_latency_improvement_no_promotion(self):
        result = compare_stream_profiles(pairs(after=990))
        self.assertIn("no_measured_p95_latency_improvement", result["reasons"])

    def test_exact_same_cases_must_be_paired(self):
        one = turn("one", route="baseline")
        two = turn("two", route="candidate")
        result = compare_stream_profiles((one, two), min_cases=2, min_spoken=1)
        self.assertEqual(result["decision"], "insufficient_or_unpaired_evidence")

    def test_context_hash_mismatch_rejected(self):
        source = list(pairs())
        source[1] = turn("trial_0", route="candidate", digest="d"*64)
        report = compare_stream_profiles(tuple(source))
        self.assertEqual(report["decision"], "insufficient_or_unpaired_evidence")

    def test_review_missing_rejected(self):
        source = list(pairs())
        source[1] = turn("trial_0", route="candidate", reviewed=False)
        report = compare_stream_profiles(tuple(source))
        self.assertEqual(report["decision"], "insufficient_or_unpaired_evidence")

    def test_grounding_annotation_missing_rejected(self):
        source = list(pairs())
        source[1] = turn("trial_0", route="candidate", grade="unreviewed")
        report = compare_stream_profiles(tuple(source))
        self.assertEqual(report["decision"], "insufficient_or_unpaired_evidence")

    def test_duplicate_ids_rejected(self):
        source = pairs()
        with self.assertRaises(ValueError):
            compare_stream_profiles(source + (source[0],))

    def test_mismatched_opportunity_labels_rejected(self):
        source = list(pairs())
        source[1] = turn("trial_0", route="candidate", needed=False)
        report = compare_stream_profiles(tuple(source))
        self.assertEqual(report["decision"], "insufficient_or_unpaired_evidence")

    def test_unexpected_speech_regression(self):
        source = []
        for idx in range(20):
            case = f"trial_{idx}"
            needed = idx < 15
            source.append(turn(case, needed=needed, outcome="spoken" if needed else "silent",
                               grade="supported" if needed else "not_applicable"))
            source.append(turn(case, route="candidate", needed=needed, first=600,
                               outcome="spoken", grade="supported"))
        result = compare_stream_profiles(tuple(source))
        self.assertIn("increased_unexpected_speech", result["reasons"])

    def test_very_small_samples_do_not_count(self):
        report = compare_stream_profiles(pairs(5))
        self.assertEqual(report["decision"], "insufficient_or_unpaired_evidence")

    def test_invalid_row_inputs(self):
        cases = (
            {"case":""}, {"digest":"a"}, {"outcome":"bogus"},
            {"grade":"excellent"}, {"first":math.nan},
            {"overlap":-1}, {"stall":math.inf}, {"needed":1},
            {"reviewed":"yes"}, {"outcome":"silent","grade":"supported"},
            {"outcome":"silent","overlap":1},
            {"outcome":"spoken","grade":"not_applicable"},
        )
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                turn(**data)

    def test_invalid_config_types(self):
        for kw in ({"min_cases":1}, {"min_spoken":0},
                   {"min_relative_latency_gain":math.inf},
                   {"min_relative_latency_gain":True},
                   {"min_useful_reply_ratio":math.nan},
                   {"min_useful_reply_ratio":math.inf},
                   {"min_useful_reply_ratio":True},
                   {"min_useful_reply_ratio":.49},
                   {"min_useful_reply_ratio":1.1}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                compare_stream_profiles(pairs(), **kw)
        with self.assertRaises(TypeError):
            compare_stream_profiles(list(pairs()))


if __name__ == "__main__":
    unittest.main()
