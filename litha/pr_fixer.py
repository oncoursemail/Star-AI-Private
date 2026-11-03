"""Litha fixes failing PRs herself: failed CI log -> her patch -> the failing tests rerun locally -> her own PR.

For an open, non-draft PR into star/next whose Python checks failed on the head commit:
1. read the failed job log, take the pytest failures (test id + its traceback section);
2. check the PR out on her own branch litha/fix-<pr>-<yyyymmdd> in a throwaway worktree;
3. Litha gets the tracebacks + the real code around every frame and answers search/replace edits;
4. her code is packed into her window by litha/context_pack.py (section 4i); a `find` that is not in the file
   exactly is landed whitespace-tolerant or by a unique fuzzy match, else re-asked once; edits that touch tests /
   CI / locks, or still name no single place, are refused and she is told why;
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
import difflib
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

from litha import build_check, claude, context_pack, fresh_py, merge3, rust_fix, self_map
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
FRONT_SPEC = re.compile(r"^frontend/(.*\.test\.[cm]?[jt]sx?|src/test-[^/]+\.ts|tsconfig[^/]*\.json|vite\.config\.\w+|"
                        r"vitest\.config\.\w+|package(-lock)?\.json)$")   # the React job's tests and its configs
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


def failed_logs(sha: str, every: bool = False) -> str:
    """The text of every failed check's job log on this commit (GitHub Actions jobs only): the newest run of each
    check, or every run (every=True: did this base commit's own CI ever fail a test)."""
    data = json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"))
    out = []
    runs = data.get("check_runs", [])
    for c in runs if every else latest_runs(runs):
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


def apply_edits(tree: Path, edits: list, misses: list | None = None) -> list[str]:
    """Apply search/replace edits; returns the problems (an edit with a problem is not applied). A `find` that is
    not in the file exactly is landed whitespace-tolerant or by a unique fuzzy match (context_pack.land); one that
    still names no single place goes to `misses` (for one re-ask). Every refusal is noted with its reason."""
    problems = []
    for index, e in enumerate(edits if isinstance(edits, list) else []):
        try:
            path, find, new = str(e["file"]).replace("\\", "/").lstrip("./"), str(e["find"]), str(e["replace"])
        except (KeyError, TypeError):
            problems.append("an edit lacked file/find/replace")
            context_pack.note_reject("", "", problems[-1])
            continue
        f = (tree / path).resolve()
        if NO_TOUCH.search(path) or GATES.match(path) or FRONT_SPEC.match(path) or tree.resolve() not in f.parents:
            problems.append(f"{path}: you may not edit this file (tests, CI and locks are the spec)")
            context_pack.note_reject(path, find, problems[-1])
            continue
        if not f.is_file():
            problems.append(f"{path}: no such file")
            context_pack.note_reject(path, find, problems[-1])
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(find) if find else 0
        if n != 1:
            got = context_pack.land(text, find, new, e.get("line"))
            if isinstance(got, str):
                problems.append(f"{path}: 'find' matched {n} times, it must match exactly once ({got})")
                context_pack.note_reject(path, find, got)
                if misses is not None:
                    misses.append({**e, "file": path, "index": index, "reason": got})
                continue
            start, end, new, _ = got
            f.write_bytes((text[:start] + new + text[end:]).encode("utf-8"))
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
    env = fresh_py.env(tree, APPDATA=tempfile.mkdtemp(prefix="litha-fix-"))
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


K = 1                                   # candidate edit sets per round, best one kept (LITHA_FIX_K overrides; 1 = off; 3 measured +2/32, 2.1x time)


def _edit_size(edits) -> int:
    """Lines an edit set removes + adds: the tie-break between candidates that leave as many failures."""
    n = 0
    for e in edits if isinstance(edits, list) else []:
        if isinstance(e, dict):
            old, new = str(e.get("find", "")).splitlines(), str(e.get("replace", "")).splitlines()
            n += sum(1 for ln in difflib.ndiff(old, new) if ln[:1] in "+-")
    return n


def _apply_saved(tree: Path, edits, saved: dict[Path, bytes], misses: list | None = None) -> list[str]:
    """apply_edits, first remembering the bytes of every file the edits name, so a candidate is undone exactly,
    also on a tree with uncommitted changes (`git checkout -- .` also erased the bench's planted bug)."""
    root = tree.resolve()
    for e in edits if isinstance(edits, list) else []:
        try:
            f = (tree / str(e["file"]).replace("\\", "/").lstrip("./")).resolve()
        except (KeyError, TypeError):
            continue
        if f not in saved and root in f.parents and f.is_file():
            saved[f] = f.read_bytes()
    return apply_edits(tree, edits, misses)


def _restore(tree: Path, saved: dict[Path, bytes], kept: list) -> None:
    """Back to the state repair() started from, plus the kept edits of earlier rounds."""
    for f, data in saved.items():
        f.write_bytes(data)
    for edits in kept:
        apply_edits(tree, edits)


BREAKS = ("F821", "F822", "F823")                            # undefined names (ruff also reports syntax errors)
ISSUE = re.compile(r"^\S+:\d+:\d+: (.*)$", re.M)              # ruff --output-format=concise


def _ruff(python: str, rel: str, data: bytes) -> list[str]:
    try:
        r = subprocess.run([python, "-m", "ruff", "check", "--isolated", "--no-cache", "--select", ",".join(BREAKS),
                            "--output-format=concise", "--stdin-filename", rel, "-"], input=data, capture_output=True,
                           timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return ISSUE.findall(r.stdout.decode("utf-8", errors="replace"))


def _new_breakage(tree: Path, saved: dict[Path, bytes], python: str) -> str:
    """An edit that adds an undefined name or a syntax error to a .py file (#905: `if "tests/" in tests:` at module
    level, where `tests` exists nowhere) is refused before any test runs; '' when none (or ruff is not there)."""
    root = tree.resolve()
    for f, data in saved.items():
        if f.suffix != ".py" or not f.is_file() or f.read_bytes() == data:
            continue
        rel = f.relative_to(root).as_posix() if root in f.parents else f.name
        old, new = _ruff(python, rel, data), _ruff(python, rel, f.read_bytes())
        added = [m for m in new if m not in old]
        if len(new) > len(old) and added:
            return f"{rel}: your edit broke the code: {added[0][:160]}"
    return ""


FLAKY = "flaky: "


def _passes_without(tree: Path, saved: dict[Path, bytes], tests: list[str], python: str) -> bool:
    """A passing fix is run once more on the code repair() started from: passing there too means the tests were
    flaky and her edits fixed nothing (#905: a no-op line in a file no failing test imports 'fixed' #903, whose
    first run had read stale bytecode). Her edits are back in the tree afterwards."""
    now = {f: f.read_bytes() for f in saved}
    if all(now[f] == data for f, data in saved.items()):
        return False
    for f, data in saved.items():
        f.write_bytes(data)
    try:
        return run_tests(tree, tests, python)[0]
    finally:
        for f, data in now.items():
            f.write_bytes(data)


def _proposed(tried: list[dict]) -> str:
    """For candidate 2..K of a round: the fixes already proposed, so she gives a different one."""
    shown = "\n".join(f"- {t['why'][:120]}: {json.dumps(t['edits'], ensure_ascii=False)[:500]}" for t in tried)
    return ("\nThese fixes were already proposed for this same code; give a DIFFERENT fix (another line or another "
            "change), not one of these:\n" + shown + "\n") if tried else ""


def ask_claude(prompt: str, effort: str = "medium") -> str:
    """The same prompt to Claude; its JSON object only (it may wrap it in a code fence)."""
    text = claude.ask(prompt, effort, what=f"{REPO}: {prompt[:60]}")
    return text[text.find("{"):text.rfind("}") + 1] if "{" in text else text


def ask_claude_hard(prompt: str) -> str:
    return ask_claude(prompt, "high")


def repair(tree: Path, title: str, fails: list[dict], out: str, tests: list[str], python: str,
           asker=ask, diff: str = "", k: int | None = None) -> tuple[bool, str, int]:
    """Up to ROUNDS rounds of Litha's edits + the tests; progress (fewer failures) is kept between rounds.
    Each round she proposes up to k edit sets from the same code (the 2nd.. are told the earlier ones and must
    differ); each is applied, the failing test files run, and the one with the fewest failures (ties: the smallest
    edit) is the round's answer. The first candidate that passes ends it at once. k=1 is the one-answer loop."""
    k = max(1, k if k is not None else int(os.environ.get("LITHA_FIX_K") or K))
    from litha import fix_reach                             # the traced run and the missing names (4j)
    ok, round_no = False, 0
    target = fails[0]["test"] if fails else ""

    def score(text: str) -> tuple[int, int]:                 # fewer failures, then the target test failing later
        return len(FAILED.findall(text)) or 99, -context_pack.failed_at(text, target)

    feedback, why, best, kept_edits = "", "", score(out), []
    saved: dict[Path, bytes] = {}                           # file -> bytes when repair() started
    if not diff.strip():                                     # blind: show the wrong values instead of a diff
        deep = deep_failure(tree, fails, python)
        if deep:
            block = failures(deep, 1)                        # its test's block, not the warnings summary after it
            fails = [{"test": fails[0]["test"], "section": block[0]["section"] if block and block[0]["section"]
                      else deep}] + fails[1:]
    window = fix_reach.window(context_pack.WINDOW)            # 8192 when her first node has it (4l)
    reached = fix_reach.trace(tree, fails[0]["test"], python) if fails else []   # what the failing test enters
    for round_no in range(1, ROUNDS + 1):
        wide = not diff.strip() or round_no > 1              # no diff, or the diff-led round failed: real-fix context
        lessons = _lessons()
        tried: list[dict] = []
        applied = False                                      # the tree holds tried[-1]'s edits
        for i in range(k):
            if applied:
                _restore(tree, saved, kept_edits)
                applied = False
            prompt = self_map.fitted("fix-python", lambda note: context_pack.fixer_prompt(  # + her weak spot, if it fits
                tree, title=title, fails=fails, out=out, diff=source_diff(diff), lessons=lessons + note,
                feedback=feedback, proposed=_proposed(tried), window=window, reached=reached, wide=wide), 700,
                window, task={"repo": REPO, "paths": [f["test"].split("::")[0] for f in fails],
                              "text": "\n".join(f["test"] + "\n" + f["section"][-1500:] for f in fails)})
            try:
                answer = json.loads(asker(prompt))
            except (ValueError, TypeError) as e:
                if window > context_pack.WINDOW and "HTTP 400" in str(e):   # a 4096 node took it: narrow from now on
                    window = context_pack.WINDOW
                continue
            if not isinstance(answer, dict):
                continue
            why = str(answer.get("why", ""))[:300]
            edits, misses = context_pack.inserts(tree, answer.get("edits")), []
            problems = _apply_saved(tree, edits, saved, misses)
            if misses and k == 1:                            # her find is nowhere: once more, with the nearest lines
                again = context_pack.inserts(tree, context_pack.reask(tree, why, misses, asker))
                if again:
                    problems = [p for p in problems if "'find' matched" not in p] + _apply_saved(tree, again, saved)
                    edits = [e for j, e in enumerate(edits or []) if j not in {m["index"] for m in misses}] + again
            problems += context_pack.check_syntax(tree, edits)
            broken = _new_breakage(tree, saved, python)
            if broken:                                       # refused without a test run, undone like a failure
                applied = True
                tried.append({"why": why, "edits": edits, "problems": problems + [broken], "out": broken,
                              "now": (10**6, 0), "size": _edit_size(edits)})       # worse than any test run
                continue
            ok, out = run_tests(tree, tests, python)
            if ok:
                break
            applied = True
            tried.append({"why": why, "edits": edits, "problems": problems, "out": out,
                          "now": score(out), "size": _edit_size(edits)})
        if ok:
            break
        if not tried:
            feedback = "\nYour last answer was not valid JSON. Answer only the JSON object.\n"
            continue
        win = min(range(len(tried)), key=lambda j: (tried[j]["now"], tried[j]["size"]))
        why, out, problems = tried[win]["why"], tried[win]["out"], tried[win]["problems"]
        others = "".join(f"\nAlso tried, no better: {json.dumps(t['edits'], ensure_ascii=False)[:300]}"
                         for j, t in enumerate(tried) if j != win)
        if tried[win]["now"] < best:                        # progress: keep it, fix the rest next
            if win != len(tried) - 1 or not applied:
                _restore(tree, saved, kept_edits)
                _apply_saved(tree, tried[win]["edits"], saved)
            best, fails = tried[win]["now"], failures(out) or fails
            kept_edits.append(tried[win]["edits"])
            reached = fix_reach.trace(tree, fails[0]["test"], python) if fails else []
            feedback = ("\nYour edits were kept: fewer tests fail now, or the test gets further. The code above "
                        "already includes them. "
                        "Fix what still fails:\n" + context_pack.tidy(out)[-1500:] + "\n")
            continue
        _restore(tree, saved, kept_edits)                    # no progress: back to the last kept state
        feedback = ("\nYour previous attempt did not work. " + ("Problems: " + "; ".join(problems) + ". " if problems
                    else "") + "Test output after it:\n" + context_pack.tidy(out)[-1500:] + others
                    + "\nTry a different fix.\n")
    if ok and _passes_without(tree, saved, tests, python):
        _restore(tree, saved, [])
        return False, FLAKY + "the failing tests pass without her edits too, so the edits fixed nothing", round_no
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


def run_pyright(tree: Path, python: str, files: list[str] | None = None) -> list[dict] | None:
    """Pyright's errors as CI computes them ({file, line, rule, message}, repo-relative), or None when it cannot run.
    With `files`, only those are checked (~3 s a file instead of ~50 s for the repo; same counts for them)."""
    npx = shutil.which("npx")
    if not npx:
        return None
    r = sh([npx, *PYRIGHT, "--pythonpath", bare_python(python), "--outputjson", *(files or [])], cwd=tree, timeout=900)
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


def _counts(errors: list[dict], files: set[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in errors:
        if e["file"] in files:
            out[f"{e['file']}::{e['rule']}"] = out.get(f"{e['file']}::{e['rule']}", 0) + 1
    return out


def excess_files(excess: dict[str, tuple[int, int]]) -> list[str]:
    return sorted({k.rsplit("::", 1)[0] for k in excess})


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


def _parses(path: Path) -> bool:
    try:
        compile(path.read_bytes(), str(path), "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return False
    return True


def fix_types(tree: Path, python: str, asker=ask, checker=run_pyright) -> tuple[bool, str, int]:
    """Up to ROUNDS rounds of her edits against the pyright baseline gate. A round must lower the errors above the
    baseline and add no ignore comment, else it is undone. Then the tests of every changed module must still pass.
    Round 0 = nothing to do here (pyright cannot run, or the gate passes locally).
    Speed: after the first full run a round re-checks only the files above the baseline (their counts do not depend
    on what else is checked; probed once here, else every round is a full run), and when those reach zero a full run
    decides, so success always means the whole repo passes."""
    errors = checker(tree, python)
    if errors is None:
        return False, "pyright cannot run here (no npx)", 0
    excess = type_excess(tree, errors)
    if not excess:
        return False, "the pyright gate passes locally (CI-only type failure)", 0
    probe_files = excess_files(excess)
    probe = checker(tree, python, probe_files)
    fast = probe is not None and _counts(probe, set(probe_files)) == _counts(errors, set(probe_files))
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
        broken = [f for f, data in before.items() if f.endswith(".py") and (tree / f).read_bytes() != data
                  and not _parses(tree / f)]
        if broken:                                        # a syntax error can still lower pyright's count: undo
            for f, data in before.items():
                (tree / f).write_bytes(data)
            feedback = (f"\nYour previous edits left a syntax error in {', '.join(broken)} and were undone. Keep the "
                        "code's indentation and syntax exactly; change only what fixes the type error.\n")
            continue
        after = (checker(tree, python, excess_files(excess)) if fast else checker(tree, python)) or []
        left = type_excess(tree, after)
        if fast and not left:                             # those files are clean: the whole repo decides
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


FRONT = "frontend"                          # CI: npm run typecheck / test --prefix frontend (tests.yml, job "react")
REACT_CI = re.compile(r"React UI compile and tests|npm run (?:typecheck|test|build) --prefix frontend")
TSC = re.compile(r"(?:^|\s|##\[error\])((?:frontend/)?[\w./-]+\.[cm]?tsx?)(?:\((\d+),(\d+)\):|:(\d+):(\d+) -) error (TS\d+): ([^\r\n]*)",
                 re.M)                      # tsc plain "f(l,c): error TSn: m" and pretty "f:l:c - error TSn: m"
VITEST = re.compile(r"^\s*FAIL\s+((?:frontend/)?[\w./-]+\.test\.[cm]?[jt]sx?)(?: \[[^\]\n]*\])?(?: > ([^\n]*?))?\s*$",
                    re.M)
VFRAME = re.compile(r"(?:❯|at )\s*\(?((?:frontend/)?src/[\w./-]+\.[cm]?[jt]sx?):(\d+):\d+")
SILENCE = re.compile(r"@ts-(?:ignore|expect-error|nocheck)|\bas\s+any\b|:\s*any\b|<any>|\bany\[\]|eslint-disable")
DEPS = Path.home() / ".star" / "pr-fixer" / "frontend-deps"   # node_modules per package.json, made once, shared
FRONT_PROMPT = """You are Litha, fixing the failing "React UI compile and tests" check (tsc + vitest) of STAR's React
frontend so CI passes. PR title: {title}
What this PR changed in the frontend (the cause is most likely in these lines):
{diff}

Errors now ({count} in all), each with the real code around it (line numbers on the left, do not copy them):
{errors}
{feedback}
Fix the cause in the source code. Test files (*.test.ts, *.test.tsx) describe the wanted behaviour: never edit them,
nor tsconfig, vite/vitest config, package.json or lock files. Never silence an error: no // @ts-ignore,
@ts-expect-error, @ts-nocheck, "as any", ": any" or eslint-disable. Give values their real types. Paths start with
frontend/. Copy "find" from the code listing (the file as it is now), never from the diff: no leading + or -.
Make the smallest correct change. Answer only JSON: {{"why": "<one sentence: the cause>", "edits":
[{{"file": "<path>", "find": "<exact existing text, a few whole lines, unique in the file>", "replace": "<new text>"}}]}}"""


def _front(path: str) -> str:
    path = path.replace("\\", "/").lstrip("./")
    return path if path.startswith(f"{FRONT}/") else f"{FRONT}/{path}"


def frontend_failures(log: str) -> dict | None:
    """The React job's failures in a CI log: tsc errors and vitest FAIL lines, repo-relative. None = none in the log."""
    log = STAMP.sub("", ANSI.sub("", log))
    tsc = [{"file": _front(f), "line": int(a or c), "code": code, "message": msg.strip()}
           for f, a, _, c, _, code, msg in TSC.findall(log)]
    tsc = list({(e["file"], e["line"], e["code"]): e for e in tsc}.values())
    tests = list(dict.fromkeys((_front(f), (name or "").strip()) for f, name in VITEST.findall(log)))
    if not tsc and not tests:
        return None
    return {"tsc": tsc, "vitest": [{"file": f, "test": t, "section": ""} for f, t in tests]}


def vitest_sections(out: str) -> list[dict]:
    """Each vitest failure with the text under its FAIL line (the assertion and the stack frames)."""
    out = ANSI.sub("", out)
    marks = list(VITEST.finditer(out))
    got: dict[tuple[str, str], dict] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(out)
        body = re.split(r"(?m)^\s*⎯{3,}", out[m.end():end], maxsplit=1)[0]
        key = (_front(m.group(1)), (m.group(2) or "").strip())
        if key not in got or len(body) > len(got[key]["section"]):
            got[key] = {"file": key[0], "test": key[1], "section": body.strip()[:1500]}
    return list(got.values())


def _link(target: Path, link: Path) -> None:
    if sys.platform == "win32":                            # a junction needs no admin rights (a symlink does)
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _unlink(link: Path) -> None:
    """Remove the node_modules link only, never what it points to (rmdir of a junction removes just the junction)."""
    try:
        if sys.platform == "win32" and (link.is_symlink() or link.is_junction()):
            os.rmdir(link)
        elif link.is_symlink():
            link.unlink()
    except OSError:
        pass


def frontend_deps(tree: Path) -> str:
    """frontend/node_modules from the shared cache: one `npm install` per package.json (+ lock) content, the same
    command CI runs (the frontend has no lockfile; npm's own lock is kept in the cache entry). '' = ready, else why."""
    import hashlib
    npm = shutil.which("npm")
    pkg = tree / FRONT / "package.json"
    if not npm or not pkg.is_file():
        return "npm is not installed" if not npm else "no frontend/package.json"
    lock = tree / FRONT / "package-lock.json"
    key = hashlib.sha256(pkg.read_bytes() + (lock.read_bytes() if lock.is_file() else b"")).hexdigest()[:16]
    cache = DEPS / key
    if not (cache / ".ok").is_file():
        shutil.rmtree(cache, ignore_errors=True)
        cache.mkdir(parents=True)
        shutil.copy2(pkg, cache / "package.json")
        if lock.is_file():
            shutil.copy2(lock, cache / "package-lock.json")
        r = sh([npm, "ci" if lock.is_file() else "install", "--no-audit", "--no-fund"], cwd=cache, timeout=1800)
        if r.returncode:
            return "npm install failed: " + (r.stdout + r.stderr)[-300:]
        (cache / ".ok").write_text(dt.datetime.now().isoformat(), encoding="utf-8")
        for old in sorted((d for d in DEPS.iterdir() if d.is_dir() and d != cache), key=lambda d: d.stat().st_mtime)[:-2]:
            shutil.rmtree(old, ignore_errors=True)         # keep the newest 3 entries
    mods = tree / FRONT / "node_modules"
    if not mods.exists():
        _link(cache / "node_modules", mods)
    return ""


def run_frontend(tree: Path, files: list[str] | None = None) -> dict | None:
    """CI's React commands here: `npm run typecheck` and `npm run test` (only `files` when given, else all).
    {tsc: [...], vitest: [...]} like frontend_failures (vitest with each failure's section), None = cannot run."""
    npm = shutil.which("npm")
    if not npm or frontend_deps(tree):
        return None
    env = dict(os.environ, CI="1", NO_COLOR="1", FORCE_COLOR="0")
    r = sh([npm, "run", "typecheck", "--prefix", FRONT], cwd=tree, timeout=900, env=env)
    found = frontend_failures(r.stdout + r.stderr) or {"tsc": [], "vitest": []}
    tsc = found["tsc"]
    if r.returncode and not tsc:                           # tsc failed without an error line: count it, show it
        tsc = [{"file": "", "line": 0, "code": "tsc", "message": (r.stdout + r.stderr).strip()[-400:]}]
    rel = [f[len(FRONT) + 1:] if f.startswith(f"{FRONT}/") else f for f in files or []]
    r = sh([npm, "run", "test", "--prefix", FRONT, "--", *rel], cwd=tree, timeout=1800, env=env)
    out = r.stdout + r.stderr
    tests = vitest_sections(out)
    if r.returncode and not tests:
        tests = [{"file": "", "test": "vitest", "section": out.strip()[-1200:]}]
    return {"tsc": tsc, "vitest": tests}


def _count(found: dict) -> int:
    return len(found["tsc"]) + len(found["vitest"])


def _near(tree: Path, path: str, line: int, around: int = 6) -> str:
    f = tree / path
    if not path or not f.is_file() or line < 1:
        return ""
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(f"{i + 1:5}: {lines[i]}" for i in range(max(0, line - around - 1), min(len(lines), line + around)))


TS_SKIP = {"expect", "it", "test", "describe", "render", "within", "waitFor", "act", "toBe", "toEqual", "toContain",
           "toMatch", "toHaveLength", "toBeTruthy", "toBeNull", "toHaveBeenCalled", "toHaveBeenCalledWith", "map",
           "filter", "find", "some", "every", "push", "String", "Number", "Array", "Object", "JSON"}


def ts_definitions(tree: Path, section: str, limit: int = 3, max_lines: int = 30) -> list[str]:
    """The source of the functions a failing vitest assertion calls (the failing line first): the frames point into
    the test only, and without the function she guesses its code (seen in the second live trial)."""
    def calls(text: str) -> list[str]:
        return [n for n in re.findall(r"\b([A-Za-z_]\w{2,})\(", text) if n not in TS_SKIP]

    def definition(name: str) -> tuple[str, list[str]] | None:
        decl = re.compile(rf"^export\s+(?:async\s+)?(?:function\s+{re.escape(name)}\b|(?:const|let)\s+"
                          rf"{re.escape(name)}\s*[=:])")
        for f in src:
            text = f.read_text(encoding="utf-8", errors="replace").splitlines()
            start = next((i for i, ln in enumerate(text) if decl.match(ln)), None)
            if start is None:
                continue
            end = start + 1
            while end < len(text) and end - start < max_lines:
                if text[end].startswith("}"):             # the body's closing brace ends it
                    end += 1
                    break
                if text[end].strip() and not text[end][0].isspace():   # the next top-level statement
                    break
                end += 1
            return f.relative_to(tree).as_posix(), [f"{i + 1:5}: {text[i]}" for i in range(start, end)]
        return None

    src = sorted(p for p in (tree / FRONT / "src").rglob("*.ts*") if ".test." not in p.name and p.suffix in (".ts", ".tsx")
                 and "node_modules" not in p.parts) if (tree / FRONT / "src").is_dir() else []
    lines = section.splitlines()
    hit = [lines[i - 1] for i in range(1, len(lines)) if re.match(r"^\s*\|\s*\^", lines[i])]
    queue, seen, out = calls("\n".join(hit)) or calls(section), set(), []
    while queue and len(out) < limit:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        got = definition(name)
        if got:
            out.append(f"--- {got[0]} (called by the test)\n" + "\n".join(got[1]))
            queue = calls("\n".join(got[1][1:])) + queue  # what that function calls comes next
    return out


def front_listing(tree: Path, found: dict, budget: int = 7000) -> str:
    out = []
    for e in found["tsc"][:10]:
        out.append(f"{e['file']}({e['line']}): error {e['code']}: {e['message']}\n{_near(tree, e['file'], e['line'])}")
    for t in found["vitest"][:4]:
        frames = list(dict.fromkeys((_front(p), int(n)) for p, n in VFRAME.findall(t["section"])))[:3]
        code = "\n".join([f"--- {p}\n{_near(tree, p, n)}" for p, n in frames if (tree / p).is_file()]
                         + ts_definitions(tree, t["section"]))
        out.append(f"vitest FAIL {t['file']} > {t['test']}\n{t['section'][:1200]}\n{code}")
    return "\n\n".join(out)[:budget]


NUMBERED = re.compile(r"(?m)^ *\d+: ")                     # the "   27: " the code listings put before each line


def as_in_file(tree: Path, edit: dict) -> dict:
    """Her 'find' as the file really has it, when she copied it with what the prompt adds around the code. Seen live:
    '-old' / '+new' lines from the diff (5 rounds in a row) and the listing's line numbers with a shifted indent (#857,
    5 rounds). The fixed text is used only when it names exactly one run of lines in the file (indentation aside)."""
    f = tree / str(edit.get("file", "")).replace("\\", "/").lstrip("./")
    find, new = str(edit.get("find", "")), str(edit.get("replace", ""))
    if not find or not f.is_file():
        return edit
    text = f.read_text(encoding="utf-8", errors="replace")
    if find in text:
        return edit
    lines = find.split("\n")
    if any(ln[:1] in "+-" for ln in lines if ln) and all(ln[:1] in "+- " for ln in lines if ln):
        lines = [ln[1:] for ln in lines if ln[:1] in "+ " and ln]          # the '+' side is what the file has now
    elif NUMBERED.search(find):
        lines, new = [NUMBERED.sub("", ln) for ln in lines], NUMBERED.sub("", new)
    want = [ln.strip() for ln in lines]
    while want and not want[-1]:
        want.pop()
    have = text.split("\n")
    hits = [i for i in range(len(have) - len(want) + 1) if want and [h.strip() for h in have[i:i + len(want)]] == want]
    if len(hits) != 1:
        return edit
    return {**edit, "find": "\n".join(have[hits[0]:hits[0] + len(want)]), "replace": new}


def fix_frontend(tree: Path, asker=ask, runner=run_frontend, title: str = "", diff: str = "") -> tuple[bool, str, int]:
    """Up to ROUNDS rounds of her edits against CI's React commands (tsc, then vitest). A round must lower the count of
    tsc errors + failing tests and add nothing that silences an error, else it is undone and she is told why. At the
    end the whole vitest suite runs once (a fix must not break another test). Round 0: (False, why) = it cannot run
    here (no npm, install failed); (True, why) = it passes here, i.e. CI-only (flaky)."""
    mods = tree / FRONT / "node_modules"
    linked = not mods.exists()                              # the link is ours: removed again at the end
    try:
        found = runner(tree, None)
        if found is None:
            return False, "the React checks cannot run here (" + (frontend_deps(tree) or "npm failed") + ")", 0
        if not _count(found):
            return True, "tsc and vitest pass locally (CI-only failure)", 0
        files = sorted({t["file"] for t in found["vitest"] if t["file"]})
        front_diff = "".join(p for p in re.split(r"(?m)^(?=diff --git )", diff)
                             if re.match(rf"diff --git a/{FRONT}/", p) and not FRONT_SPEC.match(
                                 p.split(" b/", 1)[-1].split("\n", 1)[0]))
        feedback, why, edited = "", "", False
        for round_no in range(1, ROUNDS + 1):
            before_n = _count(found)
            prompt = FRONT_PROMPT.format(title=title, diff=front_diff[:4000] or "(not available)", count=before_n,
                                         errors=front_listing(tree, found), feedback=feedback)
            try:
                answer = json.loads(asker(prompt))
            except (ValueError, TypeError):
                feedback = "\nYour last answer was not valid JSON. Answer only the JSON object.\n"
                continue
            edits = [as_in_file(tree, e) for e in answer.get("edits") or [] if isinstance(e, dict)] \
                if isinstance(answer.get("edits"), list) else []
            if any(len(SILENCE.findall(str(e.get("replace", "")))) > len(SILENCE.findall(str(e.get("find", ""))))
                   for e in edits):
                feedback = ("\nYour edits silenced an error (ts-ignore, ts-expect-error or any). That hides it; "
                            "fix its cause instead.\n")
                continue
            paths = {str(e.get("file", "")).replace("\\", "/").lstrip("./") for e in edits}
            before = {p: (tree / p).read_bytes() for p in paths if p and (tree / p).is_file()}
            problems = apply_edits(tree, edits)
            after = runner(tree, files) or found
            if _count(after) < before_n:
                why, feedback, found, edited = str(answer.get("why", why))[:300], "", after, True
                files = sorted(set(files) | {t["file"] for t in after["vitest"] if t["file"]})
                if not _count(found):
                    break
                feedback = (f"\nYour edits were kept: {before_n} -> {_count(found)} errors. The code above already "
                            "includes them. Fix what is left.\n")
                continue
            for p, data in before.items():                  # no progress: undo this round
                (tree / p).write_bytes(data)
            feedback = (f"\nYour previous edits did not lower the errors ({before_n} -> {_count(after)}). "
                        + ("Problems: " + "; ".join(problems) + ". " if problems else "") + "Try a different fix.\n")
        else:
            return False, why or "the React errors remain", ROUNDS
        if not edited:
            return False, "nothing changed", round_no
        final = runner(tree, None)                           # the whole suite once: nothing else may break
        if final is None or _count(final):
            left = "; ".join([f"{e['file']}({e['line']}) {e['code']}" for e in (final or {}).get("tsc", [])] +
                             [f"{t['file']} > {t['test']}" for t in (final or {}).get("vitest", [])])
            return False, "after her fix the full React run fails: " + (left or "it could not run")[:300], round_no
        return True, why, round_no
    finally:
        if linked:
            _unlink(mods)


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


RERAN: Path | None = None                  # {"owner/repo@sha": unix time}: heads that had their one CI rerun


def _reran_file() -> Path:
    """Next to tried.json, also when a test points STATE at a temp folder (a module-level path hit the live file)."""
    return RERAN or STATE.with_name("reran.json")


def reran(sha: str) -> bool:
    """This head already had its one CI rerun (any run, any worker)."""
    try:
        return f"{REPO}@{sha}" in json.loads(_reran_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False


def _note_rerun(sha: str) -> None:
    with TRIED, file_lock(_reran_file().with_name("reran.lock")):
        try:
            done = json.loads(_reran_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            done = {}
        now = time.time()
        done = {k: t for k, t in done.items() if isinstance(t, (int, float)) and now - t < 30 * 86400}
        done[f"{REPO}@{sha}"] = round(now)
        write_atomic(_reran_file(), json.dumps(done))


def rerun_failed(sha: str, number: int | None = None) -> int:
    """Run the failed jobs of this commit again; returns how many workflow runs were restarted. When GitHub refuses
    every rerun ("cannot be retried", seen on a 4-day-old run), closing and reopening the PR starts a fresh CI run.
    There is one CI runner: RERUNS caps the reruns of a whole run, across workers (RerunSpent when it is used up).
    At most one rerun per head commit, ever (RERAN): #700 was rerun again every run because a "rerun" result is not
    marked tried. A head that had its rerun returns 0 (nothing restarted)."""
    if reran(sha):
        return 0
    if not RERUNS.take():
        raise RerunSpent(f"#{number}: this run's CI rerun is already used")
    try:
        n = _rerun(sha, number)
    except BaseException:
        RERUNS.give()
        raise
    if n:
        _note_rerun(sha)
    return n


def _rerun(sha: str, number: int | None) -> int:
    checks = latest_runs(json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"))["check_runs"])
    runs = {m.group(1) for c in checks if c.get("conclusion") == "failure"   # the newest run of each check only
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


MERGED_INTO = re.compile(r"Merge ([0-9a-f]{40}) into ([0-9a-f]{40})")   # actions/checkout of a pull_request run


def base_fault(log: str, pr: dict, fails: list[dict]) -> tuple[str, str]:
    """(kind, why) when CI's failure is (also) the base's: CI tested the head merged into a base commit whose own CI
    failed one of the same tests (#857 #899 #903 #905, all on star/next 91c3972d). kind "stale": the base has moved
    on and its newest commit has no failed check, so a fresh run on today's base is what the PR needs (a rerun
    replays the same old merge commit, so it fails the same way; the caller first runs every failing test on the
    head merged with today's base); "broken": every failing test is the base's and the base still fails, so it is
    not this PR's to fix ('' = the PR's own failure)."""
    bases = {b for h, b in MERGED_INTO.findall(log) if h == pr.get("headRefOid")}
    names = [f["test"] for f in fails]
    if len(bases) != 1 or not names:
        return "", ""
    ci_base = bases.pop()
    seen = set(FAILED.findall(failed_logs(ci_base, every=True)))
    shared = [n for n in names if n in seen]
    if not shared:
        return "", ""
    why = (f"CI tested this head merged into {BASE} at {ci_base[:8]}, whose own CI failed "
           f"{len(shared)} of its {len(names)} failing test(s): {', '.join(shared)[:200]}")
    now = pr.get("baseRefOid") or ""
    every = len(shared) == len(names)
    if not now or now == ci_base:
        return ("broken", f"{why}; {BASE} has not moved since: not this PR's failure") if every else ("", "")
    if any(c["conclusion"] == "FAILURE" for c in head_checks(now)):
        return ("broken", f"{why}; {BASE} still fails at {now[:8]}: not this PR's failure") if every else ("", "")
    return "stale", f"{why}; {BASE} has no failed check at {now[:8]}"


def fresh_run(sha: str, number: int, base: str) -> int:
    """A CI run on today's base: close and reopen the PR (a pull_request run merges the head into the base of its
    start; a rerun would replay the old merge commit). Nothing is pushed. Once per (head, base); RERUNS caps it."""
    key = f"{sha}^{base}"
    if reran(key):
        return 0
    if not RERUNS.take():
        raise RerunSpent(f"#{number}: this run's CI rerun is already used")
    try:
        gh("pr", "close", str(number), "--repo", REPO)
        gh("pr", "reopen", str(number), "--repo", REPO)
    except RuntimeError:
        RERUNS.give()
        return 0
    _note_rerun(key)
    return 1


def on_base(pr: dict, tests: list[str], python: str) -> tuple[bool | None, str]:
    """The failing test files on the head merged with today's base (a throwaway worktree): (passed, output);
    passed None = the head does not merge cleanly (the conflict path takes it next run)."""
    number, base = pr["number"], pr.get("baseRefOid") or f"origin/{BASE}"
    tree = WORK / f"litha-fresh-{number}"
    if tree.exists():
        sh(["git", "-C", str(CLONE), "worktree", "remove", "--force", str(tree)])
    sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", BASE, f"pull/{number}/head:refs/litha-check/{number}",
        "--force"])
    sh(["git", "-C", str(CLONE), "worktree", "add", "-q", "--detach", str(tree), pr["headRefOid"]])
    try:
        if sh(["git", *IDENTITY, "merge", "--no-ff", "--no-commit", base], cwd=tree).returncode:
            return None, "the head does not merge cleanly with today's base"
        return run_tests(tree, tests, python)
    finally:
        sh(["git", "-C", str(CLONE), "worktree", "remove", "--force", str(tree)])


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
    if head.startswith("|||||||"):                     # the PR side is empty (seen: Studio #275, instance.rs)
        head = "\n" + head
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
    if why:
        return f"{tool} rejects it: {why}"
    twice = sorted(double_uses(text) - double_uses(original.stdout)) if tool == "rustfmt" else []
    return f"it imports {', '.join(twice[:4])} twice (`use` lines of both sides kept)" if twice else ""


USE = re.compile(r"^((?:#\[cfg\([^\n]*\)\]\n)?)(?:pub(?:\([\w:]+\))?\s+)?use\s+([^;]+);", re.M)


def double_uses(text: str) -> set[str]:
    """Names a file's top-level `use` lines bring in more than once (rustc E0252), counted per `#[cfg(...)]`; an
    unconditional one clashes with every cfg. Seen in Studio #210: the PR's `pub use game::{.., Game, ..}` and main's
    `#[cfg(feature = "presentation")] pub use game::{FrameOutput, Game}` both kept."""
    seen: dict[str, list[str]] = {}
    for m in USE.finditer(text):
        for leaf in re.split(r"[{},]", m.group(2)):
            name = re.split(r"\s+as\s+", leaf.strip())[-1].rsplit("::", 1)[-1].strip()
            if name and name not in ("*", "self", "super", "crate", "_"):
                seen.setdefault(name, []).append(m.group(1).strip())
    return {n for n, cfgs in seen.items() if len(cfgs) > 1 and ("" in cfgs or len(set(cfgs)) < len(cfgs))}


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


_C_LIKE = r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"'
LITERALS = {   # comments, strings and char literals per language: brackets inside them are not code
    "rs": re.compile(r'//[^\n]*|/\*.*?\*/|(?<![\w])b?r(#*)".*?"\1|b?"(?:\\.|[^"\\])*"'
                     r"|b?'(?:\\(?:u\{[0-9a-fA-F]{1,6}\}|x[0-9a-fA-F]{2}|.)|[^\\'\n])'", re.S),  # 'a alone: lifetime
    "py": re.compile(r'#[^\n]*|(?i:[rbuf]{0,2})(?:"""(?:\\.|.)*?"""|\'\'\'(?:\\.|.)*?\'\'\''
                     r'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')', re.S),
    "js": re.compile(_C_LIKE + r"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`", re.S),
    "c": re.compile(_C_LIKE + r"|'(?:\\.|[^'\\\n])*'|`[^`]*`", re.S),            # (go: `raw strings`)
    "lua": re.compile(r'--\[(=*)\[.*?\]\1\]|--[^\n]*|\[(=*)\[.*?\]\2\]|"(?:\\.|[^"\\\n])*"'
                      r"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`", re.S),
    "json": re.compile(r'"(?:\\.|[^"\\\n])*"'),
}
LANG = {"rs": "rs", "py": "py", "ts": "js", "tsx": "js", "js": "js", "jsx": "js", "lua": "lua", "luau": "lua",
        "json": "json", "wgsl": "c", "cs": "c", "java": "c", "kt": "c", "go": "c", "c": "c", "h": "c", "cc": "c",
        "cpp": "c", "hpp": "c"}


def balance(text: str, path: str = "") -> tuple[int, int, int]:
    """Open minus closed {}, () and [] in the code of `text`: brackets in comments, strings and char literals do not
    count (seen in Studio: Lua source inside Rust raw strings, '{' char literals, `(` in doc comments). A literal the
    text cuts off (a block that starts or ends inside a string) simply counts as code, the same for every side."""
    lexer = LITERALS.get(LANG.get(path.rsplit(".", 1)[-1].lower(), ""))
    code = lexer.sub(" ", text) if lexer else text
    return code.count("{") - code.count("}"), code.count("(") - code.count(")"), code.count("[") - code.count("]")


def deficit(want: tuple[int, int, int], got: tuple[int, int, int]) -> str:
    """The bracket difference in words, per kind of bracket, for her feedback (its effect alone is not measured)."""
    out = []
    for (o, c), w, g in zip(("{}", "()", "[]"), want, got):
        if g < w:
            out.append(f"you have {w - g} `{c}` too many (or lost {w - g} `{o}`); the code after the conflict "
                       f"already closes what the sides leave open")
        elif g > w:
            out.append(f"you lost {g - w} `{c}` (or added {g - w} `{o}`)")
    return "; ".join(out)


CLOSING = re.compile(r"^\s*[)\]}]+[;,)]*\s*$")


def rebalanced(path: str, block: str, new: str, before: str, after: str) -> str:
    """Her answer without the bracket-only lines she repeated from just after (or before) the block, when cutting them
    makes her brackets balance the way both sides do; else her answer unchanged. echoed() keeps such lines (a lone `}`
    is no real line). Replayed on her 90 answers to Studio tune-set blocks: 27 bracket misses, 3 of them this."""
    ours, _, theirs = sides(block)
    want = balance(ours, path)
    if not BRACKETED.search(path) or want != balance(theirs, path) or balance(new, path) == want:
        return new
    lines = new.splitlines(keepends=True)
    tail = [ln for ln in after.splitlines() if ln.strip()]
    head = [ln for ln in before.splitlines() if ln.strip()]
    for k in range(1, 4):                            # her last k lines are the first k lines after the block
        cut = lines[:-k]
        if len(lines) > k and all(CLOSING.match(x) for x in lines[-k:]) and len(tail) >= k and \
                [x.strip() for x in lines[-k:]] == [x.strip() for x in tail[:k]] and balance("".join(cut), path) == want:
            return "".join(cut)
    for k in range(1, 3):                            # her first k lines are the last k lines before it
        cut = lines[k:]
        if len(lines) > k and len(head) >= k and [x.strip() for x in lines[:k]] == [x.strip() for x in head[-k:]] \
                and balance("".join(cut), path) == want:
            return "".join(cut)
    return new


def slips(path: str, block: str, new: str, before: str = "", after: str = "") -> str:
    r"""Mistakes a merge of two sides never needs: the line just outside the block repeated inside it (seen: a doubled
    `data:BootData` field in #853), brackets that no longer balance the way BOTH sides do (seen: a lost closing brace
    of an impl), any other real line copied from the code shown around the block (seen in Studio #210: her answer to
    a doc-comment conflict went on with the file's `pub use` lines, which then stood twice), and escape sequences
    turned into real characters (seen: a Rust \n became a line break)."""
    ours, base, theirs = sides(block)
    lines = [ln for ln in new.splitlines() if ln.strip()]
    edge = [(lines[:1], before.rstrip("\n").rsplit("\n", 1)[-1], "before"),
            (lines[-1:], after.lstrip("\n").split("\n", 1)[0], "after")]
    for got, outside, where in edge:
        if got and outside.strip() and got[0].strip() == outside.strip() and outside.strip() not in \
                {ln.strip() for ln in (ours + "\n" + theirs).splitlines()}:
            return (f"Your text repeats the line just {where} the conflict ({outside.strip()[:80]}), which stays in "
                    "the file anyway. Give only what replaces the lines between the markers.\n")
    inside = {ln.strip() for ln in (ours + "\n" + base + "\n" + theirs).splitlines()}
    around = {ln.strip() for ln in (before + "\n" + after).splitlines()} - inside
    copied = [x for x in (ln.strip() for ln in lines) if x in around and len(x) >= 12 and re.search(r"\w", x)]
    if copied:
        return (f"Your text copies a line from outside the conflict ({copied[0][:80]}), which stays in the file "
                "anyway. Give only what replaces the lines between the markers, merged from the two sides.\n")
    for lang in (path, ""):                     # the code's brackets; all of them when the sides only agree on that
        if BRACKETED.search(path) and balance(ours, lang) == balance(theirs, lang):
            if balance(new, lang) != balance(ours, lang):
                return ("Your text does not open and close {}, () and [] the way both sides do (each side: "
                        f"{balance(ours, lang)}, yours: {balance(new, lang)}): "
                        f"{deficit(balance(ours, lang), balance(new, lang))}. Keep every bracket the sides have; "
                        "brackets that open in the conflict may close after it (and the other way round).\n")
            break
    if new.count("\\") < min(ours.count("\\"), theirs.count("\\")):
        return (r"You turned escape sequences such as \n into real characters. Inside the JSON string write a "
                r"backslash as \\ so the code keeps \n, \t and \" exactly as the sides have them." "\n")
    return ""


MARKER = re.compile(r"^(<<<<<<<|\|\|\|\|\|\|\||=======|>>>>>>>)( |$)")
USE_BRACE = re.compile(r"\b(use\s+[\w:]*\w)\{")     # `use api{`: never Rust; she writes it for `use api::{`


def echoed(new: str, block: str, before: str, after: str, path: str = "") -> str:
    """Her answer without the lines she copied from just outside the block, which stay in the file anyway (seen in
    Studio #421 and #255: the merged block followed by the rest of the statement after it, so the brackets that close
    after the block closed twice). Only an exact copy is cut, and only one with a real line that is in neither side;
    `use api{` (never Rust; she writes it for `use api::{`, seen in #317, #245, #421, #210) gets its `::` back."""
    ours, base, theirs = sides(block)
    inside = {ln.strip() for ln in (ours + "\n" + base + "\n" + theirs).splitlines()}
    real = re.compile(r"\w")
    lines = new.splitlines(keepends=True)
    tail = after.split("\n")
    for i in range(len(lines)):                      # earliest i: everything from lines[i] on is the start of `after`
        rest = [ln.strip() for ln in lines[i:]]
        if len(rest) > len(tail) or not any(real.search(x) and x not in inside for x in rest):
            continue
        if i and all(x == tail[k].strip() for k, x in enumerate(rest[:-1])) and \
                tail[len(rest) - 1].strip().startswith(rest[-1]):          # (her last line may stop short)
            lines = lines[:i]
            break
    head = before.split("\n")
    head = head[:-1] if head and not head[-1] else head      # `before` ends with the newline of its last line
    for i in range(len(lines), 0, -1):              # latest i: lines[:i] ends with a copy of the end of `before`
        k = 0
        while k < i and k < len(head) and lines[i - 1 - k].strip() == head[-1 - k].strip():
            k += 1
        copied = [x.strip() for x in head[len(head) - k:]] if k else []
        if k and i < len(lines) and any(real.search(x) and x not in inside for x in copied) and \
                (k == i or (k < len(head) and MARKER.match(head[-1 - k]))):  # (what came before: her redo of the
            lines = lines[i:]                                               #  previous conflict, merged on its own)
            break
    out = "".join(lines)
    if out.strip() and lines != new.splitlines(keepends=True):   # cut: without the blank lines she put between
        if not (ours.startswith("\n") or theirs.startswith("\n")):  # her merge and the copy
            out = out.lstrip("\n")
        if not (ours.endswith("\n\n") or theirs.endswith("\n\n")):
            out = out.rstrip("\n") + "\n"
    if path.endswith(".rs"):
        seen = ours + base + theirs + before + after
        if not USE_BRACE.search(ours + base + theirs):
            out = USE_BRACE.sub(r"\1::{", out)
        for name in set(re.findall(r"\b(\w+)!\(", seen)) - set(re.findall(r"(?<![!\w])(\w+)\(", seen)):
            out = re.sub(rf"(?<![\w.:]){name}\(", f"{name}!(", out)    # `assert_eq(` for `assert_eq!(` (#275)
    return out


WINDOW = 4096                       # litha-fast's context (prompt + answer); ~3.5 characters per token for code
ANSWER = 1500                       # ask()'s max_tokens (#207 ARCHITECTURE.md: ~1690 needed, 3 answers, none valid JSON)


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


def mechanical(path: str, block: str, before: str, after: str) -> str | None:
    """The block's merge when it needs no judgement (diff3 blocks only), else None: both sides only added at an empty
    ancestor (both kept, as written), one side only added next to what the other changed, or both only inserted."""
    if "\n|||||||" not in block:
        return None
    ours, base, theirs = sides(block)
    union = ours.rstrip("\n") + "\n" + theirs if ours.strip() and theirs.strip() else ""
    if not base.strip() and union and not slips(path, block, union, before, after):
        return union
    near = adjacent(ours, base, theirs)
    if near is None:
        near = both_added(ours, base, theirs, docs=path.endswith((".md", ".txt", ".rst")))
    if near is None:
        near = merge3.formatting_only(ours, base, theirs, path)
    if near is None and path.endswith(".rs"):
        near = merge3.use_lists(ours, base, theirs)
    if near is None:
        pieces = merge3.merge(ours, base, theirs)
        near = "".join(p for p in pieces if isinstance(p, str)) if pieces and all(isinstance(p, str) for p in pieces) \
            else None
    if near is None and path.endswith((".md", ".txt", ".rst")):
        near = merge3.prose(ours, base, theirs)
    return near if near is not None and not slips(path, block, near, before, after) else None


def narrow(path: str, text: str) -> tuple[str, set[str]]:
    """The file with every block that is not mechanical cut down to the edits that really overlap (merge3): the rest
    of the block merged, the overlap a smaller block with git's own marker lines. Returns the new text and those
    smaller blocks, which go to her as they are (an addition both sides made at one place stays her call there)."""
    out, last, small = [], 0, set()
    for m in CONFLICT.finditer(text):
        block = m.group(0)
        if "\n|||||||" not in block or mechanical(path, block, text[max(0, m.start() - 1500):m.start()].split("\n", 1)[-1],
                                                  text[m.end():m.end() + 1500].rsplit("\n", 1)[0]) is not None:
            continue
        pieces = merge3.merge(*sides(block))
        marks = [ln for ln in block.splitlines(keepends=True) if MARKER.match(ln)]
        if not pieces or not any(isinstance(p, tuple) for p in pieces) or len(marks) != 4:
            continue
        subs = [p if isinstance(p, str) else marks[0] + p[0] + marks[1] + p[1] + marks[2] + p[2] + marks[3]
                for p in pieces]
        small.update(x for x, p in zip(subs, pieces) if isinstance(p, tuple))
        out += [text[last:m.start()], *subs]
        last = m.end()
    return "".join(out) + text[last:], small


def settled(head: str, tail: str, i: int) -> tuple[str, str]:
    """The code she is shown around conflict i: the blocks before it as already merged, the ones after it as one note
    line each, never their markers (seen: Studio #174 physics, where her answer merged the 3 blocks she saw at once)."""
    k = iter(range(i + 1, 10**6))
    tail = CONFLICT.sub(lambda _: f"    ... (conflict {next(k)}, merged on its own) ...\n", tail)
    return head[-1500:].split("\n", 1)[-1] if len(head) > 1500 else head, tail[:1500].rsplit("\n", 1)[0]


def planned(path: str, text: str, redo: bool = False):
    """(text, blocks, the code around each, each block's mechanical merge or None = hers). With redo every block of
    the file as git wrote it is hers; otherwise the file is narrowed first and the overlaps are hers."""
    small: set[str] = set()
    if not redo:
        text, small = narrow(path, text)
    blocks = list(CONFLICT.finditer(text))
    around = [(text[max(0, m.start() - 1500):m.start()].split("\n", 1)[-1],
               text[m.end():m.end() + 1500].rsplit("\n", 1)[0]) for m in blocks]
    plan = [None if redo or m.group(0) in small else mechanical(path, m.group(0), *around[k])
            for k, m in enumerate(blocks)]
    return text, blocks, around, plan


def resolve_text(path: str, text: str, title: str, asker=ask, hint: str = "",
                 keep: bool = False) -> tuple[str | None, str]:
    """Every conflict block of one file resolved by her; (None, why) when she cannot make valid code of it. A hint is a
    checker's complaint about her previous attempt at this file; with it she redoes every block, or with keep only the
    blocks she answered (the mechanical merges stay). The 1-8 limit counts only the blocks she is asked
    about: Studio's #412 had 9 blocks in instance.rs, most of them mechanical."""
    if not CONFLICT.search(text):
        return None, (f"{path}: git marked no conflict lines in it (deleted on one side and changed on the other, "
                      "a rename, or a binary file)")
    text, blocks, around, plan = planned(path, text, redo=bool(hint and not keep))
    asks = sum(p is None for p in plan)
    if asks > 8:
        return None, f"{path}: {asks} of {len(blocks)} conflict blocks need her (1-8 handled)"
    out, last, feedback = [], 0, hint
    for i, m in enumerate(blocks, 1):
        before, after = around[i - 1]
        if plan[i - 1] is not None:
            out += [text[last:m.start()], plan[i - 1]]
            last = m.end()
            continue
        ours, base, theirs = sides(m.group(0))
        if base.strip() and (not ours.strip()) != (not theirs.strip()) and base not in (ours, theirs):
            gone, kept = (("the PR", BASE) if not ours.strip() else (BASE, "the PR"))
            return None, (f"{path}: conflict {i}: {gone} deleted these lines and {kept} changed them; where that code "
                          "went is a person's call")
        before, after = settled("".join(out) + text[last:m.start()], text[m.end():], i)
        shown = before, after
        need = (len(MERGE_PROMPT) + len(before) + len(m.group(0)) + len(after) + len(ours) + len(theirs)) / 3.5
        if need > WINDOW:                              # less of the code around it, then give up (do not burn tries)
            shown = before[-300:].split("\n", 1)[-1], after[:300].rsplit("\n", 1)[0]
            need -= (len(before) + len(after) - len(shown[0]) - len(shown[1])) / 3.5
        paid = asker is ask and claude.ready()
        local = [] if need > WINDOW or (len(ours) + len(theirs) - len(base)) / 3.5 > ANSWER else [asker] * 3
        if paid and not path.endswith((".md", ".txt", ".rst")):
            tries = [ask_claude] * 2 + local[:1]       # code: her local model rarely gets it right, Claude goes first
        else:
            tries = local + [ask_claude] * 2 * paid    # docs: Claude only after her own model failed
        if not tries and need > WINDOW:
            return None, f"{path}: conflict {i} is too big for her {WINDOW}-token window (~{need:.0f} tokens)"
        if not tries:
            return None, f"{path}: conflict {i}'s merge is longer than her {ANSWER}-token answer"
        for who in tries:
            try:
                task = {"repo": REPO, "paths": [path], "text": m.group(0)}      # her experience memory (4s)
                if who is ask_claude:                  # Claude: all the code around it, no fitting to her 4K window
                    from litha import experience
                    prompt = MERGE_PROMPT.format(repo=REPO, base=BASE, title=title, path=path, i=i, n=len(blocks),
                                                 feedback=feedback + experience.note({**task, "lane": "resolve"},
                                                                                     experience.ROOM["claude"],
                                                                                     "claude"),
                                                 context=before + m.group(0) + after)
                else:
                    prompt = self_map.fitted("resolve", lambda note: MERGE_PROMPT.format(
                        repo=REPO, base=BASE, title=title, path=path, i=i, n=len(blocks), feedback=feedback + note,
                        context=shown[0] + m.group(0) + shown[1]), (len(ours) + len(theirs)) / 3.5, task=task)
                ans = json.loads(who(prompt))
                new = rebalanced(path, m.group(0), echoed(str(ans["resolved"]), m.group(0), before, after, path),
                                 before, after)
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


def merge_file(tree: Path, path: str, raw: str, title: str, asker=ask) -> tuple[str | None, str]:
    """One conflicted file merged and parsed; when a checker rejects it she tries again, told why: first only the
    blocks she answered (the mechanical merges stay; seen in Studio #208, where redoing all 6 blocks failed on one git
    could merge), then every block."""
    merged, why = resolve_text(path, raw, title, asker)
    why = why or broken(tree, path, merged or "")
    for keep in (True, False) if merged is not None and why else ():
        merged, why = resolve_text(path, raw, title, asker, keep=keep,
                                   hint=f"Your previous merge of this file was rejected: {why[:400]}\n")
        why = why or broken(tree, path, merged or "")
        if merged is not None and not why:
            break
    return merged, why


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@[^\n]*\n((?:[ +\-\\][^\n]*(?:\n|$))*)", re.M)


def hunks(diff: str) -> list[tuple[str, str]]:
    """(old text, new text) of each hunk of a unified diff: context plus removed lines, context plus added lines."""
    out = []
    for m in HUNK.finditer(diff):
        old, new = [], []
        for ln in m.group(1).splitlines(keepends=True):
            if ln[:1] in " -":
                old.append(ln[1:])
            if ln[:1] in " +":
                new.append(ln[1:])
        out.append(("".join(old), "".join(new)))
    return out


def targets(tree: Path, deleter: str, skip: str) -> dict[str, str]:
    """The files `deleter` added or changed since the merge base, as they are in the merge now (without conflict
    markers, text only): where code it deleted from `skip` may have gone."""
    mb = sh(["git", "merge-base", "HEAD", f"origin/{BASE}"], cwd=tree).stdout.strip()
    files: dict[str, str] = {}
    for name in sh(["git", "diff", "--name-only", "--diff-filter=AMR", mb, deleter], cwd=tree).stdout.split():
        f = tree / name
        if name != skip and f.is_file() and f.stat().st_size < 2_000_000:
            text = f.read_text(encoding="utf-8", errors="replace")    # (\r\n read as \n, like git diff's lines)
            if not CONFLICT.search(text) and "\x00" not in text:
                files[name] = text
    return files


def place(parts: list[tuple[str, str]], files: dict[str, str]) -> tuple[dict[str, str], int]:
    """Each (old, new) hunk applied where its old text (ancestor lines with their context) stands exactly once in all
    of `files`; ({file: new text} of the files changed when EVERY hunk landed, else {}, hunks placed). A hunk with
    fewer than 2 real lines of old text has no reliable place and counts as not placed."""
    placed, out = 0, dict(files)
    for old, new in parts:
        if sum(1 for ln in old.splitlines() if re.search(r"\w", ln)) < 2:
            continue
        where = [n for n, t in out.items() if t.count(old)]
        if len(where) != 1 or out[where[0]].count(old) != 1:
            continue
        out[where[0]] = out[where[0]].replace(old, new)
        placed += 1
    if not parts or placed < len(parts):
        return {}, placed
    return {n: t for n, t in out.items() if t != files[n]}, placed


def relocate(tree: Path, path: str, changer: str, deleter: str) -> tuple[dict[str, str], int, int]:
    """A modify/delete conflict where the deleting side may only have MOVED the code: each hunk of `changer`'s change
    to `path` (context and removed lines exactly as in the ancestor) applied where that exact text now stands once in
    the files `deleter` changed. ({file: new text} when every hunk landed, else {}, hunks placed, hunks)."""
    mb = sh(["git", "merge-base", "HEAD", f"origin/{BASE}"], cwd=tree).stdout.strip()
    diff = sh(["git", "diff", "-U3", "--no-color", "--no-ext-diff", mb, changer, "--", path], cwd=tree).stdout
    parts = hunks(diff)
    moved, placed = place(parts, targets(tree, deleter, path))
    return moved, placed, len(parts)


def moved_to(tree: Path, path: str, ref: str) -> str:
    """Where `ref` probably put a file it deleted, for the person: the files it added under the file's stem
    (classes.rs -> classes/) or with the same name."""
    mb = sh(["git", "merge-base", "HEAD", f"origin/{BASE}"], cwd=tree).stdout.strip()
    added = sh(["git", "diff", "--name-only", "--diff-filter=A", mb, ref], cwd=tree).stdout.split()
    stem = path.rsplit(".", 1)[0] + "/"
    near = [a for a in added if a.startswith(stem)] or [a for a in added if Path(a).name == Path(path).name]
    if not near:
        return ""
    return f" ({near[0]}" + (f" and {len(near) - 1} more new files under {stem}" if len(near) > 1 else "") + ")"


def whole_file(tree: Path, path: str, raw: str) -> tuple[str | None, list[str]]:
    """A conflict git wrote no blocks for (seen: Studio #421 and #275, main split classes.rs into classes/ while the PR
    changed it). None = git wrote blocks (hers to merge). Else (why, files written and staged); why '' = settled by
    rule: both sides have the same content (only the mode differs: the side that changed it wins), or one side deleted
    the file after moving its code and every hunk of the other side's change lands exactly once where that code now
    is. Anything else is refused with the reason in words."""
    if CONFLICT.search(raw):
        return None, []
    st = {int(ln.split()[2]): (ln.split()[0], ln.split()[1])
          for ln in sh(["git", "ls-files", "-u", "--", path], cwd=tree).stdout.splitlines() if len(ln.split()) >= 4}
    if 2 in st and 3 in st:
        if st[2][1] == st[3][1]:                        # same content; the mode one side changed
            mode = st.get(1, ("", ""))[0]
            side = "--theirs" if st[2][0] in (mode, st[3][0]) else "--ours" if st[3][0] == mode else ""
            if side:
                sh(["git", "checkout", side, "--", path], cwd=tree)
                sh(["git", "add", "--", path], cwd=tree)
                return "", [path]
            return f"{path}: both sides added it with the same content but a different file mode; a person's call", []
        return (f"{path}: changed on both sides and git cannot merge it line by line (a binary file); which version "
                "stays is a person's call"), []
    if 1 in st and (2 in st) != (3 in st):
        changer, deleter = ("HEAD", f"origin/{BASE}") if 2 in st else (f"origin/{BASE}", "HEAD")
        moved, placed, total = relocate(tree, path, changer, deleter)
        if moved:
            for name, text in moved.items():
                (tree / name).write_bytes(text.encode("utf-8"))
            sh(["git", "rm", "-q", "-f", "--", path], cwd=tree)
            sh(["git", "add", "--", *moved], cwd=tree)
            return "", sorted(moved)
        what = f"only {placed} of the {total} hunks of" if total else "nothing of"
        if 2 in st:
            return (f"{path}: deleted on {BASE} and changed by this PR (modify/delete); {BASE} moved or rewrote that "
                    f"code{moved_to(tree, path, deleter)} and {what} the PR's change matched it exactly, so the change "
                    "has to be redone where the code now lives, a person's call"), []
        return (f"{path}: deleted by this PR and changed on {BASE} (modify/delete); the PR moved or rewrote that "
                f"code{moved_to(tree, path, deleter)} and {what} {BASE}'s change matched it exactly, a person's "
                "call"), []
    return (f"{path}: renamed or added differently on the two sides (git keeps no common version to merge); "
            "a person's call"), []


LOCKISH = re.compile(r"(^|/)(pnpm-lock\.yaml|[^/]+\.lock)$")


def guarded(path: str) -> bool:
    """CI, tests and the like (NO_TOUCH): merged only where git-like rules decide, never by her model."""
    return bool(NO_TOUCH.search(path)) and not DEP_FILE.match(path)


def mechanical_only(prompt: str) -> str:
    raise ValueError("a guarded file: no model answer")       # (resolve_text reads it as no usable answer)


def triage(code: list[str], raws: dict[str, str]) -> str:
    """Why the PR's conflicts are not hers ('' = they are). Only files her model has to answer count: a guarded file
    must merge mechanically, at most 5 files may need her, and CI workflows (.github/) are never hers."""
    hers = [c for c in code if LOCKISH.search(c) or not CONFLICT.search(raws.get(c, "")) or
            any(p is None for p in planned(c, raws[c])[3])]
    ci = [c for c in code if c.startswith(".github/")]
    if ci:                                  # AGENTS.md: workflow changes pass an independent review, never her merge
        return f"conflicts she does not resolve alone: {ci[:8]} are CI workflows (a person's review)"
    held = [c for c in hers if guarded(c) or LOCKISH.search(c)]
    if held:
        return f"conflicts she does not resolve alone: {held[:8]} need a judgement (tests and locks merge only mechanically)"
    most = 12 if claude.ready() else 5               # with Claude she takes bigger merges
    if len(hers) > most:
        return f"conflicts she does not resolve alone: {len(hers)} files need her model (1-{most} handled): {hers[:8]}"
    return ""


def resolve(pr: dict, python: str, dry: bool = False, asker=ask) -> dict:
    """A PR that conflicts with star/next: merge star/next into a copy of it on HER branch, resolve (lock files are
    taken from star/next and rebuilt; code conflicts are hers), prove nothing broke, open her own PR. Her own
    litha/ PR (#851: her fix of #833 conflicted and waited for a person) gets the merge on its own branch instead."""
    number = pr["number"]
    day = dt.date.today().strftime("%Y%m%d")
    own = str(pr.get("headRefName", "")).startswith("litha/")
    branch, tree = f"litha/merge-{number}-{day}-{dt.datetime.now():%H%M}", WORK / f"litha-merge-{number}"
    if own:
        branch = f"litha-work/merge-{number}"                # local name; pushed to pr["headRefName"]
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
    raws: dict[str, str] = {c: (tree / c).read_text(encoding="utf-8", errors="replace") if (tree / c).is_file() else ""
                            for c in code}                # each file with its conflict markers, to redo a merge
    why = triage(code, raws)
    if why:
        sh(["git", "merge", "--abort"], cwd=tree)
        return {"pr": number, "result": "failed", "why": why}
    for c in locks:                                         # generated files: star/next's copy, rebuilt below
        sh(["git", "checkout", "--theirs", "--", c], cwd=tree)
    tests: set[str] = set()
    moved: list[str] = []                                   # files a whole-file rule wrote (and staged)
    for c in code:
        why, wrote = whole_file(tree, c, raws[c])
        if why:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {"pr": number, "result": "failed", "why": why}
        if why is not None:
            moved += [w for w in wrote if w not in moved]
            continue
        merged, why = merge_file(tree, c, raws[c], pr.get("title", ""), mechanical_only if guarded(c) else asker)
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
    sh(["git", "add", "--", *[c for c in conflicted if (tree / c).exists()]], cwd=tree)   # (a moved file is gone)
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
    front = build_check.plan(tree, conflicted)                  # tsc (+ touched vitest files) for frontend merges:
    if front["tsc"]:                                           # #853/#857 doubled a prop (TS2300) and were pushed
        built = build_check.run(tree, conflicted, python, steps={"tsc": True, "vitest": front["vitest"]})
        row["tests"] += built["ran"]
        if not built["ok"]:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {**row, "result": "failed", "why": f"after resolving, {built['failed']}"[:400]}
    if (tree / "Cargo.toml").is_file() and any(c.endswith(".rs") for c in code):
        ok, fails, crates, out = rust_fix.crate_tests(tree, code + moved)
        mine = sorted({e["file"] for e in rust_fix.errors(out)} & set(code)) if not ok else []
        for c in mine:                                 # the errors are in a file she merged: redo that merge first,
            said = "; ".join(f"line {e['line']}: {e['error']}" for e in rust_fix.errors(out) if e["file"] == c)
            merged, why = resolve_text(c, raws[c], pr.get("title", ""), asker,   # told what the compiler said
                                       hint=f"After your merge of this file the compiler said: {said[:600]}\n")
            if merged is not None and not (why or broken(tree, c, merged)):
                (tree / c).write_bytes(tidy(tree, c, merged).encode("utf-8"))
        if mine:
            sh(["git", "add", "--", *mine], cwd=tree)
            ok, fails, crates, out = rust_fix.crate_tests(tree, code + moved)
            if ok:
                row["why"] += f"; redid {', '.join(mine)} after the compiler's errors"
        if not ok and rust_fix.errors(out):            # it does not compile (one side renamed what the other uses):
            fixed, how = rust_fix.repair(tree, REPO, pr.get("title", ""),   # her repair, then the tests again
                                         f"Run cargo test -p {' -p '.join(crates)}\n{out}", asker)
            if not fixed and asker is ask and claude.ready():               # Claude when her own repair failed
                fixed, how = rust_fix.repair(tree, REPO, pr.get("title", ""),
                                             f"Run cargo test -p {' -p '.join(crates)}\n{out}", ask_claude_hard)
            if not fixed and asker is ask and claude.ready():   # then Claude with whole files, declaration bodies
                fixed, how = rust_fix.repair(tree, REPO, pr.get("title", ""),   # and the base's diff (#239: main
                                             f"Run cargo test -p {' -p '.join(crates)}\n{out}", ask_claude_hard,
                                             rounds=2, wide=f"HEAD...origin/{BASE}")   # had moved a trait)
            if fixed:
                sh(["git", "add", "-u"], cwd=tree)
                ok, fails, crates, out = rust_fix.crate_tests(tree, code + moved)
                row["why"] += f"; fixed the merged build: {how[:200]}"
        row["tests"] += [f"cargo test -p {' -p '.join(crates)}"]
        names = rust_fix.failed_names(out) if not ok and not rust_fix.errors(out) else []
        if names and rust_fix.pass_alone(tree, crates, names):   # timing tests that fail only under load (#389, #235)
            ok = True
            row["why"] += f"; {len(names)} test(s) failed only under load and passed run alone: {', '.join(names)[:200]}"
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
    if own:                                               # her own branch: fast-forward only (no force)
        if sh(["git", "push", "-q", "origin", f"HEAD:refs/heads/{pr['headRefName']}"], cwd=tree).returncode:
            return {**row, "result": "failed", "why": "push to her own branch failed (it moved?)"}
        return {**row, "fix_pr": f"#{number}", "why": row["why"] + " (on her own branch)"}
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
    if not found and not log.strip() and reran(sha):   # its one rerun is used: done until a new push
        return {"pr": number, "result": "skip", "why": "failed logs expired; this head already had its one CI rerun"}
    if not found and not log.strip():     # logs expire on GitHub: run the failed jobs again, look next time
        n = rerun_failed(sha, number)                     # nothing restarted: not a rerun, or it loops every run
        return {"pr": number, "result": "rerun" if n else "skip",
                "why": f"failed logs expired; reran {n} run(s)" + ("" if n else "; nothing could be restarted")}
    kind, base_why = base_fault(log, pr, fails) if fails and not found else ("", "")
    if kind == "broken":                    # no fix, no rerun: tried again when the base moves (work() marks it so)
        return {"pr": number, "result": "skip", "kind": "base", "why": base_why}
    if kind == "stale":                     # a fresh run on today's base, once the tests pass there
        files = sorted({f["test"].split("::")[0] for f in fails})
        ok, out = on_base(pr, files, python)
        if ok:
            n = 0 if dry else fresh_run(sha, number, pr["baseRefOid"])
            return {"pr": number, "result": "rerun" if n or dry else "skip", "kind": "base", "tests": files,
                    "why": f"{base_why}; all {len(files)} failing file(s) pass here on the head merged with "
                           "today's base; "
                           + ("a fresh CI run on it (closed and reopened)" if n else "no fresh run (dry, or done)")}
        if ok is None:
            return {"pr": number, "result": "skip", "kind": "base", "why": f"{base_why}; {out}"}
    linting = not fails and bool(RUFF_CI.search(log))
    typing = None if found or fails or linting else TYPE_CI.search(log)   # fails the same every run: fix, no rerun
    ci_types = ("new pyright errors: " + " | ".join(re.findall(r"\S+\.py:\d+: [^\n]*", typing.group(1)))[:300]
                if typing else "")
    react = None if found or fails or linting or typing or not REACT_CI.search(log) else frontend_failures(log)
    ci_react = ("React UI fails: " + " | ".join(
        [f"{e['file']}({e['line']}): {e['code']} {e['message']}" for e in react["tsc"][:3]] +
        [f"FAIL {t['file']} > {t['test']}" for t in react["vitest"][:3]]))[:300] if react else ""
    if not found and not fails and not linting and not typing and not react:   # timeout, lost runner, setup (seen: #700 died after 9 h): one rerun
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
    elif react:
        diff = gh("pr", "diff", str(number), "--repo", REPO, timeout=300)
        ok, why, round_no = fix_frontend(tree, asker, title=pr.get("title", ""), diff=diff)
        if round_no == 0 and ok:                            # passes here: flaky (vitest under load), one rerun
            return {"pr": number, "result": "flaky-rerun", "kind": "frontend",
                    "why": f"{why}; reran {rerun_failed(sha, number)} failed run(s) once"}
        if round_no == 0:                                   # cannot run it here: report what CI said, no rerun
            return {"pr": number, "result": "failed", "kind": "frontend", "why": f"{ci_react} ({why})"}
        tests = ["tsc", "vitest"]
    else:
        diff = gh("pr", "diff", str(number), "--repo", REPO, timeout=300)
        ok, why, round_no = repair(tree, pr.get("title", ""), fails, out, tests, python, asker, diff)
        if not ok and why.startswith(FLAKY):
            return {"pr": number, "result": "flaky-rerun", "tests": tests,
                    "why": f"{why}; reran {rerun_failed(sha, number)} failed run(s) once"}
        if not ok and asker is ask and claude.ready():
            ok, why, round_no = repair(tree, pr.get("title", ""), fails, out, tests, python, ask_claude_hard, diff)
    if not ok:
        return {"pr": number, "result": "failed", "rounds": ROUNDS, "tests": tests, "why": why}
    changed = [ln[3:] for ln in sh(["git", "status", "--porcelain"], cwd=tree).stdout.splitlines()]
    row = {"pr": number, "result": "fixed", "round": round_no, "why": why, "tests": tests, "files": changed}
    built = build_check.run(tree, changed, python)              # what her edit touches still builds and passes
    row["build"] = {"ran": built["ran"], "seconds": built["seconds"]}
    if not built["ok"]:
        return {**row, "result": "failed", "why": f"{why}; but then {built['failed']}"[:400]}
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
    if not ok and asker is ask and claude.ready():
        ok, why = rust_fix.repair(tree, REPO, pr.get("title", ""), log, ask_claude_hard)
        why += " (with Claude)" if ok else ""
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
LEARNING = threading.Lock()          # one learn_loop.after_fix at a time
WORKERS_AWAY, WORKERS_ACTIVE = 3, 1  # PRs at once: the owner away (no input for 10 min) / at the PC


def workers() -> int:
    return WORKERS_AWAY if rust_fix.away() else WORKERS_ACTIVE


def log_row(t: float, row: dict) -> None:
    line = json.dumps({"ts": round(t), **row})
    with LOGGED:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(json.dumps(row), flush=True)
    try:                                  # every real fix or failure becomes a bench item (+ a lesson to gate)
        from litha.learn_loop import after_fix
        with LEARNING:                    # workers share its queue/pending files (read-modify-write)
            after_fix(row)
    except Exception:  # noqa: BLE001 - learning never costs a fix run
        pass
    if LOG == Path.home() / ".star" / "pr-fixer" / "fixes.jsonl":    # the real log only (tests point LOG elsewhere)
        try:                              # her experience memory: the row's lesson + settle the lessons she was shown
            from litha import experience
            experience.record_fix({**row, "repo": row.get("repo") or REPO, "ts": round(t)})
        except Exception:  # noqa: BLE001 - learning never costs a fix run
            pass


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
    context_pack.REJECT_LOG = STATE.parent / "rejected-edits.jsonl"   # why each edit of hers was refused
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
        seen = (pr["headRefOid"], f"{pr['headRefOid']}^{pr.get('baseRefOid')}")   # head, or head on this base
        if pr.get("isDraft") or pr.get("baseRefName") != BASE or tried.get(str(pr["number"])) in seen:
            return None
        if pr.get("mergeable") == "CONFLICTING":           # her own litha/ PRs too: on their own branch
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
            mark(str(pr["number"]), seen[1] if row.get("kind") == "base" else seen[0])   # base fault: when it moves
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
