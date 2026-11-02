"""Real fixes as bench items: a commit that fixed Python source, replayed backwards.

Item = the fix commit `sha` with its source files `src` taken back to `parent`, and the `tests` that then fail
(they pass on `sha`). Sources, in this order:
  1. ~/.star/pr-fixer/fixes.jsonl: PR failures the fixer logged (Python test files); the commit that later says
     "#<pr>" in its message is the fix (Litha's or a person's), and the logged failing tests join its tests.
  2. git history of star/next: commits whose subject says fix / bug / wrong / regress / broke / deflake, with a
     small source change (1-60 lines) and a test file changed with it.
Only verified items are kept: the tests pass on the fix and FAIL (not a collection error) on the broken code.
A failure on a missing or renamed name counts: real PR failures here are often exactly that (the test is the spec).
The bench file stores the repo, the shas and the paths, nothing else.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from litha import learn_loop as L

FIXISH = re.compile(r"\b(fix|fixes|fixed|bug|wrong|regress\w*|broke|broken|deflake\w*|red)\b", re.I)
SRC = re.compile(r"^(star|server|litha)/(?!.*/tests/)[\w/.-]+\.py$")
TEST = re.compile(r"^tests/test_[\w-]+\.py$")
FEATURE = re.compile(r"errors? during collection|ERROR collecting")   # the test file cannot even load: no fix item
FIXLOG = Path.home() / ".star" / "pr-fixer" / "fixes.jsonl"


def logged_failures(path: Path = FIXLOG) -> dict[int, list[str]]:
    """{pr: failing Python test files} from the fixer's log (this repo only)."""
    out: dict[int, list[str]] = {}
    try:
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return out
    for r in rows:
        tests = [str(t) for t in r.get("tests") or [] if TEST.match(str(t))]
        if tests and (r.get("repo") or L.REPO) == L.REPO and not r.get("kind"):
            out.setdefault(int(r["pr"]), [])
            out[int(r["pr"])] = sorted({*out[int(r["pr"])], *tests})
    return out


def changes(sha: str) -> tuple[str, list[tuple[int, int, str]]]:
    """(parent, [(added, deleted, path)]) of a non-merge commit; ('', []) for a merge."""
    parents = L.git(["rev-list", "--parents", "-n", "1", sha], L.ROOT).stdout.split()[1:]
    if len(parents) != 1:
        return "", []
    rows = []
    for ln in L.git(["show", "--numstat", "--format=", sha], L.ROOT).stdout.splitlines():
        a, d, path = (ln.split("\t") + ["", "", ""])[:3]
        if a.isdigit() and d.isdigit():
            rows.append((int(a), int(d), path))
    return parents[0], rows


def exists(sha: str, path: str) -> bool:
    return L.git(["cat-file", "-e", f"{sha}:{path}"], L.ROOT).returncode == 0


def candidate(sha: str, extra_tests: list[str], max_churn: int = 60) -> dict | None:
    parent, rows = changes(sha)
    if not parent:
        return None
    src = [p for _, _, p in rows if SRC.match(p)]
    churn = sum(a + d for a, d, p in rows if p in src)
    tests = sorted({*(p for _, _, p in rows if TEST.match(p)), *extra_tests})
    tests = [t for t in tests if exists(sha, t)]
    if not src or not tests or not 1 <= churn <= max_churn or not all(exists(parent, p) for p in src):
        return None
    return {"repo": L.REPO, "sha": sha, "parent": parent, "src": src, "tests": tests}


def verify(it: dict, python: str, log=print) -> dict | None:
    """The item with its failing test ids, or None when it is no clean fix (see the module doc)."""
    tree = L.bench_tree(it["sha"])
    ok, out, slow = L.run_tests(tree, it["tests"], python, timeout=180)
    if not ok:
        log(f"  skip {it['sha'][:9]}: tests {'too slow' if slow else 'fail'} on the fix itself")
        return None
    L.break_tree(tree, it)
    ok, out, slow = L.run_tests(tree, it["tests"], python, timeout=180)
    fails = re.findall(r"^FAILED (\S+::\S+)", out, re.M)
    L.bench_tree(it["sha"])
    if ok or slow or not fails:
        log(f"  skip {it['sha'][:9]}: the tests {'time out' if slow else 'still pass'} on the broken code")
        return None
    if FEATURE.search(out):
        log(f"  skip {it['sha'][:9]}: the test file does not even load on the broken code")
        return None
    return {**it, "fails": sorted(dict.fromkeys(fails))[:6]}


def mine(python: str, rev: str = "origin/star/next", scan: int = 3000, want: int = 12, log=print) -> list[dict]:
    L.git(["fetch", "-q", "origin", "star/next"], L.ROOT)
    order: list[tuple[str, list[str], str]] = []
    for pr, tests in sorted(logged_failures().items()):
        for sha in L.git(["log", "--format=%H", "-E", f"--grep=#{pr}\\b", rev], L.ROOT).stdout.split():
            order.append((sha, tests, "pr-fixer"))
    for ln in L.git(["log", "--no-merges", "--format=%H %s", "-n", str(scan), rev], L.ROOT).stdout.splitlines():
        sha, _, subject = ln.partition(" ")
        if FIXISH.search(subject):
            order.append((sha, [], "git"))
    items: list[dict] = []
    seen: set[str] = set()
    for sha, tests, source in order:
        if len(items) >= want:
            break
        if sha in seen:
            continue
        seen.add(sha)
        it = candidate(sha, tests)
        if not it:
            continue
        log(f"try {sha[:9]} ({source}) src {', '.join(it['src'])} tests {', '.join(it['tests'])}")
        got = verify(it, python, log)
        if got:
            items.append({"id": f"R{len(items) + 1:02d}", **got, "source": source})
            log(f"  kept {items[-1]['id']}: {len(got['fails'])} failing test(s)")
    return items


def fix_heads(item: dict) -> list[str]:
    """Where a queued failure got fixed: her fix PR's head, then star/next commits that name the PR."""
    out = []
    if item.get("fix_pr"):
        try:
            r = subprocess.run(["gh", "pr", "view", str(item["fix_pr"]), "--repo", item["repo"], "--json",
                                "headRefOid", "-q", ".headRefOid"], capture_output=True, text=True, timeout=120)
            out += re.findall(r"\b[0-9a-f]{40}\b", r.stdout)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if item.get("pr"):
        out += L.git(["log", "--format=%H", "-E", f"--grep=#{item['pr']}\b", "origin/star/next"], L.ROOT).stdout.split()
    return list(dict.fromkeys(out))


def verify_queue(python: str, heads=fix_heads, log=print) -> int:
    """Queued items (after_fix) count in the real-fix score once a fix is known: the tests pass on the fix and still
    fail on the queued head. Returns how many were verified now."""
    try:
        rows = [json.loads(ln) for ln in L.QUEUE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return 0
    done = 0
    for it in rows:
        if it.get("verified"):
            continue
        for fix in heads(it):
            ok, _, _ = L.run_tests(L.bench_tree(fix), it["tests"], python, timeout=180)
            if not ok:
                continue
            L.break_tree(L.bench_tree(it["sha"], pr=it.get("pr")), it)
            ok, out, slow = L.run_tests(L.TREE, it["tests"], python, timeout=180)
            if not ok and not slow and re.search(r"^FAILED ", out, re.M) and not FEATURE.search(out):
                it.update(verified=True, fix=fix)
                done += 1
                log(f"verified {it['id']}: fixed by {fix[:9]}")
            break
    L.QUEUE.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return done
