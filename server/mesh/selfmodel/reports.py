"""What STAR's own jobs report about themselves, kept as small JSON-lines files in the service's state folder.

Kinds (POST /mesh/self/report {"kind": ..., ...}):
  eval       {"suite", "score", "max"?, "model"?, "node"?}            eval scores over time
  training   {"state", "run"?, "base"?, "result"?, "promoted"?}       nightly self-training
  autotune   {"node", "decision": keep|reject|rollback, "candidate", "baseline", "tok_s", "quality", ...}
  upgrade    {"component", "current", "latest", "decision": none|trial|promote|reject|rollback, "why"}
  code       {"head", "branch", "prs": [...], "ci": {...}, "deployed": {...}}   from code.py on the owner PC
  error      {"where", "error"}                                       a job's own failure
Each file keeps its last KEEP lines. A report never carries secrets (the service refuses key-shaped values).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

KINDS = ("eval", "training", "autotune", "upgrade", "code", "error")
KEEP = 400
MAX_BYTES = 64_000
SECRETISH = re.compile(r"(?i)(bearer\s+\S{12,}|sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY)")


class Reports:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.lock = threading.Lock()

    def _file(self, kind: str) -> Path:
        return self.folder / f"report-{kind}.jsonl"

    def add(self, report: dict) -> tuple[bool, str]:
        kind = report.get("kind")
        if kind not in KINDS:
            return False, f"kind must be one of {', '.join(KINDS)}"
        line = json.dumps({**report, "ts": report.get("ts") or round(time.time(), 1)}, ensure_ascii=False,
                          sort_keys=True)
        if len(line) > MAX_BYTES:
            return False, "report too large"
        if SECRETISH.search(line):
            return False, "report looks like it contains a key or token"
        with self.lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self._file(kind)
            lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
            lines = (lines + [line])[-KEEP:]
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(path)
        return True, "ok"

    def last(self, kind: str, n: int = 10) -> list[dict]:
        path = self._file(kind)
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def summary(self) -> dict:
        """The part of the reports that goes into the snapshot."""
        evals = self.last("eval", 200)
        series: dict[str, list] = {}
        for e in evals:
            series.setdefault(str(e.get("suite") or "?"), []).append(
                {"ts": e.get("ts"), "score": e.get("score"), "max": e.get("max"), "model": e.get("model")})
        return {
            "evals": {k: v[-12:] for k, v in series.items()},
            "training": (self.last("training", 1) or [None])[0],
            "autotune": self.last("autotune", 12),
            "upgrade": self.last("upgrade", 12),
            "code": (self.last("code", 1) or [None])[0],
            "job_errors": self.last("error", 5),
            "flaws": next((e for e in reversed(evals) if e.get("suite") == "flaws"), None),
        }


class History:
    """Compact points of the live state every `every_s` (speeds and states over time)."""

    def __init__(self, folder: str | Path, every_s: float = 300.0, keep: int = 2016):
        self.path = Path(folder) / "history.jsonl"
        self.every_s, self.keep, self.last_at = every_s, keep, 0.0

    def maybe_add(self, snap: dict) -> bool:
        if snap.get("ts", 0) - self.last_at < self.every_s:
            return False
        self.last_at = snap.get("ts", time.time())
        point = {"ts": round(self.last_at),
                 "nodes": {n["name"]: [n.get("state"), n.get("tok_s"), n.get("vram_free_mb")] for n in snap.get("nodes") or []},
                 "brain": [m["id"] for m in (snap.get("brain") or {}).get("models") or [] if m.get("loaded")],
                 "busy": sum(int(m.get("processing") or 0) for m in (snap.get("brain") or {}).get("models") or []),
                 "fw_ms": ((snap.get("router") or {}).get("recent") or {}).get("median_first_word_ms")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []
        lines = (lines + [json.dumps(point, separators=(",", ":"))])[-self.keep:]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    def points(self, n: int = 288) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines()[-n:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out
