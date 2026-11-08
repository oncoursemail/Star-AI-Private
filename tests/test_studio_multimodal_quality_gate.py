"""Synthetic, fully offline review receipts. NOT evidence of real visual quality."""
from dataclasses import replace
import unittest

from star.studio_multimodal_quality_gate import (
    QualityCase, QualityObservation, QualityPolicy, QualityStudy,
    SignedQualityObservation, evaluate_quality, seal_digest, sign_observation,
)

KEY = b"independent-reviewer-host-test-key-0123456789"
OTHER = b"untrusted-different-host-key--0123456789"
NOW = 1_800_000_000


def fixture():
    cases = tuple(
        QualityCase(f"case{i}", f"game{i % 2}", "v1", f"{i + 1:064x}")
        for i in range(8)
    )
    study = QualityStudy("graphicsA", cases, NOW - 200)
    signed = []
    for case in cases:
        for variant in ("baseline", "candidate"):
            score = (2, 2, 2, 2, 2) if variant == "baseline" else (3, 3, 3, 3, 3)
            observed = QualityObservation(
                study_id=study.study_id, case_id=case.case_id,
                variant=variant, game_id=case.game_id,
                game_version=case.game_version,
                scenario_sha256=case.scenario_sha256,
                screenshot_sha256=("a" if variant == "baseline" else "b") * 64,
                scores=score, scene_valid=True, playable=True,
                observed_unix_s=NOW - 100,
            )
            signed.append(sign_observation(observed, reviewer_key=KEY))
    return study, signed


def run(study, receipts, **kwargs):
    return evaluate_quality(study, tuple(receipts), reviewer_key=KEY,
                            externally_sealed_sha256=seal_digest(study),
                            now_unix_s=NOW, **kwargs)


def alter(receipts, i, **kwargs):
    receipts = list(receipts)
    record = replace(receipts[i].observation, **kwargs)
    receipts[i] = sign_observation(record, reviewer_key=KEY)
    return receipts


class QualityGateTests(unittest.TestCase):
    def test_pass_eligible_for_manual_review_only(self):
        study, receipts = fixture()
        result = run(study, receipts)
        self.assertEqual(result.verdict, "eligible_for_review")
        self.assertEqual(result.complete_pairs, 8)
        self.assertEqual(result.expected_pairs, 8)
        self.assertEqual(result.distinct_games, 2)
        self.assertEqual(result.mean_score_gain, 1)
        self.assertEqual(result.positive_case_fraction, 1)
        self.assertFalse(result.authorized_to_edit)
        self.assertFalse(result.authorized_to_publish)

    def test_missing_pair_is_inconclusive(self):
        study, receipts = fixture()
        report = run(study, receipts[:-1])
        self.assertEqual(report.verdict, "inconclusive")
        self.assertEqual(report.complete_pairs, 7)
        self.assertIn("incomplete_pairs", report.concerns)

    def test_duplicate_is_rejected(self):
        study, receipts = fixture()
        report = run(study, receipts + [receipts[0]])
        self.assertEqual(report.verdict, "inconclusive")
        self.assertIn("duplicate_observation", report.concerns)

    def test_tampered_hmac_is_rejected(self):
        study, receipts = fixture()
        receipts[0] = SignedQualityObservation(
            replace(receipts[0].observation, scores=(5, 5, 5, 5, 5)),
            receipts[0].mac_sha256,
        )
        self.assertEqual(run(study, receipts).verdict, "inconclusive")

    def test_wrong_reviewer_key(self):
        study, receipts = fixture()
        receipts[0] = sign_observation(receipts[0].observation, reviewer_key=OTHER)
        self.assertEqual(run(study, receipts).verdict, "inconclusive")

    def test_wrong_case_identity(self):
        study, receipts = fixture()
        self.assertEqual(run(study, alter(receipts, 0, case_id="elsewhere")).verdict,
                         "inconclusive")

    def test_wrong_study_identity(self):
        study, receipts = fixture()
        self.assertEqual(run(study, alter(receipts, 0, study_id="other")).verdict,
                         "inconclusive")

    def test_wrong_scenario_rejected(self):
        study, receipts = fixture()
        self.assertEqual(
            run(study, alter(receipts, 0, scenario_sha256="c" * 64)).verdict,
            "inconclusive",
        )

    def test_wrong_seal_does_not_promote(self):
        study, receipts = fixture()
        report = evaluate_quality(
            study, receipts, reviewer_key=KEY,
            externally_sealed_sha256="0" * 64, now_unix_s=NOW,
        )
        self.assertEqual(report.verdict, "inconclusive")
        self.assertIn("study_seal_missing_or_stale", report.concerns)

    def test_stale_manifest(self):
        study, receipts = fixture()
        study = replace(study, registered_unix_s=NOW - 15 * 86400)
        self.assertEqual(run(study, receipts).verdict, "inconclusive")

    def test_future_review_rejected(self):
        study, receipts = fixture()
        self.assertEqual(
            run(study, alter(receipts, 0, observed_unix_s=NOW + 1)).verdict,
            "inconclusive",
        )

    def test_review_before_registration_rejected(self):
        study, receipts = fixture()
        self.assertEqual(
            run(study, alter(receipts, 0, observed_unix_s=study.registered_unix_s - 1)).verdict,
            "inconclusive",
        )

    def test_unverified_playthrough_regresses(self):
        study, receipts = fixture()
        report = run(study, alter(receipts, 1, playable=False))
        self.assertEqual(report.verdict, "regressed")
        self.assertIn("unverified_engine_or_playthrough", report.concerns)

    def test_unverified_engine_regresses(self):
        study, receipts = fixture()
        report = run(study, alter(receipts, 1, scene_valid=False))
        self.assertEqual(report.verdict, "regressed")

    def test_repeated_image_conflicting_grade(self):
        study, receipts = fixture()
        report = run(study, alter(receipts, 1, screenshot_sha256="a" * 64))
        self.assertEqual(report.verdict, "regressed")
        self.assertIn("identical_image_conflicting_scores", report.concerns)

    def test_severe_single_case_visual_regression(self):
        study, receipts = fixture()
        report = run(study, alter(receipts, 1, scores=(0, 3, 3, 3, 3)))
        self.assertEqual(report.verdict, "regressed")
        self.assertIn("severe_visual_regression", report.concerns)

    def test_mean_dimension_regression(self):
        study, receipts = fixture()
        for index in range(1, len(receipts), 2):
            receipts = alter(receipts, index, scores=(1, 4, 4, 4, 4))
        report = run(study, receipts, policy=QualityPolicy(max_per_dimension_loss=2))
        self.assertEqual(report.verdict, "regressed")
        self.assertIn("mean_visual_dimension_regression", report.concerns)

    def test_no_improvement_fails_closed(self):
        study, receipts = fixture()
        for index in range(1, len(receipts), 2):
            receipts = alter(receipts, index, scores=(2, 2, 2, 2, 2))
        report = run(study, receipts)
        self.assertEqual(report.verdict, "regressed")
        self.assertIn("insufficient_cross_game_quality_gain", report.concerns)

    def test_game_specific_regression_cannot_hide_in_macro_average(self):
        study, receipts = fixture()
        for index in range(1, len(receipts), 2):
            if (index // 2) % 2:
                receipts = alter(receipts, index, scores=(2, 2, 2, 2, 2))
        result = run(study, receipts)
        self.assertEqual(result.verdict, "regressed")
        self.assertIn("insufficient_cross_game_quality_gain", result.concerns)

    def test_bool_score_rejected(self):
        study, receipts = fixture()
        with self.assertRaises(ValueError):
            replace(receipts[0].observation, scores=(True, 2, 2, 2, 2))

    def test_duplicate_manifest_rejected(self):
        study, _ = fixture()
        with self.assertRaises(ValueError):
            replace(study, cases=study.cases[:-1] + (study.cases[0],))

    def test_single_game_manifest_rejected(self):
        study, _ = fixture()
        with self.assertRaises(ValueError):
            replace(study, cases=tuple(replace(case, game_id="game0")
                                       for case in study.cases))

    def test_key_too_short_rejected(self):
        study, receipts = fixture()
        with self.assertRaises(ValueError):
            evaluate_quality(study, receipts, reviewer_key=b"x",
                             externally_sealed_sha256=seal_digest(study),
                             now_unix_s=NOW)

    def test_bad_policy_rejected(self):
        with self.assertRaises(ValueError):
            QualityPolicy(min_mean_gain=float("nan"))
        with self.assertRaises(ValueError):
            QualityPolicy(min_positive_case_fraction=2)
        with self.assertRaises(ValueError):
            QualityPolicy(max_per_dimension_loss=True)


if __name__ == "__main__":
    unittest.main()
