"""The computer-use action log with screenshots, for the owner: what she saw, what she did, what changed.

<home>\\computer-log\\<yyyymmdd>\\steps.jsonl   one line per driver step (redacted, cut like control.log_action)
<home>\\computer-log\\<yyyymmdd>\\<n>-before.jpg / <n>-after.jpg   the screen before and after (max 1280 px wide)
The folder is in the owner's home folder, which STAR's own actions cannot write (host.py). Days older than
`keep_days` are deleted when a new log opens. Typed text is logged only as its first 30 characters (control._short
redacts keys and addresses).
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from typing import Callable

from ..home.control import _short

FOLDER = "computer-log"


class ActionLog:
    def __init__(self, home: Path, *, keep_days: int = 7, max_side: int = 1280, screenshots: bool = True,
                 clock: Callable[[], float] = time.time) -> None:
        self.root = Path(home) / FOLDER
        self.keep_days, self.max_side, self.screenshots, self.clock = keep_days, max_side, screenshots, clock
        self.n = 0
        self._prune()

    def _day(self) -> Path:
        day = self.root / time.strftime("%Y%m%d", time.gmtime(self.clock()))
        day.mkdir(parents=True, exist_ok=True)
        return day

    def _prune(self) -> None:
        if not self.root.exists():
            return
        oldest = time.strftime("%Y%m%d", time.gmtime(self.clock() - self.keep_days * 86400))
        for child in self.root.iterdir():
            if child.is_dir() and child.name.isdigit() and child.name < oldest:
                shutil.rmtree(child, ignore_errors=True)

    def shot(self, image, label: str) -> str:
        """Save a screenshot; returns its file name ('' when off or no image)."""
        if image is None or not self.screenshots:
            return ""
        small = image.convert("RGB")
        if small.width > self.max_side:
            small = small.resize((self.max_side, round(small.height * self.max_side / small.width)))
        name = f"{self.n + 1:05d}-{label}.jpg"            # belongs to the next step row
        small.save(self._day() / name, "JPEG", quality=70)
        return name

    def step(self, **fields) -> dict:
        self.n += 1
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock())), "n": self.n}
        row.update({k: _short(v) for k, v in fields.items()})
        with (self._day() / "steps.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def rows(self) -> list[dict]:
        out = []
        for day in sorted(self.root.glob("*/steps.jsonl")):
            out += [json.loads(line) for line in day.read_text(encoding="utf-8").splitlines() if line.strip()]
        return out
