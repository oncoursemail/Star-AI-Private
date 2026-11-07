"""The owner's switches for Litha. Each one writes only her own control file and appends a line to
~/.star/litha-face/controls.jsonl. None of them merges, pushes or posts anything: they only change what her next
scheduled run is allowed to do.

    pause     ~/.star/pr-merger/PAUSED          her loop (pr_merger_run.cmd) and pr_merger skip their work while it exists
    apply     ~/.star/litha-autonomy/APPLY      autonomy acts on its queue instead of a dry run
    day_cap   ~/.star/litha-claude/cap.json     {"day": X}: her Claude spend per day (total cap kept as it is)"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time

from litha.face.data import ROOT, caps

MAX_DAY_CAP = 100.0                    # a typo like 3000 must not lift her paid budget; the owner edits cap.json above it


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def log(root: Path, control: str, value, ok: bool, note: str = "") -> None:
    p = root / "litha-face" / "controls.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "control": control, "value": value, "ok": ok, "note": note}) + "\n")


def set_paused(on: bool, root: Path = ROOT, why: str = "") -> dict:
    p = root / "pr-merger" / "PAUSED"
    if on:
        _write(p, json.dumps({"at": int(time.time()), "by": "owner (face)", "why": why[:200]}))
    elif p.exists():
        p.unlink()
    log(root, "pause", on, True, why[:200])
    return {"paused": p.exists()}


def set_apply(on: bool, root: Path = ROOT) -> dict:
    p = root / "litha-autonomy" / "APPLY"
    if on:
        _write(p, f"set by the owner from her face at {time.strftime('%Y-%m-%d %H:%M')}\n")
    elif p.exists():
        p.unlink()
    log(root, "apply", on, True)
    return {"apply": p.exists()}


def set_day_cap(usd, root: Path = ROOT) -> dict:
    try:
        v = float(usd)
    except (TypeError, ValueError):
        v = float("nan")
    if not math.isfinite(v) or v < 0 or v > MAX_DAY_CAP:
        log(root, "day_cap", str(usd)[:20], False, f"refused: needs 0..{MAX_DAY_CAP:g}")
        raise ValueError(f"day cap must be a number from 0 to {MAX_DAY_CAP:g}")
    p = root / "litha-claude" / "cap.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8"))
        cur = cur if isinstance(cur, dict) else {}
    except (OSError, ValueError):
        cur = {}
    cur["day"] = round(v, 2)
    _write(p, json.dumps(cur, indent=1))
    log(root, "day_cap", cur["day"], True)
    return {"caps": caps(root)}


def apply(control: str, value, root: Path = ROOT) -> dict:
    """One control by name (the server's single entry point). Unknown names are refused."""
    if control in ("pause", "apply") and not isinstance(value, bool):
        raise ValueError(f"{control} needs true or false")
    if control == "pause":
        return set_paused(value, root)
    if control == "apply":
        return set_apply(value, root)
    if control == "day_cap":
        return set_day_cap(value, root)
    raise ValueError(f"unknown control {control!r}")
