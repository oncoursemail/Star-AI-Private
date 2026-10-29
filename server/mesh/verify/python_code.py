"""Python compiler diagnostics, without executing code, resolving imports or writing bytecode."""
from __future__ import annotations

import sys

from .source_limits import complexity_problem, problem, source_problem

GRAMMAR_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}"


def check_python(code: str) -> tuple[list[dict], bool]:
    """Return problems and whether the host interpreter completed its syntax check."""
    if issue := source_problem(code):
        return [issue], False
    try:
        compile(code, "<litha-python>", "exec", flags=0, dont_inherit=True, optimize=0)
    except SyntaxError as exc:
        if any(limit in exc.msg for limit in ("too many nested", "too many levels", "Exceeds the limit")):
            return [complexity_problem()], False
        return [problem("syntax", f"Python {GRAMMAR_VERSION} syntax: {exc.msg}",
                        line=exc.lineno, column=exc.offset)], True
    except (RecursionError, MemoryError, OverflowError):
        return [complexity_problem()], False
    return [], True
