"""Litha's bug benchmark and learning loop: plant real bugs in the real repository, let her fix them, learn from it.

1. mutants(): small realistic bugs in star/ and server/ source (== <-> !=, < -> <=, and <-> or, dropped `not`,
   True <-> False returns, +1 <-> -1, ...). A mutant counts only if the module's own tests FAIL with it (the tests
   can see the bug, so a fix can be proven by the same tests).
2. run(): for each mutant, in the bench worktree, Litha repairs it with exactly the fixer's loop (star.pr_fixer.repair:
   CI-style failure output + the mutant's diff + the real code). Solved = the module's tests pass again.
3. Learning, from every item (the answer is known: the original line):
   - lessons  ~/.star/litha/lessons.json   per bug kind: tries, solved, and the right fix of the latest miss; the fixer
                                           puts her weakest kinds into every prompt (lessons_text()).
   - sft      ~/.star/litha/sft/pr-fix.jsonl  prompt -> correct edit pairs for nightly training (her own failures
                                           with the real answer, never another model's text).
   - history  ~/.star/litha/bench.jsonl    one row per run: solved/total, by kind, seconds -> the trend.

    python -m star.bug_bench list  [--limit 40]                    which mutants exist (tests must kill them)
    python -m star.bug_bench run   [--n 10] [--seed -1] [--kind K] [--blind]  the fix benchmark; prints the score
    python -m star.bug_bench hunt  [--n 10] [--seed -1]   review catch rate: she must find AND prove the bug
Runs in worktrees/litha-bench (a detached star/next checkout). Every item is reset with git afterwards.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile
import time

HOME = Path.home() / ".star" / "litha"
LESSONS = HOME / "lessons.json"
SFT = HOME / "sft" / "pr-fix.jsonl"
HISTORY = HOME / "bench.jsonl"
ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT.parent / "litha-bench"
CLONE = ROOT.parents[1] / "Star-AI"

# kind -> (pattern, replacement); applied to ONE occurrence on one line of code (never comments / strings only)
OPS: dict[str, tuple[str, str]] = {
    "eq-flip": (r" == ", " != "),
    "ne-flip": (r" != ", " == "),
    "lt-edge": (r" < ", " <= "),
    "gt-edge": (r" > ", " >= "),
    "le-edge": (r" <= ", " < "),
    "ge-edge": (r" >= ", " > "),
    "and-or": (r" and ", " or "),
    "or-and": (r" or ", " and "),
    "drop-not": (r"\bif not ", "if "),
    "add-not": (r"\bif (?!not )", "if not "),
    "true-false": (r"\breturn True\b", "return False"),
    "false-true": (r"\breturn False\b", "return True"),
    "plus-minus-one": (r" \+ 1\b", " - 1"),
    "minus-plus-one": (r" - 1\b", " + 1"),
    "in-notin": (r" in (?=[\w(\[{])", " not in "),
    "isnone-flip": (r" is None\b", " is not None"),
    "isnotnone-flip": (r" is not None\b", " is None"),
    "max-min": (r"\bmax\(", "min("),
    "min-max": (r"\bmin\(", "max("),
    "zero-one": (r"([=!]= )0\b", r"\g<1>1"),
    "strip-drop": (r"\.strip\(\)", ""),
    "break-continue": (r"\bbreak\b", "continue"),
    "slice-shift": (r"\[1:\]", "[2:]"),
    "drop-return": (r"^(\s+)return (?=\S)", r"\g<1>"),
    "swap-args": (r"\b(\w+)\((\w+), (\w+)\)", r"\g<1>(\g<3>, \g<2>)"),
    "last-first": (r"\[-1\]", "[0]"),
    "first-last": (r"\[0\]", "[-1]"),
    "any-all": (r"\bany\(", "all("),
    "all-any": (r"\ball\(", "any("),
    "starts-ends": (r"\.startswith\(", ".endswith("),
    "lower-upper": (r"\.lower\(\)", ".upper()"),
    "add-sub": (r"(\w|\)) \+ (?=\w)", r"\g<1> - "),
}


def sh(args: list[str], cwd: Path | None = None, timeout: float = 900):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)


def code_lines(text: str) -> set[int]:
    """Line numbers that are real code inside a function (not docstrings, comments or module-level constants)."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Compare, ast.BoolOp, ast.If, ast.Return, ast.BinOp, ast.UnaryOp, ast.Break,
                                    ast.Call, ast.Subscript)):
                    lines.add(sub.lineno)
    return lines


def tests_for(module: str, tests_dir: Path, cache: dict[str, str]) -> list[str]:
    """Test files that import this module (star.x.y / from star.x import y)."""
    if not cache:
        for f in tests_dir.glob("test_*.py"):
            cache[f.as_posix()] = f.read_text(encoding="utf-8", errors="replace")
    parent, _, leaf = module.rpartition(".")
    pat = re.compile(rf"(\b{re.escape(module)}\b|from {re.escape(parent)} import [^\n]*\b{re.escape(leaf)}\b)")
    root = tests_dir.parent
    return sorted(Path(p).relative_to(root).as_posix() for p, text in cache.items() if pat.search(text))


def candidates(tree: Path, kinds: list[str] | None = None, rng: random.Random | None = None,
               max_files: int = 0) -> list[dict]:
    """(file, line, kind) mutations for modules that have tests; max_files > 0 = a random sample of files (fast)."""
    out, cache = [], {}
    files = sorted([*(tree / "star").rglob("*.py"), *(tree / "server").rglob("*.py")])
    if rng and max_files:
        rng.shuffle(files)
    scanned = 0
    for f in files:
        if max_files and scanned >= max_files:
            break
        rel = f.relative_to(tree).as_posix()
        module = rel[:-3].replace("/", ".")
        if "/tests/" in rel or rel.endswith("__init__.py"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        live = code_lines(text)
        if not live:
            continue
        tests = tests_for(module, tree / "tests", cache)
        if not tests:
            continue
        scanned += 1
        lines = text.splitlines()
        for no in sorted(live):
            line = lines[no - 1]
            code = line.split("#", 1)[0]
            for kind, (pat, _) in OPS.items():
                if kinds and kind not in kinds:
                    continue
                if re.search(pat, code) and not re.match(r"\s*(\"|')", code):
                    out.append({"file": rel, "line": no, "kind": kind, "tests": tests[:3], "orig": line})
    return out


def mutate(text: str, line: int, kind: str) -> str | None:
    lines = text.split("\n")
    pat, rep = OPS[kind]
    code, sep, comment = lines[line - 1].partition("#")
    new = re.sub(pat, rep, code, count=1)
    if new == code:
        return None
    lines[line - 1] = new + sep + comment
    out = "\n".join(lines)
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out


def run_tests(tree: Path, tests: list[str], python: str) -> tuple[bool, str]:
    env = dict(os.environ, APPDATA=tempfile.mkdtemp(prefix="litha-bench-"))
    try:
        r = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "-x", *tests], cwd=tree,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def ensure_bench() -> Path:
    if not BENCH.exists():
        sh(["git", "-C", str(CLONE), "fetch", "-q", "origin", "star/next"])
        sh(["git", "-C", str(CLONE), "worktree", "add", "-q", "--detach", str(BENCH), "origin/star/next"])
    return BENCH


def reset(tree: Path) -> None:
    sh(["git", "checkout", "--", "."], cwd=tree)


# ---------------------------------------------------------------- learning state

def load_lessons() -> dict:
    try:
        return json.loads(LESSONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def learn(kind: str, solved: bool, example: dict | None) -> None:
    lessons = load_lessons()
    k = lessons.setdefault(kind, {"tries": 0, "solved": 0})
    k["tries"] += 1
    k["solved"] += int(solved)
    if example and not solved:
        k["example"] = example                  # the latest miss with its real answer
    LESSONS.parent.mkdir(parents=True, exist_ok=True)
    LESSONS.write_text(json.dumps(lessons, indent=1), encoding="utf-8")


HINTS = {
    "eq-flip": "a == that became != (or the reverse) flips which case runs",
    "ne-flip": "a != that became == flips which case runs",
    "lt-edge": "< vs <= at a boundary: check the exact edge value the test uses",
    "gt-edge": "> vs >= at a boundary: check the exact edge value the test uses",
    "le-edge": "<= vs < at a boundary", "ge-edge": ">= vs > at a boundary",
    "and-or": "an `and` that should be `or` (or the reverse) lets wrong cases through",
    "or-and": "an `or` that should be `and` (or the reverse)",
    "drop-not": "a missing `not` inverts a condition", "add-not": "an extra `not` inverts a condition",
    "true-false": "a return True/False that is inverted", "false-true": "a return True/False that is inverted",
    "plus-minus-one": "+1 / -1 swapped: off by two", "minus-plus-one": "-1 / +1 swapped: off by two",
    "in-notin": "`in` vs `not in` inverted membership",
    "isnone-flip": "`is None` vs `is not None` inverted", "isnotnone-flip": "`is not None` vs `is None` inverted",
    "max-min": "max() where min() is meant (or the reverse)", "min-max": "min() where max() is meant (or the reverse)",
    "zero-one": "a comparison with 0 that became 1", "strip-drop": "a dropped .strip() keeps whitespace",
    "break-continue": "a `break` that became `continue` keeps looping",
    "slice-shift": "a [1:] slice that became [2:] skips an item",
    "drop-return": "a line lost its `return`: the function falls through and returns None",
    "swap-args": "two arguments passed in the wrong order", "last-first": "[0] where [-1] is meant (first vs last)",
    "first-last": "[-1] where [0] is meant (last vs first)", "any-all": "all() where any() is meant",
    "all-any": "any() where all() is meant", "starts-ends": "endswith where startswith is meant",
    "lower-upper": ".upper() where .lower() is meant", "add-sub": "a + that became -",
}


def lessons_text(limit: int = 5) -> str:
    """Her weakest bug kinds with one real example each, for the fixer's prompt ('' before any bench run)."""
    lessons = load_lessons()
    weak = sorted(((v["solved"] / max(1, v["tries"]), k, v) for k, v in lessons.items() if v["tries"]),
                  key=lambda x: x[0])[:limit]
    rows = []
    for rate, kind, v in weak:
        if rate >= 0.9:
            continue
        ex = v.get("example") or {}
        line = f"- {HINTS.get(kind, kind)} (you solved {v['solved']}/{v['tries']})"
        if ex.get("bad") and ex.get("good"):
            line += f"; e.g. `{ex['bad'].strip()[:90]}` should be `{ex['good'].strip()[:90]}`"
        rows.append(line)
    return ("Lessons from your past fixes (look for these first):\n" + "\n".join(rows) + "\n") if rows else ""


def save_sft(prompt: str, item: dict) -> None:
    """A training pair: the fixer prompt she saw -> the correct edit (the original line)."""
    SFT.parent.mkdir(parents=True, exist_ok=True)
    answer = {"why": HINTS.get(item["kind"], item["kind"]),
              "edits": [{"file": item["file"], "find": item["bad"].strip(), "replace": item["orig"].strip()}]}
    with SFT.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"messages": [{"role": "user", "content": prompt},
                                         {"role": "assistant", "content": json.dumps(answer)}],
                            "source": "bug_bench", "kind": item["kind"]}) + "\n")
    bank_row(prompt, answer, item)


def bank_row(prompt: str, answer: dict, item: dict, config: Path = Path.home() / ".star" / "nightly" / "config.json"):
    """The same pair in the nightly trainer's bank (it trains on every work_dir/bank*.jsonl; kind "corrected" rows
    count double: they carry what she got wrong). Skipped when the nightly is not set up on this machine."""
    try:
        cfg = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    import hashlib
    work = Path(str(cfg.get("work_dir", ""))).expanduser()
    if not work.is_dir():
        return
    row = {"id": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16], "group": "g:pr-fix",
           "source": "bug_bench (real answer)", "night": dt.date.today().isoformat(), "kind": "corrected",
           "messages": [{"role": "system", "content": cfg.get("system_prompt", "")},
                        {"role": "user", "content": prompt}, {"role": "assistant", "content": json.dumps(answer)}]}
    with (work / "bank-litha-fixes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- the benchmark

def killed(tree: Path, items: list[dict], n: int, python: str, rng: random.Random) -> list[dict]:
    """Up to n mutants that the module's tests really catch (tried in random order, one kind per file line)."""
    by_kind: dict[str, list[dict]] = {}
    for it in items:
        by_kind.setdefault(it["kind"], []).append(it)
    for group in by_kind.values():
        rng.shuffle(group)
    order = []                                   # round-robin over kinds: every kind gets tried, not 1/3 add-not
    while any(by_kind.values()):
        for kind in sorted(by_kind):
            if by_kind[kind]:
                order.append(by_kind[kind].pop())
    out, seen = [], set()
    for it in order:
        if len(out) == n:
            break
        key = (it["file"], it["line"])
        if key in seen:
            continue
        seen.add(key)
        f = tree / it["file"]
        text = f.read_text(encoding="utf-8")
        new = mutate(text, it["line"], it["kind"])
        if new is None:
            continue
        f.write_bytes(new.encode("utf-8"))
        ok, out_text = run_tests(tree, it["tests"], python)
        if not ok:
            out.append({**it, "bad": new.split("\n")[it["line"] - 1], "fail": out_text,
                        "diff": sh(["git", "diff"], cwd=tree).stdout})
        reset(tree)
    return out


def run(n: int, seed: int, kinds: list[str] | None, python: str, asker=None, blind: bool = False) -> dict:
    from star import pr_fixer
    tree = ensure_bench()
    rng = random.Random(seed)
    items = killed(tree, candidates(tree, kinds, rng, max_files=25), n, python, rng)
    score = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "seed": seed, "blind": blind,
             "n": len(items),
             "solved": 0, "by_kind": {}, "seconds": 0}
    t0 = time.time()
    for it in items:
        f = tree / it["file"]
        f.write_bytes(mutate(f.read_text(encoding="utf-8"), it["line"], it["kind"]).encode("utf-8"))
        fails = pr_fixer.failures(it["fail"]) or [{"test": it["tests"][0], "section": it["fail"][-2500:]}]
        prompts: list[str] = []

        def ask(prompt: str) -> str:
            prompts.append(prompt)
            return (asker or pr_fixer.ask)(prompt)

        t = time.time()
        try:
            ok, why, rounds = pr_fixer.repair(tree, f"fix {it['file']}", fails, it["fail"], it["tests"], python,
                                              ask, "" if blind else it["diff"])
        except Exception as e:  # noqa: BLE001 - one item must not end the bench
            ok, why, rounds = False, f"error {e}"[:200], 0
        reset(tree)
        k = score["by_kind"].setdefault(it["kind"], [0, 0])
        k[0] += int(ok)
        k[1] += 1
        score["solved"] += int(ok)
        learn(it["kind"], ok, {"file": it["file"], "bad": it["bad"], "good": it["orig"]})
        if prompts:
            save_sft(prompts[0], it)
        print(f"{'SOLVED' if ok else 'missed'} {it['kind']:<15} {it['file']}:{it['line']} "
              f"rounds {rounds} {round(time.time() - t)} s  {why[:90]}", flush=True)
    score["seconds"] = round(time.time() - t0)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(score) + "\n")
    return score


def ensure_base() -> Path:
    """A second, never-mutated star/next checkout: the 'code before the change' for differential proofs."""
    base = BENCH.parent / "litha-bench-base"
    if not base.exists():
        sh(["git", "-C", str(CLONE), "worktree", "add", "-q", "--detach", str(base), "origin/star/next"])
    sh(["git", "checkout", "-q", "--detach", sh(["git", "rev-parse", "HEAD"], cwd=ensure_bench()).stdout.strip()],
       cwd=base)
    return base


def hunt_run(n: int, seed: int, kinds: list[str] | None, python: str) -> dict:
    """Review catch rate: plant a bug, let her hunt it in the changed function, count only proven finds."""
    from star import bug_hunt
    tree, base = ensure_bench(), ensure_base()
    rng = random.Random(seed)
    items = killed(tree, candidates(tree, kinds, rng, max_files=25), n, python, rng)
    score = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "seed": seed, "mode": "hunt",
             "n": len(items), "caught": 0, "wrong_line": 0, "by_kind": {}}
    for it in items:
        f = tree / it["file"]
        f.write_bytes(mutate(f.read_text(encoding="utf-8"), it["line"], it["kind"]).encode("utf-8"))
        t = time.time()
        try:
            found = bug_hunt.hunt(tree, base, {it["file"]: {it["line"]}}, python)
        except Exception as e:  # noqa: BLE001
            found = []
            print(f"error {e}"[:200], flush=True)
        reset(tree)
        hit = any(abs(x["line"] - it["line"]) <= 1 for x in found)
        score["caught"] += int(hit)
        score["wrong_line"] += int(bool(found) and not hit)
        k = score["by_kind"].setdefault(it["kind"], [0, 0])
        k[0] += int(hit)
        k[1] += 1
        print(f"{'CAUGHT' if hit else 'missed'} {it['kind']:<15} {it['file']}:{it['line']} {round(time.time() - t)} s "
              f"{(found[0]['why'] if found else '')[:90]}", flush=True)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(score) + "\n")
    return score


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.bug_bench")
    ap.add_argument("cmd", choices=["list", "run", "hunt"])
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--seed", type=int, default=-1, help="-1 = today's date (new bugs every day)")
    ap.add_argument("--blind", action="store_true", help="no diff: find the bug from the failing tests alone")
    ap.add_argument("--kind", action="append")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        items = candidates(ensure_bench(), a.kind)
        kinds: dict[str, int] = {}
        for it in items:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
        print(json.dumps({"candidates": len(items), "by_kind": kinds}))
        for it in items[:a.limit]:
            print(f"{it['kind']:<15} {it['file']}:{it['line']}  tests {', '.join(it['tests'])}")
        return 0
    seed = a.seed if a.seed >= 0 else int(dt.date.today().strftime("%Y%m%d"))
    if a.cmd == "hunt":
        print(json.dumps(hunt_run(a.n, seed, a.kind, a.python)))
        return 0
    print(json.dumps(run(a.n, seed, a.kind, a.python, blind=a.blind)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
