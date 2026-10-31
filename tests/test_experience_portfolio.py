"""Offline security, reproducibility and learning-portfolio tests."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from star.experience_portfolio import (
    PracticeBudget, PracticeReceipt, PracticeTask, plan_from_json, propose_practice,
)


def task(name: str, domain: str = "gameplay", seconds: int = 60, **kw) -> PracticeTask:
    return PracticeTask(name, domain, kw.pop("scenario_id", name), seconds, host_approved=True, **kw)


def receipt(num: int, task_id: str, score: float, **kw) -> PracticeReceipt:
    return PracticeReceipt(f"r{num}", task_id, kw.pop("environment_id", f"env{num}"), num, score, **kw)


class ExperiencePortfolioTests(unittest.TestCase):
    def test_cold_start_spreads_practice_across_domains(self):
        tasks = tuple(task(name, domain) for name, domain in (
            ("game", "gameplay"), ("make", "game_creation"),
            ("voice", "streaming"), ("learn", "knowledge"), ("perf", "inference"),
        ))
        out = propose_practice(tasks, budget=PracticeBudget(max_seconds=180, max_tasks=3))
        self.assertEqual(len(out["selected"]), 3)
        self.assertEqual(len({r["domain"] for r in out["selected"]}), 3)
        self.assertEqual(out["estimated_seconds"], 180)
        self.assertFalse(out["executable"])
        self.assertFalse(out["model_trained"])

    def test_live_stream_never_schedules_background_practice(self):
        out = propose_practice((task("fps"), task("chat", "streaming")),
                               budget=PracticeBudget(live_streaming=True))
        self.assertEqual(out["selected"], [])
        self.assertEqual(len(out["blocked"]), 2)
        self.assertTrue(all(row["reason"] == "live_streaming_offline_practice_paused"
                            for row in out["blocked"]))

    def test_default_denies_unapproved_network_and_gpu(self):
        tasks = (PracticeTask("unapproved", "knowledge", "a", 10),
                 task("online", "knowledge", 10, network_required=True),
                 task("biggpu", "inference", 10, gpu_mb=500),
                 task("offline", "game_creation", 10))
        out = propose_practice(tasks, budget=PracticeBudget(gpu_headroom_mb=256))
        self.assertEqual([row["task_id"] for row in out["selected"]], ["offline"])
        self.assertEqual({b["task_id"]: b["reason"] for b in out["blocked"]},
                         {"unapproved": "host_approval_missing",
                          "online": "network_not_allowed",
                          "biggpu": "gpu_headroom_exceeded"})

    def test_budget_never_overruns_and_one_scenario_per_batch(self):
        tasks = (task("a", seconds=110, scenario_id="same"),
                 task("b", seconds=110, scenario_id="same"),
                 task("c", seconds=110, scenario_id="other"))
        out = propose_practice(tasks, budget=PracticeBudget(max_seconds=220, max_tasks=8))
        self.assertLessEqual(out["estimated_seconds"], 220)
        self.assertEqual(len(out["selected"]), 2)
        self.assertEqual(len({s["scenario_id"] for s in out["selected"]}), 2)

    def test_oversize_task_is_blocked_without_execution(self):
        out = propose_practice((task("long", seconds=400),),
                               budget=PracticeBudget(max_seconds=100))
        self.assertEqual(out["selected"], [])
        self.assertEqual(out["blocked"], [{"task_id": "long", "reason": "duration_exceeds_budget"}])

    def test_holdout_is_never_used_to_select_or_score(self):
        tasks = (task("a"), task("b", "streaming"))
        base = (receipt(1, "a", .2), receipt(2, "b", .8))
        original = propose_practice(tasks, base)
        held = tuple(receipt(i, "a", float(i % 2), split="holdout")
                     for i in range(100, 150))
        augmented = propose_practice(tasks, base + held)
        self.assertEqual(original["selected"], augmented["selected"])
        self.assertEqual(original["deferred_task_ids"], augmented["deferred_task_ids"])
        self.assertEqual(augmented["holdout_receipts_excluded"], len(held))

    def test_duplicate_environment_does_not_inflate_independence(self):
        history = (receipt(1, "game", 1, environment_id="seed1"),
                   receipt(2, "game", 1, environment_id="seed1"),
                   receipt(3, "game", 0, environment_id="seed2"))
        out = propose_practice((task("game"),), history)
        self.assertEqual(out["selected"][0]["independent_practice_receipts"], 2)

    def test_learning_progress_changes_priority_on_independent_seeds(self):
        tasks = (task("up", seconds=100), task("down", seconds=100))
        rows = tuple(receipt(i, "up", score) for i, score in enumerate((0, 0, 1, 1), 1))
        rows += tuple(receipt(i, "down", score) for i, score in enumerate((1, 1, 0, 0), 11))
        out = propose_practice(tasks, rows, PracticeBudget(max_tasks=1))
        self.assertEqual(out["selected"][0]["task_id"], "up")

    def test_repeated_unproductive_seed_not_promoted_to_productive_signal(self):
        history = tuple(receipt(i, "a", 1, environment_id="same") for i in range(1, 40))
        out = propose_practice((task("a"),), history)
        self.assertEqual(out["selected"][0]["independent_practice_receipts"], 1)

    def test_order_determinism_across_tasks_and_receipts(self):
        tasks = (task("z"), task("a", "streaming"), task("m", "knowledge"))
        rows = (receipt(1, "z", 0), receipt(2, "a", 1), receipt(3, "m", .3))
        forward = propose_practice(tasks, rows)
        backward = propose_practice(tuple(reversed(tasks)), tuple(reversed(rows)))
        self.assertEqual(forward, backward)

    def test_duplicate_receipts_and_unknown_targets_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate receipt ID"):
            propose_practice((task("a"),), (receipt(1, "a", 1), receipt(1, "a", 0)))
        with self.assertRaisesRegex(ValueError, "unknown task"):
            propose_practice((task("a"),), (receipt(2, "missing", 1),))

    def test_duplicate_tasks_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate task ID"):
            propose_practice((task("a"), task("a")))

    def test_invalid_numbers_flags_and_categories_fail(self):
        for score in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.subTest(score=score), self.assertRaises(ValueError):
                receipt(1, "a", score)
        with self.assertRaises(ValueError):
            PracticeBudget(max_seconds=True)
        with self.assertRaises(ValueError):
            PracticeTask("foo", "invalid", "x", 10, host_approved=True)
        with self.assertRaises(ValueError):
            PracticeTask("foo", "gameplay", "x", 10, host_approved=1)
        with self.assertRaises(ValueError):
            PracticeReceipt("id", "a", "seed", 0, 1, split="test")

    def test_strict_json_and_bounded_input(self):
        good = {
            "tasks": [{"task_id": "demo", "domain": "gameplay", "scenario_id": "level-1",
                       "estimated_seconds": 15, "host_approved": True}],
            "receipts": [],
            "budget": {"max_seconds": 30},
        }
        out = plan_from_json(json.dumps(good).encode())
        self.assertEqual(out["selected"][0]["task_id"], "demo")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            plan_from_json(b'{"tasks":[],"tasks":[],"receipts":[],"budget":{}}')
        with self.assertRaises(ValueError):
            plan_from_json(b'{"tasks":[],"receipts":[],"budget":{},"extra":true}')
        with self.assertRaises(ValueError):
            plan_from_json(b'{"tasks":[],"receipts":[],"budget":{"max_seconds":NaN}}')
        with self.assertRaises(ValueError):
            plan_from_json(b"x" * 512_001)

    def test_cli_runs_offline_and_emits_proposal(self):
        obj = {"tasks": [{"task_id": "voice", "domain": "streaming", "scenario_id": "rehearsal",
                          "estimated_seconds": 30, "host_approved": True}],
               "receipts": [], "budget": {}}
        run = subprocess.run([sys.executable, "-m", "star.experience_portfolio"],
                             input=json.dumps(obj), text=True, capture_output=True,
                             timeout=10, check=True)
        out = json.loads(run.stdout)
        self.assertEqual(out["selected"][0]["domain"], "streaming")
        self.assertFalse(out["executable"])


if __name__ == "__main__":
    unittest.main()
