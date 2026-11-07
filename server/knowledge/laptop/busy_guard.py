"""Busy guard for the laptop's GPU workers: the owner's games and streams always win.

Runs in the owner's logon session (a hidden scheduled task; a session-0 task cannot see windows). Every `poll_seconds`
it asks "is the owner using this machine?" with the same probes as the Litha mesh node (server/mesh/node/node_agent.py,
copied next to this file): a known game with a window, a stream/VR program, a full-screen program in front, other
programs' GPU load, or the FAKE_BUSY test file. When yes it writes PAUSE (the supervisors run-gpu-worker.cmd and
run-rerank-worker.cmd wait while it exists) and kills whatever listens on the worker ports (taskkill /T), so the video
memory is free within about one poll and the knowledge service falls back to brain 1 (connection refused = instant).
The workers come back after `resume_seconds` without a busy look (PAUSE is deleted, the supervisors restart them).

    python busy_guard.py run              the guard (one copy at a time)
    python busy_guard.py once             print one look (reason or "free") and exit
    python busy_guard.py status           print status.json

Files next to this script: FAKE_BUSY (test switch: busy while it exists), busy_guard.json (optional config overlay),
status.json (state, reason, time; rewritten every 30 s). The PAUSE file lives in the parent folder (one level up).
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
for _folder in (HERE.parents[1] / "mesh" / "node", HERE):          # in the repo, then (deployed) next to this script
    if (_folder / "node_agent.py").exists():
        sys.path.insert(0, str(_folder))
import node_agent  # noqa: E402  (the mesh node's probes; install-busy-guard.cmd copies it next to this script)

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULTS: dict = {
    "poll_seconds": 2.0,
    "resume_seconds": 120,           # free this long before the workers come back
    "kill_ports": [8090],            # llama.cpp router (embed + rerank): runs in this logon session, killed from here
    "watch_ports": [8090, 8092],     # plus the PyTorch rerank worker, which exits by itself while PAUSE exists (it runs
                                     # in a session-0 task whose process this session may not terminate)
    "base_dir": "..",                # the folder that holds the workers (everything under it counts as ours)
    "gpu_other_percent": 40,         # other programs' 3D/compute load (sum over their processes) ...
    "gpu_other_looks": 3,            # ... on this many looks in a row
    "gpu_poll_seconds": 2.0,
    "games": ["VALORANT-Win64-Shipping.exe", "VALORANT.exe", "FortniteClient-Win64-Shipping.exe",
              "RocketLeague.exe", "Marvel-Win64-Shipping.exe"],
    "log_max_bytes": 5_000_000,
}


def load_config() -> dict:
    config = dict(DEFAULTS)
    path = HERE / "busy_guard.json"
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


def probe_config(config: dict) -> dict:
    """node_agent's program rules plus the games installed on this laptop."""
    merged = dict(node_agent.DEFAULTS)
    merged["block_processes"] = list(merged["block_processes"]) + list(config["games"])
    return merged


class GpuOthers:
    """Other programs' GPU load from the Windows 'GPU Engine' performance counters (one counter per process and
    engine, instance names look like pid_1234_luid_..._engtype_3D). The per-process numbers let us leave out our own
    workers, which nvidia-smi's total cannot."""

    def __init__(self):
        import ctypes
        import ctypes.wintypes as wt
        self.ctypes = ctypes
        self.pdh = ctypes.WinDLL("pdh")
        self.query = ctypes.c_void_p()
        self.counter = ctypes.c_void_p()
        self.ok = (self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) == 0 and
                   self.pdh.PdhAddEnglishCounterW(self.query, r"\GPU Engine(*)\Utilization Percentage", 0,
                                                  ctypes.byref(self.counter)) == 0)
        if self.ok:
            self.pdh.PdhCollectQueryData(self.query)

        class Item(ctypes.Structure):
            _fields_ = [("name", wt.LPWSTR), ("status", wt.DWORD), ("pad", wt.DWORD), ("value", ctypes.c_double)]
        self.Item = Item

    def per_pid(self) -> dict[int, float]:
        """{pid: percent} summed over 3D and compute engines since the previous call ({} when unavailable)."""
        if not self.ok:
            return {}
        c = self.ctypes
        self.pdh.PdhCollectQueryData(self.query)
        size, count = c.c_ulong(0), c.c_ulong(0)
        self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, c.byref(size), c.byref(count), None)   # DOUBLE
        if not size.value:
            return {}
        buf = c.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x200, c.byref(size), c.byref(count), buf) != 0:
            return {}
        items = c.cast(buf, c.POINTER(self.Item))
        out: dict[int, float] = {}
        for i in range(count.value):
            m = re.match(r"pid_(\d+)_.*engtype_(3D|Compute\w*|Cuda\w*)$", items[i].name or "")
            if m:
                out[int(m.group(1))] = out.get(int(m.group(1)), 0.0) + items[i].value
        return out


def listening_pids(ports: list[int]) -> set[int]:
    """Process ids that listen on these TCP ports (netstat -ano)."""
    try:
        text = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=10,
                              creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    found = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].rsplit(":", 1)[-1].isdigit():
            if int(parts[1].rsplit(":", 1)[-1]) in ports and parts[4].isdigit():
                found.add(int(parts[4]))
    return found


def kill_workers(ports: list[int]) -> list[int]:
    """taskkill /T /F the processes behind these ports; returns the pids that were really killed."""
    killed = []
    for pid in sorted(listening_pids(ports)):
        done = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15,
                              creationflags=NO_WINDOW)
        if done.returncode == 0:
            killed.append(pid)
    return killed


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


class Guard:
    def __init__(self, config: dict, home: Path = HERE, probe=None, gpu=None, clock=time.monotonic,
                 kill=kill_workers):
        self.config = config
        self.home = home
        self.base = (home / config["base_dir"]).resolve()
        self.pause = self.base / "PAUSE"
        self.fake = home / "FAKE_BUSY"
        self.log_path = self.base / "logs" / "busy-guard.log"
        self.status_path = home / "status.json"
        self.probe = probe if probe is not None else node_agent.WindowsProbe()
        self.gpu = gpu if gpu is not None else GpuOthers()
        self.clock = clock
        self.kill = kill
        self.pconfig = probe_config(config)
        self.paused = False
        self.reason = ""
        self.last_busy = 0.0
        self.gpu_looks = 0
        self.gpu_others = 0.0
        self.last_gpu = 0.0
        self.last_status = 0.0
        self.last_enforce = 0.0

    # -- output ----------------------------------------------------------------------------------------------------
    def log(self, text: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > self.config["log_max_bytes"]:
                self.log_path.replace(self.log_path.with_suffix(".log.old"))
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
        except OSError:
            pass

    def write_status(self, now: float, force: bool = False) -> None:
        if not force and now - self.last_status < 30:
            return
        self.last_status = now
        try:
            self.status_path.write_text(json.dumps({"state": "paused" if self.paused else "serving",
                                                    "reason": self.reason, "gpu_others": round(self.gpu_others, 1),
                                                    "ts": time.time()}), encoding="utf-8")
        except OSError:
            pass

    # -- one look --------------------------------------------------------------------------------------------------
    def look(self) -> str:
        """Why the machine is busy ('' when it is free). Cheap rules first."""
        if self.fake.exists():
            return "FAKE_BUSY test file"
        procs = self.probe.processes()
        own = {pid for pid, name in procs.items() if self.probe.exe_path(pid, name).lower().startswith(str(self.base).lower())}
        own.add(os.getpid())
        reason = node_agent.program_reason(self.pconfig, procs, own, self.probe.exe_path, self.probe.windows,
                                           self.probe.fullscreen())
        if reason:
            return reason
        now = self.clock()
        if now - self.last_gpu >= self.config["gpu_poll_seconds"]:
            self.last_gpu = now
            others = sum(v for pid, v in self.gpu.per_pid().items() if pid not in own)
            self.gpu_looks = self.gpu_looks + 1 if others >= self.config["gpu_other_percent"] else 0
            self.gpu_others = others
        if self.gpu_looks >= self.config["gpu_other_looks"]:
            return f"other programs use the GPU ({self.gpu_others:.0f}%)"
        return ""

    def step(self) -> str:
        """One poll: look, then pause or resume. Returns the state: 'paused' or 'serving'."""
        now = self.clock()
        reason = self.look()
        if reason:
            self.last_busy = now
            if not self.paused:
                self.paused = True
                self.reason = reason
                self.pause.write_text(f"{reason}\n", encoding="utf-8")
                hit = self.kill(self.config["kill_ports"])
                self.last_enforce = now
                self.log(f"BUSY: {reason}; PAUSE written, killed pids {hit}")
                self.write_status(now, force=True)
            else:
                self.reason = reason
                if now - self.last_enforce >= 5:               # a supervisor may have raced the PAUSE file
                    self.last_enforce = now
                    open_ports = [p for p in self.config["watch_ports"] if port_open(p)]
                    if open_ports:                         # a supervisor raced the PAUSE file, or a worker is slow to exit
                        self.log(f"ports {open_ports} still listening while busy; killed pids "
                                 f"{self.kill([p for p in open_ports if p in self.config['kill_ports']])}")
        elif self.paused and now - self.last_busy >= self.config["resume_seconds"]:
            self.paused = False
            self.reason = ""
            try:
                self.pause.unlink()
            except FileNotFoundError:
                pass
            self.log(f"free for {self.config['resume_seconds']} s: PAUSE removed, supervisors restart the workers")
            self.write_status(now, force=True)
        self.write_status(now)
        return "paused" if self.paused else "serving"

    def run(self) -> int:
        # a PAUSE left by an earlier run is not ours to keep: decide again from scratch
        if self.pause.exists():
            self.log("stale PAUSE found at start; deciding again")
            self.pause.unlink()
        self.log("guard started")
        self.write_status(self.clock(), force=True)
        while True:               # on exit PAUSE stays (safe for the owner); the next start decides again
            try:
                self.step()
            except Exception as exc:                          # never die: a dead guard leaves the owner unprotected
                self.log(f"look failed: {exc!r}")
            time.sleep(self.config["poll_seconds"])


def single_instance(name: str = "Local\\STAR-laptop-busy-guard") -> bool:
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, name)
    return ctypes.windll.kernel32.GetLastError() != 183         # ERROR_ALREADY_EXISTS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["run", "once", "status"])
    args = parser.parse_args(argv)
    if args.command == "status":
        print((HERE / "status.json").read_text(encoding="utf-8"))
        return 0
    guard = Guard(load_config())
    if args.command == "once":
        print(guard.look() or "free")
        return 0
    if not single_instance():
        print("another busy guard is running")
        return 0
    return guard.run()


if __name__ == "__main__":
    sys.exit(main())
