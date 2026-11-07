"""Litha's health check: did every scheduled piece run, is anything stuck, and repair what is safely mechanical.

Checks (all from files under ~/.star, no network, no model; < 2 s when healthy):
- the 10-minute run (`pr-merger/run.log`): last start/end, a run that started and never ended, rc != 0, a Python
  traceback in the last finished run, and each step's own line in it (merger, promote, other repos);
- each log is fresh: decisions.jsonl (merger, every run), bench.jsonl (nightly bench), OFF switches;
- stuck states: a PR logged the same way again and again (retried forever), tried.json growing without bound,
  worktrees she left behind, leftover `*.tmp` files of an atomic write, logs that need rotating.
Repairs (only these, each logged in the report):
- a lock file of hers (`pr-fixer/*.lock`, `pr-merger/*.lock`, `litha/*.lock`) older than --stale-hours is removed;
- a JSON state file that no longer parses (tried.json, hunted.json, lessons.json) is restored from its last good
  copy (`<name>.good`, kept by this check whenever the file parses) or from a leftover atomic-write `.tmp` that
  parses; the broken file is kept as `<name>.corrupt-<time>`. Everything else is reported, never changed.
It also refreshes ~/.star/litha/next_steps.json (litha.self_plan) when fixes.jsonl changed, at most every 30 min.

    python -m litha.self_check [--quiet] [--no-repair] [--stale-hours 3] [--home DIR]
Report: ~/.star/litha/health.json. Exit code 0 (the scheduled run must go on) unless --strict and a problem is left.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

HOME = Path.home() / ".star"
WORK = Path(__file__).resolve().parents[2]   # worktrees/ next to the checkout this runs from (= pr_fixer.WORK)
RUN_EVERY = 10 * 60                      # the "Litha PR merger" task
LATE = 3 * RUN_EVERY                     # no finished run for 3 periods: the task is not running
HUNG = 60 * 60                           # a run that started this long ago and never ended
BENCH_LATE = 26 * 3600                   # nightly bench (03:10)
SAME_AGAIN = 4                           # the same PR logged the same way this often in 48 h: stuck ...
STILL = 6 * 3600                         # ... when the last of them is this recent (older: the loop stopped)
TRIED_KEYS, TRIED_BYTES = 300, 64_000    # tried.json bigger than this: it only grows, nobody prunes it
LOG_BYTES = 50_000_000                   # a log over 50 MB needs rotating (reads of it get slow)
PLAN_EVERY = 30 * 60
STATE_FILES = ("pr-fixer/tried.json", "pr-fixer/hunted.json", "litha/lessons.json")
LOCK_DIRS = ("pr-fixer", "pr-merger", "litha")
TAIL = 200_000                           # bytes of run.log read (a run writes ~6 KB)

STAMP = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})")       # %date% %time% (en-US)
STEP_LINES = {"pr_merger": re.compile(r"^(merged \d+|dry run)", re.M),
              "pr_promote": re.compile(r"^main: (HOLD|READY|MERGED)", re.M),
              "others": re.compile(r"^[\w.-]+/[\w.-]+: (merged \d+|review only)", re.M)}
TRACE_FILE = re.compile(r'File "[^"]*[\\/]litha[\\/](\w+)\.py", line (\d+)')


def _when(line: str) -> float | None:
    m = STAMP.search(line)
    if not m:
        return None
    mo, d, y, h, mi, s = map(int, m.groups())
    try:
        return dt.datetime(y, mo, d, h, mi, s).timestamp()
    except ValueError:
        return None


def _age(sec: float) -> str:
    return f"{sec / 3600:.1f} h" if sec >= 5400 else f"{sec / 60:.0f} min"


def _tail(path: Path, n: int = TAIL) -> str:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - n))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.selfcheck.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Report:
    def __init__(self):
        self.problems: list[str] = []
        self.repaired: list[str] = []
        self.info: list[str] = []


def check_runs(home: Path, now: float, rep: Report) -> None:
    """The scheduled 10-minute run, from its own log lines (`<date> <time> start` / `... end rc=N`)."""
    log = home / "pr-merger" / "run.log"
    if not log.exists():
        rep.problems.append("pr-merger/run.log is missing: the scheduled run never wrote a line")
        return
    text = _tail(log)
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.rstrip().endswith(" start")]
    ends = [i for i, ln in enumerate(lines) if re.search(r" end rc=-?\d+\s*$", ln)]
    mtime = log.stat().st_mtime
    if not ends:
        rep.problems.append("run.log has no finished run in its last 200 KB")
        return
    last_end = ends[-1]
    t_end = _when(lines[last_end]) or mtime
    if now - t_end > LATE:
        rep.problems.append(f'the 10-minute run last finished {_age(now - t_end)} ago (task "Litha PR merger" '
                            "not running, or switched off)")
    m = re.search(r"rc=(-?\d+)", lines[last_end])
    rc = int(m.group(1)) if m else 0
    if rc != 0:
        rep.problems.append(f"the last run ended with rc={rc}")
    if starts and starts[-1] > last_end:
        t_start = _when(lines[starts[-1]]) or mtime
        if now - t_start > HUNG:
            rep.problems.append(f"a run started {_age(now - t_start)} ago and never ended (hung or killed)")
        else:
            rep.info.append(f"a run is in progress (started {_age(now - t_start)} ago)")
    begin = max([i for i in starts if i < last_end], default=-1)
    seg = "\n".join(lines[begin + 1:last_end])
    traces = sorted({m.group(1) for m in TRACE_FILE.finditer(seg)}) if "Traceback (most recent call last)" in seg else []
    if traces or "Traceback (most recent call last)" in seg:
        rep.problems.append("the last run had a Python traceback in " + (", ".join(traces) or "an unknown module"))
    missing = [name for name, pat in STEP_LINES.items() if not pat.search(seg)]
    if missing and begin >= 0:
        rep.problems.append("the last run printed no result line for " + ", ".join(missing))
    rep.info.append(f"last run finished {_age(now - t_end)} ago, rc={rc}")


def check_fresh(home: Path, now: float, rep: Report) -> None:
    for off in ("pr-merger/OFF", "litha/OFF"):
        if (home / off).exists():
            rep.info.append(f"off switch present: ~/.star/{off}")
    merger_off = (home / "pr-merger" / "OFF").exists()
    pairs = [("pr-merger/decisions.jsonl", LATE, "the merger", merger_off),
             ("litha/bench.jsonl", BENCH_LATE, "the nightly bug bench", (home / "litha" / "OFF").exists())]
    for rel, late, who, off in pairs:
        f = home / rel
        if off:
            continue
        if not f.exists():
            rep.problems.append(f"{who} never wrote ~/.star/{rel}")
        elif now - f.stat().st_mtime > late:
            rep.problems.append(f"{who} last wrote ~/.star/{rel} {_age(now - f.stat().st_mtime)} ago")
    for rel in ("pr-merger/run.log", "pr-merger/decisions.jsonl", "pr-fixer/fixes.jsonl", "litha/bench.log"):
        f = home / rel
        if f.exists() and f.stat().st_size > LOG_BYTES:
            rep.problems.append(f"~/.star/{rel} is {f.stat().st_size // 1_000_000} MB: rotate it")


def check_locks(home: Path, now: float, rep: Report, repair: bool, stale_hours: float) -> None:
    for d in LOCK_DIRS:
        for f in sorted((home / d).glob("*.lock")):
            try:
                age = now - f.stat().st_mtime
            except OSError:
                continue
            if age < stale_hours * 3600:
                if age > LATE:
                    rep.info.append(f"lock ~/.star/{d}/{f.name} held {_age(age)}")
                continue
            if repair:
                try:
                    f.unlink()
                    rep.repaired.append(f"removed stale lock ~/.star/{d}/{f.name} ({_age(age)} old)")
                    continue
                except OSError as e:
                    rep.problems.append(f"stale lock ~/.star/{d}/{f.name} ({_age(age)}) could not be removed: {e}")
                    continue
            rep.problems.append(f"stale lock ~/.star/{d}/{f.name} ({_age(age)} old)")


def _parses(data: bytes) -> bool:
    try:
        json.loads(data.decode("utf-8"))
        return True
    except (ValueError, UnicodeDecodeError):
        return False


def check_state(home: Path, now: float, rep: Report, repair: bool) -> None:
    """JSON state: keep a last good copy while it parses; restore it when the file no longer parses."""
    for rel in STATE_FILES:
        f = home / rel
        good = f.with_name(f.name + ".good")
        tmps = sorted(f.parent.glob(f"{f.name}.*.tmp"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if f.parent.exists() else []
        old_tmps = [t for t in tmps if now - t.stat().st_mtime > 3600]
        if old_tmps:
            rep.info.append(f"{len(old_tmps)} leftover atomic-write file(s) next to ~/.star/{rel}")
        if not f.exists():
            continue
        try:
            data = f.read_bytes()
        except OSError as e:
            rep.problems.append(f"~/.star/{rel} cannot be read: {e}")
            continue
        if _parses(data):
            try:
                if not good.exists() or good.read_bytes() != data:
                    _write_atomic(good, data)
            except OSError:
                pass
            continue
        source = good if good.exists() and _parses(good.read_bytes()) else \
            next((t for t in tmps if _parses(t.read_bytes())), None)
        if not repair or source is None:
            rep.problems.append(f"~/.star/{rel} does not parse" + ("" if source else " and no good copy exists"))
            continue
        with _state_lock(f):
            keep = f.with_name(f"{f.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}")
            shutil.copyfile(f, keep)
            _write_atomic(f, source.read_bytes())
        rep.repaired.append(f"~/.star/{rel} did not parse: restored from {source.name} (broken copy kept as {keep.name})")


class _state_lock:
    """The fixer's own lock protocol (pr_fixer.file_lock: O_EXCL file) for tried.json, so mark() never races us."""

    def __init__(self, f: Path):
        self.path = f.with_name("tried.lock") if f.name == "tried.json" else None

    def __enter__(self):
        end = time.time() + 10
        while self.path:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                if time.time() > end:
                    self.path = None                    # a holder that does not let go: same as the fixer (take over)
                    return self
                time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        if self.path:
            self.path.unlink(missing_ok=True)


def check_stuck(home: Path, now: float, rep: Report, work: Path | None, stale_hours: float) -> None:
    from litha import self_plan
    rows = self_plan.read_jsonl(home / "pr-fixer" / "fixes.jsonl", now - 48 * 3600)
    same: dict[tuple, list[float]] = {}
    for r in rows:
        key = (self_plan.pr_name(r), str(r.get("result")), self_plan.classify(r))
        same.setdefault(key, []).append(self_plan._ts(r))
    for (pr, result, bucket), ts in sorted(same.items(), key=lambda kv: -len(kv[1])):
        if len(ts) < SAME_AGAIN or result == "fixed":
            continue
        line = f"{pr} logged {result}/{bucket} {len(ts)} times in 48 h"
        if now - max(ts) < STILL:
            rep.problems.append(line + " (retried without progress)")
        else:
            rep.info.append(f"{line}, last {_age(now - max(ts))} ago (stopped)")
    tried = home / "pr-fixer" / "tried.json"
    try:
        size = tried.stat().st_size
        keys = len(json.loads(tried.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        size = keys = 0
    if keys > TRIED_KEYS or size > TRIED_BYTES:
        rep.problems.append(f"tried.json holds {keys} PRs ({size // 1000} KB) and is never pruned")
    elif keys:
        rep.info.append(f"tried.json: {keys} PRs")
    if work and work.is_dir():
        left = []
        for d in work.iterdir():
            if re.match(r"litha-(fix|merge|proof|base)-\d+$", d.name) and d.is_dir():
                try:
                    if now - d.stat().st_mtime > stale_hours * 3600:
                        left.append(d.name)
                except OSError:
                    continue
        if left:
            rep.problems.append(f"{len(left)} worktree(s) of hers left behind in {work}: " + ", ".join(sorted(left)[:6]))


def refresh_plan(home: Path, now: float, rep: Report) -> None:
    from litha import self_plan
    old = self_plan.load(home)
    if old.get("stamps", {}).get("fixes") == self_plan.stamp(home / "pr-fixer" / "fixes.jsonl") \
            or now - old.get("made", 0) < PLAN_EVERY:
        return
    try:
        self_plan.write(self_plan.plan(home, now=now), home)
        rep.info.append("next_steps.json refreshed")
    except Exception as e:  # noqa: BLE001 - a planner bug must not hide the health report
        rep.problems.append(f"self_plan failed: {str(e)[:160]}")


def check(home: Path | None = None, now: float | None = None, repair: bool = True, stale_hours: float = 3.0,
          work: Path | None = None, plan: bool = True) -> dict:
    home = home or HOME
    t0 = time.time()
    now = now or t0
    rep = Report()
    steps = [lambda: check_runs(home, now, rep), lambda: check_fresh(home, now, rep),
             lambda: check_locks(home, now, rep, repair, stale_hours), lambda: check_state(home, now, rep, repair),
             lambda: check_stuck(home, now, rep, work, stale_hours)]
    if plan:
        steps.append(lambda: refresh_plan(home, now, rep))
    for step in steps:
        try:
            step()
        except Exception as e:  # noqa: BLE001 - one broken check must not hide the others
            rep.problems.append(f"check error: {type(e).__name__}: {str(e)[:160]}")
    return {"at": round(now), "ok": not rep.problems, "problems": rep.problems, "repaired": rep.repaired,
            "info": rep.info, "seconds": round(time.time() - t0, 3)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.self_check")
    ap.add_argument("--home", type=Path, help="state root (default ~/.star)")
    ap.add_argument("--no-repair", action="store_true", help="report only")
    ap.add_argument("--stale-hours", type=float, default=3.0, help="a lock / worktree older than this is stale")
    ap.add_argument("--quiet", action="store_true", help="one line when healthy")
    ap.add_argument("--strict", action="store_true", help="exit 1 when a problem is left")
    a = ap.parse_args(argv)
    home = a.home or HOME
    r = check(home, repair=not a.no_repair, stale_hours=a.stale_hours, work=None if a.home else WORK)
    try:
        (home / "litha").mkdir(parents=True, exist_ok=True)
        _write_atomic(home / "litha" / "health.json", json.dumps(r, indent=1).encode())
    except OSError:
        pass
    head = (f"self_check {'ok' if r['ok'] else str(len(r['problems'])) + ' problem(s)'}"
            f"{', ' + str(len(r['repaired'])) + ' repaired' if r['repaired'] else ''} ({r['seconds']} s)")
    print(head, flush=True)
    for line in r["repaired"] + r["problems"] + ([] if a.quiet else r["info"]):
        print("  " + line, flush=True)
    return 1 if a.strict and r["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
