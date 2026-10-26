"""Independent Home brain admission probes; fake tools and temporary owner controls only."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Callable
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home import brain, control  # noqa: E402
from star.home.host import Executor, Result  # noqa: E402


def call(tool_name, **arguments):
    return {"id": tool_name, "function": {"name": tool_name, "arguments": json.dumps(arguments)}}


class FakeLife:
    def __init__(self):
        self.writes = []

    def interests(self):
        return {"research": {"weight": 1.0}}

    def set_interest(self, **arguments):
        self.writes.append(("set_interest", arguments))
        return arguments

    def set_goal(self, **arguments):
        self.writes.append(("set_goal", arguments))
        return arguments


class FakeExecutor(Executor):
    def __init__(self, root):
        super().__init__(root / "home", backend=SimpleNamespace())
        self.actions = []
        self.outcome_ok: object = True
        self.after_action: Callable[[], object] = lambda: None

    def do(self, action: str, args: dict | None = None) -> Result:
        self.actions.append((action, args))
        self.after_action()
        result = Result(False, "fixture tool outcome")
        setattr(result, "ok", self.outcome_ok)  # Deliberately malformed adapter result for the trust-boundary probe.
        return result


class BrainReviewChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.executor = FakeExecutor(Path(self.temp.name))
        self.life = FakeLife()
        self.now = 100.0

    def run_session(self, chat, **kwargs):
        return brain.run_session(chat, self.executor, self.life, interest="research", brief="fixture", goal=None,
                                 max_steps=6, session_minutes=1, clock=lambda: self.now, **kwargs)

    @staticmethod
    def scripted(*batches):
        queue = iter(batches)
        return lambda *_: {"tool_calls": next(queue, [call("finish", summary="fixture", success=False)])}

    def test_string_finish_flags_never_claim_success(self):
        chat = self.scripted([call("click", x=1, y=1)],
                             [call("finish", summary="fixture", success="false", goal_done="true")])
        outcome = self.run_session(chat)
        self.assertIs(outcome["ok"], False)
        self.assertIs(outcome["verified"], False)
        self.assertIs(outcome["goal_done"], False)

    def test_truthy_nonboolean_tool_outcome_is_not_success_evidence(self):
        self.executor.outcome_ok = "false"
        chat = self.scripted([call("click", x=1, y=1)], [call("finish", summary="fixture", success=True)])
        self.assertIs(self.run_session(chat)["verified"], False)

    def test_owner_stop_created_during_chat_prevents_all_batch_actions(self):
        def chat(*_):
            control.stop(self.executor.home)
            return {"tool_calls": [call("click", x=1, y=1), call("set_interest", name="music", weight=2)]}

        outcome = self.run_session(chat)
        self.assertIs(outcome["verified"], False)
        self.assertEqual(self.executor.actions, [])
        self.assertEqual(self.life.writes, [])

    def test_deadline_after_chat_prevents_all_batch_actions(self):
        def chat(*_):
            self.now += 61
            return {"tool_calls": [call("click", x=1, y=1)]}

        self.assertIs(self.run_session(chat)["verified"], False)
        self.assertEqual(self.executor.actions, [])

    def test_midbatch_stop_prevents_life_write_and_finish(self):
        self.executor.after_action = lambda: control.stop(self.executor.home)
        chat = self.scripted([call("click", x=1, y=1), call("set_interest", name="music", weight=2),
                              call("finish", summary="fixture", success=True, goal_done=True)])
        outcome = self.run_session(chat)
        self.assertEqual(len(self.executor.actions), 1)
        self.assertEqual(self.life.writes, [])
        self.assertIs(outcome["verified"], False)
        self.assertIs(outcome["goal_done"], False)

    def test_direct_model_goal_completion_never_writes_done(self):
        chat = self.scripted([call("set_goal", goal_id="fixture-goal", status="done")],
                             [call("finish", summary="fixture", success=False)])
        self.run_session(chat)
        self.assertEqual(self.life.writes, [])

    def test_malformed_batches_are_bounded_without_tool_execution(self):
        for batch in ("bad", [None], [{"function": None}], [{"function": {"name": [], "arguments": "{}"}}]):
            with self.subTest(batch=batch):
                outcome = self.run_session(lambda *_: {"tool_calls": batch})
                self.assertLessEqual(outcome["steps"], 6)
                self.assertIs(outcome["verified"], False)
                self.assertEqual(self.executor.actions, [])

    def test_failing_stop_predicate_fails_closed_before_chat(self):
        heard = []

        def stop():
            raise RuntimeError("fixture stop predicate unavailable")

        def chat(*_):
            heard.append(True)
            return {"tool_calls": [call("finish", summary="fixture", success=True)]}

        self.assertIs(self.run_session(chat, stop=stop)["verified"], False)
        self.assertEqual(heard, [])

    def test_host_exception_is_unknown_and_never_automatically_retried(self):
        def uncertain():
            raise OSError("fixture action may already have happened")

        self.executor.after_action = uncertain
        outcome = self.run_session(self.scripted([call("click", x=1, y=1)]))
        self.assertEqual(len(self.executor.actions), 1)
        self.assertIs(outcome["verified"], False)
        self.assertIn("unknown", outcome["summary"])
        self.assertIn("no automatic retry", outcome["summary"])

    def test_malformed_host_result_fails_closed_without_crashing(self):
        with patch.object(self.executor, "do", return_value=None):
            outcome = self.run_session(self.scripted([call("click", x=1, y=1)]))
        self.assertIs(outcome["verified"], False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
