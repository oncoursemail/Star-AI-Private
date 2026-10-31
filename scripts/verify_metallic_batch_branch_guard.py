"""Check batch provenance with fake contexts and fully replaced queue I/O. No real queue runs."""
from __future__ import annotations

from contextlib import ExitStack, nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metallic.metallic import checks, queue  # noqa: E402
from metallic.metallic.config import Config  # noqa: E402


def protection(cfg, branch, changed):
    return checks.check_protected(checks.Context(
        root=Path("unused-fake-root"), cfg=cfg, base_tree="base", tree="combined",
        files=dict.fromkeys(changed, "fake-blob"), changed=list(changed), branch=branch,
    ))


def fake_batch(branches, changes, cfg, *, base_cfg=None):
    """Exercise production control flow; replace every Git, lock and filesystem operation."""
    root, state_dir = Path("unused-fake-root"), Path("unused-fake-state")
    state = {"head": "target", "trees": {"target": set()}, "serial": 0}
    references = {name: f"ref-{i}" for i, name in enumerate(branches)}
    seen = []
    cache = Mock(name="unused-cache")

    def rev(name, _root):
        if name == "HEAD":
            return state["head"]
        return "target" if name == "target" else references[name]

    def merge(_scratch, _sha, label, _identity):
        state["serial"] += 1
        head = f"combined-{state['serial']}"
        state["trees"][head] = state["trees"][state["head"]] | set(changes[label])
        state["head"] = head
        return []

    def git(args, _root, **_kwargs):
        if args[0] == "checkout":
            state["head"] = args[-1]
        elif args[:2] not in (["worktree", "add"], ["worktree", "remove"], ["worktree", "prune"]):
            raise AssertionError(f"Unexpected fake Git operation: {args[0]}")
        return ""

    def run_check(_scratch, combined_cfg, **kwargs):
        changed = state["trees"][kwargs["tree"]] - state["trees"][kwargs["base"]]
        result = protection(combined_cfg, kwargs["branch"], sorted(changed))
        seen.append((kwargs.copy(), result))
        red = [result.name] if result.status == checks.FAIL else []
        return {"verdict": "red" if red else "green", "red": red, "tree": kwargs["tree"],
                "timings": {"total": 0}, "tests": {}, "checks": [result.to_dict()]}

    with ExitStack() as stack:
        stack.enter_context(patch.object(queue, "load", side_effect=lambda path: (base_cfg or cfg) if path == root else cfg))
        stack.enter_context(patch.object(queue, "Lock", side_effect=lambda *_args: nullcontext()))
        stack.enter_context(patch.object(queue.Path, "exists", return_value=False))
        stack.enter_context(patch.object(queue.gitutil, "state_dir", return_value=state_dir))
        stack.enter_context(patch.object(queue.gitutil, "rev", side_effect=rev))
        stack.enter_context(patch.object(queue.gitutil, "tree_of", side_effect=lambda sha, _root: sha))
        stack.enter_context(patch.object(queue.gitutil, "git", side_effect=git))
        stack.enter_context(patch.object(queue, "_merge", side_effect=merge))
        stack.enter_context(patch.object(queue.shutil, "rmtree", return_value=None))
        stack.enter_context(patch.object(queue.engine, "run_check", side_effect=run_check))
        report = queue.run(root, "target", branches, cache=cache, apply=False)
    return report, seen, cache


class BatchBranchGuard(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(name="fake", generator_branches=["star/gen-*"], protected_paths=["evals/**"])

    def test_original_synthetic_label_loses_a_generator_restriction(self):
        self.assertEqual(protection(self.cfg, "star/gen-example", ["evals/fake.json"]).status, checks.FAIL)
        self.assertEqual(protection(self.cfg, "metallic-queue", ["evals/fake.json"]).status, checks.PASS)

    def test_generator_first_batch_is_rejected_then_safe_branch_survives(self):
        report, seen, _ = fake_batch(["star/gen-bad", "owner/docs"],
                                    {"star/gen-bad": ["evals/fake.json"], "owner/docs": ["docs/note.md"]}, self.cfg)
        self.assertEqual(seen[0][0]["branch"], "star/gen-bad")
        self.assertEqual(report["batch"]["verdict"], "red")
        self.assertEqual([(e["branch"], e["status"]) for e in report["entries"]],
                         [("star/gen-bad", "rejected"), ("owner/docs", "merged")])
        self.assertFalse(report["applied"])

    def test_generator_second_still_supplies_batch_context(self):
        report, seen, _ = fake_batch(["owner/docs", "star/gen-bad"],
                                    {"owner/docs": ["docs/note.md"], "star/gen-bad": ["evals/fake.json"]}, self.cfg)
        self.assertEqual(seen[0][0]["branch"], "star/gen-bad")
        self.assertEqual(report["merged"], ["owner/docs"])

    def test_non_generator_batch_keeps_its_label_and_fast_path(self):
        report, seen, _ = fake_batch(["owner/a", "owner/b"],
                                    {"owner/a": ["evals/fake.json"], "owner/b": ["docs/note.md"]}, self.cfg)
        self.assertEqual(seen[0][0]["branch"], "metallic-queue")
        self.assertEqual(report["batch"]["verdict"], "green")
        self.assertEqual(len(seen), 1)

    def test_mixed_batch_fallback_does_not_blame_an_unrelated_generator(self):
        report, seen, _ = fake_batch(["owner/eval", "star/gen-safe"],
                                    {"owner/eval": ["evals/fake.json"], "star/gen-safe": ["pkg/safe.py"]}, self.cfg)
        self.assertEqual(report["batch"]["verdict"], "red")
        self.assertEqual(report["merged"], ["owner/eval", "star/gen-safe"])
        self.assertEqual([item[1].status for item in seen], [checks.FAIL, checks.PASS, checks.PASS])

    def test_generator_patterns_are_read_from_combined_configuration(self):
        combined = Config(name="fake", generator_branches=["new-generator/*"], protected_paths=["evals/**"])
        report, seen, _ = fake_batch(["owner/config", "new-generator/change"],
                                    {"owner/config": ["metallic.toml"], "new-generator/change": ["evals/fake.json"]},
                                    combined, base_cfg=Config(name="fake"))
        self.assertEqual(seen[0][0]["branch"], "new-generator/change")
        self.assertEqual(report["merged"], ["owner/config"])

    def test_unconfigured_generator_policy_stays_skipped(self):
        report, seen, _ = fake_batch(["owner/a", "star/gen-b"],
                                    {"owner/a": ["docs/a.md"], "star/gen-b": ["evals/fake.json"]}, Config(name="fake"))
        self.assertEqual(seen[0][1].status, checks.SKIP)
        self.assertEqual(report["batch"]["verdict"], "green")

    def test_single_branch_identity_is_unchanged(self):
        report, seen, _ = fake_batch(["star/gen-bad"], {"star/gen-bad": ["evals/fake.json"]}, self.cfg)
        self.assertIsNone(report["batch"])
        self.assertEqual(seen[0][0]["branch"], "star/gen-bad")
        self.assertEqual(report["merged"], [])

    def test_full_tree_fail_fast_options_and_input_names_are_preserved(self):
        names = ["star/gen-safe", "owner/docs"]
        original = names.copy()
        _, seen, cache = fake_batch(names, {names[0]: ["pkg/safe.py"], names[1]: ["docs/a.md"]}, self.cfg)
        self.assertEqual(names, original)
        for kwargs, _ in seen:
            self.assertTrue(kwargs["full"])
            self.assertTrue(kwargs["fail_fast"])
            self.assertEqual(kwargs["test_cache_scope"], "tree")
            self.assertIs(kwargs["cache"], cache)
        cache.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
