"""CPU priority for STAR's non-LLM background work (tests, builds, Studio jobs, Luau checks, indexing).

The same classes as star/priority_proxy.py: P0/P1 (owner) run as they are; P2 runs at nice 10 / below-normal; P3 runs
at nice 19 under SCHED_IDLE (Linux: it only gets CPU nobody else wants) / idle priority class (Windows). Children
inherit it. With --pause-url (the priority proxy) a P2/P3 job is also stopped (SIGSTOP to its process group) while
the proxy reports `p0_active` (owner chat running, plus its grace period) and continued (SIGCONT) right after:
the job loses a few seconds and nothing else. Pausing is Linux only; an unreachable proxy never pauses anything.

  python -m star.cpu_priority --class P3 [--pause-url http://127.0.0.1:8097] -- pytest -q
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import Callable
import urllib.request

NICE = {0: 0, 1: 0, 2: 10, 3: 19}
WINDOWS_CLASS = {2: 0x4000, 3: 0x40}          # BELOW_NORMAL_PRIORITY_CLASS, IDLE_PRIORITY_CLASS


def wrap_command(cls: int, command: list[str]) -> list[str]:
    """POSIX: `command` started at the class's CPU priority (unchanged for P0/P1). Windows uses `popen`'s flags."""
    if cls <= 1 or sys.platform == "win32":
        return list(command)
    wrapped = ["nice", "-n", str(NICE[cls]), *command]
    if cls == 3 and shutil.which("chrt"):
        wrapped = ["chrt", "--idle", "0", *wrapped]
    return wrapped


def popen(cls: int, command: list[str], **kwargs) -> subprocess.Popen:
    """Start `command` at the class's CPU priority (its own process group on POSIX, for pausing)."""
    if sys.platform == "win32":
        flags = kwargs.pop("creationflags", 0) | WINDOWS_CLASS.get(cls, 0)
        return subprocess.Popen(list(command), creationflags=flags, **kwargs)
    return subprocess.Popen(wrap_command(cls, command), start_new_session=True, **kwargs)


def p0_active(url: str, timeout: float = 1.0) -> bool | None:
    """The proxy's `p0_active`, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/priority/v1/status", timeout=timeout) as reply:
            return bool(json.loads(reply.read(1 << 20)).get("p0_active"))
    except (OSError, ValueError):
        return None


def _send(pid: int, what: str) -> None:
    if sys.platform != "win32":
        os.killpg(pid, getattr(signal, "SIGSTOP" if what == "stop" else "SIGCONT"))


def run(cls: int, command: list[str], *, status_url: str = "", poll_s: float = 0.5,
        start: Callable[[list[str], int], object] = lambda command, cls: popen(cls, command), active: Callable[[str], bool | None] = p0_active,
        send: Callable[[int, str], None] = _send, sleep: Callable[[float], None] = time.sleep) -> int:
    """Run `command` at the class's priority; pause it while the owner's chat runs. Returns its exit code."""
    child = start(command, cls)
    paused = False
    try:
        while child.poll() is None:            # type: ignore[attr-defined]
            if status_url and cls >= 2:
                busy = active(status_url)
                if busy and not paused:
                    send(child.pid, "stop")    # type: ignore[attr-defined]
                    paused = True
                elif not busy and paused:
                    send(child.pid, "cont")    # type: ignore[attr-defined]
                    paused = False
            sleep(poll_s)
    finally:
        if paused:
            try:
                send(child.pid, "cont")        # type: ignore[attr-defined]
            except OSError:
                pass
    return int(child.returncode or 0)          # type: ignore[attr-defined]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m star.cpu_priority")
    parser.add_argument("--class", dest="cls", required=True, type=lambda t: int(t.strip().upper().lstrip("P")),
                        choices=(0, 1, 2, 3))
    parser.add_argument("--pause-url", default="")
    parser.add_argument("--poll-s", type=float, default=0.5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args.cls, args.command, status_url=args.pause_url, poll_s=args.poll_s)


if __name__ == "__main__":
    raise SystemExit(main())
