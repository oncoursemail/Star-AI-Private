"""Crash-loop guard for the launcher itself.

A small stub (the only file that never updates) calls `run_component` instead of starting the launcher directly:
it picks the current version folder from state.json, starts it, and treats a start that dies within `grace` seconds
as a failed boot. After two failed boots on a freshly installed version the updater switches to the previous version
and the stub starts that instead. A start that survives `grace` seconds counts as healthy and ends the probation.
The launcher may also call `Updater.confirm_healthy("launcher")` itself once its window is up.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from .client import Updater


def run_component(updater: Updater, name: str, argv: list[str] | None = None, grace: float = 20.0,
                  max_launches: int = 3) -> int:
    """Start `name`; return the exit code of the run that was kept. Falls back to the previous version after crashes."""
    code = 1
    for _ in range(max_launches):
        verdict = updater.on_boot(name)
        entry = updater.entry_path(name)
        if entry is None or not entry.is_file():
            raise FileNotFoundError(f"{name} is not installed or has no entry file")
        cmd = [sys.executable, str(entry)] if entry.suffix == ".py" else [str(entry)]
        started = time.monotonic()
        proc = subprocess.Popen(cmd + (argv or []), cwd=str(entry.parent))
        try:
            code = proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            updater.confirm_healthy(name)
            return proc.wait()
        if code == 0 and time.monotonic() - started >= 1.0:  # a deliberate quick exit is not a crash
            updater.confirm_healthy(name)
            return 0
        if verdict.get("action") == "rolled_back":  # the previous version also failed: stop looping
            break
    return code


def installed_entry(root: Path, name: str) -> Path | None:
    """For the stub: resolve the entry file without importing the whole updater."""
    import json
    try:
        st = json.loads((Path(root) / "state.json").read_text(encoding="utf-8"))["components"][name]
        entry = st["records"][st["current"]].get("entry")
        return Path(root) / "versions" / name / st["current"] / entry if entry else None
    except (OSError, KeyError, ValueError):
        return None
