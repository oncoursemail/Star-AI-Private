"""Litha fixes failing PRs herself: failed CI log -> her patch -> the failing tests rerun locally -> her own PR.

For an open, non-draft PR into star/next whose Python checks failed on the head commit:
1. read the failed job log, take the pytest failures (test id + its traceback section);
2. check the PR out on her own branch litha/fix-<pr>-<yyyymmdd> in a throwaway worktree;
3. Litha gets the tracebacks + the real code around every frame and answers search/replace edits;
4. edits that do not match the file exactly once, or touch tests / CI / locks, are refused and she is told why;
5. the failing tests run locally; up to ROUNDS rounds, each with the new output;
6. only when they pass: commit through `star commit` (secret checks), push HER branch (never the author's, never
   force), open a PR into star/next. The merger (star/pr_merger) merges it once CI is green there.
The tests are the spec: she may not edit them. Tried heads are remembered so a PR is not retried until it changes.

    python -m litha.pr_fixer [--pr N] [--max 1] [--dry]
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
import datetime as dt
import json
import shutil
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import tomllib

from litha import rust_fix
from litha.pr_merger import BASE, REPO, gh, head_checks, latest_runs, open_prs

ROOT = Path(__file__).resolve().parents[1]                  # the worktree this runs from
WORK = ROOT.parent                                          # worktrees/
CLONE = ROOT.parents[1] / "Star-AI"
HOME_CLONE = CLONE                                          # STAR's own repo: star commit, Python tests
IDENTITY = ["-c", "user.name=oncoursemail", "-c", "user.email=84545815+oncoursemail@users.noreply.github.com"]
STATE = Path.home() / ".star" / "pr-fixer" / "tried.json"


TRIED = threading.Lock()


@contextmanager
def file_lock(path: Path, wait: float = 60, stale: float = 120):
    """Another process (a re-queue, a second run) writing the same file waits here; a lock older than `stale` s is
    left over from a dead process and is taken over."""
    end = time.time() + wait
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                old = time.time() - path.stat().st_mtime > stale
            except FileNotFoundError:
                continue
            if old or time.time() > end:
                path.touch()
                break
            time.sleep(0.05)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def write_atomic(path: Path, text: str) -> None:
    """Readers see the old file or the new one, never half of it (Windows refuses a replace while a reader has the
    file open: retry briefly)."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for i in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 39:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05)


def mark(key: str, sha: str) -> dict:
    """Record one attempt on the CURRENT file: a copy loaded at the start of a long run must not undo a re-queue
    made meanwhile (seen 2026-11-01: four re-queued Studio PRs silently came back as tried). Several workers mark at
    once: read-modify-write under a thread lock and a file lock, written atomically."""
    with TRIED, file_lock(STATE.with_name("tried.lock")):
        tried = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        tried[key] = sha
        write_atomic(STATE, json.dumps(tried))
    return tried
LOG = Path.home() / ".star" / "pr-fixer" / "fixes.jsonl"
ROUNDS = 5
NO_TOUCH = re.compile(r"^(tests/|\.github/)|(^|/)(requirements[^/]*\.txt|pnpm-lock\.yaml|[^/]+\.lock)$")
GATES = re.compile(r"^(scripts/pyright_baseline\.json|pyrightconfig\.json)$")   # her edits may not move the bar
FAILED = re.compile(r"^FAILED (\S+::\S+)", re.M)
FRAME = re.compile(r"^(?:\S+ +)?((?:star|server|metallic|tools|tests)/[\w/.-]+\.py):(\d+):", re.M)
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STAMP = re.compile(r"^(?:\S+\t\S+\t)?\d{4}-\d\d-\d\dT[\d:.]+Z ", re.M)   # "2026-...Z " (gh run view adds "job<TAB>step<TAB>")

PROMPT = """You are Litha, fixing a failing pull request in STAR's Python repository so its tests pass.
PR title: {title}
Failing tests and their output:
{failures}

What this PR changed (the cause is most likely in these lines):
{diff}

The real code around every line in the tracebacks (line numbers on the left, do not copy them):
{code}
{lessons}{feedback}
Fix the cause in the source code. The tests describe the wanted behaviour: never edit files under tests/.
Edit only files shown above, with exactly those paths. Make the smallest correct change. Answer only JSON:
{{"why": "<one sentence: the cause>", "edits": [{{"file": "<path>", "find": "<exact existing text, a few whole lines,
unique in the file>", "replace": "<new text>"}}]}}"""


SHARED = threading.RLock()     # the shared clone (fetch, worktree add/remove, star commit): one worker at a time


def sh(args: list[str], cwd: Path | None = None, timeout: float = 600, env: dict | None = None):
    tool = Path(args[0]).stem.lower() if args else ""
    shared = (tool == "git" and args[1:2] == ["-C"]) or tool == "star"
    lock = rust_fix.BUILD if tool == "cargo" else SHARED if shared else nullcontext()
    with lock:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)


def failed_logs(sha: str) -> str:
    """The text of every failed check's job log on this commit (GitHub Actions jobs only)."""
    data = json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"))
    out = []
    for c in latest_runs(data.get("check_runs", [])):
        if (c.get("conclusion") or "") != "failure":
            continue
        m = re.search(r"/job/(\d+)", c.get("details_url") or "")
        if m:
            try:
                out.append(ANSI.sub("", gh("api", "--allow-escape-sequences", f"repos/{REPO}/actions/jobs/{m.group(1)}/logs",
                                           timeout=300)))
            except RuntimeError:
                pass
    return STAMP.sub("", "\n".join(out))


def failures(log: str, limit: int = 3) -> list[dict]:
    """[{test, section}] for the first pytest failures: the '____ name ____' block of each FAILED id."""
    out = []
    for test in dict.fromkeys(FAILED.findall(log)):
        name = test.split("::")[-1]
        m = re.search(rf"^_{{3,}} {re.escape(name)}(?:\[.*?\])? _{{3,}}$(.*?)(?=^_{{3,}} |^=+ )", log, re.M | re.S)
        out.append({"test": test, "section": (m.group(1) if m else "")[-2500:]})
        if len(out) == limit:
            break
    return out


SKIP_CALLS = {"assert", "print", "len", "any", "all", "set", "dict", "list", "str", "int", "next", "iter", "sorted",
              "range", "open", "isinstance", "getattr", "json", "loads", "dumps"}


def called_functions(tree: Path, sections: str, limit: int = 4, max_lines: int = 70) -> list[str]:
    """Whole definitions of the functions the failing test calls (an assert in the test never shows their frame)."""
    out, seen = [], set()
    sources = sorted(p for d in ("star", "server", "metallic") if (tree / d).is_dir() for p in (tree / d).rglob("*.py"))
    for name in re.findall(r"\b([a-z_][a-z0-9_]{2,})\(", sections):
        if name in seen or name.startswith("test_") or name in SKIP_CALLS:
            continue
        seen.add(name)
        for f in sources:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            start = next((i for i, ln in enumerate(lines) if re.match(rf"\s*(async\s+)?def {name}\(", ln)), None)
            if start is None:
                continue
            indent = len(lines[start]) - len(lines[start].lstrip())
            end = start + 1
            while end < len(lines) and end - start < max_lines and (
                    not lines[end].strip() or len(lines[end]) - len(lines[end].lstrip()) > indent):
                end += 1
            out.append(f"--- {f.relative_to(tree).as_posix()}\n"
                       + "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end)))
            break
        if len(out) == limit:
            break
    return out


def code_excerpts(tree: Path, sections: str, around: int = 25, budget: int = 9000) -> str:
    sections = sections.replace("\\", "/")                # Windows tracebacks print backslash paths
    out, seen = called_functions(tree, sections), set()
    for path, line in FRAME.findall(sections):
        key = (path, int(line) // 20)
        f = tree / path
        if key in seen or not f.is_file():
            continue
        seen.add(key)
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        no = int(line)
        lo, hi = max(0, no - around), min(len(lines), no + around)
        out.append(f"--- {path}\n" + "\n".join(f"{i + 1}: {lines[i]}" for i in range(lo, hi)))
    text = "\n".join(out)
    return text[:budget]


def apply_edits(tree: Path, edits: list) -> list[str]:
    """Apply search/replace edits; returns the problems (an edit with a problem is not applied)."""
    problems = []
    for e in edits if isinstance(edits, list) else []:
        try:
            path, find, new = str(e["file"]).replace("\\", "/").lstrip("./"), str(e["find"]), str(e["replace"])
        except (KeyError, TypeError):
            problems.append("an edit lacked file/find/replace")
            continue
        f = (tree / path).resolve()
        if NO_TOUCH.search(path) or GATES.match(path) or tree.resolve() not in f.parents:
            problems.append(f"{path}: you may not edit this file (tests, CI and locks are the spec)")
            continue
        if not f.is_file():
            problems.append(f"{path}: no such file")
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(find) if find else 0
        if n != 1:
            problems.append(f"{path}: 'find' matched {n} times, it must match exactly once")
            continue
        f.write_bytes(text.replace(find, new).encode("utf-8"))
    return problems


def _lessons() -> str:
    try:
        from litha.bug_bench import lessons_text
        return lessons_text()
    except Exception:  # noqa: BLE001 - lessons are a help, never a reason to fail a fix
        return ""


def source_diff(diff: str) -> str:
    """The PR's diff without test files (the tests are the spec, the cause is in the source)."""
    parts = re.split(r"(?m)^(?=diff --git )", diff)
    return "".join(p for p in parts if not re.match(r"diff --git a/tests/", p))


def run_tests(tree: Path, tests: list[str], python: str, extra: tuple[str, ...] = ()) -> tuple[bool, str]:
    env = dict(os.environ, APPDATA=tempfile.mkdtemp(prefix="litha-fix-"))
    r = sh([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", *extra, *tests], cwd=tree, timeout=900,
           env=env)
    return r.returncode == 0, (r.stdout + r.stderr)[-3000:]


def deep_failure(tree: Path, fails: list[dict], python: str) -> str:
    """No diff to point at the cause: rerun the first failing test with the values of every local (-l) and full
    tracebacks, so she sees WHICH value is wrong, not only that an assert failed."""
    first = fails[0]["test"] if fails else ""
    if "::" not in first:
        return ""
    _, out = run_tests(tree, [first], python, ("--tb=long", "-l", "-x"))
    return out[-3500:]


def ask(prompt: str) -> str:
    from star.asset3d.llm import chat
    text, _ = chat("litha", [{"role": "user", "content": prompt}], max_tokens=1500, temperature=0.2,
                   json_mode=True, timeout=900)
    return text


def repair(tree: Path, title: str, fails: list[dict], out: str, tests: list[str], python: str,
           asker=ask, diff: str = "") -> tuple[bool, str, int]:
    """Up to ROUNDS rounds of Litha's edits + the tests; progress (fewer failures) is kept between rounds."""
    ok, round_no = False, 0
    feedback, why, best, kept_edits = "", "", len(FAILED.findall(out)) or 99, []
    if not diff.strip():                                     # blind: show the wrong values instead of a diff
        deep = deep_failure(tree, fails, python)
        if deep:
            fails = [{"test": fails[0]["test"], "section": deep}] + fails[1:]
    for round_no in range(1, ROUNDS + 1):
        sections = "\n\n".join(f"{f['test']}\n{f['section']}" for f in fails) + "\n\nlocal run now:\n" + out[-1500:]
        prompt = PROMPT.format(title=title, failures=sections[:6000],
                               code=code_excerpts(tree, sections), feedback=feedback, lessons=_lessons(),
                               diff=source_diff(diff)[:5000] or "(not available)")
        try:
            answer = json.loads(asker(prompt))
        except (ValueError, TypeError):
            feedback = "\nYour last answer was not valid JSON. Answer only the JSON object.\n"
            continue
        why = str(answer.get("why", ""))[:300]
        problems = apply_edits(tree, answer.get("edits"))
        ok, out = run_tests(tree, tests, python)
        if ok:
            break
        now = len(FAILED.findall(out)) or 99
        if now < best:                                      # fewer failures: keep this progress, fix the rest next
            best, fails = now, failures(out) or fails
            kept_edits.append(answer.get("edits"))
            feedback = ("\nYour edits were kept: fewer tests fail now. The code above already includes them. "
                        "Fix what still fails:\n" + out[-1500:] + "\n")
            continue
        sh(["git", "checkout", "--", "."], cwd=tree)        # no progress: back to the last kept state
        for kept in kept_edits:
            apply_edits(tree, kept)
        feedback = ("\nYour previous attempt did not work. " + ("Problems: " + "; ".join(problems) + ". " if problems
                    else "") + "Test output after it:\n" + out[-1500:] + "\nTry a different fix.\n")
    return ok, why, round_no


LINT = re.compile(r"^((?:star|litha)/[\w/.-]+\.py):(\d+):\d+: (\w+) (.*)$", re.M)   # CI: ruff check star litha
RUFF_CI = re.compile(r"Ruff \(\w+\)|ruff check star")         # the lint step failed (it runs before pytest in CI)
LINT_PROMPT = """You are Litha, fixing ruff lint errors in STAR's Python code so CI passes. Keep behaviour the same.
Errors, each with the real code around it (line numbers on the left, do not copy them):
{errors}
{feedback}
Fix each error the way the rule intends (remove what is unused, define what is undefined, do not add noqa).
Answer only JSON: {{"why": "<one sentence>", "edits": [{{"file": "<path>", "find": "<exact existing text, unique in
the file>", "replace": "<new text>"}}]}}"""


def lint(tree: Path, python: str) -> list[tuple[str, int, str]]:
    dirs = [d for d in ("star", "litha") if (tree / d).is_dir()]
    r = sh([python, "-m", "ruff", "check", *dirs, "--output-format=concise", "--no-cache"], cwd=tree)
    return [(f, int(n), f"{rule} {msg}") for f, n, rule, msg in LINT.findall(r.stdout.replace("\\", "/"))]


def fix_lint(tree: Path, python: str, asker=ask) -> tuple[bool, str, int]:
    """Ruff's safe autofixes first, then up to ROUNDS rounds of her edits; a round that does not lower the error
    count is undone."""
    errs = lint(tree, python)
    if not errs:
        return False, "ruff passes locally (CI-only lint failure)", 0
    sh([python, "-m", "ruff", "check", "--fix", "--no-cache", *sorted({e[0] for e in errs})], cwd=tree)
    feedback, why = "", "ruff safe autofixes"
    for round_no in range(1, ROUNDS + 1):
        errs = lint(tree, python)
        if not errs:
            return True, why, round_no
        listing = []
        for f, n, msg in errs[:12]:
            lines = (tree / f).read_text(encoding="utf-8", errors="replace").splitlines()
            near = "\n".join(f"{i + 1:5}: {lines[i]}" for i in range(max(0, n - 7), min(len(lines), n + 6)))
            listing.append(f"{f}:{n}: {msg}\n{near}")
        before = {f: (tree / f).read_bytes() for f in {e[0] for e in errs}}
        try:
            answer = json.loads(asker(LINT_PROMPT.format(errors="\n\n".join(listing)[:7000], feedback=feedback)))
        except (ValueError, TypeError):
            feedback = "\nYour last answer was not valid JSON. Answer only the JSON object.\n"
            continue
        problems = apply_edits(tree, answer.get("edits"))
        after = lint(tree, python)
        if len(after) < len(errs):
            why, feedback = str(answer.get("why", why))[:300], ""
            continue
        for f, data in before.items():                     # no progress: undo this round
            (tree / f).write_bytes(data)
        feedback = ("\nYour previous edits did not reduce the errors. " + ("Problems: " + "; ".join(problems) + ". "
                    if problems else "") + "Try a different fix.\n")
    return not lint(tree, python), why, ROUNDS


TYPE_CI = re.compile(r"New pyright errors[^\n]*\n((?:.*\.py:\d+: .*\n?){1,4})")
PYRIGHT = ["--yes", "pyright@1.1.414"]                      # the version CI pins (.github/workflows/tests.yml)
BARE = Path.home() / ".star" / "pr-fixer" / "bare-python"   # no third-party packages, like CI's job venv
IGNORE = re.compile(r"#\s*(type|pyright)\s*:\s*ignore")
TYPE_PROMPT = """You are Litha, fixing new pyright type errors in STAR's Python code so the CI type gate passes.
The gate counts errors per file and rule; these file/rule pairs now have more errors than scripts/pyright_baseline.json
allows, so at least the listed number in each must go. Errors, each with the real code around it (line numbers on
the left, do not copy them):
{errors}
{feedback}
Fix the cause the way the type checker intends (narrow an Optional with an explicit check, correct a wrong
annotation or call, give a variable one type). Keep behaviour the same. Never add "# type: ignore" or
"# pyright: ignore", never edit the baseline. Answer only JSON: {{"why": "<one sentence>", "edits": [{{"file":
"<path>", "find": "<exact existing text, unique in the file>", "replace": "<new text>"}}]}}"""


def bare_python(python: str) -> str:
    """A venv without packages (made once): with the owner's packages installed, library stubs change the counts."""
    exe = BARE / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not exe.is_file():
        sh([python, "-m", "venv", "--without-pip", str(BARE)], timeout=300)
    return str(exe) if exe.is_file() else python


def run_pyright(tree: Path, python: str) -> list[dict] | None:
    """Pyright's errors as CI computes them ({file, line, rule, message}, repo-relative), or None when it cannot run."""
    npx = shutil.which("npx")
    if not npx:
        return None
    r = sh([npx, *PYRIGHT, "--pythonpath", bare_python(python), "--outputjson"], cwd=tree, timeout=900)
    try:
        report = json.loads(r.stdout)
    except ValueError:
        return None
    out = []
    for d in report.get("generalDiagnostics", []):
        if d.get("severity") != "error":
            continue
        try:
            path = Path(d["file"]).resolve().relative_to(tree.resolve()).as_posix()
        except ValueError:
            path = str(d["file"]).replace("\\", "/")
        out.append({"file": path, "line": d["range"]["start"]["line"] + 1, "rule": d.get("rule") or "unknown",
                    "message": str(d.get("message", "")).splitlines()[0]})
    return out


def type_excess(tree: Path, errors: list[dict]) -> dict[str, tuple[int, int]]:
    """file::rule -> (allowed, now) for every pair above the baseline: the same rule as scripts/pyright_baseline.py."""
    f = tree / "scripts" / "pyright_baseline.json"
    allowed = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    now: dict[str, int] = {}
    for e in errors:
        key = f"{e['file']}::{e['rule']}"
        now[key] = now.get(key, 0) + 1
    return {k: (allowed.get(k, 0), n) for k, n in sorted(now.items()) if n > allowed.get(k, 0)}


def related_tests(tree: Path, files: list[str], limit: int = 6) -> list[str]:
    """Test files that import a changed module: a type fix must not change what the code does."""
    mods = {f[:-3].replace("/", ".") for f in files if f.endswith(".py")}
    out = []
    for t in sorted((tree / "tests").glob("test_*.py")) if (tree / "tests").is_dir() else []:
        text = t.read_text(encoding="utf-8", errors="replace")
        if any(re.search(rf"\b(from|import) {re.escape(m)}\b", text) for m in mods):
            out.append(t.relative_to(tree).as_posix())
        if len(out) == limit:
            break
    return out


def fix_types(tree: Path, python: str, asker=ask, checker=run_pyright) -> tuple[bool, str, int]:
    """Up to ROUNDS rounds of her edits against the pyright baseline gate. A round must lower the errors above the
    baseline and add no ignore comment, else it is undone. Then the tests of every changed module must still pass.
    Round 0 = nothing to do here (pyright cannot run, or the gate passes locally)."""
    errors = checker(tree, python)
    if errors is None:
        return False, "pyright cannot run here (no npx)", 0
    excess = type_excess(tree, errors)
    if not excess:
        return False, "the pyright gate passes locally (CI-only type failure)", 0
    feedback, why, touched = "", "", set()
    for round_no in range(1, ROUNDS + 1):
        over = sum(n - a for a, n in excess.values())
        listing = []
        for e in [e for e in errors if f"{e['file']}::{e['rule']}" in excess][:12]:
            a, n = excess[f"{e['file']}::{e['rule']}"]
            lines = (tree / e["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
            near = "\n".join(f"{i + 1:5}: {lines[i]}" for i in range(max(0, e["line"] - 7), min(len(lines), e["line"] + 6)))
            listing.append(f"{e['file']}:{e['line']}: {e['message']} [{e['rule']}] ({n} in this file/rule, "
                           f"baseline allows {a})\n{near}")
        files = {e["file"] for e in errors if f"{e['file']}::{e['rule']}" in excess}
        before = {f: (tree / f).read_bytes() for f in files if (tree / f).is_file()}
        try:
            answer = json.loads(asker(TYPE_PROMPT.format(errors="\n\n".join(listing)[:7000], feedback=feedback)))
        except (ValueError, TypeError):
            feedback = "\nYour last answer was not valid JSON. Answer only the JSON object.\n"
            continue
        edits = answer.get("edits") if isinstance(answer.get("edits"), list) else []
        if any(IGNORE.search(str(e.get("replace", ""))) and not IGNORE.search(str(e.get("find", "")))
               for e in edits if isinstance(e, dict)):
            feedback = "\nYour edits added an ignore comment. That hides the error; fix its cause instead.\n"
            continue
        before.update({p: (tree / p).read_bytes() for e in edits if isinstance(e, dict)
                       for p in [str(e.get("file", "")).replace("\\", "/").lstrip("./")] if p and (tree / p).is_file()})
        problems = apply_edits(tree, edits)
        after = checker(tree, python) or []
        left = type_excess(tree, after)
        if sum(n - a for a, n in left.values()) < over:
            why, feedback, errors, excess = str(answer.get("why", why))[:300], "", after, left
            touched |= {f for f, data in before.items() if (tree / f).read_bytes() != data}
            if not excess:
                break
            continue
        for f, data in before.items():                     # no progress: undo this round
            (tree / f).write_bytes(data)
        feedback = ("\nYour previous edits did not reduce the new type errors. " + ("Problems: " + "; ".join(problems)
                    + ". " if problems else "") + "Try a different fix.\n")
    else:
        return False, why or "the new type errors remain", ROUNDS
    tests = related_tests(tree, sorted(touched))
    if tests:
        ok, out = run_tests(tree, tests, python)
        if not ok:
            failed = ", ".join(f["test"] for f in failures(out)) or out[-200:]
            return False, "the type fix changed behaviour, these tests fail now: " + failed, round_no
    return True, why, round_no


LOCK_TOOL = "installer/star-home/pin_requirements.py"
DEP_FILE = re.compile(r"^requirements[\w-]*\.(in|txt)$")


def fix_lock(tree: Path, python: str) -> tuple[bool, str]:
    """A dependency bump (Dependabot) edits the hashed lock by hand and breaks it: regenerate it with the project's
    own lock tool from the bumped requirements-home.in, then the installer tests must pass. No model involved."""
    r = sh([python, LOCK_TOOL], cwd=tree, timeout=1800)
    if r.returncode:
        return False, "the lock tool failed: " + (r.stdout + r.stderr)[-300:]
    ok, out = run_tests(tree, ["tests/test_home_installer.py"], python)
    if ok:
        return True, "requirements-home lock regenerated with " + LOCK_TOOL
    first = (failures(out, 1) or [{"section": out}])[0]["section"]
    return False, "regenerated lock still fails the installer tests (a test pins this choice; needs review): " + \
        " ".join(re.findall(r"(?m)^E\s+(.*)$", first)[:2])[:300]


def rerun_failed(sha: str, number: int | None = None) -> int:
    """Run the failed jobs of this commit again; returns how many workflow runs were restarted. When GitHub refuses
    every rerun ("cannot be retried", seen on a 4-day-old run), closing and reopening the PR starts a fresh CI run.
    There is one CI runner: RERUNS caps the reruns of a whole run, across workers (RerunSpent when it is used up)."""
    if not RERUNS.take():
        raise RerunSpent(f"#{number}: this run's CI rerun is already used")
    try:
        return _rerun(sha, number)
    except BaseException:
        RERUNS.give()
        raise


def _rerun(sha: str, number: int | None) -> int:
    checks = json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs"))["check_runs"]
    runs = {m.group(1) for c in checks if c.get("conclusion") == "failure"
            for m in [re.search(r"/runs/(\d+)/", c.get("details_url") or "")] if m}
    done = 0
    for run in runs:
        try:
            gh("run", "rerun", run, "--failed", "--repo", REPO)
            done += 1
        except RuntimeError:
            pass
    if runs and not done and number:
        try:
            gh("pr", "close", str(number), "--repo", REPO)
            gh("pr", "reopen", str(number), "--repo", REPO)
            done = 1
        except RuntimeError:
            pass
    if not done:                                   # nothing restarted: the runner is still free for another PR
        RERUNS.give()
    return done


CONFLICT = re.compile(r"^<<<<<<< [^\n]*\n.*?^>>>>>>> [^\n]*\n", re.M | re.S)
MERGE_PROMPT = """You are Litha, resolving a git merge conflict in {repo} so a pull request can merge into {base}.
Pull request: {title}
Between <<<<<<< and ||||||| is the PR's version; between ||||||| and ======= is the common ancestor both started from;
between ======= and >>>>>>> is the newest {base}. Compare each side with the ancestor to see what each one changed.
Keep BOTH sides' changes: the PR's change AND everything {base} added. Never drop a function, type, section, table row,
test or setting that either side added; when both changed the same line, combine them. What one side deleted on
purpose (present in the ancestor, gone on that side, untouched on the other) stays deleted.
File {path}, conflict {i} of {n} (with the lines around it, which stay as they are):
{context}
{feedback}Answer only JSON: {{"resolved": "<the exact text that replaces the whole conflict block, without markers>"}}"""
KEY = re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+|unsafe\s+|const\s+)*(fn|struct|enum|trait|mod|def|class)\s+(\w+)"
                 r"|^(#{1,6})\s+(.+?)\s*$|^\|\s*([^|]*?\S)\s*\|", re.M)


def keys(text: str) -> set[str]:
    """What a reader would miss if it vanished: declared names, markdown headings, first cells of table rows."""
    out = set()
    for m in KEY.finditer(text):
        if m.group(1):
            out.add(f"{m.group(1)} {m.group(2)}")
        elif m.group(3):
            out.add(f"heading {m.group(4)}")
        elif not set(m.group(5)) <= set("-: "):
            out.add(f"row {m.group(5)}")
    return out


def sides(block: str) -> tuple[str, str, str]:
    """(PR side, ancestor, base side) of one diff3 conflict block."""
    body = block.split("\n", 1)[1].rsplit(">>>>>>> ", 1)[0]
    head, theirs = body.split("\n=======\n", 1) if "\n=======\n" in body else body.split("=======\n", 1)
    ours, _, base = head.partition("\n|||||||")
    return ours, base.split("\n", 1)[1] if "\n" in base else "", theirs


def dropped(block: str, resolved: str) -> list[str]:
    """Names, headings and table rows that one side ADDED (not in the ancestor) but the resolution lost."""
    ours, base, theirs = sides(block)
    return sorted((keys(ours) | keys(theirs)) - keys(base) - keys(resolved))


EDITION = re.compile(r'^edition\s*=\s*"(\d{4})"', re.M)


def broken(tree: Path, path: str, text: str) -> str:
    """Why this merged file is not valid for its language ('' = fine). A checker only counts when the base branch's own
    copy of the file passes it (Studio's shaders use includes plain naga cannot read)."""
    if "<<<<<<<" in text or ">>>>>>>" in text:
        return "conflict markers left"
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "py":
        try:
            compile(text, path, "exec")
        except SyntaxError as e:
            return f"does not compile (line {e.lineno}: {e.msg})"
        return ""
    if ext in ("toml", "json"):
        try:
            tomllib.loads(text) if ext == "toml" else json.loads(text)
        except ValueError as e:
            return f"invalid {ext}: {str(e)[:120]}"
        return ""
    tool = {"rs": "rustfmt", "wgsl": "naga"}.get(ext)
    exe = tool and (shutil.which(tool) or str(Path.home() / ".cargo" / "bin" / f"{tool}.exe"))
    if not exe or not Path(exe).exists():
        return ""

    def check(source: str) -> str:
        if tool == "rustfmt":
            cargo = (tree / "Cargo.toml").read_text(encoding="utf-8", errors="replace") if (tree / "Cargo.toml").exists() else ""
            edition = m.group(1) if (m := EDITION.search(cargo)) else "2021"
            r = subprocess.run([exe, "--edition", edition], input=source, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
        else:
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / Path(path).name
                f.write_text(source, encoding="utf-8")
                r = subprocess.run([exe, str(f)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=120)
        return "" if r.returncode == 0 else (r.stderr or r.stdout).strip()[:200]

    original = sh(["git", "show", f"origin/{BASE}:{path}"], cwd=tree)
    if original.returncode or check(original.stdout):
        return ""
    why = check(text)
    return f"{tool} rejects it: {why}" if why else ""


def tidy(tree: Path, path: str, text: str) -> str:
    """A merged Rust file in the repo's own format (Studio CI runs cargo fmt --check), but only when the base branch's
    copy is already exactly what rustfmt makes of it: then formatting changes nothing but her merged lines."""
    exe = shutil.which("rustfmt") or str(Path.home() / ".cargo" / "bin" / "rustfmt.exe")
    if not path.endswith(".rs") or not Path(exe).exists():
        return text
    cargo = (tree / "Cargo.toml").read_text(encoding="utf-8", errors="replace") if (tree / "Cargo.toml").exists() else ""
    edition = m.group(1) if (m := EDITION.search(cargo)) else "2021"

    def fmt(source: str) -> str | None:
        r = subprocess.run([exe, "--edition", edition], input=source, capture_output=True, text=True, cwd=tree,
                           encoding="utf-8", errors="replace", timeout=120)
        return r.stdout if r.returncode == 0 else None

    original = sh(["git", "show", f"origin/{BASE}:{path}"], cwd=tree)
    if original.returncode or fmt(original.stdout) != original.stdout:
        return text
    return fmt(text) or text


BRACKETED = re.compile(r"\.(rs|py|ts|tsx|js|jsx|wgsl|cs|java|kt|go|c|h|cc|cpp|hpp|json|lua|luau)$")


def balance(text: str) -> tuple[int, int, int]:
    return text.count("{") - text.count("}"), text.count("(") - text.count(")"), text.count("[") - text.count("]")


def slips(path: str, block: str, new: str, before: str = "", after: str = "") -> str:
    r"""Mistakes a merge of two sides never needs: the line just outside the block repeated inside it (seen: a doubled
    `data:BootData` field in #853), brackets that no longer balance the way BOTH sides do (seen: a lost closing brace
    of an impl), and escape sequences turned into real characters (seen: a Rust \n became a line break)."""
    ours, _, theirs = sides(block)
    lines = [ln for ln in new.splitlines() if ln.strip()]
    edge = [(lines[:1], before.rstrip("\n").rsplit("\n", 1)[-1], "before"),
            (lines[-1:], after.lstrip("\n").split("\n", 1)[0], "after")]
    for got, outside, where in edge:
        if got and outside.strip() and got[0].strip() == outside.strip() and outside.strip() not in \
                {ln.strip() for ln in (ours + "\n" + theirs).splitlines()}:
            return (f"Your text repeats the line just {where} the conflict ({outside.strip()[:80]}), which stays in "
                    "the file anyway. Give only what replaces the lines between the markers.\n")
    if BRACKETED.search(path) and balance(ours) == balance(theirs) != balance(new):
        return ("Your text does not open and close {}, () and [] the way both sides do (each side: "
                f"{balance(ours)}, yours: {balance(new)}). Keep every bracket the sides have.\n")
    if new.count("\\") < min(ours.count("\\"), theirs.count("\\")):
        return (r"You turned escape sequences such as \n into real characters. Inside the JSON string write a "
                r"backslash as \\ so the code keeps \n, \t and \" exactly as the sides have them." "\n")
    return ""


WINDOW = 4096                       # litha-fast's context (prompt + answer); ~3.5 characters per token for code


def adjacent(ours: str, base: str, theirs: str) -> str | None:
    """Git calls edits that touch neighbouring lines a conflict. When one side only ADDED lines before and/or after the
    untouched ancestor and the other side changed the ancestor, the merge is mechanical: the additions around the
    changed text (seen: #317, one `pub use` line added above a rewritten import list). None when it is not that case."""
    ours, base, theirs = (s if s.endswith("\n") or not s else s + "\n" for s in (ours, base, theirs))
    b = base.splitlines(keepends=True)                  # (sides() may drop a part's last newline)
    if not b:
        return None
    for adder, changer in ((theirs, ours), (ours, theirs)):
        a, c = adder.splitlines(keepends=True), changer.splitlines(keepends=True)
        starts = [i for i in range(len(a) - len(b) + 1) if a[i:i + len(b)] == b]
        if len(starts) == 1 and len(a) > len(b) and c != b and base not in changer:
            i = starts[0]
            body = "".join(c)
            return "".join(a[:i]) + (body if body.endswith("\n") or not body else body + "\n") + "".join(a[i + len(b):])
    return None


def both_added(ours: str, base: str, theirs: str, docs: bool) -> str | None:
    """Both sides kept every ancestor line and only inserted lines: each insertion goes in at its own place. Two
    insertions at the same place are only joined in prose (docs); in code their order may matter, so None."""
    import difflib
    b = (base if base.endswith("\n") or not base else base + "\n").splitlines(keepends=True)
    if not b:
        return None
    gaps: list[dict[int, list[str]]] = []
    for side in (ours, theirs):
        s = (side if side.endswith("\n") or not side else side + "\n").splitlines(keepends=True)
        ins: dict[int, list[str]] = {}
        for op, i1, _i2, j1, j2 in difflib.SequenceMatcher(None, b, s, autojunk=False).get_opcodes():
            if op == "insert":
                ins[i1] = s[j1:j2]
            elif op != "equal":
                return None                           # an ancestor line changed or went away: not pure additions
        gaps.append(ins)
    if not gaps[0] or not gaps[1] or (set(gaps[0]) & set(gaps[1]) and not docs):
        return None
    out = []
    for i in range(len(b) + 1):
        out += gaps[0].get(i, []) + gaps[1].get(i, [])
        out += b[i:i + 1]
    return "".join(out)


def resolve_text(path: str, text: str, title: str, asker=ask, hint: str = "") -> tuple[str | None, str]:
    """Every conflict block of one file resolved by her; (None, why) when she cannot make valid code of it. A hint is a
    checker's complaint about her previous attempt at this file."""
    blocks = list(CONFLICT.finditer(text))
    if not blocks or len(blocks) > 8:
        return None, f"{path}: {len(blocks)} conflict blocks (1-8 handled)"
    out, last, feedback = [], 0, hint
    for i, m in enumerate(blocks, 1):
        before = text[max(0, m.start() - 1500):m.start()].split("\n", 1)[-1]
        after = text[m.end():m.end() + 1500].rsplit("\n", 1)[0]
        ours, base, theirs = sides(m.group(0))
        union = ours.rstrip("\n") + "\n" + theirs if ours.strip() and theirs.strip() else ""
        if not hint and "\n|||||||" in m.group(0) and not base.strip() and union \
                and not slips(path, m.group(0), union, before, after):
            out += [text[last:m.start()], union]       # both sides only ADDED here: keep both, exactly as written
            last = m.end()
            continue
        near = adjacent(ours, base, theirs) if not hint and "\n|||||||" in m.group(0) else None
        if near is None and not hint and "\n|||||||" in m.group(0):
            near = both_added(ours, base, theirs, docs=path.endswith((".md", ".txt", ".rst")))
        if near is not None and not slips(path, m.group(0), near, before, after):
            out += [text[last:m.start()], near]        # one side only added next to what the other changed
            last = m.end()
            continue
        need = (len(MERGE_PROMPT) + len(before) + len(m.group(0)) + len(after) + len(ours) + len(theirs)) / 3.5
        if need > WINDOW:                              # it cannot fit her model's context: say so, do not burn tries
            return None, f"{path}: conflict {i} is too big for her {WINDOW}-token window (~{need:.0f} tokens)"
        for _ in range(3):
            try:
                ans = json.loads(asker(MERGE_PROMPT.format(repo=REPO, base=BASE, title=title, path=path, i=i,
                                                           n=len(blocks), feedback=feedback,
                                                           context=before + m.group(0) + after)))
                new = str(ans["resolved"])
            except (ValueError, TypeError, KeyError):
                feedback = "Your last answer was not valid JSON with a \"resolved\" string.\n"
                continue
            if "<<<<<<<" in new or ">>>>>>>" in new or "\n=======\n" in f"\n{new}\n" or "\n|||||||" in f"\n{new}":
                feedback = "Your answer still had conflict markers. Give the merged text only.\n"
                continue
            lost = dropped(m.group(0), new)
            if lost:
                feedback = ("Your last answer dropped what one side added: " + "; ".join(lost[:8]) +
                            ". Keep everything both sides added.\n")
                continue
            feedback = slips(path, m.group(0), new, before, after)
            if feedback:
                continue
            break
        else:
            return None, f"{path}: no usable answer for conflict {i} (last check: {feedback.strip()[:160]})"
        out += [text[last:m.start()], new if new.endswith("\n") or not new else new + "\n"]
        last, feedback = m.end(), hint
    return "".join(out) + text[last:], ""


def resolve(pr: dict, python: str, dry: bool = False, asker=ask) -> dict:
    """A PR that conflicts with star/next: merge star/next into a copy of it on HER branch, resolve (lock files are
    taken from star/next and rebuilt; code conflicts are hers), prove nothing broke, open her own PR."""
    number = pr["number"]
    day = dt.date.today().strftime("%Y%m%d")
    branch, tree = f"litha/merge-{number}-{day}-{dt.datetime.now():%H%M}", WORK / f"litha-merge-{number}"
    if tree.exists():
        sh(["git", "-C", str(CLONE), "worktree", "remove", "--force", str(tree)])
    sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", BASE])
    got = sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", f"pull/{number}/head:{branch}", "--force"])
    if got.returncode:
        return {"pr": number, "result": "skip", "why": "fetch failed: " + got.stderr[-200:]}
    sh(["git", "-C", str(CLONE), "worktree", "add", "-q", str(tree), branch])
    m = sh(["git", *IDENTITY, "-c", "merge.conflictStyle=diff3",          # per-command identity, never configured
            "merge", "--no-ff", "--no-commit", f"origin/{BASE}"], cwd=tree)
    conflicted = sh(["git", "diff", "--name-only", "--diff-filter=U"], cwd=tree).stdout.split()
    if m.returncode and not conflicted:
        return {"pr": number, "result": "failed", "why": "git merge failed: " + (m.stdout + m.stderr)[-200:]}
    locks = [c for c in conflicted if (DEP_FILE.match(c) and c.endswith(".txt")) or c.endswith("Cargo.lock")]
    code = [c for c in conflicted if c not in locks]
    if len(code) > 5 or any(NO_TOUCH.search(c) and not DEP_FILE.match(c) for c in code):
        sh(["git", "merge", "--abort"], cwd=tree)
        return {"pr": number, "result": "failed", "why": f"conflicts she does not resolve alone: {code[:8]}"}
    for c in locks:                                         # generated files: star/next's copy, rebuilt below
        sh(["git", "checkout", "--theirs", "--", c], cwd=tree)
    tests: set[str] = set()
    raws: dict[str, str] = {}                          # each file with its conflict markers, to redo a merge
    for c in code:
        raw = raws[c] = (tree / c).read_text(encoding="utf-8", errors="replace")
        merged, why = resolve_text(c, raw, pr.get("title", ""), asker)
        why = why or broken(tree, c, merged or "")
        if merged is not None and why:                     # one more try at the file, told what the checker said
            merged, why = resolve_text(c, raw, pr.get("title", ""), asker,
                                       hint=f"Your previous merge of this file was rejected: {why[:400]}\n")
            why = why or broken(tree, c, merged or "")
        if merged is None or why:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {"pr": number, "result": "failed", "why": why if why.startswith(c) else f"{c}: {why}"}
        (tree / c).write_bytes(tidy(tree, c, merged).encode("utf-8"))
        if c.startswith("tests/") and c.endswith(".py"):
            tests.add(c)
        elif c.endswith(".py"):
            from litha.bug_bench import tests_for
            tests.update(tests_for(c[:-3].replace("/", "."), tree / "tests", {})[:3])
    if locks and (tree / LOCK_TOOL).is_file():
        r = sh([python, LOCK_TOOL], cwd=tree, timeout=1800)
        if r.returncode:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {"pr": number, "result": "failed", "why": "lock tool failed: " + (r.stdout + r.stderr)[-200:]}
        tests.add("tests/test_home_installer.py")
    if any(c.endswith("Cargo.lock") for c in locks):            # the base's lock, updated for the PR's manifests
        cargo = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo.exe")
        r = sh([cargo, "metadata", "--format-version", "1", "--offline"], cwd=tree, timeout=900)
        if r.returncode:
            r = sh([cargo, "metadata", "--format-version", "1"], cwd=tree, timeout=900)
        if r.returncode:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {"pr": number, "result": "failed", "why": "Cargo.lock refresh failed: " + r.stderr[-200:]}
    sh(["git", "add", "--", *conflicted], cwd=tree)
    left = sh(["git", "diff", "--cached", "--check", "--", *conflicted], cwd=tree).stdout
    if "conflict marker" in left:                         # (whitespace both sides already had is not hers to judge)
        sh(["git", "merge", "--abort"], cwd=tree)
        return {"pr": number, "result": "failed", "why": "leftover conflict markers: " + left[:200]}
    ok, out = run_tests(tree, sorted(tests)[:6], python) if tests else (True, "")
    row = {"pr": number, "result": "fixed" if ok else "failed", "kind": "merge", "files": conflicted,
           "tests": sorted(tests)[:6], "why": f"merged {BASE} and resolved " + ", ".join(conflicted)}
    if CLONE != HOME_CLONE:
        row["repo"] = REPO
    if not ok:
        sh(["git", "merge", "--abort"], cwd=tree)
        return {**row, "why": "after resolving, tests fail: " + " ".join(FAILED.findall(out))[:250]}
    if (tree / "Cargo.toml").is_file() and any(c.endswith(".rs") for c in code):
        ok, fails, crates, out = rust_fix.crate_tests(tree, code)
        mine = sorted({e["file"] for e in rust_fix.errors(out)} & set(code)) if not ok else []
        for c in mine:                                 # the errors are in a file she merged: redo that merge first,
            said = "; ".join(f"line {e['line']}: {e['error']}" for e in rust_fix.errors(out) if e["file"] == c)
            merged, why = resolve_text(c, raws[c], pr.get("title", ""), asker,   # told what the compiler said
                                       hint=f"After your merge of this file the compiler said: {said[:600]}\n")
            if merged is not None and not (why or broken(tree, c, merged)):
                (tree / c).write_bytes(tidy(tree, c, merged).encode("utf-8"))
        if mine:
            sh(["git", "add", "--", *mine], cwd=tree)
            ok, fails, crates, out = rust_fix.crate_tests(tree, code)
            if ok:
                row["why"] += f"; redid {', '.join(mine)} after the compiler's errors"
        if not ok and rust_fix.errors(out):            # it does not compile (one side renamed what the other uses):
            fixed, how = rust_fix.repair(tree, REPO, pr.get("title", ""),   # her repair, then the tests again
                                         f"Run cargo test -p {' -p '.join(crates)}\n{out}", asker)
            if fixed:
                sh(["git", "add", "-u"], cwd=tree)
                ok, fails, crates, out = rust_fix.crate_tests(tree, code)
                row["why"] += f"; fixed the merged build: {how[:200]}"
        row["tests"] += [f"cargo test -p {' -p '.join(crates)}"]
        if not ok:
            sh(["git", "merge", "--abort"], cwd=tree)
            why = f"after resolving, cargo tests fail: {fails}"
            if not dry:                                   # the authors decide which behaviour is right
                try:
                    gh("pr", "comment", str(number), "--repo", REPO, "--body",
                       f"Litha tried to merge {BASE} into this PR. The conflicts resolve and compile, but then "
                       f"`cargo test -p {' -p '.join(crates)}` fails:\n\n{fails[:1200]}\n\nThe two sides probably "
                       "change the same behaviour in different ways; this PR needs a decision on which one is "
                       "right before it can merge. She did not push anything.")
                except RuntimeError:
                    pass
            return {**row, "result": "failed", "why": why[:400]}
    if dry:
        return row
    msg = f"[litha] merge {BASE} into #{number}: {', '.join(conflicted)}"
    if CLONE == HOME_CLONE:                               # STAR's repo: star commit runs the secret and path checks
        c = sh([str(CLONE.parent / "star.cmd"), "commit", "--owner", "claude", "--worktree",
                str(tree.relative_to(CLONE.parent)), "-m", msg], cwd=CLONE.parent)
    else:                                                 # a merge commit of two sides already on GitHub
        c = sh(["git", *IDENTITY, "commit", "-q", "--no-verify", "-m", msg], cwd=tree)
    if c.returncode:
        return {**row, "result": "failed", "why": "commit refused: " + (c.stdout + c.stderr)[-300:]}
    if sh(["git", "push", "-q", "-u", "origin", branch], cwd=tree).returncode:
        return {**row, "result": "failed", "why": "push failed"}
    body = (f"Litha brought #{number} up to date with {BASE} (her own branch; the original PR is unchanged).\n\n"
            f"Conflicts resolved: {', '.join(conflicted)}. Lock files were taken from {BASE} and rebuilt.\n"
            f"Checks before pushing: nothing either side added was dropped, every file parses, "
            f"tests run: {', '.join(row['tests']) or 'none touched (CI runs the full suite)'}.\n"
            f"Contains #{number}'s commits plus the merge; merging this lands both.")
    try:
        row["fix_pr"] = gh("pr", "create", "--repo", REPO, "--base", BASE, "--head", branch,
                           "--title", f"[litha] up to date: #{number} {pr.get('title', '')[:60]}", "--body", body).strip()
        gh("pr", "comment", str(number), "--repo", REPO, "--body", f"Litha resolved the conflicts in {row['fix_pr']}")
    except RuntimeError as e:
        row["why"] += f" (PR create: {str(e)[:150]})"
    return row


def fix(pr: dict, python: str, dry: bool = False, asker=ask, found: dict | None = None) -> dict:
    """found = a bug her merger hunt PROVED in this PR ({file, line, why, test}): her proof test is the failing test,
    and it ships with the fix as a regression test."""
    sha, number = pr["headRefOid"], pr["number"]
    log = "" if found else failed_logs(sha)
    fails = failures(log)
    if not found and not log.strip():     # logs expire on GitHub: run the failed jobs again, look next time
        n = rerun_failed(sha, number)                     # nothing restarted: not a rerun, or it loops every run
        return {"pr": number, "result": "rerun" if n else "skip",
                "why": f"failed logs expired; reran {n} run(s)" + ("" if n else "; nothing could be restarted")}
    linting = not fails and bool(RUFF_CI.search(log))
    typing = None if found or fails or linting else TYPE_CI.search(log)   # fails the same every run: fix, no rerun
    ci_types = ("new pyright errors: " + " | ".join(re.findall(r"\S+\.py:\d+: [^\n]*", typing.group(1)))[:300]
                if typing else "")
    if not found and not fails and not linting and not typing:   # timeout, lost runner, setup (seen: #700 died after 9 h): one rerun
        return {"pr": number, "result": "flaky-rerun",
                "why": f"no test or lint failure in the failed logs; reran {rerun_failed(sha, number)} failed run(s) once"}
    day = dt.date.today().strftime("%Y%m%d")
    branch, tree = f"litha/fix-{number}-{day}", WORK / f"litha-fix-{number}"
    if tree.exists():
        sh(["git", "-C", str(CLONE), "worktree", "remove", "--force", str(tree)])
    got = sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", f"pull/{number}/head:{branch}", "--force"])
    if got.returncode:
        return {"pr": number, "result": "skip", "why": "fetch failed: " + got.stderr[-200:]}
    sh(["git", "-C", str(CLONE), "worktree", "add", "-q", str(tree), branch])
    tests = sorted({f["test"].split("::")[0] for f in fails})     # whole files: a second bug must fail too
    if found:
        tests = [f"tests/test_litha_found_{number}.py"]
        (tree / tests[0]).write_bytes(str(found["test"]).encode("utf-8"))
        ok, out = run_tests(tree, tests, python)
        if ok:
            return {"pr": number, "result": "skip", "why": "her proof test no longer fails on this head"}
        fails = failures(out) or [{"test": tests[0], "section": out[-2500:]}]
    elif fails:
        ok, out = run_tests(tree, tests, python)
        if ok:                            # flaky or CI-only (seen: a 0.6 s timing limit missed by 8 ms): one rerun
            return {"pr": number, "result": "flaky-rerun", "tests": tests,
                    "why": f"the failing tests pass locally; reran {rerun_failed(sha, number)} failed run(s) once"}
    if str(pr.get("headRefName", "")).startswith("litha/"):
        return {"pr": number, "result": "skip", "why": "her own fix branch fails for real: no fix on top of a fix"}
    names = gh("pr", "diff", str(number), "--repo", REPO, "--name-only", timeout=300).split()
    if not found and names and all(DEP_FILE.match(n) for n in names) and (tree / LOCK_TOOL).is_file():
        ok, why = fix_lock(tree, python)
        round_no, tests = 1, ["tests/test_home_installer.py"]
    elif linting:
        ok, why, round_no = fix_lint(tree, python, asker)
        if round_no == 0:
            return {"pr": number, "result": "skip", "why": why}
        tests = ["ruff check star"]
    elif typing:
        ok, why, round_no = fix_types(tree, python, asker)
        if round_no == 0:                                   # cannot check it here: report what CI said
            return {"pr": number, "result": "failed", "kind": "types", "why": f"{ci_types} ({why})"}
        tests = ["pyright baseline gate"]
    else:
        diff = gh("pr", "diff", str(number), "--repo", REPO, timeout=300)
        ok, why, round_no = repair(tree, pr.get("title", ""), fails, out, tests, python, asker, diff)
    if not ok:
        return {"pr": number, "result": "failed", "rounds": ROUNDS, "tests": tests, "why": why}
    changed = [ln[3:] for ln in sh(["git", "status", "--porcelain"], cwd=tree).stdout.splitlines()]
    row = {"pr": number, "result": "fixed", "round": round_no, "why": why, "tests": tests, "files": changed}
    if dry:
        return row
    msg = f"[litha] fix #{number}: {why}\n\nFailing tests now pass locally: {', '.join(tests)}"
    c = sh([str(CLONE.parent / "star.cmd"), "commit", "--owner", "claude", "--worktree", str(tree.relative_to(CLONE.parent)),
            "--paths", *changed, "-m", msg], cwd=CLONE.parent)
    if c.returncode:
        return {**row, "result": "failed", "why": "commit refused: " + (c.stdout + c.stderr)[-300:]}
    p = sh(["git", "push", "-q", "-u", "origin", branch], cwd=tree)
    if p.returncode:
        return {**row, "result": "failed", "why": "push failed: " + p.stderr[-200:]}
    seen = (f"Her review found and PROVED a bug at {found['file']}:{found['line']}: {found['why']}\nHer proof test is "
            f"added as {tests[0]} (fails before this fix, passes after).\n") if found else ""
    body = (f"Litha's fix for #{number} (her own branch; the original PR is unchanged).\n\n{seen}Cause: {why}\n"
            f"Failing tests now pass locally: {', '.join(tests)} (and their whole files).\n"
            f"Contains #{number}'s commits plus her fix; merging this lands both.")
    try:
        row["fix_pr"] = gh("pr", "create", "--repo", REPO, "--base", BASE, "--head", branch,
                           "--title", f"[litha] fix #{number}: {pr.get('title', '')[:60]}", "--body", body).strip()
        gh("pr", "comment", str(number), "--repo", REPO, "--body", f"Litha made a fix for this PR: {row['fix_pr']}")
    except RuntimeError as e:
        row["why"] += f" (PR create: {str(e)[:150]})"
    return row


def fix_rust(pr: dict, log: str, dry: bool = False, asker=ask) -> dict:
    """A Rust PR (other repos) whose CI failed to build/lint/format: her fix on top of it, proven by the same cargo
    checks locally. Her own litha/ PR gets the commit directly; anyone else's gets her PR litha/fix-<n>-..."""
    number, head = pr["number"], str(pr.get("headRefName", ""))
    own = head.startswith("litha/")
    branch = head if own else f"litha/fix-{number}-{dt.date.today():%Y%m%d}-{dt.datetime.now():%H%M}"
    tree = WORK / f"litha-fix-{number}"
    if tree.exists():
        sh(["git", "-C", str(CLONE), "worktree", "remove", "--force", str(tree)])
    local = f"litha-work/fix-{number}"
    got = sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", f"pull/{number}/head:{local}", "--force"])
    if got.returncode:
        return {"pr": number, "result": "skip", "why": "fetch failed: " + got.stderr[-200:]}
    sh(["git", "-C", str(CLONE), "worktree", "add", "-q", str(tree), local])
    ok, why = rust_fix.repair(tree, REPO, pr.get("title", ""), log, asker)
    row = {"pr": number, "result": "fixed" if ok else "failed", "kind": "rust", "why": why}
    if not ok or dry:
        return row
    changed = sh(["git", "status", "--porcelain"], cwd=tree).stdout.split("\n")
    if not any(line.strip() for line in changed):
        return {**row, "result": "failed", "why": "the checks pass here without a change (CI-only failure?)"}
    sh(["git", "add", "-A"], cwd=tree)
    c = sh(["git", *IDENTITY, "commit", "-q", "--no-verify", "-m", f"[litha] fix #{number}: {why[:120]}"], cwd=tree)
    if c.returncode:
        return {**row, "result": "failed", "why": "commit failed: " + (c.stdout + c.stderr)[-200:]}
    if sh(["git", "push", "-q", "origin", f"HEAD:refs/heads/{branch}"], cwd=tree).returncode:
        return {**row, "result": "failed", "why": "push failed (no force-push; the branch moved?)"}
    if own:
        row["fix_pr"] = pr.get("url", f"#{number}")
        return row
    try:
        row["fix_pr"] = gh("pr", "create", "--repo", REPO, "--base", BASE, "--head", branch, "--title",
                           f"[litha] fix #{number}: {pr.get('title', '')[:60]}", "--body",
                           f"Litha fixed what broke CI on #{number} ({why}). Contains #{number}'s commits plus her fix; "
                           "merging this lands both.").strip()
        gh("pr", "comment", str(number), "--repo", REPO, "--body", f"Litha fixed the failing build in {row['fix_pr']}")
    except RuntimeError as e:
        row["why"] += f" (PR create: {str(e)[:150]})"
    return row


class RerunSpent(Exception):
    """This run's CI rerun is used: the PR is left untouched (not marked tried) for the next run."""


class Budget:
    """A count shared by all workers; None = no limit."""

    def __init__(self, left: int | None = None):
        self.left, self.lock = left, threading.Lock()

    def set(self, left: int | None) -> None:
        with self.lock:
            self.left = left

    def take(self) -> bool:
        with self.lock:
            if self.left is None:
                return True
            if self.left <= 0:
                return False
            self.left -= 1
            return True

    def give(self) -> None:
        with self.lock:
            if self.left is not None:
                self.left += 1


RERUNS = Budget()                    # main() sets 1 per run: one CI runner
LOGGED = threading.Lock()            # one fixes.jsonl row + its printed line at a time
WORKERS_AWAY, WORKERS_ACTIVE = 3, 1  # PRs at once: the owner away (no input for 10 min) / at the PC


def workers() -> int:
    return WORKERS_AWAY if rust_fix.away() else WORKERS_ACTIVE


def log_row(t: float, row: dict) -> None:
    line = json.dumps({"ts": round(t), **row})
    with LOGGED:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(json.dumps(row), flush=True)


def pool(items: list, work, n: int, limit: int) -> list[dict]:
    """work(item) on up to n threads, in the items' order. work returns None (not a candidate, or deferred) or
    (row, counts). An item starts only while counted + running < limit, so a run never counts more than `limit` PRs,
    as the serial loop did; with n=1 it IS the serial loop. Each item is taken once: no PR gets two workers."""
    todo, rows = iter(items), []
    cond = threading.Condition()
    state = {"counted": 0, "running": 0}

    def worker() -> None:
        while True:
            with cond:
                while state["counted"] + state["running"] >= limit and state["running"]:
                    cond.wait()
                item = next(todo, None) if state["counted"] < limit else None
                if item is None:
                    cond.notify_all()
                    return
                state["running"] += 1
            got = None
            try:
                got = work(item)
            except Exception as e:  # noqa: BLE001 - work logs its own errors; a worker must never hang the run
                print(f"worker error: {str(e)[:300]}", flush=True)
            finally:
                with cond:
                    state["running"] -= 1
                    if got is not None:
                        rows.append(got[0])
                        state["counted"] += bool(got[1])
                    cond.notify_all()

    threads = [threading.Thread(target=worker, name=f"litha-pr-{i}") for i in range(max(1, min(n, limit)))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    return rows


def others(python: str, limit: int, dry: bool = False, n: int = 1) -> int:
    """The owner's other repos with a local clone (repos.json "clone", mode merge): she resolves conflicting PRs on
    her own branch, and reruns a failed check once per head (flaky runners). Their CI and her merger's review decide.
    Up to n resolves / repairs of one repo run at once; cargo stays one build at a time (rust_fix.BUILD)."""
    global REPO, BASE, CLONE, WORK
    from litha import pr_merger
    lock = STATE.parent / "others.lock"           # cargo builds take minutes: never two runs in the same worktrees
    try:
        os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        if time.time() - lock.stat().st_mtime < 7200:
            print("another --others run is busy", flush=True)
            return 0
        lock.touch()                              # a run that died over 2 h ago: take over
    home = (REPO, BASE, CLONE, WORK, pr_merger.REPO, pr_merger.BASE)
    tried = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}

    def finish(repo: str, key: str, pr: dict, t: float, row: dict) -> None:
        row = {"repo": repo, **row, "seconds": round(time.time() - t)}
        if not dry:                               # a dry run must not use up the real attempt
            mark(key, pr["headRefOid"])
        log_row(t, row)

    def job(repo: str, key: str, pr: dict, fn, *args) -> None:
        t = time.time()
        try:
            row = fn(*args)
        except Exception as e:  # noqa: BLE001 - one PR must not stop the others
            row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
        finish(repo, key, pr, t, row)

    try:
        for entry in json.loads(pr_merger.REPOS.read_text(encoding="utf-8"))["repos"][1:]:
            if entry.get("mode") != "merge" or not entry.get("clone"):
                continue
            REPO = pr_merger.REPO = entry["repo"]
            BASE = pr_merger.BASE = entry.get("base", "main")
            CLONE = Path(entry["clone"]).expanduser()
            WORK = Path(entry.get("worktrees") or CLONE.parent / f"{CLONE.name}-worktrees").expanduser()
            most, builds = (limit * 2, 2) if rust_fix.away() else (limit, 1)   # owner away: twice the work per run
            if not (CLONE / ".git").exists():
                print(f"{REPO}: no clone at {CLONE}", flush=True)
                continue
            prs = open_prs()
            busy = {m.group(1) for p in prs for m in [re.match(r"litha/merge-(\d+)-", p.get("headRefName", ""))] if m}
            done = reruns = repairs = 0
            # the globals above stay fixed until every job of this repo is finished (the with-block waits)
            with ThreadPoolExecutor(max_workers=max(1, n), thread_name_prefix="litha-other") as ex:
                for pr in prs:
                    key = f"{REPO}#{pr['number']}"
                    if pr.get("isDraft") or pr.get("baseRefName") != BASE or tried.get(key) == pr["headRefOid"]:
                        continue
                    if pr.get("mergeable") == "CONFLICTING" and done < most and str(pr["number"]) not in busy \
                            and not str(pr.get("headRefName", "")).startswith("litha/"):
                        ex.submit(job, REPO, key, pr, resolve, pr, python, dry)
                        done += 1
                    elif pr.get("mergeable") == "MERGEABLE" and (reruns < 3 or repairs < builds):
                        checks = head_checks(pr["headRefOid"])
                        if not any(c["conclusion"] == "FAILURE" for c in checks) or \
                                any(c["status"] != "completed" for c in checks):
                            continue
                        t = time.time()
                        log = failed_logs(pr["headRefOid"])
                        if rust_fix.checks(log) and (rust_fix.errors(log) or "Diff in " in log):
                            if repairs >= builds:             # 1 build per repo per run (2 at night): cargo is slow
                                continue
                            ex.submit(job, REPO, key, pr, fix_rust, pr, log, dry)
                            repairs += 1
                        elif reruns < 3:
                            finish(REPO, key, pr, t, {
                                "pr": pr["number"], "result": "flaky-rerun",
                                "why": f"reran {0 if dry else rerun_failed(pr['headRefOid'], pr['number'])} failed "
                                       "run(s) once for this head"})
                            reruns += 1
    finally:
        REPO, BASE, CLONE, WORK, pr_merger.REPO, pr_merger.BASE = home
        lock.unlink(missing_ok=True)
    return 0


COUNTED = ("fixed", "failed", "error", "rerun", "flaky-rerun")   # a skip does not use up a PR of the run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.pr_fixer")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--max", type=int, help="PRs to work on per run (default: one per worker)")
    ap.add_argument("--workers", type=int, help="PRs at the same time (default: 3 when the owner is away, else 1)")
    ap.add_argument("--dry", action="store_true", help="fix and test locally, do not commit or push")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--others", type=int, metavar="N", help="instead: resolve up to N conflicting PRs per other repo")
    a = ap.parse_args(argv)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, a.workers or workers())
    if a.others is not None:
        return others(a.python, a.others, a.dry, n)
    most = a.max if a.max is not None else n
    tried = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    from litha.pr_merger import HUNTED
    hunted = json.loads(HUNTED.read_text(encoding="utf-8")) if HUNTED.exists() else {}
    hunt_lock = threading.Lock()
    prs, jobs = open_prs(a.pr), []
    for pr in prs:                                      # first: bugs her review proved -> her fix with her test
        item = hunted.get(str(pr["number"]))
        if item and item.get("head") == pr["headRefOid"] and item.get("test"):
            jobs.append((pr, item))
        elif item:                                      # stale proof (head moved): dropped, as before
            hunted.pop(str(pr["number"]))
    first = {pr["number"] for pr, _ in jobs}
    jobs += [(pr, None) for pr in prs if pr["number"] not in first]     # each PR once: never two workers on one PR

    def work(job: tuple) -> tuple[dict, bool] | None:
        pr, item = job
        t = time.time()
        if item:
            try:
                row = fix(pr, a.python, a.dry, found=item)
            except Exception as e:  # noqa: BLE001 - one PR must not stop the others
                row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
            row["seconds"], row["kind"] = round(time.time() - t), "hunted"
            with hunt_lock:
                hunted.pop(str(pr["number"]), None)
                write_atomic(HUNTED, json.dumps(hunted))
            log_row(t, row)
            return row, True
        if pr.get("isDraft") or pr.get("baseRefName") != BASE or tried.get(str(pr["number"])) == pr["headRefOid"]:
            return None
        if pr.get("mergeable") == "CONFLICTING" and not str(pr.get("headRefName", "")).startswith("litha/"):
            try:
                row = resolve(pr, a.python, a.dry)
            except Exception as e:  # noqa: BLE001 - one PR must not stop the others
                row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
            row["seconds"] = round(time.time() - t)
            mark(str(pr["number"]), pr["headRefOid"])
            log_row(t, row)
            return row, True
        if pr.get("mergeable") != "MERGEABLE":                 # her own branches too: flaky reruns
            return None
        checks = head_checks(pr["headRefOid"])
        if not any(c["conclusion"] == "FAILURE" for c in checks) or any(c["status"] != "completed" for c in checks):
            return None
        t = time.time()
        try:
            row = fix(pr, a.python, a.dry)
        except RerunSpent as e:           # another worker used the run's one CI rerun: next run, untouched
            print(json.dumps({"pr": pr["number"], "result": "deferred", "why": str(e)}), flush=True)
            return None
        except Exception as e:  # noqa: BLE001 - one PR must not stop the others
            row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
        row["seconds"] = round(time.time() - t)
        if row["result"] != "rerun":      # a rerun is looked at again once its fresh log exists
            mark(str(pr["number"]), pr["headRefOid"])
        log_row(t, row)
        return row, row["result"] in COUNTED

    RERUNS.set(1)                         # one CI runner: one rerun per run, whatever the number of workers
    try:
        pool(jobs, work, n, most)
    finally:
        RERUNS.set(None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
