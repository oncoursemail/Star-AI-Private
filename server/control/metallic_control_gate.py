#!/usr/bin/env python3
"""Metallic Control host gate: the ONLY things the Metallic Control collector may read or do on a server, as a fixed
allow-list.

Runs as the LXD host's login user (standard library only, Python 3.10+). The collector's own SSH key sits in that
user's authorized_keys as `restrict,from="<collector>",command="<this file> --config <gate.json>"`, so the key can do
nothing but name one of the verbs below (`server/control/deploy.sh gate` installs it):

    stream          one JSON line every 5 s until the connection closes (host CPU/RAM/disk/network/temperatures,
                    per-container CPU and memory from the cgroup files); every 60 s also the top processes, STAR's
                    own facts (the Discord gate's `facts` verb inside the brain container), backup and runner state;
                    every 5 min the container inventory with limits. From the brain's journal (`print_timing` lines):
                    each finished request's timings, and the live tokens/s of every slot that is generating.
    act NAME        one allow-listed action that this host's gate.json enables (see ACTIONS); prints one JSON object.
    ping            {"ok": true}

Nothing here needs sudo, nothing takes the quiet lock, and no command line is ever built from the collector's text:
a verb is looked up in a table or refused.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

PROC = Path(os.environ.get("MC_GATE_PROC", "/proc"))
SYS = Path(os.environ.get("MC_GATE_SYS", "/sys"))
INTERVAL = 5.0
SLOW_EVERY = 60.0
INVENTORY_EVERY = 300.0
LIFETIME = 6 * 3600          # the collector reconnects; a stream never lives forever
LXC = "/usr/sbin/lxc"
NIC = re.compile(r"^(en|eth|wl|eno|enp)[A-Za-z0-9]*$")
DISK = re.compile(r"^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+|xvd[a-z]+)$")
TIMING = re.compile(r"^(?:\[(?P<port>\d+)\] )?.*?slot print_timing: id +(?P<slot>\d+) \| task (?P<task>\d+) \| +"
                    r"(?P<what>prompt eval time|eval time|total time) = +(?P<ms>[0-9.]+) ms / +(?P<tokens>\d+) tokens")
PROGRESS = re.compile(r"^(?:\[(?P<port>\d+)\] )?.*?slot print_timing: id +(?P<slot>\d+) \| task (?P<task>\d+) \| +"
                      r"n_gen = +(?P<n>\d+), tg = +(?P<tg>[0-9.]+) t/s, tg_3s = +(?P<tg3>[0-9.]+) t/s")

# Actions: name -> (what it runs, given the host config). Each host enables a subset in gate.json "actions".
STAR_RESTART = ("star-brain", "star-knowledge", "star-search-gateway", "star-night-school", "star-ns-brain",
                "star-discord", "searxng")


def _now() -> float:
    return time.time()


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False)


def _read(path: Path, limit: int = 1_000_000) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


# ------------------------------------------------------------------------------------------------ /proc parsers

def parse_stat(text: str) -> dict:
    """/proc/stat -> {"cpu": [user, nice, system, idle, iowait, irq, softirq, steal], "ncpu": n}."""
    out: dict = {"cpu": None, "ncpu": 0}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "cpu":
            out["cpu"] = [int(v) for v in parts[1:9]]
        elif re.fullmatch(r"cpu\d+", parts[0]):
            out["ncpu"] += 1
    return out


def parse_meminfo(text: str) -> dict:
    """/proc/meminfo -> bytes for total, available, swap_total, swap_free."""
    keys = {"MemTotal": "total", "MemAvailable": "available", "SwapTotal": "swap_total", "SwapFree": "swap_free"}
    out = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if name in keys:
            out[keys[name]] = int(rest.split()[0]) * 1024
    return out


def parse_net_dev(text: str) -> dict:
    """/proc/net/dev -> {iface: [rx_bytes, tx_bytes]} for physical NICs only (no lo, veth, bridges)."""
    out = {}
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        fields = rest.split()
        if NIC.match(name) and len(fields) >= 9:
            out[name] = [int(fields[0]), int(fields[8])]
    return out


def parse_diskstats(text: str) -> dict:
    """/proc/diskstats -> {disk: [sectors_read, sectors_written]} for whole disks (512-byte sectors)."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 10 and DISK.match(f[2]):
            out[f[2]] = [int(f[5]), int(f[9])]
    return out


def parse_loadavg(text: str) -> list[float]:
    parts = text.split()
    return [float(p) for p in parts[:3]] if len(parts) >= 3 else []


def parse_psi(text: str) -> float | None:
    match = re.search(r"^some avg10=([0-9.]+)", text, re.M)
    return float(match.group(1)) if match else None


def parse_cpu_stat(text: str) -> int | None:
    match = re.search(r"^usage_usec (\d+)", text, re.M)
    return int(match.group(1)) if match else None


def parse_proc_pid_stat(text: str) -> tuple[str, int] | None:
    """/proc/<pid>/stat -> (comm, utime+stime ticks). comm may contain spaces and parentheses."""
    left, right = text.find("("), text.rfind(")")
    if left < 0 or right < left:
        return None
    rest = text[right + 2:].split()
    try:
        return text[left + 1:right][:32], int(rest[11]) + int(rest[12])
    except (IndexError, ValueError):
        return None


def container_of(cgroup_text: str) -> str:
    match = re.search(r"lxc\.payload\.([A-Za-z0-9-]+)", cgroup_text)
    return match.group(1) if match else ""


def temperatures(sys_root: Path = SYS) -> dict:
    """{"<chip>/<label>": celsius}. Missing sensors are simply absent."""
    out: dict = {}
    for chip in sorted((sys_root / "class" / "hwmon").glob("hwmon*")):
        name = _read(chip / "name", 64).strip() or chip.name
        for sensor in sorted(chip.glob("temp*_input")):
            raw = _read(sensor, 32).strip()
            if not raw.lstrip("-").isdigit():
                continue
            label = _read(Path(str(sensor).replace("_input", "_label")), 64).strip() or sensor.name.split("_")[0]
            key = f"{name}/{label}"
            value = round(int(raw) / 1000, 1)
            out[key] = max(value, out.get(key, value))
    return out


def filesystems(mounts: list[str]) -> dict:
    out = {}
    for mount in mounts:
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        out[mount] = [usage.total, usage.used, usage.free]      # df: Use% = used / (used + free)
    return out


def containers(sys_root: Path = SYS) -> dict:
    """Per LXD container: cumulative CPU microseconds, memory now and its limit (bytes, None = no limit)."""
    out = {}
    for group in sorted((sys_root / "fs" / "cgroup").glob("lxc.payload.*")):
        cpu = parse_cpu_stat(_read(group / "cpu.stat", 4096))
        mem = _read(group / "memory.current", 64).strip()
        limit = _read(group / "memory.max", 64).strip()
        inactive = re.search(r"^inactive_file (\d+)", _read(group / "memory.stat", 8192), re.M)
        used = int(mem) - (int(inactive.group(1)) if inactive else 0) if mem.isdigit() else None
        out[group.name.removeprefix("lxc.payload.")] = {          # used = current - inactive page cache (as docker)
            "cpu_usec": cpu, "mem": used, "mem_max": int(limit) if limit.isdigit() else None}
    return out


def sample(cfg: dict) -> dict:
    stat = parse_stat(_read(PROC / "stat"))
    return {"kind": "sample", "t": round(_now(), 3), "cpu": stat["cpu"], "ncpu": stat["ncpu"],
            "load": parse_loadavg(_read(PROC / "loadavg")), "mem": parse_meminfo(_read(PROC / "meminfo")),
            "net": parse_net_dev(_read(PROC / "net" / "dev")), "disk": parse_diskstats(_read(PROC / "diskstats")),
            "fs": filesystems(cfg.get("mounts", ["/"])), "temps": temperatures(),
            "psi_cpu": parse_psi(_read(PROC / "pressure" / "cpu")), "ct": containers()}


class TopProcesses:
    """CPU share per process between two looks (60 s apart), top N, with the container it runs in."""

    def __init__(self, top: int = 10):
        self.top, self.before, self.at = top, {}, None
        self.hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

    def __call__(self) -> list[dict]:
        now, current = _now(), {}
        for entry in PROC.glob("[0-9]*"):
            parsed = parse_proc_pid_stat(_read(entry / "stat", 2048))
            if parsed:
                current[entry.name] = parsed
        rows = []
        if self.at is not None and now > self.at:
            span = (now - self.at) * self.hz
            for pid, (comm, ticks) in current.items():
                old = self.before.get(pid)
                if old and old[0] == comm and ticks >= old[1]:
                    rows.append((ticks - old[1], pid, comm))
            rows.sort(reverse=True)
            rows = [{"pid": int(pid), "comm": comm, "cpu_pct": round(100 * delta / span, 1),
                     "rss": _rss(pid), "container": container_of(_read(PROC / pid / "cgroup", 4096))}
                    for delta, pid, comm in rows[:self.top] if delta > 0]
        self.before, self.at = current, now
        return rows


def _rss(pid: str) -> int | None:
    match = re.search(r"^VmRSS:\s+(\d+) kB", _read(PROC / pid / "status", 8192), re.M)
    return int(match.group(1)) * 1024 if match else None


# ------------------------------------------------------------------------------------------------ STAR, backups, runners

def star_facts(cfg: dict, run=_run) -> dict | None:
    star = cfg.get("star")
    if not star:
        return None
    result = run([LXC, "exec", star["container"], "--", "/usr/bin/python3", star["gate"], "facts"], timeout=30)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return {"ok": False, "error": f"facts exit {result.returncode}"}
    return data.get("facts") if isinstance(data, dict) and data.get("ok") else {"ok": False, "error": "facts refused"}


def backups(cfg: dict) -> list[dict]:
    out = []
    for item in cfg.get("backups", []):
        status = _json_file(Path(os.path.expanduser(item["status"])))
        config = _json_file(Path(os.path.expanduser(item["config"]))) if item.get("config") else {}
        row = {"set": item["set"], "where": item.get("where", ""), "schedule": item.get("schedule", ""),
               "max_repository_bytes": config.get("max_repository_bytes")}
        if isinstance(status, dict):
            keep = ("last_attempt_utc", "last_success_utc", "latest_complete", "in_progress", "data_added",
                    "data_added_packed", "repository_bytes", "last_retention_utc", "last_snapshot_id")
            row.update({k: status.get(k) for k in keep})
            row["last_snapshot_id"] = str(status.get("last_snapshot_id") or "")[:8]
            err = status.get("last_error")
            row["last_error"] = ({"at": err.get("at"), "action": err.get("action"),
                                  "message": str(err.get("message", ""))[:160]} if isinstance(err, dict) else None)
            for key in ("last_restore_verification", "baseline_verification", "last_ingest_validation"):
                ver = status.get(key)
                if isinstance(ver, dict):
                    row[key] = {k: ver.get(k) for k in ("verified_utc", "files", "sqlite_databases", "source_bytes")}
        else:
            row["error"] = "status file missing or unreadable"
        out.append(row)
    return out


def forge_backups(cfg: dict, run=_run) -> dict | None:
    forge = cfg.get("forge_backups")
    if not forge:
        return None
    result = run([LXC, "exec", forge["container"], "--", "find", forge["path"], "-maxdepth", "1", "-type", "f",
                  "-name", "forgejo-*", "-printf", "%T@ %s %f\\n"], timeout=20)
    files = []
    for line in result.stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[1].isdigit():
            files.append({"t": float(parts[0]), "bytes": int(parts[1]), "name": parts[2][:80]})
    files.sort(key=lambda f: f["t"])
    return {"ok": result.returncode == 0, "files": files[-6:], "count": len(files),
            "total_bytes": sum(f["bytes"] for f in files)}


def runners(cfg: dict, run=_run) -> list[dict]:
    out = []
    for item in cfg.get("runners", []):
        state = run([LXC, "exec", item["container"], "--", "systemctl", "is-active", item["unit"]], timeout=15)
        out.append({"runner": item["name"], "kind": item["kind"], "state": state.stdout.strip() or "unknown"})
    return out


def user_timers(cfg: dict, run=_run) -> list[dict]:
    names = cfg.get("timers", [])
    if not names:
        return []
    result = run(["systemctl", "--user", "show", "-p", "Id,NextElapseUSecRealtime,LastTriggerUSec", *names])
    rows, row = [], {}
    for line in result.stdout.splitlines() + [""]:
        if not line.strip():
            if row.get("Id"):
                rows.append({"unit": row["Id"], "next": row.get("NextElapseUSecRealtime", ""),
                             "last": row.get("LastTriggerUSec", "")})
            row = {}
            continue
        key, _, value = line.partition("=")
        row[key] = value
    return rows


def inventory(cfg: dict, run=_run) -> list[dict]:
    result = run([LXC, "query", "/1.0/instances?recursion=1"], timeout=30)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return []
    out = []
    for inst in data if isinstance(data, list) else []:
        conf = inst.get("expanded_config") or inst.get("config") or {}
        out.append({"name": inst.get("name"), "status": inst.get("status"), "type": inst.get("type"),
                    "limits": {k.removeprefix("limits."): v for k, v in conf.items() if k.startswith("limits.")},
                    "autostart": conf.get("boot.autostart")})
    return out


# ------------------------------------------------------------------------------------------------ request timings

class Timings:
    """Turns the llama.cpp `print_timing` triplets into one row per finished request."""

    def __init__(self):
        self.pending: dict = {}
        self.done: list[dict] = []
        self.live: dict = {}            # (port, slot) -> latest progress line of a request still generating
        self.lock = threading.Lock()

    def feed(self, line: str, now: float | None = None) -> dict | None:
        now = now if now is not None else _now()
        prog = PROGRESS.match(line.strip())
        if prog:                        # llama.cpp prints n_gen / tg / tg_3s every 3 s while a slot generates
            with self.lock:
                self.live[(prog.group("port") or "", int(prog.group("slot")))] = {
                    "port": prog.group("port") or "", "slot": int(prog.group("slot")), "task": int(prog.group("task")),
                    "n_gen": int(prog.group("n")), "tg": float(prog.group("tg")), "tg3": float(prog.group("tg3")),
                    "t": round(now, 3)}
            return None
        match = TIMING.match(line.strip())
        if not match:
            return None
        key = (match.group("port") or "", match.group("task"))
        row = self.pending.setdefault(key, {"port": match.group("port") or "", "slot": int(match.group("slot")),
                                            "task": int(match.group("task"))})
        what, ms, tokens = match.group("what"), float(match.group("ms")), int(match.group("tokens"))
        if what == "prompt eval time":
            row["prompt_ms"], row["prompt_tokens"] = ms, tokens
        elif what == "eval time":
            row["eval_ms"], row["eval_tokens"] = ms, tokens
        else:
            row["total_ms"] = ms
            row["t"] = round(now, 3)
            del self.pending[key]
            with self.lock:
                self.done.append(row)
                del self.done[:-200]
                self.live.pop((row["port"], row["slot"]), None)
            return row
        return None

    def take(self) -> list[dict]:
        with self.lock:
            rows, self.done = self.done, []
        return rows

    def generating(self, now: float | None = None) -> list[dict]:
        """Slots that logged progress in the last 10 s (a request that ends without timing lines ages out)."""
        now = now if now is not None else _now()
        with self.lock:
            for key in [k for k, v in self.live.items() if now - v["t"] > 10]:
                del self.live[key]
            return list(self.live.values())


def follow_journal(cfg: dict, timings: Timings) -> subprocess.Popen | None:
    star = cfg.get("star")
    if not star or not star.get("journal_unit"):
        return None
    proc = subprocess.Popen([LXC, "exec", star["container"], "--", "journalctl", "-u", star["journal_unit"], "-f",
                             "-n", "0", "-o", "cat", "--grep", "print_timing"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
                            bufsize=1)

    def pump():
        for line in proc.stdout:
            timings.feed(line)

    threading.Thread(target=pump, daemon=True).start()
    return proc


# ------------------------------------------------------------------------------------------------ verbs

def stream(cfg: dict, out=sys.stdout, clock=time.monotonic, sleep=time.sleep, lifetime: float = LIFETIME) -> int:
    timings = Timings()
    child = follow_journal(cfg, timings)
    tops = TopProcesses()
    start = clock()
    last_slow = last_inv = -1e9
    try:
        while clock() - start < lifetime:
            tick = clock()
            row = sample(cfg)
            row["machine"] = cfg.get("machine", "")
            reqs = timings.take()
            if reqs:
                row["reqs"] = reqs
            if child is not None:
                row["gen"] = timings.generating()
            if tick - last_slow >= SLOW_EVERY:
                last_slow = tick
                row["slow"] = {"procs": tops(), "facts": star_facts(cfg), "backups": backups(cfg),
                               "runners": runners(cfg), "timers": user_timers(cfg)}
            if tick - last_inv >= INVENTORY_EVERY:
                last_inv = tick
                row["inventory"] = inventory(cfg)
                fb = forge_backups(cfg)
                if fb is not None:
                    row["forge_backups"] = fb
            out.write(json.dumps(row, separators=(",", ":")) + "\n")
            out.flush()
            sleep(max(0.5, INTERVAL - (clock() - tick)))
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        if child is not None:
            child.terminate()
    return 0


def action_command(name: str, cfg: dict) -> list[str] | None:
    """The command for an allow-listed action, or None when this host does not offer it."""
    if name not in cfg.get("actions", []):
        return None
    star = cfg.get("star") or {}
    if name.startswith("restart:") and name[8:] in STAR_RESTART and star:
        return [LXC, "exec", star["container"], "--", "/usr/bin/python3", star["gate"], name]
    if name in ("ns-pause", "ns-resume") and star:
        return [LXC, "exec", star["container"], "--", "/usr/bin/python3", star["gate"], name]
    if name in ("litha-brain:on", "litha-brain:off"):  # helper next to this file (deploy.sh gate copies both)
        return ["/usr/bin/python3", str(Path(__file__).with_name("litha_brain.py")), name[12:]]
    if name.startswith("runner-start:") or name.startswith("runner-stop:"):
        verb, _, which = name.partition(":")
        for item in cfg.get("runners", []):
            if item["name"] == which:
                return [LXC, "exec", item["container"], "--", "systemctl", verb.split("-")[1], item["unit"]]
        return None
    if name.startswith("backup-now:"):
        which = name[11:]
        for item in cfg.get("backups", []):
            if item["set"] == which and item.get("unit"):
                return ["systemctl", "--user", "start", "--no-block", item["unit"]]
        fb = cfg.get("forge_backups")
        if fb and which == "forge":
            return [LXC, "exec", fb["container"], "--", "systemctl", "start", "--no-block", fb["unit"]]
    return None


def act(name: str, cfg: dict, run=_run) -> tuple[int, dict]:
    command = action_command(name, cfg)
    if command is None:
        return 2, {"ok": False, "action": name, "text": "refused: not an allowed action on this host"}
    result = run(command, timeout=150)
    text = (result.stdout.strip() or result.stderr.strip())[-400:]
    try:                                      # the STAR gate answers with its own JSON
        inner = json.loads(result.stdout)
        if isinstance(inner, dict) and "text" in inner:
            text = str(inner["text"])[:400]
    except ValueError:
        pass
    if not text:                              # systemctl --no-block and friends print nothing on success
        text = "started" if result.returncode == 0 else f"exit {result.returncode}"
    return (0 if result.returncode == 0 else 1), {"ok": result.returncode == 0, "action": name,
                                                  "exit": result.returncode, "text": text}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--config":
        cfg = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        argv = argv[2:]
    else:
        cfg = {}
    words = (os.environ.get("SSH_ORIGINAL_COMMAND") or " ".join(argv)).split()
    if words == ["ping"]:
        print(json.dumps({"ok": True, "machine": cfg.get("machine", "")}))
        return 0
    if words == ["stream"]:
        return stream(cfg)
    if len(words) == 2 and words[0] == "act":
        code, result = act(words[1], cfg)
        print(json.dumps(result, separators=(",", ":")))
        return code
    print(json.dumps({"ok": False, "text": "refused: not an allowed verb"}))
    return 2


def _json_file(path: Path):
    try:
        if path.stat().st_size > 256_000:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
