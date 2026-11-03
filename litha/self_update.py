"""Litha's live checkout follows star/next by itself, only to a green head, and steps back when she cannot start.

    python -m litha.self_update            step 1 of pr_merger_run.cmd
    python -m litha.self_update --last     the script's last line (`... & exit /b`): an update that changes
                                           pr_merger_run.cmd itself is applied only there
    python -m litha.self_update --dry      say what it would do, change nothing

A fast-forward to origin/star/next happens only when ALL hold: the checkout is on star/next (or detached at an
ancestor of it), the new head descends from HEAD, the tree has no uncommitted changes, ~/.star/pr-merger/OFF is
absent, the nightly bug bench is not running (it runs from this same checkout), the new head did not fail this check
before, and every check on the new head passed (pr_merger.check_gates). Afterwards every litha/*.py must
byte-compile and every module pr_merger_run.cmd runs must import in a fresh Python, and the new code must still hold
every gate canary outside litha.canaries.KNOWN_ESCAPES (section 8: known-bad PRs and merges replayed through her
decision code, offline); otherwise `git reset --keep` returns to the old head, the head is remembered as bad and the
reason is logged.

cmd.exe reads a running .cmd by byte offset: a file that changes under it makes the rest of the run execute
fragments of the new lines. So step 1 never applies an update that changes pr_merger_run.cmd; it leaves a note and
the last line, which cmd.exe has already read whole together with its `& exit /b`, applies it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from litha import pr_merger

ROOT = Path(__file__).resolve().parents[1]                  # the checkout this runs from (the live one when scheduled)
BRANCH = "star/next"
RUN_CMD = "litha/pr_merger_run.cmd"
HOME = Path.home() / ".star" / "pr-merger"
PENDING = "update-pending.json"                             # {"sha": head}: step 1 left a run-script change for --last
BAD = "update-bad.json"                                     # {head: why}: heads that failed the self-check
BENCH_TASK = "Litha bug bench"


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def bench_running() -> str:
    """Why the bug bench counts as running ('' = it is not): its scheduled task, or any process running it."""
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", BENCH_TASK, "/fo", "csv", "/nh"], capture_output=True,
                           text=True, errors="replace", timeout=30)
        if '"Running"' in r.stdout:
            return f'task "{BENCH_TASK}" is running'
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-CimInstance Win32_Process).CommandLine"], capture_output=True, text=True,
                           errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"cannot tell whether the bench runs: {e}"
    if r.returncode:
        return "cannot tell whether the bench runs: the process list failed"
    return "a litha.bug_bench process is running" if "litha.bug_bench" in r.stdout else ""


def modules(root: Path) -> list[str]:
    """The modules the scheduled run starts (`-m litha.x` in pr_merger_run.cmd), in order, once each."""
    text = (root / RUN_CMD).read_text(encoding="utf-8", errors="replace")
    return list(dict.fromkeys(re.findall(r"-m (litha\.\w+)", text)))


CHECK = ("import importlib, pathlib, sys\n"
         "for p in sorted(pathlib.Path('litha').glob('*.py')):\n"
         "    compile(p.read_text(encoding='utf-8'), str(p), 'exec')\n"
         "for m in sys.argv[1:]:\n"
         "    importlib.import_module(m)\n")


def healthy(root: Path, python: str) -> str:
    """'' when every litha/*.py compiles and every scheduled module imports in a fresh process; else why not."""
    try:
        r = subprocess.run([python, "-c", CHECK, *modules(root)], cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"self-check did not run: {e}"
    if r.returncode:
        lines = (r.stderr or r.stdout).strip().splitlines()
        return "self-check failed: " + " | ".join(lines[-3:])[:400]
    return ""


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def canary_gate(root: Path, python: str) -> str:
    """'' when the code in root still holds every gate canary it must (litha.canaries, run in a fresh Python there)."""
    from litha import canaries
    return canaries.gate(python, root)


def update(root: Path = ROOT, python: str = sys.executable, last: bool = False, dry: bool = False,
           home: Path = HOME, checks_fn=None, bench_fn=bench_running, health_fn=healthy, canary_fn=None) -> str:
    """One look; returns the line it logs ('' = nothing to say: --last without a pending run-script change)."""
    pending = home / PENDING
    if last and not pending.exists():
        return ""
    if (home / "OFF").exists():
        return "switched off (OFF), skipped"
    branch = git(root, "symbolic-ref", "-q", "--short", "HEAD", check=False).stdout.strip()
    if branch not in (BRANCH, ""):                          # until PR #917 merges the live checkout is on its branch
        pending.unlink(missing_ok=True)
        return f"not on {BRANCH}, skipped (on {branch})"
    git(root, "fetch", "-q", "origin", BRANCH)
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    new = git(root, "rev-parse", f"origin/{BRANCH}").stdout.strip()
    descends = git(root, "merge-base", "--is-ancestor", old, new, check=False).returncode == 0
    if branch == "" and not descends:
        pending.unlink(missing_ok=True)
        return f"not on {BRANCH}, skipped (detached at {old[:9]}, not an ancestor of origin/{BRANCH})"
    if new == old:
        pending.unlink(missing_ok=True)
        return f"up to date at {new[:9]}"
    short = f"{old[:9]}..{new[:9]}"
    if not descends:
        return f"origin/{BRANCH} {new[:9]} does not descend from HEAD {old[:9]}, skipped"
    if git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return f"{short}: the tree has uncommitted changes, skipped"
    bad = _read(home / BAD)
    if new in bad:
        return f"{short}: {new[:9]} failed its self-check before ({bad[new][:120]}), skipped"
    busy = bench_fn()
    if busy:
        return f"{short}: {busy}, skipped"
    gates = pr_merger.check_gates((checks_fn or pr_merger.head_checks)(new))
    if gates:
        return f"{short}: not every check passed on {new[:9]} ({'; '.join(gates[:3])}), skipped"
    changed = git(root, "diff", "--name-only", old, new).stdout.split()
    if RUN_CMD in changed and not last:
        if not dry:
            _write(pending, {"sha": new, "ts": round(time.time())})
        return f"{short}: changes {RUN_CMD}, left for the script's last line"
    if dry:
        return f"{short}: would fast-forward ({len(changed)} files)"
    git(root, "merge", "-q", "--ff-only", new)
    pending.unlink(missing_ok=True)
    why = health_fn(root, python) or (canary_fn(root, python) if canary_fn else "")
    if why:
        back = git(root, "reset", "-q", "--keep", old, check=False)
        bad[new] = why
        _write(home / BAD, dict(list(bad.items())[-50:]))
        return (f"{short}: {why}; rolled back to {old[:9]}" if back.returncode == 0 else
                f"{short}: {why}; ROLLBACK FAILED: {(back.stderr or back.stdout).strip()[:200]}")
    return f"{short}: updated ({len(changed)} files, every check passed, self-check passed)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.self_update")
    ap.add_argument("--last", action="store_true", help="the run script's last line: may change the script itself")
    ap.add_argument("--dry", action="store_true", help="say what it would do, change nothing")
    ap.add_argument("--python", default=sys.executable, help="the Python the scheduled run uses")
    a = ap.parse_args(argv)
    try:
        line = update(python=a.python, last=a.last, dry=a.dry, canary_fn=canary_gate)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        line = f"error: {str(e)[:300]}"
    if line:
        print(f"self_update: {line}", flush=True)
    return 0                                                # the scheduled run goes on whatever happens here


if __name__ == "__main__":
    sys.exit(main())
