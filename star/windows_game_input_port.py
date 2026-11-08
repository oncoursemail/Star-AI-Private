"""Owner-only Windows game input port with two-process key-up recovery.

This port supplies the three callbacks required by GameActuationRehearsal:
send_action, request_all_up, all_keys_up. A separate, short-lived worker owns
each key-down and performs a timed key-up while alive. An independent
watchdog supervises the worker and attempts recovery key-up after failure.
Emergency stop never waits on the worker/OBS lock. A joint crash, stuck OS
input, OS scheduling stall or anti-cheat rejection is NOT certified safe by Python.

OFF until both this port and the OBS-guarded rehearsal are owner enabled.
Use only on owner-authorized, automation-permitting games. Never expose these
callbacks to a model, viewer, content retrieval or a web endpoint.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from threading import Event, Lock
import time
from typing import Mapping

from .windows_game_input_worker import KEYS, WindowsKeyboard

_ACTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


def _windows() -> bool:
    return os.name == "nt"


class WindowsGameInputPort:
    """Single pinned HWND/PID, allowlisted keys, bounded synthetic presses.

    Key observation uses Win32 GetAsyncKeyState. This is a useful independent
    OS-state check but NOT hardware proof that a game processed a key event,
    or that releases will succeed after an arbitrary worker crash. The user
    still needs a separately supervised owner emergency stop and a dedicated PC.
    """

    def __init__(
        self, *, hwnd: int, pid: int, action_map: Mapping[str, str],
        worker_timeout_s: float = 1.8,
    ) -> None:
        if not _windows():
            raise RuntimeError("native game input requires an interactive Windows host")
        if type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0:
            raise ValueError("trusted game window HWND and PID required")
        if (not isinstance(action_map, Mapping) or not 1 <= len(action_map) <= 12
                or any(type(k) is not str or _ACTION.fullmatch(k) is None
                       or type(v) is not str or v not in KEYS
                       for k, v in action_map.items())):
            raise ValueError("1..12 owner-curated action-to-key bindings required")
        if (type(worker_timeout_s) not in (int, float)
                or not 0.5 <= float(worker_timeout_s) <= 5.0):
            raise ValueError("worker timeout must be 0.5..5 seconds")
        self._hwnd, self._pid = hwnd, pid
        self._actions = dict(action_map)
        self._timeout = float(worker_timeout_s)
        self._device = WindowsKeyboard()
        self._guard = Lock()
        self._stop = Event()
        self._enabled = False
        self._ever_enabled = False
        self._proc: subprocess.Popen[bytes] | None = None

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner approval required")
        with self._guard:
            if self._ever_enabled or self._stop.is_set():
                raise RuntimeError("create a fresh port for each game episode")
            if not self.focus_ok() or not self.all_keys_up():
                raise RuntimeError("game focus or neutral key preflight failed")
            self._ever_enabled = True
            self._enabled = True

    def focus_ok(self) -> bool:
        try:
            return self._device.foreground_is(self._hwnd, self._pid) is True
        except Exception:
            return False

    def all_keys_up(self) -> bool:
        """Probe all configured virtual keys; not game-delivery verification."""
        try:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                return False
            return all(self._device.up(KEYS[name]) is True
                       for name in set(self._actions.values()))
        except Exception:
            return False

    def request_all_up(self) -> None:
        """Request bounded worker key-up; never report it as verified.

        GameActuationRehearsal calls this after *every* completed press.
        Do not disable a cleanly exited/verified worker's next action. An
        active/uncertain worker or a failed OS state probe is terminal.
        """
        proc = self._proc
        exited = proc is not None and proc.poll() is not None
        if exited and self.all_keys_up():
            return
        self._stop.set()
        self._enabled = False
        if proc is None or exited:
            return
        try:
            if proc.stdin is not None:
                # Tiny one-way message; never wait for an ACK in emergency stop.
                os.write(proc.stdin.fileno(), b"STOP\n")
        except (OSError, ValueError, BrokenPipeError):
            pass

    def send_action(self, action_id: str, hold_ms: int, cancelled: Event) -> bool:
        """Host worker callback for GameActuationRehearsal.

        Two interpreter startups are not optimized for twitch games. The
        watchdog is the process tracked by this port; its child owns key-down.
        Failed or uncertain action execution permanently disables this port.
        """
        if (type(action_id) is not str or type(hold_ms) is not int
                or not 1 <= hold_ms <= 180 or not isinstance(cancelled, Event)):
            return False
        if (not self._enabled or self._stop.is_set() or cancelled.is_set()
                or action_id not in self._actions):
            return False
        if not self._guard.acquire(blocking=False):
            return False
        spawned = False
        verified = False
        try:
            if (not self._enabled or self._stop.is_set() or cancelled.is_set()
                    or not self.focus_ok() or not self.all_keys_up()):
                return False
            command = [
                sys.executable, "-m", "star.windows_game_input_watchdog",
                "--watchdog", "--action", self._actions[action_id],
                "--hwnd", str(self._hwnd), "--pid", str(self._pid),
                "--hold-ms", str(hold_ms),
            ]
            try:
                proc = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, ValueError):
                return False
            self._proc = proc
            spawned = True
            if self._stop.is_set() or cancelled.is_set():
                self.request_all_up()
            deadline = time.monotonic() + self._timeout
            while proc.poll() is None and time.monotonic() < deadline:
                if cancelled.is_set() or self._stop.is_set():
                    self.request_all_up()
                    # Do not block on an unresponsive child after stop.
                    return False
                time.sleep(0.005)
            if proc.poll() is None:
                self.request_all_up()
                return False
            try:
                output, _ = proc.communicate(timeout=0.2)
            except (OSError, subprocess.TimeoutExpired):
                return False
            verified = (
                proc.returncode == 0 and output == b"RELEASED"
                and not cancelled.is_set() and not self._stop.is_set()
                and self.focus_ok() and self.all_keys_up()
            )
            return verified
        finally:
            # An uncertain worker/OS receipt is terminal, even if the next
            # OS key-state sample happens to look neutral.
            if spawned and not verified:
                self._stop.set()
                self._enabled = False
            self._guard.release()


__all__ = ["WindowsGameInputPort"]
