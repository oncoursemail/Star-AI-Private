"""Offline, deterministic gates for the *unintegrated* counterfactual skill prototype."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from star.counterfactual_skills import CounterfactualSkillStore, PairedTrial, Scope, _p_value


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CounterfactualSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = CounterfactualSkillStore(Path(self.temp.name) / "skills.sqlite3")
        self.addCleanup(self.store.close)
        self.scope = Scope("Roblox", "luau_pathfinding", digest("env-v1"), digest("checker-v1"))
        self.recipe = "studio-pathfinder-v2"
        self.store.propose(self.scope, self.recipe)

    def record(self, n=12, *, wins=12, losses=0, baseline_ms=100, candidate_ms=90, recipe=None):
        for i in range(n):
            baseline_pass = not (i < wins)
            candidate_pass = i < wins or (i >= wins + losses)
            # Explicit wins, then losses, then ties (both passing).
            self.store.append_trial(self.scope, recipe or self.recipe,
                PairedTrial(digest(f"case-{i}"), baseline_pass, candidate_pass,
                            baseline_ms, candidate_ms), host_verified=True)

    def test_promotion_needs_owner_review_and_pairing(self):
        self.record()
        result = self.store.assess(self.scope, self.recipe)
        self.assertEqual(result.mode, "quality")
        self.assertFalse(result.eligible)
        self.assertIsNone(self.store.recommend(self.scope))
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        result = self.store.assess(self.scope, self.recipe)
        self.assertTrue(result.eligible)
        self.assertEqual(self.store.recommend(self.scope).recipe_ref, self.recipe)
        self.assertEqual(result.cases, 12)

    def test_explicit_owner_flag_is_needed(self):
        with self.assertRaises(PermissionError):
            self.store.approve_candidate(self.scope, self.recipe, owner_approval=False)
        self.assertIsNone(self.store.recommend(self.scope))

    def test_underpowered_not_promoted(self):
        self.record(n=10, wins=10)
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        result = self.store.assess(self.scope, self.recipe)
        self.assertFalse(result.eligible)
        self.assertEqual(result.cases, 10)

    def test_regression_rejects_even_with_many_wins(self):
        self.record(wins=10, losses=2)
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        self.assertFalse(self.store.assess(self.scope, self.recipe).eligible)

    def test_high_latency_rejects_quality_gain(self):
        self.record(candidate_ms=115)
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        self.assertFalse(self.store.assess(self.scope, self.recipe).eligible)

    def test_speed_only_improvement_requires_equal_quality(self):
        self.record(wins=0, losses=0, candidate_ms=70)
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        result = self.store.assess(self.scope, self.recipe)
        self.assertTrue(result.eligible)
        self.assertEqual(result.mode, "speed")
        self.assertEqual(result.candidate_p95_ms, 70)

    def test_unproven_latency_is_not_an_improvement(self):
        self.record(wins=0, losses=0, candidate_ms=101)
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        self.assertFalse(self.store.assess(self.scope, self.recipe).eligible)

    def test_duplicate_case_cannot_be_rewritten_or_replayed(self):
        self.record(n=1, wins=1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append_trial(self.scope, self.recipe,
                PairedTrial(digest("case-0"), True, False, 100, 20), host_verified=True)
        self.assertEqual(self.store.assess(self.scope, self.recipe).quality_wins, 1)
        self.assertEqual(self.store.assess(self.scope, self.recipe).quality_losses, 0)

    def test_trusted_host_flag_is_needed(self):
        with self.assertRaises(PermissionError):
            self.store.append_trial(self.scope, self.recipe,
                PairedTrial(digest("case-0"), False, True, 100, 30), host_verified=False)

    def test_invalid_or_holdout_trial_is_rejected(self):
        with self.assertRaises(ValueError):
            PairedTrial(digest("case"), False, True, 100, 80, partition="holdout")
        with self.assertRaises(ValueError):
            PairedTrial(digest("case"), False, True, 100, 80, origin="model")
        with self.assertRaises(ValueError):
            PairedTrial(digest("case"), 0, True, 100, 80)
        with self.assertRaises(ValueError):
            PairedTrial(digest("case"), False, True, -1, 80)

    def test_scope_blocks_cross_project_and_environment_transfer(self):
        self.record()
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        changed_project = Scope("Metallic", self.scope.task_family,
                                self.scope.environment_sha256, self.scope.toolchain_sha256)
        changed_checker = Scope(self.scope.project, self.scope.task_family,
                                self.scope.environment_sha256, digest("checker-v2"))
        changed_environment = Scope(self.scope.project, self.scope.task_family,
                                    digest("env-v2"), self.scope.toolchain_sha256)
        for other in (changed_project, changed_checker, changed_environment):
            self.assertIsNone(self.store.recommend(other))
            with self.assertRaises(KeyError):
                self.store.append_trial(other, self.recipe,
                    PairedTrial(digest("foo"), False, True, 100, 90), host_verified=True)

    def test_no_prompt_or_executable_recipe_payloads(self):
        with self.assertRaises(ValueError):
            self.store.propose(self.scope, "import os;os.system('rm -rf /')")
        with self.assertRaises(ValueError):
            self.store.propose(self.scope, "quoted\nscript")
        with self.assertRaises(ValueError):
            Scope("a project", "code", digest("env"), digest("harness"))

    def test_candidate_count_corrects_multiple_testing(self):
        # 7 quality wins, 5 ties: one-sided p=0.0078125, qualifies at alpha 0.01.
        self.record(wins=7)
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        self.assertTrue(self.store.assess(self.scope, self.recipe).eligible)
        self.store.propose(self.scope, "different-idea")
        # Two candidates in the same scope -> alpha=0.005; previous evidence no longer sufficient.
        self.assertFalse(self.store.assess(self.scope, self.recipe).eligible)

    def test_first_attempts_survive_close_and_reopen(self):
        self.record()
        self.store.approve_candidate(self.scope, self.recipe, owner_approval=True)
        with CounterfactualSkillStore(Path(self.temp.name) / "skills.sqlite3") as reopened:
            self.assertTrue(reopened.assess(self.scope, self.recipe).eligible)
            self.assertEqual(reopened.assess(self.scope, self.recipe).cases, 12)

    def test_exact_sign_probability(self):
        self.assertEqual(_p_value(0, 0), 1.0)
        self.assertEqual(_p_value(7, 0), 1 / 128)
        self.assertEqual(_p_value(0, 5), 1.0)
        self.assertEqual(_p_value(1, 1), 0.75)

    def test_no_unreviewed_advice_from_empty_store(self):
        self.assertIsNone(self.store.recommend(self.scope))
        self.assertFalse(self.store.assess(self.scope, self.recipe).eligible)


if __name__ == "__main__":
    unittest.main()
