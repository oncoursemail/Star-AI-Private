"""Test-backed bug proofs: a claimed bug counts only when Litha writes a test that really fails on the PR's code.

prove(tree, risk) asks her for ONE small pytest file that should pass on correct code and fails because of the bug she
claimed, writes it as tests/_litha_proof_test.py in the PR checkout (never committed), runs it, deletes it.
Proven = the test FAILS with an assertion (or the code raises inside the module under test). A test that cannot even
run (syntax error, import of something that does not exist, error inside the test's own setup) proves nothing.
Up to 3 tries; each later try sees the previous output (syntax errors are caught before running).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

PROOF = "tests/_litha_proof_test.py"
ASK = """You claimed this bug in a pull request:
{file}:{line}: {why}

The real code (line numbers on the left):
{excerpt}

Prove it with ONE small pytest test that calls the real code (import it from its module, e.g. `from {module} import
...`), PASSES if the code were correct, and FAILS because of exactly this bug. No network, no files outside tmp_path,
no sleeping. If you cannot prove it, say so.
{feedback}Answer only JSON: {{"possible": true or false, "test": "<the whole python test file>"}}"""
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


def run_proof(tree: Path, code: str, python: str) -> tuple[str, str]:
    """('proven' | 'passed' | 'useless', output)."""
    f = tree / PROOF
    f.write_text(code, encoding="utf-8")
    env = dict(os.environ, APPDATA=tempfile.mkdtemp(prefix="litha-proof-"))
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


def prove(tree: Path, risk: dict, python: str, asker=ask, tries: int = 3, base: Path | None = None) -> dict:
    """base = a checkout of the code BEFORE the PR. With it, a proof also needs the same test to PASS there: the
    PR introduced the failure (her own wrong expectation fails on both and proves nothing)."""
    src = (tree / risk["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(0, risk["line"] - 40), min(len(src), risk["line"] + 40)
    excerpt = "\n".join(f"{i + 1}: {src[i]}" for i in range(lo, hi))
    feedback = ""
    for n in range(1, tries + 1):
        try:
            answer = json.loads(asker(ASK.format(excerpt=excerpt, module=module_of(risk["file"]), feedback=feedback,
                                                 **risk)))
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
            if before != "passed":
                return {"proven": False, "why": f"the test also fails ({before}) on the code before the PR: it shows "
                        "her expectation, not a bug the PR made", "tries": n, "output": base_out[-400:]}
        if verdict == "proven":
            return {"proven": True, "test": str(answer["test"])[:3000], "output": out[-800:], "tries": n}
        said = {"passed": "PASSED, so it does not show the bug",
                "crashed": "crashed with an exception instead of failing an assert (wrong use of the code?)"}
        feedback = (f"Your test {said.get(verdict, 'could not run')}:\n"
                    f"{out[-1200:]}\nWrite a better test, or say it is not possible.\n")
    return {"proven": False, "why": "no failing test after retries", "tries": tries}
