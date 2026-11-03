"""Deterministic, no-key-injection tests of the independent game input supervisor."""
from __future__ import annotations

from threading import Event
import unittest
from unittest.mock import patch

from star.windows_game_input_watchdog import supervise_press
from star.windows_game_input_port import WindowsGameInputPort


class Keyboard:
    def __init__(self, *, focus=True, up=True):
        self.focus = focus
        self.key_up = up
        self.events = []

    def foreground_is(self, hwnd, pid):
        return self.focus and (hwnd, pid) == (123, 456)

    def up(self, key):
        return self.key_up

    def send(self, key, *, release):
        self.events.append((key, release))
        if release:
            self.key_up = True
        return True


class Process:
    stdin = None

    def __init__(self, *, status=0, receipt=b"RELEASED", stopped=False,
                 unkillable=False):
        self.returncode = None if stopped else status
        self.receipt = receipt
        self.unkillable = unkillable
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return self.returncode

    def communicate(self, timeout):
        return self.receipt, b""

    def terminate(self):
        self.terminated += 1
        if not self.unkillable:
            self.returncode = -15

    def kill(self):
        self.killed += 1
        if not self.unkillable:
            self.returncode = -9

    def wait(self, timeout):
        return self.returncode


def run(device=None, process=None, *, action="jump", stop=None, **kw):
    device = device or Keyboard()
    process = process or Process()
    commands = []
    def spawn(args):
        commands.append(args)
        return process
    result = supervise_press(
        device, action=action, hwnd=123, pid=456, hold_ms=20,
        stop=stop or Event(), spawn=spawn, **kw,
    )
    return result, device, process, commands


class WatchdogTests(unittest.TestCase):
    def test_worker_success_is_accepted_only_with_neutral_key(self):
        result, dev, proc, calls = run()
        self.assertTrue(result)
        self.assertFalse(dev.events)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-8:], [
            "--action", "jump", "--hwnd", "123",
            "--pid", "456", "--hold-ms", "20",
        ])
        self.assertEqual(calls[0][2], "star.windows_game_input_worker")

    def test_crashed_worker_gets_independent_key_up_and_failed_receipt(self):
        dev = Keyboard()
        proc = Process(status=-9, receipt=b"")
        result, _, _, _ = run(dev, proc)
        self.assertFalse(result)
        self.assertEqual(len(dev.events), 1)
        self.assertTrue(dev.events[0][1])

    def test_forged_successful_receipt_without_os_key_up_is_rejected(self):
        dev = Keyboard()
        proc = Process()
        def spawn(cmd):
            dev.key_up = False
            return proc
        result = supervise_press(
            dev, action="jump", hwnd=123, pid=456, hold_ms=20,
            stop=Event(), spawn=spawn,
        )
        self.assertFalse(result)
        self.assertTrue(dev.key_up)
        self.assertEqual(len(dev.events), 1)

    def test_timeout_terminates_worker_before_attempting_recovery(self):
        time = [100.0]
        proc = Process(stopped=True)
        def clock():
            return time[0]
        def sleep(delay):
            time[0] += delay
        result, dev, _, _ = run(process=proc, clock=clock, sleep=sleep)
        self.assertFalse(result)
        self.assertEqual(proc.terminated, 1)
        self.assertEqual(proc.killed, 0)
        self.assertEqual(len(dev.events), 1)

    def test_unkillable_worker_is_not_certified_as_released(self):
        time = [100.0]
        proc = Process(stopped=True, unkillable=True)
        result, dev, _, _ = run(
            process=proc, clock=lambda: time[0],
            sleep=lambda d: time.__setitem__(0, time[0] + d),
        )
        self.assertFalse(result)
        self.assertEqual(proc.terminated, 1)
        self.assertEqual(proc.killed, 1)
        self.assertEqual(len(dev.events), 1)

    def test_cancel_in_middle_rejects_worker_result(self):
        stop = Event()
        time = [0.0]
        proc = Process(stopped=True)
        def sleep(delta):
            time[0] += delta
            stop.set()
        result, dev, _, _ = run(
            process=proc, stop=stop, clock=lambda: time[0], sleep=sleep,
        )
        self.assertFalse(result)
        self.assertEqual(proc.terminated, 1)
        self.assertEqual(len(dev.events), 1)

    def test_focus_loss_while_child_active_requests_shutdown(self):
        time = [0.0]
        dev = Keyboard()
        proc = Process(stopped=True)
        def sleep(delta):
            time[0] += delta
            dev.focus = False
        result, _, _, _ = run(
            dev, proc, clock=lambda: time[0], sleep=sleep,
        )
        self.assertFalse(result)
        self.assertTrue(proc.terminated)

    def test_invalid_allowlist_and_user_key_stays_untouched(self):
        dev = Keyboard(up=False)
        self.assertFalse(run(device=dev)[0])
        self.assertEqual(dev.events, [])
        self.assertFalse(run(action="alt_tab")[0])

    def test_stopped_before_spawn_never_launches_worker(self):
        stop = Event()
        stop.set()
        result, dev, _, calls = run(stop=stop)
        self.assertFalse(result)
        self.assertEqual(calls, [])
        self.assertFalse(dev.events)

    def test_spawn_failure_does_not_claim_success(self):
        dev = Keyboard()
        def raise_error(cmd):
            raise OSError("no worker")
        self.assertFalse(supervise_press(
            dev, action="jump", hwnd=123, pid=456,
            hold_ms=10, stop=Event(), spawn=raise_error,
        ))
        self.assertFalse(dev.events)

    def test_port_uses_watchdog_process_and_latches_after_bad_result(self):
        dev = Keyboard()
        with patch("star.windows_game_input_port._windows", return_value=True), \
             patch("star.windows_game_input_port.WindowsKeyboard", return_value=dev):
            port = WindowsGameInputPort(
                hwnd=123, pid=456, action_map={"jump": "jump"},
            )
        port.enable(owner_approved=True)
        rejected = Process(status=1, receipt=b"REJECTED")
        with patch("star.windows_game_input_port.subprocess.Popen",
                   return_value=rejected) as popen:
            self.assertFalse(port.send_action("jump", 20, Event()))
            cmd = popen.call_args.args[0]
            self.assertEqual(cmd[2], "star.windows_game_input_watchdog")
            self.assertIn("--watchdog", cmd)
        self.assertFalse(port.send_action("jump", 20, Event()))
        self.assertTrue(port._stop.is_set())


if __name__ == "__main__":
    unittest.main()
