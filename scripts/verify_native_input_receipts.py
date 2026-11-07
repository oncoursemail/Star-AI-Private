"""Offline native-input failure injection. Never loads user32 or sends desktop input."""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import sys
import threading
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.computer.hands import Hands, Stopped  # noqa: E402
from star.computer.winapi import DesktopSink  # noqa: E402
from star.home import plugins  # noqa: E402
from star.play.humanlike import Actuator, Event, RecordingSink  # noqa: E402
from star.play.loop import GameSession  # noqa: E402
from star.play.winput import INPUT, INPUT_KEYBOARD, InputDeliveryError, SendInputSink  # noqa: E402


class Clock:
    now = 10.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Native:
    """Scripted native replies; any unexpected call fails instead of reaching Windows."""

    def __init__(self, replies=(), *, cursor=True):
        self.replies = list(replies)
        self.calls = []
        self.cursor = cursor
        self.cursor_calls = []
        self.after = lambda: None

    def SendInput(self, count, ptr, size):
        assert count == 1 and size == ctypes.sizeof(INPUT)
        inp = ctypes.cast(ptr, ctypes.POINTER(INPUT)).contents
        self.calls.append((inp.type, inp.u.ki.wScan, inp.u.ki.dwFlags) if inp.type == INPUT_KEYBOARD
                          else (inp.type, inp.u.mi.dx, inp.u.mi.dwFlags))
        assert self.replies, "unexpected native call / replay"
        reply = self.replies.pop(0)
        self.after()
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def MapVirtualKeyW(self, vk, mode):
        return vk

    def GetSystemMetrics(self, index):
        return {76: 0, 77: 0, 78: 1920, 79: 1080}[index]

    def SetCursorPos(self, x, y):
        self.cursor_calls.append((x, y))
        return self.cursor


def sink_for(kind, replies=(), *, guard=lambda: True, cursor=True):
    sink = object.__new__(kind)  # Constructors would load the actual desktop API.
    sink.guard = guard
    sink.dropped = sink.accepted_events = sink.failed_events = sink.confirmed_moves = 0
    api = Native(replies, cursor=cursor)
    sink.u = sink._user32 = api
    sink.position = lambda: (100, 100)
    return sink, api


def session_for(actuator):
    fast = SimpleNamespace(ticks=3, overruns=0, goal=SimpleNamespace(name="explore"),
                           stats=SimpleNamespace(summary=lambda: {}), stop=lambda: None)
    return GameSession(cast(Any, fast), actuator=actuator)


class ReceiptChecks(unittest.TestCase):
    def test_accepted_receipts_both_sinks(self):
        for kind in (DesktopSink, SendInputSink):
            with self.subTest(kind=kind):
                sink, api = sink_for(kind, [1, 1])
                sink.key("a", True)
                sink.key("a", False)
                self.assertEqual((sink.accepted_events, sink.failed_events, sink.dropped), (2, 0, 0))
                self.assertEqual(len(api.calls), 2)

    def test_zero_receipt_not_retried_both_sinks(self):
        for kind in (DesktopSink, SendInputSink):
            sink, api = sink_for(kind, [0])
            with self.assertRaises(InputDeliveryError) as caught:
                sink.move_rel(2, 3)
            self.assertEqual(caught.exception.accepted, 0)
            self.assertEqual((len(api.calls), sink.failed_events, sink.accepted_events), (1, 1, 0))

    def test_invalid_receipt_types_and_counts_fail_closed(self):
        for kind in (DesktopSink, SendInputSink):
            for reply in (None, True, "1", -1, 2):
                with self.subTest(kind=kind, reply=reply):
                    sink, api = sink_for(kind, [reply])
                    with self.assertRaises(InputDeliveryError) as caught:
                        sink.key("a", True)
                    self.assertIsNone(caught.exception.accepted)
                    self.assertEqual(len(api.calls), 1)

    def test_native_exception_sanitized(self):
        for kind in (DesktopSink, SendInputSink):
            sink, _ = sink_for(kind, [OSError("private native diagnostic")])
            with self.assertRaises(InputDeliveryError) as caught:
                sink.button("left", True)
            self.assertNotIn("private", str(caught.exception))
            self.assertEqual(sink.failed_events, 1)

    def test_guard_refusal_never_calls_native(self):
        for kind in (DesktopSink, SendInputSink):
            sink, api = sink_for(kind, guard=lambda: False)
            with self.assertRaises(InputDeliveryError) as caught:
                sink.key("a", True)
            self.assertEqual(caught.exception.accepted, 0)
            self.assertEqual(api.calls, [])
            self.assertEqual(sink.failed_events, 0)

    def test_cursor_placement_failure_and_success(self):
        sink, api = sink_for(SendInputSink, cursor=False)
        with self.assertRaises(InputDeliveryError):
            sink.move_to(5, 8)
        self.assertEqual((sink.failed_events, sink.confirmed_moves), (1, 0))
        api.cursor = True
        sink.move_to(6, 9)
        self.assertEqual(sink.confirmed_moves, 1)
        sink.guard = lambda: False
        with self.assertRaises(InputDeliveryError):
            sink.move_to(7, 10)
        self.assertEqual(api.cursor_calls, [(5, 8), (6, 9)])

    def test_unicode_rejected_down_does_not_release_foreign_key(self):
        sink, api = sink_for(DesktopSink, [0])
        with self.assertRaises(InputDeliveryError):
            sink.type_char("a")
        self.assertEqual(len(api.calls), 1)

    def test_unicode_partial_pair_not_replayed(self):
        sink, api = sink_for(DesktopSink, [1, 0])
        with self.assertRaises(InputDeliveryError):
            sink.type_char("a")
        self.assertEqual([row[2] for row in api.calls], [4, 6])

    def test_unicode_unknown_down_attempts_only_cleanup(self):
        sink, api = sink_for(DesktopSink, [OSError("unknown"), 1])
        with self.assertRaises(InputDeliveryError):
            sink.type_char("a")
        self.assertEqual([row[2] for row in api.calls], [4, 6])

    def test_text_prefix_failure_stops_remaining_characters(self):
        sink, api = sink_for(DesktopSink, [1, 1, 0])
        clock = Clock()
        hands = Hands(sink, clock=clock, sleep=clock.sleep)
        with self.assertRaises(InputDeliveryError):
            hands.type_text("abc")
        self.assertEqual([row[1] for row in api.calls], [ord("a"), ord("a"), ord("b")])
        self.assertEqual(hands.actions, 0)

    def test_owned_up_only_after_focus_change(self):
        for kind in (DesktopSink, SendInputSink):
            sink, api = sink_for(kind, [1, 1, 1, 1])
            sink.key("ctrl", True)
            sink.button("left", True)
            sink.guard = lambda: False
            with self.assertRaises(InputDeliveryError):
                sink.key("a", True)
            sink.release_key("ctrl")
            sink.release_button("left")
            self.assertEqual([row[2] for row in api.calls], [8, 2, 10, 4])

    def test_actuator_failure_stops_and_discards_future_plans(self):
        sink, api = sink_for(DesktopSink, [0])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "move_rel", 1, 1), Event(10, "key_down", "a")])
        with self.assertRaises(InputDeliveryError):
            actor.pump()
        actor.submit([Event(10, "key_down", "b")])
        self.assertEqual(actor.pump(), 0)
        self.assertEqual((actor.attempted, actor.fired, actor.failures), (1, 0, 1))
        self.assertEqual(len(api.calls), 1)

    def test_rejected_press_is_not_owned(self):
        sink, api = sink_for(DesktopSink, [0])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "a")])
        with self.assertRaises(InputDeliveryError):
            actor.pump()
        actor.release_all()
        self.assertFalse(actor.held())
        self.assertEqual(len(api.calls), 1)

    def test_partial_plan_releases_only_successful_press(self):
        sink, api = sink_for(DesktopSink, [1, 0, 1])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl"), Event(10, "move_rel", 1, 1)])
        with self.assertRaises(InputDeliveryError):
            actor.pump()
        sink.guard = lambda: False
        actor.release_all()
        self.assertFalse(actor.held())
        self.assertEqual([row[2] for row in api.calls], [8, 1, 10])

    def test_cleanup_attempts_other_releases_after_one_fails(self):
        sink, api = sink_for(DesktopSink, [1, 1, 0, 1])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl"), Event(10, "button_down", "left")])
        actor.pump()
        with self.assertRaises(InputDeliveryError):
            actor.release_all()
        self.assertEqual(actor.held(), {"ctrl"})
        self.assertFalse(actor._buttons)
        self.assertEqual(len(api.calls), 4)

    def test_run_failure_finally_releases_owned_key(self):
        sink, api = sink_for(DesktopSink, [1, 0, 1])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl"), Event(10, "move_rel", 1, 1)])
        actor.run()
        self.assertFalse(actor.held())
        self.assertEqual((actor.failures, len(api.calls)), (1, 3))

    def test_stop_during_due_batch_prevents_next_down(self):
        sink, api = sink_for(DesktopSink, [1, 1])
        actor = Actuator(sink, clock=Clock())
        api.after = actor.stop
        actor.submit([Event(10, "key_down", "ctrl"), Event(10, "key_down", "a")])
        actor.pump()
        actor.release_all()
        self.assertEqual([row[1] for row in api.calls], [17, 17])

    def test_per_event_lag_counts_previous_native_delay(self):
        clock = Clock()
        sink, api = sink_for(DesktopSink, [1, 1])
        api.after = lambda: clock.sleep(0.07)
        actor = Actuator(sink, clock=clock)
        actor.submit([Event(10, "move_rel", 1, 1), Event(10, "move_rel", 2, 2)])
        actor.pump()
        self.assertAlmostEqual(actor.first_fire_lag[0], 0)
        self.assertAlmostEqual(actor.first_fire_lag[1], 0.07)

    def test_legacy_none_return_sink_has_no_invented_native_receipt(self):
        actor = Actuator(RecordingSink(), clock=Clock())
        actor.submit([Event(10, "move_rel", 1, 1)])
        actor.pump()
        receipt = session_for(actor).report()["input_delivery"]
        self.assertEqual(receipt["sink_calls_completed"], 1)
        self.assertIsNone(receipt["native_accepted_events"])

    def test_hands_failure_logs_error_not_done(self):
        with TemporaryDirectory() as tmp:
            sink, _ = sink_for(DesktopSink, [0])
            clock = Clock()
            hands = Hands(sink, home=Path(tmp), clock=clock, sleep=clock.sleep)
            with self.assertRaises(InputDeliveryError):
                hands.key("a")
            rows = [json.loads(line) for line in (Path(tmp) / "actions.jsonl").read_text().splitlines()]
            self.assertEqual([row["phase"] for row in rows], ["start", "error"])

    def test_hands_modifier_released_after_main_key_refusal(self):
        sink, api = sink_for(DesktopSink, [1, 0, 1])
        clock = Clock()
        hands = Hands(sink, clock=clock, sleep=clock.sleep)
        with self.assertRaises(InputDeliveryError):
            hands.key("ctrl+a")
        self.assertEqual([(row[1], row[2]) for row in api.calls], [(17, 8), (65, 8), (17, 10)])

    def test_hands_focus_loss_preserves_only_owned_cleanup(self):
        sink, api = sink_for(DesktopSink, [1, 1])
        api.after = lambda: setattr(sink, "guard", lambda: False)
        clock = Clock()
        hands = Hands(sink, clock=clock, sleep=clock.sleep)
        with self.assertRaises(InputDeliveryError):
            hands.key("ctrl+a")
        self.assertEqual([(row[1], row[2]) for row in api.calls], [(17, 8), (17, 10)])

    def test_hands_interruption_still_releases_modifier(self):
        sink, api = sink_for(DesktopSink, [1, 1])
        clock = Clock()

        def interrupted_sleep(seconds):
            clock.sleep(seconds)
            if len(api.calls) == 1:
                raise KeyboardInterrupt()

        hands = Hands(sink, clock=clock, sleep=interrupted_sleep)
        with self.assertRaises(KeyboardInterrupt):
            hands.key("ctrl+a")
        self.assertEqual([(row[1], row[2]) for row in api.calls], [(17, 8), (17, 10)])

    def test_hands_stop_releases_drag_button(self):
        sink, api = sink_for(DesktopSink, [1, 1])
        clock = Clock()
        hands = Hands(sink, clock=clock, sleep=clock.sleep, stopped=lambda: len(api.calls) == 1)
        with self.assertRaises(Stopped):
            hands._play([Event(10, "button_down", "left"), Event(20, "button_up", "left")])
        self.assertEqual([row[2] for row in api.calls], [2, 4])

    def test_session_receipt_forces_unverified_home_outcome(self):
        sink, _ = sink_for(DesktopSink, [1, 0, 1])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl"), Event(10, "move_rel", 1, 1)])
        actor.run()
        session = session_for(actor)
        session.stop()
        out = {"ok": True, "verified": True, "paused": True, "summary": "explored", "failures": []}
        plugins._record_input_delivery(out, session)
        self.assertFalse(out["ok"])
        self.assertFalse(out["verified"])
        self.assertFalse(out["paused"])
        self.assertEqual(out["input_delivery"]["native_accepted_events"], 2)
        called = []
        result = plugins._session_step(session, lambda: called.append(True))
        assert result is not None
        self.assertFalse(result.ok)
        self.assertFalse(called)

    def test_session_retains_stalled_worker_and_refuses_cleanup_success(self):
        actor = Actuator(RecordingSink(), clock=Clock())
        session = session_for(actor)
        worker = SimpleNamespace(join=lambda timeout: None, is_alive=lambda: True)
        session._threads = [cast(Any, worker)]
        with self.assertRaisesRegex(RuntimeError, "shutdown is incomplete"):
            session.stop(timeout=0)
        self.assertEqual(session._threads, [worker])

    def test_interrupted_os_thread_start_retains_ownership_until_down_finishes(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        sink, api = sink_for(DesktopSink, [1, 1])

        def during_native_call():
            entered.set()
            assert release.wait(2), "fixture native call was never released"

        api.after = during_native_call
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl")])
        session = session_for(actor)
        session.fast.run = lambda: None
        real_thread = threading.Thread

        class InterruptedThread(real_thread):
            def start(self):
                super().start()
                assert entered.wait(1)
                raise KeyboardInterrupt()

        with patch("star.play.loop.threading.Thread", InterruptedThread):
            with self.assertRaises(KeyboardInterrupt):
                session.start()
        self.assertEqual(len(session._threads), 1)
        with self.assertRaisesRegex(RuntimeError, "shutdown is incomplete"):
            session.stop(timeout=0)
        self.assertEqual(len(api.calls), 1)  # Never release before the in-flight DOWN has finished.
        release.set()
        session.stop(timeout=1)
        self.assertFalse(session._threads)
        self.assertFalse(actor.held())
        self.assertEqual([(row[1], row[2]) for row in api.calls], [(17, 8), (17, 10)])

    def test_uncertain_unstarted_worker_does_not_claim_cleanup(self):
        sink, api = sink_for(DesktopSink, [1])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl")])
        actor.pump()
        session = session_for(actor)
        session._threads = [threading.Thread(target=lambda: None)]
        with self.assertRaisesRegex(RuntimeError, "shutdown is incomplete"):
            session.stop(timeout=0)
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(actor.held(), {"ctrl"})

    def test_registered_roblox_activity_reports_native_failure(self):
        from scripts.verify_autonomy_recovery import GameStopChecks

        fixture = GameStopChecks()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        sink, api = sink_for(DesktopSink, [0])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "move_rel", 1, 1)])
        session = session_for(actor)
        session.fast.on_moment = []
        session.start = actor.run
        fixture.rt.hooks["roblox_session"] = lambda *args, **kwargs: session
        out = fixture.run_game("roblox")
        self.assertFalse(out["verified"])
        self.assertFalse(out["ok"])
        self.assertEqual(out["input_delivery"]["native_failed_events"], 1)
        self.assertEqual(len(api.calls), 1)
        self.assertNotIn("roblox.session", fixture.active)

    def test_registered_activity_cleanup_failure_overrides_success(self):
        from scripts.verify_autonomy_recovery import GameStopChecks

        fixture = GameStopChecks()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        sink, api = sink_for(DesktopSink, [1, 0])
        actor = Actuator(sink, clock=Clock())
        actor.submit([Event(10, "key_down", "ctrl")])
        session = session_for(actor)
        session.fast.on_moment = []
        def start():
            actor.pump()
        session.start = start
        fixture.rt.hooks["roblox_session"] = lambda *args, **kwargs: session
        out = fixture.run_game("roblox")
        self.assertFalse(out["verified"])
        self.assertFalse(out["ok"])
        self.assertFalse(out["paused"])
        self.assertEqual(out["input_delivery"]["held_keys"], 1)
        self.assertEqual(len(api.calls), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
