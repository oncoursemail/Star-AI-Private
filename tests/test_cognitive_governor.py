"""Offline, standard-library tests of verified autonomous effort advice."""
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from star.cognitive_governor import (
    EffortBudget, GradeReceipt, OutcomeLedger, advise_effort, advise_initiative,
)


class CognitiveGovernorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "private" / "cognitive.sqlite3"
        self.ledger = OutcomeLedger(self.path)

    def receipt(self, *, project="GameOne", family="luau", model="quick",
                revision="rev1", case_id="case1", run_id="run1",
                result="pass", verifier="independent_eval", split="development",
                elapsed_ms=1000):
        evidence = hashlib.sha256(
            f"{project}/{family}/{model}/{revision}/{case_id}/{run_id}/{result}".encode()
        ).hexdigest()
        return GradeReceipt(project, family, model, revision, run_id, case_id,
                            result, elapsed_ms, verifier, evidence, split)

    def put(self, n, *, result="pass", family="luau", revision="rev1",
            project="GameOne", model="quick"):
        for i in range(n):
            self.ledger.record_grade(self.receipt(
                project=project, family=family, model=model, revision=revision,
                case_id=f"case{i}", run_id=f"run{i}", result=result,
                elapsed_ms=1000 + i * 100
            ))

    def stats(self, *, project="GameOne", family="luau", model="quick", revision="rev1"):
        return self.ledger.summary(project=project, family=family,
                                   model=model, revision=revision)

    def test_empty_summary_does_not_create_file(self):
        s = self.stats()
        self.assertEqual(s.distinct_cases, 0)
        self.assertIsNone(s.wilson_lower_95)
        self.assertFalse(self.path.exists())

    def test_records_distinct_verified_cases(self):
        self.put(20)
        s = self.stats()
        self.assertEqual((s.distinct_cases, s.passed, s.failed, s.errored), (20, 20, 0, 0))
        self.assertGreater(s.wilson_lower_95, 0.75)
        self.assertTrue(s.eligible_for_fast)
        self.assertEqual(s.median_ms, 1950)
        self.assertEqual(s.p95_ms, 2800)

    def test_revision_model_and_project_isolation(self):
        self.put(16)
        self.assertEqual(self.stats(project="GameTwo").distinct_cases, 0)
        self.assertEqual(self.stats(model="deep").distinct_cases, 0)
        self.assertEqual(self.stats(revision="rev2").distinct_cases, 0)
        self.assertEqual(self.stats(family="graphics").distinct_cases, 0)

    def test_retry_is_idempotent_and_conflict_is_rejected(self):
        r = self.receipt()
        self.assertTrue(self.ledger.record_grade(r))
        self.assertFalse(self.ledger.record_grade(r))
        with self.assertRaises(ValueError):
            self.ledger.record_grade(self.receipt(result="fail"))
        self.assertEqual(self.stats().distinct_cases, 1)

    def test_repeated_case_does_not_fake_sample_size(self):
        for i in range(30):
            self.ledger.record_grade(self.receipt(run_id=f"run{i}"))
        s = self.stats()
        self.assertEqual(s.distinct_cases, 1)
        self.assertFalse(s.eligible_for_fast)

    def test_first_attempt_failure_cannot_be_erased_by_retry(self):
        self.ledger.record_grade(self.receipt(result="fail", run_id="old"))
        self.ledger.record_grade(self.receipt(result="pass", run_id="new"))
        s = self.stats()
        self.assertEqual((s.distinct_cases, s.passed, s.failed), (1, 0, 1))

    def test_uncertain_and_error_outcomes_not_claimed_as_success(self):
        self.put(3, result="error")
        s = self.stats()
        self.assertEqual((s.passed, s.errored, s.observed_pass_rate), (0, 3, 0))
        self.assertFalse(s.eligible_for_fast)

    def test_recording_never_accepts_self_grade_or_holdout(self):
        with self.assertRaises(ValueError):
            self.ledger.record_grade(self.receipt(verifier="model"))
        with self.assertRaises(ValueError):
            self.ledger.record_grade(self.receipt(split="holdout"))
        with self.assertRaises(ValueError):
            self.ledger.record_grade(self.receipt(split="production"))
        self.assertFalse(self.path.exists())

    def test_receipt_validation_rejects_raw_prompts_and_fake_hashes(self):
        with self.assertRaises(ValueError):
            self.receipt(case_id="build a sword with secrets")
        with self.assertRaises(ValueError):
            GradeReceipt("GameOne", "luau", "quick", "rev1", "run1", "case1",
                         "pass", 42, "independent_eval", "not-a-digest")
        with self.assertRaises(ValueError):
            self.receipt(elapsed_ms=-1)
        with self.assertRaises(ValueError):
            self.receipt(result="almost_pass")
        with self.assertRaises(ValueError):
            self.receipt(project="../Other")

    def test_receipts_are_append_only(self):
        self.ledger.record_grade(self.receipt())
        with closing(sqlite3.connect(self.path)) as con:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("DELETE FROM grades")
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute("UPDATE grades SET result='fail'")

    def test_old_results_expire_from_advice_but_stay_in_ledger(self):
        self.ledger.record_grade(self.receipt())
        s = self.ledger.summary(project="GameOne", family="luau", model="quick",
                                revision="rev1", now=9999999999)
        self.assertEqual(s.distinct_cases, 0)
        self.assertEqual(self.stats().distinct_cases, 1)

    def test_symlinked_database_is_rejected(self):
        target = Path(self.tmp.name) / "target.sqlite3"
        target.touch()
        link = Path(self.tmp.name) / "shortcut.sqlite3"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(ValueError):
            OutcomeLedger(link)

    def test_sparse_evidence_can_request_bounded_best_of_n(self):
        s = self.stats()
        advice = advise_effort(s, EffortBudget(4, 60, 3), stakes="low",
                               external_verifier_available=True)
        self.assertEqual((advice.mode, advice.candidate_count), ("BEST_OF_N_VERIFY", 3))
        self.assertTrue(advice.external_verification_required)
        self.assertFalse(advice.owner_approval_required)

    def test_no_extra_budget_does_not_launch_more_agents(self):
        advice = advise_effort(self.stats(), EffortBudget(4, 10, 1), stakes="low",
                               external_verifier_available=True)
        self.assertEqual((advice.mode, advice.candidate_count), ("STANDARD_VERIFY", 1))

    def test_strong_evidence_can_recommend_faster_route_without_skipping_check(self):
        self.put(25)
        advice = advise_effort(self.stats(), EffortBudget(), stakes="low",
                               external_verifier_available=True)
        self.assertEqual((advice.mode, advice.candidate_count), ("FAST_VERIFY", 1))
        self.assertTrue(advice.external_verification_required)
        medium = advise_effort(self.stats(), EffortBudget(), stakes="medium",
                               external_verifier_available=True)
        self.assertEqual(medium.mode, "STANDARD_VERIFY")

    def test_high_stakes_and_irreversible_require_owner(self):
        for stakes, reversible in (("high", True), ("low", False)):
            result = advise_effort(self.stats(), EffortBudget(8, 3600, 8),
                                   stakes=stakes, action_is_reversible=reversible,
                                   external_verifier_available=True)
            self.assertEqual(result.mode, "OWNER_REVIEW")
            self.assertTrue(result.owner_approval_required)

    def test_no_external_verifier_blocks_unverified_promotion(self):
        result = advise_effort(self.stats(), EffortBudget(8, 3600, 8),
                               stakes="medium", external_verifier_available=False)
        self.assertEqual(result.mode, "GET_EVIDENCE")
        self.assertTrue(result.owner_approval_required)
        self.assertTrue(result.external_verification_required)

    def test_budget_rejects_invalid_values(self):
        for args in ((0, 60, 1), (2, 0, 1), (9, 60, 1), (2, 45, 0), (2, 45, True)):
            with self.assertRaises(ValueError):
                EffortBudget(*args)

    def test_practice_favors_failures_and_uncovered_families(self):
        self.put(16, family="strong")
        self.put(10, result="fail", family="weak")
        results = self.ledger.suggest_practice(
            project="GameOne", model="quick", revision="rev1",
            families=("strong", "weak", "uncovered"), limit=3
        )
        self.assertEqual([item.family for item in results],
                         ["weak", "uncovered", "strong"])
        self.assertEqual(results[0].distinct_cases, 10)

    def test_practice_refuses_holdout_and_unreviewed_ids(self):
        for name in ("holdout_secret", "sealed_suite", "private-test-1"):
            with self.assertRaises(ValueError):
                self.ledger.suggest_practice(
                    project="GameOne", model="quick", revision="rev1",
                    families=(name,)
                )
        with self.assertRaises(ValueError):
            self.ledger.suggest_practice(project="GameOne", model="quick",
                                         revision="rev1", families=("same", "same"))
        with self.assertRaises(ValueError):
            self.ledger.suggest_practice(project="GameOne", model="quick",
                                         revision="rev1", families=("unsafe text",))

    def test_initiative_is_opt_in_and_never_bothers_speaking_user(self):
        proof = "a" * 64
        base = dict(event="verified_failure", opt_in=True,
                    evidence_sha256=proof, user_speaking=False, quiet_hours=False)
        self.assertEqual(advise_initiative(**base).action, "OFFER_UPDATE")
        self.assertEqual(advise_initiative(**{**base, "opt_in": False}).action, "SILENT")
        self.assertEqual(advise_initiative(**{**base, "user_speaking": True}).action, "WAIT")
        self.assertEqual(advise_initiative(**{**base, "quiet_hours": True}).action, "WAIT")
        self.assertEqual(advise_initiative(**{**base, "evidence_sha256": None}).action, "SILENT")
        self.assertEqual(advise_initiative(**{**base, "event": "idle"}).action, "SILENT")
        self.assertEqual(advise_initiative(**{**base, "approval_pending": True}).action, "ASK_PERMISSION")

    def test_cli_report_is_read_only_when_database_does_not_exist(self):
        cmd = [sys.executable, "-m", "star.cognitive_governor", "--db", str(self.path),
               "--project", "GameOne", "--family", "luau", "--model", "quick",
               "--revision", "rev1"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STANDARD_VERIFY", result.stdout)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
