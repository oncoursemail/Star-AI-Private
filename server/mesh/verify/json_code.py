"""JSON syntax and ambiguous duplicate-member checks; no schema validation or file access."""
from __future__ import annotations

import json

from .source_limits import complexity_problem, problem, source_problem

MAX_DUPLICATES = 16
MAX_DEPTH = 128


class _NonFinite(ValueError):
    pass


def _too_deep(code: str) -> bool:
    depth = 0
    quoted = escaped = False
    for char in code:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return True
        elif char in "]}":
            depth -= 1
    return False


def analyze_json(code: str) -> tuple[list[dict], bool, frozenset[str]]:
    """Return diagnostics, completed-check status and root object member names in one parse."""
    if issue := source_problem(code):
        return [issue], False, frozenset()
    if _too_deep(code):
        return [complexity_problem()], False, frozenset()
    duplicates = []

    def pairs(items):
        seen = set()
        for key, _value in items:
            if key in seen and key not in duplicates and len(duplicates) < MAX_DUPLICATES:
                duplicates.append(key)
            seen.add(key)
        # Keep only member names; do not retain values or silently choose duplicate values.
        return frozenset(seen)

    def constant(_token):
        raise _NonFinite

    try:
        # Numeric lexemes need no host-number conversion for syntax validation. Valid huge JSON numbers
        # must not fail because of Python's integer-digit or floating-point range limits.
        root = json.loads(code, object_pairs_hook=pairs, parse_constant=constant, parse_int=str, parse_float=str)
    except json.JSONDecodeError as exc:
        return [problem("syntax", exc.msg, line=exc.lineno, column=exc.colno)], True, frozenset()
    except _NonFinite:
        return [problem("syntax", "NaN and Infinity are not JSON numbers. Use a value supported by JSON.")], True, frozenset()
    except (RecursionError, MemoryError, OverflowError):
        return [complexity_problem()], False, frozenset()
    issues = []
    for key in duplicates:
        label = json.dumps(key, ensure_ascii=True)
        if len(label) > 96:
            label = label[:93] + "..."
        issues.append(problem("json_duplicate_key", f"Duplicate JSON object key {label}; later values can overwrite earlier ones.",
                              severity="warning"))
    return issues, True, root if isinstance(root, frozenset) else frozenset()


def check_json(code: str) -> tuple[list[dict], bool]:
    issues, checked, _members = analyze_json(code)
    return issues, checked
