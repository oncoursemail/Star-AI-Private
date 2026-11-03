"""Adversarial, no-input tests for bounded Windows game guardian and host."""
from __future__ import annotations

import os
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch

from star.windows_game_input_worker import KEYS, Key, bounded_press, _Input
from star.windows_game_input_port import WindowsGameInputPort


class FakeKeyboard:
    def __init__(self):
        self.focus = True
        self.is_up = True
        self.sent = []
        self.fail_down = False
        self.fail_up = False
        self.on_down = None

    def foreground_is(self, hwnd, pid):
        return self.focus and (hwnd, pid) == (123, 456)

    def up(self, key):
        return self.is_up

    def send(self, key, *, release):
        self.sent.append((key, release))
        if release:
            if self.fail_up:
                return False
            self.is_up = True
        else:
            if self.fail_down:
                return False
            self.is_up = False
            if self.on_down:
                self.on_down()
        return True


def press(device, **kw):
    return bounded_press(
        device, action=kw.pop("action", "jump"), hwnd=123, pid=456,
        hold_ms=kw.pop("hold_ms", 5), stop=kw.pop("stop", Event()),
        **kw,
    )


class WorkerTests(unittest.TestCase):
    def test_allowlist_excludes_shortcuts_and_text(self):
        self.assertEqual(len(KEYS), 9)
        self.assertNotIn("alt_tab", KEYS)
        self.assertNotIn("win", KEYS)
        self.assertTrue(all(type(v) is Key for v in KEYS.values()))

    def test_normal_press_releases_and_probes(self):
        d = FakeKeyboard()
        self.assertTrue(press(d))
        self.assertEqual(d.sent, [(KEYS["jump"], False), (KEYS["jump"], True)])
        self.assertTrue(d.is_up)

    def test_focus_failure_never_injects(self):
        d = FakeKeyboard()
        d.focus = False
        self.assertFalse(press(d))
        self.assertEqual(d.sent, [])

    def test_already_held_key_not_stolen(self):
        d = FakeKeyboard()
        d.is_up = False
        self.assertFalse(press(d))
        self.assertEqual(d.sent, [])

    def test_invalid_commands_cannot_inject(self):
        for action, hold in [("ctrl", 10), ("jump", 0), ("jump", 181),
                             ("jump", True), ("Jump", 10)]:
            d = FakeKeyboard()
            self.assertFalse(press(d, action=action, hold_ms=hold))
            self.assertFalse(d.sent)

    def test_stop_while_held_releases_before_reporting_failure(self):
        d = FakeKeyboard()
        stop = Event()
        d.on_down = stop.set
        self.assertFalse(press(d, hold_ms=100, stop=stop))
        self.assertEqual([release for _, release in d.sent], [False, True])
        self.assertTrue(d.is_up)

    def test_focus_loss_after_down_releases(self):
        d = FakeKeyboard()
        d.on_down = lambda: setattr(d, "focus", False)
        self.assertFalse(press(d))
        self.assertEqual([release for _, release in d.sent], [False, True])

    def test_key_down_failure_no_unevidenced_release(self):
        d = FakeKeyboard()
        d.fail_down = True
        self.assertFalse(press(d))
        self.assertEqual([release for _, release in d.sent], [False])

    def test_key_up_failure_never_claims_success(self):
        d = FakeKeyboard()
        d.fail_up = True
        self.assertFalse(press(d))
        self.assertEqual([release for _, release in d.sent], [False, True])

    def test_os_state_unverified_no_success(self):
        d = FakeKeyboard()
        old_send = d.send
        def bogus(key, *, release):
            ok = old_send(key, release=release)
            if release:
                d.is_up = False
            return ok
        d.send = bogus
        self.assertFalse(press(d))

    def test_no_windows_runtime_on_linux(self):
        if os.name != "nt":
            from star.windows_game_input_worker import WindowsKeyboard
            with self.assertRaises(RuntimeError):
                WindowsKeyboard()

    def test_win32_input_structure_is_pointer_size_aware(self):
        import ctypes
        self.assertGreaterEqual(ctypes.sizeof(_Input), 28)


class FakeProcess:
    def __init__(self, outcome=b"RELEASED", returncode=0):
        self.outcome = outcome
        self.returncode = returncode
        self.stdin = None
    def poll(self):
        return self.returncode
    def communicate(self, timeout):
        return self.outcome, b""


class PortTests(unittest.TestCase):
    def make_port(self, *, focus=True, up=True):
        self.device = FakeKeyboard()
        self.device.focus = focus
        self.device.is_up = up
        with patch("star.windows_game_input_port._windows", return_value=True), \
             patch("star.windows_game_input_port.WindowsKeyboard", return_value=self.device):
            port = WindowsGameInputPort(
                hwnd=123, pid=456,
                action_map={"jump_left": "arrow_left", "jump": "jump"},
            )
        return port

    def test_off_by_default_and_owner_approved(self):
        port = self.make_port()
        self.assertFalse(port.send_action("jump", 5, Event()))
        with self.assertRaises(PermissionError):
            port.enable()
        port.enable(owner_approved=True)
        with self.assertRaises(RuntimeError):
            port.enable(owner_approved=True)

    def test_reject_wrong_focus_or_pressed_user_key(self):
        for focus, up in [(False, True), (True, False)]:
            port = self.make_port(focus=focus, up=up)
            with self.assertRaises(RuntimeError):
                port.enable(owner_approved=True)

    def test_full_mocked_host_callback(self):
        port = self.make_port()
        port.enable(owner_approved=True)
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=FakeProcess()) as p:
            self.assertTrue(port.send_action("jump_left", 20, Event()))
            self.assertEqual(p.call_args.args[0][-8:],
                             ["--action", "arrow_left", "--hwnd", "123", "--pid", "456", "--hold-ms", "20"])
        self.assertTrue(port.all_keys_up())
        # GameActuationRehearsal asks for release after each successful press.
        # An already-exited child has released its key: preserve reusability.
        port.request_all_up()
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=FakeProcess()) as p2:
            self.assertTrue(port.send_action("jump", 12, Event()))
            self.assertEqual(p2.call_args.args[0][-1], "12")

    def test_exact_guarded_episode_accepts_native_port_callbacks(self):
        # End-to-end through the real ActionPermit claim/release state machine,
        # while mocking *only* the OS worker and Win32 API (no real keys).
        from test_game_actuation_rehearsal import ready
        guard, permit, _, episode, _ = ready()
        port = self.make_port()
        port.enable(owner_approved=True)
        guard._send_action = port.send_action
        guard._request_all_up = port.request_all_up
        guard._all_keys_up = port.all_keys_up
        guard._focus = port.focus_ok
        guard.enable(owner_approved=True)
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=FakeProcess()):
            result = guard.run(permit)
        self.assertEqual(result.status, "released_verified")
        self.assertTrue(result.keys_up_verified)
        self.assertFalse(episode.revoked)
        self.assertFalse(port._stop.is_set())
        guard.stop()
        self.assertTrue(episode.revoked)

    def test_fake_worker_rejection_is_not_success(self):
        port = self.make_port()
        port.enable(owner_approved=True)
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=FakeProcess(b"REJECTED", 1)):
            self.assertFalse(port.send_action("jump", 3, Event()))
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=FakeProcess(b"RELEASED", 1)):
            self.assertFalse(port.send_action("jump", 3, Event()))

    def test_unknown_action_and_cancelled_request_never_spawn(self):
        port = self.make_port()
        port.enable(owner_approved=True)
        cancelled = Event()
        cancelled.set()
        with patch("star.windows_game_input_port.subprocess.Popen") as p:
            self.assertFalse(port.send_action("unmapped", 10, Event()))
            self.assertFalse(port.send_action("jump", 10, cancelled))
            self.assertFalse(port.send_action("jump", 181, Event()))
            p.assert_not_called()

    def test_stop_irreversible_and_does_not_wait_for_os(self):
        port = self.make_port()
        port.enable(owner_approved=True)
        start = time.monotonic()
        port.request_all_up()
        self.assertLess(time.monotonic()-start, .1)
        with patch("star.windows_game_input_port.subprocess.Popen") as p:
            self.assertFalse(port.send_action("jump", 10, Event()))
            p.assert_not_called()
        with self.assertRaises(RuntimeError):
            port.enable(owner_approved=True)

    def test_emergency_stop_does_not_wait_for_unresponsive_worker(self):
        class StuckProcess:
            stdin = None
            def poll(self):
                return None

        port = self.make_port()
        port.enable(owner_approved=True)
        results = []
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=StuckProcess()):
            thread = Thread(
                target=lambda: results.append(
                    port.send_action("jump", 40, Event())
                ), daemon=True,
            )
            thread.start()
            deadline = time.monotonic() + 1
            while port._proc is None and time.monotonic() < deadline:
                time.sleep(.001)
            self.assertIsNotNone(port._proc)
            start = time.monotonic()
            port.request_all_up()
            self.assertLess(time.monotonic()-start, .1)
            thread.join(.4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [False])
        self.assertFalse(port.send_action("jump", 30, Event()))

    def test_unverified_release_latches_port_even_after_worker_exit(self):
        port = self.make_port()
        port.enable(owner_approved=True)
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=FakeProcess()):
            self.assertTrue(port.send_action("jump", 5, Event()))
        self.device.is_up = False
        port.request_all_up()
        self.assertFalse(port.send_action("jump", 5, Event()))

    def test_port_refuses_nonwindows(self):
        if os.name != "nt":
            with self.assertRaises(RuntimeError):
                WindowsGameInputPort(
                    hwnd=123, pid=456, action_map={"jump": "jump"}
                )

    def test_constructor_never_accepts_unbounded_keys(self):
        cases = [{"hi": "alt_tab"}, {"": "jump"}, {f"a{i}": "jump" for i in range(13)}, {}]
        for mapping in cases:
            with patch("star.windows_game_input_port._windows", return_value=True):
                with self.assertRaises(ValueError):
                    WindowsGameInputPort(hwnd=123, pid=456, action_map=mapping)

    def test_probe_failure_fails_closed(self):
        port = self.make_port()
        port.enable(owner_approved=True)
        self.device.focus = False
        self.assertFalse(port.focus_ok())
        self.device.is_up = False
        self.assertFalse(port.all_keys_up())


if __name__ == "__main__":
    unittest.main()
