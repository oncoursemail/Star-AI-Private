"""Adversarial paired-audio evidence: p95 alone cannot certify natural latency."""
from __future__ import annotations

import math
import unittest

from star.stream_quality import (
    StreamAuditTurn, _one_sided_sign_p, compare_stream_profiles,
)


def scenario(baseline: list[int], candidate: list[int]) -> tuple[StreamAuditTurn, ...]:
    assert len(baseline) == len(candidate)
    result: list[StreamAuditTurn] = []
    for index, (before, after) in enumerate(zip(baseline, candidate)):
        case = f"anonymous_case_{index}"
        for route, measured in (("baseline", before), ("candidate", after)):
            result.append(StreamAuditTurn(
                case_id=case, context_sha256="a" * 64, route=route,
                should_reply=True, result="spoken", grounding="supported",
                first_audible_ms=measured, overlap_ms=0, game_stall_ms=0,
                reviewed=True,
            ))
    return tuple(result)


class StreamQualityPairedEvidenceTests(unittest.TestCase):
    def test_broad_400ms_improvement_is_still_review_only(self):
        result = compare_stream_profiles(scenario([1000] * 20, [600] * 20))
        self.assertEqual(result["decision"], "candidate_for_independent_review")
        self.assertTrue(result["paired_directional_gain_supported"])
        self.assertEqual(result["paired_faster_cases"], 20)
        self.assertEqual(result["paired_slower_cases"], 0)
        self.assertEqual(result["paired_neutral_cases"], 0)
        self.assertAlmostEqual(result["paired_one_sided_sign_p"], 2 ** -20)
        self.assertFalse(result["promoted"])

    def test_tiny_outlier_cohort_can_improve_p95_but_not_broad_quality(self):
        # Old p95-only comparison would recommend this despite 90% of
        # opportunities seeing no perceptible latency benefit.
        result = compare_stream_profiles(
            scenario([10000] * 2 + [1000] * 18,
                     [4000] * 2 + [1000] * 18)
        )
        self.assertGreater(result["p95_relative_latency_gain"], 0.5)
        self.assertEqual(result["paired_faster_cases"], 2)
        self.assertEqual(result["paired_neutral_cases"], 18)
        self.assertGreater(result["paired_one_sided_sign_p"], .025)
        self.assertIn("paired_latency_gain_not_broadly_supported", result["reasons"])
        self.assertEqual(result["decision"], "do_not_promote")

    def test_majority_slower_despite_large_aggregate_p95_gain(self):
        result = compare_stream_profiles(
            scenario([10000] * 3 + [1000] * 17,
                     [7000] * 3 + [1050] * 17)
        )
        self.assertGreater(result["p95_relative_latency_gain"], .25)
        self.assertEqual(result["paired_faster_cases"], 3)
        self.assertEqual(result["paired_slower_cases"], 17)
        self.assertEqual(result["decision"], "do_not_promote")

    def test_fifteen_percent_slower_is_blocked_despite_significance(self):
        result = compare_stream_profiles(
            scenario([10000] * 5 + [1000] * 15,
                     [6000] * 5 + [500] * 12 + [1060] * 3)
        )
        self.assertGreater(result["p95_relative_latency_gain"], .35)
        self.assertLess(result["paired_one_sided_sign_p"], .025)
        self.assertEqual(result["paired_faster_cases"], 17)
        self.assertEqual(result["paired_slower_cases"], 3)
        self.assertFalse(result["paired_directional_gain_supported"])
        self.assertIn("paired_latency_gain_not_broadly_supported", result["reasons"])

    def test_millisecond_noise_cannot_be_counted_as_broad_speedup(self):
        result = compare_stream_profiles(scenario([1000] * 20, [992] * 20))
        self.assertEqual(result["paired_neutral_cases"], 20)
        self.assertEqual(result["paired_one_sided_sign_p"], 1.0)
        self.assertIn("paired_latency_gain_not_broadly_supported", result["reasons"])

    def test_order_does_not_change_paired_latency_verdict(self):
        rows = scenario([1000] * 20, [600] * 20)
        normal = compare_stream_profiles(rows)
        reverse = compare_stream_profiles(tuple(reversed(rows)))
        for key in ("decision", "paired_faster_cases", "paired_slower_cases",
                    "paired_one_sided_sign_p", "matched_candidate_p95_ms"):
            self.assertEqual(normal[key], reverse[key])

    def test_sign_test_is_stable_for_large_and_balanced_cohorts(self):
        self.assertAlmostEqual(_one_sided_sign_p(20, 0), 2 ** -20)
        self.assertAlmostEqual(_one_sided_sign_p(0, 20), 1.0)
        self.assertAlmostEqual(_one_sided_sign_p(1, 1), 0.75)
        self.assertGreater(_one_sided_sign_p(1000, 1000), 0.5)
        self.assertLess(_one_sided_sign_p(1000, 1000), 0.52)
        self.assertEqual(_one_sided_sign_p(10000, 0), 0.0)
        self.assertEqual(_one_sided_sign_p(0, 10000), 1.0)
        self.assertTrue(math.isfinite(_one_sided_sign_p(5500, 4500)))


if __name__ == "__main__":
    unittest.main()
