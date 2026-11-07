"""Where STAR lives on her PC: one install root, by default a folder on the second drive (e.g. D:\\STAR).

    <root>\\app        the STAR source (setup.cmd copies it)       <root>\\home       data: config, STOP, actions.jsonl,
    <root>\\venv       Python virtual environment                                    life, acceptance reports
    <root>\\models     voice / vision model files (models\\voice, models\\hf)  <root>\\workspace  her own projects
    <root>\\tools      downloaded helpers (Autologon)                        <root>\\logs       service logs

The root is, in this order: the STAR_ROOT environment variable; else, when the running Python is the install's venv
python (<root>\\venv\\Scripts\\python.exe with <root>\\app next to venv), that root (so a process started by the
scheduled task or a desktop button finds it even before the variable reaches it); else None (a development
checkout: callers keep their old defaults). Other packages (senses, vtuber, computer) call models_dir() / root() instead of choosing their own folder.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


def root() -> Path | None:
    configured = os.environ.get("STAR_ROOT", "").strip()
    if configured:
        return Path(configured)
    exe = Path(sys.executable)                       # <root>\venv\Scripts\python.exe when setup.cmd's venv runs us
    if exe.parent.name.lower() == "scripts" and exe.parent.parent.name.lower() == "venv":
        base = exe.parent.parent.parent
        if (base / "app").is_dir():
            return base
    return None


def _under(name: str) -> Path | None:
    base = root()
    return base / name if base else None


def home_dir() -> Path | None:
    return _under("home")


def workspace_dir() -> Path | None:
    return _under("workspace")


def models_dir() -> Path | None:
    return _under("models")


def tools_dir() -> Path | None:
    return _under("tools")


def logs_dir() -> Path | None:
    return _under("logs")


def acceptance_dir() -> Path | None:
    home = home_dir()
    return home / "acceptance" if home else None
