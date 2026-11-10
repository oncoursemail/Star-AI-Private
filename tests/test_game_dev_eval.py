from __future__ import annotations

import hashlib
import unittest

from star.game_dev_eval import (
    GameDevCampaign, GameDevEvaluator, GameDevReceipt, GameDevTask, sign_receipt,
)

KEY = b"test-only-key-that-is-never-used-in-production-0123456789"
H = lambda value: hashlib.sha256(value.encode()).hexdigest()
SUITE = "a" * 40
VALIDATOR = H("validator")
BASE = H("baseline-agent")
CAND = H("candidate-agent")
ENV = H("environment")


def campaign(task_count=8, engine="4.4.1"):
    categories = ["2d_graphics_animation", "3d_graphics_animation", "ui", "gameplay_logic"]
    tasks = []
    for index in range(task_count):
        category = categories[index % 4]
        tasks.append(GameDevTask(
            task_id=f"task-{index}", category=category,
            task_sha256=H(f"task-{index}"),
            first_arm="baseline" if index % 2 == 0 else "candidate",
        ))
    return GameDevCampaign(
        campaign_id="campaign-1", suite_revision=SUITE, engine_version=engine,
        validator_sha256=VALIDATOR, baseline_agent_sha256=BASE,
        candidate_agent_sha256=CAND, feedback_mode="screenshot", tasks=tuple(tasks),
    )


def receipt(c, task, arm, outcome, *, run_suffix="", environment=ENV, run_order=None):
    spec = next(item for item in c.tasks if item.task_id == task)
    agent = BASE if arm == "baseline" else CAND
    expected_order = 1 if arm == spec.first_arm else 2
    return GameDevReceipt(
        campaign_id=c.campaign_id, task_id=task, task_sha256=spec.task_sha256,
        arm=arm, agent_sha256=agent, run_id=f"{task}-{arm}{run_suffix}",
        run_order=expected_order if run_order is None else run_order,
        outcome=outcome, elapsed_ms=100 + (arm == "candidate") * 10,
        environment_sha256=environment,
        artifact_sha256=H(f"artifact-{task}-{arm}"),
        suite_revision=c.suite_revision, engine_version=c.engine_version,
        validator_sha256=c.validator_sha256, feedback_mode=c.feedback_mode,
    )


class GameDevEvalTests(unittest.TestCase):
    def add(self, evaluator, r):
        evaluator.add(r, sign_receipt(r, KEY))

    def fill(self, evaluator, c, outcomes):
        for spec in c.tasks:
            base, cand = outcomes(spec.task_id)
            self.add(evaluator, receipt(c, spec.task_id, "baseline", base))
            self.add(evaluator, receipt(c, spec.task_id, "candidate", cand))

    def test_complete_subset_is_screening_only(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        self.fill(e, c, lambda task: ("failed", "passed") if task != "task-0" else ("passed", "passed"))
        report = e.report()
        self.assertEqual(report["status"], "screening_only")
        self.assertFalse(report["official_roster_verified"])
        self.assertEqual(report["missing_receipts"], 0)
        self.assertEqual(report["paired_candidate_wins"], 7)
        self.assertEqual(report["completed_pairs"], 8)

    def test_missing_receipt_is_incomplete_not_success(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        self.add(e, receipt(c, "task-0", "baseline", "passed"))
        self.assertEqual(e.report()["status"], "incomplete")
        self.assertEqual(e.report()["missing_receipts"], 15)
        self.assertEqual(e.report()["completed_pairs"], 0)

    def test_bad_signature_rejected(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        r = receipt(c, "task-0", "baseline", "passed")
        with self.assertRaises(PermissionError):
            e.add(r, "0" * 64)

    def test_duplicate_task_arm_and_replayed_run_id_rejected(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        r = receipt(c, "task-0", "baseline", "passed")
        self.add(e, r)
        with self.assertRaises(ValueError):
            self.add(e, r)

    def test_wrong_agent_revision_rejected(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        r = receipt(c, "task-0", "baseline", "passed")
        wrong = GameDevReceipt(**{**r.__dict__, "agent_sha256": CAND})
        with self.assertRaises(ValueError):
            self.add(e, wrong)

    def test_unbalanced_pair_order_rejected(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        r = receipt(c, "task-0", "baseline", "passed", run_order=2)
        with self.assertRaises(ValueError):
            self.add(e, r)

    def test_environment_mismatch_contaminates_campaign(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        self.add(e, receipt(c, "task-0", "baseline", "passed"))
        self.add(e, receipt(c, "task-0", "candidate", "passed", environment=H("other-env")))
        self.assertEqual(e.report()["status"], "inconclusive_infrastructure_contamination")

    def test_infrastructure_error_contaminates_campaign(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        for spec in c.tasks:
            self.add(e, receipt(c, spec.task_id, "baseline", "infrastructure_error", run_suffix="-infra"))
            self.add(e, receipt(c, spec.task_id, "candidate", "passed", run_suffix="-ok"))
        self.assertEqual(e.report()["status"], "inconclusive_infrastructure_contamination")

    def test_category_regression_blocks_positive_pooled_result(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)

        def outcomes(task):
            if task in {"task-0", "task-4"}:
                return "passed", "failed"  # both are 2D category
            return "failed", "passed"

        self.fill(e, c, outcomes)
        report = e.report()
        self.assertEqual(report["status"], "keep_baseline_category_regression")
        self.assertIn("2d_graphics_animation", report["category_regressions"])

    def test_report_separates_elapsed_from_quality(self):
        c = campaign(8)
        e = GameDevEvaluator(c, receipt_key=KEY)
        self.fill(e, c, lambda task: ("passed", "passed"))
        report = e.report()
        self.assertEqual(report["status"], "no_measured_improvement")
        self.assertEqual(report["elapsed_ms"]["baseline"]["median"], 100)
        self.assertEqual(report["elapsed_ms"]["candidate"]["median"], 110)

    def test_campaign_rejects_duplicate_task_roster(self):
        c = campaign(8)
        tasks = c.tasks[:-1] + (c.tasks[0],)
        with self.assertRaises(ValueError):
            GameDevCampaign(
                campaign_id=c.campaign_id, suite_revision=c.suite_revision,
                engine_version=c.engine_version, validator_sha256=c.validator_sha256,
                baseline_agent_sha256=c.baseline_agent_sha256,
                candidate_agent_sha256=c.candidate_agent_sha256,
                feedback_mode=c.feedback_mode, tasks=tasks,
            )

    def test_full_shape_is_not_claimed_as_official_roster(self):
        c = campaign(333)
        e = GameDevEvaluator(c, receipt_key=KEY)
        report = e.report()
        self.assertTrue(report["full_333_task_godot_4_4_1_shape"])
        self.assertFalse(report["official_roster_verified"])
        self.assertNotEqual(report["status"], "manual_review_recommended")

    def test_host_verified_manifest_must_match_exact_roster(self):
        base = campaign(333)
        verified = GameDevCampaign(
            campaign_id="campaign-verified", suite_revision=base.suite_revision,
            engine_version=base.engine_version, validator_sha256=base.validator_sha256,
            baseline_agent_sha256=base.baseline_agent_sha256,
            candidate_agent_sha256=base.candidate_agent_sha256,
            feedback_mode=base.feedback_mode, tasks=base.tasks,
            host_verified_official_manifest_sha256=base.task_manifest_sha256,
        )
        self.assertTrue(verified.official_roster_verified)
        tampered = GameDevCampaign(
            campaign_id="campaign-tampered", suite_revision=base.suite_revision,
            engine_version=base.engine_version, validator_sha256=base.validator_sha256,
            baseline_agent_sha256=base.baseline_agent_sha256,
            candidate_agent_sha256=base.candidate_agent_sha256,
            feedback_mode=base.feedback_mode, tasks=base.tasks,
            host_verified_official_manifest_sha256=H("not-the-manifest"),
        )
        self.assertFalse(tampered.official_roster_verified)


if __name__ == "__main__":
    unittest.main()
