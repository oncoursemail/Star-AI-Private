"""Bounded, reviewable text edits through STAR's existing workspace boundary.

Plans contain private before/after text for the host's reversible job record; they
are not model tools or permission grants. Applying still needs ``allow_write=True``.
All files are checked before the first write, then checked again before their own
write. Each replacement is atomic through Workspace, but a batch is NOT a filesystem
transaction. An error or Stop can leave verified earlier edits in place.

The process-local lock covers overlapping roots as well as identical roots. Other
applications do not take this lock: hashes are observations, not an OS-level atomic
compare-and-swap or a claim that syntax, tests, or runtime behavior were verified.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
from hashlib import sha256
import os
from pathlib import Path
import stat
import threading

from .edit_match import apply_edit
from .workspace import MAX_READ_BYTES, MAX_WRITE_BYTES, Workspace

MAX_FILES = 16
MAX_TOTAL_BYTES = 1_048_576  # Combined before AND after UTF-8 content.
MAX_FILE_BYTES = min(MAX_READ_BYTES, MAX_WRITE_BYTES)
MAX_DIFF_CHARS = 6000
MAX_DIFF_LINES = 100
_EXECUTION_LOCK = threading.RLock()
_PLAN_KEYS = frozenset({"version", "direction", "root", "root_identity", "files", "file_count",
                        "total_before_bytes", "total_after_bytes", "total_content_bytes"})
_FILE_KEYS = frozenset({"path", "before", "after", "before_sha256", "after_sha256", "before_bytes",
                        "after_bytes", "diff", "diff_truncated", "replacements", "match_strategy"})


class BulkEditConflict(ValueError):
    """A preview no longer describes the selected workspace or file contents."""


class BulkEditVerificationError(RuntimeError):
    """A replacement's expected bytes could not be verified after the write."""


def _relative_path(value: object) -> str:
    if (not isinstance(value, str) or not value or len(value) > 500 or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError("Use an explicit relative file path with forward slashes")
    path = Path(value)
    if path.is_absolute() or path.drive or path.root:
        raise PermissionError("Absolute paths are blocked")
    return value


def _bytes(value: object) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_FILE_BYTES or "\x00" in value:
        raise ValueError("Bulk edits require bounded UTF-8 text without NUL bytes")
    try:
        data = value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Bulk edits require valid UTF-8 text") from None
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the workspace text limit")
    return data


def _identity(info: os.stat_result) -> dict:
    if info.st_ino <= 0:
        raise ValueError("This filesystem does not provide a stable workspace identity")
    return {"device": info.st_dev, "inode": info.st_ino}


def _linked(info: os.stat_result) -> bool:
    # On Windows this also refuses directory junctions and other reparse aliases.
    return (stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _root_identity(ws: Workspace) -> dict:
    info = ws.root.lstat()
    if _linked(info) or not stat.S_ISDIR(info.st_mode) or ws.root.resolve(strict=True) != ws.root:
        raise BulkEditConflict("Workspace location changed; create a new preview")
    return _identity(info)


def _assert_root(ws: Workspace, plan: dict) -> None:
    if str(ws.root) != plan["root"] or _root_identity(ws) != plan["root_identity"]:
        raise BulkEditConflict("Workspace identity changed; create a new preview")


@dataclass(frozen=True)
class _Snapshot:
    path: str
    content: str
    digest: str
    identity: tuple[int, int]


def _read_file(ws: Workspace, relative: str) -> _Snapshot:
    """Reapply Workspace policy, refuse aliases, and read exact bounded bytes."""
    relative = _relative_path(relative)
    path = ws.resolve(relative)  # Includes STAR's protected-name and sensitive-suffix rules.
    current = ws.root
    for part in Path(relative).parts:
        current = current / part
        info = current.lstat()
        if _linked(info):
            raise PermissionError("Bulk edits do not follow file or directory links")
    info = path.lstat()
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise PermissionError("Bulk edits require regular files without hardlink aliases")
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError("File exceeds the workspace text limit")
    # NONBLOCK avoids hanging if another process replaces the checked file with a
    # FIFO; NOFOLLOW refuses a last-moment final-component symlink where supported.
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
            raise BulkEditConflict("File identity changed while reading; create a new preview")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
        ended = os.fstat(fd)
        if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                ended.st_size, ended.st_mtime_ns, ended.st_ctime_ns):
            raise BulkEditConflict("File changed while reading; create a new preview")
    finally:
        os.close(fd)
    try:
        content = data.decode("utf-8")
    except UnicodeError:
        raise ValueError("Bulk edits require valid UTF-8 text") from None
    _bytes(content)
    return _Snapshot(path.relative_to(ws.root).as_posix(), content, sha256(data).hexdigest(),
                     (opened.st_dev, opened.st_ino))


def _diff(path: str, before: str, after: str) -> tuple[str, bool]:
    chunks = []
    length = 0
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                 fromfile="a/" + path, tofile="b/" + path, n=2)
    for index, line in enumerate(lines):
        if index >= MAX_DIFF_LINES or length + len(line) > MAX_DIFF_CHARS:
            remaining = MAX_DIFF_CHARS - length
            if index < MAX_DIFF_LINES and remaining:
                chunks.append(line[:remaining])
            return "".join(chunks), True
        if not line.endswith("\n"):
            line += "\n\\ No newline at end of file\n"
        if length + len(line) > MAX_DIFF_CHARS:
            return "".join(chunks), True
        chunks.append(line)
        length += len(line)
    return "".join(chunks), False


def _file_plan(path: str, before: str, after: str, replacements: int, strategy: str) -> dict:
    old, new = _bytes(before), _bytes(after)
    if old == new:
        raise ValueError("Bulk edit would not change the file")
    diff, truncated = _diff(path, before, after)
    return {"path": path, "before": before, "after": after,
            "before_sha256": sha256(old).hexdigest(), "after_sha256": sha256(new).hexdigest(),
            "before_bytes": len(old), "after_bytes": len(new), "diff": diff, "diff_truncated": truncated,
            "replacements": replacements, "match_strategy": strategy}


def _make_plan(root: str, identity: dict, files: list[dict], direction: str = "edit") -> dict:
    before = sum(item["before_bytes"] for item in files)
    after = sum(item["after_bytes"] for item in files)
    if before + after > MAX_TOTAL_BYTES:
        raise ValueError("Bulk preview exceeds the combined 1 MiB content limit")
    return {"version": 1, "direction": direction, "root": root, "root_identity": dict(identity), "files": files,
            "file_count": len(files), "total_before_bytes": before, "total_after_bytes": after,
            "total_content_bytes": before + after}


def _validated_plan(plan: object) -> dict:
    """Validate persisted JSON and take a detached snapshot before filesystem work."""
    if not isinstance(plan, dict) or set(plan) != _PLAN_KEYS:
        raise ValueError("Invalid bulk preview schema")
    if (type(plan["version"]) is not int or plan["version"] != 1
            or not isinstance(plan["direction"], str) or plan["direction"] not in {"edit", "undo"}):
        raise ValueError("Unsupported bulk preview version or direction")
    root = plan["root"]
    if (not isinstance(root, str) or not 1 <= len(root) <= 4096 or any(ord(c) < 32 for c in root)
            or not Path(root).is_absolute() or str(Path(root)) != root or ".." in Path(root).parts):
        raise ValueError("Invalid canonical workspace root")
    identity = plan["root_identity"]
    if (not isinstance(identity, dict) or set(identity) != {"device", "inode"}
            or any(type(value) is not int for value in identity.values())
            or identity["device"] < 0 or identity["inode"] <= 0):
        raise ValueError("Invalid workspace identity")
    rows = plan["files"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError("Bulk edits need 1–16 files")
    files = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict) or set(item) != _FILE_KEYS:
            raise ValueError("Invalid bulk file preview schema")
        path = _relative_path(item["path"])
        if path in seen:
            raise ValueError("Each file may occur only once in a bulk preview")
        seen.add(path)
        if (type(item["replacements"]) is not int or not 1 <= item["replacements"] <= MAX_FILE_BYTES
                or not isinstance(item["match_strategy"], str)
                or item["match_strategy"] not in {"exact", "line_endings", "whitespace"}):
            raise ValueError("Invalid edit replacement metadata")
        expected = _file_plan(path, item["before"], item["after"], item["replacements"], item["match_strategy"])
        if (any(type(item[key]) is not int for key in ("before_bytes", "after_bytes"))
                or type(item["diff_truncated"]) is not bool or item != expected):
            raise ValueError("Bulk preview content, hashes, or diff do not match")
        files.append(expected)
    expected = _make_plan(root, identity, files, plan["direction"])
    if (any(type(plan[key]) is not int for key in ("file_count", "total_before_bytes", "total_after_bytes",
                                                  "total_content_bytes")) or plan != expected):
        raise ValueError("Bulk preview totals do not match")
    return expected


def preview_edits(root: Path, edits: list[dict]) -> dict:
    """Preview one explicit find/replace per existing file; do not write anything.

    Edit keys are ``path``, ``old_string``, ``new_string`` and optional boolean
    ``replace_all``. STAR's exact/line-ending/indentation matching is reused.
    The returned JSON plan contains private reversible text, capped at 1 MiB.
    """
    if not isinstance(edits, list) or not 1 <= len(edits) <= MAX_FILES:
        raise ValueError("Bulk edits need 1–16 files")
    specifications = []
    for item in edits:
        if (not isinstance(item, dict) or not {"path", "old_string", "new_string"} <= set(item)
                or set(item) - {"path", "old_string", "new_string", "replace_all"}
                or type(item.get("replace_all", False)) is not bool):
            raise ValueError("Invalid bulk edit schema")
        path = _relative_path(item["path"])
        _bytes(item["old_string"])
        _bytes(item["new_string"])
        specifications.append({**item, "path": path})
    with _EXECUTION_LOCK:
        ws = Workspace(Path(root))
        identity = _root_identity(ws)
        files, paths, identities = [], set(), set()
        for item in specifications:
            snapshot = _read_file(ws, item["path"])
            if snapshot.path in paths or snapshot.identity in identities:
                raise ValueError("Each resolved file may occur only once in a bulk preview")
            paths.add(snapshot.path)
            identities.add(snapshot.identity)
            edited = apply_edit(snapshot.content, item["old_string"], item["new_string"],
                                replace_all=item.get("replace_all", False))
            files.append(_file_plan(snapshot.path, snapshot.content, edited.text, edited.count, edited.strategy))
            if sum(row["before_bytes"] + row["after_bytes"] for row in files) > MAX_TOTAL_BYTES:
                raise ValueError("Bulk preview exceeds the combined 1 MiB content limit")
        plan = _make_plan(str(ws.root), identity, files)
        _assert_root(ws, plan)
        return plan


def read_context(root: Path, paths: list[str], *, max_chars: int = 6000) -> dict:
    """Snapshot explicitly selected files for a read-only brain request.

    Text is exact, never silently truncated. The host can compare a fresh result
    with its persisted snapshot immediately before dispatch to detect changed
    workspace identity, file selection, or content. Empty selection is allowed.
    """
    if not isinstance(paths, list) or len(paths) > MAX_FILES:
        raise ValueError("Context accepts at most 16 explicitly selected files")
    if type(max_chars) is not int or not 1 <= max_chars <= 12000:
        raise ValueError("Context character budget must be 1–12,000")
    selected = [_relative_path(path) for path in paths]
    with _EXECUTION_LOCK:
        ws = Workspace(Path(root))
        context = {"root": str(ws.root), "root_identity": _root_identity(ws), "files": []}
        seen_paths, seen_identities = set(), set()
        total = 0
        for path in selected:
            snapshot = _read_file(ws, path)
            if snapshot.path in seen_paths or snapshot.identity in seen_identities:
                raise ValueError("Each resolved context file may occur only once")
            seen_paths.add(snapshot.path)
            seen_identities.add(snapshot.identity)
            total += len(snapshot.content)
            if total > max_chars:
                raise ValueError("Selected context exceeds its character budget; choose fewer or smaller files")
            context["files"].append({"path": snapshot.path, "text": snapshot.content, "sha256": snapshot.digest})
        _assert_root(ws, context)
        return context


def _cancelled(event) -> bool:
    if event is None:
        return False
    probe = getattr(event, "is_set", None)
    if not callable(probe):
        raise ValueError("Cancellation needs an event with is_set()")
    value = probe()
    if type(value) is not bool:
        raise ValueError("Cancellation state must be a boolean")
    return value


def _error(exc: Exception) -> dict:
    if isinstance(exc, BulkEditConflict):
        message = "A workspace or file changed; create a new preview."
    elif isinstance(exc, BulkEditVerificationError):
        message = "Written bytes could not be verified; inspect the affected file before retrying."
    elif isinstance(exc, PermissionError):
        message = "A file is no longer within the approved editable scope."
    elif isinstance(exc, OSError):
        message = "A filesystem write or verification failed."
    else:
        message = "The edit could not finish; inspect the recorded file outcomes."
    return {"type": type(exc).__name__[:80], "message": message}


def _result(plan: dict, files: list[dict], pending: list[str], *, cancelled: bool = False,
            error: dict | None = None, failed_path: str = "", uncertain: list[dict] | None = None) -> dict:
    uncertain = uncertain or []
    if error or cancelled:
        status = "partial" if files or uncertain else ("cancelled" if cancelled else "failed")
    else:
        status = "completed"
    result = {"status": status, "root": plan["root"], "files": files, "pending": pending,
              "uncertain": uncertain, "applied_count": len(files), "total_count": plan["file_count"],
              "cancel_requested": cancelled, "verified": status == "completed", "verification": "content_sha256"}
    if error:
        result.update({"error": error, "failed_path": failed_path})
    return result


def _receipt(item: dict) -> dict:
    return {"path": item["path"], "before_sha256": item["before_sha256"],
            "after_sha256": item["after_sha256"], "bytes_written": item["after_bytes"],
            "verified": True}


def apply_preview(root: Path, plan: dict, *, allow_write: bool = False, cancel_event=None) -> dict:
    """Apply a validated preview, returning observed per-file outcomes.

    Invalid/stale preflight raises before any write. Once a write is attempted,
    failures return ``failed`` or ``partial`` with verified ``files``, untouched
    ``pending`` paths and any ``uncertain`` outcomes. Stop before writing returns
    ``cancelled``; Stop between files returns ``partial`` plus cancel_requested.
    Verification covers read-back content hashes, never syntax or runtime behavior.
    """
    if allow_write is not True:
        raise PermissionError("Workspace editing is switched off")
    snapshot_plan = _validated_plan(plan)
    with _EXECUTION_LOCK:
        ws = Workspace(Path(root))
        _assert_root(ws, snapshot_plan)
        items = snapshot_plan["files"]
        paths = [item["path"] for item in items]
        if _cancelled(cancel_event):
            return _result(snapshot_plan, [], paths, cancelled=True)
        checked, identities, resolved = {}, set(), set()
        # An invalid LAST item prevents writes to every earlier item.
        for item in items:
            observed = _read_file(ws, item["path"])
            if observed.path in resolved or observed.identity in identities:
                raise ValueError("Bulk preview contains duplicate resolved files")
            resolved.add(observed.path)
            identities.add(observed.identity)
            if observed.path != item["path"] or observed.digest != item["before_sha256"]:
                raise BulkEditConflict("File changed since preview; create a new preview")
            checked[item["path"]] = observed
        _assert_root(ws, snapshot_plan)
        applied = []
        for index, item in enumerate(items):
            attempted = False
            try:
                if _cancelled(cancel_event):
                    return _result(snapshot_plan, applied, paths[index:], cancelled=True)
                _assert_root(ws, snapshot_plan)
                current = _read_file(ws, item["path"])
                if (current.digest != item["before_sha256"] or current.path != item["path"]
                        or current.identity != checked[item["path"]].identity):
                    raise BulkEditConflict("File changed before its write; create a new preview")
                attempted = True
                ws.call("workspace_write", {"path": item["path"], "content": item["after"]}, allow_write=True)
                _assert_root(ws, snapshot_plan)
                after = _read_file(ws, item["path"])
                if after.path != item["path"] or after.digest != item["after_sha256"]:
                    raise BulkEditVerificationError("Written content did not match the preview")
                applied.append(_receipt(item))
            except Exception as exc:
                if not attempted:
                    if not applied:
                        raise
                    return _result(snapshot_plan, applied, paths[index:], error=_error(exc), failed_path=item["path"])
                # Workspace may raise after os.replace (e.g. an advisory hook). Read
                # back before deciding whether the attempted file changed.
                observed_hash = None
                try:
                    _assert_root(ws, snapshot_plan)
                    observed_hash = _read_file(ws, item["path"]).digest
                except Exception:
                    pass
                uncertain = []
                pending = paths[index + 1:]
                if observed_hash == item["after_sha256"]:
                    applied.append(_receipt(item))
                elif observed_hash == item["before_sha256"]:
                    pending = paths[index:]
                else:
                    uncertain = [{"path": item["path"], "expected_after_sha256": item["after_sha256"],
                                  "observed_sha256": observed_hash}]
                return _result(snapshot_plan, applied, pending, error=_error(exc),
                               failed_path=item["path"], uncertain=uncertain)
        return _result(snapshot_plan, applied, [])


def undo_preview(plan: dict) -> dict:
    """Return a reverse plan without filesystem access or writes.

    Applying it uses the original after-hash as the new before-hash, so an owner
    edit made since the batch is refused. For a partial batch the host must first
    construct a plan containing ONLY its verified applied items; do not retry or
    reverse uncertain writes automatically.
    """
    original = _validated_plan(plan)
    files = [_file_plan(item["path"], item["after"], item["before"],
                        item["replacements"], item["match_strategy"]) for item in original["files"]]
    return _make_plan(original["root"], original["root_identity"], files,
                      "undo" if original["direction"] == "edit" else "edit")
