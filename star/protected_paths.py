"""Protected closure (W2 of docs/research/self-improving-star-claude-v2.md): a generator never edits its own yardstick.

A *generator* is anything that proposes changes to STAR by itself: the ChatGPT/Codex autopilot, night school's outbox
pull requests, STAR's self-builder and GitHub App, and any later generator. Their work branches are recognised by
name (the convention below). A diff from a generator branch must not touch the evaluation closure: the evaluation
suites and the blind holdout, stored results, the graders and the gate code, night school's validation and
promotion code, CI workflows, and this guard with its tests.

Branch-name convention for generators (case-insensitive):
    star/chatgpt-*            ChatGPT / Codex autopilot work (every branch the autopilot opens)
    star/autopilot-*          any other autopilot
    star/night-school-outbox-*, star/outbox-*   night school's learned-lesson / worked-example pull requests
    star/selfbuild-*, star/genesis-*            STAR's self-builder and its GitHub App
    star/gen-*                any future generator (use this prefix when adding one)

Integrity gate (issue #562, no owner click): a generator diff that only ADDS evaluation material passes by itself:
new files under evals/ (not evals/sealed/ or evals/results/), and new tasks appended to an existing task-list JSON
while every existing task stays byte-for-byte the same. Anything that edits or deletes an existing task, a test, a
reference, a grader, the gate, a sealed manifest, night school's promotion code or CI is still refused, because it
could make grading easier. Work that legitimately changes the closure (a new holdout by its custodian, a grader fix)
is done on a branch that is not a generator branch. The label `owner-approved-eval-change` remains a manual
override on GitHub; `star commit` in the workspace has no override.

Limits (said once, plainly): the guard keys on branch names, so it stops generators that follow the convention, not
a person or process that names a branch otherwise. The label override is only as strong as who can add labels.

    python -m star.protected_paths --branch star/chatgpt-x --base origin/star/next     # exit 1 on a violation
    python -m star.protected_paths --branch star/chatgpt-x --files evals/a.json star/x.py
    python -m star.protected_paths --branch star/chatgpt-x --files evals/a.json --base-sha B --head-sha H  # + gate
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

OWNER_LABEL = "owner-approved-eval-change"

GENERATOR_BRANCH_PATTERNS = (
    "star/chatgpt-*",
    "star/autopilot-*",
    "star/night-school-outbox-*",
    "star/outbox-*",
    "star/selfbuild-*",
    "star/genesis-*",
    "star/gen-*",
)

PROTECTED_PATH_PATTERNS = (
    "evals/**",                                   # suites, the blind holdout (evals/roblox/holdout-*), results
    "star/eval_gate.py",
    "star/eval_runner.py",
    "star/eval_checks.py",
    "star/eval_sandbox.py",
    "star/eval_stats.py",
    "star/protected_paths.py",
    "server/night_school/nightschool/pool.py",    # validation selection and the holdout guard
    "server/night_school/nightschool/engine.py",  # promotion and retirement decisions
    "server/night_school/nightschool/config.py",  # validation size, samples, alpha
    "tests/test_eval_*.py",
    "tests/test_protected_closure.py",
    ".github/workflows/**",
)


def _regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out), re.IGNORECASE)


_BRANCH_RES = tuple(_regex(p) for p in GENERATOR_BRANCH_PATTERNS)
_PATH_RES = tuple((p, _regex(p)) for p in PROTECTED_PATH_PATTERNS)


def norm(path: str) -> str:
    path = str(path).strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path.lstrip("/")


def is_generator_branch(branch: str) -> bool:
    name = str(branch or "").strip()
    for prefix in ("refs/heads/", "origin/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return any(r.fullmatch(name) for r in _BRANCH_RES)


def protected_pattern(path: str) -> str | None:
    """The protected pattern that covers `path`, or None."""
    p = norm(path)
    for pattern, regex in _PATH_RES:
        if regex.fullmatch(p):
            return pattern
    return None


def violations(branch: str, paths, *, owner_approved: bool = False) -> list[tuple[str, str]]:
    """[(path, pattern)] that a diff from `branch` may not touch; empty for non-generator branches or with the
    owner's approval label."""
    if owner_approved or not is_generator_branch(branch):
        return []
    found = []
    for path in paths:
        pattern = protected_pattern(path)
        if pattern and (norm(path), pattern) not in found:
            found.append((norm(path), pattern))
    return found


def changed_files(base: str, head: str = "HEAD", cwd=None) -> list[str]:
    """Files touched between the merge base of `base` and `head` (both sides of a rename)."""
    done = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"], cwd=cwd,
                          capture_output=True)
    if done.returncode != 0:
        raise RuntimeError("git diff failed: " + done.stderr.decode("utf-8", "replace").strip()[:300])
    return [p for p in done.stdout.decode("utf-8", "replace").split("\0") if p]


# --- integrity gate: additions only (self-contained: CI runs this file alone from the base branch) ----------------

ADDITIVE_ROOT = "evals/"
NEVER_ADDITIVE = ("evals/sealed/", "evals/results/")


def _blob(rev: str, path: str, cwd=None) -> bytes | None:
    done = subprocess.run(["git", "--no-replace-objects", "show", f"{rev}:{path}"], cwd=cwd, capture_output=True)
    return done.stdout if done.returncode == 0 else None


def additive_problem(path: str, old: bytes | None, new: bytes | None) -> str:
    """'' when the change to `path` only adds evaluation material, else why it is refused."""
    p = norm(path)
    if not p.startswith(ADDITIVE_ROOT) or p.startswith(NEVER_ADDITIVE):
        return "not evaluation data (graders, gate, CI, sealed manifests and results are never additive)"
    if new is None:
        return "file deleted"
    if old is None:
        return ""                                   # a new file: new tasks, tests or references
    if old == new:
        return ""
    if not p.endswith(".json"):
        return "existing file edited (tests and references may not change)"
    try:
        before, after = json.loads(old.decode("utf-8")), json.loads(new.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "not readable JSON"
    if not (isinstance(before, list) and isinstance(after, list)):
        return "existing JSON edited (only task lists may grow)"
    if after[:len(before)] != before:
        return "existing tasks edited, removed or reordered (only appending new tasks is allowed)"
    ids = [t.get("id") for t in after if isinstance(t, dict)]
    if len(ids) != len(after) or len(set(ids)) != len(ids):
        return "new tasks need unique ids"
    return ""


def integrity_violations(found: list[tuple[str, str]], base_sha: str, head_sha: str, cwd=None) -> list[tuple[str, str]]:
    """The violations the additions-only gate cannot clear (empty = every protected change only adds material)."""
    left = []
    for path, pattern in found:
        problem = additive_problem(path, _blob(base_sha, path, cwd), _blob(head_sha, path, cwd))
        if problem:
            left.append((path, f"{pattern}; {problem}"))
    return left


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.protected_paths", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--branch", required=True, help="the branch the diff comes from (a PR's head branch)")
    parser.add_argument("--base", default="", help="compare HEAD with the merge base of this ref")
    parser.add_argument("--files", nargs="*", default=None, help="check these paths instead of a git diff")
    parser.add_argument("--labels", default="", help="comma list of the PR's labels (CI)")
    parser.add_argument("--base-sha", default="", help="with --head-sha: run the additions-only integrity gate")
    parser.add_argument("--head-sha", default="")
    args = parser.parse_args(argv)
    labels = {x.strip() for x in args.labels.split(",") if x.strip()}
    if not is_generator_branch(args.branch):
        print(f"protected closure: '{args.branch}' is not a generator branch; nothing to check")
        return 0
    try:
        paths = list(args.files) if args.files is not None else changed_files(args.base or "origin/star/next")
    except (OSError, RuntimeError) as exc:
        print(f"protected closure: cannot list the changed files ({exc})", file=sys.stderr)
        return 2
    found = violations(args.branch, paths, owner_approved=OWNER_LABEL in labels)
    if OWNER_LABEL in labels and violations(args.branch, paths):
        print(f"protected closure: label '{OWNER_LABEL}' present: protected paths allowed for this PR")
    base_sha = args.base_sha
    if not base_sha and args.files is None:
        done = subprocess.run(["git", "merge-base", args.base or "origin/star/next", "HEAD"], capture_output=True, text=True)
        base_sha = done.stdout.strip() if done.returncode == 0 else ""
    head_sha = args.head_sha or ("HEAD" if args.files is None else "")
    if found and base_sha and head_sha:
        cleared = len(found)
        found = integrity_violations(found, base_sha, head_sha)
        if not found:
            print(f"protected closure: integrity gate passed ({cleared} protected file(s), additions only)")
    if not found:
        print(f"protected closure: OK ({len(paths)} changed files from generator branch '{args.branch}')")
        return 0
    print(f"protected closure: REFUSED - generator branch '{args.branch}' touches the evaluation closure:", file=sys.stderr)
    for path, pattern in found:
        print(f"  {path}  (protected by {pattern})", file=sys.stderr)
    print("Generators may not edit evals, graders, the holdout, stored results or the gate. Move these changes to a "
          f"non-generator branch for owner review, or the owner adds the label '{OWNER_LABEL}'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
