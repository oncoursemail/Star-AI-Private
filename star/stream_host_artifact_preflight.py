"""Offline host-side preflight for actual model, runtime and voice artifacts.

This is deliberately NOT a model-worker attestation or a streaming hot-path.
A trusted owner host must load the same verified artifacts into a supervised
worker after preflight. Never hash multi-GiB weights for each inference request.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic
from typing import Mapping

from .stream_host_model_catalog import HostInferenceCatalog, HostModelRoute

_CHUNK = 1024 * 1024
_MAX_BUNDLE_FILES = 128
_MAX_TOTAL_BYTES = 64 * 1024**3
_MAX_PATH = 240
_COMPONENT = re.compile(r"[A-Za-z0-9_. -]{1,100}\Z")
_HAS_OPENAT_NOFOLLOW = (hasattr(os, "O_NOFOLLOW")
                        and hasattr(os, "O_DIRECTORY")
                        and os.open in os.supports_dir_fd
                        and os.stat in os.supports_dir_fd
                        and os.stat in os.supports_follow_symlinks)




def _is_link_or_reparse(info: os.stat_result) -> bool:
    """Reject symlinks AND Windows junctions/other reparse entries."""
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)))


def _relative(name: str) -> tuple[str, ...]:
    if (type(name) is not str or not 1 <= len(name) <= _MAX_PATH
            or name.startswith("/") or "\\" in name or ":" in name):
        raise ValueError("artifact path must be short and relative to trusted root")
    parts = tuple(name.split("/"))
    if any(part in {"", ".", ".."} or not _COMPONENT.fullmatch(part) for part in parts):
        raise ValueError("artifact path contains unsupported components")
    return parts


@dataclass(frozen=True)
class HostArtifactPaths:
    """Relative names supplied ONLY by an owner-controlled deployment manifest."""

    model_files: tuple[str, ...]
    runtime_file: str
    voice_file: str = ""

    def __post_init__(self) -> None:
        if (type(self.model_files) is not tuple
                or not 1 <= len(self.model_files) <= _MAX_BUNDLE_FILES):
            raise ValueError("model bundle must be a bounded tuple of files")
        if type(self.voice_file) is not str:
            raise ValueError("voice file must be a relative path or empty")
        all_names = (*self.model_files, self.runtime_file)
        if self.voice_file:
            all_names += (self.voice_file,)
        for name in all_names:
            _relative(name)
        if len(set(all_names)) != len(all_names):
            raise ValueError("a route cannot reuse an artifact under two roles")


@dataclass(frozen=True)
class HostArtifactPreflight:
    """A catalog whose declared content digests were checked against disk.

    A preflight snapshot does not pin a process or prevent later file changes.
    """

    catalog: HostInferenceCatalog
    checked_files: int
    checked_bytes: int
    elapsed_ms: float


class _Reader:
    def __init__(self, root: Path, max_total_bytes: int) -> None:
        # Windows junctions/reparse roots can redirect without is_symlink().
        # Protect the owner-controlled root by its ACL as well.
        try:
            root_info = root.lstat()
        except OSError:
            raise ValueError("trusted artifact root missing") from None
        if _is_link_or_reparse(root_info) or not stat.S_ISDIR(root_info.st_mode):
            raise ValueError("trusted artifact root must be a real directory")
        self.root = root.resolve(strict=True)
        self.max_total_bytes = max_total_bytes
        self.checked_bytes = 0
        self.checked_files = 0

    @contextmanager
    def _opened_artifact(self, parts: tuple[str, ...]):
        """Yield (file descriptor, path-identity callback) during verification.

        POSIX: anchor EACH component to an open parent directory descriptor.
        This prevents a directory swapped to a symlink between lstat and open
        from redirecting the hash outside the intended artifact root.
        Windows: Python lacks dir_fd/openat, so reject junctions/reparse points
        and compare metadata; the trusted root still needs exclusive ACLs.
        """
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        anchored = _HAS_OPENAT_NOFOLLOW
        if anchored:
            with ExitStack() as opened:
                parent_fd = os.open(
                    self.root, flags | os.O_DIRECTORY | os.O_NOFOLLOW)
                opened.callback(os.close, parent_fd)
                for part in parts[:-1]:
                    checked = os.stat(
                        part, dir_fd=parent_fd, follow_symlinks=False)
                    if _is_link_or_reparse(checked):
                        raise ValueError("artifact path cannot include links")
                    if not stat.S_ISDIR(checked.st_mode):
                        raise ValueError("artifact parent is not a directory")
                    child_fd = os.open(
                        part, flags | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent_fd)
                    opened.callback(os.close, child_fd)
                    actual = os.fstat(child_fd)
                    if ((actual.st_dev, actual.st_ino)
                            != (checked.st_dev, checked.st_ino)
                            or not stat.S_ISDIR(actual.st_mode)):
                        raise ValueError("artifact parent changed while opening")
                    parent_fd = child_fd
                name = parts[-1]
                checked = os.stat(
                    name, dir_fd=parent_fd, follow_symlinks=False)
                if _is_link_or_reparse(checked):
                    raise ValueError("artifact path cannot include links")
                if not stat.S_ISREG(checked.st_mode):
                    raise ValueError("artifact must be a regular file")
                fd = os.open(name, flags | os.O_NOFOLLOW, dir_fd=parent_fd)
                opened.callback(os.close, fd)
                actual = os.fstat(fd)
                if ((actual.st_dev, actual.st_ino)
                        != (checked.st_dev, checked.st_ino)
                        or not stat.S_ISREG(actual.st_mode)):
                    raise ValueError("artifact changed while opening")
                yield fd, lambda: os.stat(
                    name, dir_fd=parent_fd, follow_symlinks=False)
            return

        # Windows/other non-openat platforms: best-effort path check.
        # Never advertise this as a race-free file-identity guarantee.
        path = self.root
        for index, part in enumerate(parts):
            path = path / part
            info = path.lstat()
            if _is_link_or_reparse(info):
                raise ValueError("artifact path cannot include links")
            if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise ValueError("artifact parent is not a directory")
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("artifact must be a regular file")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.root):
            raise ValueError("artifact escapes trusted root")
        fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0))
        try:
            observed = os.fstat(fd)
            checked = path.lstat()
            if (_is_link_or_reparse(checked)
                    or (observed.st_dev, observed.st_ino)
                    != (checked.st_dev, checked.st_ino)):
                raise ValueError("artifact changed while opening")
            yield fd, path.lstat
        finally:
            os.close(fd)

    def digest(self, relative_name: str) -> tuple[int, str]:
        parts = _relative(relative_name)
        with self._opened_artifact(parts) as (fd, inspect_entry):
            before = os.fstat(fd)
            size = before.st_size
            if (not stat.S_ISREG(before.st_mode) or size <= 0
                    or size > self.max_total_bytes - self.checked_bytes):
                raise ValueError("artifact violates preflight byte budget")
            hasher = hashlib.sha256()
            counted = 0
            with os.fdopen(fd, "rb", closefd=False) as file:
                while True:
                    block = file.read(_CHUNK)
                    if not block:
                        break
                    counted += len(block)
                    if counted > size:
                        raise ValueError("artifact grew while hashing")
                    hasher.update(block)
            after = os.fstat(fd)
            disk = inspect_entry()
            if (_is_link_or_reparse(disk)
                    or counted != size or before.st_size != after.st_size
                    or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ctime_ns != after.st_ctime_ns
                    or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
                    or (before.st_dev, before.st_ino) != (disk.st_dev, disk.st_ino)
                    or after.st_size != disk.st_size
                    or after.st_mtime_ns != disk.st_mtime_ns
                    or after.st_ctime_ns != disk.st_ctime_ns):
                raise ValueError("artifact changed during verification")
            self.checked_bytes += size
            self.checked_files += 1
            return size, hasher.hexdigest()

    def model_digest(self, names: tuple[str, ...]) -> str:
        parts = [(name, *self.digest(name)) for name in names]
        if len(parts) == 1:
            return parts[0][2]
        # Content-addressed multi-shard manifest, INCLUDING names and ordering.
        manifest = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()
        return hashlib.sha256(b"STAR_MODEL_BUNDLE_V1\n" + manifest).hexdigest()


def verify_host_artifacts(
    root: str | Path,
    routes: tuple[HostModelRoute, ...],
    manifests: Mapping[str, HostArtifactPaths],
    *,
    max_total_bytes: int = _MAX_TOTAL_BYTES,
) -> HostArtifactPreflight:
    """Build a host-owned catalog only after checking ALL declared route files.

    Reads actual bytes once, at worker startup. Never accept paths or expected
    hashes from an LLM, viewer, remote request or prompt. If any check fails,
    return no catalog; the caller must not start an unverified worker.
    """
    if type(max_total_bytes) is not int or not 1 <= max_total_bytes <= _MAX_TOTAL_BYTES:
        raise ValueError("invalid preflight byte budget")
    if not isinstance(manifests, Mapping) or not isinstance(routes, tuple):
        raise TypeError("expected host-owned manifests and route tuple")
    catalog = HostInferenceCatalog(routes)
    if (len(manifests) != catalog.route_count
            or set(manifests) != {r.alias for r in routes}):
        raise ValueError("every host route must have exactly one artifact manifest")
    begin = monotonic()
    try:
        reader = _Reader(Path(root), max_total_bytes)
        for route in routes:
            spec = manifests[route.alias]
            if not isinstance(spec, HostArtifactPaths):
                raise ValueError("artifact manifest is not host-configured")
            if bool(spec.voice_file) != bool(route.voice_sha256):
                raise ValueError("voice file presence must match the registered route")
            model_digest = reader.model_digest(spec.model_files)
            _, runtime_digest = reader.digest(spec.runtime_file)
            voice_digest = reader.digest(spec.voice_file)[1] if spec.voice_file else ""
            if (model_digest != route.model_sha256
                    or runtime_digest != route.runtime_sha256
                    or voice_digest != route.voice_sha256):
                raise ValueError("model/runtime/voice artifact digest mismatch")
    except (OSError, RuntimeError):
        # Avoid accidentally leaking host paths in user-visible error messages.
        raise ValueError("host artifact preflight failed") from None
    return HostArtifactPreflight(
        catalog=catalog, checked_files=reader.checked_files,
        checked_bytes=reader.checked_bytes,
        elapsed_ms=(monotonic() - begin) * 1000,
    )


def main(argv: list[str] | None = None) -> int:
    """Manually run read-only preflight from a LOCAL owner-managed JSON manifest."""
    import argparse

    parser = argparse.ArgumentParser(description="Verify local model/runtime/voice bytes")
    parser.add_argument("--root", required=True, help="trusted local artifact root")
    parser.add_argument("--manifest", required=True, help="owner-managed JSON manifest")
    args = parser.parse_args(argv)
    try:
        manifest_path = Path(args.manifest)
        if manifest_path.stat().st_size > 256 * 1024:
            raise ValueError("manifest exceeds size limit")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (type(payload) is not dict or set(payload) != {"routes"}
                or type(payload["routes"]) is not list
                or not 1 <= len(payload["routes"]) <= 64):
            raise ValueError("invalid manifest layout")
        routes = []
        artifacts = {}
        for item in payload["routes"]:
            if type(item) is not dict or set(item) != {
                "alias", "kind", "device", "engine", "model_sha256",
                "runtime_sha256", "voice_sha256", "ram_mib", "vram_mib",
                "artifacts",
            }:
                raise ValueError("invalid route configuration")
            details = dict(item)
            file_specs = details.pop("artifacts")
            if type(file_specs) is not dict or set(file_specs) != {
                "model_files", "runtime_file", "voice_file",
            }:
                raise ValueError("invalid artifact file configuration")
            if type(file_specs["model_files"]) is not list:
                raise ValueError("model_files must be a list")
            route = HostModelRoute(**details)
            routes.append(route)
            artifacts[route.alias] = HostArtifactPaths(
                model_files=tuple(file_specs["model_files"]),
                runtime_file=file_specs["runtime_file"],
                voice_file=file_specs["voice_file"],
            )
        report = verify_host_artifacts(args.root, tuple(routes), artifacts)
    except (OSError, ValueError, TypeError, KeyError):
        # Intentionally never echo private host paths or fingerprints to stdout.
        print(json.dumps({"status": "failed", "reason": "local preflight failed"}))
        return 2
    print(json.dumps({
        "status": "passed", "verified_routes": report.catalog.route_count,
        "files": report.checked_files, "bytes": report.checked_bytes,
        "elapsed_ms": round(report.elapsed_ms, 2),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["HostArtifactPaths", "HostArtifactPreflight", "verify_host_artifacts"]
