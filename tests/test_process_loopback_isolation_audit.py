"""Synthetic only: no audio devices, process launching, OBS or secrets."""

import json
import os
from pathlib import Path

import pytest

from star.process_loopback_isolation_audit import inspect_bundle, main, verify_pair


def fixture(
    *, amplitude: int, callbacks: int = 5, loud_windows: int = 5, complete: bool = True, authority: bool = False
) -> bytes:
    def make(
        state: str,
        elapsed: int,
        ncb: int,
        nfr: int,
        win_cb: int,
        win_fr: int,
        peak: int | None,
        rms: int | None,
        max_peak: int,
    ):
        return {
            "schema": "star.process_loopback.diagnostic.v1",
            "state": state,
            "elapsed_ms": elapsed,
            "callback_generation": ncb,
            "sample_frames": nfr,
            "bad_packets": 0,
            "max_peak_milli": max_peak,
            "last_callback_age_ms": 1 if ncb else -1,
            "activity_window_ms": 250,
            "activity_callbacks": win_cb,
            "activity_sample_frames": win_fr,
            "activity_peak_milli": peak,
            "activity_rms_milli": rms,
            "activity_is_audio_observation_only": True,
            "verified_silence": False,
            "gameplay_authorized": False,
            "broadcast_authorized": authority,
        }

    rows = [make("capture_started", 0, 0, 0, 0, 0, None, None, 0)]
    cb, frames, maximum = 0, 0, 0
    for tick in range(1, 7):
        have_pcm = tick <= callbacks
        p = amplitude if have_pcm and tick <= loud_windows else 0
        p = p if have_pcm else None
        rms = (p // 2) if p is not None else None
        cb += int(have_pcm)
        frames += 4800 if have_pcm else 0
        maximum = max(maximum, p or 0)
        rows.append(
            make(
                "observing_no_silence_claim",
                tick * 250,
                cb,
                frames,
                int(have_pcm),
                4800 if have_pcm else 0,
                p,
                rms,
                maximum,
            )
        )
    rows.append(
        make(
            "capture_complete_no_silence_claim" if complete else "capture_invalid",
            1750,
            cb,
            frames,
            0,
            0,
            None,
            None,
            maximum,
        )
    )
    return ("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n").encode()


POSITIVE = fixture(amplitude=30)
NEGATIVE = fixture(amplitude=0)


def test_good_differential_is_advisory_only():
    result = verify_pair(POSITIVE, NEGATIVE, owner_approved=True)
    assert result.status == "offline_isolation_trace_pair_compatible"
    assert result.positive_nonzero_windows == 5
    assert result.negative_zero_amplitude_windows == 5
    assert result.positive_peak_milli == 30
    assert result.negative_peak_milli == 0
    assert not result.capture_source_identity_attested
    assert not result.physical_silence_verified
    assert not result.speech_or_interruption_verified
    assert not result.gameplay_authorized
    assert not result.broadcast_authorized


@pytest.mark.parametrize(
    "badpositive",
    [
        fixture(amplitude=0),
        fixture(amplitude=30, callbacks=0),
        fixture(amplitude=30, loud_windows=1),
        fixture(amplitude=400),
        fixture(amplitude=30, complete=False),
        POSITIVE.rstrip(b"\n"),
        b"",
        b"x" * 65537,
    ],
)
def test_no_false_positive(badpositive):
    with pytest.raises(ValueError):
        verify_pair(badpositive, NEGATIVE, owner_approved=True)


@pytest.mark.parametrize(
    "badnegative",
    [
        fixture(amplitude=30),
        fixture(amplitude=1),
        fixture(amplitude=0, callbacks=0),
        fixture(amplitude=0, callbacks=1),
        fixture(amplitude=0, complete=False),
        fixture(amplitude=0, authority=True),
        NEGATIVE.rstrip(b"\n"),
    ],
)
def test_no_false_isolation(badnegative):
    with pytest.raises(ValueError):
        verify_pair(POSITIVE, badnegative, owner_approved=True)


def test_default_deny_and_strict_consent():
    for consent in (False, 1, "True", None):
        with pytest.raises(PermissionError):
            verify_pair(POSITIVE, NEGATIVE, owner_approved=consent)


def test_reject_duplicated_json_key():
    changed = POSITIVE.replace(b'"state":', b'"state":"capture_started","state":', 1)
    with pytest.raises(ValueError):
        verify_pair(changed, NEGATIVE, owner_approved=True)


def test_reject_cumulative_counter_tampering():
    arr = POSITIVE.decode().splitlines()
    obj = json.loads(arr[2])
    obj["callback_generation"] += 1
    arr[2] = json.dumps(obj)
    with pytest.raises(ValueError):
        verify_pair(("\n".join(arr) + "\n").encode(), NEGATIVE, owner_approved=True)


def test_reject_nonboolean_authority_claims():
    arr = NEGATIVE.decode().splitlines()
    obj = json.loads(arr[3])
    obj["verified_silence"] = True
    arr[3] = json.dumps(obj)
    with pytest.raises(ValueError):
        verify_pair(POSITIVE, ("\n".join(arr) + "\n").encode(), owner_approved=True)


def test_bundle_reads_two_files_and_redacts(tmp_path: Path, capsys):
    tmp_path.chmod(0o700)
    (tmp_path / "positive.jsonl").write_bytes(POSITIVE)
    (tmp_path / "negative.jsonl").write_bytes(NEGATIVE)
    assert inspect_bundle(tmp_path, owner_approved=True).positive_nonzero_windows == 5
    assert main(["--bundle-dir", str(tmp_path), "--owner-approved"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["positive_peak_milli"] == 30
    assert "positive.jsonl" not in str(report)
    assert "pid" not in str(report).lower()
    assert report["broadcast_authorized"] is False


def test_bundle_denies_without_consent(tmp_path: Path, capsys):
    assert main(["--bundle-dir", str(tmp_path)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "invalid_or_inconclusive"


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink needs developer privileges")
def test_bundle_denies_symlink(tmp_path: Path):
    tmp_path.chmod(0o700)
    (tmp_path / "negative.jsonl").write_bytes(NEGATIVE)
    real = tmp_path / "real.jsonl"
    real.write_bytes(POSITIVE)
    (tmp_path / "positive.jsonl").symlink_to(real)
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path, owner_approved=True)


def test_bundle_denies_hardlink(tmp_path: Path):
    import os

    tmp_path.chmod(0o700)
    (tmp_path / "negative.jsonl").write_bytes(NEGATIVE)
    real = tmp_path / "real.jsonl"
    real.write_bytes(POSITIVE)
    os.link(real, tmp_path / "positive.jsonl")
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path, owner_approved=True)


@pytest.mark.skipif(os.name == "nt", reason="Windows ACLs differ from POSIX modes")
def test_bundle_denies_world_writable_root(tmp_path: Path):
    tmp_path.chmod(0o777)
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path, owner_approved=True)


def test_bundle_denies_identical_positive_and_negative(tmp_path: Path):
    tmp_path.chmod(0o700)
    (tmp_path / "positive.jsonl").write_bytes(POSITIVE)
    (tmp_path / "negative.jsonl").write_bytes(POSITIVE)
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path, owner_approved=True)
