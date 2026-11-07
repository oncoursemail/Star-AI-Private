"""Bounded local inputs for the optional recompilation analysis tools.

These helpers read selected workspace files; they do not execute them. Metadata
checks detect observed changes but are not an atomic filesystem snapshot or an
OS sandbox against hostile concurrent ancestor-directory replacement.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_ELF_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
READ_TIMEOUT_SECONDS = 15
_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$)\Z", re.I)
_INVALID = set('<>:"\\|?*')


@dataclass(frozen=True)
class InputSpec:
    label: str
    max_bytes: int
    expected_sha256: str | None = None


@dataclass(frozen=True)
class InputSnapshot:
    label: str
    path: Path
    identity: tuple[int, ...]
    data: bytes
    sha256: str
    pinned: bool

    def receipt(self) -> dict:
        return {
            "path": self.label,
            "size_bytes": len(self.data),
            "sha256": self.sha256,
            "pin_checked": self.pinned,
            "provenance": "not_authenticated",
        }


def _parts(label: str) -> tuple[str, ...]:
    if not isinstance(label, str) or not 1 <= len(label) <= 500:
        raise ValueError("A bounded workspace-relative path is required")
    parts = tuple(label.split("/"))
    for part in parts:
        if (not part or part in {".", ".."} or part.endswith((" ", "."))
                or any(ord(ch) < 32 or ch in _INVALID for ch in part)
                or _RESERVED.fullmatch(part.split(".", 1)[0])):
            raise PermissionError("Path is not an unambiguous portable workspace path")
    return parts


def _identity(info: os.stat_result) -> tuple[int, ...]:
    # On Windows st_ctime_ns differs between lstat (creation) and fstat (change) of one file.
    ctime = 0 if os.name == "nt" else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, ctime)


def _no_links(workspace: Path, label: str) -> os.stat_result:
    parts = _parts(label)
    current = workspace
    root_info = current.lstat()
    if (stat.S_ISLNK(root_info.st_mode)
            or getattr(root_info, "st_file_attributes", 0) & 0x400
            or not stat.S_ISDIR(root_info.st_mode)):
        raise PermissionError("Workspace is no longer a plain directory")
    info = root_info
    for index, part in enumerate(parts):
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PermissionError("Links and reparse points are not analysis inputs")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("An input ancestor is not a directory")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Analysis input is not a regular file")
    return info


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ValueError("The cooperative analysis read budget was exhausted")


def assert_inputs_stable(workspace: Path, snapshots: Sequence[InputSnapshot]) -> None:
    """Recheck every input after all reads/comparisons, including earlier inputs."""
    for item in snapshots:
        info = _no_links(workspace, item.label)
        if _identity(info) != item.identity or _identity(item.path.stat()) != item.identity:
            raise ValueError("An input changed during analysis; results are not stable")


def read_inputs(
    workspace: Path | None,
    resolve: Callable[[str], Path],
    specs: Sequence[InputSpec],
) -> list[InputSnapshot]:
    """Preflight all paths, then stream bounded files without creating outputs."""
    if workspace is None:
        raise PermissionError("Select a workspace before analysing local inputs")
    if not 1 <= len(specs) <= 3:
        raise ValueError("One to three analysis inputs are required")
    deadline = time.monotonic() + READ_TIMEOUT_SECONDS
    prepared: list[tuple[InputSpec, Path, tuple[int, ...]]] = []
    names: set[str] = set()
    inodes: set[tuple[int, int]] = set()
    for spec in specs:
        _check_deadline(deadline)
        _parts(spec.label)
        if type(spec.max_bytes) is not int or not 1 <= spec.max_bytes <= MAX_ELF_BYTES:
            raise ValueError("Invalid input byte budget")
        if spec.expected_sha256 is not None and (
            not isinstance(spec.expected_sha256, str) or not _HASH.fullmatch(spec.expected_sha256)
        ):
            raise ValueError("An expected SHA-256 must contain exactly 64 hexadecimal digits")
        path = resolve(spec.label)
        # The existing gateway still enforces workspace/credential boundaries.
        if not isinstance(path, Path) or not path.is_relative_to(workspace):
            raise PermissionError("Resolved input escapes the selected workspace")
        info = _no_links(workspace, spec.label)
        identity = _identity(info)
        if _identity(path.stat()) != identity:
            raise ValueError("Input identity changed during path validation")
        if info.st_size > spec.max_bytes:
            raise ValueError(f"Input exceeds its {spec.max_bytes}-byte analysis budget")
        name = unicodedata.normalize("NFC", path.as_posix()).casefold()
        inode = (info.st_dev, info.st_ino)
        if name in names or (info.st_ino != 0 and inode in inodes):
            raise ValueError("Analysis inputs must be distinct files, not aliases")
        names.add(name)
        if info.st_ino != 0:
            inodes.add(inode)
        prepared.append((spec, path, identity))

    snapshots: list[InputSnapshot] = []
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    for spec, path, identity in prepared:
        _check_deadline(deadline)
        if _identity(_no_links(workspace, spec.label)) != identity:
            raise ValueError("Input changed before it could be read")
        fd = os.open(path, flags)
        try:
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                if _identity(os.fstat(handle.fileno())) != identity:
                    raise ValueError("Opened input differs from its inspected identity")
                chunks = bytearray()
                digest = hashlib.sha256()
                while True:
                    _check_deadline(deadline)
                    chunk = handle.read(min(CHUNK_BYTES, spec.max_bytes - len(chunks) + 1))
                    if not chunk:
                        break
                    if len(chunks) + len(chunk) > spec.max_bytes:
                        raise ValueError("Input grew beyond its byte budget")
                    chunks.extend(chunk)
                    digest.update(chunk)
                if _identity(os.fstat(handle.fileno())) != identity:
                    raise ValueError("Input changed while it was being read")
        finally:
            if fd >= 0:
                os.close(fd)
        actual = digest.hexdigest()
        if spec.expected_sha256 is not None and actual != spec.expected_sha256.lower():
            raise ValueError("Input SHA-256 does not match the supplied pin")
        snapshots.append(InputSnapshot(
            spec.label, path, identity, bytes(chunks), actual, spec.expected_sha256 is not None,
        ))
    _check_deadline(deadline)
    assert_inputs_stable(workspace, snapshots)
    return snapshots


def parse_strict_json(data: bytes) -> dict:
    """Reject duplicate keys, non-finite numbers and non-object documents."""
    if not isinstance(data, bytes) or len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON input exceeds its bounded byte contract")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Non-finite JSON numbers are not accepted")

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON numbers are not accepted")
        return number

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=constant, parse_float=finite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Input must be a bounded UTF-8 JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON evidence must be an object")
    return value
