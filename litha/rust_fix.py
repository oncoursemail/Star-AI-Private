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
import threading

ROUNDS = 4
JOBS = "4"                                   # a third of this PC's 12 threads: the owner keeps working meanwhile
BUILD = threading.RLock()                    # cargo runs one at a time, however many PRs she works on at once


def away(minutes: float = 10) -> bool:
    """No keyboard or mouse input for `minutes` (her task runs in the owner's session): she may use more of the PC."""
    import ctypes

    class Info(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint), ("time", ctypes.c_uint)]
    info = Info(ctypes.sizeof(Info), 0)
    if os.name != "nt" or not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return False
    return ((ctypes.windll.kernel32.GetTickCount() - info.time) & 0xFFFFFFFF) / 1000 >= minutes * 60


def jobs() -> str:
    return "8" if away() else JOBS
ERROR = re.compile(r"^(error(?:\[E\d+\])?: .+)\n(?:.*\n){0,3}?\s*--> ([^\s:]+):(\d+):\d+", re.M)
RUN = re.compile(r"^(?:##\[group\])?Run (cargo .+)$", re.M)
PROMPT = """You are Litha, fixing a pull request in {repo} (Rust) so it builds and passes its checks again.
PR title: {title}
The checks that must pass: {commands}
The compiler's errors:
{errors}

The real code around every error (line numbers on the left, do not copy them):
{code}

Where the names in the errors are declared, and the crate features (cfg lines matter: a check run with
--no-default-features does not see items behind a default feature):
{names}
{feedback}
Fix the cause with the smallest correct change. You may edit any file shown, including a test file that cannot
compile (for example a missing #![cfg(feature = ...)] gate or import), but never remove a test or an assertion.
If a test uses items that a feature gates and the check turns that feature off, gate the test (put
#![cfg(feature = "<that feature>")] as the first line of the test file); do not change the library's feature gates.
Copy "find" text character for character from the code shown, blank lines included.
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
    head, _, tail = " ".join(args).partition(" -- ")
    own = any(a == "--jobs" or a.startswith(("-j", "--jobs=")) for a in head.split())   # CI may set its own
    extra = ["-j", jobs()] if args[0] in ("test", "build", "check", "clippy") and not own else []
    cmd = [cargo(), *head.split(), *extra, *(["--", *tail.split()] if tail else [])]
    try:
        with BUILD:
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


NAME = re.compile(r"`[&*]?(?:[\w:]*::)?([A-Za-z_]\w{2,})`")


def declarations(tree: Path, errs: list[dict], budget: int = 4000) -> str:
    """Each name an error mentions: its declaration or re-export with the two lines above it (the #[cfg]), plus the
    [features] of the Cargo.toml nearest each error file."""
    names = list(dict.fromkeys(n for e in errs for n in NAME.findall(e["error"])))[:8]
    parts: list[str] = []
    for e in errs:
        for d in Path(e["file"]).parents:
            toml = tree / d / "Cargo.toml"
            if toml.is_file():
                m = re.search(r"^\[features\]\n(?:(?!\[).*(?:\n|$))*", toml.read_text(encoding="utf-8", errors="replace"), re.M)
                if m and f"--- {toml.relative_to(tree).as_posix()}" not in "\n".join(parts):
                    parts.append(f"--- {toml.relative_to(tree).as_posix()}\n{m.group(0).strip()}")
                break
    if names:
        decl = re.compile(r"\b(?:struct|enum|trait|type|fn|mod)\s+(?:" + "|".join(names) + r")\b|\bpub use\b.*\b(?:"
                          + "|".join(names) + r")\b")
        for f in sorted(tree.rglob("*.rs")):
            rel = f.relative_to(tree).as_posix()
            if rel.startswith(("target/", ".git/")) or "/tests/" in f"/{rel}":
                continue
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(lines):
                if decl.search(line):
                    parts.append(f"--- {rel}:{i + 1}\n" + "\n".join(lines[max(0, i - 2):i + 1]))
    out, used = [], 0
    for p in parts:
        if used + len(p) > budget:
            break
        out.append(p)
        used += len(p)
    return "\n".join(out) or "(none found)"


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


FAILED_TEST = re.compile(r"^---- (\S+) stdout ----\n(?:.*\n){0,6}?.*panicked at [^\n]*\n([^\n]*)", re.M)


def crate_tests(tree: Path, files: list[str]) -> tuple[bool, str, list[str], str]:
    """(passed, failures, packages, output): the tests of every crate a merged .rs file belongs to. A merge can compile and
    still be wrong (both sides fixed one bug two ways, and one side's test now fails); this catches it before a push."""
    packages: list[str] = []
    for f in files:
        if not f.endswith(".rs"):
            continue
        for d in Path(f).parents:
            toml = tree / d / "Cargo.toml"
            m = re.search(r'^\[package\][^\[]*?^name\s*=\s*"([^"]+)"', toml.read_text(encoding="utf-8"), re.M | re.S) \
                if toml.is_file() else None
            if m:
                packages += [m.group(1)] if m.group(1) not in packages else []
                break
    if not packages:
        return True, "", [], ""
    ok, out = run(tree, ["test", *[a for p in packages for a in ("-p", p)]])
    fails = "; ".join(f"{name}: {why.strip()[:200]}" for name, why in FAILED_TEST.findall(out)[:4])
    return ok, fails or out[-600:], packages, out


def failed_names(out: str) -> list[str]:
    """The tests libtest reports as failed (each `---- name stdout ----` section), each once."""
    return list(dict.fromkeys(re.findall(r"^---- (\S+) stdout ----$", out, re.M)))


def pass_alone(tree: Path, packages: list[str], names: list[str]) -> bool:
    """True when the crates' tests pass with `names` run on their own, one thread, and every other test passes as
    usual. Studio's timing tests (a 1 s budget for a 100 KB pattern, retried 5 times) fail in a debug build while the
    PC is busy (seen: #389 and #235, two unrelated PRs, the same test); cargo test also stops at the first failing
    test binary, so the rest is run too before the merge counts as passing."""
    if not packages or not names or len(names) > 3:
        return False
    pk = [a for p in packages for a in ("-p", p)]
    ok, _ = run(tree, ["test", *pk, "--no-fail-fast", "--", "--exact", *[a for n in names for a in ("--skip", n)]])
    if not ok:
        return False
    ok, _ = run(tree, ["test", *pk, "--", "--exact", "--test-threads=1", *names])
    return ok


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


BLOCK = re.compile(r"^error(?:\[E\d+\])?: .*\n(?:(?!error|warning).*\n?)*", re.M)
TYPE_NAME = re.compile(r"\b([A-Z][A-Za-z0-9]{2,})\b")


def error_text(log: str, budget: int = 12000) -> str:
    """rustc's error blocks in full (the notes and `expected ... found` lines say what changed), without warnings."""
    out, used = [], 0
    for m in BLOCK.finditer(log):
        block = m.group(0).rstrip()
        if used + len(block) > budget:
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


def whole_files(tree: Path, errs: list[dict], budget: int = 60000, long: int = 500, around: int = 120) -> str:
    """Every erroring file in full, numbered: a merge breaks code far from the conflict (seen: Studio #428, a struct
    literal in debug_views.rs, which had no conflict, after main changed a field's type). A file over `long` lines
    shows `around` lines either side of each of its errors instead, so one big file cannot crowd out the others
    (#428: a test file that needed a feature gate came after a 3000-line one)."""
    parts, used = [], 0
    files = list(dict.fromkeys(e["file"] for e in errs))
    for k, name in enumerate(files):
        f = tree / name
        if not f.is_file():
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        keep = set(range(len(lines)))
        if len(lines) > long:
            keep = {i for e in errs if e["file"] == name
                    for i in range(max(0, e["line"] - around), min(len(lines), e["line"] + around))}
        shown, last = [], -1
        for i in sorted(keep):
            if i != last + 1:
                shown.append("...")
            shown.append(f"{i + 1}: {lines[i]}")
            last = i
        block = f"--- {name}\n" + "\n".join(shown + (["..."] if last < len(lines) - 1 else []))
        share = (budget - used) // (len(files) - k)          # what is left, split over the files still to show
        if len(block) > share:
            block = block[:max(0, share)] + "\n... (cut)"
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)


def near_types(tree: Path, errs: list[dict], around: int = 12, limit: int = 10) -> list[str]:
    """Type-like names (CamelCase) in the lines around each error: the struct a literal builds, the trait a call
    goes through. The error itself often names only `u32` or a field."""
    names: list[str] = []
    for e in errs:
        f = tree / e["file"]
        if f.is_file():
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            for ln in lines[max(0, e["line"] - around):e["line"] + 2]:
                names += [n for n in TYPE_NAME.findall(ln) if n not in names and n not in ("Self", "Some", "None",
                                                                                           "Ok", "Err", "Vec", "String")]
    return names[:limit]


def bodies(tree: Path, names: list[str], budget: int = 12000) -> str:
    """Each name's declaration in full (a struct's fields, an enum's variants, a fn's signature), with the lines
    above it (docs, #[cfg])."""
    if not names:
        return ""
    decl = re.compile(r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+|unsafe\s+|const\s+)*"
                      r"(struct|enum|trait|type|fn|const|static)\s+(?:" + "|".join(map(re.escape, names)) + r")\b")
    parts, used = [], 0
    for f in sorted(tree.rglob("*.rs")):
        rel = f.relative_to(tree).as_posix()
        if rel.startswith(("target/", ".git/")):
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = decl.match(line)
            if not m:
                continue
            j, depth, opened = i, 0, False             # a fn: its signature; a type: all of it (80 lines at most)
            while j < len(lines) - 1 and j < i + 80:
                depth += lines[j].count("{") - lines[j].count("}")
                opened = opened or "{" in lines[j]
                if lines[j].rstrip().endswith(";") and not opened or opened and (m.group(1) == "fn" or depth <= 0):
                    break
                j += 1
            block = f"--- {rel}:{i + 1}\n" + "\n".join(lines[max(0, i - 3):j + 1])
            if used + len(block) > budget:
                return "\n".join(parts)
            parts.append(block)
            used += len(block)
    return "\n".join(parts)


WIDE = """You are fixing a merge in {repo} (Rust): the newest base branch was merged into a pull request, every conflict
was resolved, but the merged code does not build. Usually one side changed a type, field, function or import that
the other side's code still uses the old way. Make the merged code build with BOTH sides' intent kept: adapt the
code that uses the old form to the new one; never undo what the base branch changed and never drop a feature.
PR title: {title}
The checks that must pass: {commands}

The compiler's errors in full:
{errors}

Every file with an error, in full (line numbers on the left, do not copy them):
{code}

Declarations of the names involved (with the lines above them):
{names}

Re-exports and the crate features (cfg lines matter: a check run with --no-default-features does not see items behind
a default feature):
{features}

What the base branch changed since the PR branched, in the files that declare those names or have the errors:
{changed}
{feedback}
If a test uses items that a feature gates and a check turns that feature off, gate the test (put
#![cfg(feature = "<that feature>")] as the first line of the test file); do not change the library's feature gates.
Copy "find" text character for character from the code shown, blank lines included; never remove a test or an
assertion. Answer only JSON: {{"why": "<one sentence: the cause>", "edits": [{{"file": "<path>", "find": "<exact
existing text, a few whole lines, unique in the file>", "replace": "<new text>"}}]}}"""


def wide_prompt(tree: Path, repo: str, title: str, cmds: list[list[str]], out: str, errs: list[dict], since: str,
                feedback: str) -> str:
    """Claude's repair prompt: whole erroring files, full error text, declaration bodies and the base's diff of the
    files involved (`since` = a git range, e.g. HEAD...origin/main)."""
    names = list(dict.fromkeys(n for e in errs for n in NAME.findall(e["error"]))) + near_types(tree, errs)
    names = list(dict.fromkeys(names))[:16]
    found = bodies(tree, names)
    files = list(dict.fromkeys([e["file"] for e in errs] + re.findall(r"^--- ([^\s:]+):\d+$", found, re.M)))
    diff = ""
    if since and files:
        r = subprocess.run(["git", "diff", "--no-color", "--no-ext-diff", since, "--", *files], cwd=tree,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        diff = r.stdout[:12000] + ("\n... (cut)" if len(r.stdout) > 12000 else "")
    return WIDE.format(repo=repo, title=title, commands="; ".join("cargo " + " ".join(c) for c in cmds),
                       errors=error_text(out) or "\n".join(f"{e['file']}:{e['line']}: {e['error']}" for e in errs),
                       code=whole_files(tree, errs), names=found or "(none found)", features=declarations(tree, errs),
                       changed=diff or "(no change found)", feedback=feedback)


def repair(tree: Path, repo: str, title: str, log: str, ask, rounds: int = ROUNDS, wide: str = "") -> tuple[bool, str]:
    """(fixed, why). `log` is the failed CI log; the checks it ran decide, plus the repo's clippy steps. wide = a git
    range of what the base changed (e.g. HEAD...origin/main): the prompt for a big-window model (Claude), with whole
    files, full errors, declaration bodies and that diff instead of excerpts cut to her 4K window."""
    cmds = checks(log)
    if not cmds:
        return False, "no cargo command found in the failed job log"
    cmds += [c for c in later_checks(tree) if c not in cmds]
    limit = 12 if wide else 4
    errs, feedback, cause = errors(log, limit), "", ""
    for n in range(rounds + 1):
        ok, out = verify(tree, cmds)
        if ok:
            return True, (f"{cause} " if cause else "") + \
                f"(checked: {', '.join('cargo ' + ' '.join(c) for c in cmds)}; {n} round(s))"
        errs = errors(out, limit) or errs
        if n == rounds or not errs:
            return False, "still failing: " + (" | ".join(e["error"] for e in errs) or out[-300:])
        prompt = wide_prompt(tree, repo, title, cmds, out, errs, wide, feedback) if wide else PROMPT.format(
            repo=repo, title=title, code=excerpts(tree, errs), feedback=feedback,
            commands="; ".join("cargo " + " ".join(c) for c in cmds), names=declarations(tree, errs),
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
