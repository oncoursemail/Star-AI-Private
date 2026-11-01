"""Config, the camera process (start / stop / status) and its heartbeat file.

Data folder: STAR_VTUBER_DIR, else <STAR_ROOT>/home/vtuber, else %ProgramData%\\STAR\\vtuber.
  config.json   the settings below (all optional)
  status.json   written once a second by the camera process: pid, beat, frames, fps, dropped, quality, device, model
  stop.flag     "turn the camera off": the process polls it, exits and removes it
  camera.log    the process's stdout/stderr

The camera runs as its own hidden, below-normal-priority process so that her voice call, her game and the brain
connection never wait for a frame, and so "camera off" really releases the virtual camera device.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

BEAT_STALE_S = 5.0


def data_dir() -> Path:
    override = os.environ.get("STAR_VTUBER_DIR")
    if override:
        return Path(override)
    from ..home.paths import home_dir
    home = home_dir()
    if home is not None:
        return home / "vtuber"
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "STAR" / "vtuber"


@dataclass
class Config:
    model: str = "starface"          # vtuber_model: 'starface' | 'placeholder' | a folder with avatar.json
    width: int = 1280
    height: int = 720
    fps: float = 30.0
    backend: str = "unitycapture"    # 'unitycapture' (named "STAR Camera") | 'obs' (fixed name, fallback) | '' = any
    device_name: str = "STAR Camera"
    mode: str = "normal"             # normal | cat | puppy (ears and tail, see stream_motion)
    reduced_motion: bool = False
    feed_port: int = 39541           # her voice process sends mouth frames here (127.0.0.1 only)
    vmc_port: int = 0                # >0: also send the pose to a VMC receiver on this port (VSeeFace, Warudo)
    use_emotion: bool = True         # face and cues from star.emotion when its setting is on
    allow_share_screen: bool = True  # the "share screen" activity (the owner asked for it; false switches it off)
    extra: dict = field(default_factory=dict)


def load_config(folder: Path | None = None) -> Config:
    path = (folder or data_dir()) / "config.json"
    cfg = Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    for key, value in raw.items():
        if key == "extra" or not hasattr(cfg, key):
            continue
        current = getattr(cfg, key)
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        fits = {bool: isinstance(value, bool), int: isinstance(value, int) and not isinstance(value, bool),
                float: number, str: isinstance(value, str)}.get(type(current), False)
        if fits:
            setattr(cfg, key, type(current)(value))
    cfg.width = min(3840, max(64, cfg.width))
    cfg.height = min(2160, max(64, cfg.height))
    cfg.fps = min(60.0, max(5.0, cfg.fps))
    if cfg.mode not in ("normal", "cat", "puppy"):
        cfg.mode = "normal"
    return cfg


def set_mode(mode: str, folder: Path | None = None) -> dict:
    """Save a motion mode without starting a camera or replacing the avatar art."""
    mode = "puppy" if mode == "dog" else mode
    if mode not in ("normal", "cat", "puppy"):
        raise ValueError("mode must be normal, cat, puppy or dog")
    folder = folder or data_dir()
    path = folder / "config.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("camera config must be a JSON object")
    raw["mode"] = mode
    _write(path, raw)
    return {"requested_mode": mode, "camera_started": False,
            "note": "Ears and tail are visible only in a model with matching painted layers and bindings."}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def write_status(folder: Path, **fields) -> None:
    _write(folder / "status.json", {"pid": os.getpid(), "beat": time.time(), **fields})


def read_status(folder: Path | None = None, now: float | None = None) -> dict:
    """{alive, ...status.json}: alive means a heartbeat younger than 5 s. A missing file is {alive: False}."""
    folder = folder or data_dir()
    try:
        data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"alive": False}
    if not isinstance(data, dict):
        return {"alive": False}
    age = (time.time() if now is None else now) - float(data.get("beat", 0))
    data["alive"] = age < BEAT_STALE_S and not data.get("stopped") and not data.get("error")
    return data


def stop_requested(folder: Path) -> bool:
    return (folder / "stop.flag").exists()


def _spawn(argv: list[str], env: dict, log_path: Path):                # pragma: no cover - launches a real process
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = 0
    if os.name == "nt":
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | 0x00004000)                                         # BELOW_NORMAL_PRIORITY_CLASS
    log = open(log_path, "ab")
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, creationflags=flags,
                            close_fds=True)


def _kill_tree(pid: int) -> None:                                      # pragma: no cover - real process tree
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        os.kill(pid, 15)


def status_error(folder: Path) -> str:
    try:
        return str(json.loads((folder / "status.json").read_text(encoding="utf-8")).get("error", ""))
    except (OSError, ValueError):
        return ""


def start(folder: Path | None = None, *, wait_s: float = 12.0, spawn: Callable = _spawn,
          sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> dict:
    """Start the camera process if it is not already running; returns the status once frames flow (or the failure)."""
    folder = folder or data_dir()
    current = read_status(folder)
    if current["alive"]:
        return {**current, "started": False}
    for name in ("stop.flag", "status.json"):
        try:
            (folder / name).unlink()
        except OSError:
            pass
    env = {**os.environ, "STAR_VTUBER_DIR": str(folder)}
    spawn([sys.executable, "-m", "star.vtuber", "run"], env, folder / "camera.log")
    deadline = clock() + wait_s
    while clock() < deadline:
        status = read_status(folder)
        if status.get("error"):
            return {**status, "alive": False, "started": True}
        if status["alive"] and int(status.get("frames", 0)) > 0:
            return {**status, "started": True}
        sleep(0.3)
    return {**read_status(folder), "started": True, "error": status_error(folder) or "no frames within the wait"}


def stop(folder: Path | None = None, *, wait_s: float = 5.0, kill: Callable[[int], None] = _kill_tree,
         sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time) -> dict:
    """Ask the process to exit (stop.flag), force-kill its tree if it has not gone after wait_s."""
    folder = folder or data_dir()
    status = read_status(folder)
    if not status["alive"]:
        return {**status, "stopped": True, "forced": False}
    _write(folder / "stop.flag", {"at": time.time()})
    deadline = clock() + wait_s
    while clock() < deadline:
        if not read_status(folder)["alive"]:
            return {**read_status(folder), "stopped": True, "forced": False}
        sleep(0.2)
    pid = int(status.get("pid", 0))
    if pid:
        kill(pid)
    try:
        write_status(folder, stopped=True)
    except OSError:
        pass
    return {"alive": False, "stopped": True, "forced": True}


def frames_flowing(folder: Path | None = None, *, wait_s: float = 3.0, sleep: Callable[[float], None] = time.sleep,
                   clock: Callable[[], float] = time.time) -> bool:
    """True when the heartbeat's frame counter grows during wait_s (a stuck process still has a recent beat)."""
    folder = folder or data_dir()
    first = read_status(folder)
    if not first["alive"]:
        return False
    deadline = clock() + wait_s
    while clock() < deadline:
        sleep(0.4)
        later = read_status(folder)
        if later["alive"] and int(later.get("frames", 0)) > int(first.get("frames", 0)):
            return True
    return False


def config_dict(cfg: Config) -> dict:
    return asdict(cfg)
