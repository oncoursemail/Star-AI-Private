"""Bug hunt: Litha reads each changed function on its own and names a suspected bug; only PROVEN suspicions count.

Measured 2026-10-31: whole-diff review caught 0/3 planted bugs; a per-function "find the bug" prompt caught 2/3 but
also flagged 3 lines of a clean file. So every suspicion goes through star.bug_proof with the code BEFORE the change:
her test must pass before and fail after. False flags die there; real regressions survive.

    hunt(head, base, changed)  ->  [{"file", "line", "why", "proof"}]  (proven only)
changed = {path: set(changed line numbers)} (from the PR diff, or a bench mutant).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from star import bug_proof

HUNT = """You are Litha, a careful code reviewer. This function was just changed (changed lines are marked >>).
{intent}{doc}
{func}
{uses}
Read every condition, comparison and return value slowly. Is there a line whose logic is wrong: an inverted
condition, `and`/`or` swapped, `<` vs `<=`, `is None` vs `is not None`, a wrong variable, min/max swapped, a missing
`not`, an off-by-one, a dropped `return`, swapped arguments? Only a changed line can hold the bug. A behaviour
change the author says they meant is not a bug. Name up to 2 suspect lines, most likely first (each one will be
checked with a test, so a wrong guess costs nothing); an empty list if nothing is wrong.
Answer only JSON: {{"suspects": [{{"line": <number>, "why": "<what is wrong and what it should be>"}}]}}"""


def functions_touching(source: str, lines: set[int]) -> list[tuple[int, int]]:
    """(first, last) line of every innermost function that contains a changed line."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    spans = [(n.lineno, n.end_lineno or n.lineno) for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    out = set()
    for no in lines:
        inner = [s for s in spans if s[0] <= no <= s[1]]
        if inner:
            out.add(min(inner, key=lambda s: s[1] - s[0]))
    return sorted(out)


def test_uses(head: Path, name: str, limit: int = 12) -> str:
    """Lines of the repo's tests that call this function: what callers expect from it."""
    if len(name) < 4:
        return ""
    pat = re.compile(rf"\b{re.escape(name)}\(")
    hits = []
    for f in sorted((head / "tests").glob("test_*.py")):
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if pat.search(ln):
                hits.append(f"{f.name}: {ln.strip()[:160]}")
                if len(hits) == limit:
                    break
        if len(hits) == limit:
            break
    return ("How the tests call it (what callers expect):\n" + "\n".join(hits) + "\n") if hits else ""


def suspects(ans: dict) -> list[tuple[int, str]]:
    """[(line, why)] from {"suspects": [...]} (or the older {"bug", "line", "why"} shape)."""
    rows = ans.get("suspects") if isinstance(ans.get("suspects"), list) else [ans] if ans.get("bug") else []
    out = []
    for r in rows[:2]:
        try:
            out.append((int(r.get("line") or 0), str(r.get("why", ""))[:300]))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def hunt(head: Path, base: Path, changed: dict[str, set[int]], python: str, asker=bug_proof.ask,
         prove=bug_proof.prove, max_funcs: int = 6, intent: str = "") -> list[dict]:
    found = []
    budget = max_funcs
    for path, lines in changed.items():
        if not path.endswith(".py") or path.startswith("tests/"):
            continue
        source = (head / path).read_text(encoding="utf-8", errors="replace")
        src_lines = source.splitlines()
        doc = ast.get_docstring(ast.parse(source)) or ""
        for first, last in functions_touching(source, lines):
            if budget <= 0:
                return found
            budget -= 1
            func = "\n".join(f"{'>>' if i + 1 in lines else '  '} {i + 1}: {src_lines[i]}" for i in range(first - 1, last))
            name = re.match(r"\s*(?:async\s+)?def\s+(\w+)", src_lines[first - 1])
            try:
                said = f"What the author says the change is for: {intent[:1200]}\n" if intent else ""
                ans = json.loads(asker(HUNT.format(intent=said, doc=f"Module docstring: {doc[:800]}" if doc else "",
                                                   func=func, uses=test_uses(head, name.group(1)) if name else "")))
            except (ValueError, TypeError):
                continue
            for line, why in suspects(ans if isinstance(ans, dict) else {}):
                if not first <= line <= last:
                    continue
                risk = {"file": path, "line": line, "severity": "high", "why": why}
                proof = prove(head, risk, python, asker, base=base)
                if proof.get("proven"):
                    found.append({**risk, "proof": {k: v for k, v in proof.items() if k != "test"}})
                    break                                   # one proven bug per function is enough to hold
    return found
