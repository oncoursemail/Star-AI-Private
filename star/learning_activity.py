"""Is STAR learning on this PC right now? Read-only look at the PC night-school worker
(server/night_school/pc/turbo.py) for the desktop companions' study looks.

Active means the supervisor's STATUS.txt says "running" and night school's own log was written in the
last 15 minutes (STATUS.txt is written once when a session starts, so a crashed session would stay
"running" without the log check).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

FRESH_S = 15 * 60


def turbo_home() -> Path | None:
    base = os.environ.get('LOCALAPPDATA')
    return Path(base) / 'STAR-night-turbo' if base else None


def pc_learning_status(home: Path | None = None, now: float | None = None) -> dict:
    home = home if home is not None else turbo_home()
    if home is None:
        return {'active': False, 'state': 'unknown'}
    try:
        status = (home / 'STATUS.txt').read_text(encoding='utf-8', errors='replace').strip()
    except OSError:
        return {'active': False, 'state': 'not installed'}
    # "<date> <time> <state>: <reason>"
    parts = status.split(' ', 2)
    state = parts[2].split(':', 1)[0].strip() if len(parts) == 3 else 'unknown'
    try:
        fresh = (now if now is not None else time.time()) - (home / 'ns' / 'nightschool.log').stat().st_mtime < FRESH_S
    except OSError:
        fresh = False
    return {'active': state == 'running' and fresh, 'state': state}
