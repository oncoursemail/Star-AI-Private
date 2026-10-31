"""Offline trusted-host tests for STAR's frontier practice ladder."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from star import frontier_quests as fq


class FrontierProblemTests(unittest.TestCase):
    def test_generators_are_deterministic_and_oracle_solvable(self):
        for family in fq.FAMILIES:
            for level in range(1, fq.MAX_LEVEL + 1):
                for seed in (0, 1, 42, 20261025):
                    prompt, spec = fq.build_problem(family, level, seed)
                    self.assertEqual((prompt, spec), fq.build_problem(family, level, seed))
                    expected = fq.oracle_answer(family, spec)
                    self.assertIsInstance(expected, dict)
                    self.assertLess(len(prompt), 20_000)
                    self.assertTrue(all(type(x) is int for x in expected.values()
                                        if not isinstance(x, dict)))
                    self.assertIn("JSON", prompt)
                    self.assertNotIn("evals/", prompt)

    def test_route_passes_through_checkpoint_without_double_counting(self):
        spec = {"grid": [[1, 2, 9], [5, 2, 9], [9, 1, 1]],
                "checkpoints": [[1, 1]], "count_optimal": False}
        # Start (0,0) -> (1,1) costs 1+2+2=5;
        # checkpoint -> goal costs 2+1+1=4; only count checkpoint once.
        self.assertEqual(fq._route_answer(spec), {"minimum_cost": 7})

    def test_shortest_route_counts_ties(self):
        spec = {"grid": [[1, 1], [1, 1]], "checkpoints": [], "count_optimal": True}
        self.assertEqual(fq._route_answer(spec), {"minimum_cost": 3, "optimal_routes": 2})

    def test_fusion_has_only_one_answer_instruction_and_unmodified_input(self):
        prompt, spec = fq.build_problem("fusion", 12, 24)
        self.assertEqual(prompt.count("Return ONLY"), 1)
        self.assertIn("ORIGINAL, not adjusted", prompt)
        self.assertEqual(
            fq.oracle_answer("fusion", spec)["minimum_cost"],
            fq._route_answer(spec["route"])["minimum_cost"],
        )

    def test_scheduler_dependencies_are_valid(self):
        for level in range(1, 13):
            _prompt, spec = fq.build_problem("scheduler", level, 99)
            earlier = set()
            for task in spec["tasks"]:
                self.assertTrue(set(task["after"]) <= earlier)
                earlier.add(task["id"])
            result = fq.oracle_answer("scheduler", spec)
            self.assertGreater(result["makespan"], 0)

    def test_boolean_cannot_pass_as_integer(self):
        self.assertFalse(fq._exact({"cost": True}, {"cost": 1}))
        self.assertFalse(fq._exact({"x": 1, "bonus": 2}, {"x": 1}))
        self.assertFalse(fq._exact({"starts": {"T1": False}}, {"starts": {"T1": 0}}))

    def test_reject_invalid_generators(self):
        for family, level, seed in (("evil", 2, 1), ("route", 0, 1),
                                    ("route", 13, 1), ("route", 2, -1),
                                    ("route", True, 1), ("route", 2, True)):
            with self.assertRaises(ValueError):
                fq.build_problem(family, level, seed)


class FrontierStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.store = fq.FrontierStore(self.home)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def answer(self, challenge: fq.Challenge) -> str:
        row = self.store.db.execute(
            "SELECT specification FROM frontier_challenges WHERE id=?", (challenge.id,)
        ).fetchone()
        self.assertIsNotNone(row)
        return fq._json(fq.oracle_answer(challenge.family, json.loads(row["specification"])))

    def complete(self, family: str, *, correct: bool, seed: int):
        challenge = self.store.issue("STAR", family=family, seed=seed)
        answer = self.answer(challenge) if correct else '{"intentionally_wrong":true}'
        return self.store.grade("STAR", challenge.id, answer)

    def test_database_is_local_and_private(self):
        self.assertTrue(self.store.path.is_file())
        self.assertTrue(str(self.store.path).startswith(str(self.home)))
        self.assertEqual(self.store.overview("STAR")["measured_holdout_improvement"], False)
        self.assertEqual(self.store.overview("STAR")["trained_model_weights"], False)

    def test_pending_task_reused_instead_of_spam(self):
        first = self.store.issue("STAR", family="route", seed=13)
        second = self.store.issue("STAR", family="route", seed=1234)
        self.assertEqual(first, second)
        self.assertTrue(first.training_only)
        self.assertNotIn("expected_answer", asdict(first))
        self.assertNotIn("specification", asdict(first))
        self.assertEqual(len(first.id), 64)
        self.assertEqual(self.store.overview("STAR")["pending"], 1)

    def test_correct_answer_advances_at_three_passes(self):
        for seed in (0, 1, 2):
            outcome = self.complete("route", correct=True, seed=seed)
        self.assertTrue(outcome["passed"])
        self.assertEqual(outcome["next_level"], 2)
        new = self.store.issue("STAR", family="route", seed=3)
        self.assertEqual(new.level, 2)
        self.assertFalse(self.store.overview("STAR")["measured_holdout_improvement"])

    def test_three_failures_regress_but_not_below_one(self):
        for seed in (0, 1, 2):
            self.complete("scheduler", correct=True, seed=seed)
        self.assertEqual(self.store.issue("STAR", family="scheduler", seed=3).level, 2)
        self.store.grade("STAR", self.store.issue("STAR", family="scheduler").id, "wrong")
        self.complete("scheduler", correct=False, seed=4)
        outcome = self.complete("scheduler", correct=False, seed=5)
        self.assertEqual(outcome["next_level"], 1)
        for seed in (6, 7, 8):
            self.complete("scheduler", correct=False, seed=seed)
        self.assertEqual(self.store.overview("STAR")["families"][0]["level"], 1)  # scheduler is only family

    def test_submission_is_one_shot_and_scoped(self):
        c = self.store.issue("STAR", family="route", seed=5)
        with self.assertRaises(ValueError):
            self.store.grade("OTHER", c.id, self.answer(c))
        self.store.grade("STAR", c.id, self.answer(c))
        with self.assertRaises(ValueError):
            self.store.grade("STAR", c.id, self.answer(c))
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM frontier_attempts").fetchone()[0], 1
        )

    def test_reject_forged_specification(self):
        c = self.store.issue("STAR", family="route", seed=6)
        self.store.db.execute(
            "UPDATE frontier_challenges SET specification=? WHERE id=?",
            ('{"grid": [[0]], "checkpoints":[], "count_optimal": false}', c.id),
        )
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.store.grade("STAR", c.id, '{"minimum_cost":0}')
        self.assertEqual(self.store.overview("STAR")["pending"], 1)

    def test_bad_json_is_counted_as_failure(self):
        c = self.store.issue("STAR", family="game-state", seed=10)
        out = self.store.grade("STAR", c.id, "not-json")
        self.assertFalse(out["passed"])
        self.assertEqual(out["next_level"], 1)

    def test_answers_are_hashed_not_stored_plaintext(self):
        c = self.store.issue("STAR", family="scheduler", seed=7)
        raw = self.answer(c)
        self.store.grade("STAR", c.id, raw)
        row = self.store.db.execute("SELECT * FROM frontier_attempts").fetchone()
        self.assertEqual(len(row["answer_sha256"]), 64)
        self.assertNotIn(raw, json.dumps(dict(row)))

    def test_no_project_cross_leak(self):
        first = self.store.issue("STAR", family="route", seed=10)
        second = self.store.issue("DIFFERENT", family="route", seed=10)
        self.assertNotEqual(first.id, second.id)
        self.store.grade("STAR", first.id, self.answer(first))
        self.assertEqual(self.store.overview("DIFFERENT")["pending"], 1)

    def test_proposals_only_follow_verified_repeated_failures(self):
        self.assertEqual(self.store.propose_focus("STAR"), [])
        for seed in (1, 2, 3):
            self.complete("game-state", correct=False, seed=seed)
        proposals = self.store.propose_focus("STAR")
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["family"], "game-state")
        self.assertEqual(proposals[0]["status"], "candidate")
        self.assertFalse(proposals[0]["opened_pr"])
        self.assertEqual(len(self.store.propose_focus("STAR")), 1)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM frontier_proposals").fetchone()[0], 1
        )

    def test_one_upgrade_proposal_per_eight_additional_attempts(self):
        for seed in range(3):
            self.complete("route", correct=False, seed=seed)
        first = self.store.propose_focus("STAR")[0]["id"]
        for seed in range(3, 10):
            self.complete("route", correct=False, seed=seed)
            self.assertEqual(self.store.propose_focus("STAR")[0]["id"], first)
        self.complete("route", correct=False, seed=10)
        second = self.store.propose_focus("STAR")[0]["id"]
        self.assertNotEqual(first, second)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM frontier_proposals").fetchone()[0], 2)

    def test_invalid_identifiers_and_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            self.store.issue("../../../private")
        with self.assertRaises(ValueError):
            self.store.issue("STAR", family="unknown")
        with self.assertRaises(ValueError):
            self.store.issue("STAR", family="route", seed=True)
        with self.assertRaises(ValueError):
            self.store.grade("STAR", "invalid", '{"x":2}')
        c = self.store.issue("STAR", family="route", seed=3)
        with self.assertRaises(ValueError):
            self.store.grade("STAR", c.id, "x" * (fq.MAX_ANSWER_BYTES + 1))

    def test_symlinked_database_and_home_refused(self):
        symlink = self.home / "linked"
        try:
            symlink.symlink_to(self.home, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("OS symlink unavailable")
        with self.assertRaises(PermissionError):
            fq.FrontierStore(symlink)
        self.store.close()
        self.store.path.unlink()
        self.store.path.symlink_to(self.home / "other-file")
        with self.assertRaises(PermissionError):
            fq.FrontierStore(self.home)
        self.store = fq.FrontierStore.__new__(fq.FrontierStore)
        self.store.close = lambda: None  # tearDown already closed the real store

    def test_fusion_unlock_after_two_basic_masteries(self):
        for family in ("route", "scheduler"):
            for seed in range(6):
                self.complete(family, correct=True, seed=seed)
        auto = self.store.issue("STAR")
        self.assertIn(auto.family, fq.FAMILIES)
        self.assertIn("fusion", [r["family"] for r in self.store.overview("STAR")["families"]])


class FrontierCampaignTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = fq.FrontierStore(Path(self.tmp.name))

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_disabled_by_default(self):
        async def solve(_challenge):
            raise AssertionError("solver must never be called")
        with self.assertRaises(PermissionError):
            await fq.practice_campaign(self.store, "STAR", solve)
        self.assertEqual(self.store.overview("STAR")["pending"], 0)

    async def test_campaign_with_trusted_oracle_simulator(self):
        async def solve(challenge):
            row = self.store.db.execute("SELECT specification FROM frontier_challenges WHERE id=?",
                                        (challenge.id,)).fetchone()
            return fq._json(fq.oracle_answer(challenge.family, json.loads(row[0])))
        report = await fq.practice_campaign(self.store, "STAR", solve,
                                            host_approved=True, count=4)
        self.assertEqual(report["attempts"], 4)
        self.assertTrue(all(r["passed"] for r in report["results"]))
        self.assertFalse(report["opened_pr"])
        self.assertFalse(report["trained_model_weights"])

    async def test_solver_exception_leaves_pending_for_inspection(self):
        async def solve(_challenge):
            raise RuntimeError("local inference stopped")
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            await fq.practice_campaign(self.store, "STAR", solve, host_approved=True, count=1)
        self.assertEqual(self.store.overview("STAR")["pending"], 1)

    async def test_campaign_budget_enforced(self):
        async def solve(_challenge):
            return "{}"
        for count in (0, 7, True):
            with self.assertRaises(ValueError):
                await fq.practice_campaign(self.store, "STAR", solve, host_approved=True, count=count)


class FrontierUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = fq.FrontierStore(Path(self.tmp.name))

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def seed_failure_proposal(self):
        for seed in (1, 2, 3):
            c = self.store.issue("STAR", family="route", seed=seed)
            self.store.grade("STAR", c.id, "{}")
        self.assertEqual(len(self.store.propose_focus("STAR")), 1)

    async def test_fails_closed_without_host_approval(self):
        with self.assertRaises(PermissionError):
            await fq.draft_skill_upgrade(
                self.store, "STAR", client=None, model="local-model", repository=Path("."))

    async def test_skips_selfbuilder_without_evidence(self):
        result = await fq.draft_skill_upgrade(
            self.store, "STAR", client=None, model="local-model", repository=Path("."),
            host_approved=True)
        self.assertEqual(result["status"], "no_evidence")
        self.assertFalse(result["opened_pr"])

    async def test_sends_only_scoped_reviewable_skill_and_is_idempotent(self):
        self.seed_failure_proposal()
        called = []

        async def mock_builder(**kwargs):
            called.append(kwargs)
            return {"branch": "star/skill-simulated",
                    "files": ["docs/skills/frontier-pathfinding-reasoning.md"],
                    "github_pr": None, "verification": "NOT EXECUTED"}

        with patch("star.selfbuild.develop", new=mock_builder):
            outcome = await fq.draft_skill_upgrade(
                self.store, "STAR", client=object(), model="local-model",
                repository=Path("."), host_approved=True)
            repeated = await fq.draft_skill_upgrade(
                self.store, "STAR", client=object(), model="local-model",
                repository=Path("."), host_approved=True)
        self.assertEqual(len(called), 1)
        self.assertEqual(outcome["status"], "review_candidate_created")
        self.assertTrue(outcome["review_required"])
        self.assertFalse(outcome["merged"])
        self.assertFalse(outcome["opened_pr"])
        self.assertEqual(repeated["status"], "already_submitted_or_needs_review")
        self.assertIn("docs/skills/frontier-pathfinding-reasoning.md", called[0]["task"])
        self.assertEqual(called[0]["github"], None)

    async def test_unknown_builder_failure_does_not_retry(self):
        self.seed_failure_proposal()
        called = []

        async def fail(**_kwargs):
            called.append(1)
            raise RuntimeError("builder result or remote state unknown")

        with patch("star.selfbuild.develop", new=fail):
            with self.assertRaises(RuntimeError):
                await fq.draft_skill_upgrade(
                    self.store, "STAR", client=None, model="local-model",
                    repository=Path("."), host_approved=True)
            second = await fq.draft_skill_upgrade(
                self.store, "STAR", client=None, model="local-model",
                repository=Path("."), host_approved=True)
        self.assertEqual(called, [1])
        self.assertEqual(second["job_status"], "unknown")

    async def test_bad_receipt_cannot_claim_a_real_pr(self):
        self.seed_failure_proposal()

        async def forged(**_kwargs):
            return {"branch": "main", "files": ["evals/holdout.json"], "github_pr": "https://fake"}

        with patch("star.selfbuild.develop", new=forged):
            with self.assertRaisesRegex(ValueError, "receipt"):
                await fq.draft_skill_upgrade(
                    self.store, "STAR", client=None, model="local-model",
                    repository=Path("."), host_approved=True)
        row = self.store.db.execute("SELECT status FROM frontier_upgrade_jobs").fetchone()
        self.assertEqual(row["status"], "unknown")

    async def test_pending_github_writer_migration_cannot_be_bypassed(self):
        self.seed_failure_proposal()
        with self.assertRaisesRegex(TypeError, "scoped GitHubApp"):
            await fq.draft_skill_upgrade(
                self.store, "STAR", client=None, model="local-model",
                repository=Path("."), host_approved=True,
                github=SimpleNamespace(repo="oncoursemail/Star-AI-Private"))
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM frontier_upgrade_jobs").fetchone()[0], 0)


class FrontierCLITests(unittest.TestCase):
    def test_preview_offline_no_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "star.frontier_quests", "preview",
                 "--family", "route", "--level", "4", "--seed", "42"],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            parsed = json.loads(result.stdout)
            self.assertEqual(parsed["level"], 4)
            self.assertIn("minimum_cost", parsed["answer_schema"])
            self.assertFalse((Path(tmp) / "frontier_quests").exists())


if __name__ == "__main__":
    unittest.main()
