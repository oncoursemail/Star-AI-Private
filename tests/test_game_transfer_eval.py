"""Offline independent game-learning generalization tests; no Studio input."""
import hashlib
import hmac
import unittest
from dataclasses import replace

from star.gameplay_skill_bank import GameTrial
from star.game_transfer_eval import HoldoutCase, SignedHoldoutTrial, evaluate_transfer, roster_digest

KEY = b"V" * 32
NOW = 1793000000


def records(n_games=5, per_game=10, *, baseline="failure", candidate="success"):
    roster = []
    signed = []
    for game in range(n_games):
        for seed in range(per_game):
            case = HoldoutCase(f"game{game}", "v1", "finish", f"seed{seed}")
            roster.append(case)
            for action, outcome in (("control", baseline), ("trained", candidate)):
                trial = GameTrial(
                    f"trial_{game}_{seed}_{action}", case.game_id, case.game_version,
                    case.objective_id, case.situation_id, action,
                    f"run_{game}_{seed}_{action}", "validation", outcome,
                    hashlib.sha256(f"frame:{game}:{seed}:{action}".encode()).hexdigest(), NOW - 5,
                )
                receipt = hmac.new(KEY, trial.canonical_bytes(), hashlib.sha256).hexdigest()
                signed.append(SignedHoldoutTrial(trial, receipt))
    return roster, signed


def check(roster, signed, **kwargs):
    return evaluate_transfer(
        roster, signed, validation_key=KEY, expected_roster_sha256=roster_digest(roster),
        baseline_action_id="control", candidate_action_id="trained", now_unix_s=NOW, **kwargs
    )


class TransferTests(unittest.TestCase):
    def test_strong_independent_gain_produces_advisory_not_permission(self):
        roster, signed = records()
        result = check(roster, signed)
        self.assertEqual(result.verdict, "eligible_for_owner_pilot")
        self.assertEqual(result.preregistered_pairs, 50)
        self.assertEqual(result.distinct_games, 5)
        self.assertEqual(result.paired_success_gain, 1.0)
        self.assertEqual(result.candidate_only_successes, 50)
        self.assertLess(result.mcnemar_one_sided_p, 0.025)
        self.assertFalse(hasattr(result, "authorized_to_play"))

    def test_regression_and_unchanged_not_promoted(self):
        roster, signed = records(baseline="success", candidate="failure")
        self.assertEqual(check(roster, signed).verdict, "regressed")
        roster, signed = records(baseline="success", candidate="success")
        self.assertEqual(check(roster, signed).verdict, "inconclusive")

    def test_missing_data_no_selective_results_released(self):
        roster, signed = records()
        result = check(roster, signed[:-1])
        self.assertEqual(result.verdict, "inconclusive")
        self.assertEqual(result.incomplete_pairs, 1)
        self.assertIsNone(result.candidate_success_rate)
        self.assertIsNone(result.mcnemar_one_sided_p)

    def test_roster_precommit_required_and_order_independent(self):
        roster, signed = records()
        self.assertEqual(roster_digest(roster), roster_digest(list(reversed(roster))))
        with self.assertRaises(PermissionError):
            evaluate_transfer(roster, signed, validation_key=KEY,
                              expected_roster_sha256="0" * 64,
                              baseline_action_id="control", candidate_action_id="trained",
                              now_unix_s=NOW)

    def test_rejects_unsigned_forged_stale_practice(self):
        roster, signed = records()
        forged = replace(signed[0], trial=replace(signed[0].trial, outcome="success"))
        with self.assertRaises(PermissionError):
            check(roster, [forged, *signed[1:]])
        with self.assertRaises(PermissionError):
            check(roster, [replace(signed[0], trial=replace(signed[0].trial, split="practice")), *signed[1:]])
        with self.assertRaises(ValueError):
            check(roster, [replace(signed[0], trial=replace(signed[0].trial, observed_unix_s=NOW-31*86400)), *signed[1:]])
        with self.assertRaises(ValueError):
            check(roster, [replace(signed[0], trial=replace(signed[0].trial, observed_unix_s=NOW+10)), *signed[1:]])

    def test_rejects_duplicate_or_unregistered_cases(self):
        roster, signed = records()
        with self.assertRaises(ValueError):
            check(roster + roster[:1], signed)
        with self.assertRaises(ValueError):
            check(roster[:-1], signed)
        with self.assertRaises(ValueError):
            check(roster, [*signed, signed[0]])
        with self.assertRaises(ValueError):
            reused = replace(signed[0].trial, run_id=signed[1].trial.run_id)
            signed_duplicate = SignedHoldoutTrial(
                reused, hmac.new(KEY, reused.canonical_bytes(), hashlib.sha256).hexdigest()
            )
            check(roster, [signed_duplicate, *signed[1:]])

    def test_cross_day_matching_rejected_even_with_valid_signature(self):
        roster, signed = records()
        altered = replace(signed[0].trial, observed_unix_s=NOW - 90000)
        signed[0] = SignedHoldoutTrial(altered, hmac.new(KEY, altered.canonical_bytes(), hashlib.sha256).hexdigest())
        with self.assertRaises(ValueError):
            check(roster, signed)

    def test_coverage_blocks_one_game_cherry_pick(self):
        roster, signed = records(n_games=1, per_game=50)
        self.assertEqual(check(roster, signed).verdict, "inconclusive")
        roster, signed = records(n_games=5, per_game=4)
        self.assertEqual(check(roster, signed).verdict, "inconclusive")

    def test_validation_bad_params_fail_closed(self):
        roster, signed = records()
        for params in ({"validation_key": b"x"}, {"minimum_pairs": 0},
                       {"minimum_games": True}, {"min_cases_per_game": False}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                call = {
                    "validation_key": KEY, "expected_roster_sha256": roster_digest(roster),
                    "baseline_action_id": "control", "candidate_action_id": "trained",
                    "now_unix_s": NOW
                }
                call.update(params)
                evaluate_transfer(roster, signed, **call)

    def test_true_paired_mc_nemar_not_naive_success_rate(self):
        roster, signed = records()
        # Both baseline and candidate win most cases; only two discordant pairs
        # gives no statistical evidence of improved success.
        adjusted = []
        for item in signed:
            missed = (
                item.trial.action_id == "control" and item.trial.game_id == "game0"
                and item.trial.situation_id in ("seed0", "seed1")
            )
            trial = replace(item.trial, outcome="failure" if missed else "success")
            adjusted.append(SignedHoldoutTrial(
                trial, hmac.new(KEY, trial.canonical_bytes(), hashlib.sha256).hexdigest()
            ))
        report = check(roster, adjusted)
        self.assertEqual(report.verdict, "inconclusive")
        self.assertEqual(report.candidate_only_successes, 2)
        self.assertGreater(report.mcnemar_one_sided_p, 0)


if __name__ == "__main__":
    unittest.main()
