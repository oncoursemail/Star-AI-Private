"""Privacy-safe artifact validation; fake decoder + optional real FFmpeg smoke."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from star import stream_obs_recording_artifact_probe as probe

_GOOD_INFO = {
    "format": {"duration": "6.0"},
    "streams": [
        {"index": 0, "codec_type": "video", "width": 128, "height": 72, "nb_read_frames": "180"},
        {"index": 1, "codec_type": "audio", "sample_rate": "8000"},
    ],
}


def _selected(tmp_path):
    root = tmp_path / "recordings"
    root.mkdir()
    file = root / "private; no shell.mkv"
    file.write_bytes(b"x" * 4096)
    return root, file


def _run(root, file, **kwargs):
    return probe.inspect_private_obs_artifact(
        file, allowed_root=root, owner_approved=True,
        host_confirms_recording_stopped=True,
        host_confirms_broadcast_inactive=True, **kwargs,
    )


def _fake(monkeypatch, info=None, *, error=False, on_decode=None):
    calls = []

    def run(args, **opts):
        calls.append((args, opts))
        assert opts["stdin"] == subprocess.DEVNULL
        assert opts["check"] is False
        assert "shell" not in opts
        if error:
            return subprocess.CompletedProcess(args, 1, b"", b"SECRET RECORDING /home/private")
        if args[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args, 0, json.dumps(_GOOD_INFO if info is None else info).encode(), b""
            )
        if on_decode is not None:
            on_decode()
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(probe.subprocess, "run", run)
    return calls


def test_stopped_private_local_media_has_advisory_decodable_report(tmp_path, monkeypatch):
    root, file = _selected(tmp_path)
    calls = _fake(monkeypatch)
    result = _run(root, file)
    assert result.local_media_decoded
    assert result.video_frames == 180
    assert result.audio_streams == 1
    assert result.status == "candidate_for_owner_review"
    assert not result.recording_origin_attested
    assert not result.star_only_audio_attested
    assert not result.gameplay_or_avatar_verified
    assert not result.broadcast_authorized
    assert len(calls) == 2
    assert "-count_frames" in calls[0][0]
    assert "-xerror" in calls[1][0]
    assert calls[1][0][calls[1][0].index("-map") + 1] == "0:v:0"
    assert str(file) in calls[0][0] and str(file) in calls[1][0]
    assert "private" not in result.to_json()  # no path or user content


@pytest.mark.parametrize("overrides", [
    {}, {"owner_approved": 1}, {"host_confirms_recording_stopped": False},
    {"host_confirms_broadcast_inactive": 1},
])
def test_never_reads_without_exact_trusted_host_admission(tmp_path, monkeypatch, overrides):
    root, file = _selected(tmp_path)
    def unexpected(*_args, **_kwargs):
        pytest.fail("media must not be opened")
    monkeypatch.setattr(probe.subprocess, "run", unexpected)
    opts = {"owner_approved": True, "host_confirms_recording_stopped": True,
            "host_confirms_broadcast_inactive": True}
    opts.update(overrides)
    if overrides == {}:
        opts["owner_approved"] = False
    with pytest.raises(PermissionError):
        probe.inspect_private_obs_artifact(file, allowed_root=root, **opts)


def test_rejects_file_outside_root_symlinks_and_unsupported_containers(tmp_path, monkeypatch):
    root, file = _selected(tmp_path)
    _fake(monkeypatch)
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"x" * 4096)
    with pytest.raises(probe.RecordingArtifactError, match="outside approved"):
        _run(root, outside)
    link = root / "link.mkv"
    link.symlink_to(file)
    with pytest.raises(probe.RecordingArtifactError):
        _run(root, link)
    wrong = root / "private.mp3"
    wrong.write_bytes(b"x" * 4096)
    with pytest.raises(probe.RecordingArtifactError):
        _run(root, wrong)
    with pytest.raises(ValueError, match="absolute"):
        _run(root, "relative.mkv")
    with pytest.raises(ValueError, match="absolute"):
        _run(root, str(root / ".." / "recordings" / file.name))


@pytest.mark.parametrize("patch", [
    {"format": {"duration": "NaN"}},
    {"format": {"duration": "-1"}},
    {"format": {"duration": "1000"}},
    {"format": {"duration": None}},
    {"streams": []},
    {"streams": [{"codec_type": "video", "width": 128, "height": 72, "nb_read_frames": "180"}]},
    {"streams": [{"codec_type": "audio", "sample_rate": "8000"}]},
    {"streams": [{"codec_type": "video", "width": 9000, "height": 72, "nb_read_frames": "180"},
                 {"codec_type": "audio", "sample_rate": "8000"}]},
    {"streams": [{"codec_type": "video", "width": 128, "height": 72, "nb_read_frames": "N/A"},
                 {"codec_type": "audio", "sample_rate": "8000"}]},
    {"streams": [{"codec_type": "video", "width": 128, "height": 72, "nb_read_frames": "180"},
                 {"codec_type": "audio", "sample_rate": "NaN"}]},
])
def test_rejects_incomplete_invalid_or_unbounded_metadata(tmp_path, monkeypatch, patch):
    root, file = _selected(tmp_path)
    info = json.loads(json.dumps(_GOOD_INFO))
    info.update(patch)
    calls = _fake(monkeypatch, info)
    with pytest.raises(probe.RecordingArtifactError):
        _run(root, file)
    assert len(calls) == 1  # never decodes bad metadata


@pytest.mark.parametrize("track", [-1, 6, True, "0"])
def test_audio_index_is_strict(tmp_path, monkeypatch, track):
    root, file = _selected(tmp_path)
    calls = _fake(monkeypatch)
    with pytest.raises(ValueError, match="audio track"):
        _run(root, file, selected_audio_track=track)
    assert not calls


def test_decoder_failure_cannot_leak_file_path_or_secret_stderr(tmp_path, monkeypatch):
    root, file = _selected(tmp_path)
    _fake(monkeypatch, error=True)
    with pytest.raises(probe.RecordingArtifactError) as e:
        _run(root, file)
    assert "SECRET" not in str(e.value)
    assert str(file) not in str(e.value)


def test_changed_media_is_not_verified(tmp_path, monkeypatch):
    root, file = _selected(tmp_path)
    _fake(monkeypatch, on_decode=lambda: file.write_bytes(b"x" * 4100))
    with pytest.raises(probe.RecordingArtifactError, match="changed"):
        _run(root, file)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg absent")
def test_real_ffmpeg_decodes_synthetic_local_video_and_audio(tmp_path):
    root = tmp_path / "obs"
    root.mkdir()
    file = root / "test.mkv"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error",
        "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=8000",
        "-t", "6", "-c:v", "mpeg4", "-c:a", "aac", str(file),
    ], check=True, timeout=30)
    result = _run(root, file)
    assert result.local_media_decoded
    assert result.video_frames == 180
    assert result.audio_streams == 1
    assert result.duration_s == pytest.approx(6, abs=.1)
