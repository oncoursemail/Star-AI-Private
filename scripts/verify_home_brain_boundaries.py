"""Home tool sessions on temporary files and scripted replies; no model or device calls."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home import brain, control
from star.home.host import Executor
from star.home.life import Life


def call(tool, **args):
    return {"id": tool, "function": {"name": tool, "arguments": json.dumps(args)}}


class Checks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="star-brain-boundaries-")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "home"
        self.ex = Executor(self.home)
        self.life = Life(self.home)
        self.file = self.ex.workspace / "drawing.txt"
        self.now = 1.0

    def run_session(self, messages=None, *, chat=None, **kwargs):
        queue = list(messages or [])
        def scripted(*_):
            return queue.pop(0)
        return brain.run_session(chat or scripted, self.ex, self.life,
            interest="drawing", brief="temporary test", goal=None, clock=lambda: self.now, **kwargs)

    def batch(self, *calls):
        return {"tool_calls": list(calls)}

    def finish(self, **extra):
        return call("finish", **{"summary": "done", "success": True, **extra})

    def write(self):
        return call("write_file", path=str(self.file), text="temporary test")

    def test_invalid_finish_can_recover_without_repeating_the_action(self):
        result = self.run_session([self.batch(self.write()), self.batch(self.finish(success="false")),
                                   self.batch(self.finish(artifacts=[str(self.file)]))])
        self.assertTrue(result["verified"])
        self.assertTrue(result["failures"])
        self.assertEqual(self.file.read_text(), "temporary test")

    def test_goal_completion_requires_verified_finish_and_selected_goal_record(self):
        goal = self.life.add_goal("drawing", "make a temporary drawing")
        result = self.run_session([self.batch(call("set_goal", goal_id=goal["id"], status="done")),
            self.batch(self.write()), self.batch(self.finish(goal_done=True, artifacts=[str(self.file)]))])
        self.assertTrue(result["verified"] and result["goal_done"])
        self.assertEqual(next(g for g in self.life.goals() if g["id"] == goal["id"])["status"], "open")
        self.life.record("drawing", "drawing", result, goal)
        self.assertEqual(next(g for g in self.life.goals("done") if g["id"] == goal["id"])["status"], "done")

    def test_malformed_finish_never_claims_success(self):
        for extra in ({"success": "false"}, {"success": 1}, {"goal_done": "false"},
                      {"artifacts": "file"}, {"artifacts": [1]}, {"artifacts": ["x"] * 11},
                      {"artifacts": ["bad\0name"]}, {"summary": "bad\ud800"}, {"extra": True}):
            with self.subTest(extra=repr(extra)):
                result = self.run_session([self.batch(self.finish(**extra))], max_steps=1)
                self.assertFalse(result["ok"] or result["verified"] or result["goal_done"])

    def test_no_action_and_preview_cannot_complete_a_goal(self):
        result = self.run_session([self.batch(self.finish(goal_done=True))])
        self.assertFalse(result["verified"] or result["goal_done"])
        self.ex.dry_run = True
        result = self.run_session([self.batch(self.write()), self.batch(self.finish(goal_done=True))])
        self.assertFalse(self.file.exists() or result["verified"] or result["goal_done"])

    def test_owner_stop_inside_chat_prevents_lifecycle_and_finish(self):
        def chat(*_):
            control.stop(self.home)
            return self.batch(call("set_interest", name="music", weight=4), self.finish())
        before = self.life.interests()
        result = self.run_session(chat=chat)
        self.assertFalse(result["ok"] or result["verified"])
        self.assertNotIn("paused", result)
        self.assertEqual(self.life.interests(), before)

    def test_stop_after_first_action_prevents_remaining_batch(self):
        original = self.ex.do
        def do(*args):
            result = original(*args)
            control.stop(self.home)
            return result
        before = self.life.interests()
        with patch.object(self.ex, "do", side_effect=do):
            result = self.run_session([self.batch(self.write(), call("set_interest", name="music", weight=4), self.finish())])
        self.assertTrue(self.file.exists())
        self.assertFalse(result["verified"])
        self.assertEqual(self.life.interests(), before)

    def test_deadline_after_model_return_prevents_all_calls(self):
        def chat(*_):
            self.now = 1000.0
            return self.batch(self.write(), self.finish())
        result = self.run_session(chat=chat, session_minutes=1)
        self.assertFalse(self.file.exists() or result["verified"])

    def test_failed_stop_predicate_fails_closed_before_model(self):
        def fail():
            raise RuntimeError("unavailable")
        with patch.object(brain, "tool_defs", wraps=brain.tool_defs):
            result = self.run_session(chat=lambda *_: self.fail("model called"), stop=fail)
        self.assertFalse(result["ok"] or self.file.exists())

    def test_provider_error_does_not_replay_completed_action(self):
        count = 0
        def chat(*_):
            nonlocal count
            count += 1
            if count == 1:
                return self.batch(self.write())
            raise ConnectionError("temporary failure")
        result = self.run_session(chat=chat)
        self.assertEqual(count, 2)
        self.assertTrue(self.file.exists())
        self.assertFalse(result["verified"])

    def test_action_that_raises_after_effect_is_unknown_not_retried(self):
        original = self.ex.do
        def do(*args):
            original(*args)
            raise OSError("receipt could not be written")
        with patch.object(self.ex, "do", side_effect=do) as operation:
            result = self.run_session([self.batch(self.write(), self.finish())])
        self.assertEqual(operation.call_count, 1)
        self.assertTrue(self.file.exists())
        self.assertFalse(result["verified"])
        self.assertIn("unknown", result["summary"])

    def test_malformed_host_results_return_structured_unknown_outcome(self):
        for value in (None, SimpleNamespace(ok="false", text="ok"), SimpleNamespace(ok=True, text=None),
                      SimpleNamespace(ok=True, text="bad\ud800")):
            with self.subTest(value=repr(value)), patch.object(self.ex, "do", return_value=value):
                result = self.run_session([self.batch(self.write(), self.finish())])
                self.assertFalse(result["verified"])
                self.assertTrue(result["failures"])

    def test_protected_and_network_artifacts_are_not_read_as_evidence(self):
        protected = self.home / "owner.txt"
        protected.write_text("temporary owner control")
        self.assertFalse(brain._artifact_ok(self.ex, str(protected)))
        with patch.object(self.ex, "_check_path", side_effect=AssertionError("network path resolved")):
            self.assertFalse(brain._artifact_ok(self.ex, r"\\example.invalid\share\file"))

    def test_each_batch_obeys_the_step_limit(self):
        result = self.run_session([self.batch(*[call("add_goal", interest="drawing", text=str(i)) for i in range(8)])], max_steps=2)
        self.assertEqual(result["steps"], 2)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
