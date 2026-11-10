"""Host-owned materialization of completed STAR agent artifacts.

Only the trusted host receives the coordinator. Workers write to the virtual
SQLite workspace; this module exports only artifacts from a fully successful
run into a dedicated staging root outside every Git working tree.

This is a single-host, single-writer staging boundary. It is not a Git commit,
source-tree deployment, multi-host CAS service, or permission grant to workers.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
import threading

from .agent_run_coordinator import AgentRunCoordinator, ArtifactRecord

_MARKER = ".star-artifact-staging"
_MARKER_CONTENT = b"star-artifact-staging-v1\n"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
})


class MaterializationError(RuntimeError):
    """The host could not safely stage a verified artifact."""


class MaterializationConflict(MaterializationError):
    """The staging target changed or does not match the requested CAS digest."""


@dataclass(frozen=True)
class MaterializationReceipt:
    run_id: str
    resource: str
    sha256: str
    artifact_version: int
    path: Path
    status: str


def _resource_path(value: str) -> str:
    if (type(value) is not str or not value or len(value) > 500
            or value.startswith("/") or value.endswith("/")
            or "\\" in value or "//" in value or ":" in value):
        raise ValueError("Resource must be a bounded relative POSIX path")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Resource path traversal is not allowed")
    if any(any(ord(char) < 32 or ord(char) == 127 for char in part) for part in parts):
        raise ValueError("Resource path contains control characters")
    for part in parts:
        stem = part.split(".", 1)[0].upper()
        if part.endswith((".", " ")) or stem in _WINDOWS_RESERVED:
            raise ValueError("Resource contains a Windows-reserved path component")
        if len(part) > 180:
            raise ValueError("Resource path component is too long")
    return value


def _is_link_or_junction(path: Path) -> bool:
    junction_check = getattr(path, "is_junction", None)
    return path.is_symlink() or (callable(junction_check) and junction_check())


def _check_no_symlink_components(path: Path) -> None:
    for component in reversed((path, *path.parents)):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode) or _is_link_or_junction(component):
            raise MaterializationError("Symlink or junction path components are not allowed")


def _inside_git_worktree(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ArtifactStagingMaterializer:
    """Materialize completed-run artifacts beneath a private staging root.

    Initialize a dedicated directory outside all Git repositories. On POSIX the
    directory is forced to mode 0700 and marker files to 0600. On Windows, the
    host must provision a private ACL; portable Python does not reliably inspect
    the directory DACL.

    The root must not be shared with model-generated code or untrusted workers.
    Concurrent writes through one instance are serialized. Use one trusted
    materializer process per root; do not let independent processes bypass it.
    """

    def __init__(self, root: Path) -> None:
        if type(root) is not Path or not root.is_absolute():
            raise ValueError("Staging root must be an absolute pathlib.Path")
        _check_no_symlink_components(root)
        if not root.is_dir() or _is_link_or_junction(root):
            raise MaterializationError("Staging root must be an existing real directory")
        if _inside_git_worktree(root):
            raise MaterializationError("Staging root must be outside every Git worktree")
        self.root = root.resolve(strict=True)
        marker = self.root / _MARKER
        try:
            mode = marker.lstat().st_mode
        except FileNotFoundError as exc:
            raise MaterializationError("Staging root has not been initialized") from exc
        if not stat.S_ISREG(mode) or _is_link_or_junction(marker):
            raise MaterializationError("Staging marker must be a regular file")
        if marker.read_bytes() != _MARKER_CONTENT:
            raise MaterializationError("Staging marker is invalid")
        if os.name == "posix" and stat.S_IMODE(self.root.stat().st_mode) & 0o077:
            raise MaterializationError("Staging root must be private (mode 0700)")
        self._lock = threading.RLock()

    @classmethod
    def initialize(cls, root: Path) -> "ArtifactStagingMaterializer":
        if type(root) is not Path or not root.is_absolute():
            raise ValueError("Staging root must be an absolute pathlib.Path")
        _check_no_symlink_components(root)
        if _inside_git_worktree(root):
            raise MaterializationError("Staging root must be outside every Git worktree")
        if root.exists():
            if not root.is_dir() or _is_link_or_junction(root):
                raise MaterializationError("Staging root must be a real directory")
        else:
            root.mkdir(parents=True, mode=0o700)
        _check_no_symlink_components(root)
        if os.name == "posix":
            root.chmod(0o700)
        marker = root / _MARKER
        if marker.exists() or marker.is_symlink():
            if _is_link_or_junction(marker) or not marker.is_file():
                raise MaterializationError("Staging marker must be a regular file")
            if marker.read_bytes() != _MARKER_CONTENT:
                raise MaterializationError("Existing staging marker is invalid")
        else:
            if any(root.iterdir()):
                raise MaterializationError("Refusing to adopt a non-empty unmarked directory")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(marker, flags, 0o600)
            try:
                os.write(descriptor, _MARKER_CONTENT)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if os.name == "posix":
            marker.chmod(0o600)
        return cls(root)

    @staticmethod
    def _read_target_digest(path: Path) -> str | None:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(mode) or _is_link_or_junction(path):
            raise MaterializationError("Existing target must be a regular non-symlink file")
        if path.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise MaterializationError("Existing target exceeds the artifact size limit")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(_MAX_ARTIFACT_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise MaterializationError("Existing target exceeds the artifact size limit")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _reject_casefold_collision(parent: Path, name: str) -> None:
        wanted = name.casefold()
        for child in parent.iterdir():
            if child.name.casefold() == wanted and child.name != name:
                raise MaterializationConflict("Path collides with an existing case-insensitive name")

    def _ensure_parent(self, run_id: str, resource: str) -> Path:
        current = self.root
        parts = [run_id, *resource.split("/")[:-1]]
        for part in parts:
            self._reject_casefold_collision(current, part)
            current = current / part
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError as exc:
                raise MaterializationError("Staging directory disappeared during creation") from exc
            if not stat.S_ISDIR(mode) or _is_link_or_junction(current):
                raise MaterializationError("Staging path contains a non-directory or symlink")
        _check_no_symlink_components(current)
        return current

    def materialize(
        self,
        coordinator: AgentRunCoordinator,
        run_id: str,
        resource: str,
        *,
        expected_current_sha256: str | None = None,
    ) -> MaterializationReceipt | None:
        """Export one verified artifact to root/run_id/resource using SHA-256 CAS.

        A missing destination is created only when expected_current_sha256 is
        None. An existing different file is replaced only when its current digest
        exactly matches expected_current_sha256. Repeating an identical export is
        idempotent. No arbitrary destination path is accepted.
        """
        if not isinstance(coordinator, AgentRunCoordinator):
            raise TypeError("A trusted AgentRunCoordinator is required")
        if type(run_id) is not str or not _RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run identifier")
        resource = _resource_path(resource)
        if expected_current_sha256 is not None and (
            type(expected_current_sha256) is not str
            or not _SHA256.fullmatch(expected_current_sha256)
        ):
            raise ValueError("expected_current_sha256 must be a lowercase SHA-256 digest")
        record = coordinator.read_completed_artifact(run_id, resource)
        if record is None:
            return None
        if not isinstance(record, ArtifactRecord) or record.resource != resource:
            raise MaterializationError("Coordinator returned an invalid artifact record")
        if type(record.content) is not bytes or len(record.content) > _MAX_ARTIFACT_BYTES:
            raise MaterializationError("Artifact payload is invalid or exceeds the size limit")
        digest = hashlib.sha256(record.content).hexdigest()
        if digest != record.sha256:
            raise MaterializationError("Artifact digest does not match its content")

        with self._lock:
            parent = self._ensure_parent(run_id, resource)
            target_name = resource.split("/")[-1]
            self._reject_casefold_collision(parent, target_name)
            target = parent / target_name
            if os.name == "nt" and len(str(target)) > 240:
                raise MaterializationError("Staging path exceeds the conservative Windows path limit")
            _check_no_symlink_components(target)
            current = self._read_target_digest(target)
            if current == digest:
                return MaterializationReceipt(
                    run_id, resource, digest, record.version, target, "already_present"
                )
            if current is None:
                if expected_current_sha256 is not None:
                    raise MaterializationConflict("Destination disappeared before compare-and-swap")
            elif expected_current_sha256 is None or current != expected_current_sha256:
                raise MaterializationConflict("Destination changed; expected digest is required")

            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".star-stage-", dir=parent
            )
            temporary = Path(temporary_name)
            try:
                if os.name == "posix":
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(record.content)
                    stream.flush()
                    os.fsync(stream.fileno())
                _check_no_symlink_components(target)
                if self._read_target_digest(target) != current:
                    raise MaterializationConflict(
                        "Destination changed during staging; no replacement performed"
                    )
                os.replace(temporary, target)
                _fsync_directory(parent)
            except OSError as exc:
                raise MaterializationError("Atomic staging write failed") from exc
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            return MaterializationReceipt(
                run_id, resource, digest, record.version, target, "materialized"
            )
