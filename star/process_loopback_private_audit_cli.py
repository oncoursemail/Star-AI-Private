"""Read-only, bounded, offline audit of Star's native Windows voice JSONL.

This opt-in CLI/utility *parses* diagnostic evidence after native capture ends.
It never launches a process, records sound, selects a process, contacts a
service, touches OBS, controls games, or authorizes streaming. A digest match
establishes only byte equality with an externally supplied commitment; CLI
declarations cannot authenticate the source, real playback, or physical quiet.
Do not send a stream, microphone recording or any raw PCM to this auditor.
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

from .process_loopback_activity import ProcessLoopbackActivityVerifier

_MAX_FILE = 1_048_576
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PrivateVoiceAuditError(ValueError):
    """Fixed, non-sensitive failure classification."""


@dataclass(frozen=True)
class PrivateVoiceAudit:
    status: str
    report_source: str
    matched_independent_precommit: bool
    activity_windows: int
    pcm_windows: int
    no_pcm_windows_unknown: int
    possible_audio_activity_windows: int
    sample_frames: int
    callback_count: int
    verified_physical_silence: bool = False
    verified_speech_identity: bool = False
    certifies_natural_conversation: bool = False
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _fingerprint(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _admit(path: str | Path, *, root: str | Path) -> tuple[Path, tuple[int, ...]]:
    for value in (path, root):
        if not isinstance(value, (str, Path)) or not 1 <= len(str(value)) <= 4096:
            raise PrivateVoiceAuditError("invalid_local_path")
    selected, allowed = Path(path), Path(root)
    if not selected.is_absolute() or not allowed.is_absolute() or ".." in selected.parts or ".." in allowed.parts:
        raise PrivateVoiceAuditError("absolute_local_path_required")
    # Reject symlinked ancestors, not just the final filename. Do not silently
    # admit an external file via an alias inside the approved folder.
    for item in (selected, *selected.parents, allowed):
        if item.is_symlink():
            raise PrivateVoiceAuditError("symlink_not_allowed")
    try:
        allowed_real = allowed.resolve(strict=True)
        selected_real = selected.resolve(strict=True)
        if not allowed_real.is_dir() or not selected_real.is_relative_to(allowed_real):
            raise PrivateVoiceAuditError("outside_approved_root")
        metadata = selected.lstat()
    except PrivateVoiceAuditError:
        raise
    except (OSError, RuntimeError) as exc:
        raise PrivateVoiceAuditError("unavailable_local_file") from exc
    if not stat.S_ISREG(metadata.st_mode) or not 1 <= metadata.st_size <= _MAX_FILE:
        raise PrivateVoiceAuditError("unbounded_or_nonregular_file")
    return selected, _fingerprint(metadata)


def audit_private_voice_activity(
    input_file: str | Path,
    *,
    allowed_root: str | Path,
    expected_sha256: str,
    owner_approved: bool = False,
    host_confirms_broadcast_inactive: bool = False,
    host_confirms_native_capture_stopped: bool = False,
    host_confirms_dedicated_voice_process_pinned: bool = False,
    host_confirms_native_binary_pinned: bool = False,
    host_confirms_independent_precommit: bool = False,
) -> PrivateVoiceAudit:
    """Review a STOPPED, LOCAL, host-pinned native JSONL diagnostic.

    The attestation booleans are operator assertions, not identity proof.
    The expected digest must be obtained independently *before* review.
    A forged file + forged digest can fool this offline process, and a valid
    diagnostic cannot establish which speaker produced physical sound.
    """
    flags = (
        owner_approved,
        host_confirms_broadcast_inactive,
        host_confirms_native_capture_stopped,
        host_confirms_dedicated_voice_process_pinned,
        host_confirms_native_binary_pinned,
        host_confirms_independent_precommit,
    )
    if any(flag is not True for flag in flags):
        raise PermissionError("explicit_private_stopped_capture_attestations_required")
    if type(expected_sha256) is not str or _SHA256.fullmatch(expected_sha256) is None:
        raise PrivateVoiceAuditError("independent_sha256_required")

    selected, before = _admit(input_file, root=allowed_root)
    # O_NOFOLLOW where supported, and *also* fstat under the opened descriptor
    # on Windows where that flag may not exist. No unbounded read.
    flags_open = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        handle = os.open(selected, flags_open)
        try:
            descriptor_stat = os.fstat(handle)
            if not stat.S_ISREG(descriptor_stat.st_mode) or _fingerprint(descriptor_stat) != before:
                raise PrivateVoiceAuditError("file_changed_during_open")
            with os.fdopen(handle, "rb", closefd=False) as stream:
                payload = stream.read(_MAX_FILE + 1)
            if _fingerprint(os.fstat(handle)) != before or _fingerprint(selected.lstat()) != before:
                raise PrivateVoiceAuditError("file_changed_during_read")
        finally:
            os.close(handle)
    except PrivateVoiceAuditError:
        raise
    except (OSError, RuntimeError) as exc:
        raise PrivateVoiceAuditError("cannot_read_local_diagnostic") from exc

    if not 1 <= len(payload) <= _MAX_FILE or not payload.endswith(b"\n"):
        raise PrivateVoiceAuditError("truncated_or_unbounded_diagnostic")
    if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_sha256):
        raise PrivateVoiceAuditError("independent_digest_mismatch")
    try:
        rows = payload.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise PrivateVoiceAuditError("non_ascii_diagnostic") from exc
    if not 2 <= len(rows) <= 512 or any(not row or len(row) > 4096 for row in rows):
        raise PrivateVoiceAuditError("invalid_line_count_or_size")
    verifier = ProcessLoopbackActivityVerifier(owner_approved=True)
    try:
        for line in rows:
            verifier.feed_line(line)
    except (ValueError, TypeError) as exc:
        raise PrivateVoiceAuditError("invalid_native_diagnostic") from exc
    summary = verifier.summary()
    if summary.state != "completed":
        raise PrivateVoiceAuditError("native_diagnostic_not_complete")

    return PrivateVoiceAudit(
        status="complete_observation_for_private_manual_review",
        report_source="pinned_process_loopback_jsonl_declaration_only",
        matched_independent_precommit=True,
        activity_windows=summary.windows,
        pcm_windows=summary.pcm_windows,
        no_pcm_windows_unknown=summary.missing_pcm_windows,
        possible_audio_activity_windows=summary.audio_activity_hint_windows,
        sample_frames=summary.sample_frames,
        callback_count=summary.callbacks,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private, stopped Star voice diagnostic audit; never verifies silence")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--allowed-root", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--broadcast-inactive", action="store_true")
    parser.add_argument("--capture-stopped", action="store_true")
    parser.add_argument("--voice-process-pinned", action="store_true")
    parser.add_argument("--native-binary-pinned", action="store_true")
    parser.add_argument("--independent-precommit", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = audit_private_voice_activity(
            args.input_file,
            allowed_root=args.allowed_root,
            expected_sha256=args.expected_sha256,
            owner_approved=args.owner_approved,
            host_confirms_broadcast_inactive=args.broadcast_inactive,
            host_confirms_native_capture_stopped=args.capture_stopped,
            host_confirms_dedicated_voice_process_pinned=args.voice_process_pinned,
            host_confirms_native_binary_pinned=args.native_binary_pinned,
            host_confirms_independent_precommit=args.independent_precommit,
        )
    except (ValueError, PermissionError, OSError):
        # Never echo paths, process IDs, event text, source audio or filenames.
        print("private_voice_activity_audit_failed", file=sys.stderr)
        return 2
    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["PrivateVoiceAudit", "PrivateVoiceAuditError", "audit_private_voice_activity", "main"]
