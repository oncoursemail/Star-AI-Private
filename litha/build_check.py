"""Build/test check before a decision (docs/LITHA_AUTONOMY.md section 4s).

Before her merger calls a PR merge-ready, and before her fixer pushes a merge or fix of hers, the code that would land
(the PR head merged with today's base) builds and passes the tests the diff touches, run here in a throwaway
worktree. Reading the diff alone let two broken merges of hers out (#853/#857: a doubled prop, tsc TS2300; Studio
#486: compiled, broke main's raycast test).

What runs (plan): pytest on the test files the diff touches, the test files that import a changed module and CI's
quick file; tsc for any frontend change, vitest for touched frontend tests; `cargo test -p <crate>` for every crate a
changed .rs file is in (one cargo at a time: rust_fix.BUILD). Cached per (repo, PR, head, base); skipped when CI's
green runs on this head started after the base's tip was committed (CI then ran the full suite on the same code);
time-boxed: a check that does not finish holds the PR too.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from litha import fresh_py, rust_fix

CACHE = Path.home() / ".star" / "pr-merger" / "build_checks.json"
TTL = 7 * 24 * 3600                       # a (head, base) pair gives the same answer; old entries are dropped
BUDGET = 900                              # seconds for one check, all steps together
MAX_TEST_FILES = 8
QUICK = ("tests/test_star_research.py",)  # CI's first, quick pytest step (.github/workflows/tests.yml)
FRONT_CODE = re.compile(r"^frontend/(src/.*\.[cm]?[jt]sx?|package\.json|tsconfig[^/]*\.json)$")
FRONT_TEST = re.compile(r"^frontend/.*\.test\.[cm]?[jt]sx?$")
PY_FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)
GREEN = {"SUCCESS", "SKIPPED", "NEUTRAL"}


def plan(tree: Path, files: list[str]) -> dict:
    """{pytest: [test files], tsc: bool, vitest: [test files], cargo: [.rs files]} for the changed files."""
    from litha import pr_fixer
    tests = [f for f in files if re.match(r"^tests/(.*/)?test_[^/]*\.py$", f) and (tree / f).is_file()]
    src = [f for f in files if f.endswith(".py") and not f.startswith("tests/") and (tree / f).is_file()]
    if src:
        tests += [t for t in pr_fixer.related_tests(tree, src, limit=MAX_TEST_FILES) if t not in tests]
    if tests or src:
        tests += [q for q in QUICK if (tree / q).is_file() and q not in tests]
    cargo = [f for f in files if f.endswith(".rs")] if (tree / "Cargo.toml").is_file() else []
    return {"pytest": tests[:MAX_TEST_FILES + len(QUICK)],
            "tsc": any(FRONT_CODE.match(f) for f in files) and (tree / "frontend" / "package.json").is_file(),
            "vitest": [f for f in files if FRONT_TEST.match(f) and (tree / f).is_file()],
            "cargo": cargo}


def _pytest(tree: Path, tests: list[str], python: str, timeout: float) -> tuple[bool, str, str]:
    from litha import pr_fixer
    env = fresh_py.env(tree, APPDATA=tempfile.mkdtemp(prefix="litha-check-"))
    r = pr_fixer.sh([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *tests], cwd=tree,
                    timeout=timeout, env=env)
    out = r.stdout + r.stderr
    names = list(dict.fromkeys(PY_FAILED.findall(out)))
    if r.returncode and 0 < len(names) <= 3:                 # tests that fail only under load (test_litha_bug_diff):
        again = pr_fixer.sh([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rfE", *names], cwd=tree,
                            timeout=timeout, env=env)        # each failing test once more, alone
        if again.returncode == 0:
            return True, f"passed alone: {', '.join(names)}", out[-3000:]
    if r.returncode == 0:
        return True, "", out[-3000:]
    return False, ", ".join(names[:4]) or out.strip()[-300:], out[-3000:]


def _front(tree: Path, vitest: list[str], timeout: float) -> tuple[bool, str, str]:
    """`npm run typecheck` (+ `npm run test -- <files>` for touched tests) with the shared node_modules."""
    from litha import pr_fixer
    npm = shutil.which("npm")
    why = pr_fixer.frontend_deps(tree) if npm else "npm is not installed"
    if why or not npm:                                            # CI's own tsc on this head still counts; not a failure
        return True, f"tsc not run here: {why[:200]}", ""
    env = dict(os.environ, CI="1", NO_COLOR="1", FORCE_COLOR="0")
    try:
        r = pr_fixer.sh([npm, "run", "typecheck", "--prefix", "frontend"], cwd=tree, timeout=timeout, env=env)
        found = (pr_fixer.frontend_failures(r.stdout + r.stderr) or {}).get("tsc", [])
        if r.returncode:
            named = "; ".join(f"{e['file']}({e['line']}): {e['code']} {e['message']}" for e in found[:3])
            return False, "tsc: " + (named or (r.stdout + r.stderr).strip()[-300:]), r.stdout[-3000:]
        if vitest:
            rel = [f[len("frontend/"):] for f in vitest]
            r = pr_fixer.sh([npm, "run", "test", "--prefix", "frontend", "--", *rel], cwd=tree, timeout=timeout,
                            env=env)
            if r.returncode:
                secs = pr_fixer.vitest_sections(r.stdout + r.stderr)
                return False, "vitest: " + (", ".join(f"{s['file']} > {s['test']}" for s in secs[:3])
                                            or (r.stdout + r.stderr).strip()[-300:]), r.stdout[-3000:]
    finally:
        pr_fixer._unlink(tree / "frontend" / "node_modules")
    return True, "", ""


def run(tree: Path, files: list[str], python: str, budget: float = BUDGET, steps: dict | None = None,
        cargo: bool = True) -> dict:
    """Run the plan in tree: {ok, ran: [step names], failed: what failed (named), seconds}. Stops at the first failing
    step. A step that runs past the budget fails the check (named as such)."""
    import subprocess
    steps = steps or plan(tree, files)
    t0, ran = time.time(), []

    def left() -> float:
        return max(5.0, budget - (time.time() - t0))

    def done(ok: bool, failed: str = "") -> dict:
        return {"ok": ok, "ran": ran, "failed": failed[:600], "seconds": round(time.time() - t0, 1)}

    try:
        if steps.get("pytest"):
            ran.append("pytest " + " ".join(steps["pytest"]))
            ok, names, _ = _pytest(tree, steps["pytest"], python, left())
            if not ok:
                return done(False, f"pytest: {names}")
            if names:
                ran.append(names)
        if steps.get("tsc"):
            ran.append("tsc" + (" + vitest " + " ".join(steps["vitest"]) if steps.get("vitest") else ""))
            ok, why, _ = _front(tree, steps.get("vitest") or [], left())
            if not ok:
                return done(False, why)
            if why:
                ran[-1] = why
        if cargo and steps.get("cargo"):
            ok, fails, crates, out = rust_fix.crate_tests(tree, steps["cargo"])
            ran.append(f"cargo test -p {' -p '.join(crates)}" if crates else "cargo (no crate)")
            if not ok:
                errs = rust_fix.errors(out)
                named = "; ".join(f"{e['file']}:{e['line']} {e['error']}" for e in errs[:3]) if errs else fails
                return done(False, f"cargo test -p {' -p '.join(crates)}: {named}")
    except subprocess.TimeoutExpired:
        return done(False, f"did not finish within {budget:.0f} s ({ran[-1] if ran else 'setup'})")
    return done(True)


def _when(stamp: str) -> float:
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def ci_covered(checks: list[dict], base_time: float) -> bool:
    """CI's checks on this head all passed and the last of them started after the base's tip was committed: a
    pull_request run tests the head merged with the base of its start, so it already ran on this exact code."""
    if not checks or base_time <= 0 or any(c.get("conclusion") not in GREEN for c in checks):
        return False
    real = [c for c in checks if c.get("conclusion") == "SUCCESS"]
    return bool(real) and all(_when(c.get("started_at") or "") > base_time for c in real)


def _load(path: Path) -> dict:
    try:
        memo = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {k: v for k, v in memo.items() if now - v.get("ts", 0) < TTL}


def _save(path: Path, memo: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(memo), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass                                            # a lost memo only costs a second run


def check(pr: dict, files: list[str], python: str, checks: list[dict] | None = None, cache: Path | None = None,
          runner=run) -> dict:
    """The merger's check of one merge-ready PR: {ok, skipped|ran, failed, seconds}. ok False = hold."""
    from litha import pr_fixer, pr_merger
    cache = cache or CACHE
    head, base = pr["headRefOid"], pr.get("baseRefOid") or ""
    key = f"{pr_merger.REPO}#{pr['number']}@{head}^{base}"
    memo = _load(cache)
    if key in memo:
        return {**memo[key], "cached": True}
    clone, work = pr_fixer.CLONE, pr_fixer.WORK
    t0 = time.time()
    pr_fixer.sh(["git", "-C", str(clone), "fetch", "-q", "origin", pr_merger.BASE,
                 f"pull/{pr['number']}/head:refs/litha-check/{pr['number']}", "--force"])
    stamp = pr_fixer.sh(["git", "-C", str(clone), "show", "-s", "--format=%ct", base or f"origin/{pr_merger.BASE}"])
    base_time = float(stamp.stdout.strip() or 0) if stamp.returncode == 0 else 0.0
    if ci_covered(checks or [], base_time):
        res = {"ok": True, "skipped": "CI ran green on this head after the base's tip", "ran": [], "failed": "",
               "seconds": round(time.time() - t0, 1)}
    else:
        tree = work / f"litha-check-{pr['number']}"
        if tree.exists():
            pr_fixer.sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(tree)])
        pr_fixer.sh(["git", "-C", str(clone), "worktree", "add", "-q", "--detach", str(tree), head])
        try:
            m = pr_fixer.sh(["git", *pr_fixer.IDENTITY, "merge", "--no-ff", "--no-commit",
                             base or f"origin/{pr_merger.BASE}"], cwd=tree)
            if m.returncode:
                res = {"ok": False, "ran": ["git merge"], "failed": "the head does not merge cleanly with the base",
                       "seconds": round(time.time() - t0, 1)}
            else:
                res = runner(tree, files, python)
                res["seconds"] = round(time.time() - t0, 1)
        finally:
            pr_fixer.sh(["git", "-C", str(clone), "worktree", "remove", "--force", str(tree)])
    memo[key] = {**res, "ts": round(time.time())}
    _save(cache, memo)
    return res
