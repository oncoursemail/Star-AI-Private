"""Small in-memory source limits and diagnostics shared by syntax-only checkers."""
from __future__ import annotations

MAX_SOURCE_BYTES = 64 * 1024


def problem(kind: str, message: str, *, line: int | None = None, column: int | None = None,
            severity: str = "error") -> dict:
    # No source identifier in name: the existing placeholder policy must not demote syntax failures.
    return {"kind": kind, "severity": severity, "name": None, "message": message[:240],
            "suggestion": None, "line": line, "column": column}


def source_problem(code: str) -> dict | None:
    if not isinstance(code, str):
        return problem("source_input", "The code must be text.")
    if len(code) > MAX_SOURCE_BYTES:
        return problem("source_limit", "This checker accepts at most 64 KiB per code block. Check a smaller block.")
    try:
        size = len(code.encode("utf-8", "strict"))
    except UnicodeError:
        return problem("source_input", "The source is not valid Unicode text.")
    if size > MAX_SOURCE_BYTES:
        return problem("source_limit", "This checker accepts at most 64 KiB per code block. Check a smaller block.")
    return None


def complexity_problem() -> dict:
    return problem("source_limit", "The source exceeds this checker's parsing limits. Check a smaller or less nested block.")
