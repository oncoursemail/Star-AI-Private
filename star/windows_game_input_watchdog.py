"""Second-process supervisor for a single owner-approved Windows game key press.

The watchdog starts the existing bounded input *worker*, monitors its exit,
and sends an additional key-up after a crash, timeout, cancellation or bad
receipt. The worker still releases its own key if the watchdog itself exits.
Both processes are intentionally short-lived; this is not a kernel watchdog
or proof that an application accepted synthetic input.

Disabled unless WindowsGameInputPort has been explicitly owner-enabled.
No focus stealing, window discovery, mouse support or network endpoints.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from threading import Event, Thread
import time
from typing import Callable

from .windows_game_input_worker import KEYS, WindowsKeyboard

# Covers interpreter startup and one worker's <=180 ms key hold. A deadline
# limits the watchdog's recovery time, not a verified physical-key-up SLA.
WORKER_DEADLINE_S = 1.25
STOP_GRACE_S = 0.12


def _signal_stop(proc: subprocess.Popen[bytes]) -> None:
    try:
        if proc.stdin is not None:
            os.write(proc.stdin.fileno(), b"STOP\n")
    except (OSError, ValueError):
        pass


def _terminate_bounded(proc: subprocess.Popen[bytes]) -> bool:
    """Attempt to stop a hung worker before issuing a compensating key-up."""
    if proc.poll() is not None:
        return True
    try:
        proc.terminate()
        proc.wait(timeout=0.12)
    except (OSError, subprocess.TimeoutExpired):
        pass
    if proc.poll() is not None:
        return True
    try:
        proc.kill()
        proc.wait(timeout=0.12)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return proc.poll() is not None


def supervise_press(
    device: WindowsKeyboard, *, action: str, hwnd: int, pid: int,
    hold_ms: int, stop: Event,
    spawn: Callable[[list[str]], subprocess.Popen[bytes]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Supervise one key worker; reject any uncertain or repaired outcome.

    The compensating release can be blocked by UIPI or a locked desktop.
    GetAsyncKeyState only reports observed OS state; it is not hardware
    verification. Owners must still retain an out-of-process emergency stop.
    """
    if (type(action) is not str or action not in KEYS
            or type(hwnd) is not int or hwnd <= 0
            or type(pid) is not int or pid <= 0
            or type(hold_ms) is not int or not 1 <= hold_ms <= 180
            or not isinstance(stop, Event) or stop.is_set()):
        return False

    key = KEYS[action]
    try:
        if not device.foreground_is(hwnd, pid) or not device.up(key):
            return False
    except Exception:
        return False

    command = [
        sys.executable, "-m", "star.windows_game_input_worker",
        "--worker", "--action", action, "--hwnd", str(hwnd),
        "--pid", str(pid), "--hold-ms", str(hold_ms),
    ]
    if spawn is None:
        spawn = lambda cmd: subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    proc: subprocess.Popen[bytes] | None = None
    finished_cleanly = False
    try:
        if stop.is_set() or not device.foreground_is(hwnd, pid):
            return False
        proc = spawn(command)
        deadline = clock() + WORKER_DEADLINE_S
        stop_since: float | None = None
        signalled = False
        while proc.poll() is None:
            now = clock()
            cancelled = stop.is_set() or not device.foreground_is(hwnd, pid)
            if cancelled or now >= deadline:
                if not signalled:
                    _signal_stop(proc)
                    signalled = True
                    stop_since = now
                if stop_since is not None and now - stop_since >= STOP_GRACE_S:
                    break
            sleep(0.005)
        # Terminate before rescue: never let a still-running worker inject
        # another key-down *after* the watchdog's key-up.
        if not _terminate_bounded(proc):
            return False
        try:
            result, _ = proc.communicate(timeout=0.2)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            result = b""
        finished_cleanly = (
            proc.returncode == 0 and result == b"RELEASED"
            and not signalled and not stop.is_set()
            and clock() <= deadline
            and device.foreground_is(hwnd, pid)
            and device.up(key)
        )
        return finished_cleanly
    except (OSError, ValueError, RuntimeError):
        return False
    finally:
        # On every failure (including a worker crash or missing receipt), a
        # *different* process from the key-down worker attempts release.
        # Success is NEVER inferred from this recovery edge.
        if not finished_cleanly and proc is not None:
            try:
                device.send(key, release=True)
            except Exception:
                pass


def _watch_parent(stop: Event) -> None:
    # Parent EOF or any input is a stop request; do not trust text commands.
    try:
        for _ in sys.stdin:
            stop.set()
            return
    finally:
        stop.set()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="internal one-key recovery watchdog")
    p.add_argument("--watchdog", action="store_true")
    p.add_argument("--action", choices=sorted(KEYS))
    p.add_argument("--hwnd", type=int)
    p.add_argument("--pid", type=int)
    p.add_argument("--hold-ms", type=int)
    args = p.parse_args(argv)
    if (not args.watchdog or args.action is None or args.hwnd is None
            or args.pid is None or args.hold_ms is None or os.name != "nt"):
        return 2
    stop = Event()
    Thread(target=_watch_parent, args=(stop,), daemon=True).start()
    try:
        ok = supervise_press(
            WindowsKeyboard(), action=args.action, hwnd=args.hwnd,
            pid=args.pid, hold_ms=args.hold_ms, stop=stop,
        )
    except Exception:
        ok = False
    sys.stdout.write("RELEASED" if ok else "REJECTED")
    sys.stdout.flush()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
