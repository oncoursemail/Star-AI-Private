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
from pathlib import Path

from star import bug_proof

HUNT = """You are Litha, a careful code reviewer. This function was just changed (changed lines are marked >>).
{intent}{doc}
{func}

Read every condition, comparison and return value slowly. Is there a line whose logic is wrong: an inverted
condition, `and`/`or` swapped, `<` vs `<=`, `is None` vs `is not None`, a wrong variable, min/max swapped, a missing
`not`, an off-by-one? Only a changed line can hold the bug. A behaviour change the author says they meant is not a
bug. If nothing is wrong, say so.
Answer only JSON: {{"bug": true or false, "line": <number or 0>, "why": "<what is wrong and what it should be>"}}"""


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
            try:
                said = f"What the author says the change is for: {intent[:1200]}\n" if intent else ""
                ans = json.loads(asker(HUNT.format(intent=said, doc=f"Module docstring: {doc[:800]}" if doc else "",
                                                   func=func)))
            except (ValueError, TypeError):
                continue
            if not ans.get("bug"):
                continue
            try:
                line = int(ans.get("line") or 0)
            except (TypeError, ValueError):
                continue
            if not first <= line <= last:
                continue
            risk = {"file": path, "line": line, "severity": "high", "why": str(ans.get("why", ""))[:300]}
            proof = prove(head, risk, python, asker, base=base)
            if proof.get("proven"):
                found.append({**risk, "proof": {k: v for k, v in proof.items() if k != "test"}})
    return found
