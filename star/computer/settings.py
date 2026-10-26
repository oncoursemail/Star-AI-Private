"""Her computer-use settings: <home>/computer.json (plain JSON, the owner can edit it). Unknown keys are ignored.

grounder.kind    "none" (UI Automation only) or "vlm" (an OpenAI-compatible vision endpoint, see grounding.py)
grounder.model   name sent to the endpoint; grounder.choice names a row of grounding.MODELS (documentation + installer)
grounder.format  pixels | resized | unit1000 | unit1 | auto (auto = measured once by `python -m star.computer calibrate`)
settle_s         how long to wait after an action before looking again
capture_hz       desired desktop sampling rate (0 < rate <= 60); not model reasoning speed
frame_max_age_s   discard captured frames older than this (0 < age <= 10 seconds)
speed_px_s       how fast she drags the mouse when drawing
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
    "capture_hz": 30,
    "frame_max_age_s": 0.5,
    "speed_px_s": 380,
    "max_elements": 400,
    "prompt_elements": 60,
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
