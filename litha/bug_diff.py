"""Differential proofs: for a bug no existing test sees, run the changed code on the same inputs before and after.

She names a few small calls of the changed function (edges, None, empty, negatives: the inputs where the old and
the new line can differ). Each call runs in a fresh Python on the base and on the PR code, twice per side. The first
call that is stable on both sides, reaches the suspect line on the PR code, and gives a different result becomes a
plain pytest test that asserts the OLD result. That test is then run like every proof: it must fail on the PR code and
pass on the base, twice per side (a flake is no proof).

A difference is only a behaviour CHANGE, and a PR is meant to change behaviour. So before it counts she is shown both
results and the author's words and must say the new result is wrong. Differences that come from the call itself
(a name the base does not have, a changed signature: the exception is raised outside the module) never count.

    differential(tree, base, risk, python, asker, intent)  ->  {"proven", "test", "via", ...}
"""
from __future__ import annotations

import ast
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from litha import fresh_py

CALLS = """A pull request changed this code (changed lines marked >>, the line before the change under it as `was:`):
{func}
{shape}Suspected bug at line {line}: {why}
Write up to 6 short Python expressions that call this code with inputs where the old line and the new line give
DIFFERENT results: the exact edge values of the changed comparison, None, empty, zero, negative, one item, several.
Every name the module defines is in scope{hint}. If the calls need an object first (a store, a config), build it
in "setup" (plain statements, run before each call), the way the example test does. No network, sleeping or
randomness.
{feedback}Answer only JSON: {{"setup": "<statements or empty>", "calls": ["<expression>", ...]}}"""
JUDGE = """A pull request changed this code:
{changes}
Calling `{call}` gave {before} before the change and gives {after} now.
The suspected bug: {why}
{intent}Is the NEW result wrong, i.e. a bug the change brought in, not a behaviour change the author meant?
Answer only JSON: {{"bug": true or false, "why": "<one line>"}}"""
PROBE = "tests/_litha_diff_probe_test.py"
RUNNER = r'''# Litha's differential probe (never committed): runs her calls under the suite's own conftest isolation.
import ast, asyncio, importlib, inspect, itertools, json, os, re, sys, traceback
BS = chr(92)


def test_litha_probe():
    spec = json.load(open(os.environ["LITHA_DIFF_SPEC"], encoding="utf-8"))
    norm = lambda p: os.path.normcase(os.path.abspath(p))
    target, lines, seen = norm(spec["file"]), set(spec["lines"]), {}
    mod = importlib.import_module(spec["module"])
    rows = []
    for expr in spec["calls"]:
        hits = set()

        def local(frame, event, arg):
            if event == "line":
                hits.add(frame.f_lineno)
            return local

        def glob(frame, event, arg):
            f = frame.f_code.co_filename
            if f not in seen:
                seen[f] = norm(f) == target
            return local if seen[f] else None

        row = {"call": expr}
        ns = dict(vars(mod))
        try:
            exec(compile(spec.get("setup") or "pass", "<setup>", "exec"), ns)
        except BaseException as e:
            rows.append({**row, "setup_error": type(e).__name__, "hit": []})
            continue
        sys.settrace(glob)
        try:
            v = eval(compile(expr, "<call>", "eval"), ns)
            if inspect.iscoroutine(v):
                row["wrap"] = "await"
                v = asyncio.run(v)
            elif inspect.isgenerator(v):
                row["wrap"] = "list"
                v = list(itertools.islice(v, 100))
            sys.settrace(None)
            r = repr(v)
            row["ok"] = r[:1500]
            try:
                row["literal"] = len(r) <= 1500 and ast.literal_eval(r) == v
            except Exception:
                row["literal"] = False
            low = r.lower()                                  # its own checkout's path differs on each side
            row["unstable"] = bool(re.search(r" at 0x[0-9a-fA-F]+", r)) or any(
                root.lower() in low for root in (spec["root"], spec["root"].replace(BS, BS * 2),
                                                 spec["root"].replace(BS, "/")))
        except BaseException as e:
            sys.settrace(None)
            row["raise"] = type(e).__name__
            row["builtin"] = type(e).__module__ == "builtins"
            row["in_file"] = any(norm(f.filename) == target for f in traceback.extract_tb(e.__traceback__))
        row["hit"] = sorted(hits & lines)
        rows.append(row)
    names = [n for n in vars(mod) if not n.startswith("__")]
    with open(spec["out"], "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "names": names}, f)
'''




def ask(prompt: str) -> str:
    """Litha with a small answer budget: a list of calls or a yes/no, never a whole file."""
    from star.asset3d.llm import chat
    text, _ = chat("litha", [{"role": "user", "content": prompt}], max_tokens=500, temperature=0.2,
                   json_mode=True, timeout=900)
    return text


def was_lines(before: str, after: str) -> dict[int, str | None]:
    """{line in the new code: the line it replaced (None = a new line)} for every changed line."""
    a, b = before.splitlines(), after.splitlines()
    out: dict[int, str | None] = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "insert"):
            for j in range(j1, j2):
                i = i1 + (j - j1)
                out[j + 1] = a[i] if tag == "replace" and i < i2 else None
    return out


def target(source: str, line: int) -> tuple[str, int, int] | None:
    """(name to call, first, last) of the innermost function holding `line`: `f` or `Class.method`. Functions
    nested in another function cannot be called from outside: None."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    best = None
    for node in tree.body:
        inner = [(node.name, node)] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
        if isinstance(node, ast.ClassDef):
            inner = [(f"{node.name}.{m.name}", m) for m in node.body
                     if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for name, fn in inner:
            if fn.lineno <= line <= (fn.end_lineno or fn.lineno):
                nested = [s for s in ast.walk(fn) if s is not fn and isinstance(s, (ast.FunctionDef,
                          ast.AsyncFunctionDef, ast.Lambda)) and s.lineno <= line <= (s.end_lineno or s.lineno)]
                best = None if nested else (name, fn.lineno, fn.end_lineno or fn.lineno)
    return best


BANNED = re.compile(r"\b(exec|eval|__import__|input|system|remove|rmtree|unlink|subprocess|socket|urlopen)\b")


def calls_of(answer: str, limit: int = 6) -> tuple[str, list[str]]:
    """(setup statements, call expressions) from her answer; anything that does not parse is dropped."""
    try:
        got = json.loads(answer)
    except (ValueError, TypeError):
        return "", []
    rows = got.get("calls") if isinstance(got, dict) else got
    setup = str(got.get("setup") or "").strip() if isinstance(got, dict) else ""
    try:
        compile(setup, "<setup>", "exec")
    except (SyntaxError, ValueError):
        setup = ""
    if len(setup) > 800 or BANNED.search(setup):
        setup = ""
    out = []
    for c in rows if isinstance(rows, list) else []:
        c = str(c).strip()
        if not c or len(c) > 300 or BANNED.search(c) or re.search(r"\bopen\(", c):
            continue
        try:
            ast.parse(c, mode="eval")
        except SyntaxError:
            continue
        out.append(c)
    return setup, list(dict.fromkeys(out))[:limit]


def probe(tree: Path, module: str, file: str, calls: list[str], lines: set[int], python: str,
          setup: str = "") -> dict | None:
    """Run each call in a fresh pytest in `tree` (the suite's conftest isolation applies):
    {"rows": [{call, ok|raise, hit, ...}], "names"} or None when the module cannot even be run."""
    tmp = Path(tempfile.mkdtemp(prefix="litha-diff-"))
    (tmp / "spec.json").write_text(json.dumps({"module": module, "file": str(tree / file), "lines": sorted(lines),
                                               "calls": calls, "setup": setup, "out": str(tmp / "out.json"),
                                               "root": str(tree.resolve())}), encoding="utf-8")
    (tree / PROBE).write_text(RUNNER, encoding="utf-8")
    env = fresh_py.env(tree, APPDATA=str(tmp), PYTHONHASHSEED="0", LITHA_DIFF_SPEC=str(tmp / "spec.json"),
                        PYTHONPATH=os.pathsep.join([str(tree), os.environ.get("PYTHONPATH", "")]))
    (tmp / "cwd").mkdir()                                  # files her calls write land here, not in the checkout
    try:
        subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tree / PROBE)],
                       cwd=tmp / "cwd",
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, env=env)
        return json.loads((tmp / "out.json").read_text(encoding="utf-8"))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    finally:
        (tree / PROBE).unlink(missing_ok=True)


def outcome(row: dict) -> tuple:
    return ("ok", row["ok"]) if "ok" in row else ("raise", row.get("raise"))


def first_difference(before: list[dict], before2: list[dict], after: list[dict], after2: list[dict]) -> dict | None:
    """The first call that is stable on both sides (same result twice), reaches the suspect line on the new code and
    differs. An exception counts only when it is raised inside the module (not by the call itself)."""
    for b, b2, a, a2 in zip(before, before2, after, after2):
        if any("setup_error" in r for r in (b, b2, a, a2)):
            continue
        if outcome(b) != outcome(b2) or outcome(a) != outcome(a2) or outcome(a) == outcome(b) or not a["hit"]:
            continue
        if b.get("unstable") or a.get("unstable"):
            continue
        if "raise" in b and not (b["in_file"] and b["builtin"]):
            continue                                            # the old code cannot even take this call
        if "raise" in a and not a["in_file"]:
            continue
        if "raise" in a and "raise" in b and not b["builtin"]:
            continue
        return {"before": b, "after": a}
    return None


def build_test(module: str, call: str, before: dict, names: list[str], func: str, setup: str = "") -> str:
    """A plain pytest file asserting what the code returned (or raised) before the change."""
    code = ast.parse(f"{setup}\n_ = {call}")
    made = {n.id for n in ast.walk(code) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    used = sorted({n.id for n in ast.walk(code) if isinstance(n, ast.Name)} & set(names) - made)
    wrap = before.get("wrap")
    expr = f"asyncio.run({call})" if wrap == "await" else f"list(itertools.islice({call}, 100))" if wrap == "list" \
        else call
    head = [f"import {m}" for m in (["asyncio"] if wrap == "await" else ["itertools"] if wrap == "list" else [])]
    head.append("import tempfile")
    if used:
        head.append(f"from {module} import {', '.join(used)}")
    name = re.sub(r"\W", "_", func.split(".")[-1]).strip("_").lower() or "code"
    shown = (before["ok"] if "ok" in before else f"raised {before['raise']}")[:200]
    doc = f"# Litha's differential proof: `{call}` gave {shown} before the change.".replace("\n", " ")
    pre = "".join(f"    {ln}\n" for ln in setup.splitlines())
    if "raise" in before:
        body = (f"    try:\n        got = {expr}\n    except {before['raise']}:\n        return\n"
                f"    assert False, f\"expected {before['raise']} as before the change, got {{got!r}}\"\n")
    elif before["ok"] in ("None", "True", "False"):
        body = f"    got = {expr}\n    assert got is {before['ok']}\n"
    elif before.get("literal"):
        body = f"    got = {expr}\n    assert got == {before['ok']}\n"
    else:
        body = f"    got = {expr}\n    assert repr(got) == {before['ok']!r}\n"
    # its own folder, not pytest's tmp_path: a nested pytest prunes the numbered tmp folders of the one running it
    return "\n".join([doc, *head, "", "", f"def test_{name}_as_before_the_change(monkeypatch):",
                      '    monkeypatch.chdir(tempfile.mkdtemp(prefix="litha-proof-"))', pre + body])


def seen(row: dict, line: int) -> str:
    """One line of feedback on a call that showed nothing."""
    if "setup_error" in row:
        return f"`{row['call']}`: your setup raised {row['setup_error']}"
    got = (row.get("ok") or f"raised {row.get('raise')}")[:80]
    return f"`{row['call']}`: {got} on both sides" + ("" if row["hit"] else f" (never reached line {line})")


def said(row: dict) -> str:
    return row["ok"][:200] if "ok" in row else f"an exception {row['raise']}"


def changes_text(src: list[str], was: dict[int, str | None], first: int, last: int, limit: int = 8) -> str:
    rows = []
    for no in sorted(n for n in was if first <= n <= last)[:limit]:
        rows.append(f"now {no}: {src[no - 1].strip()}\nwas:    {(was[no] or '(new line)').strip()}")
    return "\n".join(rows)


def differential(tree: Path, base: Path, risk: dict, python: str, asker=ask, intent: str = "", rounds: int = 2,
                 shape: str = "") -> dict:
    """See the module docstring. LITHA_DIFF_LOG=<file> appends each outcome and the calls she tried (diagnosis)."""
    tried: list[str] = []
    got = _differential(tree, base, risk, python, asker, intent, rounds, shape, tried)
    if os.environ.get("LITHA_DIFF_LOG"):
        with open(os.environ["LITHA_DIFF_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"file": risk["file"], "line": risk["line"], "why": risk.get("why", "")[:200],
                                "calls": tried, **{k: v for k, v in got.items() if k != "output"}}) + "\n")
    return got


def _differential(tree: Path, base: Path, risk: dict, python: str, asker, intent: str, rounds: int, shape: str,
                  tried: list[str]) -> dict:
    from litha import bug_proof
    file, line = risk["file"], int(risk["line"])
    try:
        head_src = (tree / file).read_text(encoding="utf-8", errors="replace")
        base_src = (base / file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"proven": False, "why": "file missing on one side"}
    found = target(head_src, line)
    if found is None:
        return {"proven": False, "why": "no callable function holds the line"}
    func, first, last = found
    src, was = head_src.splitlines(), was_lines(base_src, head_src)
    if last - first > 50:                                          # a 4096-token window: the lines around the change
        first, last = max(first, line - 25), min(last, line + 25)
    view = []
    for i in range(first, last + 1):
        view.append(f"{'>>' if i in was else '  '} {i}: {src[i - 1]}")
        if i in was:
            view.append(f"   was: {(was[i] or '(new line)').strip()}")
    cls, _, meth = func.rpartition(".")
    hint = f" (a method: build a `{cls}` first, e.g. `{cls}(...).{meth}(...)`)" if cls else f" (e.g. `{func}(...)`)"
    module = bug_proof.module_of(file)
    near = {line - 1, line, line + 1}
    feedback = ""
    for n in range(1, rounds + 1):
        setup, calls = calls_of(asker(CALLS.format(func="\n".join(view), shape=shape, line=line,
                                                   why=risk.get("why", "")[:300], hint=hint, feedback=feedback)))
        key = (lambda c: f"{setup} | {c}") if setup else (lambda c: c)  # noqa: E731
        calls = [c for c in calls if key(c) not in tried]
        if not calls:
            continue
        tried += [key(c) for c in calls]
        runs = [probe(t, module, file, calls, near, python, setup) for t in (base, base, tree, tree)]
        if any(r is None for r in runs):
            return {"proven": False, "why": "the code could not be imported and run", "rounds": n}
        ran = [r for r in runs if r is not None]            # all four (checked above)
        diff = first_difference(*(r["rows"] for r in ran))
        if diff is None:
            feedback = "Your last calls showed no bug:\n" + "\n".join(seen(r, line) for r in ran[2]["rows"][:6]) + \
                "\nTry other inputs.\n"
            continue
        b, a = diff["before"], diff["after"]
        judged = asker(JUDGE.format(changes=changes_text(src, was, found[1], found[2]), call=a["call"],
                                    before=said(b), after=said(a), why=risk.get("why", "")[:300],
                                    intent=f"What the author says the change is for: {intent[:800]}\n"
                                    if intent else ""))
        try:
            verdict = json.loads(judged)
        except (ValueError, TypeError):
            verdict = {}
        if not (isinstance(verdict, dict) and verdict.get("bug") is True):
            return {"proven": False, "why": "the new result is what the change meant", "rounds": n,
                    "difference": {"call": a["call"], "before": said(b), "after": said(a)}}
        test = build_test(module, a["call"], b, ran[0]["names"], func, setup)

        def fails(result: str, out: str) -> bool:
            return result == "proven" or (result == "crashed" and bug_proof.raised_in(out, file))

        verdict1, out = bug_proof.run_proof(tree, test, python)
        if not (fails(verdict1, out) and fails(*bug_proof.run_proof(tree, test, python))):
            return {"proven": False, "why": "the differential test did not fail twice on the new code", "rounds": n}
        if not all(bug_proof.run_proof(base, test, python)[0] == "passed" for _ in range(2)):
            return {"proven": False, "why": "the differential test did not pass twice on the old code", "rounds": n}
        return {"proven": True, "test": test, "output": out[-800:], "tries": n, "via": f"differential {a['call']}"[:200],
                "difference": {"call": a["call"], "before": said(b), "after": said(a)}}
    return {"proven": False, "why": "no input gave a different result", "rounds": rounds}
