"""Private OBS rehearsal audit integration and adversarial tests."""
from __future__ import annotations

import json
import hashlib
import shutil
import subprocess

import pytest

from star import stream_private_rehearsal_audit_cli as audit
from star.stream_av_recording_host import MouthROI, RecordingAVResult
from star.stream_av_sync_audit import AVSyncReport
from star.stream_obs_recording_artifact_probe import RecordingArtifactReport


def _media(tmp_path):
    root = tmp_path / "private-clips"
    root.mkdir()
    clip = root / "secret owner recording.mkv"
    closed = root / "closed.png"
    opened = root / "open.png"
    for path in (clip, closed, opened):
        path.write_bytes(b"x" * 4096)
    return root, clip, closed, opened


def _options(root, clip):
    return dict(
        allowed_root=root, owner_approved=True,
        host_confirms_recording_stopped=True,
        host_confirms_broadcast_inactive=True,
    )


def _mocks(monkeypatch):
    calls = []
    def probe(*args, **kwargs):
        calls.append(("decode", args, kwargs))
        return RecordingArtifactReport(
            "candidate_for_owner_review", 6.0, 180, 128, 72, 1, 0,
        )
    def av(*args, **kwargs):
        calls.append(("mouth", args, kwargs))
        return RecordingAVResult(
            AVSyncReport(
                "eligible_for_owner_review", "bounded_av_sync_targets_met",
                180, 6000.0, 20, 0.92, 0.9, 0.95, 0.02, 10,
            ), 180, 0, 25.0, True, True,
        )
    monkeypatch.setattr(audit, "inspect_private_obs_artifact", probe)
    monkeypatch.setattr(audit, "audit_local_obs_recording", av)
    return calls


def test_decode_is_only_advisory_and_never_claims_speech_or_game(tmp_path, monkeypatch):
    root, clip, _, _ = _media(tmp_path)
    calls = _mocks(monkeypatch)
    report = audit.audit_private_rehearsal(clip, **_options(root, clip))
    assert report.status == "decodable_only"
    assert report.decoded_video_frames == 180
    assert report.av_verdict is None
    assert not any([
        report.recording_origin_verified, report.gameplay_verified,
        report.star_speech_identity_verified, report.humanlike_verified,
        report.broadcast_authorized,
    ])
    assert len(calls) == 1
    assert "owner" not in report.to_json()
    assert str(root) not in report.to_json()


@pytest.mark.parametrize("key,val", [
    ("owner_approved", False),
    ("owner_approved", 1),
    ("host_confirms_recording_stopped", False),
    ("host_confirms_broadcast_inactive", "true"),
])
def test_no_media_access_without_exact_private_consent(tmp_path, monkeypatch, key, val):
    root, clip, _, _ = _media(tmp_path)
    calls = _mocks(monkeypatch)
    settings = _options(root, clip)
    settings[key] = val
    with pytest.raises(PermissionError):
        audit.audit_private_rehearsal(clip, **settings)
    assert not calls


def test_joint_decoding_and_rendered_mouth_sync(tmp_path, monkeypatch):
    root, clip, closed, opened = _media(tmp_path)
    calls = _mocks(monkeypatch)
    report = audit.audit_private_rehearsal(
        clip, **_options(root, clip),
        closed_still=closed, open_still=opened,
        mouth_roi=MouthROI(0, 0, 20, 20),
        host_confirms_isolated_star_audio=True,
        host_attests_actual_output=True,
    )
    assert [row[0] for row in calls] == ["decode", "mouth"]
    assert report.status == "av_review_candidate"
    assert report.av_verdict == "eligible_for_owner_review"
    assert report.estimated_mouth_lag_ms == 20
    assert report.voiced_mouth_coverage == 0.95
    assert report.best_alignment_f1 == 0.92
    assert calls[1][2]["host_attests_actual_output"] is True
    assert not report.humanlike_verified
    assert not report.star_speech_identity_verified


@pytest.mark.parametrize("verdict, status", [
    ("needs_improvement", "av_needs_improvement"),
    ("insufficient_evidence", "av_inconclusive"),
])
def test_low_quality_never_becomes_success(tmp_path, monkeypatch, verdict, status):
    root, clip, closed, opened = _media(tmp_path)
    _mocks(monkeypatch)
    def low_quality(*args, **kwargs):
        return RecordingAVResult(
            AVSyncReport(verdict, "reason", 180, 6000.0),
            180, 0, 25.0, True, True,
        )
    monkeypatch.setattr(audit, "audit_local_obs_recording", low_quality)
    report = audit.audit_private_rehearsal(
        clip, **_options(root, clip), closed_still=closed, open_still=opened,
        mouth_roi=MouthROI(0, 0, 20, 20),
        host_confirms_isolated_star_audio=True, host_attests_actual_output=True,
    )
    assert report.status == status
    assert not report.broadcast_authorized


@pytest.mark.parametrize("extra, error", [
    ({"closed_still": "foo"}, audit.PrivateRehearsalAuditError),
    ({"host_attests_actual_output": True}, audit.PrivateRehearsalAuditError),
    ({"closed_still": "foo", "open_still": "bar",
      "mouth_roi": MouthROI(0, 0, 20, 20)}, PermissionError),
])
def test_mouth_inputs_and_claims_are_all_or_nothing(tmp_path, monkeypatch, extra, error):
    root, clip, _, _ = _media(tmp_path)
    calls = _mocks(monkeypatch)
    with pytest.raises(error):
        audit.audit_private_rehearsal(clip, **_options(root, clip), **extra)
    assert not calls


def test_outside_root_and_symlink_rejected_before_any_decoder(tmp_path, monkeypatch):
    root, clip, _, _ = _media(tmp_path)
    _mocks(monkeypatch)
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"x" * 4096)
    for path in [outside, root / ".." / "outside.mkv", "relative.mkv"]:
        with pytest.raises(audit.PrivateRehearsalAuditError):
            audit.audit_private_rehearsal(path, **_options(root, clip))
    link = root / "linked.mkv"
    link.symlink_to(clip)
    with pytest.raises(audit.PrivateRehearsalAuditError):
        audit.audit_private_rehearsal(link, **_options(root, clip))


def test_calibration_not_allowed_outside_root(tmp_path, monkeypatch):
    root, clip, _, opened = _media(tmp_path)
    _mocks(monkeypatch)
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x" * 4096)
    with pytest.raises(audit.PrivateRehearsalAuditError):
        audit.audit_private_rehearsal(
            clip, **_options(root, clip),
            closed_still=outside, open_still=opened,
            mouth_roi=MouthROI(0, 0, 20, 20),
            host_confirms_isolated_star_audio=True,
            host_attests_actual_output=True,
        )


def test_source_mutation_between_passes_invalidates_aggregate_result(tmp_path, monkeypatch):
    root, clip, closed, opened = _media(tmp_path)
    _mocks(monkeypatch)
    def changed(*args, **kwargs):
        clip.write_bytes(b"x" * 4100)
        return RecordingAVResult(
            AVSyncReport("eligible_for_owner_review", "ok", 180, 6000),
            180, 0, 25.0, True, True,
        )
    monkeypatch.setattr(audit, "audit_local_obs_recording", changed)
    with pytest.raises(audit.PrivateRehearsalAuditError, match="changed"):
        audit.audit_private_rehearsal(
            clip, **_options(root, clip), closed_still=closed, open_still=opened,
            mouth_roi=MouthROI(0, 0, 20, 20),
            host_confirms_isolated_star_audio=True, host_attests_actual_output=True,
        )


def test_cli_fails_closed_and_redacts_private_path(capsys, tmp_path):
    root, clip, *_ = _media(tmp_path)
    rc = audit.main([
        "--recording", str(clip), "--allowed-root", str(root),
    ])
    text = capsys.readouterr().out
    assert rc == 2
    parsed = json.loads(text)
    assert parsed["status"] == "deferred"
    assert not parsed["broadcast_authorized"]
    assert str(root) not in text and "secret" not in text


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not installed")
def test_actual_ffmpeg_private_file_cli_smoke(tmp_path, capsys):
    root = tmp_path / "recording"
    root.mkdir()
    clip = root / "synthetic.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000",
        "-t", "6", "-c:v", "mpeg4", "-c:a", "aac", str(clip),
    ], check=True, timeout=30)
    rc = audit.main([
        "--recording", str(clip), "--allowed-root", str(root),
        "--owner-approved", "--recording-stopped", "--broadcast-inactive",
    ])
    report = json.loads(capsys.readouterr().out)
    assert rc == 0, report
    assert report["status"] == "decodable_only"
    assert report["decoded_video_frames"] == 180
    assert report["audio_stream_count"] == 1
    assert not report["star_speech_identity_verified"]
    assert not report["humanlike_verified"]


def test_precommitted_media_is_verified_without_exposing_digest(tmp_path, monkeypatch):
    """A prior, separately retained SHA-256 can bind selected clip bytes."""
    root, clip, _, _ = _media(tmp_path)
    _mocks(monkeypatch)
    expected = hashlib.sha256(clip.read_bytes()).hexdigest()
    report = audit.audit_private_rehearsal(
        clip, **_options(root, clip), expected_media_sha256=expected.upper(),
    )
    assert report.media_sha256_precommit_matched is True
    serialized = report.to_json()
    assert expected not in serialized and expected.upper() not in serialized
    assert str(clip) not in serialized
    # Byte equality does NOT prove the OBS source, voice or game identity.
    assert not report.recording_origin_verified
    assert not report.gameplay_verified
    assert not report.star_speech_identity_verified
    assert not report.broadcast_authorized


def test_no_precommit_defaults_to_unverified_even_if_media_decodes(tmp_path, monkeypatch):
    root, clip, _, _ = _media(tmp_path)
    _mocks(monkeypatch)
    def never_hash(*args):
        raise AssertionError("opt-in hashing must not slow down default audit")
    monkeypatch.setattr(audit, "_content_sha256", never_hash)
    result = audit.audit_private_rehearsal(clip, **_options(root, clip))
    assert result.media_sha256_precommit_matched is False


@pytest.mark.parametrize("candidate", [
    "a" * 63, "z" * 64, "a" * 65, " a" * 32, "", 123,
    "a" * 32 + "/" + "a" * 31,
])
def test_malformed_media_precommit_rejected_before_media_access(
        tmp_path, monkeypatch, candidate):
    root, clip, _, _ = _media(tmp_path)
    calls = _mocks(monkeypatch)
    with pytest.raises(audit.PrivateRehearsalAuditError, match="invalid.*digest"):
        audit.audit_private_rehearsal(
            clip, **_options(root, clip), expected_media_sha256=candidate,
        )
    assert not calls


def test_wrong_media_precommit_fails_before_decoder_and_reveals_no_path(
        tmp_path, monkeypatch):
    root, clip, _, _ = _media(tmp_path)
    calls = _mocks(monkeypatch)
    with pytest.raises(audit.PrivateRehearsalAuditError) as error:
        audit.audit_private_rehearsal(
            clip, **_options(root, clip), expected_media_sha256="a" * 64,
        )
    assert not calls
    assert str(clip) not in str(error.value)


def test_in_place_media_tampering_detected_even_if_stats_are_reported_unchanged(
        tmp_path, monkeypatch):
    root, clip, _, _ = _media(tmp_path)
    expected = hashlib.sha256(clip.read_bytes()).hexdigest()
    def mutate_during_decode(*args, **kwargs):
        # Same-size modification would not be caught by a size-only check.
        clip.write_bytes(b"y" * 4096)
        return RecordingArtifactReport(
            "candidate_for_owner_review", 6.0, 180, 128, 72, 1, 0,
        )
    monkeypatch.setattr(audit, "inspect_private_obs_artifact", mutate_during_decode)
    # Simulate restored or otherwise unreliable filesystem metadata.
    monkeypatch.setattr(audit, "_unchanged", lambda *args: True)
    with pytest.raises(audit.PrivateRehearsalAuditError, match="precommit"):
        audit.audit_private_rehearsal(
            clip, **_options(root, clip), expected_media_sha256=expected,
        )


def test_cli_rejects_precommit_mismatch_with_sanitized_output(
        tmp_path, monkeypatch, capsys):
    root, clip, _, _ = _media(tmp_path)
    calls = _mocks(monkeypatch)
    rc = audit.main([
        "--recording", str(clip), "--allowed-root", str(root),
        "--owner-approved", "--recording-stopped", "--broadcast-inactive",
        "--expected-media-sha256", "f" * 64,
    ])
    result = capsys.readouterr().out
    assert rc == 2 and not calls
    assert json.loads(result)["status"] == "deferred"
    assert "f" * 64 not in result and str(clip) not in result
