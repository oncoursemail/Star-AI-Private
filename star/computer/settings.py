"""Her computer-use settings: <home>/computer.json (plain JSON, the owner can edit it). Unknown keys are ignored.

grounder.kind    "none" (UI Automation only) or "vlm" (an OpenAI-compatible vision endpoint, see grounding.py)
grounder.model   name sent to the endpoint; grounder.choice names a row of grounding.MODELS (documentation + installer)
grounder.format  pixels | resized | unit1000 | unit1 | auto (auto = measured once by `python -m star.computer calibrate`)
settle_s         how long to wait after an action before looking again
capture_hz       desired desktop sampling rate (0 < rate <= 60); not model reasoning speed
frame_max_age_s   discard captured frames older than this (0 < age <= 10 seconds)
speed_px_s       how fast she drags the mouse when drawing
remote_vision    true = when her GPU grounder misses, ask STAR's image model on the brain (star.vision.ask)
apps             extra app names for skills.open_app, e.g. {"minecraft": "<path to MinecraftLauncher.exe>"}
limits           limits.DEFAULTS overrides (actions_per_minute, messages_per_hour, recipients_per_day, ...)
stop_api         the owner's stop API (stopswitch.py): enabled, host, port
log_keep_days    days of computer-log screenshots kept; log_screenshots false = text log only
"""
from __future__ import annotations

import json
import math
import os
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


def make_grounder(settings: dict, *, for_calibration: bool = False):
    """Runtime honors kind=none; explicit calibration may inspect that configured candidate."""
    from .grounding import VlmGrounder
    g = settings.get("grounder", {})
    if ((g.get('kind') != 'vlm' and not (for_calibration and g.get('kind') == 'none'))
            or not g.get('url') or not g.get('model')):
        return None
    return VlmGrounder(str(g["url"]), str(g.get("model", "")), fmt=str(g.get("format", "auto")),
                       max_side=int(g.get("max_side", 1280)), timeout_s=float(g.get("timeout_s", 60)))


def calibration_snapshot(home: Path) -> bytes:
    path = Path(home) / NAME
    if path.is_symlink() or path.stat().st_nlink != 1:
        raise ValueError('calibration requires an ordinary existing computer.json')
    raw = path.read_bytes()
    if len(raw) > 262144 or not isinstance(json.loads(raw.decode('utf-8-sig')), dict):
        raise ValueError('computer.json must be a JSON object of at most 256 KiB')
    return raw


def save_calibration(home: Path, expected: bytes, report: dict, *, cancelled=None) -> None:
    """Merge a measured format under a file lock; reject any intervening owner edits.

    Windows byte locks plus the open file's deny-delete sharing prevent an editor
    from writing/replacing the document during this update. POSIX flock coordinates
    cooperating writers. A write failure restores the original bytes before unlock.
    """
    from .grounding import FORMATS
    if (report.get('format') not in FORMATS or report.get('points') != 6
            or report.get('kind') != 'synthetic-six-buttons'):
        raise ValueError('no accepted six-point calibration')
    for key, limit in (('mean_error_px', 12), ('max_error_px', 20)):
        value = report.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= limit:
            raise ValueError('calibration exceeded the accepted error bounds')
    document = json.loads(expected.decode('utf-8-sig'))
    grounder = document.get('grounder') if isinstance(document, dict) else None
    if (not isinstance(grounder, dict) or grounder.get('kind') not in ('vlm', 'none')
            or str(grounder.get('url', '')).rstrip('/') != report.get('url')
            or grounder.get('model') != report.get('model')
            or int(grounder.get('max_side', 1280)) != report.get('max_side')):
        raise ValueError('calibration does not match this grounder configuration')
    grounder['format'], grounder['calibration'] = report['format'], dict(report)
    payload = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(payload) > 262144:
        raise ValueError('calibration would exceed the computer.json size limit')
    path = Path(home) / NAME
    if calibration_snapshot(home) != expected:
        raise RuntimeError('computer.json changed during calibration; nothing was saved')

    def write_all(file, data):
        file.seek(0)
        remaining = memoryview(data)
        while remaining:
            count = file.write(remaining)
            if not count:
                raise OSError('configuration write was incomplete')
            remaining = remaining[count:]
        file.truncate(len(data))
        os.fsync(file.fileno())

    with path.open('r+b', buffering=0) as file:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 0x7fffffff)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        writing = False
        try:
            current = path.stat()
            held = os.fstat(file.fileno())
            if (current.st_ino, current.st_dev) != (held.st_ino, held.st_dev) or file.read() != expected:
                raise RuntimeError('computer.json changed during calibration; nothing was saved')
            if cancelled is not None and cancelled():
                raise RuntimeError('calibration cancelled; nothing was saved')
            writing = True
            write_all(file, payload)
            if cancelled is not None and cancelled():
                raise RuntimeError('calibration cancelled; nothing was saved')
        except BaseException:
            if writing:
                write_all(file, expected)
            raise
        finally:
            if os.name == 'nt':
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 0x7fffffff)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
