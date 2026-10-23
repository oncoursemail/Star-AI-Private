"""star.cpu_priority: lower CPU priority for background classes, pause a job while the owner's chat runs."""
from __future__ import annotations

import subprocess
import sys

import pytest

from star import cpu_priority as cp


class FakeChild:
    def __init__(self, polls_before_exit: int):
        self.left, self.pid, self.returncode = polls_before_exit, 4242, None

    def poll(self):
        self.left -= 1
        if self.left <= 0:
            self.returncode = 0
        return self.returncode


def test_run_pauses_while_p0_is_active_and_resumes_after():
    child = FakeChild(8)
    states = iter([False, True, True, True, False, False, False, False, False])
    sent: list[str] = []
    code = cp.run(3, ["job"], status_url="http://proxy", poll_s=0, start=lambda cmd, cls: child,
                  active=lambda url: next(states), send=lambda pid, what: sent.append(what), sleep=lambda s: None)
    assert code == 0
    assert sent == ["stop", "cont"]


def test_run_never_leaves_a_job_stopped_and_ignores_an_unreachable_proxy():
    child = FakeChild(3)
    sent: list[str] = []
    cp.run(2, ["job"], status_url="http://proxy", poll_s=0, start=lambda cmd, cls: child,
           active=lambda url: True, send=lambda pid, what: sent.append(what), sleep=lambda s: None)
    assert sent == ["stop", "cont"]                       # the job ended while stopped: it is continued anyway
    sent.clear()
    cp.run(2, ["job"], status_url="http://proxy", poll_s=0, start=lambda cmd, cls: FakeChild(3),
           active=lambda url: None, send=lambda pid, what: sent.append(what), sleep=lambda s: None)
    assert sent == []


def test_owner_classes_are_never_paused_or_lowered():
    sent: list[str] = []
    cp.run(0, ["job"], status_url="http://proxy", poll_s=0, start=lambda cmd, cls: FakeChild(3),
           active=lambda url: True, send=lambda pid, what: sent.append(what), sleep=lambda s: None)
    assert sent == []
    assert cp.NICE[0] == cp.NICE[1] == 0 and cp.NICE[2] < cp.NICE[3] == 19


def test_a_real_child_runs_at_lower_priority():
    code = "import os,sys\n" + ("print(os.getpriority(os.PRIO_PROCESS, 0))" if sys.platform != "win32" else
                                "import ctypes; k=ctypes.windll.kernel32; k.GetCurrentProcess.restype=ctypes.c_void_p; "
                                "k.GetPriorityClass.argtypes=[ctypes.c_void_p]; print(k.GetPriorityClass(k.GetCurrentProcess()))")
    child = cp.popen(3, [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = child.communicate(timeout=60)
    assert child.returncode == 0, err
    assert int(out.strip()) == (cp.WINDOWS_CLASS[3] if sys.platform == "win32" else 19)


@pytest.mark.parametrize("text,cls", [("P3", 3), ("p2", 2), ("1", 1)])
def test_cli_parses_class(text, cls):
    args = cp.parse_args(["--class", text, "--", "echo", "hi"])
    assert args.cls == cls and args.command == ["echo", "hi"]
