"""Litha repairs a Rust PR whose CI failed to build, lint or format (the owner's other repos, e.g. Metallic Studio).

1. the failed job log gives the cargo commands that ran and rustc's errors (`error[E..]: ...` + `--> file:line`);
2. formatting is fixed without her (`cargo fmt`), everything else by her search/replace edits on the real code;
3. the same cargo commands run locally as compile-only checks (`cargo test --no-run`, clippy as CI runs it), up to
   ROUNDS rounds with the new errors each time; only a clean run counts.
A test file may be edited (a test can fail to compile behind a feature flag) but no test or assertion may disappear.

    used by litha.pr_fixer --others; the pieces are plain functions so tests can drive them without cargo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROUNDS = 4
JOBS = "4"                                   # a third of this PC's 12 threads: the owner keeps working meanwhile
ERROR = re.compile(r"^(error(?:\[E\d+\])?: .+)\n(?:.*\n){0,3}?\s*--> ([^\s:]+):(\d+):\d+", re.M)
RUN = re.compile(r"^(?:##\[group\])?Run (cargo .+)$", re.M)
PROMPT = """You are Litha, fixing a pull request in {repo} (Rust) so it builds and passes its checks again.
PR title: {title}
The compiler's errors:
{errors}

The real code around every error (line numbers on the left, do not copy them):
{code}
{feedback}
Fix the cause with the smallest correct change. You may edit any file shown, including a test file that cannot
compile (for example a missing #![cfg(feature = ...)] gate or import), but never remove a test or an assertion.
Answer only JSON: {{"why": "<one sentence: the cause>", "edits": [{{"file": "<path>", "find": "<exact existing text,
a few whole lines, unique in the file>", "replace": "<new text>"}}]}}"""


def cargo() -> str:
    return shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo.exe")


def errors(log: str, limit: int = 4) -> list[dict]:
    """rustc's errors with their first location, each once."""
    out, seen = [], set()
    for m in ERROR.finditer(log):
        path = m.group(2).replace("\\", "/")
        key = (m.group(1), path, int(m.group(3)))
        if key not in seen:
            seen.add(key)
            out.append({"error": m.group(1).strip(), "file": path, "line": int(m.group(3))})
    return out[:limit]


def checks(log: str) -> list[list[str]]:
    """The failed CI job's cargo commands as local compile-only checks."""
    out: list[list[str]] = []
    for m in RUN.finditer(log):
        args = m.group(1).split(" -- ")[0].split()[1:]
        if args[:2] == ["nextest", "run"]:
            args = ["test", "--no-run", "--workspace"]
        elif args[:1] == ["test"]:
            args = ["test", "--no-run", *args[1:]]
        elif args[:1] == ["clippy"]:
            args = [*m.group(1).split()[1:]]                    # with its -- -D warnings: warnings are the check
        elif args[:1] not in (["build"], ["check"], ["fmt"]):
            continue
        if args not in out:
            out.append(args)
    return out


def run(tree: Path, args: list[str], timeout: float = 2400) -> tuple[bool, str]:
    env = {**os.environ, "CARGO_TERM_COLOR": "never",
           "CARGO_TARGET_DIR": str(Path.home() / ".star" / "litha-cargo" / tree.parent.name.replace(" ", "_"))}
    extra = ["-j", JOBS] if args[0] in ("test", "build", "check", "clippy") else []
    head, _, tail = " ".join(args).partition(" -- ")
    cmd = [cargo(), *head.split(), *extra, *(["--", *tail.split()] if tail else [])]
    try:
        r = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout:.0f} s: cargo {' '.join(args)}"
    return r.returncode == 0, (r.stdout + r.stderr)[-12000:]


def verify(tree: Path, cmds: list[list[str]]) -> tuple[bool, str]:
    for args in cmds:
        if args[:2] == ["fmt", "--check"] or args == ["fmt"]:
            run(tree, ["fmt"])                                   # formatting: no judgement needed
        ok, out = run(tree, args)
        if not ok:
            return False, out
    return True, ""


def excerpts(tree: Path, errs: list[dict], around: int = 20, budget: int = 9000) -> str:
    parts, used = [], 0
    for e in errs:
        f = tree / e["file"]
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        lo, hi = max(0, e["line"] - around), min(len(lines), e["line"] + around)
        block = f"--- {e['file']}\n" + "\n".join(f"{i + 1}: {lines[i]}" for i in range(lo, hi))
        if used + len(block) > budget:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


TESTS = re.compile(r"#\[(?:tokio::)?test\]|\bassert(?:_eq|_ne)?!")


def apply(tree: Path, edits: list) -> list[str]:
    """Her search/replace edits; an edit that removes a test or an assertion, or leaves the tree, is refused."""
    problems = []
    for e in edits if isinstance(edits, list) else []:
        try:
            path, find, new = str(e["file"]).replace("\\", "/").lstrip("./"), str(e["find"]), str(e["replace"])
        except (KeyError, TypeError):
            problems.append("an edit lacked file/find/replace")
            continue
        f = (tree / path).resolve()
        if tree.resolve() not in f.parents or path.startswith(".github/") or path.endswith("Cargo.lock"):
            problems.append(f"{path}: you may not edit this file")
            continue
        if not f.is_file():
            problems.append(f"{path}: no such file")
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(find) if find else 0
        if n != 1:
            problems.append(f"{path}: 'find' matched {n} times, it must match exactly once")
            continue
        if len(TESTS.findall(new)) < len(TESTS.findall(find)):
            problems.append(f"{path}: that edit removes a test or an assertion; fix the code instead")
            continue
        f.write_bytes(text.replace(find, new).encode("utf-8"))
    return problems


CLIPPY = re.compile(r"^\s*(?:-\s*)?run:\s*(cargo clippy[^\n#]*)", re.M)


def later_checks(tree: Path) -> list[list[str]]:
    """The repo's clippy steps: CI never reached them when the build failed first, but they run after her fix."""
    found = []
    for wf in sorted((tree / ".github" / "workflows").glob("*.y*ml")):
        for m in CLIPPY.finditer(wf.read_text(encoding="utf-8", errors="replace")):
            args = m.group(1).split()[1:]
            if args not in found:
                found.append(args)
    return found


def repair(tree: Path, repo: str, title: str, log: str, ask, rounds: int = ROUNDS) -> tuple[bool, str]:
    """(fixed, why). `log` is the failed CI log; the checks it ran decide, plus the repo's clippy steps."""
    cmds = checks(log)
    if not cmds:
        return False, "no cargo command found in the failed job log"
    cmds += [c for c in later_checks(tree) if c not in cmds]
    errs, feedback, cause = errors(log), "", ""
    for n in range(rounds + 1):
        ok, out = verify(tree, cmds)
        if ok:
            return True, (f"{cause} " if cause else "") + \
                f"(checked: {', '.join('cargo ' + ' '.join(c) for c in cmds)}; {n} round(s))"
        errs = errors(out) or errs
        if n == rounds or not errs:
            return False, "still failing: " + (" | ".join(e["error"] for e in errs) or out[-300:])
        prompt = PROMPT.format(repo=repo, title=title, code=excerpts(tree, errs), feedback=feedback,
                               errors="\n".join(f"{e['file']}:{e['line']}: {e['error']}" for e in errs))
        try:
            ans = json.loads(ask(prompt))
        except (ValueError, TypeError):
            feedback = "Your last answer was not valid JSON.\n"
            continue
        cause = str(ans.get("why") or cause)[:160]
        problems = apply(tree, ans.get("edits") or [])
        feedback = ("Problems with your last edits: " + "; ".join(problems) + "\n") if problems else ""
    return False, "no fix found"
