"""Fail-closed, offline integrity gate for Star's portable Windows voice diagnostic.

The caller must obtain SHA-256 digests of BOTH the manifest and executable,
and the Git commit/tree, from an independent trusted build channel *before*
examining a downloaded/extracted artifact. A GitHub artifact's own manifest
does not authenticate itself. This verifies byte integrity only, NOT publisher
identity, a Windows digital signature, genuine audio capture or safe execution.

No executable is launched, no process/audio/OBS/game is accessed, and no
filesystem paths, PIDs, or private samples are included in reports.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_FILES = frozenset({"manifest.json", "Star.ProcessLoopback.exe", "README.md"})
_MANIFEST_FIELDS = frozenset(
    {
        "schema",
        "checkout_commit",
        "checkout_tree",
        "executable_sha256",
        "readme_sha256",
        "platform",
        "requires_installed_dotnet",
        "self_test_passed",
        "live_audio_capture_tested",
        "quiet_evidence_verified",
        "permitted_to_stream",
    }
)


class PortableVoiceArtifactError(ValueError):
    """Sanitized failure category, never the untrusted path or field value."""


@dataclass(frozen=True)
class PortableVoiceArtifactReport:
    status: str = "portable_artifact_bytes_match_independent_commitments"
    schema: str = "star.process_loopback.windows_diagnostic_artifact.v2"
    manifest_digest_matches: bool = True
    executable_digest_matches: bool = True
    readme_digest_matches: bool = True
    source_commit_matches: bool = True
    source_tree_matches: bool = True
    verified_audio_capture: bool = False
    verified_physical_silence: bool = False
    verified_gameplay_skill: bool = False
    authorized_to_run_executable: bool = False
    authorized_to_record: bool = False
    authorized_to_broadcast: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _sha(value: object, *, git: bool = False) -> str:
    pattern = _GIT_SHA if git else _SHA256
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise PortableVoiceArtifactError("independent_digest_or_commit_required")
    return value


def _reject_links(path: Path) -> None:
    for part in (path, *path.parents):
        try:
            junction = getattr(part, "is_junction", None)
            if part.is_symlink() or (callable(junction) and junction()):
                raise PortableVoiceArtifactError("linked_path_forbidden")
        except (OSError, RuntimeError) as exc:
            raise PortableVoiceArtifactError("unverifiable_local_path") from exc


def _file_fingerprint(info: os.stat_result) -> tuple[int, ...]:
    # Windows path lstat and descriptor fstat may report different ctimes;
    # compare cross-API dev/ino/size/mtime, handle ctime only to itself.
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_regular_digest(path: Path, *, maximum: int, collect: bool = False) -> tuple[str, bytes]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= maximum or info.st_nlink != 1:
            raise PortableVoiceArtifactError("missing_or_unbounded_regular_file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(fd)
            if _file_fingerprint(info) != _file_fingerprint(before):
                raise PortableVoiceArtifactError("file_changed_before_read")
            fingerprint = _file_fingerprint(before) + (before.st_ctime_ns,)
            hasher = hashlib.sha256()
            content = bytearray()
            seen = 0
            while True:
                chunk = os.read(fd, min(1_048_576, maximum + 1 - seen))
                if not chunk:
                    break
                seen += len(chunk)
                if seen > maximum:
                    raise PortableVoiceArtifactError("unbounded_artifact_file")
                hasher.update(chunk)
                if collect:
                    content.extend(chunk)
            after = os.fstat(fd)
            if (
                seen != info.st_size
                or fingerprint != _file_fingerprint(after) + (after.st_ctime_ns,)
                or _file_fingerprint(path.lstat()) != _file_fingerprint(info)
            ):
                raise PortableVoiceArtifactError("file_changed_during_read")
            return hasher.hexdigest(), bytes(content)
        finally:
            os.close(fd)
    except PortableVoiceArtifactError:
        raise
    except (OSError, RuntimeError) as exc:
        raise PortableVoiceArtifactError("unavailable_artifact_file") from exc


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_manifest_field")
        result[key] = value
    return result


def audit_portable_voice_artifact(
    artifact_dir: str | Path,
    *,
    approved_root: str | Path,
    expected_manifest_sha256: str,
    expected_executable_sha256: str,
    expected_checkout_commit: str,
    expected_checkout_tree: str,
    owner_approved: bool = False,
) -> PortableVoiceArtifactReport:
    """Verify a stopped, extracted Windows diagnostic WITHOUT executing it.

    Expected digests must be independently pinned before opening the artifact;
    a claim from its own manifest is insufficient. Do not use model/chat text
    as a trust anchor. This never certifies executable behavior or provenance.
    """
    if owner_approved is not True:
        raise PermissionError("local_owner_review_required")
    expected_manifest_sha256 = _sha(expected_manifest_sha256)
    expected_executable_sha256 = _sha(expected_executable_sha256)
    expected_checkout_commit = _sha(expected_checkout_commit, git=True)
    expected_checkout_tree = _sha(expected_checkout_tree, git=True)
    for value in (artifact_dir, approved_root):
        if not isinstance(value, (str, Path)) or not 1 <= len(str(value)) <= 4096:
            raise PortableVoiceArtifactError("invalid_local_directory")
    target, root = Path(artifact_dir), Path(approved_root)
    if not target.is_absolute() or not root.is_absolute() or ".." in target.parts or ".." in root.parts:
        raise PortableVoiceArtifactError("absolute_local_directory_required")
    _reject_links(target)
    _reject_links(root)
    try:
        resolved = target.resolve(strict=True)
        allowed = root.resolve(strict=True)
        if not resolved.is_dir() or not allowed.is_dir() or not resolved.is_relative_to(allowed):
            raise PortableVoiceArtifactError("directory_outside_approved_root")
        if {entry.name for entry in target.iterdir()} != _FILES:
            raise PortableVoiceArtifactError("unexpected_artifact_entries")
    except PortableVoiceArtifactError:
        raise
    except (OSError, RuntimeError) as exc:
        raise PortableVoiceArtifactError("unavailable_artifact_directory") from exc

    for name in _FILES:
        _reject_links(target / name)
    manifest_hash, manifest_bytes = _read_regular_digest(
        target / "manifest.json",
        maximum=4096,
        collect=True,
    )
    if not hmac.compare_digest(manifest_hash, expected_manifest_sha256):
        raise PortableVoiceArtifactError("independent_manifest_digest_mismatch")
    try:
        manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise PortableVoiceArtifactError("invalid_artifact_manifest") from exc
    if (
        type(manifest) is not dict
        or manifest.keys() != _MANIFEST_FIELDS
        or manifest["schema"] != "star.process_loopback.windows_diagnostic_artifact.v2"
        or type(manifest["schema"]) is not str
        or manifest["platform"] != "windows-x64"
        or type(manifest["platform"]) is not str
        or manifest["requires_installed_dotnet"] is not False
        or manifest["self_test_passed"] is not True
        or manifest["live_audio_capture_tested"] is not False
        or manifest["quiet_evidence_verified"] is not False
        or manifest["permitted_to_stream"] is not False
    ):
        raise PortableVoiceArtifactError("manifest_contains_invalid_claims")
    try:
        if (
            not hmac.compare_digest(_sha(manifest["checkout_commit"], git=True), expected_checkout_commit)
            or not hmac.compare_digest(_sha(manifest["checkout_tree"], git=True), expected_checkout_tree)
            or not hmac.compare_digest(_sha(manifest["executable_sha256"]), expected_executable_sha256)
        ):
            raise PortableVoiceArtifactError("independent_source_or_executable_mismatch")
        readme_digest = _sha(manifest["readme_sha256"])
    except PortableVoiceArtifactError:
        raise
    exe_hash, _ = _read_regular_digest(
        target / "Star.ProcessLoopback.exe",
        maximum=209_715_200,
    )
    if not hmac.compare_digest(exe_hash, expected_executable_sha256):
        raise PortableVoiceArtifactError("executable_byte_digest_mismatch")
    readme_hash, _ = _read_regular_digest(target / "README.md", maximum=262_144)
    if not hmac.compare_digest(readme_hash, readme_digest):
        raise PortableVoiceArtifactError("readme_byte_digest_mismatch")
    return PortableVoiceArtifactReport()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline Windows audio diagnostic artifact integrity; NEVER executes/records"
    )
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--approved-root", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-executable-sha256", required=True)
    parser.add_argument("--expected-checkout-commit", required=True)
    parser.add_argument("--expected-checkout-tree", required=True)
    parser.add_argument("--owner-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = audit_portable_voice_artifact(
            args.artifact_dir,
            approved_root=args.approved_root,
            expected_manifest_sha256=args.expected_manifest_sha256,
            expected_executable_sha256=args.expected_executable_sha256,
            expected_checkout_commit=args.expected_checkout_commit,
            expected_checkout_tree=args.expected_checkout_tree,
            owner_approved=args.owner_approved,
        )
    except (PermissionError, ValueError, OSError):
        print("portable_voice_artifact_preflight_failed", file=sys.stderr)
        return 2
    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PortableVoiceArtifactError", "PortableVoiceArtifactReport", "audit_portable_voice_artifact", "main"]
