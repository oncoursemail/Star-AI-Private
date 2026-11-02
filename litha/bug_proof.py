"""Test-backed bug proofs: a claimed bug counts only when Litha writes a test that really fails on the PR's code.

prove(tree, risk) asks her for ONE small pytest file that should pass on correct code and fails because of the bug she
claimed, writes it as tests/_litha_proof_test.py in the PR checkout (never committed), runs it, deletes it.
Proven = the test FAILS with an assertion (or the code raises inside the module under test). A test that cannot even
run (syntax error, import of something that does not exist, error inside the test's own setup) proves nothing.
Up to 3 tries; each later try sees the previous output (syntax errors are caught before running).

With a base (the code before the change), the module's EXISTING tests run first: one that fails on the PR's code
(twice: no flake) and passes on the base is the proof as it is, trimmed to that one test (no model call). For an
existing test, failing means an assert OR an exception raised inside the changed module: the test passes on the base,
so it is not misusing the code (measured: all 4 misses on seed 5 were exceptions raised in the module, no assert).
One that fails but is not a clean proof is her starting point to edit. When no existing test fails (a bug the tests
miss), the differential step comes next (litha.bug_diff): she names a few calls, they run on both sides, and the first
real difference she judges a bug becomes a test asserting the old result. Only after that does she invent a test.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from litha import fresh_py

PROOF = "tests/_litha_proof_test.py"
ASK = """You claimed this bug in a pull request:
{file}:{line}: {why}

What the module defines (use these exact names; build objects the way the example test does):
{outline}
{example}
The real code (line numbers on the left):
{excerpt}

Prove it with ONE small pytest test that calls the real code (import it from its module, e.g. `from {module} import
...`), PASSES if the code were correct, and FAILS because of exactly this bug. No network, no files outside tmp_path,
no sleeping. If you cannot prove it, say so.
{start}{feedback}Answer only JSON: {{"possible": true or false, "test": "<the whole python test file>"}}"""
USELESS = re.compile(r"(SyntaxError|IndentationError|ModuleNotFoundError|ImportError|NameError|fixture '.*' not found|"
                     r"collected 0 items|no tests ran)", re.I)


def ask(prompt: str) -> str:
    """Litha with room for a whole test file (the merger's 700-token review budget cuts tests off)."""
    from star.asset3d.llm import chat
    text, _ = chat("litha", [{"role": "user", "content": prompt}], max_tokens=1800, temperature=0.2,
                   json_mode=True, timeout=900)
    return text


def module_of(path: str) -> str:
    return path[:-3].replace("/", ".") if path.endswith(".py") else path


def outline(source: str, limit: int = 60) -> str:
    """Every class (with its __init__ signature) and function the module defines: the excerpt alone made her
    invent class names (measured: `CallHandler` for a module without it)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    lines = source.splitlines()
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append(lines[node.lineno - 1].strip())
            out += [f"    {lines[s.lineno - 1].strip()}" for s in node.body
                    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "__init__"]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(lines[node.lineno - 1].strip())
    return "\n".join(out[:limit])


def example_test(tree: Path, module: str, names: list[str], max_lines: int = 60) -> str:
    """An existing test that uses this module (its imports + the first test function naming one of `names`):
    how the real tests build its objects."""
    parent, _, leaf = module.rpartition(".")
    pat = re.compile(rf"(\b{re.escape(module)}\b|from {re.escape(parent)} import [^\n]*\b{re.escape(leaf)}\b)")
    uses = re.compile(r"\b(" + "|".join(map(re.escape, names or [leaf])) + r")\b")
    for f in sorted((tree / "tests").glob("test_*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not pat.search(text):
            continue
        try:                                                             # whole statements: `from x import (A,` spans lines
            imports = [ast.get_source_segment(text, s) or "" for s in ast.parse(text).body
                       if isinstance(s, (ast.Import, ast.ImportFrom))]
        except SyntaxError:
            continue
        for block in re.split(r"(?m)^(?=def test_)", text)[1:]:
            body = re.split(r"\n(?=\S)", block, maxsplit=1)[0]               # up to the next top-level statement
            if uses.search(body):
                code = "\n".join(imports + [""] + body.splitlines()[:max_lines])
                return f"An existing test of this module ({f.name}):\n{code}\n"
    return ""


FAILED = re.compile(r"^FAILED (\S+::\S+)", re.M)
ASSERT = re.compile(r"^E\s+(assert\b|AssertionError)", re.M)
_RUNS: dict[tuple, list[dict]] = {}
_PROOFS: dict[tuple, tuple[dict | None, str]] = {}


def raised_in(out: str, file: str) -> bool:
    """An exception (not an assert) whose traceback runs through the changed module itself."""
    if not re.search(r"^E\s+[\w.]*(Error|Exception)\b", out, re.M):
        return False
    return re.search(rf"(^|[/\s]){re.escape(file)}:\d+", out.replace("\\", "/"), re.M) is not None


def module_tests(tree: Path, module: str, limit: int = 3) -> list[str]:
    from litha.bug_bench import tests_for
    return tests_for(module, tree / "tests", {})[:limit] if (tree / "tests").is_dir() else []


def failing_tests(tree: Path, file: str, python: str, limit: int = 3) -> list[dict]:
    """[{test, section}] of the module's existing tests that fail in this tree on an assert or on an exception
    raised inside `file` (cached per file content: the hunt asks once per suspect)."""
    tests = module_tests(tree, module_of(file))
    if not tests:
        return []
    digest = hashlib.sha1((tree / file).read_bytes()).hexdigest()
    key = (str(tree), file, digest)
    if key in _RUNS:
        return _RUNS[key]
    env = fresh_py.env(tree, APPDATA=tempfile.mkdtemp(prefix="litha-proof-"))
    try:
        r = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "--tb=short", *tests],
                           cwd=tree, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                           env=env)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        out = ""
    found = []
    for test in dict.fromkeys(FAILED.findall(out)):
        name = test.split("::")[-1]
        m = re.search(rf"^_{{3,}} (?:\w+\.)?{re.escape(name)} _{{3,}}$(.*?)(?=^_{{3,}} |^=+ )", out, re.M | re.S)
        section = m.group(1) if m else ""
        if ASSERT.search(section) or raised_in(section, file):
            found.append({"test": test, "section": section[-1500:]})
        if len(found) == limit:
            break
    _RUNS[key] = found
    return found


def single_test(text: str, node: str) -> str | None:
    """The test file with only this one test left (imports, helpers and fixtures kept, source lines untouched)."""
    parts = node.split("::")[1:]
    if not parts:
        return None
    name, cls = re.sub(r"\[.*$", "", parts[-1]), parts[0] if len(parts) > 1 else None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    def span(n: ast.stmt) -> range:
        first = min([n.lineno, *(d.lineno for d in getattr(n, "decorator_list", []))])
        return range(first, (n.end_lineno or n.lineno) + 1)

    drop: set[int] = set()
    kept = False
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"):
            if cls is None and n.name == name:
                kept = True
            else:
                drop.update(span(n))
        elif isinstance(n, ast.ClassDef) and n.name.startswith("Test"):
            if n.name != cls:
                drop.update(span(n))
                continue
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith("test"):
                    if m.name == name:
                        kept = True
                    else:
                        drop.update(span(m))
    if not kept:
        return None
    return "\n".join(ln for i, ln in enumerate(text.splitlines(), 1) if i not in drop) + "\n"


def existing_proof(tree: Path, base: Path, file: str, python: str) -> tuple[dict | None, str]:
    """(proof, starting point): an existing test of the module that fails on an assert here and passes on the base,
    trimmed to that test, is a proof as it is. A failing one that is not (fails on the base too, or only as part of
    its file) becomes the starting point she edits: its code and the assert that differs. Cached per file content:
    the hunt shows it to her first, then every suspect's proof starts from it."""
    key = (str(tree), str(base), file, hashlib.sha1((tree / file).read_bytes()).hexdigest())
    if key not in _PROOFS:
        _PROOFS[key] = _existing_proof(tree, base, file, python)
    return _PROOFS[key]


def _existing_proof(tree: Path, base: Path, file: str, python: str) -> tuple[dict | None, str]:
    start = ""
    for f in failing_tests(tree, file, python, limit=2):
        path = f["test"].split("::")[0]
        try:
            code = single_test((tree / path).read_text(encoding="utf-8", errors="replace"), f["test"])
        except OSError:
            code = None
        if not code:
            continue
        def fails(verdict: str, out: str) -> bool:
            return verdict == "proven" or (verdict == "crashed" and raised_in(out, file))

        verdict, out = run_proof(tree, code, python)
        if fails(verdict, out) and fails(*run_proof(tree, code, python)):          # twice: a flake is no proof
            before, _ = run_proof(base, code, python)
            if before == "passed":
                return {"proven": True, "test": code[:6000], "output": out[-800:], "tries": 0,
                        "via": f"existing test {f['test']}", "failure": f["section"][-1200:]}, ""
        if not start:
            start = (f"An existing test of this module fails on the new code ({f['test']}):\n{f['section'][-1000:]}\n"
                     f"Its code (start from it, keep only what shows your bug):\n{code[-2500:]}\n")
    return None, start


def run_proof(tree: Path, code: str, python: str) -> tuple[str, str]:
    """('proven' | 'passed' | 'useless', output)."""
    f = tree / PROOF
    f.write_text(code, encoding="utf-8")
    env = fresh_py.env(tree, APPDATA=tempfile.mkdtemp(prefix="litha-proof-"))
    try:
        r = subprocess.run([python, "-m", "pytest", "-q", "-p", "no:cacheprovider", PROOF], cwd=tree, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180, env=env)
        out = (r.stdout + r.stderr)[-2500:]
    except subprocess.TimeoutExpired:
        return "useless", "timeout"
    finally:
        f.unlink(missing_ok=True)
    if r.returncode == 0:
        return "passed", out
    if USELESS.search(out) or not re.search(r"\b\d+ failed\b", out):     # collection errors are not a proof
        return "useless", out
    if not re.search(r"^E\s+(assert\b|AssertionError)", out, re.M):    # a crash from misusing the code is not a proof
        return "crashed", out
    return "proven", out


def prove(tree: Path, risk: dict, python: str, asker=ask, tries: int = 3, base: Path | None = None,
          intent: str = "", diff_asker=None) -> dict:
    """base = a checkout of the code BEFORE the PR. With it, a proof also needs the same test to PASS there: the
    PR introduced the failure (her own wrong expectation fails on both and proves nothing). Order: an existing test
    that fails now (no model call), then a differential test (same calls on both sides, litha.bug_diff), then a
    test she writes herself. diff_asker answers the differential's prompts (default: her, when asker is her)."""
    src = (tree / risk["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(0, risk["line"] - 40), min(len(src), risk["line"] + 40)
    excerpt = "\n".join(f"{i + 1}: {src[i]}" for i in range(lo, hi))
    module = module_of(risk["file"])
    shape = {"outline": outline("\n".join(src))}
    classes = re.findall(r"^class (\w+)", shape["outline"], re.M)
    shape["example"] = example_test(tree, module, classes)
    start = ""
    if base is not None:                                            # the module's own tests first: no invented names
        found, start = existing_proof(tree, base, risk["file"], python)
        if found:
            return found
        from litha import bug_diff
        diff_asker = diff_asker or (bug_diff.ask if asker is ask else None)
        if diff_asker is not None:
            diff = bug_diff.differential(tree, base, risk, python, diff_asker, intent,
                                         shape=f"What the module defines:\n{shape['outline'][:1200]}\n"
                                               f"{shape['example'][:1500]}")
            if diff.get("proven"):
                return diff
    feedback = ""
    for n in range(1, tries + 1):
        try:
            answer = json.loads(asker(ASK.format(excerpt=excerpt, module=module, feedback=feedback, start=start,
                                                 **shape, **risk)))
        except (ValueError, TypeError):
            feedback = "Your last answer was not valid JSON.\n"
            continue
        if not answer.get("possible") or not str(answer.get("test", "")).strip():
            return {"proven": False, "why": "she could not write a proof", "tries": n}
        try:
            compile(str(answer["test"]), PROOF, "exec")
        except SyntaxError as e:
            feedback = f"Your test has a syntax error at line {e.lineno}: {e.msg}. Write it again, plain and simple.\n"
            continue
        verdict, out = run_proof(tree, str(answer["test"]), python)
        if verdict == "proven" and base is not None:
            before, base_out = run_proof(base, str(answer["test"]), python)
            if before != "passed":                                  # her expectation is wrong: show her, try again
                feedback = ("Your test fails on the code BEFORE the change too, so it tests something else (a wrong "
                            "expectation or setup), not this bug. Output on the old code:\n"
                            f"{base_out[-1200:]}\nFix the test so it passes on the old code and fails on the new.\n")
                continue
        if verdict == "proven":
            return {"proven": True, "test": str(answer["test"])[:3000], "output": out[-800:], "tries": n}
        said = {"passed": "PASSED, so it does not show the bug",
                "crashed": "crashed with an exception instead of failing an assert (wrong use of the code?)"}
        feedback = (f"Your test {said.get(verdict, 'could not run')}:\n"
                    f"{out[-1200:]}\nWrite a better test, or say it is not possible.\n")
    return {"proven": False, "why": "no failing test after retries", "tries": tries}
