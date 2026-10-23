"""Settings > "Use my GPU": STAR's code model on this PC's graphics card, chosen per request.

When the switch is on and STAR Server is the provider, the desktop starts a CUDA llama-server on 127.0.0.1 with
the same model file the server runs as `star-fast` (Qwen3.6-35B-A3B Q4_K_M) and sends that model's requests to it.
Everything else stays as it is: the agent loop, memory, tools, lessons and identity run in the desktop exactly as
before, and every other model (quick chat, images, embeddings, the deep model) still goes to the server. Nothing
listens on the network: the PC only talks to itself (loopback) and, as before, out to the server.

Settings measured on the owner's RTX 3060 Ti 8 GB + Ryzen 5 5500 (docs/agents/gpu-helper-test.md): 31-33 tok/s
writing and ~790 tok/s reading, against ~11 and ~70 on the server, with all layers on the GPU except the experts of
34 layers (`--n-cpu-moe 34`), batch 2048, flash attention, 6 threads and nothing spilled into shared GPU memory.

Rules:
  * Off by default. On: the model is loaded when the switch is turned on or when a request needs it, and unloaded
    after `gpu_idle_minutes` without a request.
  * It yields to the owner: it does not start, and an idle one stops, while another program uses the graphics card
    (utilisation, or too little free video memory) or the image engine (ComfyUI) runs. It resumes once the card has
    been free for two minutes. Before STAR makes a picture on this PC it is stopped, so both are never loaded.
  * Any failure or timeout sends that request to the server instead. A stream that breaks after some text was
    shown continues on the server from that text (the server continues a final assistant message; measured on
    llama.cpp b11541). Tool calls from the PC are held back until its answer is complete, so a break never leaves
    half a tool call behind. The only visible trace is the status line in Settings.
  * Turning the switch off while an answer runs on the PC does not cut that answer: the model keeps running until
    the answer (and any draft warm-up) is done, then stops. Requests made after the switch went off go to the
    server at once, and turning it on again before the answer ends simply keeps the loaded model. Turning it on
    mid-answer affects only the next request.
  * "Automatically turn on at night" (`use_my_pc_auto_night`, on by default): between NIGHT_START and NIGHT_END
    o'clock local time the PC may be used even when the switch is off; at NIGHT_END it follows the switch again
    (a running answer finishes first, like a switch-off). Every rule above still applies.
  * One request at a time (`-np 1`): a second request made meanwhile (a sub-agent, a candidate) goes to the server.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

_LOG = logging.getLogger(__name__)

NAME = "star-fast"                        # the name the PC server answers to (the server's own id for this model)
HEAVY = ("star-fast", "star-code")        # server_roles.ROLE_NAMES["code"]: the names of that model on the server
N_CPU_MOE = 34
BATCH = 2048
CONTEXT = 32768                           # the server's per-slot context for star-fast (65536 / 2 slots)
NEED_VRAM_MIB = 6200                      # free video memory needed to start (measured use with these settings)
LOW_VRAM_MIB = 300                        # less free than this while loaded: another program wants the memory
NEED_RAM_MIB = 8192                       # free system memory needed to start (the CPU-side experts are mapped)
BUSY_PERCENT = 50                         # GPU utilisation from other programs that counts as "in use"
POLL_SECONDS = 3.0
RESUME_SECONDS = 120.0
LOAD_SECONDS = 300.0
RETRY_SECONDS = 60.0
CONNECT_SECONDS = 2.0
SILENCE_SECONDS = 90.0                    # a 32K prompt is read in ~40 s; then tokens arrive every ~30 ms

NIGHT_START, NIGHT_END = 1, 8             # local hours; the same window as the night turbo (server/night_school/pc/turbo.py)

LABELS = {"off": "Off", "starting": "Starting", "ready": "Ready", "busy": "Paused", "idle": "Sleeping",
          "failed": "Failed"}


def local_hour() -> int:
    return time.localtime().tm_hour


def night_now(hour: int | None = None) -> bool:
    hour = local_hour() if hour is None else hour
    return NIGHT_START <= hour < NIGHT_END


def pc_allowed(settings, hour: int | None = None) -> bool:
    """May STAR use this PC now: the switch is on, or it is night and "Automatically turn on at night" is on."""
    if getattr(settings, "use_my_gpu", False) is True:
        return True
    return getattr(settings, "use_my_pc_auto_night", False) is True and night_now(hour)


def threads() -> int:
    """Generation threads: 6 (the measured best on a 6-core Ryzen 5 5500), fewer on a smaller CPU."""
    return max(1, min(6, (os.cpu_count() or 12) // 2))


def default_folder(home: Path) -> Path:
    return Path(home) / "gpu-helper"


def files_for(settings, home: Path) -> tuple[Path, Path]:
    """(llama-server.exe, model file): the owner's paths, or the defaults in <app data>/gpu-helper/."""
    folder = default_folder(home)
    exe = str(getattr(settings, "gpu_helper_server", "") or "").strip()
    model = str(getattr(settings, "gpu_helper_model", "") or "").strip()
    return (Path(exe).expanduser() if exe else folder / "llama-server.exe",
            Path(model).expanduser() if model else folder / "star-fast.gguf")


def arguments(exe: Path, model: Path, port: int) -> list[str]:
    """The fixed command line. Only a file named llama-server.exe and a .gguf model are accepted."""
    if exe.name.lower() != "llama-server.exe" or not exe.is_file():
        raise ValueError(f"llama-server.exe (CUDA build) was not found at {exe}")
    if model.suffix.lower() != ".gguf" or not model.is_file():
        raise ValueError(f"The model file was not found at {model}")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Invalid port")
    return [str(exe), "-m", str(model), "--alias", NAME, "--host", "127.0.0.1", "--port", str(port),
            "-ngl", "99", "--n-cpu-moe", str(N_CPU_MOE), "-fa", "on", "-t", str(threads()),
            "-b", str(BATCH), "-ub", str(BATCH), "-c", str(CONTEXT), "-np", "1", "--jinja", "--reasoning", "off"]


@dataclass(frozen=True)
class GpuReading:
    utilization: int     # percent, whole card
    used_mib: int
    total_mib: int

    @property
    def free_mib(self) -> int:
        return self.total_mib - self.used_mib


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def read_gpu() -> GpuReading | None:
    """The first NVIDIA card from nvidia-smi; None when there is none or it does not answer."""
    tool = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
    try:
        out = subprocess.run([tool, "--query-gpu=utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=_no_window()).stdout
        util, used, total = (int(part.strip()) for part in out.splitlines()[0].split(","))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
    return GpuReading(util, used, total)


def free_ram_mib() -> int | None:
    """Available physical memory (Windows); None elsewhere or when it cannot be read."""
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
    try:
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
    except (AttributeError, OSError):
        return None
    return int(status.available // (1024 * 1024))


def port_open(port: int) -> bool:
    """Is something listening on 127.0.0.1:port? (ComfyUI, the image engine.)"""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
            return True
    except (OSError, ValueError):
        return False


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_WARM_TEXT = ('local Players = game:GetService("Players")\n'
              'local function onPlayerAdded(player)\n'
              '  local stats = Instance.new("Folder")\n'
              '  stats.Name = "leaderstats"\n'
              '  stats.Parent = player\n'
              'end\n'
              'Players.PlayerAdded:Connect(onPlayerAdded)\n') * 12


def warm_up(base: str) -> None:
    """Read one ~500-token prompt so the model's CPU-side experts are paged in before the first real question.

    Measured: the first request after a load read its prompt at ~30 tok/s while the 14 GB of experts came off the
    disk; the next ones at 170-220 tok/s on short prompts.
    """
    import httpx
    httpx.post(base[:-3] + "/completion", json={"prompt": _WARM_TEXT, "n_predict": 1, "cache_prompt": False},
               timeout=180.0, trust_env=False)


def healthy(base: str) -> bool:
    import httpx
    try:
        return httpx.get(base[:-3] + "/health", timeout=1.0, trust_env=False).status_code == 200
    except Exception:
        return False


class GpuHelper:
    """The PC model server's life: start, health, yield, idle stop, and which state the status line shows."""

    def __init__(self, *, popen=subprocess.Popen, gpu=read_gpu, ram=free_ram_mib, image_engine=port_open,
                 health=healthy, clock=time.monotonic, pick_port=free_port, watchdog: bool = True, warm=warm_up, hour=None):
        self._popen, self._gpu, self._ram, self._image_engine = popen, gpu, ram, image_engine
        self._health, self._clock, self._pick_port, self._watchdog = health, clock, pick_port, watchdog
        self._hour = hour or (lambda: local_hour())
        self._warm = warm             # None: ready as soon as /health answers
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.enabled = False
        self.state, self.reason = "off", ""
        self.files: tuple[Path, Path] | None = None
        self.log_path: Path | None = None
        self.idle_seconds = 600.0
        self.comfy_port = 8188
        self.process = None
        self.base = ""
        self.in_flight = 0
        self.warms = 0                # draft warm-ups on the PC right now (star/prefill_warm.py), not leases
        self.started_at = self.last_used = self.since = 0.0
        self.want_start = False
        self.switch_on = False        # the owner's switch itself (the helper may also be on for the night)
        self.night_only = False       # on only because of "Automatically turn on at night"
        self.draining = False         # switched off while a request ran: stop the model when the last one ends
        self.hot_ticks = 0
        self.warming = False
        self.tokens_per_second: float | None = None
        self.last_fallback = ""

    # ---- configuration and status -------------------------------------------------------------------------------
    def configure(self, settings, home: Path, *, start: bool = False) -> None:
        """Apply the saved settings. Off stops the model. `start`: load it now (the owner just turned the switch
        on); otherwise it loads with the next request that needs it."""
        switch = getattr(settings, "use_my_gpu", False) is True
        on = pc_allowed(settings, self._hour())
        files = files_for(settings, home)
        with self._lock:
            self.idle_seconds = 60.0 * int(getattr(settings, "gpu_idle_minutes", 10) or 10)
            self.comfy_port = int(getattr(settings, "comfy_port", 8188) or 8188)
            self.log_path = Path(home) / "logs" / "gpu-helper.log"
            changed = files != self.files
            self.files = files
            self.switch_on, self.night_only = switch, on and not switch
            if not on:
                self.enabled = False
                if self.in_flight or self.warms:      # an answer is running here: let it finish, then stop
                    self.draining = True
                else:
                    self._stop_locked()
                self._set("off", "")
                return
            if changed and self.process is not None:
                self._stop_locked()
                self._set("idle", "")
            resumed = self.draining and self.process is not None
            self.draining = False
            if resumed:                              # switched back on before the answer ended: still loaded
                self._set("ready", "")
            elif not self.enabled or self.state in ("off", "failed", "idle"):
                if self.state != "idle":
                    self._set("idle", "")
                self.want_start = self.want_start or start
            self.enabled = True
        if self._watchdog:
            self._ensure_thread()
        self._wake.set()

    def status(self) -> dict:
        with self._lock:
            return {"state": self.state, "label": LABELS[self.state], "text": self._text(),
                    "tokens_per_second": self.tokens_per_second, "enabled": self.enabled,
                    "switch": self.switch_on, "night": self.night_only}

    def _text(self) -> str:
        text = self._state_text()
        return text + (f" On automatically at night until {NIGHT_END:02d}:00." if self.night_only and self.enabled else "")

    def _state_text(self) -> str:
        speed = f" Last answer: {self.tokens_per_second:.1f} tokens per second." if self.tokens_per_second else ""
        fallback = f" The last request went to the server ({self.last_fallback})." if self.last_fallback else ""
        if self.state == "off":
            return "Off. Every answer comes from STAR Server."
        if self.state == "starting":
            return "Starting: loading STAR's code model on your graphics card. The server answers meanwhile."
        if self.state == "ready":
            return "Ready: STAR's code model runs on your graphics card." + speed + fallback
        if self.state == "busy":
            return f"Paused: {self.reason}. The server answers meanwhile."
        if self.state == "idle":
            return ((self.reason + ". ") if self.reason else "") + "Starts again with your next question." + fallback
        return f"Failed: {self.reason}. The server answers meanwhile."

    def _set(self, state: str, reason: str) -> None:
        if (state, reason) != (self.state, self.reason):
            _LOG.info("Use my GPU: %s %s", state, reason)
        self.state, self.reason = state, reason
        self.since = self._clock()

    # ---- requests -----------------------------------------------------------------------------------------------
    def lease(self) -> str | None:
        """The PC server's address for one request, or None (then the request goes to the server).

        Never blocks: a model that is not loaded yet is asked to start, and this request uses the server.
        """
        with self._lock:
            if not self.enabled or (self.night_only and not night_now(self._hour())):
                return None
            if self.state == "ready" and self.in_flight == 0 and self._alive():
                self.in_flight = 1
                self.last_used = self._clock()
                return self.base
            if self.state in ("idle", "failed") or (self.state == "ready" and not self._alive()):
                self.want_start = True
        self._wake.set()
        return None

    def warm_begin(self) -> str | None:
        """The PC server's address for a draft warm-up when it is loaded and answering nothing, else None.

        Not a lease (star/prefill_warm.py): the real turn still finds the PC free and queues behind the short
        warm-up there; a model that is not loaded is never started for it. While it runs the card is busy
        with STAR's own work, so the watchdog does not take it for another program. End with `warm_end()`."""
        with self._lock:
            if self.enabled and self.state == "ready" and self.in_flight == 0 and self._alive():
                self.warms += 1
                self.last_used = self._clock()
                return self.base
            return None

    def warm_end(self) -> None:
        with self._lock:
            self.warms = max(0, self.warms - 1)
            self.last_used = self._clock()
            if self.draining and not self.warms and not self.in_flight:
                self._stop_locked()

    def finish(self, *, ok: bool, reason: str = "", hard: bool = False, tokens_per_second: float | None = None):
        """End of a leased request. `hard`: the PC server itself failed (connection, timeout); it is stopped."""
        with self._lock:
            self.in_flight = 0
            self.last_used = self._clock()
            if tokens_per_second:
                self.tokens_per_second = round(float(tokens_per_second), 1)
            self.last_fallback = "" if ok else reason[:120]
            if not ok and hard:
                self._stop_locked()
                if self.enabled:
                    self._set("failed", reason[:160] or "the graphics card server stopped answering")
            elif self.draining and not self.warms:
                self._stop_locked()

    def yield_to(self, reason: str) -> None:
        """Stop now (for the image engine): the card is never shared by two big models."""
        with self._lock:
            if not self.enabled:
                return
            self._stop_locked()
            self._set("busy", reason)

    def shutdown(self) -> None:
        with self._lock:
            self.enabled = False
            self._stop_locked()
            self._set("off", "")
        self._wake.set()

    # ---- the watchdog -------------------------------------------------------------------------------------------
    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="star-gpu-helper", daemon=True)
                self._thread.start()

    def _loop(self) -> None:
        while True:
            self._wake.wait(POLL_SECONDS)
            self._wake.clear()
            with self._lock:
                if not self.enabled:
                    self._thread = None
                    return
            try:
                self.tick()
            except Exception as exc:          # the watchdog must never die silently
                _LOG.warning("Use my GPU watchdog: %s", type(exc).__name__)

    def tick(self) -> None:
        """One look at the card and the process (every few seconds)."""
        with self._lock:
            if not self.enabled:
                return
            now = self._clock()
            if self.night_only and not night_now(self._hour()):     # the night is over: back to the switch (off)
                self.enabled = self.night_only = False
                if self.in_flight or self.warms:
                    self.draining = True
                else:
                    self._stop_locked()
                self._set("off", "")
                return
            if self.process is not None:
                code = self.process.poll()
                if code is not None:
                    self._stop_locked()
                    self._set("failed", f"the graphics card server stopped (exit code {code}); see logs\\gpu-helper.log")
                    return
                if self.state == "starting":
                    if self.warming:
                        return
                    if self._health(self.base):
                        if self._warm is None:
                            self.last_used = now
                            self._set("ready", "")
                        else:
                            self.warming = True
                            threading.Thread(target=self._warm_then_ready, args=(self.process, self.base),
                                             name="star-gpu-warm", daemon=True).start()
                    elif now - self.started_at > LOAD_SECONDS:
                        self._stop_locked()
                        self._set("failed", f"the model did not load within {int(LOAD_SECONDS // 60)} minutes")
                    return
                if self.in_flight or self.warms:
                    return
                problem = self._card_problem(loaded=True)
                if problem:
                    self._stop_locked()
                    self._set("busy", problem)
                elif now - self.last_used > self.idle_seconds:
                    self._stop_locked()
                    self._set("idle", f"Stopped after {int(self.idle_seconds // 60)} idle minutes to free the card")
                return
            if self.state == "busy":
                if self._card_problem(loaded=False):
                    self.since = now
                elif now - self.since >= RESUME_SECONDS:
                    self._set("idle", "")
                return
            if not self.want_start or (self.state == "failed" and now - self.since < RETRY_SECONDS):
                return
            self.want_start = False
            problem = self._card_problem(loaded=False)
            if problem:
                self._set("busy", problem)
                return
            self._start_locked()

    def _warm_then_ready(self, process, base: str) -> None:
        try:
            self._warm(base)
        except Exception as exc:      # a failed warm-up only means a slower first answer
            _LOG.info("Use my GPU: warm-up failed (%s)", type(exc).__name__)
        with self._lock:
            self.warming = False
            if self.process is process and self.state == "starting" and self._alive():
                self.last_used = self._clock()
                self._set("ready", "")

    def _card_problem(self, *, loaded: bool) -> str:
        """Why the card is not STAR's right now, in words; '' when it is free."""
        if self._image_engine(self.comfy_port):
            return "the image engine (ComfyUI) is using the graphics card"
        reading = self._gpu()
        if reading is None:
            return "no NVIDIA graphics card answered (nvidia-smi)"
        if loaded:
            if reading.free_mib < LOW_VRAM_MIB:
                return "another program needs the graphics card's memory"
            self.hot_ticks = self.hot_ticks + 1 if reading.utilization >= BUSY_PERCENT else 0
            return "another program is using the graphics card" if self.hot_ticks >= 2 else ""
        if reading.utilization >= BUSY_PERCENT:
            return "another program is using the graphics card"
        if reading.free_mib < NEED_VRAM_MIB:
            return (f"only {reading.free_mib / 1024:.1f} GB of graphics memory is free "
                    f"({NEED_VRAM_MIB / 1024:.1f} GB needed)")
        ram = self._ram()
        if ram is not None and ram < NEED_RAM_MIB:
            return f"only {ram / 1024:.1f} GB of memory is free ({NEED_RAM_MIB // 1024} GB needed)"
        return ""

    def _start_locked(self) -> None:
        exe, model = self.files or (Path(), Path())
        try:
            port = self._pick_port()
            argv = arguments(exe, model, port)
        except ValueError as exc:
            self._set("failed", str(exc))
            return
        log = None
        try:
            if self.log_path is not None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                log = self.log_path.open("ab")
            self.process = self._popen(argv, stdin=subprocess.DEVNULL, stdout=log or subprocess.DEVNULL,
                                       stderr=subprocess.STDOUT, creationflags=_no_window())
        except OSError as exc:
            self._set("failed", f"llama-server.exe could not start ({type(exc).__name__})")
            return
        finally:
            if log is not None:
                log.close()           # the child keeps its own handle
        self.base = f"http://127.0.0.1:{port}/v1"
        self.started_at = self._clock()
        self.hot_ticks = 0
        self._set("starting", "")

    def _alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _stop_locked(self) -> None:
        process, self.process, self.base, self.in_flight, self.warming = self.process, None, "", 0, False
        self.draining = False
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except Exception as exc:
            _LOG.warning("Use my GPU: stopping the server failed (%s)", type(exc).__name__)


HELPER = GpuHelper()


# ---- per-request routing -------------------------------------------------------------------------------------------
def _has_images(messages) -> bool:
    for message in messages or ():
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(isinstance(part, dict) and part.get("type") != "text" for part in content):
            return True
    return False


def wanted(settings, kwargs: dict) -> bool:
    """Does this request belong on the PC: STAR's code model, text only?"""
    from .providers import _instance
    name = str(kwargs.get("model", ""))
    return ((name in HEAVY or _instance(settings, name)[1] in HEAVY)
            and not _has_images(kwargs.get("messages")))


def for_local(kwargs: dict) -> dict:
    """The same request for the PC server: its own model name, and no server slot number (it has one slot)."""
    local: dict = {**kwargs, "model": NAME}
    extra = local.get("extra_body")
    if isinstance(extra, dict) and "id_slot" in extra:
        local["extra_body"] = {key: value for key, value in extra.items() if key != "id_slot"}
    return local


def local_client(base: str):
    from openai import AsyncOpenAI
    import httpx
    timeout = httpx.Timeout(SILENCE_SECONDS, connect=CONNECT_SECONDS)
    return AsyncOpenAI(base_url=base, api_key="local-only", timeout=timeout, max_retries=0,
                       http_client=httpx.AsyncClient(trust_env=False, timeout=timeout))


def _speed(item) -> float | None:
    timings = getattr(item, "timings", None)
    if timings is None:
        timings = (getattr(item, "model_extra", None) or {}).get("timings")
    value = timings.get("predicted_per_second") if isinstance(timings, dict) else None
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def _why(exc: BaseException) -> tuple[str, bool]:
    """(reason in words, hard). An HTTP error answer is soft: the PC server is alive and only refused this one."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return f"the graphics card server answered HTTP {status}", False
    name = type(exc).__name__
    if "Timeout" in name:
        return "the graphics card server did not answer in time", True
    return f"the graphics card server stopped answering ({name})", True


async def _close(client) -> None:
    try:
        await client.close()
    except Exception:
        pass


class GpuRoutingClient:
    """`client.chat.completions.create(...)` that sends STAR's code model to the PC when it is ready.

    Every other attribute (embeddings, models, ...) is the server client's.
    """

    def __init__(self, server, settings, *, helper: GpuHelper | None = None, open_local=None):
        self._server, self._settings = server, settings
        self._helper = helper or HELPER
        self._open_local = open_local or local_client
        self.chat = self.completions = self

    def __getattr__(self, name):
        return getattr(self._server, name)

    async def create(self, **kwargs):
        send = self._server.chat.completions.create
        if not wanted(self._settings, kwargs):
            return await send(**kwargs)
        base = self._helper.lease()
        if base is None:
            return await send(**kwargs)
        client = self._open_local(base)
        try:
            reply = await client.chat.completions.create(**for_local(kwargs))
        except Exception as exc:
            await _close(client)
            reason, hard = _why(exc)
            self._helper.finish(ok=False, reason=reason, hard=hard)
            return await send(**kwargs)
        if not kwargs.get("stream") or not hasattr(reply, "__aiter__"):
            await _close(client)
            self._helper.finish(ok=True, tokens_per_second=_speed(reply))
            return reply
        return _FallbackStream(reply, client, kwargs, send, self._helper)


def _has_tool_call(chunk) -> bool:
    choices = getattr(chunk, "choices", None) or []
    return bool(choices) and bool(getattr(getattr(choices[0], "delta", None), "tool_calls", None))


def _text_of(chunk) -> str:
    choices = getattr(chunk, "choices", None) or []
    text = getattr(getattr(choices[0], "delta", None), "content", None) if choices else None
    return text if isinstance(text, str) else ""


class _FallbackStream:
    """The PC's stream; if it breaks, the rest comes from the server, continuing the text already shown."""

    def __init__(self, local, client, kwargs: dict, send, helper: GpuHelper):
        self._local, self._client, self._kwargs, self._send, self._helper = local, client, kwargs, send, helper

    def __aiter__(self):
        return self._run()

    async def _run(self):
        shown: list[str] = []
        held: list = []              # tool-call chunks and everything after them, released at the end
        speed = None
        finished = False
        try:
            try:
                async for chunk in self._local:
                    speed = _speed(chunk) or speed
                    if held or _has_tool_call(chunk):
                        held.append(chunk)
                        continue
                    shown.append(_text_of(chunk))
                    yield chunk
            except Exception as exc:
                reason, hard = _why(exc)
                finished = True
                self._helper.finish(ok=False, reason=reason, hard=hard)
                await _close(self._client)
                text = "".join(shown)
                kwargs = dict(self._kwargs)
                if text:
                    kwargs["messages"] = [*kwargs["messages"], {"role": "assistant", "content": text}]
                _LOG.info("Use my GPU: stream broke after %d characters (%s); continuing on the server",
                          len(text), reason)
                async for chunk in await self._send(**kwargs):
                    yield chunk
                return
            finished = True
            self._helper.finish(ok=True, tokens_per_second=speed)
            for chunk in held:
                yield chunk
        finally:
            if not finished:          # the reader stopped early (cancelled): not a failure
                self._helper.finish(ok=True)
            await _close(self._client)
