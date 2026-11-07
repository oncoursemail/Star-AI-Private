"""Offline developer checks for computer-driver recovery and bounded verification.

Run from any directory:
    python benchmarks/verify_computer_driver_recovery.py -v

To reproduce recovery failures against an inspected source snapshot:
    python benchmarks/verify_computer_driver_recovery.py --driver-source PATH RecoveryChecks -v

All input, windows, observations, logging, and elapsed time are safe in-memory fakes.
Only a temporary directory receives an enrollment file, using a synthetic GUID.
These checks exercise the actual Driver; they are not sealed evaluation results or
Windows performance measurements. The optional source path executes that local
Python module, as a normal developer test would; use only an inspected snapshot.
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from star.computer import identity
from star.computer import driver as driver_module
from star.computer.ground import GroundingChain, UiaFinder
from star.computer.hands import Stopped
from star.computer.limits import Limited
from star.computer.screen import Element, Screen


if "--driver-source" in sys.argv:
    _argument = sys.argv.index("--driver-source")
    if _argument + 1 >= len(sys.argv):
        raise SystemExit("--driver-source needs one inspected Python source path")
    _source = Path(sys.argv[_argument + 1]).resolve(strict=True)
    del sys.argv[_argument:_argument + 2]
    _spec = importlib.util.spec_from_file_location("star.computer._recovery_check_source", _source)
    if _spec is None or _spec.loader is None:
        raise SystemExit("cannot load the inspected driver source")
    driver_module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = driver_module
    _spec.loader.exec_module(driver_module)

Driver, Step, Expect = driver_module.Driver, driver_module.Step, driver_module.Expect


class SimClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []
        self.after_sleep = None

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise AssertionError("driver requested invalid sleep")
        self.sleeps.append(seconds)
        self.now += seconds
        if self.after_sleep is not None:
            self.after_sleep()


class FakeSwitch:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped


class FakeLog:
    def __init__(self):
        self.records = []

    def shot(self, image, label):
        return ""

    def step(self, **record):
        self.records.append(record)


class FakeLimits:
    def __init__(self):
        self.calls = 0
        self.fail_first = False

    def action(self):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise Limited("simulated rate delay before dispatch", 0.04)

    def message(self, recipient, text):
        raise AssertionError("these checks must not send or prepare messages")


class FakeHands:
    def __init__(self, computer):
        self.computer = computer
        self.events = []
        self._stopped = lambda: False

    def _emit(self, kind, **fields):
        self.events.append((kind, fields))
        if self.computer.on_action is not None:
            self.computer.on_action(kind, fields)

    def click(self, x, y, **fields):
        self._emit("click", x=x, y=y, **fields)

    def type_text(self, text):
        self._emit("type", text=text)

    def key(self, keys):
        self._emit("key", keys=keys)

    def scroll(self, amount, **fields):
        self._emit("scroll", amount=amount, **fields)

    def wait(self, amount):
        self._emit("wait", amount=amount)
        self.computer.sleep(amount)


class FakeWindows:
    def __init__(self, computer):
        self.computer = computer
        self.focus_calls = []

    def windows(self):
        return [SimpleNamespace(hwnd=41, title="Notes", exe="notes.exe")]

    def focus(self, hwnd):
        self.focus_calls.append(hwnd)
        return True


class FakeComputer:
    def __init__(self):
        self.cfg = {}
        self.clock = SimClock()
        self.sleep = self.clock.sleep
        self.hands = FakeHands(self)
        self.windows = FakeWindows(self)
        self.eye = None
        self.on_action = None
        self.view = None
        self.see_calls = 0
        self.see_times = []
        self.changed = False
        self.value = ""
        self.ready_at = None
        self.spinner = False
        self.ask_calls = []

    def see(self):
        self.see_calls += 1
        self.see_times.append(self.clock())
        if self.view is not None:
            return self.view()
        elements = [
            Element(1, "Apply", "button", (10, 10, 90, 40)),
            Element(2, "Alternate", "button", (100, 10, 190, 40)),
            Element(3, "Document", "edit", (10, 60, 300, 100), focused=True, value=self.value),
        ]
        if self.changed:
            elements.append(Element(4, "State changed", "text", (10, 120, 120, 140)))
        if self.ready_at is not None and self.clock() >= self.ready_at:
            elements.append(Element(5, "Ready", "text", (10, 160, 120, 180)))
        if self.spinner:
            elements.append(Element(6, "Working", "text", (10, 200, 120, 220)))
        return Screen(elements, window="Notes", process="notes.exe", hwnd=41,
                      size=(1920, 1080), taken=self.clock())

    @staticmethod
    def aim_point(element):
        return element.center

    def ask_owner(self, action, reason):
        self.ask_calls.append((action, reason))


class DriverCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="litha-driver-check-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.read_guid = lambda: "synthetic-offline-driver-check-guid"
        identity.enroll(self.home, self.read_guid)
        self.c = FakeComputer()
        self.switch = FakeSwitch()
        self.log = FakeLog()
        self.limits = FakeLimits()

    def make_driver(self, **options):
        defaults = dict(home=self.home, read_guid=self.read_guid,
                        switch=self.switch, log=self.log, limits=self.limits,
                        sleep=self.c.sleep, settle_s=0.2)
        defaults.update(options)
        return Driver(self.c, **defaults)

    def event_count(self, kind):
        return sum(name == kind for name, _ in self.c.hands.events)

    def assert_unknown(self, result):
        self.assertFalse(result.ok)
        self.assertRegex(result.detail.lower(), r"unknown|uncertain")
        self.assertTrue(result.outcome_uncertain)
        self.assertTrue(self.log.records[-1]["outcome_uncertain"])


class RecoveryChecks(DriverCase):
    def test_changed_pointer_action_does_not_try_alternative(self):
        for kind in ("click", "double", "right"):
            with self.subTest(kind=kind):
                self.c.changed = False
                self.c.hands.events.clear()
                self.c.on_action = lambda *_: setattr(self.c, "changed", True)
                result = self.make_driver().run(Step(
                    kind, target=("Apply", "Alternate"),
                    expect=Expect(text="Never appears"), retries=3))
                self.assertFalse(result.ok)
                self.assertEqual(self.event_count("click"), 1)
                self.assertEqual(result.attempts, 1)

    def test_changed_key_does_not_try_alternative(self):
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver().run(Step(
            "key", target=("first", "second"), keys="ctrl+s",
            expect=Expect(text="Never appears"), retries=3))
        self.assertFalse(result.ok)
        self.assertEqual(self.event_count("key"), 1)

    def test_partial_type_is_not_replayed_when_screen_signature_is_unchanged(self):
        before = self.c.see()

        def type_prefix(kind, fields):
            if kind == "type":
                self.c.value += fields["text"][:2]

        self.c.on_action = type_prefix
        result = self.make_driver().run(Step(
            "type", target=("Document", "Alternate"), text="hello",
            expect=Expect(text="hello"), retries=3))
        self.assertEqual(before.difference(self.c.see()), 0.0)
        self.assertFalse(result.ok)
        self.assertEqual(self.c.value, "he")
        self.assertEqual(self.event_count("type"), 1)

    def test_unverified_type_without_specific_expectation_is_not_replayed(self):
        result = self.make_driver().run(Step("type", text="hello", retries=3))
        self.assertFalse(result.ok)
        self.assertEqual(self.event_count("type"), 1)

    def test_postdispatch_exceptions_are_unknown_and_not_replayed(self):
        for error in (RuntimeError("lost reply"), ValueError("late invalid value"),
                      TypeError("late bad result"), Limited("late rate result", 0.01),
                      OSError("device reply unavailable"), KeyError("missing result field")):
            with self.subTest(error=type(error).__name__):
                self.c.hands.events.clear()

                def act_then_fail(*_):
                    self.c.value += "x"
                    raise error

                self.c.on_action = act_then_fail
                result = self.make_driver().run(Step("type", text="x", retries=3))
                self.assert_unknown(result)
                self.assertEqual(self.event_count("type"), 1)

    def test_predispatch_grounding_error_can_retry(self):
        underlying = GroundingChain([UiaFinder()])

        class FlakyChain:
            calls = 0

            def ground(inner, *args):
                inner.calls += 1
                if inner.calls == 1:
                    raise RuntimeError("grounder unavailable before input")
                return underlying.ground(*args)

        chain = FlakyChain()
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver(chain=chain).run(Step("click", target="Apply", retries=2))
        self.assertTrue(result.ok)
        self.assertEqual(chain.calls, 2)
        self.assertEqual(self.event_count("click"), 1)

    def test_missing_first_target_can_try_alternative_before_dispatch(self):
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver().run(Step("click", target=("Not present", "Apply"), retries=2))
        self.assertTrue(result.ok)
        self.assertEqual(self.event_count("click"), 1)
        self.assertEqual(result.attempts, 2)

    def test_predispatch_rate_limit_can_retry(self):
        self.limits.fail_first = True
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver().run(Step("click", target="Apply", retries=2))
        self.assertTrue(result.ok)
        self.assertEqual(self.limits.calls, 2)
        self.assertEqual(self.event_count("click"), 1)

    def test_postdispatch_observation_error_reports_unknown(self):
        original_see = self.c.see

        def failing_see():
            if self.c.hands.events:
                raise RuntimeError("capture unavailable after input")
            return original_see()

        self.c.see = failing_see
        result = self.make_driver().run(Step("click", target="Apply", retries=2))
        self.assert_unknown(result)
        self.assertEqual(self.event_count("click"), 1)

    def test_postdispatch_exception_payload_is_not_copied_to_result_or_log(self):
        sentinel = "synthetic-private-backend-error-payload"

        def failing_input(*_):
            raise OSError(sentinel)

        self.c.on_action = failing_input
        result = self.make_driver().run(Step("type", text="hello", retries=2))
        self.assert_unknown(result)
        self.assertIn("OSError", result.detail)
        self.assertNotIn(sentinel, result.detail)
        self.assertNotIn(sentinel, repr(self.log.records))
        self.assertEqual(self.event_count("type"), 1)

    def test_postdispatch_verifier_error_reports_unknown(self):
        driver = self.make_driver()

        def failing_verify(*args, **kwargs):
            raise ValueError("verification cannot read the result")

        driver.verify = failing_verify
        result = driver.run(Step("click", target="Apply", retries=2))
        self.assert_unknown(result)
        self.assertEqual(self.event_count("click"), 1)

    def test_run_all_stops_after_unverified_typing(self):
        ok, results = self.make_driver().run_all([
            Step("type", text="hello", retries=2),
            Step("key", keys="enter"),
        ])
        self.assertFalse(ok)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.event_count("type"), 1)
        self.assertEqual(self.event_count("key"), 0)

    def test_stop_before_dispatch_touches_no_input(self):
        self.switch.stopped = True
        with self.assertRaises(Stopped):
            self.make_driver().run(Step("click", target="Apply"))
        self.assertEqual(self.c.hands.events, [])

    def test_stop_during_postdispatch_capture_is_propagated(self):
        original_see = self.c.see

        def stopping_see():
            if self.c.hands.events:
                self.switch.stopped = True
            return original_see()

        self.c.see = stopping_see
        with self.assertRaises(Stopped):
            self.make_driver().run(Step("click", target="Apply", retries=2))
        self.assertEqual(self.event_count("click"), 1)

    def test_stop_during_initial_capture_blocks_non_hands_dispatch(self):
        original_see = self.c.see

        def stopping_see():
            self.switch.stopped = True
            return original_see()

        self.c.see = stopping_see
        with self.assertRaises(Stopped):
            self.make_driver().run(Step("focus", target="Notes", retries=2))
        self.assertEqual(self.c.windows.focus_calls, [])

    def test_stop_during_grounding_blocks_dispatch(self):
        underlying = GroundingChain([UiaFinder()])
        switch = self.switch

        class StoppingChain:
            def ground(inner, *args):
                result = underlying.ground(*args)
                switch.stopped = True
                return result

        with self.assertRaises(Stopped):
            self.make_driver(chain=StoppingChain()).run(Step("click", target="Apply", retries=2))
        self.assertEqual(self.c.hands.events, [])

    def test_stop_during_final_log_blocks_recovery_focus(self):
        original_log_step = self.log.step

        def stopping_log(**record):
            original_log_step(**record)
            self.switch.stopped = True

        self.log.step = stopping_log
        with self.assertRaises(Stopped):
            self.make_driver().run(Step("wait", amount=0, expect=Expect(text="Ready"), retries=2))
        self.assertEqual(self.event_count("wait"), 1)
        self.assertEqual(self.c.windows.focus_calls, [])

    def test_stop_during_verification_is_propagated(self):
        driver = self.make_driver()
        original_verify = driver.verify

        def stopping_verify(*args, **kwargs):
            self.switch.stopped = True
            return original_verify(*args, **kwargs)

        driver.verify = stopping_verify
        with self.assertRaises(Stopped):
            driver.run(Step("click", target="Apply", retries=2))
        self.assertEqual(self.event_count("click"), 1)

    def test_stop_raised_by_input_handler_is_not_swallowed(self):
        def stop_input(*_):
            raise Stopped("input interrupted")

        self.c.on_action = stop_input
        with self.assertRaises(Stopped):
            self.make_driver().run(Step("type", text="hello", retries=2))
        self.assertEqual(self.event_count("type"), 1)

    def test_unexpected_predispatch_error_preserves_failure(self):
        class BrokenChain:
            def ground(inner, *args):
                raise OSError("grounder local transport failed")

        with self.assertRaises(OSError):
            self.make_driver(chain=BrokenChain()).run(Step("click", target="Apply", retries=2))
        self.assertEqual(self.c.hands.events, [])

    def test_success_receipt_is_not_marked_uncertain(self):
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver().run(Step("click", target="Apply", retries=0))
        self.assertTrue(result.ok)
        self.assertFalse(result.outcome_uncertain)
        self.assertFalse(self.log.records[-1]["outcome_uncertain"])


class AdaptivePollingChecks(DriverCase):
    def test_default_keeps_fixed_settle(self):
        self.c.on_action = lambda *_: setattr(self.c, "ready_at", 0.04)
        result = self.make_driver().run(Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)
        self.assertEqual(self.c.see_calls, 2)

    def test_positive_transition_finishes_before_fixed_settle(self):
        self.c.on_action = lambda *_: setattr(self.c, "ready_at", 0.04)
        result = self.make_driver(verification_poll_s=0.01).run(
            Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertTrue(result.ok)
        self.assertGreaterEqual(self.c.clock(), 0.04)
        self.assertLess(self.c.clock(), 0.2)
        self.assertEqual(self.event_count("click"), 1)

    def test_config_can_enable_polling(self):
        self.c.cfg["verification_poll_s"] = 0.01
        self.c.on_action = lambda *_: setattr(self.c, "ready_at", 0.04)
        result = self.make_driver().run(Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertTrue(result.ok)
        self.assertLess(self.c.clock(), 0.2)

    def test_explicit_zero_disables_configured_polling(self):
        self.c.cfg["verification_poll_s"] = 0.01
        self.c.on_action = lambda *_: setattr(self.c, "ready_at", 0.04)
        result = self.make_driver(verification_poll_s=0).run(
            Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)

    def test_preexisting_positive_expectation_keeps_fixed_wait(self):
        self.c.ready_at = 0.0
        result = self.make_driver(verification_poll_s=0.01).run(
            Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)
        self.assertEqual(self.c.see_calls, 2)

    def test_negative_expectation_keeps_fixed_wait(self):
        self.c.spinner = True
        self.c.on_action = lambda *_: setattr(self.c, "spinner", False)
        result = self.make_driver(verification_poll_s=0.01).run(
            Step("click", target="Apply", expect=Expect(gone="Working"), retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)

    def test_closed_window_expectation_keeps_fixed_wait(self):
        result = self.make_driver(verification_poll_s=0.01).run(
            Step("click", target="Apply", expect=Expect(window_closed="Absent window"), retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)

    def test_mixed_positive_and_negative_expectation_keeps_fixed_wait(self):
        self.c.spinner = True

        def complete(*_):
            self.c.spinner = False
            self.c.ready_at = 0.04

        self.c.on_action = complete
        result = self.make_driver(verification_poll_s=0.01).run(Step(
            "click", target="Apply", expect=Expect(text="Ready", gone="Working"), retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)

    def test_generic_change_expectation_keeps_fixed_wait(self):
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver(verification_poll_s=0.01).run(Step("click", target="Apply", retries=0))
        self.assertTrue(result.ok)
        self.assertAlmostEqual(self.c.clock(), 0.2)

    def test_missing_predicate_is_bounded_without_extra_input(self):
        result = self.make_driver(verification_poll_s=0.01).run(
            Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertFalse(result.ok)
        self.assertLessEqual(self.c.clock(), 0.2 + 1e-9)
        self.assertLessEqual(self.c.see_calls, 34)
        self.assertEqual(self.event_count("click"), 1)

    def test_sampling_count_is_bounded_for_large_wait_budget(self):
        result = self.make_driver(verification_poll_s=0.01, settle_s=10).run(
            Step("click", target="Apply", expect=Expect(text="Ready"), retries=0))
        self.assertFalse(result.ok)
        self.assertLessEqual(self.c.clock(), 10 + 1e-9)
        self.assertLessEqual(self.c.see_calls, 34)
        self.assertEqual(self.event_count("click"), 1)

    def test_stop_interrupts_polling(self):
        self.c.clock.after_sleep = lambda: setattr(self.switch, "stopped", self.c.clock() >= 0.03)
        with self.assertRaises(Stopped):
            self.make_driver(verification_poll_s=0.01).run(
                Step("click", target="Apply", expect=Expect(text="Ready"), retries=2))
        self.assertLess(self.c.clock(), 0.2)
        self.assertEqual(self.event_count("click"), 1)

    def test_polling_respects_all_positive_predicates(self):
        self.c.on_action = lambda *_: setattr(self.c, "ready_at", 0.04)
        result = self.make_driver(verification_poll_s=0.01).run(Step(
            "click", target="Apply", expect=Expect(text="Ready", focused="nonexistent control"), retries=0))
        self.assertFalse(result.ok)
        self.assertGreaterEqual(self.c.clock(), 0.2)
        self.assertEqual(self.event_count("click"), 1)

    def test_invalid_poll_intervals_are_rejected(self):
        for invalid in (True, False, "0.1", -0.1, 0.001, 1.01, float("nan"), float("inf")):
            with self.subTest(value=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.make_driver(verification_poll_s=invalid)

    def test_valid_poll_boundaries_and_zero(self):
        for valid in (0, 0.01, 1.0):
            with self.subTest(value=valid):
                self.make_driver(verification_poll_s=valid)

    def test_invalid_configured_interval_is_rejected(self):
        self.c.cfg["verification_poll_s"] = 0.001
        with self.assertRaises(ValueError):
            self.make_driver()


class WaitValidationChecks(DriverCase):
    def test_invalid_settle_values_are_rejected_before_input(self):
        for invalid in (True, False, "0.2", -0.01, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.make_driver(settle_s=invalid)
        self.assertEqual(self.c.hands.events, [])

    def test_invalid_configured_settle_value_is_rejected(self):
        self.c.cfg["settle_s"] = float("nan")
        with self.assertRaises(ValueError):
            self.make_driver(settle_s=None)
        self.assertEqual(self.c.hands.events, [])

    def test_zero_settle_is_valid_and_does_not_schedule_wait(self):
        self.c.on_action = lambda *_: setattr(self.c, "changed", True)
        result = self.make_driver(settle_s=0).run(Step("click", target="Apply", retries=0))
        self.assertTrue(result.ok)
        self.assertEqual(self.c.clock.sleeps, [])

    def test_internal_wait_rejects_invalid_duration(self):
        driver = self.make_driver()
        for invalid in (True, False, "0.2", -0.01, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    driver._sleep_checked(invalid)
        self.assertEqual(self.c.clock.sleeps, [])

    def test_internal_wait_rejects_nonfinite_deadline(self):
        driver = self.make_driver()
        self.c.clock.now = 1e308
        with self.assertRaises(ValueError):
            driver._sleep_checked(1e308)
        self.assertEqual(self.c.clock.sleeps, [])

    def test_internal_wait_rejects_clock_becoming_nonfinite(self):
        for invalid in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=invalid):
                driver = self.make_driver()
                driver.clock = iter((0.0, invalid)).__next__
                with self.assertRaises(ValueError):
                    driver._sleep_checked(0.2)
        self.assertEqual(self.c.clock.sleeps, [])


if __name__ == "__main__":
    unittest.main()
