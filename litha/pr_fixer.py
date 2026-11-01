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
import datetime as dt
import json
import shutil
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib

from litha import rust_fix
from litha.pr_merger import BASE, REPO, gh, head_checks, open_prs

ROOT = Path(__file__).resolve().parents[1]                  # the worktree this runs from
WORK = ROOT.parent                                          # worktrees/
CLONE = ROOT.parents[1] / "Star-AI"
HOME_CLONE = CLONE                                          # STAR's own repo: star commit, Python tests
IDENTITY = ["-c", "user.name=oncoursemail", "-c", "user.email=84545815+oncoursemail@users.noreply.github.com"]
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
            edition = (EDITION.search(cargo) or [None, "2021"])[1]
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
    edition = (EDITION.search(cargo) or [None, "2021"])[1]

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
    for c in code:
        raw = (tree / c).read_text(encoding="utf-8", errors="replace")
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


def others(python: str, limit: int, dry: bool = False) -> int:
    """The owner's other repos with a local clone (repos.json "clone", mode merge): she resolves conflicting PRs on
    her own branch, and reruns a failed check once per head (flaky runners). Their CI and her merger's review decide."""
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
    try:
        for entry in json.loads(pr_merger.REPOS.read_text(encoding="utf-8"))["repos"][1:]:
            if entry.get("mode") != "merge" or not entry.get("clone"):
                continue
            REPO = pr_merger.REPO = entry["repo"]
            BASE = pr_merger.BASE = entry.get("base", "main")
            CLONE = Path(entry["clone"]).expanduser()
            WORK = Path(entry.get("worktrees") or CLONE.parent / f"{CLONE.name}-worktrees").expanduser()
            if not (CLONE / ".git").exists():
                print(f"{REPO}: no clone at {CLONE}", flush=True)
                continue
            prs = open_prs()
            busy = {m.group(1) for p in prs for m in [re.match(r"litha/merge-(\d+)-", p.get("headRefName", ""))] if m}
            done = reruns = repairs = 0
            for pr in prs:
                key = f"{REPO}#{pr['number']}"
                if pr.get("isDraft") or pr.get("baseRefName") != BASE or tried.get(key) == pr["headRefOid"]:
                    continue
                if pr.get("mergeable") == "CONFLICTING" and done < limit and str(pr["number"]) not in busy \
                        and not str(pr.get("headRefName", "")).startswith("litha/"):
                    t = time.time()
                    try:
                        row = resolve(pr, python, dry)
                    except Exception as e:  # noqa: BLE001 - one PR must not stop the others
                        row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
                    done += 1
                elif pr.get("mergeable") == "MERGEABLE" and (reruns < 3 or repairs < 1):
                    checks = head_checks(pr["headRefOid"])
                    if not any(c["conclusion"] == "FAILURE" for c in checks) or \
                            any(c["status"] != "completed" for c in checks):
                        continue
                    t = time.time()
                    log = failed_logs(pr["headRefOid"])
                    if rust_fix.checks(log) and (rust_fix.errors(log) or "Diff in " in log):
                        if repairs >= 1:                  # one build per repo per run: cargo is the slow part
                            continue
                        try:
                            row = fix_rust(pr, log, dry)
                        except Exception as e:  # noqa: BLE001 - one PR must not stop the others
                            row = {"pr": pr["number"], "result": "error", "why": str(e)[:300]}
                        repairs += 1
                    elif reruns < 3:
                        row = {"pr": pr["number"], "result": "flaky-rerun",
                               "why": f"reran {0 if dry else rerun_failed(pr['headRefOid'], pr['number'])} failed "
                                      "run(s) once for this head"}
                        reruns += 1
                    else:
                        continue
                else:
                    continue
                row = {"repo": REPO, **row, "seconds": round(time.time() - t)}
                if not dry:                               # a dry run must not use up the real attempt
                    tried[key] = pr["headRefOid"]
                    STATE.write_text(json.dumps(tried), encoding="utf-8")
                with LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": round(t), **row}) + "\n")
                print(json.dumps(row), flush=True)
    finally:
        REPO, BASE, CLONE, WORK, pr_merger.REPO, pr_merger.BASE = home
        lock.unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m litha.pr_fixer")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--max", type=int, default=1, help="PRs to work on per run")
    ap.add_argument("--dry", action="store_true", help="fix and test locally, do not commit or push")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--others", type=int, metavar="N", help="instead: resolve up to N conflicting PRs per other repo")
    a = ap.parse_args(argv)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if a.others is not None:
        return others(a.python, a.others, a.dry)
    tried = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    done = 0
    from litha.pr_merger import HUNTED
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
