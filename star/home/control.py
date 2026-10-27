"""The owner's controls on STAR's PC: the data folder, the global stop and the action log.

Everything lives in one folder (<install root>\\home, see paths.py; with no root C:\\ProgramData\\STAR\\home;
STAR_HOME_DIR overrides both):

  STOP          present = STAR stops: the loop sleeps, the executor refuses every action. The owner creates it with
                "STAR STOP.cmd" on the desktop, `python -m star.home stop`, or the hotkey Ctrl+Alt+Shift+F12.
  actions.jsonl one JSON line per action, written before it runs ("start") and after ("done" / "refused" / "error").
  config.json   brain address, model, compute bounds, dry_run (written by setup, edited by the owner).

STAR's own actions may not touch this folder (host.py refuses them), so only the owner removes STOP.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from ..redact import redact_text
from . import paths

STOP_NAME = "STOP"
LOG_NAME = "actions.jsonl"
CONFIG_NAME = "config.json"
LOG_ARG_CHARS = 400
DEFAULTS = {
    "brain_url": "",                 # e.g. http://<server-1-address>:8080 ; set by the owner or the lead, not in git
    "model": "star-fast",
    "key_file": "",                  # "" = %USERPROFILE%\.star\server_api_key
    "dry_run": False,
    "max_steps": 12,                 # tool calls per session
    "session_minutes": 20,           # wall clock per session
    "sessions_per_day": 24,
    "pause_minutes": 30,             # between sessions
    "request_timeout_s": 180,
    "vision": False,                 # attach screenshots to the model (only if the brain model reads images)
    "game_reserve_mb": 5000,         # video memory kept free for her game while one runs (8 GB card)
    "game_processes": ["RobloxPlayerBeta.exe", "javaw.exe", "Minecraft.Windows.exe", "RobloxStudioBeta.exe"],
    "availability": {},              # star.home.attention.DEFAULTS overrides: quiet_hours, delays, call chances
    "notifications": {"enabled": True, "apps": ["discord", "roblox"], "poll_s": 2.0},
    "close_friends": {},             # {"discord": ["her owner's display name"]}: always treated as close friends
    "calls": {},                     # call_accept_keys, call_idle_leave_minutes, call_max_minutes, call_pickup_wait_s
    "play": {"obby_places": [], "session_minutes": 12, "step_s": 3.0, "voice_in_games": True},
    "voice": {},                     # VoiceSettings overrides on top of star.senses.instant.PC_PRESET
}


def home_dir() -> Path:
    override = os.environ.get("STAR_HOME_DIR")
    if override:
        return Path(override)
    rooted = paths.home_dir()
    if rooted:
        return rooted
    base = os.environ.get("ProgramData") or r"C:\ProgramData"
    return Path(base) / "STAR" / "home"


def load_config(home: Path | None = None) -> dict:
    path = (home or home_dir()) / CONFIG_NAME
    config = dict(DEFAULTS)
    try:
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(saved, dict):
            config.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return config


def stop_path(home: Path | None = None) -> Path:
    return (home or home_dir()) / STOP_NAME


def stopped(home: Path | None = None) -> bool:
    return stop_path(home).exists()


def stop(home: Path | None = None, reason: str = "owner") -> Path:
    path = stop_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {reason}\n", encoding="utf-8")
    return path


def resume(home: Path | None = None) -> bool:
    path = stop_path(home)
    if path.exists():
        path.unlink()
        return True
    return False


def _short(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)[:LOG_ARG_CHARS]
    if isinstance(value, dict):
        return {str(k): _short(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_short(v) for v in list(value)[:20]]
    return value


def log_action(home: Path | None, action: str, phase: str, **fields) -> None:
    """Append one line. Text is redacted and cut; the log is never rewritten."""
    path = (home or home_dir()) / LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": action, "phase": phase}
    row.update({k: _short(v) for k, v in fields.items()})
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_log(home: Path | None = None, last: int = 20) -> list[dict]:
    path = (home or home_dir()) / LOG_NAME
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-last:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def hotkey_watch(home: Path | None = None) -> None:  # pragma: no cover - needs a Windows desktop session
    """Block on the global hotkey Ctrl+Alt+Shift+F12; each press creates STOP. Run in a daemon thread."""
    import ctypes
    import ctypes.wintypes as wt
    user32 = ctypes.WinDLL("user32")  # pyright: ignore[reportAttributeAccessIssue]
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, VK_F12, WM_HOTKEY = 0x1, 0x2, 0x4, 0x7B, 0x312
    if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL | MOD_SHIFT, VK_F12):
        log_action(home, "hotkey", "error", detail="RegisterHotKey failed (another program holds it)")
        return
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            stop(home, "hotkey")
            log_action(home, "hotkey", "done", detail="STOP created")
