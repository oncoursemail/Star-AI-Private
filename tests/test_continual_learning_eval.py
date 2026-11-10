from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from star.continual_learning_eval import (
    CampaignManifest, TaskSpec, TaskReceipt, evaluate_continual_learning, sign_receipt,
)

KEY = b"star-test-host-key-32-bytes-minimum!!"
NOW = 1_800_000_000_000


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def build_manifest(split="holdout", streams=8):
    tasks = []
    domains = ("coding", "gameplay", "research", "creator")
    for index in range(streams):
        sid = f"stream-{index:02}"
        domain = domains[index % len(domains)]
        first = "memory_off" if index % 2 == 0 else "memory_on"
        acquired = f"acq-{index:02}"
        tasks.extend([
            TaskSpec(acquired, sid, 0, domain, f"skill-{index:02}", "acquire", sha(f"acq-{index}"), first),
            TaskSpec(f"dep-{index:02}", sid, 1, domain, f"skill-{index:02}", "dependent_probe",
                     sha(f"dep-{index}"), first, (acquired,)),
            TaskSpec(f"ind-{index:02}", sid, 2, domain, f"unrelated-{index:02}", "independent_probe",
                     sha(f"ind-{index}"), first),
            TaskSpec(f"ret-{index:02}", sid, 3, domain, f"skill-{index:02}", "retention_probe",
                     sha(f"acq-{index}"), first, (), acquired),
        ])
    return CampaignManifest(
        campaign_id="campaign-01", split=split, backbone_sha256=sha("backbone"),
        runner_sha256=sha("runner"), grader_sha256=sha("grader"), prompt_template_sha256=sha("prompt"),
        tool_policy_sha256=sha("tools"), memory_off_policy_sha256=sha("memory-off"),
        memory_on_policy_sha256=sha("memory-on"), context_budget_tokens=8192,
        output_budget_tokens=1024, memory_budget_tokens=4096, tasks=tuple(tasks),
    )


def receipts_for(manifest, *, dependent_gain=True, independent_harm=False, retention_harm=False):
    receipts = []
    for task_index, task in enumerate(manifest.tasks):
        for arm in ("memory_off", "memory_on"):
            status = "pass"
            if task.role == "dependent_probe" and arm == "memory_off" and dependent_gain:
                status = "fail"
            if task.role == "independent_probe" and arm == "memory_on" and independent_harm:
                status = "fail"
            if task.role == "retention_probe" and arm == "memory_on" and retention_harm:
                status = "fail"
            arm_order = 0 if arm == task.first_arm else 1
            unsigned = TaskReceipt(
                manifest_sha256=manifest.sha256, task_id=task.task_id, stream_id=task.stream_id,
                arm=arm, arm_order=arm_order, run_id=f"run-{task.task_id}-{arm}",
                evidence_sha256=sha(f"evidence-{task.task_id}-{arm}"), status=status,
                observed_unix_ms=NOW - (len(manifest.tasks) - task_index) * 2000 + (0 if arm_order == 0 else 500),
                elapsed_ms=1000 + (100 if arm == "memory_on" else 0),
                input_tokens=500, output_tokens=100,
                memory_tokens_read=(50 if arm == "memory_on" else 0),
                memory_tokens_written=(20 if arm == "memory_on" else 0),
            )
            receipts.append(replace(unsigned, signature=sign_receipt(unsigned, KEY)))
    return tuple(receipts)


class ContinualLearningEvalTests(unittest.TestCase):
    def evaluate(self, manifest, receipts, **kwargs):
        return evaluate_continual_learning(
            manifest, receipts, validation_key=KEY, expected_manifest_sha256=manifest.sha256,
            now_unix_ms=NOW, **kwargs,
        )

    def test_holdout_memory_gain_recommends_manual_review_not_promotion(self):
        manifest = build_manifest()
        report = self.evaluate(manifest, receipts_for(manifest))
        self.assertEqual(report.verdict, "manual_review_recommended")
        self.assertEqual(report.completed_pairs, len(manifest.tasks))
        self.assertEqual(report.dependent_gain_pp, 100.0)
        self.assertEqual(report.improved_streams, 8)
        self.assertAlmostEqual(report.dependent_sign_test_p, 1 / 256)

    def test_development_never_recommends_holdout_pilot(self):
        manifest = build_manifest(split="development")
        report = self.evaluate(manifest, receipts_for(manifest))
        self.assertEqual(report.verdict, "development_signal_only")
        self.assertEqual(report.split, "development")

    def test_independent_task_harm_blocks_positive_transfer(self):
        manifest = build_manifest()
        report = self.evaluate(manifest, receipts_for(manifest, independent_harm=True))
        self.assertEqual(report.verdict, "memory_regressed")
        self.assertEqual(report.independent_gain_pp, -100.0)

    def test_retention_harm_blocks_positive_transfer(self):
        manifest = build_manifest()
        report = self.evaluate(manifest, receipts_for(manifest, retention_harm=True))
        self.assertEqual(report.verdict, "memory_regressed")
        self.assertEqual(report.retention_gain_pp, -100.0)

    def test_missing_arm_is_inconclusive(self):
        manifest = build_manifest()
        receipts = receipts_for(manifest)[:-1]
        report = self.evaluate(manifest, receipts)
        self.assertEqual(report.verdict, "inconclusive")
        self.assertEqual(report.incomplete_pairs, 1)

    def test_infrastructure_error_contaminates_campaign(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        receipts[0] = replace(receipts[0], status="infra_error", signature="")
        receipts[0] = replace(receipts[0], signature=sign_receipt(receipts[0], KEY))
        report = self.evaluate(manifest, receipts)
        self.assertEqual(report.verdict, "contaminated")
        self.assertIsNone(report.overall_gain_pp)

    def test_bad_signature_rejected(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        receipts[0] = replace(receipts[0], signature="0" * 64)
        with self.assertRaises(PermissionError):
            self.evaluate(manifest, receipts)

    def test_manifest_mismatch_rejected(self):
        manifest = build_manifest()
        with self.assertRaises(PermissionError):
            evaluate_continual_learning(manifest, (), validation_key=KEY,
                                        expected_manifest_sha256=sha("wrong"), now_unix_ms=NOW)

    def test_memory_off_must_report_zero_memory_usage(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        original = receipts[0]
        if original.arm != "memory_off":
            original = next(item for item in receipts if item.arm == "memory_off")
        bad = replace(original, memory_tokens_read=1, signature="")
        bad = replace(bad, signature=sign_receipt(bad, KEY))
        receipts[receipts.index(original)] = bad
        with self.assertRaises(PermissionError):
            self.evaluate(manifest, receipts)

    def test_memory_budget_is_enforced(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        original = next(item for item in receipts if item.arm == "memory_on")
        bad = replace(original, memory_tokens_read=manifest.memory_budget_tokens + 1, signature="")
        bad = replace(bad, signature=sign_receipt(bad, KEY))
        receipts[receipts.index(original)] = bad
        with self.assertRaises(PermissionError):
            self.evaluate(manifest, receipts)

    def test_replayed_evidence_rejected_even_with_new_run_id(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        first = receipts[0]
        second_index = 1
        second = replace(receipts[second_index], evidence_sha256=first.evidence_sha256,
                         run_id="fresh-run-id", signature="")
        second = replace(second, signature=sign_receipt(second, KEY))
        receipts[second_index] = second
        with self.assertRaises(ValueError):
            self.evaluate(manifest, receipts)

    def test_wrong_arm_order_rejected(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        original = receipts[0]
        bad = replace(original, arm_order=1 - original.arm_order, signature="")
        receipts[0] = replace(bad, signature=sign_receipt(bad, KEY))
        with self.assertRaises(PermissionError):
            self.evaluate(manifest, receipts)

    def test_future_or_stale_receipt_rejected(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        original = receipts[0]
        bad = replace(original, observed_unix_ms=NOW + 1, signature="")
        receipts[0] = replace(bad, signature=sign_receipt(bad, KEY))
        with self.assertRaises(PermissionError):
            self.evaluate(manifest, receipts)

    def test_duplicate_task_arm_rejected(self):
        manifest = build_manifest()
        receipts = list(receipts_for(manifest))
        receipts.append(receipts[0])
        with self.assertRaises(ValueError):
            self.evaluate(manifest, receipts)

    def test_invalid_dependent_reference_rejected(self):
        tasks = []
        for i in range(4):
            sid = f"s{i}"
            first = "memory_off" if i % 2 == 0 else "memory_on"
            tasks.extend([
                TaskSpec(f"a{i}", sid, 0, "coding", f"k{i}", "acquire", sha(f"a{i}"), first),
                TaskSpec(f"d{i}", sid, 1, "coding", f"k{i}", "dependent_probe", sha(f"d{i}"), first, ("missing",)),
                TaskSpec(f"i{i}", sid, 2, "coding", f"u{i}", "independent_probe", sha(f"i{i}"), first),
            ])
        with self.assertRaises(ValueError):
            CampaignManifest("c", "holdout", sha("b"), sha("r"), sha("g"), sha("p"), sha("t"),
                             sha("off"), sha("on"), 4096, 256, 1024, tuple(tasks))

    def test_retention_must_replay_exact_source_digest(self):
        tasks = []
        for i in range(4):
            sid = f"s{i}"
            first = "memory_off" if i % 2 == 0 else "memory_on"
            tasks.extend([
                TaskSpec(f"a{i}", sid, 0, "coding", f"k{i}", "acquire", sha(f"a{i}"), first),
                TaskSpec(f"d{i}", sid, 1, "coding", f"k{i}", "dependent_probe", sha(f"d{i}"), first, (f"a{i}",)),
                TaskSpec(f"i{i}", sid, 2, "coding", f"u{i}", "independent_probe", sha(f"i{i}"), first),
                TaskSpec(f"r{i}", sid, 3, "coding", f"k{i}", "retention_probe", sha(f"wrong{i}"), first, (), f"a{i}"),
            ])
        with self.assertRaises(ValueError):
            CampaignManifest("c", "holdout", sha("b"), sha("r"), sha("g"), sha("p"), sha("t"),
                             sha("off"), sha("on"), 4096, 256, 1024, tuple(tasks))

    def test_first_arm_order_must_be_balanced(self):
        tasks = []
        for i in range(4):
            sid = f"s{i}"
            first = "memory_off"
            tasks.extend([
                TaskSpec(f"a{i}", sid, 0, "coding", f"k{i}", "acquire", sha(f"a{i}"), first),
                TaskSpec(f"d{i}", sid, 1, "coding", f"k{i}", "dependent_probe", sha(f"d{i}"), first, (f"a{i}",)),
                TaskSpec(f"i{i}", sid, 2, "coding", f"u{i}", "independent_probe", sha(f"i{i}"), first),
            ])
        with self.assertRaises(ValueError):
            CampaignManifest("c", "holdout", sha("b"), sha("r"), sha("g"), sha("p"), sha("t"),
                             sha("off"), sha("on"), 4096, 256, 1024, tuple(tasks))

    def test_incomplete_campaign_cannot_recommend(self):
        manifest = build_manifest(streams=4)
        report = self.evaluate(manifest, receipts_for(manifest), minimum_streams=8)
        self.assertEqual(report.verdict, "inconclusive")


if __name__ == "__main__":
    unittest.main()
