"""STAR GPU night turbo: a third night-school worker on this PC's graphics card, only while the owner is away.

    python turbo.py [--home DIR] run        the supervisor loop (the scheduled task starts it; one copy at a time)
    python turbo.py [--home DIR] status     what it is doing and why
    python turbo.py [--home DIR] off | on   the off switch (the file DIR/OFF); off also stops a running session
    python turbo.py [--home DIR] merge      combine server 1's outbox and this PC's into DIR/merged now
    python turbo.py [--home DIR] install | uninstall   the per-user scheduled task (no admin rights)

A session starts when the owner has not touched keyboard or mouse for `day_idle_minutes` (20), or for
`night_idle_minutes` (5) between `night_start` and `night_end` o'clock local time (01:00-08:00), and nothing else
uses the graphics card: no full-screen program or game in front, no other process busy on the card, no other
llama-server (the STAR app's "Use my GPU" switch), no program from `block_processes`, and the switch's own start
rules (free video memory, free RAM, ComfyUI). It stops within seconds when any of that changes: the owner touches
the PC, a game starts, the switch starts, or the OFF file appears.

A session = the GPU switch's own launcher (star/gpu_helper.GpuHelper: the same llama-server command line and
checks) + night school (`python -m nightschool run`) pointed at it, with its own share of the practice tasks
(`share`, default 2/4: server 1 has 0,1/4, server 2 3/4), the tasks server 1 already answered left out, server 1's
validation slice, the documentation and static Luau checks from server 1's knowledge service, and the unit tests in
server 1's container sandbox over SSH (model-written code never runs on this PC). Results are written in night
school's own report/outbox formats under DIR/ns and merged with server 1's outbox into DIR/merged after a session.

Private addresses and the SSH target live only in DIR/config.json, never in the repository.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULTS = {
    "app": str(REPO),                     # the repository copy night school runs (star/ and server/night_school/)
    "python": "",                         # python.exe for night school; "" = the one running this script
    "llama_server": "", "model": "",      # the GPU switch's llama-server.exe (CUDA build) and star-fast.gguf
    "key_file": "~/.star/server_api_key",  # the brain key, for server 1's knowledge service (read, never printed)
    "knowledge_url": "",                  # server 1's knowledge service, http://<address>:8091
    "server_ssh": "",                     # user@address of server 1's LXD host (pool, state, sandbox, outbox)
    "container": "starai",
    "share": "2/4", "validation_share": 0.33,
    "day_idle_minutes": 20, "night_idle_minutes": 5, "night_start": 1, "night_end": 8,
    "other_gpu_percent": 15,              # another process this busy on the card (two looks in a row) blocks
    "block_processes": [],                # program names (e.g. "RobloxPlayerBeta.exe") that always block
    "back_seconds": 10,                   # input this recent while running = the owner is back
}
POLL_S = 2.0
GPU_LOOK_S = 15.0
COOL_DOWN_S = 600.0
LOAD_S = 330.0
YIELD_WAIT_S = 4.0
LOCK_STALE_S = 1200                       # night school's rule: an older quiet lock is stale
SERVER_HOME = "/opt/star/learning"
TASK_NAME = "STAR GPU night turbo"
SYSTEM_GPU = {"dwm.exe", "csrss.exe", "system", "idle", "explorer.exe"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def default_home() -> Path:
    return Path(os.environ.get("STAR_TURBO_HOME") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "STAR-night-turbo")


def load_config(home: Path) -> dict:
    config = dict(DEFAULTS)
    path = home / "config.json"
    if path.is_file():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


# ---- what the PC is doing (Windows) --------------------------------------------------------------------------------
class Probe:
    def idle_seconds(self) -> float:
        """Seconds since the last keyboard or mouse input in this session."""
        import ctypes

        class Info(ctypes.Structure):
            _fields_ = [("size", ctypes.c_uint), ("time", ctypes.c_uint)]
        info = Info(ctypes.sizeof(Info), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return ((ctypes.windll.kernel32.GetTickCount() - info.time) & 0xFFFFFFFF) / 1000.0

    def fullscreen(self) -> bool:
        """A full-screen program, a Direct3D full-screen game or presentation mode is in front."""
        import ctypes
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return False
        return state.value in (2, 3, 4)       # QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE

    def processes(self) -> dict[int, str]:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=20,
                             creationflags=NO_WINDOW).stdout
        found = {}
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) > 1 and parts[1].isdigit():
                found[int(parts[1])] = parts[0]
        return found

    def gpu_users(self) -> dict[int, float]:
        """{pid: percent} of the card's 3D/compute engines (Windows GPU Engine counters; video and copy left out)."""
        command = ("(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue)"
                   ".CounterSamples | ForEach-Object { $_.InstanceName + '|' + $_.CookedValue }")
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout
        return parse_gpu_counters(out)


def parse_gpu_counters(text: str) -> dict[int, float]:
    use: dict[int, float] = {}
    for line in text.splitlines():
        name, _, value = line.strip().rpartition("|")
        if not name.startswith("pid_") or any(w in name.lower() for w in ("video", "copy", "security")):
            continue
        try:
            pid, percent = int(name.split("_")[1]), float(value)
        except (ValueError, IndexError):
            continue
        use[pid] = use.get(pid, 0.0) + percent
    return use


def night_now(config: dict, hour: int) -> bool:
    start, end = int(config["night_start"]), int(config["night_end"])
    return start <= hour < end if start <= end else (hour >= start or hour < end)


# ---- the supervisor ------------------------------------------------------------------------------------------------
class Turbo:
    def __init__(self, home: Path, config: dict, *, probe=None, helper=None, popen=subprocess.Popen, sync=None,
                 merge=None, server_lock=None, clock=time.monotonic, hour=lambda: time.localtime().tm_hour):
        from star.gpu_helper import GpuHelper
        self.home, self.config = Path(home), config
        self.ns = self.home / "ns"
        self.probe = probe or Probe()
        self.helper = helper or GpuHelper()
        self._popen, self._clock, self._hour = popen, clock, hour
        self._sync = sync or (lambda: sync_from_server(self.config, self.ns))
        self._merge = merge or (lambda: merge_now(self.config, self.home))
        self._server_lock = server_lock or (lambda: quiet_lock_held(self.config))
        self.state = "waiting"                # waiting -> loading -> running -> waiting
        self.reason = ""
        self.worker = None
        self.started = 0.0
        self.cool_until = -1e18
        self.gpu_at, self.gpu_hot = -1e18, 0
        self.answers_at_start = 0
        self.ran_at = 0.0
        self.next_look = -1e18                # programs and card are looked at once a minute while they block
        self.block_text = ""

    # -- logging and status ------------------------------------------------------------------------------------------
    def log(self, text: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + text
        with open(self.home / "turbo.log", "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _status(self) -> None:
        (self.home / "STATUS.txt").write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.state}: {self.reason}\n",
                                              encoding="utf-8")

    def _say(self, state: str, reason: str) -> None:
        if (state, reason.split(" (")[0]) != (self.state, self.reason.split(" (")[0]):    # not every idle minute
            self.log(f"{state}: {reason}" if reason else state)
        self.state, self.reason = state, reason
        self._status()

    # -- the rules ---------------------------------------------------------------------------------------------------
    def _own_pids(self) -> set[int]:
        return {p.pid for p in (getattr(self.helper, "process", None), self.worker) if p is not None}

    def _program_blocker(self) -> str:
        """A game in front, another llama-server (the app's GPU switch), or a program from block_processes."""
        if self.probe.fullscreen():
            return "a full-screen program or game is in front"
        names = self.probe.processes()
        own = self._own_pids()
        blocked = {n.lower() for n in self.config["block_processes"]}
        for pid, name in names.items():
            if pid in own:
                continue
            if name.lower() == "llama-server.exe":
                return "another llama-server is running (the STAR app's GPU switch?)"
            if name.lower() in blocked:
                return f"{name} is running"
        self._names = names
        return ""

    def _gpu_blocker(self, *, force: bool = False) -> str:
        """Another process busy on the card, at two looks in a row (looks every GPU_LOOK_S while running)."""
        now = self._clock()
        if not force and now - self.gpu_at < GPU_LOOK_S:
            return ""
        self.gpu_at = now
        own, names = self._own_pids(), getattr(self, "_names", {})
        busy = [(p, pct) for p, pct in self.probe.gpu_users().items()
                if p not in own and names.get(p, "").lower() not in SYSTEM_GPU and pct >= self.config["other_gpu_percent"]]
        self.gpu_hot = self.gpu_hot + 1 if busy else 0
        if self.gpu_hot >= 2:
            pid, pct = max(busy, key=lambda b: b[1])
            return f"{names.get(pid, 'pid ' + str(pid))} is using the graphics card ({pct:.0f}%)"
        return ""

    def start_blocker(self) -> str:
        if (self.home / "OFF").exists():
            return "off (the OFF file exists)"
        if self._clock() < self.cool_until:
            return "cooling down after a failure"
        night = night_now(self.config, self._hour())
        need = 60 * float(self.config["night_idle_minutes" if night else "day_idle_minutes"])
        idle = self.probe.idle_seconds()
        if idle < need:
            return f"the owner is active (idle {int(idle // 60)} of {int(need // 60)} min{', night' if night else ''})"
        if self._clock() < self.next_look:
            return self.block_text
        found = self._lock() or self._program_blocker() or self._gpu_blocker(force=True)
        if found:
            self.next_look, self.block_text = self._clock() + 60, found
        return found or ("checking the graphics card again" if self.gpu_hot else "")

    def stop_reason(self) -> str:
        if (self.home / "OFF").exists():
            return "off switch"
        if self.probe.idle_seconds() < float(self.config["back_seconds"]):
            return "the owner is back"
        if self.worker is not None and self.worker.poll() is not None:
            return f"night school exited (code {self.worker.returncode})"
        state = self.helper.status()["state"]
        if self.state == "running" and state != "ready":
            return f"the model server is {state}: {self.helper.status()['text'][:120]}"
        if self.state == "loading" and state in ("failed", "busy", "off"):
            return "the model server did not start: " + self.helper.status()["text"][:160]
        if self._clock() - self.gpu_at >= GPU_LOOK_S:
            return self._lock() or self._program_blocker() or self._gpu_blocker()
        return ""

    def _lock(self) -> str:
        """Server 1's quiet lock (timing runs): the sessions use its knowledge service and sandbox, so they pause."""
        return "server 1's quiet lock is held" if self._server_lock() else ""

    # -- one step ----------------------------------------------------------------------------------------------------
    def tick(self) -> None:
        if self.state == "waiting":
            why = self.start_blocker()
            if why:
                self._say("waiting", why)
                return
            self._begin()
            return
        why = self.stop_reason()
        if why:
            self.end(why)
            return
        if self.state == "loading":
            if self.helper.status()["state"] == "ready":
                self._spawn_worker()
            elif self._clock() - self.started > LOAD_S:
                self.end("the model did not load in time", failed=True)

    def _begin(self) -> None:
        self._say("loading", "syncing the pool and loading the model")
        self.started = self._clock()
        self.gpu_hot = 0
        note = self._sync()
        if note:
            self.log("sync: " + note)
        if not (self.ns / "pool").is_dir():
            self.end("no practice pool (server 1 not reachable and nothing synced before)", failed=True)
            return
        settings = SimpleNamespace(use_my_gpu=True, gpu_helper_server=self.config["llama_server"],
                                   gpu_helper_model=self.config["model"], gpu_idle_minutes=24 * 60, comfy_port=8188)
        self.helper.configure(settings, self.home, start=True)

    def _spawn_worker(self) -> None:
        base = self.helper.lease()            # held for the whole session: the helper's own idle/busy stops stay off
        if not base:
            self.end("the model server was not ready", failed=True)
            return
        hold = self.ns / "data" / "HOLD"
        hold.unlink(missing_ok=True)
        self.answers_at_start = count_lines(self.ns / "data" / "attempts.jsonl")
        self.ran_at = self._clock()
        python = self.config["python"] or sys.executable.replace("pythonw.exe", "python.exe")
        env = {**os.environ, **worker_env(self.config, self.ns, base[:-3])}
        app = Path(self.config["app"])
        self.ns.mkdir(parents=True, exist_ok=True)
        log = open(self.ns / "nightschool.log", "ab")
        try:
            self.worker = self._popen([python, "-m", "nightschool", "run"], cwd=str(app / "server" / "night_school"),
                                      env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                      creationflags=NO_WINDOW)
        finally:
            log.close()
        self._say("running", f"night school on the graphics card (share {self.config['share']})")

    def end(self, why: str, *, failed: bool = False) -> None:
        """Stop night school politely (HOLD: it drops the answer in flight), then the model server."""
        worker, self.worker = self.worker, None
        if worker is not None and worker.poll() is None:
            hold = self.ns / "data" / "HOLD"
            hold.parent.mkdir(parents=True, exist_ok=True)
            mark = count_bytes(self.ns / "nightschool.log")
            hold.write_text("GPU night turbo: " + why + "\n", encoding="utf-8")
            deadline = self._clock() + YIELD_WAIT_S
            while worker.poll() is None and self._clock() < deadline and not yielded(self.ns / "nightschool.log", mark):
                time.sleep(0.25)
            kill_tree(worker)
        self.helper.shutdown()
        if self.state == "running":
            self.log(session_summary(self.ns / "data" / "attempts.jsonl", self.answers_at_start,
                                     self._clock() - self.ran_at))
        if failed:
            self.cool_until = self._clock() + COOL_DOWN_S
        was_running = self.state == "running"
        self._say("waiting", "stopped: " + why)
        if was_running:
            try:
                note = self._merge()
                if note:
                    self.log("merge: " + note)
            except Exception as exc:          # a merge problem never blocks the next session
                self.log("merge failed: " + type(exc).__name__)

    def run(self, stop=lambda: False) -> None:
        self.log(f"supervisor started (home {self.home}; server_ssh {'set' if self.config['server_ssh'] else 'NOT set'}; "
                 f"pool {'present' if (self.ns / 'pool').is_dir() else 'missing'})")
        try:
            while not stop():
                try:
                    self.tick()
                except Exception as exc:
                    self.log("tick error: " + type(exc).__name__ + ": " + str(exc)[:160])
                    if self.state != "waiting":
                        self.end("internal error", failed=True)
                time.sleep(POLL_S)
        finally:
            if self.state != "waiting":
                self.end("supervisor stopped")


# ---- night school's settings for this PC ---------------------------------------------------------------------------
def worker_env(config: dict, ns: Path, brain_url: str) -> dict:
    return {
        "STAR_NS_HOME": str(ns), "STAR_NS_APP": str(config["app"]), "STAR_NS_BRAIN_URL": brain_url,
        "STAR_NS_MODEL": "star-fast", "STAR_NS_KEY_FILE": str(Path(config["key_file"]).expanduser()),
        "STAR_NS_KNOWLEDGE_URL": config["knowledge_url"], "STAR_NS_PLANNER_URL": "off",
        "STAR_NS_IDLE_S": "0", "STAR_NS_POLL_S": "2", "STAR_NS_SLOT": "0",
        "STAR_NS_LOCK_DIR": str(ns / "no-lock"),          # server 1's quiet lock is about server 1's brain, not this one
        "STAR_NS_SHARE": config["share"], "STAR_NS_VALIDATION_SHARE": str(config["validation_share"]),
        "STAR_NS_SKIP_FILE": str(ns / "skip.json"), "STAR_NS_SANDBOX_SSH": config["server_ssh"],
        "STAR_NS_DIAGNOSE_MODEL": "",                    # only star-fast is loaded here
        "STAR_NS_CONDUCTOR_MODELS": "star-fast", "STAR_NS_CONDUCTOR_TAG": "pc-",   # its new tasks go to server 1's pool
        "PYTHONIOENCODING": "utf-8",
        "APPDATA": str(ns / "appdata"), "XDG_DATA_HOME": str(ns / "appdata"),   # never the owner's STAR profile
    }


def count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def count_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def yielded(log: Path, since: int) -> bool:
    """Night school wrote that it saw the HOLD file (after byte `since` of its log)."""
    try:
        with open(log, "rb") as handle:
            handle.seek(since)
            return b"HOLD" in handle.read()
    except OSError:
        return False


def kill_tree(process) -> None:
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=20,
                   creationflags=NO_WINDOW)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def session_summary(attempts: Path, before: int, seconds: float) -> str:
    rows = []
    try:
        lines = attempts.read_text(encoding="utf-8").splitlines()[before:]
        rows = [json.loads(line) for line in lines if line.strip()]
    except (OSError, ValueError):
        pass
    first = [r for r in rows if r.get("purpose") == "first"]
    hours = max(seconds, 1.0) / 3600
    return (f"session {seconds / 60:.1f} min: {len(rows)} answers ({len(first)} first tries, "
            f"{sum(1 for r in first if r.get('passed'))} passed first; "
            f"{sum(1 for r in rows if str(r.get('purpose', '')).startswith('validation'))} validation); "
            f"{len(rows) / hours:.1f} answers/hour, {len(first) / hours:.1f} first tries/hour")


# ---- server 1: pool, skip list, validation slice, outbox -----------------------------------------------------------
def _ssh(config: dict, command: str, timeout: float = 90) -> bytes:
    done = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", config["server_ssh"],
                           f"lxc exec {config['container']} -- {command}"], capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW)
    if done.returncode != 0:
        raise OSError(f"ssh failed (status {done.returncode})")
    return done.stdout


def quiet_lock_held(config: dict) -> bool:
    """/opt/star/lock exists in server 1's container and is fresh (older than LOCK_STALE_S = stale, as in night
    school). Unreachable server: False (night school's own checks then fail and count as errors, not answers)."""
    if not config["server_ssh"]:
        return False
    try:
        out = _ssh(config, "sh -c 'echo $(( $(date +%s) - $(stat -c %Y /opt/star/lock 2>/dev/null || echo 0) ))'", 20)
        return int(out.decode().strip() or "999999") < LOCK_STALE_S
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def _untar(data: bytes, into: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(into, filter="data")


def apply_server_state(ns: Path, state: dict) -> str:
    """skip.json = every task server 1 has answered; the validation slice = server 1's (set once, never moved)."""
    ns.mkdir(parents=True, exist_ok=True)
    tried = sorted(state.get("tasks") or {})
    (ns / "skip.json").write_text(json.dumps(tried), encoding="utf-8")
    own = ns / "data" / "state.json"
    seeded = ""
    if not own.is_file() and state.get("validation_ids"):
        own.parent.mkdir(parents=True, exist_ok=True)
        own.write_text(json.dumps({"validation_ids": list(state["validation_ids"])}), encoding="utf-8")
        seeded = f"; validation slice seeded ({len(state['validation_ids'])} tasks)"
    return f"{len(tried)} tasks answered on server 1 are skipped" + seeded


def push_conductor_tasks(config: dict, ns: Path) -> int:
    """Copy the PC conductor's pool files (pool/conductor-pc-*.json, already checked by the same validators) into
    server 1's pool, so every worker practises them and the next pool sync does not lose them. Returns files sent."""
    sent = 0
    for path in sorted((ns / "pool").glob("conductor-pc-*.json")) if config["server_ssh"] else ():
        name = path.name
        if not re.fullmatch(r"conductor-pc-\d{8}\.json", name):
            continue
        done = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", config["server_ssh"],
             f"lxc exec {config['container']} -- sh -c 'cat > {SERVER_HOME}/pool/.{name}.tmp && "
             f"chown star:star {SERVER_HOME}/pool/.{name}.tmp && mv {SERVER_HOME}/pool/.{name}.tmp {SERVER_HOME}/pool/{name}'"],
            input=path.read_bytes(), capture_output=True, timeout=90, creationflags=NO_WINDOW)
        sent += done.returncode == 0
    return sent


def sync_from_server(config: dict, ns: Path) -> str:
    if not config["server_ssh"]:
        return "no server_ssh in config.json: using the pool already here"
    try:
        push_conductor_tasks(config, ns)          # before the local pool is replaced by server 1's copy
        data = _ssh(config, f"tar c -C {SERVER_HOME} pool")
        with tempfile.TemporaryDirectory(dir=ns.parent if ns.parent.is_dir() else None) as folder:
            _untar(data, Path(folder))
            ns.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(ns / "pool", ignore_errors=True)
            shutil.move(str(Path(folder) / "pool"), str(ns / "pool"))
        state = json.loads(_ssh(config, f"cat {SERVER_HOME}/data/state.json").decode("utf-8"))
        return "pool copied; " + apply_server_state(ns, state)
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        return f"server 1 not reachable ({type(exc).__name__}); using the pool already here"


def merge_outboxes(sources: list[tuple[str, Path]], out: Path) -> dict:
    """One outbox in night school's formats from several: lessons side by side, the worked examples of all (the
    first source wins when two have the same task), each source's report kept as report-<label>.md."""
    from star.lessons import write_export
    from star.worked_examples import MAX_ROWS
    out.mkdir(parents=True, exist_ok=True)
    lessons, counts, rows, seen = [], {}, [], set()
    for label, folder in sources:
        lesson_file = folder / "outbox" / "star-lessons-night-school.json"
        if lesson_file.is_file():
            data = json.loads(lesson_file.read_text(encoding="utf-8"))
            offset = max((int(l["id"]) for l in lessons), default=0)      # export ids must stay unique
            for lesson in data.get("lessons") or []:
                lesson = {**lesson, **{k: lesson[k] + offset for k in ("id", "supersedes_id", "merged_into")
                                       if isinstance(lesson.get(k), int)}}
                if label != sources[0][0]:          # "night-school:L3" -> "night-school:pc-gpu:L3"
                    lesson["source"] = str(lesson.get("source", "")).replace(":", f":{label}:", 1)
                lessons.append(lesson)
            for key, value in (data.get("counts") or {}).items():
                counts[key] = counts.get(key, 0) + int(value or 0)
        example_file = folder / "outbox" / "worked-examples.jsonl"
        if example_file.is_file():
            for line in example_file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row.get("group_id") not in seen and len(rows) < MAX_ROWS:
                        seen.add(row.get("group_id"))
                        rows.append(row)
        report = folder / "report" / "latest.md"
        if report.is_file():
            shutil.copyfile(report, out / f"report-{label}.md")
    write_export(out / "star-lessons-night-school.json", {
        "format": "star-lessons-v1", "project": "night-school", "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "counts": counts, "lessons": lessons,
        "note": "Merged by the GPU night turbo from: " + ", ".join(l for l, _ in sources) + ". Every lesson is a "
                "CANDIDATE (see each worker's report); no person has reviewed it."})
    with open(out / "worked-examples.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for row in sorted(rows, key=lambda r: str(r.get("group_id"))):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"lessons": len(lessons), "examples": len(rows)}


def merge_now(config: dict, home: Path) -> str:
    sources, note = [], ""
    with tempfile.TemporaryDirectory() as folder:
        if config["server_ssh"]:
            try:
                _untar(_ssh(config, f"tar c -C {SERVER_HOME} outbox report"), Path(folder))
                sources.append(("server1", Path(folder)))
            except (OSError, subprocess.SubprocessError, tarfile.TarError) as exc:
                note = f"server 1's outbox not reachable ({type(exc).__name__}); "
        sources.append(("pc-gpu", home / "ns"))
        try:
            if push_conductor_tasks(config, home / "ns"):
                note += "PC conductor tasks copied to server 1's pool; "
        except (OSError, subprocess.SubprocessError) as exc:
            note += f"PC conductor tasks not copied ({type(exc).__name__}); "
        done = merge_outboxes(sources, home / "merged")
    return note + f"{done['lessons']} lessons, {done['examples']} worked examples in merged/"


# ---- commands ------------------------------------------------------------------------------------------------------
def single_instance() -> bool:
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW(None, False, "Local\\STAR-gpu-night-turbo")     # held until this process ends
    return ctypes.get_last_error() != 183                                  # ERROR_ALREADY_EXISTS


def install(home: Path) -> int:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    action = f'"{pythonw}" "{Path(__file__).resolve()}" --home "{home}" run'
    if len(action) > 261:
        print("the task command is longer than Windows allows (261); use shorter paths")
        return 1
    done = subprocess.run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5", "/TN", TASK_NAME, "/TR", action],
                          capture_output=True, text=True)
    print((done.stdout or done.stderr).strip())
    (home / "turbo.cmd").write_text(
        "@echo off\r\nrem STAR GPU night turbo: turbo off | on | status | merge\r\n"
        f'"{Path(sys.executable).with_name("python.exe")}" "{Path(__file__).resolve()}" --home "{home}" %*\r\n',
        encoding="utf-8")
    print(f"off switch: {home / 'turbo.cmd'} off   (or create the file {home / 'OFF'})")
    return done.returncode


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="turbo", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--home", type=Path, default=default_home())
    parser.add_argument("command", choices=["run", "status", "off", "on", "merge", "install", "uninstall"])
    args = parser.parse_args(argv)
    home = args.home
    home.mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(home / "appdata")       # nothing here may read or write the owner's STAR profile
    config = load_config(home)
    if args.command == "off":
        (home / "OFF").write_text("off\n", encoding="utf-8")
        print("off: a running session stops within seconds; delete OFF or run 'on' to allow sessions again")
        return 0
    if args.command == "on":
        (home / "OFF").unlink(missing_ok=True)
        print("on")
        return 0
    if args.command == "status":
        for name in ("STATUS.txt",):
            path = home / name
            print(path.read_text(encoding="utf-8").strip() if path.is_file() else "no status yet (not started)")
        print("off switch: " + ("ON (sessions blocked)" if (home / "OFF").exists() else "not set"))
        log = home / "turbo.log"
        if log.is_file():
            print("\n".join(log.read_text(encoding="utf-8").splitlines()[-8:]))
        return 0
    if args.command == "merge":
        print(merge_now(config, home))
        return 0
    if args.command == "install":
        return install(home)
    if args.command == "uninstall":
        return subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME]).returncode
    if not single_instance():
        return 0                              # the scheduled task found the supervisor already running
    Turbo(home, config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
