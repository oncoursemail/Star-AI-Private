"""Bounded, nonexecuting feedback for the exact text a workspace tool wrote.

``passed`` means that one local syntax/parser check completed. It never means a
program ran, a schema matched, imports resolved, or behavior was tested. Luau's
existing heuristic findings remain in ``workspace._with_lint`` and are not
promoted to parser evidence here.

Baseline comparisons concern the first reported parser diagnostic only. They
are best-effort observations of captured text, not a concurrency guard or proof
that an edit caused a problem.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import warnings

try:
    import tomllib
except ImportError:  # Explicitly unavailable if packaged on an older Python.
    tomllib = None


MAX_VALIDATION_BYTES = 250_000
MAX_DIAGNOSTICS = 8
MAX_DIAGNOSTIC_CHARS = 400

_CHECKERS = {
    '.py': 'python.compile',
    '.pyw': 'python.compile',
    '.pyi': 'python.compile',
    '.json': 'json.loads',
    '.toml': 'tomllib.loads',
}
_LIMITATIONS = {
    'python.compile': 'Python syntax only; code was not executed and runtime behavior is unverified.',
    'json.loads': 'Strict JSON parsing only; no schema or runtime behavior was verified.',
    'tomllib.loads': 'TOML parsing only; no schema or runtime behavior was verified.',
    'none': 'No syntax checker is configured for this file type; runtime behavior is unverified.',
}


class _NonStandardJSONConstant(ValueError):
    pass


class _CheckerUnavailable(Exception):
    pass


def _diagnostic(code: str, message: str, *, line: int | None = None,
                column: int | None = None, severity: str = 'error') -> dict[str, Any]:
    """Messages are bounded and contain no source excerpt or absolute filename."""
    result: dict[str, Any] = {
        'code': code,
        'message': message[:MAX_DIAGNOSTIC_CHARS],
        'severity': severity,
    }
    # Parser locations are one-based; some errors (e.g. null bytes) have none.
    if isinstance(line, int) and line > 0:
        result['line'] = line
    if isinstance(column, int) and column > 0:
        result['column'] = column
    return result


def _check_python(text: str) -> list[dict[str, Any]]:
    try:
        # Compile includes context checks such as ``return`` outside a function.
        # The code object is immediately dropped; it is never executed or imported.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            compile(text, '<workspace>', 'exec', dont_inherit=True, optimize=0)
    except SyntaxError as exc:
        return [_diagnostic(type(exc).__name__, exc.msg,
                            line=exc.lineno, column=exc.offset)]
    return []


def _reject_json_constant(value: str) -> None:
    # json.loads otherwise accepts NaN and +/-Infinity, which are not JSON.
    raise _NonStandardJSONConstant(f'JSON does not permit the constant {value}.')


def _check_json(text: str) -> list[dict[str, Any]]:
    try:
        json.loads(text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        return [_diagnostic('JSONDecodeError', exc.msg,
                            line=exc.lineno, column=exc.colno)]
    except _NonStandardJSONConstant as exc:
        return [_diagnostic('NonStandardJSONConstant', str(exc))]
    return []


def _check_toml(text: str) -> list[dict[str, Any]]:
    if tomllib is None:
        raise _CheckerUnavailable('tomllib is unavailable')
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        # Python 3.11-3.13 include locations only in the message. Later versions
        # expose lineno/colno; prefer those where available.
        line, column = getattr(exc, 'lineno', None), getattr(exc, 'colno', None)
        if line is None:
            location = re.search(r'\(at line (\d+), column (\d+)\)$', str(exc))
            if location:
                line, column = map(int, location.groups())
        return [_diagnostic('TOMLDecodeError', str(exc), line=line, column=column)]
    return []


def _inspect(path: str | Path, text: str) -> dict[str, Any]:
    data = text.encode('utf-8')
    checker = _CHECKERS.get(Path(path).suffix.lower(), 'none')
    result: dict[str, Any] = {
        'checker': checker,
        'scope': 'file_syntax',
        'status': 'not_applicable' if checker == 'none' else 'unavailable',
        'content_sha256': hashlib.sha256(data).hexdigest(),
        'diagnostics': [],
        'runtime_verified': False,
        'summary': _LIMITATIONS[checker],
    }
    if checker == 'python.compile':
        result['checker_version'] = '.'.join(str(n) for n in sys.version_info[:3])
    if checker == 'none':
        return result
    if len(data) > MAX_VALIDATION_BYTES:
        result['diagnostics'] = [_diagnostic(
            'validation_size_limit', 'Syntax was not checked: content exceeds the validation byte limit.',
            severity='info')]
        return result
    try:
        check = {'python.compile': _check_python,
                 'json.loads': _check_json,
                 'tomllib.loads': _check_toml}[checker]
        result['diagnostics'] = check(text)[:MAX_DIAGNOSTICS]
    except Exception as exc:
        # Resource limits and checker defects are unavailable evidence, not proof
        # that the file has invalid syntax and not a reason to fail a saved write.
        result['diagnostics'] = [_diagnostic(
            'checker_unavailable', f'Syntax checker could not complete ({type(exc).__name__}).',
            severity='info')]
        return result
    result['status'] = 'failed' if result['diagnostics'] else 'passed'
    return result


def _same_failure(before: dict[str, Any], after: dict[str, Any],
                  previous_text: str, text: str) -> bool:
    if before['diagnostics'] != after['diagnostics']:
        return False
    # A matching generic parser message alone is insufficient: require that its
    # source line also matches. Without a location, require identical full text.
    line = after['diagnostics'][0].get('line')
    if line is None:
        return previous_text == text
    previous_lines, lines = previous_text.splitlines(), text.splitlines()
    return (line <= len(previous_lines) and line <= len(lines)
            and previous_lines[line - 1] == lines[line - 1])


def validate_text(path: str | Path, text: str, *, previous_text: str | None = None) -> dict[str, Any]:
    """Check the exact UTF-8 text without reading files, executing code, or tools.

    ``content_sha256`` includes original newlines and Unicode encoding. A
    baseline is the captured prior text, which might have changed concurrently.
    ``preexisting`` describes only the same first diagnostic on the same source
    line; ``newly_detected`` requires the captured baseline to have passed.
    """
    result = _inspect(path, text)
    result['comparison'] = 'unknown'
    if previous_text is None or result['status'] == 'not_applicable':
        return result
    baseline = _inspect(path, previous_text)
    result['baseline'] = baseline
    if result['status'] == 'failed':
        if baseline['status'] == 'passed':
            result['comparison'] = 'newly_detected'
        elif baseline['status'] == 'failed':
            result['comparison'] = ('preexisting' if _same_failure(baseline, result, previous_text, text)
                                    else 'changed')
    elif result['status'] == 'passed' and baseline['status'] == 'failed':
        result['comparison'] = 'changed'
    return result
