"""Her computer-use settings: <home>/computer.json (plain JSON, the owner can edit it). Unknown keys are ignored.

grounder.kind    "none" (UI Automation only) or "vlm" (an OpenAI-compatible vision endpoint, see grounding.py)
grounder.model   name sent to the endpoint; grounder.choice names a row of grounding.MODELS (documentation + installer)
grounder.format  pixels | resized | unit1000 | unit1 | auto (auto = measured once by `python -m star.computer calibrate`)
settle_s         how long to wait after an action before looking again
speed_px_s       how fast she drags the mouse when drawing
remote_vision    true = when her GPU grounder misses, ask STAR's image model on the brain (star.vision.ask)
apps             extra app names for skills.open_app, e.g. {"minecraft": "<path to MinecraftLauncher.exe>"}
limits           limits.DEFAULTS overrides (actions_per_minute, messages_per_hour, recipients_per_day, ...)
stop_api         the owner's stop API (stopswitch.py): enabled, host, port
log_keep_days    days of computer-log screenshots kept; log_screenshots false = text log only
"""
from __future__ import annotations

import json
from pathlib import Path

from ..home import control

NAME = "computer.json"
DEFAULTS = {
    "grounder": {"kind": "none", "url": "", "model": "ui-tars-1.5-7b", "choice": "ui-tars-1.5-7b", "format": "auto",
                 "max_side": 1280, "timeout_s": 60},
    "settle_s": 0.5,
    "speed_px_s": 380,
    "max_elements": 400,
    "prompt_elements": 60,
    "remote_vision": False,
    "apps": {},
    "limits": {},
    "stop_api": {"enabled": True, "host": "127.0.0.1", "port": 8767},
    "log_keep_days": 7,
    "log_screenshots": True,
}


def load(home: Path | None = None) -> dict:
    path = (home or control.home_dir()) / NAME
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    try:
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return out
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key == "grounder" and isinstance(value, dict):
                out["grounder"].update({k: v for k, v in value.items() if k in DEFAULTS["grounder"]})
            elif key in DEFAULTS and key != "grounder" and isinstance(DEFAULTS[key], dict) and isinstance(value, dict):
                out[key].update(value)
            elif key in DEFAULTS and isinstance(DEFAULTS[key], bool):
                if isinstance(value, bool):
                    out[key] = value
            elif key in DEFAULTS and key != "grounder" and type(value) in (int, float) and not isinstance(value, bool):
                out[key] = value
    return out


def make_grounder(settings: dict):
    """The configured Grounder, or None when only UI Automation is wanted."""
    from .grounding import VlmGrounder
    g = settings.get("grounder", {})
    if g.get("kind") != "vlm" or not g.get("url"):
        return None
    return VlmGrounder(str(g["url"]), str(g.get("model", "")), fmt=str(g.get("format", "auto")),
                       max_side=int(g.get("max_side", 1280)), timeout_s=float(g.get("timeout_s", 60)))
