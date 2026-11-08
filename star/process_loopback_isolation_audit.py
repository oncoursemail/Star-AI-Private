"""Offline, non-authorizing differential check for two owner-launched WASAPI traces.

The caller must separately attest that positive and negative observations came
from distinct pinned *child* processes while a controlled tone was playing.
Neither JSONL nor this parser can authenticate a Windows PID, prove physical
silence, grant broadcast permission, or measure Star's actual speech.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import stat

from star.process_loopback_activity import ActivityDiagnosticSummary, ProcessLoopbackActivityVerifier

MAX_BYTES = 65536
MIN_LINES = 7
MAX_LINES = 70


@dataclass(frozen=True)
class IsolationAdvisory:
    status: str
    positive_nonzero_windows: int
    positive_pcm_windows: int
    negative_pcm_windows: int
    negative_zero_amplitude_windows: int
    positive_peak_milli: int
    negative_peak_milli: int
    capture_source_identity_attested: bool = False
    physical_silence_verified: bool = False
    speech_or_interruption_verified: bool = False
    gameplay_authorized: bool = False
    broadcast_authorized: bool = False


def _parse(data: bytes) -> tuple[list[tuple[int | None, int | None, int]], ActivityDiagnosticSummary]:
    if len(data) > MAX_BYTES or not data.endswith(b"\n"):
        raise ValueError("invalid bounded diagnostic")
    try:
        contents = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("diagnostic must be UTF-8") from exc
    lines = contents.splitlines()
    if not MIN_LINES <= len(lines) <= MAX_LINES:
        raise ValueError("unexpected number of native diagnostic records")
    verifier = ProcessLoopbackActivityVerifier(owner_approved=True, possible_audio_peak_milli=2)
    windows: list[tuple[int | None, int | None, int]] = []
    for line in lines:
        reading = verifier.feed_line(line)
        if reading.state != "capture_started":
            windows.append((reading.activity_peak_milli, reading.activity_rms_milli, reading.activity_sample_frames))
    summary = verifier.summary()
    if summary.state != "completed" or summary.windows != len(lines) - 1:
        raise ValueError("native diagnostic did not complete")
    return windows, summary


def verify_pair(positive: bytes, negative: bytes, *, owner_approved: bool = False) -> IsolationAdvisory:
    """An advisory only; source authenticity requires a separate trusted host."""
    if owner_approved is not True:
        raise PermissionError("explicit owner approval required")
    p_windows, p = _parse(positive)
    n_windows, n = _parse(negative)
    p_nonzero = sum(
        peak is not None and rms is not None and peak >= 2 and rms >= 1 and frames > 0
        for peak, rms, frames in p_windows
    )
    if p_nonzero < 2 or p.sample_frames <= 0 or not 2 <= p.maximum_peak_milli <= 300:
        raise ValueError("controlled positive tone not independently observed")
    # Negative must show healthy zero-amplitude PCM packets, NOT just missing
    # callbacks. Absent packets are unknown and make this test inconclusive.
    if n.pcm_windows < 2 or n.sample_frames <= 0:
        raise ValueError("negative trace has insufficient PCM to establish isolation")
    n_zero = sum(peak == 0 and rms == 0 and frames > 0 for peak, rms, frames in n_windows)
    if n_zero != n.pcm_windows or n.maximum_peak_milli != 0:
        raise ValueError("nonzero audio leaked into independent silent child capture")
    return IsolationAdvisory(
        status="offline_isolation_trace_pair_compatible",
        positive_nonzero_windows=p_nonzero,
        positive_pcm_windows=p.pcm_windows,
        negative_pcm_windows=n.pcm_windows,
        negative_zero_amplitude_windows=n_zero,
        positive_peak_milli=p.maximum_peak_milli,
        negative_peak_milli=n.maximum_peak_milli,
    )


def _read_bounded(root: Path, name: str) -> bytes:
    path = root / name
    if path.is_symlink():
        raise ValueError("diagnostic link prohibited")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_BYTES:
            raise ValueError("untrusted diagnostic file")
        data = os.read(fd, MAX_BYTES + 1)
        after = os.fstat(fd)
        if len(data) != before.st_size or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError("diagnostic changed during inspection")
        return data
    finally:
        os.close(fd)


def inspect_bundle(bundle_dir: Path, *, owner_approved: bool = False) -> IsolationAdvisory:
    if owner_approved is not True:
        raise PermissionError("explicit owner approval required")
    if bundle_dir.is_symlink() or not bundle_dir.is_dir():
        raise ValueError("untrusted diagnostic root")
    if (bundle_dir.stat().st_mode & 0o022) != 0 and os.name != "nt":
        raise ValueError("untrusted writable diagnostic root")
    positive = _read_bounded(bundle_dir, "positive.jsonl")
    negative = _read_bounded(bundle_dir, "negative.jsonl")
    return verify_pair(positive, negative, owner_approved=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Private offline paired process-loopback audit; never authorize streaming"
    )
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--owner-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = inspect_bundle(args.bundle_dir, owner_approved=args.owner_approved)
    except (ValueError, PermissionError, OSError):
        print(json.dumps({"status": "invalid_or_inconclusive", "broadcast_authorized": False}))
        return 2
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
