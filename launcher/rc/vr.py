"""Is there a VR runtime for Rec Room's VR mode? Read-only checks of the two usual places.

Never blocks a launch: the RC tools decide whether a launch plan is valid. This only lets the UI say "no VR runtime
found" before the player puts a headset on and wonders why nothing happens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

STEAMVR_EXES = ("vrserver.exe", "vrmonitor.exe")


def _openxr_active_runtime() -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Khronos\OpenXR\1") as key:
            value, _ = winreg.QueryValueEx(key, "ActiveRuntime")
            return str(value)
    except OSError:
        return None


def _steam_roots() -> list[Path]:
    roots = []
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(var)
        if base:
            roots.append(Path(base) / "Steam" / "steamapps" / "common" / "SteamVR")
    return roots


def detect(*, openxr: Callable[[], str | None] = _openxr_active_runtime, steamvr_roots: Callable[[], list[Path]] = _steam_roots,
           processes: Callable[[], dict[int, str]] = lambda: {}) -> dict:
    runtimes: list[str] = []
    active = openxr()
    if active and Path(active).is_file():
        name = Path(active).stem
        try:
            name = json.loads(Path(active).read_text(encoding="utf-8")).get("runtime", {}).get("name", name)
        except (OSError, ValueError, AttributeError):
            pass
        runtimes.append(f"OpenXR: {name}")
    if any((root / "bin" / "win64" / "vrserver.exe").is_file() for root in steamvr_roots()):
        runtimes.append("SteamVR")
    running = bool(set(processes().values()) & set(STEAMVR_EXES))
    available = bool(runtimes) or running
    note = ("VR runtime found: " + ", ".join(runtimes) + (" (SteamVR is running)" if running else "")) if available else \
        "No VR runtime found (SteamVR or an OpenXR runtime). VR mode may not start."
    return {"available": available, "runtimes": runtimes, "steamvrRunning": running, "note": note}
