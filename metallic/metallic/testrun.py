"""Run test files in parallel batches and report one result per file.

Workers pull from one queue ordered for an early useful signal: by import distance to the change (changed test
files, then their direct importers, ...), and within a distance the fastest files first (durations recorded on earlier
runs). A worker's first batch is a single file (first verdict in seconds); later batches
grow to about `batch_seconds` of estimated work to amortise interpreter start-up. Each batch is one pytest process
writing a JUnit XML report (xunit1, which carries the file of every test case), parsed per file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

DEFAULT_SECONDS = 2.0


@dataclass
class FileResult:
    path: str
    status: str                 # pass | fail | error
    tests: int = 0
    failed: int = 0
    seconds: float = 0.0
    output: str = ""
    cached: bool = False
    failures: list[str] = field(default_factory=list)
    order_dependent: bool = False   # failed next to other files, passed when re-run alone: a test-isolation bug


def _expand(cmd: list[str], python: str, tmp: str) -> list[str]:
    return [c.replace("{python}", python).replace("{tmp}", tmp) for c in cmd]


def parse_junit(xml_path: Path, root: Path) -> dict[str, dict]:
    per: dict[str, dict] = {}
    try:
        tree = ET.parse(xml_path)
    except (OSError, ET.ParseError):
        return per
    for case in tree.iter("testcase"):
        f = (case.get("file") or "").replace("\\", "/")
        if not f:
            cls = case.get("classname") or ""
            f = cls.replace(".", "/") + ".py" if cls else ""
        rec = per.setdefault(f, {"tests": 0, "failed": 0, "seconds": 0.0, "failures": []})
        rec["tests"] += 1
        rec["seconds"] += float(case.get("time") or 0)
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is not None:
            rec["failed"] += 1
            rec["failures"].append((case.get("name") or "?") + ": " + (bad.get("message") or "")[:200])
    return per


class Durations:
    """Seconds per test file from earlier runs (per clone, in the state dir)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self._lock = threading.Lock()

    def get(self, f: str) -> float:
        return float(self.data.get(f, DEFAULT_SECONDS))

    def set(self, f: str, s: float) -> None:
        with self._lock:
            self.data[f] = round(s, 3)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


def run_files(root: Path, files: list[str], cmd: list[str], python: str, env: dict[str, str], *, jobs: int,
              durations: Durations, priority: dict[str, int] | None = None, batch_seconds: float = 25.0,
              timeout: int = 1800, on_result=None, fail_fast: bool = False) -> list[FileResult]:
    """fail_fast: no new batch starts after a file fails (the merge queue only needs to know the tree is red)."""
    priority = priority or {}
    order = sorted(files, key=lambda f: (priority.get(f, 99), durations.get(f), f))
    lock = threading.Lock()
    results: list[FileResult] = []
    todo = list(order)

    stop = threading.Event()

    def take(n_done: int) -> list[str]:
        with lock:
            if not todo or stop.is_set():
                return []
            if n_done == 0:
                return [todo.pop(0)]
            batch, est = [], 0.0
            tier = priority.get(todo[0], 99)
            while todo and (not batch or est + durations.get(todo[0]) <= batch_seconds) and len(batch) < 40                     and priority.get(todo[0], 99) == tier:
                f = todo.pop(0)
                batch.append(f)
                est += durations.get(f)
            return batch

    def worker():
        done = 0
        while True:
            batch = take(done)
            if not batch:
                return
            done += 1
            got = _run_batch(root, batch, cmd, python, env, timeout)
            if len(batch) > 1:
                for i, r in enumerate(got):
                    if r.status != "pass":
                        alone = _run_batch(root, [r.path], cmd, python, env, timeout)[0]
                        if alone.status == "pass":
                            alone.order_dependent, alone.failures, alone.output = True, r.failures, r.output
                            got[i] = alone
            for r in got:
                if fail_fast and r.status != "pass":
                    stop.set()
                durations.set(r.path, r.seconds)
                with lock:
                    results.append(r)
                if on_result:
                    on_result(r)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(jobs, len(order))))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _run_batch(root: Path, batch: list[str], cmd: list[str], python: str, env: dict[str, str],
               timeout: int) -> list[FileResult]:
    with tempfile.TemporaryDirectory(prefix="metallic-run-") as tmp:
        xml = Path(tmp) / "junit.xml"
        full = _expand(cmd, python, tmp) + ["-o", "junit_family=xunit1", "--junitxml", str(xml)] + batch
        run_env = dict(os.environ, **{k: v.replace("{tmp}", tmp) for k, v in env.items()})
        started = time.monotonic()
        try:
            proc = subprocess.run(full, cwd=str(root), env=run_env, capture_output=True, timeout=timeout)
            code, out = proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")
        except subprocess.TimeoutExpired as e:
            code, out = -1, "timeout after %ss\n" % timeout + ((e.stdout or b"") + (e.stderr or b"")).decode(
                "utf-8", "replace")
        wall = time.monotonic() - started
        per = parse_junit(xml, root)
    tail = "\n".join(out.splitlines()[-60:])
    results = []
    for f in batch:
        rec = per.get(f)
        if rec is None:
            # No test cases recorded for this file: fine when pytest says "no tests" (5) or all passed (0),
            # otherwise the file did not run (collection error, crash, timeout).
            status = "pass" if code in (0, 5) else "error"
            results.append(FileResult(f, status, seconds=wall / len(batch), output="" if status == "pass" else tail))
            continue
        status = "fail" if rec["failed"] else "pass"
        results.append(FileResult(f, status, tests=rec["tests"], failed=rec["failed"],
                                  seconds=rec["seconds"] or wall / len(batch),
                                  output=tail if status != "pass" else "", failures=rec["failures"][:20]))
    if code not in (0, 1, 5) and all(r.status == "pass" for r in results):
        for r in results:          # pytest itself failed (usage error, internal error, killed): nothing is proven
            r.status, r.output = "error", tail
    return results
