"""The Windows PC's reporter for Metallic Control (stdlib + ctypes; runs as the owner's normal user, no admin).

Every 10 s it pushes CPU, memory, disks, network and GPU numbers plus Sunshine and Windows-runner state to the
collector (POST /api/push with the push token, which can do nothing else). Every 5 minutes it adds the dev view only
this PC has: open GitHub PRs, recent GitHub Actions runs and runners (the owner's `gh` login stays here; only
titles, states and links leave), and the Metallic merge-queue state from ~/.metallic/projects.toml.

The collector answers each push with pending admin commands; the agent runs only verbs in LOCAL_ACTIONS and reports
the result with its next push. Config: ~/.metallic/control-agent.toml (url, push_token_file, star_ci_cmd, gh_repo).
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request

PUSH_EVERY = 10.0
DEV_EVERY = 300.0
SUNSHINE = "SunshineService"
BACKUP_TASK = "STAR compact recovery backup"
NO_WINDOW = 0x08000000


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          check=False, creationflags=NO_WINDOW if os.name == "nt" else 0)


# ------------------------------------------------------------------------------------------------ parsers (pure)

def parse_netstat_e(text: str) -> list[int] | None:
    """`netstat -e` -> [bytes received, bytes sent] (32-bit counters on Windows; the collector skips wraps)."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "Bytes" and parts[1].isdigit() and parts[2].isdigit():
            return [int(parts[1]), int(parts[2])]
    return None


def parse_nvidia(text: str) -> dict | None:
    """name, utilization.gpu, memory.used, memory.total, temperature.gpu, power.draw (csv, noheader, nounits)."""
    line = text.strip().splitlines()[0] if text.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 6:
        return None

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None
    mem_used, mem_total = num(parts[2]), num(parts[3])
    return {"name": parts[0][:60], "util": num(parts[1]),
            "mem_used": mem_used * 1048576 if mem_used is not None else None,
            "mem_total": mem_total * 1048576 if mem_total is not None else None,
            "temp": num(parts[4]), "power": num(parts[5])}


def parse_sc_state(text: str) -> str:
    match = re.search(r"STATE\s+:\s+\d+\s+(\w+)", text)
    return match.group(1).lower() if match else "unknown"


def summarize_backup(status) -> dict | None:
    if not isinstance(status, dict):
        return None
    receipt = status.get("receipt") if isinstance(status.get("receipt"), dict) else {}
    return {"last_attempt_utc": status.get("last_attempt_utc"), "last_success_utc": status.get("last_success_utc"),
            "latest_complete": status.get("latest_complete"), "in_progress": status.get("in_progress"),
            "error": str(status.get("error"))[:160] if status.get("error") else None,
            "snapshot": str(receipt.get("snapshot") or "")[:8]}


# ------------------------------------------------------------------------------------------------ Windows probes

class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32), ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64), ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64), ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64), ("ullAvailExtendedVirtual", ctypes.c_uint64)]


def cpu_times() -> list[int] | None:
    """[busy, total] in 100 ns units since boot (GetSystemTimes; kernel time includes idle)."""
    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None

    def v(ft):
        return (ft.hi << 32) | ft.lo
    total = v(kernel) + v(user)
    return [total - v(idle), total]


def memory() -> list[int] | None:
    stat = _MEMSTAT()
    stat.dwLength = ctypes.sizeof(_MEMSTAT)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return None
    return [stat.ullTotalPhys, stat.ullAvailPhys]


def fixed_drives() -> list[dict]:
    out = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:      # DRIVE_FIXED
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        out.append({"mount": root[:2], "total": usage.total, "used": usage.used})
    return out


def sample(run=_run) -> dict:
    gpu = run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
               "--format=csv,noheader,nounits"], timeout=10)
    runner = run(["tasklist", "/FI", "IMAGENAME eq Runner.Listener.exe", "/NH"], timeout=10)
    return {"cpu": cpu_times(), "ncpu": os.cpu_count(), "mem": memory(), "fs": fixed_drives(),
            "net": parse_netstat_e(run(["netstat", "-e"], timeout=10).stdout),
            "gpu": parse_nvidia(gpu.stdout) if gpu.returncode == 0 else None,
            "services": {"sunshine": parse_sc_state(run(["sc.exe", "query", SUNSHINE], timeout=10).stdout),
                         "pc_win_runner": "running" if "Runner.Listener" in runner.stdout else "stopped"}}


# ------------------------------------------------------------------------------------------------ dev view (gh, queue)

def gh_json(args: list[str], run=_run):
    result = run(["gh", *args], timeout=60)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


def dev_view(cfg: dict, run=_run) -> dict:
    repo = cfg.get("gh_repo", "")
    out: dict = {"repo": repo}
    if repo:
        prs = gh_json(["pr", "list", "--repo", repo, "--state", "open", "-L", "80", "--json",
                       "number,title,isDraft,updatedAt,author,headRefName,baseRefName,url"], run)
        runs = gh_json(["run", "list", "--repo", repo, "-L", "15", "--json",
                        "databaseId,displayTitle,workflowName,status,conclusion,headBranch,createdAt,updatedAt,url"], run)
        runners = gh_json(["api", f"repos/{repo}/actions/runners"], run)
        out["prs"] = [{"number": p.get("number"), "title": str(p.get("title", ""))[:140], "draft": p.get("isDraft"),
                       "updated": p.get("updatedAt"), "author": (p.get("author") or {}).get("login"),
                       "head": p.get("headRefName"), "base": p.get("baseRefName"), "url": p.get("url")}
                      for p in prs] if isinstance(prs, list) else None
        out["runs"] = [{"id": r.get("databaseId"), "title": str(r.get("displayTitle", ""))[:120],
                        "workflow": r.get("workflowName"), "status": r.get("status"), "conclusion": r.get("conclusion"),
                        "branch": r.get("headBranch"), "created": r.get("createdAt"), "updated": r.get("updatedAt"),
                        "url": r.get("url")} for r in runs] if isinstance(runs, list) else None
        out["runners"] = [{"name": r.get("name"), "status": r.get("status"), "busy": r.get("busy"),
                           "labels": [lab.get("name") for lab in r.get("labels", [])]}
                          for r in runners.get("runners", [])] if isinstance(runners, dict) else None
    try:
        from .. import status as status_mod
        from ..config import user_dir
        entries = tomllib.loads((user_dir() / "projects.toml").read_text(encoding="utf-8")).get("project", [])
        projects = []
        for entry in entries:
            p = status_mod.project(entry)
            projects.append({k: p.get(k) for k in ("name", "lang", "connected", "note", "target", "branch", "head",
                                                   "pending", "release")}
                            | {"checks": [{"verdict": c.get("verdict"), "started": c.get("started"), "red": c.get("red"),
                                           "branch": c.get("branch"), "seconds": (c.get("timings") or {}).get("total"),
                                           "cache_hit_rate": (c.get("cache") or {}).get("hit_rate")}
                                          for c in p.get("checks", [])[:3]],
                               "queue_runs": [{"started": c.get("started"), "target": c.get("target"), "seconds": c.get("seconds"),
                                               "applied": c.get("applied"), "merged": c.get("merged"),
                                               "entries": [{"branch": e.get("branch"), "status": e.get("status")}
                                                           for e in c.get("entries", [])[:12]]}
                                              for c in p.get("queue_runs", [])[:3]]})
        out["projects"] = projects
    except (OSError, ValueError, ImportError) as exc:
        out["projects_error"] = type(exc).__name__
    return out


# ------------------------------------------------------------------------------------------------ actions

def local_command(verb: str, cfg: dict) -> list[str] | None:
    table = {"sunshine-start": ["sc.exe", "start", SUNSHINE], "sunshine-stop": ["sc.exe", "stop", SUNSHINE],
             "backup-now:pc": ["schtasks", "/run", "/tn", BACKUP_TASK]}
    if verb in table:
        return table[verb]
    if verb in ("runner-start:pc-win", "runner-stop:pc-win") and cfg.get("star_ci_cmd"):
        return ["cmd.exe", "/c", cfg["star_ci_cmd"], "start" if verb.startswith("runner-start") else "stop"]
    return None


def run_command(cmd: dict, cfg: dict, run=_run) -> dict:
    command = local_command(str(cmd.get("verb", "")), cfg)
    if command is None:
        return {"audit": cmd.get("audit"), "ok": False, "exit": None, "text": "refused by the PC agent"}
    result = run(command, timeout=120)
    text = (result.stdout.strip() or result.stderr.strip()).splitlines()
    return {"audit": cmd.get("audit"), "ok": result.returncode == 0, "exit": result.returncode,
            "text": " ".join(t.strip() for t in text[-3:])[:300]}


# ------------------------------------------------------------------------------------------------ loop

def push(url: str, token: str, payload: dict) -> list[dict]:
    req = urllib.request.Request(url.rstrip("/") + "/api/push", data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=10) as reply:
        data = json.loads(reply.read(1_000_000))
    return [c for c in data.get("commands", []) if isinstance(c, dict)]


def load_config(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[1]) if len(argv) >= 2 and argv[0] == "--config" else Path.home() / ".metallic" / "control-agent.toml"
    cfg = load_config(path)
    with open(os.path.expanduser(cfg["push_token_file"]), encoding="utf-8") as handle:
        token = handle.readline().strip()
    log = Path(os.path.expandvars(cfg.get("log", r"%LOCALAPPDATA%\MetallicControl\agent.log")))
    log.parent.mkdir(parents=True, exist_ok=True)
    lock = open(log.with_name("agent.lock"), "a+")            # one agent per user: a second start exits quietly
    try:
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return 0
    results: list[dict] = []
    last_dev = -1e9
    status_file = Path(os.path.expandvars(cfg.get("backup_status", r"%LOCALAPPDATA%\StarRecovery\status.json")))
    while True:
        tick = time.monotonic()
        payload: dict = {"sample": sample(), "results": results}
        try:
            payload["backup"] = summarize_backup(json.loads(status_file.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            payload["backup"] = None
        if tick - last_dev >= DEV_EVERY:
            last_dev = tick
            payload["dev"] = dev_view(cfg)
        try:
            commands = push(cfg["url"], token, payload)
            results = [run_command(c, cfg) for c in commands]
        except (OSError, ValueError) as exc:
            if log.exists() and log.stat().st_size > 1_000_000:
                log.replace(log.with_suffix(".previous.log"))
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} push failed: {type(exc).__name__}\n")
            if "dev" in payload:
                last_dev = -1e9                 # resend the dev view with the next successful push
        time.sleep(max(1.0, PUSH_EVERY - (time.monotonic() - tick)))


if __name__ == "__main__":
    raise SystemExit(main())
