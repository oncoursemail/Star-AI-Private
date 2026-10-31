"""Opt-in agent fleet: resource-sized worker slots, one git worktree per task, independent test receipts.

Off by default (set STAR_AGENT_FLEET=1 or pass enabled=True). Never merges, pushes or publishes: a task that passes its
own independent test run only yields a *proposal* (branch + diffstat) for the owner to review.

Slice 2: a task may hand its worktree to an ACP agent (``acp_prompt``; the agent process is started with cwd = the
worktree and may only write when the host's ``approve`` says yes), receipts can be appended to a JSON-lines file,
``fleet_worktrees()`` lists leftover fleet worktrees after a crash (never deletes them) and ``probe_agents()`` says
which agent CLIs are installed (auth and quota stay "unknown": nothing is launched or guessed).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from star import resource_probes as probes
from star.acp_adapter import AcpAdapter

PROTECTED_MARKERS = ("paintball", os.path.join("appdata", "roaming", "star").lower())
AGENT_CLIS = ("opencode", "codex", "claude")   # ACP/CLI coding agents the owner may have installed and signed in to
_WORKTREE_ADD = threading.Lock()  # concurrent `git worktree add` on one repo races on git lock files
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")


def fleet_enabled(enabled: bool | None = None) -> bool:
    if enabled is not None:
        return enabled
    return os.environ.get("STAR_AGENT_FLEET", "") == "1"


def sample_resources(interval: float = 0.2) -> dict:
    """Live total/available RAM (MiB), CPU busy share and logical CPUs. Missing probes give None, never a guess."""
    mem = probes.windows_memory() or probes.proc_meminfo()
    if os.name == "nt":
        read = probes.windows_cpu_times
    else:
        read = probes.proc_cpu_times
    before = read()
    time.sleep(interval)
    busy = probes.cpu_busy_share(before, read())
    return {"ram_total_mib": mem[0] if mem else None, "ram_free_mib": mem[1] if mem else None,
            "cpu_busy": busy, "cpus": os.cpu_count() or 1}


def plan_slots(res: dict, *, mib_per_agent: int = 2048, reserve_mib: int = 4096, max_busy: float = 0.85,
               cap: int = 4) -> tuple[int, str]:
    """Number of worker slots the live resources allow, plus an honest reason when it is 0 or reduced."""
    free, busy = res.get("ram_free_mib"), res.get("cpu_busy")
    if free is None or busy is None:
        return 0, "blocked: RAM or CPU could not be measured"
    if busy > max_busy:
        return 0, f"waiting: CPU busy {busy:.0%} > {max_busy:.0%}"
    by_ram = max(0, (free - reserve_mib) // mib_per_agent)
    by_cpu = max(0, int(res["cpus"] * (1 - busy)) // 2)
    n = min(by_ram, by_cpu, cap)
    if n == 0:
        return 0, f"waiting: free RAM {free} MiB, {res['cpus']} CPUs at {busy:.0%} leave no slot"
    why = "" if n == cap else f"limited by {'RAM' if by_ram <= by_cpu else 'CPU'}"
    return n, why


@dataclass
class FleetTask:
    task_id: str
    agent_cmd: list[str]   # the CLI agent, run with cwd = its worktree
    test_cmd: list[str]    # run by the fleet itself after the agent exits; the agent is never trusted on tests
    enabled: bool = True
    acp_prompt: str = ""   # set: agent_cmd is an ACP agent (JSON-RPC over stdio) that gets this one prompt
    approve: Callable[[dict[str, Any]], bool] | None = None   # host answer to the agent's permission requests


@dataclass
class Receipt:
    task_id: str
    status: str            # disabled | cancelled | agent_failed | no_changes | tests_failed | proposed | error
    branch: str = ""
    worktree: str = ""
    detail: str = ""
    test_rc: int | None = None
    diffstat: str = ""
    test_tail: str = ""
    seconds: float = 0.0


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120)


def is_protected(path: Path) -> bool:
    low = str(path.resolve()).lower()
    return any(m in low for m in PROTECTED_MARKERS)


def _run(cmd: list[str], cwd: Path, timeout: float, cancel: threading.Event) -> tuple[int | None, str]:
    """Run cmd (no shell); poll so cancel and timeout kill the process. rc None = killed."""
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace")
    out: list[str] = []
    stream = proc.stdout
    assert stream is not None
    reader = threading.Thread(target=lambda: out.append(stream.read()), daemon=True)
    reader.start()
    end = time.monotonic() + timeout
    while proc.poll() is None:
        if cancel.is_set() or time.monotonic() > end:
            proc.kill()
            proc.wait()
            reader.join(2)
            return None, "cancelled" if cancel.is_set() else "timeout"
        time.sleep(0.05)
    reader.join(5)
    return proc.returncode, "".join(out)


def _run_acp(task: FleetTask, wt: Path, timeout: float, cancel: threading.Event) -> tuple[int | None, str]:
    """One ACP turn in the worktree. rc 0 = the agent finished its turn (not a pass: the host tests decide)."""
    adapter = AcpAdapter(task.agent_cmd, name=task.task_id, enabled=True, cwd=str(wt), timeout=timeout,
                         approve=task.approve)
    stop = threading.Event()

    def watch() -> None:   # a fleet cancel reaches the agent at its next message (the adapter polls between lines)
        while not stop.wait(0.1):
            if cancel.is_set():
                adapter.cancel()
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        turn = asyncio.run(adapter.run_turn(task.acp_prompt))
    finally:
        stop.set()
    if turn.state == "cancelled":
        return None, "cancelled"
    if turn.state != "ok":
        return 1, f"{turn.state}: {turn.error}"[-300:]
    return 0, turn.text


def probe_agents(clis: tuple[str, ...] = AGENT_CLIS) -> list[dict[str, Any]]:
    """Installed check per agent CLI; never launches one, never guesses sign-in or quota."""
    return [{"agent": name, "installed": shutil.which(name) is not None, "auth": "unknown", "quota": "unknown"}
            for name in clis]


def fleet_worktrees(repo: str | Path) -> list[tuple[str, str]]:
    """(path, branch) of every fleet worktree git still knows about, e.g. after a crash. Nothing is removed here:
    the owner reviews them and removes worktree and branch by hand."""
    out = _git(Path(repo), "worktree", "list", "--porcelain").stdout
    found, path = [], ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[9:]
        elif line.startswith("branch refs/heads/star/fleet-"):
            found.append((path, line[len("branch refs/heads/"):]))
    return found


def run_task(repo: Path, base_ref: str, task: FleetTask, worktrees: Path, cancel: threading.Event,
             timeout: float = 1800) -> Receipt:
    t0 = time.monotonic()
    rec = Receipt(task.task_id, "error")
    if not task.enabled:
        rec.status = "disabled"
        return rec
    if cancel.is_set():
        rec.status = "cancelled"
        return rec
    if not _ID.match(task.task_id):
        rec.detail = "bad task id"
        return rec
    if not task.test_cmd:
        rec.detail = "no test command: a pass cannot be proven"
        return rec
    rec.branch = f"star/fleet-{task.task_id}"
    wt = worktrees / task.task_id
    rec.worktree = str(wt)
    try:
        with _WORKTREE_ADD:
            add = _git(repo, "worktree", "add", "-b", rec.branch, str(wt), base_ref)
        if add.returncode:
            rec.detail = add.stderr.strip()[-300:]
            return rec
        if task.acp_prompt:
            rc, out = _run_acp(task, wt, timeout, cancel)
        else:
            rc, out = _run(task.agent_cmd, wt, timeout, cancel)
        if rc is None:
            rec.status, rec.detail = "cancelled", out
            return rec
        if rc != 0:
            rec.status, rec.detail = "agent_failed", f"agent exit {rc}: {out[-300:]}"
            return rec
        _git(wt, "add", "-A")
        stat = _git(wt, "diff", "--cached", "--stat").stdout.strip()
        if not stat:
            rec.status = "no_changes"
            return rec
        rec.diffstat = stat
        trc, tout = _run(task.test_cmd, wt, timeout, cancel)
        rec.test_rc, rec.test_tail = trc, tout[-600:]
        if trc is None:
            rec.status, rec.detail = "cancelled", tout
        elif trc != 0:
            rec.status = "tests_failed"
        else:
            rec.status = "proposed"
            rec.detail = "review the diff; the fleet never merges"
    except Exception as exc:  # a crashed worker must not take the fleet down
        rec.status, rec.detail = "error", f"{type(exc).__name__}: {exc}"[:300]
    finally:
        rec.seconds = round(time.monotonic() - t0, 2)
    return rec


@dataclass
class FleetResult:
    slots: int
    reason: str
    receipts: list[Receipt] = field(default_factory=list)


def run_fleet(repo: str | Path, tasks: list[FleetTask], *, base_ref: str = "HEAD", worktrees: str | Path | None = None,
              enabled: bool | None = None, resources: dict | None = None, cancel: threading.Event | None = None,
              timeout: float = 1800, receipts_file: str | Path | None = None, **plan_kw) -> FleetResult:
    """Run every enabled task in its own worktree, at most as many at once as live resources allow.
    With ``receipts_file`` every receipt (plus the measured resources and slot count) is appended as one JSON line."""
    if not fleet_enabled(enabled):
        return FleetResult(0, "disabled: set STAR_AGENT_FLEET=1 to opt in")
    repo = Path(repo)
    if is_protected(repo):
        return FleetResult(0, "refused: protected project")
    res = resources or sample_resources()
    n, reason = plan_slots(res, **plan_kw)
    if n == 0:
        return FleetResult(0, reason)
    wts = Path(worktrees) if worktrees else repo.parent / (repo.name + "-fleet")
    wts.mkdir(parents=True, exist_ok=True)
    cancel = cancel or threading.Event()
    with ThreadPoolExecutor(max_workers=n) as pool:
        recs = list(pool.map(lambda t: run_task(repo, base_ref, t, wts, cancel, timeout), tasks))
    if receipts_file:
        with open(receipts_file, "a", encoding="utf-8") as fh:
            for rec in recs:
                fh.write(json.dumps({**asdict(rec), "resources": res, "slots": n, "at": time.time()}) + "\n")
    return FleetResult(n, reason, recs)
