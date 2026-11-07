"""Content-addressed result cache.

A key is the SHA-256 of everything that can change a result: the task (check name, command, version), the toolchain
fingerprint and the content (blob hashes) of the task's inputs. The same key means the same work, so the stored
result is reused instead of re-running. Records are small JSON files under <root>/<2 hex>/<key>.json, written
atomically (temp file + rename) so parallel workers and machines sharing the directory never read half a record.

Only conclusive results are stored (pass/fail of a deterministic task); errors, timeouts and skips are not.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

SCHEMA = 1


def key(*parts) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([SCHEMA, *parts], sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


class Cache:
    def __init__(self, root: Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    def _path(self, k: str) -> Path:
        return self.root / k[:2] / (k + ".json")

    def get(self, k: str) -> dict | None:
        if not self.enabled:
            self.misses += 1
            return None
        try:
            rec = json.loads(self._path(k).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.misses += 1
            return None
        self.hits += 1
        return rec

    def peek(self, k: str) -> dict | None:
        """Read without counting (bookkeeping lookups such as the parse cache)."""
        try:
            return json.loads(self._path(k).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def put(self, k: str, record: dict) -> None:
        p = self._path(k)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(record, stored=time.time()), f)
        os.replace(tmp, p)


_TOOLCHAIN: dict[str, str] = {}


def toolchain(python: str) -> str:
    """Fingerprint of the interpreter the tests run under (version, implementation, platform, executable)."""
    if python not in _TOOLCHAIN:
        try:
            out = subprocess.run([python, "-c", "import sys,platform;print(sys.version);print(platform.platform());"
                                  "print(sys.executable)"], capture_output=True, text=True, timeout=60).stdout
        except OSError:
            out = "missing " + python
        _TOOLCHAIN[python] = hashlib.sha256((out + sys.platform + platform.machine()).encode()).hexdigest()[:16]
    return _TOOLCHAIN[python]
