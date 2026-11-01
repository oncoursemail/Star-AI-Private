"""Deterministic local demonstrations of a stricter, independent upgrade audit.

All outcomes below are synthetic test fixtures. None are actual STAR model scores.
"""
from dataclasses import replace
import hashlib
import unittest

from star.upgrade_evidence import Audit, Calibration, Comparison, Trial, _sign_tail, audit_comparison, REQUIRED_CHECKS


def digest(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def sample(*, family="coding", cases=32, improve=0, regression=-1, baseline_ms=1000,
           candidate_ms=700, baseline_ttft=250, candidate_ttft=150, modes=("cold", "warm"),
           checks=None, review=True, holdout_cases=24, holdout_base=12,
           holdout_candidate=12, holdout_regression=0, rubric_regression=0, all_fail=False, infra=True):
    t = []
    for i in range(cases):
        baseline_ok = False if all_fail else i >= improve
        candidate_ok = False if all_fail else (True if i < improve else baseline_ok)
        for mode in modes:
            new_ok = False if (i == regression and mode == "warm") else candidate_ok
            t.append(Trial(digest(f"case-{i}"), mode, baseline_ok, new_ok,
                           baseline_ms, candidate_ms, baseline_ttft, candidate_ttft, infra))
    proof = Calibration(
        completed=frozenset(REQUIRED_CHECKS[family] if checks is None else checks),
        required_quality_regressions=rubric_regression,
        reviewer_consensus=review,
        holdout_cases=holdout_cases,
        holdout_baseline_passes=holdout_base,
        holdout_candidate_passes=holdout_candidate,
        holdout_case_regressions=holdout_regression,
    )
    return Comparison(family, digest("frozen-suite"), digest("frozen-verifier"),
                      digest("same-device"), tuple(t), proof)


class UpgradeAuditTests(unittest.TestCase):
    def test_statistic_exact_sign_tails(self):
        for (wins, losses), expected in { (0, 0): 1.0, (1, 0): .5, (1, 1): .75,
                (2, 0): .25, (7, 0): 1/128, (0, 10): 1.0 }.items():
            self.assertAlmostEqual(_sign_tail(wins, losses), expected, places=12)
        self.assertLess(_sign_tail(500, 0), 1e-100)

    def test_quality_advance_is_review_candidate(self):
        result = audit_comparison(sample(improve=12, candidate_ms=1010, candidate_ttft=252))
        self.assertEqual(result.status, "candidate_for_review")
        self.assertTrue(result.can_request_owner_review)
        self.assertEqual(result.distinct_cases, 32)
        self.assertAlmostEqual(result.first_attempt_baseline, 20/32)
        self.assertEqual(result.first_attempt_candidate, 1.0)
        self.assertEqual(result.candidate_p95_ms["cold"], 1010)

    def test_speed_advance_is_review_candidate(self):
        result = audit_comparison(sample())
        self.assertEqual(result.status, "candidate_for_review")
        self.assertTrue(result.can_request_owner_review)
        self.assertGreater(result.candidate_successes_per_minute, result.baseline_successes_per_minute)
        self.assertGreater(result.candidate_tasks_per_minute, result.baseline_tasks_per_minute)
        self.assertLess(result.candidate_p95_ttft_ms["warm"], result.baseline_p95_ttft_ms["warm"])

    def test_infrastructure_failures_cannot_be_counted_as_failures(self):
        result = audit_comparison(sample(infra=False))
        self.assertEqual(result.status, "insufficient")
        self.assertFalse(result.can_request_owner_review)

    def test_candidate_search_adjusts_significance(self):
        # 7 independent improvements -> p=1/128 under one candidate (significant),
        # but not after 2 or more proposals were tried against the same suite.
        data = sample(improve=7, candidate_ms=1000, candidate_ttft=250)
        self.assertTrue(audit_comparison(data, candidate_count=1).can_request_owner_review)
        self.assertFalse(audit_comparison(data, candidate_count=2).can_request_owner_review)

    def test_everything_wrong_but_faster_does_not_count_as_good_ai(self):
        result = audit_comparison(sample(all_fail=True))
        self.assertEqual(result.status, "inconclusive")
        self.assertFalse(result.can_request_owner_review)

    def test_one_real_correctness_regression_blocks(self):
        result = audit_comparison(sample(improve=12, regression=30))
        self.assertEqual(result.status, "regression")
        self.assertFalse(result.can_request_owner_review)
        self.assertTrue(any("correctness regression" in s for s in result.reasons))

    def test_holdout_not_run_blocks_local_green(self):
        checks=REQUIRED_CHECKS["coding"] - {"holdout_confirmation"}
        result=audit_comparison(sample(checks=checks, holdout_cases=0, holdout_base=0, holdout_candidate=0))
        self.assertEqual(result.status, "insufficient")
        self.assertFalse(result.can_request_owner_review)
        self.assertTrue(any("holdout" in x for x in result.reasons))

    def test_missing_cold_cache_blocks(self):
        result = audit_comparison(sample(modes=("warm",)))
        self.assertEqual(result.status, "insufficient")
        self.assertFalse(result.can_request_owner_review)

    def test_repeated_case_in_same_mode_is_not_more_evidence(self):
        data = sample()
        with self.assertRaises(ValueError):
            replace(data, trials=data.trials + (data.trials[0],))

    def test_task_family_must_be_known(self):
        data = sample()
        with self.assertRaises(ValueError):
            replace(data, family="all")

    def test_missing_studio_visual_review_blocks(self):
        needed = REQUIRED_CHECKS["studio_scene"] - {"visual_review"}
        result = audit_comparison(sample(family="studio_scene", checks=needed))
        self.assertEqual(result.status, "insufficient")
        self.assertTrue(any("visual_review" in x for x in result.reasons))

    def test_studio_game_requires_player_input_multiplayer_and_device_layout(self):
        checks = REQUIRED_CHECKS["studio_game"] - {"multiplayer", "player_input", "device_layout"}
        result = audit_comparison(sample(family="studio_game", checks=checks))
        self.assertFalse(result.can_request_owner_review)
        self.assertIn("multiplayer", " ".join(result.reasons))
        self.assertIn("player_input", " ".join(result.reasons))

    def test_visual_rubric_regression_blocks_even_when_faster(self):
        result = audit_comparison(sample(family="studio_scene", rubric_regression=1))
        self.assertEqual(result.status, "regression")
        self.assertFalse(result.can_request_owner_review)

    def test_holdout_regression_blocks_though_dev_faster(self):
        result = audit_comparison(sample(holdout_regression=1, holdout_candidate=12))
        self.assertEqual(result.status, "regression")
        self.assertFalse(result.can_request_owner_review)

    def test_holdout_net_pass_drop_blocks(self):
        result = audit_comparison(sample(holdout_regression=0, holdout_candidate=10))
        self.assertEqual(result.status, "regression")

    def test_not_enough_independent_cases_cannot_be_faked_with_cache_states(self):
        result = audit_comparison(sample(cases=12, improve=12))
        self.assertEqual(result.trials, 24)
        self.assertEqual(result.distinct_cases, 12)
        self.assertFalse(result.can_request_owner_review)

    def test_ttft_regression_cannot_hide_behind_fast_e2e(self):
        result = audit_comparison(sample(candidate_ttft=400))
        self.assertEqual(result.status, "inconclusive")
        self.assertFalse(result.can_request_owner_review)

    def test_slow_candidate_cannot_be_disguised_by_success_improvement(self):
        result = audit_comparison(sample(improve=12, candidate_ms=1200))
        self.assertEqual(result.status, "inconclusive")
        self.assertFalse(result.can_request_owner_review)

    def test_missing_reviewer_agreement_blocks(self):
        result = audit_comparison(sample(review=False))
        self.assertEqual(result.status, "insufficient")
        self.assertFalse(result.can_request_owner_review)

    def test_empty_benchmark_has_no_score(self):
        result = audit_comparison(sample(cases=0))
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.first_attempt_candidate, 0.0)
        self.assertEqual(result.candidate_successes_per_minute, 0.0)

    def test_quality_promotion_cannot_reuse_warm_and_cold_as_independent_wins(self):
        result = audit_comparison(sample(improve=6, candidate_ms=1020))
        self.assertFalse(result.can_request_owner_review)

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):
            Trial("bad-digest", "warm", True, True, 20, 20, 10, 10, True)
        with self.assertRaises(ValueError):
            Trial(digest("a"), "hot", True, True, 20, 20, 10, 10, True)
        with self.assertRaises(ValueError):
            Trial(digest("a"), "warm", 1, True, 20, 20, 10, 10, True)
        with self.assertRaises(ValueError):
            Trial(digest("a"), "warm", True, True, 20, 20, 25, 10, True)
        with self.assertRaises(ValueError):
            Calibration(frozenset(), -1, True)
        with self.assertRaises(ValueError):
            Calibration(frozenset(), 0, True, holdout_cases=10, holdout_baseline_passes=11)
        with self.assertRaises(ValueError):
            audit_comparison(sample(), minimum_cases=1)
        with self.assertRaises(ValueError):
            audit_comparison(sample(), alpha=.5)
        with self.assertRaises(ValueError):
            audit_comparison(sample(), candidate_count=0)


if __name__ == "__main__":
    unittest.main()
