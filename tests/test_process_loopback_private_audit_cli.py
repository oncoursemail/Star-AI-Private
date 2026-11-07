"""Offline end-to-end tests for a bounded Windows process audio diagnostic audit."""

import hashlib
import json
from pathlib import Path

import pytest

from star.process_loopback_private_audit_cli import (
    PrivateVoiceAuditError,
    audit_private_voice_activity,
    main,
)


def _row(
    state: str,
    elapsed: int,
    *,
    callbacks: int,
    window_callbacks: int,
    frames: int,
    window_frames: int,
    peak: int | None,
    rms: int | None,
    age: int,
    max_peak: int,
) -> dict:
    return {
        "schema": "star.process_loopback.diagnostic.v1",
        "state": state,
        "elapsed_ms": elapsed,
        "callback_generation": callbacks,
        "sample_frames": frames,
        "bad_packets": 0,
        "max_peak_milli": max_peak,
        "last_callback_age_ms": age,
        "activity_window_ms": 50,
        "activity_callbacks": window_callbacks,
        "activity_sample_frames": window_frames,
        "activity_peak_milli": peak,
        "activity_rms_milli": rms,
        "activity_is_audio_observation_only": True,
        "verified_silence": False,
        "gameplay_authorized": False,
        "broadcast_authorized": False,
    }


def valid_rows() -> list[dict]:
    return [
        _row(
            "capture_started",
            0,
            callbacks=0,
            window_callbacks=0,
            frames=0,
            window_frames=0,
            peak=None,
            rms=None,
            age=-1,
            max_peak=0,
        ),
        _row(
            "observing_no_silence_claim",
            50,
            callbacks=1,
            window_callbacks=1,
            frames=80,
            window_frames=80,
            peak=570,
            rms=240,
            age=4,
            max_peak=570,
        ),
        _row(
            "observing_no_silence_claim",
            100,
            callbacks=1,
            window_callbacks=0,
            frames=80,
            window_frames=0,
            peak=None,
            rms=None,
            age=54,
            max_peak=570,
        ),
        _row(
            "capture_complete_no_silence_claim",
            150,
            callbacks=1,
            window_callbacks=0,
            frames=80,
            window_frames=0,
            peak=None,
            rms=None,
            age=104,
            max_peak=570,
        ),
    ]


def make_bytes(rows: list[dict] | None = None) -> bytes:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in (valid_rows() if rows is None else rows)).encode(
        "ascii"
    )


def create_case(tmp_path: Path, data: bytes | None = None):
    root = tmp_path / "allowed"
    root.mkdir()
    path = root / "isolated.jsonl"
    payload = make_bytes() if data is None else data
    path.write_bytes(payload)
    return path, root, hashlib.sha256(payload).hexdigest()


def run(path, root, digest, **changes):
    options = dict(
        allowed_root=root,
        expected_sha256=digest,
        owner_approved=True,
        host_confirms_broadcast_inactive=True,
        host_confirms_native_capture_stopped=True,
        host_confirms_dedicated_voice_process_pinned=True,
        host_confirms_native_binary_pinned=True,
        host_confirms_independent_precommit=True,
    )
    options.update(changes)
    return audit_private_voice_activity(path, **options)


def test_complete_file_only_reports_audio_hints_never_silence(tmp_path):
    path, root, digest = create_case(tmp_path)
    report = run(path, root, digest)
    assert report.status == "complete_observation_for_private_manual_review"
    assert (report.activity_windows, report.pcm_windows, report.no_pcm_windows_unknown) == (3, 1, 2)
    assert report.possible_audio_activity_windows == 1
    assert (report.callback_count, report.sample_frames) == (1, 80)
    assert report.matched_independent_precommit
    assert not report.verified_physical_silence
    assert not report.verified_speech_identity
    assert not report.certifies_natural_conversation
    assert not report.authorizes_gameplay
    assert not report.authorizes_broadcast
    output = report.to_json()
    assert "isolated" not in output and str(tmp_path) not in output
    assert "false" in output


@pytest.mark.parametrize(
    "key",
    [
        "owner_approved",
        "host_confirms_broadcast_inactive",
        "host_confirms_native_capture_stopped",
        "host_confirms_dedicated_voice_process_pinned",
        "host_confirms_native_binary_pinned",
        "host_confirms_independent_precommit",
    ],
)
def test_must_have_every_attestation(tmp_path, key):
    path, root, digest = create_case(tmp_path)
    with pytest.raises(PermissionError):
        run(path, root, digest, **{key: False})
    with pytest.raises(PermissionError):
        run(path, root, digest, **{key: 1})


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "0" * 63,
        "F" * 64,
        "g" * 64,
        13,
        None,
        True,
    ],
)
def test_hash_format_must_be_fixed_lowercase_hex(tmp_path, bad):
    path, root, _ = create_case(tmp_path)
    with pytest.raises(PrivateVoiceAuditError):
        run(path, root, bad)


def test_wrong_precommit_rejected(tmp_path):
    path, root, digest = create_case(tmp_path)
    with pytest.raises(PrivateVoiceAuditError, match="digest_mismatch"):
        run(path, root, "0" * 64 if digest != "0" * 64 else "1" * 64)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{}\n",
        b"{}",
        make_bytes()[:-1],
        make_bytes() + b"\n",
        make_bytes() + b" " * (1_048_577),
        b"\xff\n" + make_bytes(),
    ],
    ids=(
        "empty",
        "empty-object",
        "nonterminated-object",
        "missing-final-newline",
        "extra-blank-line",
        "oversized-file",
        "non-ascii",
    ),
)
def test_invalid_or_truncated_file_rejected(tmp_path, data):
    path, root, digest = create_case(tmp_path, data)
    with pytest.raises(PrivateVoiceAuditError):
        run(path, root, digest)


def test_native_not_completed_rejected(tmp_path):
    path, root, digest = create_case(tmp_path, make_bytes(valid_rows()[:-1]))
    with pytest.raises(PrivateVoiceAuditError, match="not_complete"):
        run(path, root, digest)


def test_duplicate_reordered_or_changed_native_rows_rejected(tmp_path):
    for index, mutate in enumerate(
        (
            lambda rows: [rows[0], rows[1], rows[1], rows[3]],
            lambda rows: [rows[0], rows[2], rows[1], rows[3]],
            lambda rows: [rows[0], {**rows[1], "verified_silence": True}, rows[2], rows[3]],
            lambda rows: [rows[0], {**rows[1], "activity_sample_frames": 79}, rows[2], rows[3]],
            lambda rows: [rows[0], {**rows[1], "state": "capture_invalid"}, rows[2], rows[3]],
        )
    ):
        rows = mutate(valid_rows())
        # A fresh file per case avoids Windows metadata coalescing from rapid
        # unlink/recreate of the same path while preserving strict file guards.
        variant_root = tmp_path / f"variant_{index}"
        variant_root.mkdir()
        path, root, digest = create_case(variant_root, make_bytes(rows))
        with pytest.raises(PrivateVoiceAuditError, match="invalid_native"):
            run(path, root, digest)


def test_reject_symlink_and_parent_symlink(tmp_path):
    path, root, digest = create_case(tmp_path)
    alias = tmp_path / "alias.jsonl"
    try:
        alias.symlink_to(path)
    except OSError:
        pytest.skip("symlink creation requires privilege on this platform")
    with pytest.raises(PrivateVoiceAuditError, match="symlink"):
        run(alias, root, digest)
    parent = tmp_path / "linked_directory"
    parent.symlink_to(root, target_is_directory=True)
    with pytest.raises(PrivateVoiceAuditError, match="symlink"):
        run(parent / path.name, root, digest)


def test_external_file_and_relative_paths_rejected(tmp_path):
    path, root, digest = create_case(tmp_path)
    other = tmp_path / "outside.jsonl"
    other.write_bytes(path.read_bytes())
    with pytest.raises(PrivateVoiceAuditError, match="outside"):
        run(other, root, digest)
    with pytest.raises(PrivateVoiceAuditError, match="absolute"):
        run("outside.jsonl", root, digest)
    with pytest.raises(PrivateVoiceAuditError, match="absolute"):
        run(path, "allowed", digest)
    with pytest.raises(PrivateVoiceAuditError, match="absolute"):
        run(root / ".." / "outside.jsonl", root, digest)


def test_nonregular_directory_rejected(tmp_path):
    path, root, digest = create_case(tmp_path)
    with pytest.raises(PrivateVoiceAuditError):
        run(root, tmp_path, digest)


def test_file_changes_between_admission_and_read_rejected(tmp_path, monkeypatch):
    path, root, digest = create_case(tmp_path)
    import star.process_loopback_private_audit_cli as module

    original = module._admit

    def tamper(*args, **kwargs):
        admitted = original(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b"x")
        return admitted

    monkeypatch.setattr(module, "_admit", tamper)
    with pytest.raises(PrivateVoiceAuditError, match="file_changed"):
        run(path, root, digest)


def test_cli_returns_bounded_json_and_no_path(tmp_path, capsys):
    path, root, digest = create_case(tmp_path)
    args = [
        "--input-file",
        str(path),
        "--allowed-root",
        str(root),
        "--expected-sha256",
        digest,
        "--owner-approved",
        "--broadcast-inactive",
        "--capture-stopped",
        "--voice-process-pinned",
        "--native-binary-pinned",
        "--independent-precommit",
    ]
    assert main(args) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["matched_independent_precommit"]
    assert str(path) not in captured.out
    assert captured.err == ""
    path.write_bytes(b"tampered\n")
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "private_voice_activity_audit_failed"
    assert str(path) not in captured.err


def test_audio_packet_with_zero_peak_is_not_physical_quiet(tmp_path):
    rows = valid_rows()
    rows[1]["activity_peak_milli"] = 0
    rows[1]["activity_rms_milli"] = 0
    rows[1]["max_peak_milli"] = 0
    for row in rows[2:]:
        row["max_peak_milli"] = 0
    path, root, digest = create_case(tmp_path, make_bytes(rows))
    report = run(path, root, digest)
    assert report.pcm_windows == 1
    assert report.possible_audio_activity_windows == 0
    assert not report.verified_physical_silence


def test_bool_is_not_a_valid_precommit_or_host_assertion(tmp_path):
    path, root, digest = create_case(tmp_path)
    with pytest.raises(PermissionError):
        run(path, root, digest, host_confirms_native_capture_stopped=1)
    with pytest.raises(PrivateVoiceAuditError):
        run(path, root, True)


def test_path_handle_windows_ctime_drift_does_not_lose_same_handle_tamper_guard():
    from types import SimpleNamespace

    import star.process_loopback_private_audit_cli as module

    before = SimpleNamespace(st_dev=1, st_ino=2, st_size=500, st_mtime_ns=123, st_ctime_ns=999)
    after = SimpleNamespace(st_dev=1, st_ino=2, st_size=500, st_mtime_ns=123, st_ctime_ns=1000)
    # Path stat vs handle fstat can disagree on st_ctime_ns on Windows.
    # Identity fields still match; never reject identical bytes just because
    # those different OS APIs report different ctime semantics.
    assert module._fingerprint(before) == module._fingerprint(after)
    # A metadata edit during the same opened file's read remains detectable
    # using two descriptor-only fstat values.
    assert module._handle_fingerprint(before) != module._handle_fingerprint(after)
