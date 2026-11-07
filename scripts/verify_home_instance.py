"""Offline CLI lease checks, including owned subprocess crashes; no native Home activities."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
from typing import Any, cast
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.discord_bot.instance_lock import InstanceLock  # noqa: E402
from star.home import __main__ as entry, control  # noqa: E402
from star.home.activities import Registry  # noqa: E402
from star.home.runtime import Runtime  # noqa: E402


class FakeRuntime:
    def __init__(self):
        self.attention = None
        self.closed = False

    def background(self):
        return []

    def shutdown(self):
        self.closed = True
        self.stop()

    def stop(self):
        pass

    def stop_status(self):
        return {"pending": [], "errors": {}}


def worker(mode: str, folder: str) -> int:
    runtime = FakeRuntime()
    released = threading.Event()

    def setup(dry, *, home):
        if mode == "setup_error":
            raise OSError("PRIVATE_FIXTURE_EXCEPTION")
        return home, {}, SimpleNamespace(dry_run=dry), None, None

    def build(*args, **kwargs):
        if mode == "partial_build":
            raise RuntimeError("PRIVATE_FIXTURE_EXCEPTION")
        if mode == "partial_build_interrupt":
            raise KeyboardInterrupt()
        return Registry(), runtime

    def cycle(*args, **kwargs):
        print("OWNED", flush=True)
        if mode in ("once_hold", "race"):
            sys.stdin.readline()
        return {"state": "idle"}

    def run(*args, **kwargs):
        print("OWNED", flush=True)

    if mode == "cleanup_hold":
        def stop():
            print("CLEANUP", flush=True)
        runtime.stop = stop
        runtime.stop_status = lambda: {"pending": [] if released.is_set() else ["fixture"], "errors": {}}
        threading.Thread(target=lambda: (sys.stdin.readline(), released.set()), daemon=True).start()
    if mode == "shutdown_exit":
        runtime.shutdown = lambda: (_ for _ in ()).throw(SystemExit(17))
    with (patch.dict(os.environ, {"STAR_HOME_DIR": folder}), patch.object(entry, "_setup", side_effect=setup),
          patch.object(entry.home_runtime, "build", side_effect=build), patch.object(entry, "cycle", side_effect=cycle),
          patch.object(entry, "run_forever", side_effect=run)):
        if mode == "race":
            print("ARMED", flush=True)
            sys.stdin.readline()
        try:
            code = entry.main(["run" if mode == "run_return" else "once", "--dry-run"])
        except SystemExit as error:
            assert isinstance(error.code, int)
            code = error.code
        print(f"RETURN {code}", flush=True)
        if mode in ("run_return", "once_return", "partial_build", "partial_build_interrupt", "setup_error", "shutdown_exit"):
            sys.stdin.readline()
        return code


class Child:
    def __init__(self, mode, home):
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", mode, str(home)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.lines = Queue()
        self.errors = []

        def read_stdout():
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.lines.put(line.strip())
        def read_stderr():
            assert self.process.stderr is not None
            self.errors.extend(self.process.stderr.readlines())
        self.readers = [threading.Thread(target=read_stdout, daemon=True), threading.Thread(target=read_stderr, daemon=True)]
        for reader in self.readers:
            reader.start()

    def until(self, prefix):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.1)
            except Empty:
                if self.process.poll() is not None:
                    self.readers[0].join(0.1)
                    if self.lines.empty():
                        raise AssertionError(f"fixture exited before {prefix}: {''.join(self.errors)}")
                continue
            if line.startswith(prefix):
                return line
        raise AssertionError(f"fixture did not reach {prefix}")

    def send(self, text="continue"):
        assert self.process.stdin is not None
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.kill()  # Only this verifier's known fake subprocess, never a PID from a lock file.
        self.process.wait(timeout=5)
        for reader in self.readers:
            reader.join(2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()


class LeaseChecks(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()

    def child(self, mode, home=None):
        child = Child(mode, self.home if home is None else home)
        self.addCleanup(child.close)
        return child

    def command(self, command, *, home=None, runtime=None, setup_error=None, cycle_error=None):
        runtime = runtime or FakeRuntime()
        out, err = io.StringIO(), io.StringIO()
        def setup(dry, *, home):
            if setup_error:
                raise setup_error
            return home, {}, SimpleNamespace(dry_run=dry), None, None
        with (patch.dict(os.environ, {"STAR_HOME_DIR": str(home or self.home)}),
              patch.object(entry, "_setup", side_effect=setup) as setup_call,
              patch.object(entry.home_runtime, "build", return_value=(Registry(), runtime)),
              patch.object(entry, "cycle", side_effect=cycle_error, return_value={"state": "idle"}),
              patch.object(entry, "run_forever", return_value=None),
              redirect_stdout(out), redirect_stderr(err)):
            code = entry.main(command)
        return code, setup_call, out.getvalue(), err.getvalue()

    def assert_busy(self, command=None, home=None):
        code, setup, _, err = self.command(command or ["once", "--dry-run"], home=home)
        self.assertEqual(code, 2)
        setup.assert_not_called()
        self.assertIn("already running", err)

    def test_second_process_and_preview_are_refused_before_setup(self):
        child = self.child("once_hold")
        child.until("OWNED")
        self.assert_busy()
        self.assert_busy(["run", "--dry-run"])
        self.assert_busy(["run"])
        child.send()
        self.assertEqual(child.until("RETURN"), "RETURN 0")
        self.assertEqual(child.process.wait(5), 0)
        self.assertEqual(self.command(["once"])[0], 0)

    def test_same_process_distinct_lease_cannot_reenter_home(self):
        lease = InstanceLock(self.home, entry._LEASE_NAME)
        self.assertTrue(lease.acquire())
        try:
            self.assert_busy()
        finally:
            lease.release()

    def test_simultaneous_processes_admit_exactly_one_owner(self):
        children = [self.child("race") for _ in range(3)]
        for child in children:
            child.until("ARMED")
        for child in children:
            child.send("go")
        owners, refused = [], set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(refused) < 2:
            for index, child in enumerate(children):
                try:
                    line = child.lines.get_nowait()
                except Empty:
                    continue
                if line == "OWNED":
                    owners.append(index)
                elif line.startswith("RETURN"):
                    self.assertEqual(line, "RETURN 2")
                    refused.add(index)
            self.assertLessEqual(len(owners), 1)
            time.sleep(0.01)
        self.assertEqual(len(owners), 1)
        self.assertEqual(len(refused), 2)
        winner = children[owners[0]]
        winner.send("finish")
        self.assertEqual(winner.until("RETURN"), "RETURN 0")

    def test_alias_path_resolves_to_the_same_live_lease(self):
        child = self.child("once_hold")
        child.until("OWNED")
        alias = self.home / ".." / "home"
        self.assert_busy(home=alias)
        if os.name == "nt":
            self.assert_busy(home=self.home.with_name("HOME"))

    def test_different_home_can_execute_without_claiming_global_pc_exclusivity(self):
        child = self.child("once_hold")
        child.until("OWNED")
        other = Path(self.temp.name) / "other"
        self.assertEqual(self.command(["once", "--dry-run"], home=other)[0], 0)

    def test_os_releases_crashed_owner_without_stale_pid_cleanup(self):
        child = self.child("once_hold")
        child.until("OWNED")
        lock = self.home / entry._LEASE_NAME
        self.assertTrue(lock.exists())
        child.process.kill()
        child.process.wait(5)
        self.assertTrue(lock.exists(), "the stale lock file is deliberately retained")
        self.assertEqual(self.command(["once"])[0], 0)

    def test_run_return_keeps_lease_until_process_exit(self):
        child = self.child("run_return")
        self.assertEqual(child.until("RETURN"), "RETURN 0")
        self.assert_busy()
        child.send()
        self.assertEqual(child.process.wait(5), 0)
        self.assertEqual(self.command(["once"])[0], 0)

    def test_once_can_release_after_cleanup_even_while_embedding_process_lives(self):
        child = self.child("once_return")
        self.assertEqual(child.until("RETURN"), "RETURN 0")
        self.assertIsNone(child.process.poll())
        self.assertEqual(self.command(["once"])[0], 0)

    def test_partial_build_failure_keeps_uncertain_resources_reserved_until_exit(self):
        child = self.child("partial_build")
        self.assertEqual(child.until("RETURN"), "RETURN 1")
        self.assert_busy()
        child.send()
        self.assertEqual(child.process.wait(5), 1)
        self.assertNotIn("PRIVATE_FIXTURE_EXCEPTION", "".join(child.errors))
        self.assertEqual(self.command(["once"])[0], 0)

    def test_setup_failure_before_runtime_build_releases_lease(self):
        child = self.child("setup_error")
        self.assertEqual(child.until("RETURN"), "RETURN 1")
        self.assertIsNone(child.process.poll())
        self.assertEqual(self.command(["once"])[0], 0)

    def test_partial_build_interrupt_retains_lease_until_process_exit(self):
        child = self.child("partial_build_interrupt")
        self.assertEqual(child.until("RETURN"), "RETURN 130")
        self.assert_busy()
        child.send()
        self.assertEqual(child.process.wait(5), 130)
        self.assertEqual(self.command(["once"])[0], 0)

    def test_unavailable_os_lease_fails_closed_before_setup(self):
        with patch.object(InstanceLock, "acquire", side_effect=OSError("PRIVATE_LOCK_ERROR")):
            code, setup, _, err = self.command(["once"])
        self.assertEqual(code, 2)
        setup.assert_not_called()
        self.assertNotIn("PRIVATE_LOCK_ERROR", err)

    def test_pending_cleanup_holds_lease_until_completion(self):
        child = self.child("cleanup_hold")
        child.until("CLEANUP")
        self.assert_busy()
        child.send()
        self.assertEqual(child.until("RETURN"), "RETURN 0")
        self.assertEqual(child.process.wait(5), 0)
        self.assertEqual(self.command(["once"])[0], 0)

    def test_unexpected_cleanup_baseexception_still_has_process_owned_lease(self):
        child = self.child("shutdown_exit")
        self.assertEqual(child.until("RETURN"), "RETURN 17")
        self.assert_busy()
        child.send()
        self.assertEqual(child.process.wait(5), 17)
        self.assertEqual(self.command(["once"])[0], 0)

    def test_cleanup_interrupts_and_errors_retry_with_bounded_waits_and_static_output(self):
        runtime = FakeRuntime()
        calls, waits = [], []
        def shutdown():
            calls.append(1)
            if len(calls) == 1:
                raise KeyboardInterrupt()
        runtime.shutdown = shutdown
        runtime.stop_status = lambda: {"pending": [], "errors": {"PRIVATE_NAME": "PRIVATE_ERROR"} if len(calls) < 3 else {}}
        def sleep(seconds):
            waits.append(seconds)
            self.assert_busy()
            if len(waits) == 1:
                raise KeyboardInterrupt()
        with patch.object(entry.time, "sleep", side_effect=sleep):
            code, _, _, err = self.command(["once"], runtime=runtime)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(0.1 <= wait <= 2 for wait in waits))
        self.assertEqual(err.count("Home is waiting"), 1)
        self.assertNotIn("PRIVATE", err)
        self.assertEqual(self.command(["once"])[0], 0)

    def test_cycle_keyboardinterrupt_and_error_both_clean_and_release_once(self):
        for error, expected in ((KeyboardInterrupt(), 130), (RuntimeError("PRIVATE_EXCEPTION"), 1)):
            runtime = FakeRuntime()
            code, _, _, err = self.command(["once"], runtime=runtime, cycle_error=error)
            self.assertEqual(code, expected)
            self.assertTrue(runtime.closed)
            self.assertNotIn("PRIVATE_EXCEPTION", err)
            self.assertEqual(self.command(["once"])[0], 0)

    def test_owner_stop_resume_status_and_delegated_checks_remain_available(self):
        child = self.child("once_hold")
        child.until("OWNED")
        self.assertEqual(self.command(["stop"])[0], 0)
        self.assertTrue(control.stopped(self.home))
        self.assertEqual(self.command(["status"])[0], 0)
        self.assertEqual(self.command(["resume"])[0], 0)
        self.assertFalse(control.stopped(self.home))
        with (patch.dict(os.environ, {"STAR_HOME_DIR": str(self.home)}),
              patch("star.home.acceptance.cli", return_value=7) as acceptance,
              patch("star.home.onboarding.cli", return_value=8) as configure):
            self.assertEqual(entry.main(["acceptance", "--dry-run"]), 7)
            self.assertEqual(entry.main(["configure", "status"]), 8)
            acceptance.assert_called_once_with(["--dry-run"])
            configure.assert_called_once_with(["status"])

    def test_check_is_still_usable_under_another_live_lease_without_actions_or_brain(self):
        child = self.child("once_hold")
        child.until("OWNED")
        executor = SimpleNamespace(do=Mock(return_value=SimpleNamespace(text="fake dry preview")), dry_run=True)
        runtime = FakeRuntime()
        with (patch.dict(os.environ, {"STAR_HOME_DIR": str(self.home)}),
              patch.object(entry, "_setup", return_value=(self.home, {}, executor, None, None)) as setup,
              patch.object(entry.home_runtime, "build", return_value=(Registry(), runtime)),
              patch("star.home.voicestack.build_status", return_value={}), redirect_stdout(io.StringIO())):
            self.assertEqual(entry.main(["check"]), 1)  # The existing no-brain result is unchanged.
        setup.assert_called_once()
        executor.do.assert_called_once_with("shell", {"command": "Get-Date"})
        self.assertFalse(runtime.closed)

    def test_shutdown_cannot_be_revived_by_owner_resume_or_old_watcher(self):
        voice = SimpleNamespace(stop=Mock(), set_stop_check=Mock())
        runtime: Any = cast(Any, Runtime)(self.home, {}, SimpleNamespace(dry_run=False), None, voice=voice, emotion=None)
        runtime._calls = SimpleNamespace(stop=Mock(), tick=Mock())
        runtime.attention.watch_tick = Mock()
        control.stop(self.home)
        runtime.shutdown()
        entry._finish_runtime(runtime)
        control.resume(self.home)
        for _ in range(5):
            runtime.watch_tick()
            self.assertTrue(runtime.admission_blocked())
        runtime._calls.tick.assert_not_called()
        runtime.attention.watch_tick.assert_not_called()
        self.assertTrue(voice.set_stop_check.call_args.args[0]())


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        raise SystemExit(worker(sys.argv[2], sys.argv[3]))
    unittest.main(verbosity=2)
