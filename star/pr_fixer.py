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

    python -m star.pr_fixer [--pr N] [--max 1] [--dry]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from star.pr_merger import BASE, REPO, gh, head_checks, open_prs

ROOT = Path(__file__).resolve().parents[1]                  # the worktree this runs from
WORK = ROOT.parent                                          # worktrees/
CLONE = ROOT.parents[1] / "Star-AI"
STATE = Path.home() / ".star" / "pr-fixer" / "tried.json"
LOG = Path.home() / ".star" / "pr-fixer" / "fixes.jsonl"
ROUNDS = 5
NO_TOUCH = re.compile(r"^(tests/|\.github/)|(^|/)(requirements[^/]*\.txt|pnpm-lock\.yaml|[^/]+\.lock)$")
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


def sh(args: list[str], cwd: Path | None = None, timeout: float = 600, env: dict | None = None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env)


def failed_logs(sha: str) -> str:
    """The text of every failed check's job log on this commit (GitHub Actions jobs only)."""
    data = json.loads(gh("api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"))
    out = []
    for c in data.get("check_runs", []):
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
        if NO_TOUCH.search(path) or tree.resolve() not in f.parents:
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
        from star.bug_bench import lessons_text
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


LINT = re.compile(r"^(star/[\w/.-]+\.py):(\d+):\d+: (\w+) (.*)$", re.M)
RUFF_CI = re.compile(r"Ruff \(\w+\)|ruff check star")         # the lint step failed (it runs before pytest in CI)
LINT_PROMPT = """You are Litha, fixing ruff lint errors in STAR's Python code so CI passes. Keep behaviour the same.
Errors, each with the real code around it (line numbers on the left, do not copy them):
{errors}
{feedback}
Fix each error the way the rule intends (remove what is unused, define what is undefined, do not add noqa).
Answer only JSON: {{"why": "<one sentence>", "edits": [{{"file": "<path>", "find": "<exact existing text, unique in
the file>", "replace": "<new text>"}}]}}"""


def lint(tree: Path, python: str) -> list[tuple[str, int, str]]:
    r = sh([python, "-m", "ruff", "check", "star", "--output-format=concise", "--no-cache"], cwd=tree)
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
    every rerun ("cannot be retried", seen on a 4-day-old run), closing and reopening the PR starts a fresh CI run."""
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
    return done


CONFLICT = re.compile(r"^<<<<<<< [^\n]*\n.*?^>>>>>>> [^\n]*\n", re.M | re.S)
MERGE_PROMPT = """You are Litha, resolving a git merge conflict in STAR's repository so a pull request can merge.
Pull request: {title}
Between <<<<<<< and ======= is the PR's version; between ======= and >>>>>>> is the newest star/next.
Keep BOTH sides' intent: the PR's change AND everything star/next added. Never drop a feature, import, test or
setting from either side; when both changed the same line, combine them.
File {path}, conflict {i} of {n} (with the lines around it, which stay as they are):
{context}
{feedback}Answer only JSON: {{"resolved": "<the exact text that replaces the whole conflict block, without markers>"}}"""


def resolve_text(path: str, text: str, title: str, asker=ask) -> tuple[str | None, str]:
    """Every conflict block of one file resolved by her; (None, why) when she cannot make valid code of it."""
    blocks = list(CONFLICT.finditer(text))
    if not blocks or len(blocks) > 8:
        return None, f"{path}: {len(blocks)} conflict blocks (1-8 handled)"
    out, last, feedback = [], 0, ""
    for i, m in enumerate(blocks, 1):
        before = text[max(0, m.start() - 1500):m.start()].split("\n", 1)[-1]
        after = text[m.end():m.end() + 1500].rsplit("\n", 1)[0]
        for _ in range(2):
            try:
                ans = json.loads(asker(MERGE_PROMPT.format(title=title, path=path, i=i, n=len(blocks), feedback=feedback,
                                                           context=before + m.group(0) + after)))
                new = str(ans["resolved"])
            except (ValueError, TypeError, KeyError):
                feedback = "Your last answer was not valid JSON with a \"resolved\" string.\n"
                continue
            if "<<<<<<<" in new or ">>>>>>>" in new or "\n=======\n" in f"\n{new}\n":
                feedback = "Your answer still had conflict markers. Give the merged text only.\n"
                continue
            break
        else:
            return None, f"{path}: no usable answer for conflict {i}"
        out += [text[last:m.start()], new if new.endswith("\n") or not new else new + "\n"]
        last, feedback = m.end(), ""
    merged = "".join(out) + text[last:]
    if path.endswith(".py"):
        try:
            compile(merged, path, "exec")
        except SyntaxError as e:
            return None, f"{path}: merged code does not compile (line {e.lineno}: {e.msg})"
    return merged, ""


def resolve(pr: dict, python: str, dry: bool = False, asker=ask) -> dict:
    """A PR that conflicts with star/next: merge star/next into a copy of it on HER branch, resolve (lock files are
    taken from star/next and rebuilt; code conflicts are hers), prove nothing broke, open her own PR."""
    number = pr["number"]
    day = dt.date.today().strftime("%Y%m%d")
    branch, tree = f"litha/merge-{number}-{day}", WORK / f"litha-merge-{number}"
    if tree.exists():
        sh(["git", "-C", str(CLONE), "worktree", "remove", "--force", str(tree)])
    sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", BASE])
    got = sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", f"pull/{number}/head:{branch}", "--force"])
    if got.returncode:
        return {"pr": number, "result": "skip", "why": "fetch failed: " + got.stderr[-200:]}
    sh(["git", "-C", str(CLONE), "worktree", "add", "-q", str(tree), branch])
    m = sh(["git", "-c", "user.name=oncoursemail", "-c", "user.email=84545815+oncoursemail@users.noreply.github.com",
            "merge", "--no-ff", "--no-commit", f"origin/{BASE}"], cwd=tree)    # per-command identity, never configured
    conflicted = sh(["git", "diff", "--name-only", "--diff-filter=U"], cwd=tree).stdout.split()
    if m.returncode and not conflicted:
        return {"pr": number, "result": "failed", "why": "git merge failed: " + (m.stdout + m.stderr)[-200:]}
    locks = [c for c in conflicted if DEP_FILE.match(c) and c.endswith(".txt")]
    code = [c for c in conflicted if c not in locks]
    if len(code) > 4 or any(NO_TOUCH.search(c) and not DEP_FILE.match(c) for c in code):
        sh(["git", "merge", "--abort"], cwd=tree)
        return {"pr": number, "result": "failed", "why": f"conflicts she does not resolve alone: {code[:8]}"}
    for c in locks:                                         # generated files: star/next's copy, rebuilt below
        sh(["git", "checkout", "--theirs", "--", c], cwd=tree)
    tests: set[str] = set()
    for c in code:
        merged, why = resolve_text(c, (tree / c).read_text(encoding="utf-8", errors="replace"), pr.get("title", ""), asker)
        if merged is None:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {"pr": number, "result": "failed", "why": why}
        (tree / c).write_bytes(merged.encode("utf-8"))
        if c.startswith("tests/") and c.endswith(".py"):
            tests.add(c)
        elif c.endswith(".py"):
            from star.bug_bench import tests_for
            tests.update(tests_for(c[:-3].replace("/", "."), tree / "tests", {})[:3])
    if locks and (tree / LOCK_TOOL).is_file():
        r = sh([python, LOCK_TOOL], cwd=tree, timeout=1800)
        if r.returncode:
            sh(["git", "merge", "--abort"], cwd=tree)
            return {"pr": number, "result": "failed", "why": "lock tool failed: " + (r.stdout + r.stderr)[-200:]}
        tests.add("tests/test_home_installer.py")
    sh(["git", "add", "--", *conflicted], cwd=tree)
    ok, out = run_tests(tree, sorted(tests)[:6], python) if tests else (True, "")
    row = {"pr": number, "result": "fixed" if ok else "failed", "kind": "merge", "files": conflicted,
           "tests": sorted(tests)[:6], "why": "merged star/next and resolved " + ", ".join(conflicted)}
    if not ok:
        sh(["git", "merge", "--abort"], cwd=tree)
        return {**row, "why": "after resolving, tests fail: " + " ".join(FAILED.findall(out))[:250]}
    if dry:
        return row
    c = sh([str(CLONE.parent / "star.cmd"), "commit", "--owner", "claude", "--worktree",
            str(tree.relative_to(CLONE.parent)), "-m", f"[litha] merge star/next into #{number}: {', '.join(conflicted)}"],
           cwd=CLONE.parent)
    if c.returncode:
        return {**row, "result": "failed", "why": "commit refused: " + (c.stdout + c.stderr)[-300:]}
    if sh(["git", "push", "-q", "-u", "origin", branch], cwd=tree).returncode:
        return {**row, "result": "failed", "why": "push failed"}
    body = (f"Litha brought #{number} up to date with star/next (her own branch; the original PR is unchanged).\n\n"
            f"Conflicts resolved: {', '.join(conflicted)}. Lock files were taken from star/next and rebuilt with "
            f"{LOCK_TOOL}.\nTests run after resolving: {', '.join(sorted(tests)[:6]) or 'none touched'}.\n"
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
        return {"pr": number, "result": "rerun", "why": f"failed logs expired; reran {rerun_failed(sha, number)} run(s)"}
    linting = not fails and bool(RUFF_CI.search(log))
    if not found and not fails and not linting:   # timeout, lost runner, setup (seen: #700 died after 9 h): one rerun
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.pr_fixer")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--max", type=int, default=1, help="PRs to work on per run")
    ap.add_argument("--dry", action="store_true", help="fix and test locally, do not commit or push")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tried = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    done = 0
    from star.pr_merger import HUNTED
    hunted = json.loads(HUNTED.read_text(encoding="utf-8")) if HUNTED.exists() else {}
    for pr in open_prs(a.pr):                           # first: bugs her review proved -> her fix with her test
        item = hunted.pop(str(pr["number"]), None)
        if done >= a.max or not item or item.get("head") != pr["headRefOid"] or not item.get("test"):
            continue
        t = time.time()
        try:
            row = fix(pr, a.python, a.dry, found=item)
        except Exception as e:  # noqa: BLE001 - one PR must not stop the others
            row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
        row["seconds"], row["kind"] = round(time.time() - t), "hunted"
        HUNTED.write_text(json.dumps(hunted), encoding="utf-8")
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": round(t), **row}) + "\n")
        print(json.dumps(row), flush=True)
        done += 1
    for pr in open_prs(a.pr):
        if done >= a.max:
            break
        if pr.get("isDraft") or pr.get("baseRefName") != BASE or tried.get(str(pr["number"])) == pr["headRefOid"]:
            continue
        if pr.get("mergeable") == "CONFLICTING" and not str(pr.get("headRefName", "")).startswith("litha/"):
            t = time.time()
            try:
                row = resolve(pr, a.python, a.dry)
            except Exception as e:  # noqa: BLE001 - one PR must not stop the others
                row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
            row["seconds"] = round(time.time() - t)
            tried[str(pr["number"])] = pr["headRefOid"]
            STATE.write_text(json.dumps(tried), encoding="utf-8")
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": round(t), **row}) + "\n")
            print(json.dumps(row), flush=True)
            done += 1
            continue
        if pr.get("mergeable") != "MERGEABLE":                 # her own branches too: flaky reruns
            continue
        checks = head_checks(pr["headRefOid"])
        if not any(c["conclusion"] == "FAILURE" for c in checks) or any(c["status"] != "completed" for c in checks):
            continue
        t = time.time()
        try:
            row = fix(pr, a.python, a.dry)
        except Exception as e:  # noqa: BLE001 - one PR must not stop the others
            row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
        row["seconds"] = round(time.time() - t)
        if row["result"] != "rerun":      # a rerun is looked at again once its fresh log exists
            tried[str(pr["number"])] = pr["headRefOid"]
        STATE.write_text(json.dumps(tried), encoding="utf-8")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(t), **row}) + "\n")
        print(json.dumps(row), flush=True)
        done += row["result"] in ("fixed", "failed", "error", "rerun", "flaky-rerun")   # one CI rerun per run
    return 0


if __name__ == "__main__":
    sys.exit(main())
