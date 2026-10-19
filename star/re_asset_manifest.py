"""Bounded, read-only asset integrity checks for STAR's optional RE gateway.

An original implementation informed by Grand-V's size-only package check.
All paths are workspace-relative and pass the gateway resolver. A manifest is
untrusted input; matching its hashes proves consistency, not trusted provenance.
No asset is executed, downloaded, extracted, changed, or imported as a lesson.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import unicodedata
from collections.abc import Callable
from urllib.parse import urlsplit

FORMAT = "star-asset-manifest-v1"
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ASSETS = 128
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_HASH_SECONDS = 15.0
CHUNK_BYTES = 64 * 1024
MAX_RESULT_DETAILS = 24
_DIGEST = re.compile(r"[a-fA-F0-9]{64}\Z")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.IGNORECASE)


def portable_asset_path(value: str) -> str:
    """Reject ambiguous Windows/POSIX paths before the gateway touches disk."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 500
            or value.startswith("/") or "\\" in value or ":" in value
            or any(char in '<>"|?*' for char in value)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Asset paths must be portable workspace-relative paths")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or part.endswith((".", " ")) or _RESERVED.match(part)
           for part in parts):
        raise ValueError("Asset path has a traversal, empty, or reserved component")
    return value


def resolve_manifest_member(root: Path, resolver: Callable[[str], Path], relative: str) -> Path:
    """Apply stricter manifest path rules without changing the existing gateway."""
    portable_asset_path(relative)
    cursor = root
    for part in relative.split("/"):
        cursor = cursor / part
        # Reject links even when they point back inside the workspace. On Windows
        # junctions and other reparse points also need an explicit check.
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise PermissionError("Manifest paths cannot contain symlinks or reparse points")
    return resolver(relative)


def _identity(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _regular(path: Path) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Manifest and asset paths must be regular non-link files")
    return info


def _read_file(path: Path, expected: os.stat_result, *, deadline: float,
               capture: bool = False) -> tuple[str, int, bytes]:
    """Hash an already resolved regular file, detecting ordinary substitutions.

    O_NOFOLLOW/O_NONBLOCK protect the final component where available. Parent
    directories must remain stable during the call; this is not an OS sandbox
    against a hostile process concurrently replacing directory ancestors.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    digest = hashlib.sha256()
    total = 0
    chunks = []
    with os.fdopen(os.open(path, flags), "rb") as file:
        if _identity(os.fstat(file.fileno())) != _identity(expected):
            raise ValueError("File changed before verification")
        remaining = expected.st_size
        while remaining:
            if time.monotonic() > deadline:
                raise TimeoutError("Asset verification reached its time budget")
            chunk = file.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise ValueError("File changed or ended during verification")
            total += len(chunk)
            remaining -= len(chunk)
            digest.update(chunk)
            if capture:
                chunks.append(chunk)
        if (_identity(os.fstat(file.fileno())) != _identity(expected)
                or _identity(_regular(path)) != _identity(expected)):
            raise ValueError("File changed during verification")
    return digest.hexdigest(), total, b"".join(chunks)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object fields are not allowed")
        result[key] = value
    return result


def _nonfinite(_value: str):
    raise ValueError("Non-finite JSON numbers are not allowed")


def _text(value: object, name: str, limit: int) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{name} must be nonempty bounded text")
    return value


def _hash_pin(value: object) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ValueError("SHA-256 must contain exactly 64 hexadecimal characters")
    return value.lower()


def _manifest(raw: bytes) -> dict:
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                              parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Manifest must be bounded valid UTF-8 JSON") from exc
    keys = {"schema_version", "package_id", "version", "assets"}
    if not isinstance(document, dict) or set(document) != keys:
        raise ValueError("Manifest fields must be schema_version, package_id, version, and assets")
    if document["schema_version"] != FORMAT:
        raise ValueError(f"Manifest schema_version must be {FORMAT}")
    _text(document["package_id"], "package_id", 120)
    _text(document["version"], "version", 120)
    entries = document["assets"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ASSETS:
        raise ValueError(f"Manifest must contain between 1 and {MAX_ASSETS} assets")
    seen = set()
    declared_bytes = 0
    for entry in entries:
        required = {"path", "size_bytes", "sha256"}
        if (not isinstance(entry, dict) or not required <= set(entry)
                or not set(entry) <= required | {"source", "license"}):
            raise ValueError("Asset fields must be path, size_bytes, sha256, and optional source/license")
        label = portable_asset_path(entry["path"])
        normalized = unicodedata.normalize("NFC", label).casefold()
        if normalized in seen:
            raise ValueError("Duplicate asset paths are not allowed")
        seen.add(normalized)
        size = entry["size_bytes"]
        if type(size) is not int or not 0 <= size <= MAX_ASSET_BYTES:
            raise ValueError("Asset size_bytes must be an integer from 0 to 128 MiB")
        declared_bytes += size
        _hash_pin(entry["sha256"])
        if "source" in entry:
            value = _text(entry["source"], "source", 1000)
            try:
                parsed = urlsplit(value)
            except ValueError as exc:
                raise ValueError("Asset source must be an HTTPS provenance URL") from exc
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Asset source must be an HTTPS provenance URL without credentials")
        if "license" in entry:
            _text(entry["license"], "license", 120)
    if declared_bytes > MAX_TOTAL_BYTES:
        raise ValueError("Declared assets exceed the 512 MiB total verification budget")
    return document


def verify_asset_manifest(
    manifest: Path,
    resolve_asset: Callable[[str], Path],
    *,
    manifest_label: str,
    expected_manifest_sha256: str | None = None,
) -> dict:
    """Check listed assets against a strict versioned manifest, without writes.

    The caller supplies a resolver that enforces its existing workspace and
    sensitive-path boundary. Every member is resolved before any asset hashing.
    Schema/permission errors reject the call; absent/mismatched files yield FAIL.
    Unlisted files are outside this audit, including executable dependencies.
    """
    portable_asset_path(manifest_label)
    pin = None if expected_manifest_sha256 is None else _hash_pin(expected_manifest_sha256)
    deadline = time.monotonic() + MAX_HASH_SECONDS
    initial = _regular(manifest)
    if not 0 < initial.st_size <= MAX_MANIFEST_BYTES:
        raise ValueError("Manifest must be nonempty and no larger than 128 KiB")
    manifest_hash, _count, raw = _read_file(manifest, initial, deadline=deadline, capture=True)
    document = _manifest(raw)
    output: dict = {
        "verdict": "FAIL", "schema_version": FORMAT,
        "package_id": document["package_id"], "version": document["version"],
        "manifest_path": manifest_label, "manifest_sha256": manifest_hash,
        "manifest_pin_matches": None if pin is None else manifest_hash == pin,
        "asset_count": len(document["assets"]), "checked_files": 0, "omitted_results": 0,
        "bytes_hashed": 0, "results": [], "read_only": True,
        "executed": False, "runtime_verified": False,
        "reference_provenance": "not_authenticated",
        "scope": "listed_assets_only",
        "notice": (
            "PASS checks listed file sizes and SHA-256 values against the supplied manifest. "
            "The manifest and source/license labels are caller-supplied and unauthenticated. "
            "Unlisted files, runtime behavior, performance, and asset rights are not verified."
        ),
    }
    if output["manifest_pin_matches"] is False:
        output["reason"] = "manifest_pin_mismatch"
        return output

    resolved = []
    identities = {(initial.st_dev, initial.st_ino)}
    actual_bytes = 0
    for entry in document["assets"]:
        try:
            path = resolve_asset(entry["path"])
            info = _regular(path)
        except PermissionError:
            raise
        except (FileNotFoundError, NotADirectoryError):
            resolved.append((entry, None, None, "unavailable"))
            continue
        except ValueError as exc:
            # The existing RE resolver deliberately exposes only this generic
            # message for a missing path. Other resolver failures stay failures.
            if str(exc) != "Path is not a file":
                raise
            resolved.append((entry, None, None, "unavailable"))
            continue
        except OSError:
            resolved.append((entry, None, None, "unreadable"))
            continue
        identity = (info.st_dev, info.st_ino)
        if identity in identities:
            raise ValueError("Duplicate asset aliases or manifest self-reference are not allowed")
        identities.add(identity)
        if info.st_size > MAX_ASSET_BYTES:
            raise ValueError("Actual asset exceeds the 128 MiB file limit")
        actual_bytes += info.st_size
        if actual_bytes > MAX_TOTAL_BYTES:
            raise ValueError("Actual assets exceed the 512 MiB total verification budget")
        resolved.append((entry, path, info, None))

    # Budget includes bytes read on attempts that later encounter a mutation.
    # Reserve each file's whole observed size before reading; bytes_hashed counts
    # only completed stable reads and is therefore a lower bound on actual I/O.
    complete = True
    for entry, path, info, error in resolved:
        result = {"path": entry["path"], "status": error or "pending"}
        if error:
            output["results"].append(result)
            continue
        assert path is not None and info is not None
        if time.monotonic() > deadline:
            result["status"] = "not_checked_time_budget"
            complete = False
        elif info.st_size != entry["size_bytes"]:
            result.update(status="size_mismatch", expected_size=entry["size_bytes"], actual_size=info.st_size)
            output["checked_files"] += 1
        else:
            try:
                # Recheck the original relative path immediately before and
                # after reading so ordinary link/path replacements are caught.
                if resolve_asset(entry["path"]) != path:
                    raise ValueError("Asset path changed before verification")
                digest, count, _raw = _read_file(path, info, deadline=deadline)
                if resolve_asset(entry["path"]) != path:
                    raise ValueError("Asset path changed during verification")
                output["bytes_hashed"] += count
                output["checked_files"] += 1
                result.update(status="matched" if digest == entry["sha256"].lower() else "hash_mismatch",
                              actual_sha256=digest, size_bytes=count)
            except TimeoutError:
                result["status"] = "not_checked_time_budget"
                complete = False
            except (ValueError, FileNotFoundError, NotADirectoryError):
                result["status"] = "changed"
            except OSError:
                result["status"] = "unreadable"
        output["results"].append(result)

    # An earlier file can change while a later one is hashed. Revalidate the
    # observed identities across the whole audit before issuing a package PASS.
    # This remains an observational check, not an atomic filesystem snapshot.
    for result, (entry, path, info, _error) in zip(output["results"], resolved):
        if result["status"] != "matched":
            continue
        assert path is not None and info is not None
        if time.monotonic() > deadline:
            result["status"] = "not_checked_time_budget"
            complete = False
            continue
        try:
            if (resolve_asset(entry["path"]) != path
                    or _identity(_regular(path)) != _identity(info)):
                result["status"] = "changed"
        except (OSError, ValueError):
            result["status"] = "changed"

    try:
        if _identity(_regular(manifest)) != _identity(initial):
            output["reason"] = "manifest_changed"
            return _bounded_result(output)
    except (OSError, ValueError):
        output["reason"] = "manifest_changed"
        return _bounded_result(output)
    output["verdict"] = ("INCOMPLETE" if not complete else
                         "PASS" if all(r["status"] == "matched" for r in output["results"]) else "FAIL")
    return _bounded_result(output)


def _bounded_result(output: dict) -> dict:
    counts = {}
    for result in output["results"]:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    output["status_counts"] = counts
    # Show failures first without emitting an unbounded model transcript.
    details = sorted(output["results"], key=lambda item: item["status"] == "matched")
    output["omitted_results"] = max(0, len(details) - MAX_RESULT_DETAILS)
    output["results"] = details[:MAX_RESULT_DETAILS]
    return output
