"""Bounded, local-only diagnostic artifacts shared by opt-in collectors.

These helpers are not a code sandbox. Captures remain untrusted evidence, never
permission to execute code, change a setting, or certify a repair.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit

from .redact import redact_text

SCHEMA = "star-debug-evidence-v1"
MAX_REPORT_BYTES = 2_000_000
_URL = re.compile(r"(?i)\b(?:https?|wss?|ftp)://[^\s<>\"']+")
_HEADER = re.compile(r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)[\"']?\s*[:=]\s*[^\r\n]+")
_ASSIGNMENT_HEAD = re.compile(r"\b([A-Za-z_][A-Za-z0-9_-]{0,160})([\"']?\s*[:=]\s*)")
_ASSIGNMENT_VALUE = re.compile(r"(?:\[REDACTED\]|\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;\]}]+)")
_SENSITIVE_NAME = re.compile(
    r"(?i)^(?:[a-z0-9]+[_-])*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie)"
    r"(?:[_-][a-z0-9]+)*$"
)


def _sensitive_name(name: str) -> bool:
    # Split camelCase and acronyms, but never treat a path such as test_tokens.py
    # as a credential name. Those keys are required for source-hash comparison.
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized).strip("_")
    return bool(_SENSITIVE_NAME.fullmatch(normalized))


def _redact_assignments(text: str) -> str:
    # Scan heads, so an ordinary outer assignment never consumes a nested secret.
    # Once a sensitive value is hidden, ignore heads inside that same value.
    pieces, cursor = [], 0
    for head in _ASSIGNMENT_HEAD.finditer(text):
        if head.start() < cursor or not _sensitive_name(head.group(1)):
            continue
        value = _ASSIGNMENT_VALUE.match(text, head.end())
        if value is not None:
            pieces.extend((text[cursor:head.end()], "[REDACTED]"))
            cursor = value.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def _clean_url(match: re.Match) -> str:
    try:
        parsed = urlsplit(match.group(0))
        host = parsed.hostname or "redacted-host"
        if ":" in host:
            host = "[" + host + "]"
        port = parsed.port
        return urlunsplit((parsed.scheme, host + (f":{port}" if port else ""), parsed.path, "", ""))
    except (ValueError, UnicodeError):
        return "[REDACTED URL]"


def redact_debug(value, limit: int = 2000) -> str:
    """Sanitize diagnostic text, including short secrets and URL query values.

    This deliberately redacts more aggressively than editable source reads.
    Arbitrary personal data cannot be reliably detected; raw captures stay local.
    """
    if type(limit) is not int or not 0 <= limit <= MAX_REPORT_BYTES:
        raise ValueError("Invalid diagnostic text limit")
    if value is None:
        return ""
    # Redact BEFORE final truncation, so cutting a credential cannot hide its shape.
    text = str(value)[:MAX_REPORT_BYTES]
    text = redact_text(text)
    text = _HEADER.sub(lambda m: m.group(1) + ": [REDACTED]", text)
    text = _redact_assignments(text)
    text = _URL.sub(_clean_url, text)
    text = "".join(c for c in text if c in "\n\r\t" or ord(c) >= 32)
    return text if len(text) <= limit else text[:limit] + " [TRUNCATED]"


def sanitize_tree(value, *, depth: int = 0):
    if depth > 16:
        raise ValueError("Diagnostic data is nested too deeply")
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Diagnostic numbers must be finite")
        return value
    if isinstance(value, str):
        return redact_debug(value, limit=12000)
    if isinstance(value, list):
        if len(value) > 20000:
            raise ValueError("Too many diagnostic records")
        return [sanitize_tree(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 20000 or any(not isinstance(k, str) for k in value):
            raise ValueError("Invalid diagnostic object")
        result = {}
        named_secret = isinstance(value.get("name"), str) and _sensitive_name(value["name"])
        for key, item in value.items():
            clean_key = redact_debug(key, limit=600)
            if clean_key in result:
                raise ValueError("Diagnostic keys collide after redaction")
            hide_value = named_secret and key in {"value", "display_value", "repr", "raw", "text"}
            result[clean_key] = "[REDACTED]" if _sensitive_name(key) or hide_value else sanitize_tree(item, depth=depth + 1)
        return result
    raise ValueError("Unsupported diagnostic value")


def sha256_file(path: Path) -> str:
    """Hash a small regular source file; no links or unbounded reads."""
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
            return ""
        with path.open("rb") as handle:
            raw = handle.read(MAX_REPORT_BYTES + 1)
        return hashlib.sha256(raw).hexdigest() if len(raw) <= MAX_REPORT_BYTES else ""
    except OSError:
        return ""


def write_report(path: Path, payload: dict) -> Path:
    """Atomically write an explicitly requested report; never follow a target link."""
    path = Path(path).expanduser()
    if path.suffix.lower() != ".json":
        raise ValueError("Diagnostic reports require a .json output path")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise PermissionError("Diagnostic output must not traverse symbolic links")
    if path.exists() and not path.is_file():
        raise ValueError("Diagnostic output must be a regular file")
    if not path.parent.is_dir():
        raise ValueError("Diagnostic output directory must already exist")
    clean = sanitize_tree(payload)
    raw = json.dumps(clean, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Diagnostic report exceeds the 2 MB limit")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".star-debug-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
        # Recheck after writing: do not replace a newly introduced target link.
        if path.is_symlink():
            raise PermissionError("Diagnostic output became a symbolic link")
        os.replace(temporary, path)
        return path
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
