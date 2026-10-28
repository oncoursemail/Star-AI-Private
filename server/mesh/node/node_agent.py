"""Litha mesh node: lends this PC's graphics card to the STAR compute mesh while nobody needs it.

    python node_agent.py run          the node (the scheduled task starts it; one copy at a time)
    python node_agent.py status       print GET /status of the local node
    python node_agent.py load|unload  ask the local node to load or free the model (mesh token auth)
    python node_agent.py off|on       the off switch (the file OFF next to this script)

Contract (docs/agents/WAVE-20261027-MESH-BRIEF.md):
  GET  :8099/status   {"node","state":"idle|busy|away|off","reason","gpu":{...},"ram_free_mb","models":[...],"ts"}
  POST :8099/load     load the model now (Authorization: Bearer <mesh token>); refused while busy
  POST :8099/unload   free the card; the node then stays unloaded until the next /load
  :8098               the model (llama-server, OpenAI-compatible), same mesh token. llama-server itself listens
                      only on 127.0.0.1; this process forwards LAN requests to it, so one program needs a firewall rule.

States: idle = the model is loaded and serving; busy = the machine is in use (game, stream, other GPU work), the
model is unloaded and comes back after `resume_seconds` free; away = nothing is in the way but the model is not
loaded (loading, unloaded on request, failed); off = the OFF file exists.

The busy guard runs every `poll_seconds`: a full-screen program in front, a known game/stream/VR program, a Steam
game, Minecraft (Java), the FAKE_BUSY test file, another program's GPU load or video memory. It stops the model at
once (TerminateProcess) when any of them appears. Standard library only; the mesh token is read, never printed.
"""
from __future__ import annotations

import argparse
import hmac
import http.client
import http.server
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BELOW_NORMAL = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

DEFAULTS: dict = {
    "node": "",                                 # name in /status; "" = this computer's name
    "advertise_host": "",                       # host in the model url; "" = this PC's LAN address
    "status_port": 8099, "model_port": 8098, "bind": "0.0.0.0",
    "internal_port": 18098,                     # llama-server on 127.0.0.1 only
    "llama_server": "engine/llama-server.exe",  # relative paths are relative to this folder; ~ works
    "model_path": "models/litha-fast.gguf",
    "model_id": "litha-fast",
    "ctx": 8192,
    "llama_args": ["-ngl", "99", "-fa", "on", "-t", "4", "-np", "1", "--jinja"],
    "token_file": "~/.star/mesh_token",
    "model_auth": True,                         # :8098 needs the mesh token too
    "autoload": True,
    "poll_seconds": 2.5,
    "resume_seconds": 180,                      # free this long after busy before the model comes back
    "retry_seconds": 300,                       # after a failed load
    "load_timeout_seconds": 300,
    "need_free_vram_mb": 0,                     # free video memory needed to load (0 = do not check)
    "busy_util_percent": 40, "busy_util_looks": 2,   # other programs' GPU load (while the model is not working)
    "other_vram_grow_mb": 1200,                 # other programs grew their video memory this much since the load
    "fullscreen": True,
    "block_processes": ["RobloxPlayerBeta.exe", "RobloxStudioBeta.exe", "obs64.exe", "obs32.exe",
                        "Minecraft.Windows.exe", "recroom.exe", "recroom_release.exe",
                        "vrserver.exe", "vrcompositor.exe", "vrmonitor.exe", "OVRServer_x64.exe", "VRChat.exe",
                        "Streamlabs OBS.exe", "Streamlabs Desktop.exe", "XSplit.Core.exe"],
    "block_path_parts": ["\\steamapps\\common\\"],     # Steam games (any program under a Steam library)
    "ignore_processes": ["wallpaper32.exe", "wallpaper64.exe", "webwallpaper32.exe", "steamwebhelper.exe",
                         "UnityCrashHandler64.exe", "UnityCrashHandler32.exe"],
    "minecraft_java": True,                     # javaw/java with "minecraft" in its path or window title
    "warm_prompt": "In two short sentences, explain what a Roblox RemoteEvent is.",
    "warm_tokens": 64,
    "router_url": "",                           # mesh router, e.g. http://<router>:8100; "" = do not self-register
    "register_seconds": 30,
}


# ---- configuration and token ---------------------------------------------------------------------------------------
def load_config(home: Path = HERE) -> dict:
    config = dict(DEFAULTS)
    path = home / "node.json"
    if path.is_file():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    return config


def resolve(home: Path, value: str) -> Path:
    path = Path(os.path.expanduser(str(value)))
    return path if path.is_absolute() else home / path


def read_or_create_token(path: Path) -> str:
    """The mesh token (64 hex characters). Created when missing, readable only by this user. Never printed."""
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    path.write_text(token + "\n", encoding="utf-8")
    if os.name == "nt":
        user = os.environ.get("USERNAME", "")
        if user:
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                           capture_output=True, creationflags=NO_WINDOW)
    else:
        os.chmod(path, 0o600)
    return token


def authorized(header: str | None, token: str) -> bool:
    if not token or not header or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].strip().encode(), token.encode())


def lan_address() -> str:
    """The address other machines reach this one at (the interface of the default route; nothing is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))     # TEST-NET-1: only selects the outgoing interface
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostname()


# ---- what the machine is doing (Windows) ---------------------------------------------------------------------------
def read_gpu() -> dict | None:
    """{"name","total","used","util"} of the first NVIDIA card (nvidia-smi); None when there is none."""
    tool = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    try:
        out = subprocess.run([tool, "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=NO_WINDOW).stdout
        name, total, used, util = (p.strip() for p in out.splitlines()[0].split(","))
        return {"name": name, "total": int(total), "used": int(used), "util": int(util)}
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def free_ram_mb() -> int | None:
    if os.name != "nt":
        return None
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("available", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                    ("page_free", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                    ("virtual_free", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]
    status = Status()
    status.length = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.available // (1024 * 1024))


class WindowsProbe:
    """Cheap looks at the desktop: ToolHelp process snapshot, exe paths cached per pid, two user32 calls."""

    def __init__(self):
        import ctypes
        import ctypes.wintypes as wt
        self.ctypes, self.wt = ctypes, wt
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.paths: dict[tuple[int, str], str] = {}

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                        ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                        ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]
        self.Entry = Entry
        self.k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
        self.k32.OpenProcess.restype = wt.HANDLE
        self.u32.GetForegroundWindow.restype = wt.HWND
        self.u32.MonitorFromWindow.restype = wt.HANDLE

    def processes(self) -> dict[int, str]:
        snap = self.k32.CreateToolhelp32Snapshot(0x2, 0)
        entry = self.Entry()
        entry.dwSize = self.ctypes.sizeof(entry)
        found = {}
        ok = self.k32.Process32FirstW(snap, self.ctypes.byref(entry))
        while ok:
            found[int(entry.th32ProcessID)] = entry.szExeFile
            ok = self.k32.Process32NextW(snap, self.ctypes.byref(entry))
        self.k32.CloseHandle(snap)
        if len(self.paths) > 4000:
            self.paths = {k: v for k, v in self.paths.items() if found.get(k[0]) == k[1]}
        return found

    def exe_path(self, pid: int, name: str) -> str:
        key = (pid, name)
        if key not in self.paths:
            path = ""
            handle = self.k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                buf = self.ctypes.create_unicode_buffer(1024)
                size = self.wt.DWORD(len(buf))
                if self.k32.QueryFullProcessImageNameW(handle, 0, buf, self.ctypes.byref(size)):
                    path = buf.value
                self.k32.CloseHandle(handle)
            self.paths[key] = path
        return self.paths[key]

    def window_titles(self, pids: set[int]) -> list[str]:
        """Titles of the visible top-level windows of these processes."""
        ctypes, wt, u32 = self.ctypes, self.wt, self.u32
        titles: list[str] = []
        proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def each(hwnd, _):
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and u32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(256)
                u32.GetWindowTextW(hwnd, buf, 256)
                if buf.value:
                    titles.append(buf.value)
            return True
        u32.EnumWindows(proto(each), 0)
        return titles

    def fullscreen(self) -> bool:
        """A full-screen program, D3D full-screen game or presentation mode, or a borderless window that covers
        its whole monitor (the desktop and the taskbar themselves do not count)."""
        ctypes, wt, u32 = self.ctypes, self.wt, self.u32
        state = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in (2, 3, 4):
            return True
        hwnd = u32.GetForegroundWindow()
        if not hwnd or u32.IsIconic(hwnd):
            return False
        cls = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(hwnd, cls, 64)
        if cls.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        rect = wt.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        monitor = u32.MonitorFromWindow(hwnd, 2)                      # MONITOR_DEFAULTTONEAREST
        if not monitor or not u32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        m = info.rcMonitor
        return rect.left <= m.left and rect.top <= m.top and rect.right >= m.right and rect.bottom >= m.bottom


def program_reason(config: dict, procs: dict[int, str], own: set[int], exe_path, titles, fullscreen: bool) -> str:
    """Why a program on this machine needs it (game, stream, VR, full screen); '' when none does."""
    if config.get("fullscreen", True) and fullscreen:
        return "a full-screen program or game is in front"
    blocked = {n.lower() for n in config.get("block_processes", [])}
    ignored = {n.lower() for n in config.get("ignore_processes", [])}
    parts = [p.lower() for p in config.get("block_path_parts", [])]
    java: set[int] = set()
    for pid, name in procs.items():
        low = name.lower()
        if pid in own or low in ignored:
            continue
        if low in blocked:
            return f"{name} is running"
        if config.get("minecraft_java", True) and low in ("javaw.exe", "java.exe"):
            if "minecraft" in exe_path(pid, name).lower():
                return f"Minecraft is running ({name})"
            java.add(pid)
        if parts and low.endswith(".exe"):
            path = exe_path(pid, name).lower()
            if path and any(p in path for p in parts):
                return f"a Steam game is running ({name})"
    if java and any("minecraft" in t.lower() for t in titles(java)):
        return "Minecraft is running (Java)"
    return ""


# ---- the model server ----------------------------------------------------------------------------------------------
def llama_argv(config: dict, home: Path) -> list[str]:
    exe, model = resolve(home, config["llama_server"]), resolve(home, config["model_path"])
    if exe.name.lower() not in ("llama-server.exe", "llama-server") or not exe.is_file():
        raise ValueError(f"llama-server was not found at {exe}")
    if model.suffix.lower() != ".gguf" or not model.is_file():
        raise ValueError(f"the model file was not found at {model}")
    return [str(exe), "-m", str(model), "--alias", str(config["model_id"]), "--host", "127.0.0.1",
            "--port", str(int(config["internal_port"])), "-c", str(int(config["ctx"])),
            *[str(a) for a in config.get("llama_args", [])]]


def http_json(method: str, url: str, body: dict | None = None, timeout: float = 5.0) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def health(port: int) -> bool:
    try:
        return http_json("GET", f"http://127.0.0.1:{port}/health", timeout=1.5)[0] == 200
    except (OSError, ValueError):
        return False


def warm_measure(port: int, config: dict) -> tuple[float | None, float | None]:
    """One short chat request: (generation tok/s, prompt tok/s) from llama-server's timings."""
    body = {"messages": [{"role": "user", "content": config["warm_prompt"]}],
            "max_tokens": int(config["warm_tokens"]), "temperature": 0.2}
    status, data = http_json("POST", f"http://127.0.0.1:{port}/v1/chat/completions", body, timeout=120)
    timings = data.get("timings") or {}
    gen, prompt = timings.get("predicted_per_second"), timings.get("prompt_per_second")
    return (round(gen, 1) if gen else None), (round(prompt, 1) if prompt else None)


class Node:
    """State machine: the guard tick, load/unload, status. Everything external is injectable for tests."""

    def __init__(self, config: dict, home: Path = HERE, *, probe=None, gpu=read_gpu, ram=free_ram_mb,
                 popen=subprocess.Popen, healthy=health, measure=warm_measure, clock=time.monotonic,
                 log=None, background=True):
        self.config, self.home = config, Path(home)
        self.probe = probe
        self._gpu, self._ram, self._popen, self._healthy, self._measure = gpu, ram, popen, healthy, measure
        self._clock, self._background = clock, background
        self._log = log or self._file_log
        self.lock = threading.RLock()
        self.name = config.get("node") or socket.gethostname().lower()
        self.host = config.get("advertise_host") or lan_address()
        self.state, self.reason = "away", "starting"
        self.process = None
        self.loading = self.ready = False
        self.hold = False               # unloaded on request: stays unloaded until /load
        self.failed_at = -1e18
        self.free_since: float | None = None
        self.was_busy = False
        self.hot_looks = 0
        self.in_flight = 0
        self.quiet_until = -1e18        # a request just ended: the card's load is still ours for a moment
        self.own_mb = 0
        self.others_at_load = 0
        self.tok_s: float | None = None
        self.prompt_tok_s: float | None = None
        self.last_gpu: dict | None = None
        self.load_started = 0.0

    # -- logging -----------------------------------------------------------------------------------------------------
    def _file_log(self, text: str) -> None:
        logs = self.home / "logs"
        logs.mkdir(exist_ok=True)
        path = logs / "node.log"
        if path.is_file() and path.stat().st_size > 5_000_000:
            path.replace(logs / "node.log.1")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")

    def _set(self, state: str, reason: str) -> None:
        if (state, reason.split(" (free")[0]) != (self.state, self.reason.split(" (free")[0]):
            self._log(f"{state}: {reason}")
        self.state, self.reason = state, reason

    # -- the guard ---------------------------------------------------------------------------------------------------
    def own_pids(self) -> set[int]:
        return {self.process.pid} if self.process is not None else set()

    def busy_reason(self, gpu: dict | None) -> str:
        if (self.home / "FAKE_BUSY").exists():
            return "test hook (the FAKE_BUSY file exists)"
        if self.probe is not None:
            procs = self.probe.processes()
            found = program_reason(self.config, procs, self.own_pids(), self.probe.exe_path,
                                   self.probe.window_titles, self.probe.fullscreen())
            if found:
                return found
        if gpu is None:
            return ""
        now = self._clock()
        ours = self.loading or self.in_flight > 0 or now < self.quiet_until
        if not ours and gpu["util"] >= int(self.config["busy_util_percent"]):
            self.hot_looks += 1
            if self.hot_looks >= int(self.config["busy_util_looks"]):
                return f"another program is using the graphics card ({gpu['util']}%)"
        elif not ours:
            self.hot_looks = 0
        if self.ready:
            grown = (gpu["used"] - self.own_mb) - self.others_at_load
            if grown > int(self.config["other_vram_grow_mb"]):
                return f"other programs took {grown} MB more graphics memory"
        elif not self.loading:
            need = int(self.config.get("need_free_vram_mb") or 0)
            free = gpu["total"] - gpu["used"]
            if need and free < need:
                return f"only {free} MB of graphics memory is free ({need} MB needed)"
        return ""

    def tick(self) -> None:
        gpu = self._gpu()
        with self.lock:
            self.last_gpu = gpu
            self._check_process()
            if (self.home / "OFF").exists():
                self._stop("off switch")
                self.free_since, self.was_busy = None, False
                self._set("off", "the OFF file exists")
                return
            reason = self.busy_reason(gpu)
            now = self._clock()
            if reason:
                if self.process is not None:
                    self._stop(reason)
                self.free_since, self.was_busy = None, True
                self._set("busy", reason)
                return
            if self.was_busy:
                if self.free_since is None:
                    self.free_since = now
                waited, need = now - self.free_since, float(self.config["resume_seconds"])
                if waited < need:
                    self._set("busy", f"{self.reason.split(' (free')[0]} (free for {int(waited)} of {int(need)} s)")
                    return
                self.was_busy, self.free_since = False, None
            if self.ready:
                self._set("idle", "model loaded")
            elif self.loading:
                self._set("away", "loading the model")
            elif self.hold:
                self._set("away", "unloaded on request (POST /load to load)")
            elif not self.config.get("autoload", True):
                self._set("away", "autoload is off (POST /load to load)")
            elif now - self.failed_at < float(self.config["retry_seconds"]):
                self._set("away", self.reason if self.reason.startswith("failed") else "failed; retrying later")
            else:
                self.start_load(gpu)

    def _check_process(self) -> None:
        if self.process is not None and not self.loading and self.process.poll() is not None:
            code = self.process.returncode
            self.process, self.ready = None, False
            self.failed_at = self._clock()
            self._set("away", f"failed: llama-server exited (code {code}); see logs\\llama-server.log")

    # -- load and unload ---------------------------------------------------------------------------------------------
    def start_load(self, gpu: dict | None = None) -> tuple[bool, str]:
        with self.lock:
            if self.ready or self.loading:
                return True, "already loaded" if self.ready else "already loading"
            try:
                argv = llama_argv(self.config, self.home)
            except ValueError as exc:
                self.failed_at = self._clock()
                self._set("away", f"failed: {exc}")
                return False, str(exc)
            logs = self.home / "logs"
            logs.mkdir(exist_ok=True)
            log_path = logs / "llama-server.log"
            if log_path.is_file() and log_path.stat().st_size > 20_000_000:
                log_path.replace(logs / "llama-server.log.1")
            gpu = gpu if gpu is not None else self._gpu()
            self.others_at_load = gpu["used"] if gpu else 0
            with open(log_path, "ab") as log:
                try:
                    self.process = self._popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                               creationflags=NO_WINDOW | BELOW_NORMAL)
                except OSError as exc:
                    self.failed_at = self._clock()
                    self._set("away", f"failed: llama-server could not start ({type(exc).__name__})")
                    return False, "could not start"
            self.loading, self.hold = True, False
            self.load_started = self._clock()
            self._set("away", "loading the model")
            process = self.process
        if self._background:
            threading.Thread(target=self._finish_load, args=(process,), daemon=True, name="node-load").start()
        else:
            self._finish_load(process)
        return True, "loading"

    def _finish_load(self, process) -> None:
        port = int(self.config["internal_port"])
        deadline = self._clock() + float(self.config["load_timeout_seconds"])
        while self._clock() < deadline:
            with self.lock:
                if self.process is not process:
                    return                                  # unloaded meanwhile (busy, /unload)
                if process.poll() is not None:
                    break
            if self._healthy(port):
                try:
                    gen, prompt = self._measure(port, self.config)
                except (OSError, ValueError) as exc:
                    self._log(f"warm request failed ({type(exc).__name__})")
                    gen = prompt = None
                gpu = self._gpu()
                with self.lock:
                    if self.process is not process:
                        return
                    self.tok_s, self.prompt_tok_s = gen or self.tok_s, prompt or self.prompt_tok_s
                    self.last_gpu = gpu or self.last_gpu
                    self.own_mb = max(0, (gpu["used"] if gpu else 0) - self.others_at_load)
                    self.loading, self.ready = False, True
                    self.quiet_until = self._clock() + 3.0
                    self._set("idle", "model loaded")
                    self._log(f"loaded in {self._clock() - self.load_started:.0f} s, {self.tok_s} tok/s gen, "
                              f"{self.prompt_tok_s} tok/s prompt, {self.own_mb} MB on the card")
                return
            if self._background:
                time.sleep(1.0)
        with self.lock:
            if self.process is process:
                code = process.poll()
                self._stop("load failed")
                self.failed_at = self._clock()
                self._set("away", f"failed: the model did not load (exit code {code}); see logs\\llama-server.log"
                          if code is not None else "failed: the model did not load in time")

    def unload(self, why: str, *, hold: bool = False) -> None:
        with self.lock:
            self._stop(why)
            self.hold = self.hold or hold
            if self.state != "busy" and self.state != "off":
                self._set("away", "unloaded on request (POST /load to load)" if hold else why)

    def _stop(self, why: str) -> None:
        process, self.process = self.process, None
        was = self.ready or self.loading
        self.ready = self.loading = False
        if process is None:
            return
        try:
            if process.poll() is None:
                process.kill()                              # TerminateProcess: the card is free at once
                process.wait(timeout=5)
        except Exception as exc:                            # noqa: BLE001 - stopping must never raise
            self._log(f"stopping llama-server failed ({type(exc).__name__})")
        if was:
            self._log(f"unloaded: {why}")

    # -- requests through the proxy ------------------------------------------------------------------------------------
    def begin_request(self) -> bool:
        with self.lock:
            if not self.ready:
                return False
            self.in_flight += 1
            return True

    def end_request(self) -> None:
        with self.lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.quiet_until = self._clock() + 3.0

    # -- status ------------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        with self.lock:
            gpu = self.last_gpu
            return {
                "node": self.name, "state": self.state, "reason": self.reason,
                "gpu": ({"name": gpu["name"], "vram_total_mb": gpu["total"], "vram_free_mb": gpu["total"] - gpu["used"],
                         "util": gpu["util"]} if gpu else None),
                "ram_free_mb": self._ram(),
                "models": [{"id": self.config["model_id"], "url": f"http://{self.host}:{int(self.config['model_port'])}/v1",
                            "ctx": int(self.config["ctx"]), "loaded": self.ready, "loading": self.loading,
                            "in_flight": self.in_flight, "tok_s": self.tok_s, "prompt_tok_s": self.prompt_tok_s,
                            "auth": "mesh_token" if self.config.get("model_auth", True) else "none"}],
                "ts": round(time.time(), 3),
            }

    def run_guard(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception as exc:                        # noqa: BLE001 - the guard must never die silently
                self._log(f"guard error: {type(exc).__name__}: {exc}")
            stop.wait(float(self.config["poll_seconds"]))


# ---- HTTP ----------------------------------------------------------------------------------------------------------
HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization",
       "proxy-authenticate", "content-length", "authorization", "host"}


def make_control_handler(node: Node, token: str):
    class Control(http.server.BaseHTTPRequestHandler):
        server_version = "litha-node/1"

        def log_message(self, *args):                       # quiet: the node log has the state changes
            pass

        def _send(self, code: int, data: dict) -> None:
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?")[0] == "/status":
                self._send(200, node.status())
            elif self.path == "/health":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}") if 0 < length < 65536 else {}
            path = self.path.split("?")[0]
            if path not in ("/load", "/unload"):
                return self._send(404, {"error": "not found"})
            if not authorized(self.headers.get("Authorization"), token):
                return self._send(401, {"ok": False, "error": "mesh token required"})
            if path == "/unload":
                node.unload("unloaded on request", hold=True)
                return self._send(200, {"ok": True, **node.status()})
            if body.get("model") not in (None, "", node.config["model_id"]):
                return self._send(404, {"ok": False, "error": f"this node serves {node.config['model_id']}"})
            with node.lock:
                if node.state in ("busy", "off"):
                    return self._send(409, {"ok": False, **node.status()})
                node.hold = False
            ok, why = node.start_load()
            if ok and body.get("wait"):
                deadline = time.monotonic() + float(node.config["load_timeout_seconds"])
                while node.loading and time.monotonic() < deadline:
                    time.sleep(0.5)
            self._send(202 if ok else 500, {"ok": ok and not (body.get("wait") and not node.ready), "detail": why,
                                            **node.status()})
    return Control


def make_model_handler(node: Node, token: str):
    port = int(node.config["internal_port"])
    need_auth = bool(node.config.get("model_auth", True))

    class Model(http.server.BaseHTTPRequestHandler):
        server_version = "litha-node/1"

        def log_message(self, *args):
            pass

        def _error(self, code: int, message: str) -> None:
            body = json.dumps({"error": {"message": message, "code": code}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _forward(self):
            if need_auth and not authorized(self.headers.get("Authorization"), token):
                return self._error(401, "mesh token required")
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            if not node.begin_request():
                return self._error(503, f"model not loaded: {node.state}: {node.reason}")
            try:
                upstream = http.client.HTTPConnection("127.0.0.1", port, timeout=600)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
                upstream.request(self.command, self.path, body=body, headers=headers)
                resp = upstream.getresponse()
                self.send_response(resp.status)
                for key, value in resp.getheaders():
                    if key.lower() not in HOP:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    chunk = resp.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                upstream.close()
            except (OSError, http.client.HTTPException):
                try:
                    self._error(502, "the model server stopped answering (unloaded?)")
                except OSError:
                    pass
            finally:
                node.end_request()

        do_GET = do_POST = do_DELETE = do_PUT = _forward
    return Model


def registration(node: Node) -> dict:
    """What the node tells the router every `register_seconds` (POST <router_url>/mesh/register)."""
    host, cfg = node.host, node.config
    return {"node": node.name, "status_url": f"http://{host}:{int(cfg['status_port'])}/status",
            "model_url": f"http://{host}:{int(cfg['model_port'])}/v1"}


def register_loop(node: Node, token: str, stop: threading.Event, post=None) -> None:
    """Self-registration, so a node with an unknown address (STAR's PC) joins the mesh. Failures are logged once."""
    url = str(node.config.get("router_url") or "").rstrip("/")
    if not url:
        return
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    last = None
    while not stop.is_set():
        try:
            req = urllib.request.Request(url + "/mesh/register", data=json.dumps(registration(node)).encode(),
                                         method="POST", headers={"Authorization": "Bearer " + token,
                                                                 "Content-Type": "application/json"})
            with (post or opener.open)(req, timeout=5) as resp:
                result = f"registered ({resp.status})"
        except urllib.error.HTTPError as exc:
            result = f"router refused the registration (HTTP {exc.code})"
        except (OSError, ValueError) as exc:
            result = f"router not reachable ({type(exc).__name__})"
        if result != last:
            node._log(f"mesh register: {result}")
            last = result
        stop.wait(float(node.config.get("register_seconds") or 30))


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def single_instance(name: str = "Local\\Litha-mesh-node") -> bool:
    if os.name != "nt":
        return True
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW(None, False, name)                       # held until this process ends
    return ctypes.get_last_error() != 183                        # ERROR_ALREADY_EXISTS


def serve(home: Path = HERE) -> int:
    if not single_instance():
        return 0
    config = load_config(home)
    token = read_or_create_token(Path(os.path.expanduser(config["token_file"])))
    node = Node(config, home, probe=WindowsProbe() if os.name == "nt" else None)
    node._log(f"start: node {node.name}, status :{config['status_port']}, model :{config['model_port']}")
    (home / "logs" / "node.pid").write_text(str(os.getpid()), encoding="utf-8")
    bind = config.get("bind", "0.0.0.0")
    control = Server((bind, int(config["status_port"])), make_control_handler(node, token))
    model = Server((bind, int(config["model_port"])), make_model_handler(node, token))
    stop = threading.Event()
    for target in (control.serve_forever, model.serve_forever, lambda: register_loop(node, token, stop)):
        threading.Thread(target=target, daemon=True).start()
    try:
        node.run_guard(stop)
    finally:
        node.unload("node stopping")
    return 0


def run(home: Path = HERE) -> int:
    """Under pythonw (the scheduled task): start python.exe without a window and wait for it, so the listener
    is python.exe (the program the firewall rules name) and nothing ever opens a console."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        child = subprocess.Popen([str(exe.with_name("python.exe")), str(Path(__file__).resolve()), "serve"],
                                 cwd=str(home), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        return child.wait()
    return serve(home)


TASK_NAME = "Litha mesh node"
RULE_NAME = "Litha mesh node (LAN)"


def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def firewall_command(python: Path, config: dict) -> list[str]:
    ports = f"{int(config['model_port'])},{int(config['status_port'])}"
    return ["netsh", "advfirewall", "firewall", "add", "rule", f"name={RULE_NAME}", "dir=in", "action=allow",
            "protocol=TCP", f"localport={ports}", "remoteip=LocalSubnet", f"program={python}", "profile=any"]


def install(home: Path = HERE) -> int:
    """Per-user scheduled task (every 5 minutes; the mutex keeps one copy, so it also restarts a crashed node) and,
    with admin rights, the LAN-only firewall rule. Without admin rights the exact rule goes to OWNER-TODO.txt."""
    config = load_config(home)
    for key in ("llama_server", "model_path"):
        if not resolve(home, config[key]).is_file():
            print(f"warning: {key} not found at {resolve(home, config[key])} (edit node.json)")
    read_or_create_token(Path(os.path.expanduser(config["token_file"])))
    exe = Path(sys.executable)
    pythonw, python = exe.with_name("pythonw.exe"), exe.with_name("python.exe")
    action = f'"{pythonw if pythonw.is_file() else exe}" "{Path(__file__).resolve()}" run'
    if len(action) > 261:
        print("the task command is longer than Windows allows (261 characters); use a shorter folder")
        return 1
    done = subprocess.run(["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", "5", "/TN", TASK_NAME, "/TR", action],
                          capture_output=True, text=True, creationflags=NO_WINDOW)
    print((done.stdout or done.stderr).strip())
    if done.returncode:
        return done.returncode
    rule = firewall_command(python if python.is_file() else exe, config)
    if is_admin():
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"],
                       capture_output=True, creationflags=NO_WINDOW)
        added = subprocess.run(rule, capture_output=True, text=True, creationflags=NO_WINDOW)
        print("firewall rule:", (added.stdout or added.stderr).strip())
    else:
        line = " ".join(f'"{p}"' if " " in p else p for p in rule)
        (home / "OWNER-TODO.txt").write_text(
            "Run once in an administrator command prompt so other machines on the LAN can reach the node:\r\n"
            + line + "\r\n", encoding="utf-8")
        print("not admin: the firewall rule is in OWNER-TODO.txt (run it as administrator)")
    subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME], capture_output=True, creationflags=NO_WINDOW)
    print(f"started; status: http://127.0.0.1:{int(config['status_port'])}/status")
    return 0


def uninstall(home: Path = HERE) -> int:
    config = load_config(home)
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME], creationflags=NO_WINDOW)
    try:                                                         # free the card, then end the node
        main(["unload"])
    except SystemExit:
        pass
    pid_file = home / "logs" / "node.pid"
    if pid_file.is_file():
        subprocess.run(["taskkill", "/F", "/PID", pid_file.read_text().strip()], capture_output=True,
                       creationflags=NO_WINDOW)
        pid_file.unlink(missing_ok=True)
    if is_admin():
        subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"],
                       creationflags=NO_WINDOW)
    else:
        print(f'as administrator: netsh advfirewall firewall delete rule name="{RULE_NAME}"')
    print(f"removed the task; the folder {home} and the mesh token ({config['token_file']}) are left in place")
    return 0


def deploy(target: str, folder: str, engine: str, model: str, python: str, node_json: str) -> int:
    """Copy this package (+ engine, model, Python, the mesh token) to a Windows machine over ssh and install it.
    The remote shell is cmd (Windows OpenSSH). The token is copied as a file, never shown."""
    remote = folder.rstrip("\\/")
    rfwd = remote.replace("\\", "/")

    def ssh(command: str) -> int:
        return subprocess.run(["ssh", "-o", "BatchMode=yes", target, command]).returncode

    def scp(sources: list[str], dest: str, recursive: bool = False) -> int:
        return subprocess.run(["scp", "-q", "-B", *(["-r"] if recursive else []), *sources, f"{target}:{dest}"]).returncode

    steps = [lambda: ssh(f'if not exist "{remote}\\models" mkdir "{remote}\\models" & '
                         f'if not exist "%USERPROFILE%\\.star" mkdir "%USERPROFILE%\\.star"'),
             lambda: scp([str(HERE / n) for n in ("node_agent.py", "install.cmd", "uninstall.cmd", "README.md")],
                         rfwd + "/"),
             lambda: scp([node_json or str(HERE / "node.json")], rfwd + "/node.json"),
             lambda: scp([os.path.expanduser(load_config()["token_file"])], ".star/mesh_token")]
    if engine:
        steps.append(lambda: scp([engine.rstrip("\\/")], rfwd + "/engine", recursive=True))
    if python:
        steps.append(lambda: scp([python.rstrip("\\/")], rfwd + "/python", recursive=True))
    if model:
        steps.append(lambda: scp([model], rfwd + "/models/" + Path(model).name))
    steps.append(lambda: ssh(f'"{remote}\\install.cmd"'))
    for step in steps:
        code = step()
        if code:
            print(f"deploy step failed (exit {code})")
            return code
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="node_agent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "serve", "status", "load", "unload", "off", "on", "install",
                                            "uninstall", "deploy"])
    parser.add_argument("--ssh", default="", help="deploy: user@host of the target Windows PC")
    parser.add_argument("--dir", default="D:\\Litha", help="deploy: folder on the target")
    parser.add_argument("--engine", default="", help="deploy: local llama.cpp CUDA folder to copy as engine\\")
    parser.add_argument("--model", default="", help="deploy: local .gguf to copy into models\\")
    parser.add_argument("--python", default="", help="deploy: local Python folder to copy as python\\ (optional)")
    parser.add_argument("--node-json", default="", help="deploy: node.json for the target")
    args = parser.parse_args(argv)
    home = HERE
    config = load_config(home)
    base = f"http://127.0.0.1:{int(config['status_port'])}"
    if args.command == "run":
        return run(home)
    if args.command == "serve":
        return serve(home)
    if args.command == "install":
        return install(home)
    if args.command == "uninstall":
        return uninstall(home)
    if args.command == "deploy":
        if not args.ssh:
            parser.error("deploy needs --ssh user@host")
        return deploy(args.ssh, args.dir, args.engine, args.model, args.python, args.node_json)
    if args.command == "off":
        (home / "OFF").write_text("off\n", encoding="utf-8")
        print("off: the model is unloaded within seconds and stays off until 'on'")
        return 0
    if args.command == "on":
        (home / "OFF").unlink(missing_ok=True)
        print("on")
        return 0
    try:
        if args.command == "status":
            print(json.dumps(http_json("GET", base + "/status")[1], indent=2))
            return 0
        token = read_or_create_token(Path(os.path.expanduser(config["token_file"])))
        req = urllib.request.Request(base + "/" + args.command, data=b"{}", method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=10) as resp:
                code, data = resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            code, data = exc.code, json.loads(exc.read() or b"{}")
        print(code, data.get("state"), data.get("reason"))
        return 0 if code < 300 else 1
    except OSError as exc:
        print(f"the node does not answer on {base} ({type(exc).__name__})")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
