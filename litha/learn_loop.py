"""Litha's trusted bench and learning loop: the same items every time, a stored baseline, and lessons that must not
lower the score.

Two fixed item sets (in the repo, only repo / sha / paths / mutant positions, never secrets or local paths):
  litha/bench/standard_suite.json  32 AST mutants (litha.ast_mutants) at one pinned star/next sha, each killed by an
                                   existing test. Solved = the module's tests pass after her edits.
  litha/bench/real_fixes.json      real failures somebody fixed (litha.real_fixes mines them from git history and
                                   ~/.star/pr-fixer/fixes.jsonl): the broken code + the tests that failed on it.
Plus a local queue ~/.star/litha/real_items.jsonl that after_fix() fills after every real fix or failure.

Bench runs never teach her: lessons are frozen for the run (a snapshot), no SFT or training-bank rows are written
(both sets are eval data), and a real item never sees the lesson made from itself.

    python -m litha.bug_bench standard [--k 1] [--save-baseline]   the standard suite (32 items)
    python -m litha.bug_bench real     [--k 1]                      the real-fix items (blind: failing tests only)
    python -m litha.bug_bench report   [--last] [--no-real]         both scores, wall time, calls -> ~/.star/litha/
    python -m litha.bug_bench gate     [--margin 0] [--if-pending]  standard suite with the pending lessons; they are
                                                                    kept only if the score does not drop below the
                                                                    stored baseline (exit 1 when it drops)
    python -m litha.bug_bench build-standard [--seed 32] [--n 32]   (re)make the standard suite (changes the items!)
    python -m litha.bug_bench mine-real [--scan 3000] [--want 12]    verify the queue; (re)mine the real-fix items
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

from litha import ast_mutants as M
from litha import bug_bench as B
from litha import fresh_py

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "litha" / "bench" / "standard_suite.json"
REAL = ROOT / "litha" / "bench" / "real_fixes.json"
HOME = Path.home() / ".star" / "litha"
BASELINE = HOME / "bench-baseline.json"
RUNS = HOME / "bench-runs.jsonl"
SCOREBOARD = HOME / "scoreboard.jsonl"
PENDING = HOME / "lessons-pending.json"
REJECTED = HOME / "lessons-rejected.jsonl"
QUEUE = HOME / "real_items.jsonl"
FIXER_LOG = Path.home() / ".star" / "pr-fixer" / "fixes.jsonl"   # the fixer's real log (after_fix acts only on it)
TREE = ROOT.parent / "litha-bench-std"          # this lane's own detached checkout (other benches use litha-bench)
REPO = "oncoursemail/Star-AI-Project"
COMMANDS = ("standard", "real", "report", "gate", "build-standard", "mine-real")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def git(args: list[str], cwd: Path, timeout: float = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def run_tests(tree: Path, tests: list[str], python: str, timeout: float = 300,
              extra: tuple[str, ...] = ()) -> tuple[bool, str, bool]:
    """(passed, output tail, timed out) for pytest on these files in this tree (its own code, a scratch APPDATA)."""
    env = fresh_py.env(tree, APPDATA=tempfile.mkdtemp(prefix="litha-std-"), PYTHONPATH=str(tree))
    try:
        r = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", *extra, *tests], cwd=tree,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=env)
    except subprocess.TimeoutExpired:
        return False, "timeout", True
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:], False


def bench_tree(sha: str, tree: Path | None = None, pr: int | None = None) -> Path:
    """The bench checkout, clean, at this sha (fetched when this clone does not have it yet; a PR head that never
    reached a branch comes from pull/<pr>/head)."""
    tree = tree or TREE
    if not (tree / ".git").exists():
        git(["worktree", "add", "-q", "--detach", str(tree), "HEAD"], ROOT)
    for ref in [sha] + ([f"pull/{pr}/head"] if pr else []):
        if git(["cat-file", "-e", f"{sha}^{{commit}}"], tree).returncode == 0:
            break
        git(["fetch", "-q", "origin", ref], tree)
    git(["checkout", "-q", "--force", "--detach", sha], tree)
    git(["clean", "-fdq"], tree)
    return tree


def file_hash(data: bytes) -> str:
    """The file's identity whatever the checkout's line endings (core.autocrlf gives CRLF on Windows)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:16]


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def suite_id(suite: dict) -> str:
    return hashlib.sha256(json.dumps(suite.get("items", []), sort_keys=True).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- the standard suite

def build_standard(python: str, n: int = 32, seed: int = 32, sha: str = "", per_file: int = 2,
                   tries_per_family: int = 40, log=print) -> dict:
    """n AST mutants at one sha, round-robin over the families, each one killed by the module's existing tests
    (which pass on the clean code, in under 60 s). At most per_file items per file."""
    if not sha:
        git(["fetch", "-q", "origin", "star/next"], ROOT)
        sha = git(["rev-parse", "origin/star/next"], ROOT).stdout.strip()
    tree = bench_tree(sha)
    rng = random.Random(seed)
    cache: dict[str, str] = {}
    files = sorted([*(tree / "star").rglob("*.py"), *(tree / "server").rglob("*.py")])
    pools: dict[str, list[tuple[str, dict, list[str]]]] = {f: [] for f in M.FAMILIES}
    for f in files:
        rel = f.relative_to(tree).as_posix()
        if "/tests/" in rel or rel.endswith("__init__.py"):
            continue
        tests = B.tests_for(rel[:-3].replace("/", "."), tree / "tests", cache)
        if not tests:
            continue
        for site in M.sites(f.read_bytes().decode("utf-8", errors="replace")):   # bytes: CRLF offsets stay right
            pools[site["op"]].append((rel, site, tests[:3]))
    for fam in M.FAMILIES:
        rng.shuffle(pools[fam])
    green: dict[tuple, float | None] = {}
    per: dict[str, int] = {}
    items: list[dict] = []
    tried = {f: 0 for f in M.FAMILIES}
    while len(items) < n and any(pools[f] and tried[f] < tries_per_family for f in M.FAMILIES):
        for fam in M.FAMILIES:
            if len(items) >= n:
                break
            while pools[fam] and tried[fam] < tries_per_family:
                rel, site, tests = pools[fam].pop()
                if per.get(rel, 0) >= per_file:
                    continue
                key = tuple(tests)
                if key not in green:
                    t = time.time()
                    ok, _, _ = run_tests(tree, tests, python, timeout=90)
                    green[key] = (time.time() - t) if ok and time.time() - t < 60 else None
                took = green[key]
                if took is None:
                    continue
                f = tree / rel
                raw = f.read_bytes()
                text = raw.decode("utf-8")
                new = M.apply(text, site)
                if new is None:
                    continue
                tried[fam] += 1
                f.write_bytes(new.encode("utf-8"))
                try:
                    ok, out, slow = run_tests(tree, tests, python, timeout=max(60, 3 * took), extra=("-x",))
                finally:
                    f.write_bytes(raw)
                if ok or slow:
                    continue
                orig, bad = M.changed_line(text, new, site["line"])
                items.append({"id": f"S{len(items) + 1:02d}", "file": rel, "line": site["line"], "col": site["col"],
                              "op": fam, "sub": site["sub"], "tests": tests, "orig": orig.strip(),
                              "bad": bad.strip(), "file_sha": file_hash(raw)})
                per[rel] = per.get(rel, 0) + 1
                log(f"kept {items[-1]['id']} {fam:<11} {rel}:{site['line']} {site['sub']}")
                break
    return {"made": now()[:10], "sha": sha, "seed": seed, "families": list(M.FAMILIES),
            "rule": "killed by the module's existing tests; tests green and < 60 s on the clean code", "items": items}


def plant(tree: Path, it: dict) -> str | None:
    """Write the standard item's mutant into the tree; None when the file is not the recorded one."""
    f = tree / it["file"]
    raw = f.read_bytes()
    if file_hash(raw) != it["file_sha"]:
        return None
    text = raw.decode("utf-8")
    site = M.find(text, it["line"], it["col"], it["sub"])
    new = M.apply(text, site) if site else None
    if new is None:
        return None
    f.write_bytes(new.encode("utf-8"))
    return new


# ---------------------------------------------------------------- running items

class Lessons:
    """Frozen lessons for one bench run: the fixer reads a snapshot (current + extra), never the live file, and
    the bench's own learn() is not called."""

    def __init__(self, extra: dict | None = None):
        self.data = {**B.load_lessons(), **(extra or {})}
        self.dir = Path(tempfile.mkdtemp(prefix="litha-lessons-"))
        self.old = B.LESSONS

    def use(self, hide: str = "") -> None:
        """Point the fixer at the snapshot, without the lessons made from item `hide` (no answer leaks)."""
        data = {k: v for k, v in self.data.items() if not hide or v.get("item") != hide}
        path = self.dir / "lessons.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        B.LESSONS = path

    def close(self) -> None:
        B.LESSONS = self.old
        shutil.rmtree(self.dir, ignore_errors=True)


def _repair(tree: Path, title: str, out: str, tests: list[str], python: str, asker, diff: str, k: int) -> dict:
    from litha import pr_fixer
    calls = [0]

    def ask(prompt: str) -> str:
        calls[0] += 1
        return (asker or pr_fixer.ask)(prompt)

    fails = pr_fixer.failures(out) or [{"test": tests[0], "section": out[-2500:]}]
    t = time.time()
    try:
        ok, why, rounds = pr_fixer.repair(tree, title, fails, out, tests, python, ask, diff, k=k)
    except Exception as e:  # noqa: BLE001 - one item must not end the bench
        ok, why, rounds = False, f"error {e}"[:200], 0
    return {"ok": bool(ok), "rounds": rounds, "calls": calls[0], "seconds": round(time.time() - t), "why": why[:160]}


def run_standard(python: str, k: int = 1, asker=None, extra_lessons: dict | None = None, ids: list[str] | None = None,
                 suite: dict | None = None, label: str = "standard", log=print) -> dict:
    """Every standard item once, with the PR-style diff of the bug (the fixer's normal input)."""
    suite = suite or load(SUITE)
    items = [it for it in suite["items"] if not ids or it["id"] in ids]
    env = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = "."                       # the fixer's own pytest runs must import the bench tree
    lessons = Lessons(extra_lessons)
    res = {"at": now(), "suite": "standard", "label": label, "suite_id": suite_id(suite), "sha": suite["sha"],
           "fixer": git(["rev-parse", "--short", "HEAD"], ROOT).stdout.strip(), "k": k, "mode": "diff",
           "n": len(items), "solved": 0, "seconds": 0, "calls": 0, "by_op": {}, "items": []}
    t0 = time.time()
    try:
        for it in items:
            tree = bench_tree(suite["sha"])
            if plant(tree, it) is None:
                res["items"].append({"id": it["id"], "ok": False, "why": "could not plant (file changed)"})
                continue
            diff = git(["diff"], tree).stdout
            _, out, _ = run_tests(tree, it["tests"], python, timeout=300, extra=("-x",))
            lessons.use()
            r = _repair(tree, f"fix {it['file']}", out, it["tests"], python, asker, diff, k)
            res["items"].append({"id": it["id"], **r})
            res["solved"] += int(r["ok"])
            res["calls"] += r["calls"]
            o = res["by_op"].setdefault(it["op"], [0, 0])
            o[0] += int(r["ok"])
            o[1] += 1
            log(f"{'SOLVED' if r['ok'] else 'missed'} {it['id']} {it['op']:<11} {it['file']}:{it['line']} "
                f"{r['seconds']} s {r['calls']} calls  {r['why'][:80]}")
    finally:
        lessons.close()
        _env(env)
        bench_tree(suite["sha"])
    res["seconds"] = round(time.time() - t0)
    append(RUNS, res)
    return res


def real_items() -> list[dict]:
    """The repo's real-fix items plus the verified ones the learning loop queued on this machine."""
    items = list(load(REAL).get("items", []))
    seen = {(i["repo"], i["sha"]) for i in items}
    try:
        rows = [json.loads(ln) for ln in QUEUE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        rows = []
    for r in rows:
        if r.get("verified") and (r["repo"], r["sha"]) not in seen:
            seen.add((r["repo"], r["sha"]))
            items.append(r)
    return items


def break_tree(tree: Path, it: dict) -> None:
    """The broken state of a real item: its sha, with the fix's source files taken back to the parent."""
    bench_tree(it["sha"], tree, it.get("pr"))
    if it.get("src"):
        git(["checkout", "-q", it["parent"], "--", *it["src"]], tree)


def run_real(python: str, k: int = 1, asker=None, ids: list[str] | None = None, items: list[dict] | None = None,
             log=print) -> dict:
    """Every real-fix item once, blind (the failing tests and the code; the change that broke it is unknown)."""
    items = [it for it in (items if items is not None else real_items()) if not ids or it["id"] in ids]
    env = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = "."
    lessons = Lessons()
    res = {"at": now(), "suite": "real", "fixer": git(["rev-parse", "--short", "HEAD"], ROOT).stdout.strip(),
           "k": k, "mode": "blind", "n": 0, "solved": 0, "seconds": 0, "calls": 0, "items": []}
    t0 = time.time()
    try:
        for it in items:
            tree = bench_tree(it["sha"], pr=it.get("pr"))
            break_tree(tree, it)
            ok, out, _ = run_tests(tree, it["tests"], python, timeout=300)
            if ok:
                res["items"].append({"id": it["id"], "ok": False, "why": "stale: the tests pass on the broken code"})
                continue
            lessons.use(hide=f"{it['repo']}@{it['sha']}")
            r = _repair(tree, "fix the failing tests", out, it["tests"], python, asker, "", k)
            res["items"].append({"id": it["id"], **r})
            res["n"] += 1
            res["solved"] += int(r["ok"])
            res["calls"] += r["calls"]
            log(f"{'SOLVED' if r['ok'] else 'missed'} {it['id']} {it['sha'][:9]} {','.join(it.get('src', []))[:60]} "
                f"{r['seconds']} s {r['calls']} calls  {r['why'][:70]}")
    finally:
        lessons.close()
        _env(env)
    res["seconds"] = round(time.time() - t0)
    append(RUNS, res)
    return res


def _env(old: str | None) -> None:
    if old is None:
        os.environ.pop("PYTHONPATH", None)
    else:
        os.environ["PYTHONPATH"] = old


# ---------------------------------------------------------------- learning: items + lessons after every real fix

def _sha_for(pr: int, repo: str) -> str:
    from litha import pr_fixer
    tried = load(pr_fixer.STATE)
    return str(tried.get(str(pr) if repo == REPO else f"{repo}#{pr}", ""))


def after_fix(row: dict) -> dict | None:
    """Called after every fixer log row. A real Python test failure (fixed or not) becomes a queued bench item (the
    PR head that failed + its failing test files); a fixed one also gives a pending lesson (her cause sentence),
    which `gate` keeps only if the standard suite does not drop. Returns the queued item, or None."""
    from litha import pr_fixer
    if Path(pr_fixer.LOG) != FIXER_LOG:                 # a redirected log (a test) is no real fix
        return None
    tests = [str(t) for t in row.get("tests") or []]
    repo = row.get("repo") or REPO
    if (row.get("result") not in ("fixed", "failed") or row.get("kind") or repo != REPO or not tests
            or not all(re.match(r"^tests/[\w/.-]+\.py$", t) for t in tests)):
        return None
    sha = _sha_for(int(row["pr"]), repo)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    try:
        known = {json.loads(ln).get("sha") for ln in QUEUE.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except OSError:
        known = set()
    item = {"id": f"Q{int(row['pr'])}-{sha[:7]}", "repo": repo, "pr": int(row["pr"]), "sha": sha, "tests": tests,
            "src": [], "result": row["result"], "source": "pr-fixer", "added": now()[:10],
            "verified": False}                           # verified once a fix is known (litha.real_fixes)
    fix_pr = re.search(r"/pull/(\d+)$", str(row.get("fix_pr", "")))
    if fix_pr:
        item["fix_pr"] = int(fix_pr.group(1))
    if sha not in known:
        append(QUEUE, item)
    why = str(row.get("why", "")).strip()
    if row["result"] == "fixed" and why and not why.startswith(("requirements", "merged")):
        add_pending(f"real:{item['pr']}", why, item=f"{repo}@{sha}")
    return item


def add_pending(key: str, hint: str, item: str = "", example: dict | None = None) -> None:
    """A lesson waiting for the gate (the fixer does not see it yet)."""
    pending = load(PENDING)
    pending[key] = {"tries": 0, "solved": 0, "real": True, "hint": hint[:200], "item": item,
                    **({"example": example} if example else {})}
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(pending, indent=1), encoding="utf-8")


def gate(python: str, margin: int = 0, k: int = 1, asker=None, log=print) -> tuple[int, dict]:
    """The standard suite with the pending lessons on top of the current ones, against the stored baseline. Kept
    (moved into lessons.json) only when solved >= baseline - margin; otherwise logged as rejected. Exit code 0 =
    not lower, 1 = lower, 2 = no baseline for this suite."""
    base, suite = load(BASELINE), load(SUITE)
    if base.get("suite_id") != suite_id(suite):
        log("no baseline for this standard suite: run `bug_bench standard --save-baseline` first")
        return 2, {}
    pending = load(PENDING)
    res = run_standard(python, k, asker, extra_lessons=pending, label="gate", log=log)
    keep = res["solved"] >= base["solved"] - margin
    verdict = {"at": now(), "baseline": base["solved"], "solved": res["solved"], "n": res["n"], "margin": margin,
               "pending": sorted(pending), "kept": keep}
    if pending:
        if keep:
            lessons = B.load_lessons()
            lessons.update(pending)
            B.LESSONS.parent.mkdir(parents=True, exist_ok=True)
            B.LESSONS.write_text(json.dumps(lessons, indent=1), encoding="utf-8")
        else:
            append(REJECTED, verdict | {"lessons": pending})
        PENDING.unlink(missing_ok=True)
    log(f"gate: {res['solved']}/{res['n']} vs baseline {base['solved']}/{base['n']} (margin {margin}): "
        f"{'not lower' if keep else 'LOWER'}; {len(pending)} pending lesson(s) {'kept' if keep else 'dropped'}")
    return (0 if keep else 1), verdict


# ---------------------------------------------------------------- scoreboard

def last_run(suite: str) -> dict:
    try:
        rows = [json.loads(ln) for ln in RUNS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return {}
    return next((r for r in reversed(rows) if r.get("suite") == suite and r.get("label", "") != "gate"), {})


def report(python: str, k: int = 1, last: bool = False, real: bool = True, asker=None, log=print) -> dict:
    """Standard-suite score, real-fix score, wall time and model calls; one JSON record in the scoreboard."""
    std = last_run("standard") if last else run_standard(python, k, asker, log=log)
    rf = (last_run("real") if last else run_real(python, k, asker, log=log)) if real else {}
    base = load(BASELINE)
    rec = {"at": now(), "fixer": std.get("fixer") or rf.get("fixer"), "k": k,
           "standard": {x: std.get(x) for x in ("solved", "n", "seconds", "calls", "suite_id", "sha", "at")},
           "real": {x: rf.get(x) for x in ("solved", "n", "seconds", "calls", "at")} if rf else None,
           "baseline": {x: base.get(x) for x in ("solved", "n", "at", "fixer")} if base else None}
    append(SCOREBOARD, rec)
    s = rec["standard"]
    log(f"standard suite  {s['solved']}/{s['n']}   {s['seconds']} s   {s['calls']} calls"
        + (f"   (baseline {base['solved']}/{base['n']})" if base else ""))
    if rf:
        log(f"real fixes      {rf['solved']}/{rf['n']}   {rf['seconds']} s   {rf['calls']} calls")
    log(f"record: {SCOREBOARD}")
    return rec


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.bug_bench")
    ap.add_argument("cmd", choices=COMMANDS)
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--margin", type=int, default=0)
    ap.add_argument("--last", action="store_true", help="report: the latest stored runs, no new run")
    ap.add_argument("--no-real", action="store_true")
    ap.add_argument("--if-pending", action="store_true", help="gate: run only when lessons wait for it (nightly)")
    ap.add_argument("--id", action="append", help="only these item ids")
    ap.add_argument("--seed", type=int, default=32)
    ap.add_argument("--n", type=int, default=32)
    ap.add_argument("--scan", type=int, default=3000)
    ap.add_argument("--want", type=int, default=12)
    a = ap.parse_args(argv)
    if a.cmd == "build-standard":
        suite = build_standard(a.python, a.n, a.seed)
        SUITE.parent.mkdir(parents=True, exist_ok=True)
        SUITE.write_text(json.dumps(suite, indent=1) + "\n", encoding="utf-8")
        print(f"{len(suite['items'])} items -> {SUITE.relative_to(ROOT).as_posix()} (suite {suite_id(suite)})")
        return 0
    if a.cmd == "mine-real":
        from litha import real_fixes
        print(f"{real_fixes.verify_queue(a.python)} queued item(s) verified")
        items = real_fixes.mine(a.python, scan=a.scan, want=a.want)
        REAL.parent.mkdir(parents=True, exist_ok=True)
        REAL.write_text(json.dumps({"made": now()[:10], "repo": REPO, "items": items}, indent=1) + "\n",
                        encoding="utf-8")
        print(f"{len(items)} real-fix items -> {REAL.relative_to(ROOT).as_posix()}")
        return 0
    if a.cmd == "standard":
        res = run_standard(a.python, a.k, ids=a.id)
        if a.save_baseline and not a.id:
            BASELINE.parent.mkdir(parents=True, exist_ok=True)
            BASELINE.write_text(json.dumps({x: res[x] for x in ("at", "suite_id", "sha", "fixer", "k", "n", "solved",
                                                                "seconds", "calls")}, indent=1), encoding="utf-8")
        print(json.dumps({x: res[x] for x in ("solved", "n", "seconds", "calls", "by_op", "suite_id")}))
        return 0
    if a.cmd == "real":
        res = run_real(a.python, a.k, ids=a.id)
        print(json.dumps({x: res[x] for x in ("solved", "n", "seconds", "calls")}))
        return 0
    if a.cmd == "gate":
        if a.if_pending and not load(PENDING):
            print("gate: no pending lessons")
            return 0
        return gate(a.python, a.margin, a.k)[0]
    report(a.python, a.k, a.last, not a.no_real)
    return 0
