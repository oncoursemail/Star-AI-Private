"""Step checkpoints for long background tasks (conductor cycles, agent runs, Studio job batches).

A task that is stopped between steps (a yield to the owner's chat, a restart, a crash) starts again with the steps it
already finished taken from the checkpoint file instead of being done (and paid for in model time) a second time.
One JSON file per task: {"scope": ..., "steps": {key: result}}. A different scope (a new night, a new run id) starts
clean. Results must be JSON. Writes are atomic (temp file + replace), so a stop mid-write leaves the previous file.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any


def step_key(*parts: str) -> str:
    """A short stable key for a step from what defines it (its kind and its prompt, for example)."""
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


class StepCheckpoint:
    def __init__(self, path: str | os.PathLike, *, scope: str):
        self.path, self.scope = Path(path), scope
        self._steps: dict[str, Any] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("scope") == scope and isinstance(data.get("steps"), dict):
                self._steps = data["steps"]
        except (OSError, ValueError):
            pass

    def __len__(self) -> int:
        return len(self._steps)

    def get(self, key: str) -> Any:
        return self._steps.get(key)

    def put(self, key: str, result: Any) -> None:
        self._steps[key] = result
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"scope": self.scope, "steps": self._steps}, handle, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def clear(self) -> None:
        """The task finished: forget its steps."""
        self._steps = {}
        try:
            self.path.unlink()
        except OSError:
            pass
