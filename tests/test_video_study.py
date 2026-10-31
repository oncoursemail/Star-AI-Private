from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from star import video_study as study


def test_timeline_short_video_is_fully_sampled():
    assert study.plan_windows(125, window_seconds=60, max_windows=4) == [
        (0.0, 60), (60.0, 120.0), (120.0, 125)
    ]


def test_long_recording_samples_start_and_end_without_pretending_full_coverage():
    plan = study.plan_windows(1800, window_seconds=60, max_windows=4)
    assert len(plan) == 4
    assert plan[0] == (0, 60.0)
    assert plan[-1] == (1740, 1800)
    assert all(a[1] < b[0] for a, b in zip(plan, plan[1:]))


@pytest.mark.parametrize("duration,window,count", [(0, 60, 8), (5500, 60, 8),
                                                      (10, 0, 8), (20, 200, 8),
                                                      (20, 50, 0), (20, 50, 13),
                                                      (float("nan"), 20, 2)])
def test_windows_validate_limits(duration, window, count):
    with pytest.raises(ValueError):
        study.plan_windows(duration, window_seconds=window, max_windows=count)


def test_window_frames_and_prompt_are_time_anchored(tmp_path, monkeypatch):
    local = tmp_path / "recording.mp4"
    local.write_bytes(b"mock recording")
    events = []

    def run(command, timeout):
        events.append(command)
        if "-frames:v" in command:
            Path(command[-1]).write_bytes(b"jpeg frame data")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(study.video, "_run", run)
    facts = {"duration": 100.0, "width": 1280, "height": 720, "has_audio": False}
    window = study.read_window(local, tmp_path / "slices", facts, "ffmpeg", 25.0, 45.0)
    assert len(window.frames) == study.FRAMES_PER_WINDOW
    assert window.times[0] > 25 and window.times[-1] < 45
    assert not window.transcript
    prompt = study.window_prompt(window, "How does the jump work?")
    assert "continuous motion" in prompt
    assert "hypotheses" in prompt
    assert "How does the jump work?" in prompt
    assert len(events) == study.FRAMES_PER_WINDOW


def test_study_local_reports_unobserved_gaps(tmp_path, monkeypatch):
    local = tmp_path / "video.mp4"
    local.write_bytes(b"mock")
    monkeypatch.setattr(study.video, "ffmpeg_tools", lambda folder="": ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(study.video, "probe",
                        lambda *_: {"duration": 600.0, "width": 640, "height": 360, "has_audio": False})

    def run(command, timeout):
        if "-frames:v" in command:
            Path(command[-1]).write_bytes(b"frame")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    monkeypatch.setattr(study.video, "_run", run)
    evidence = study.study_local(local, tmp_path / "out", window_seconds=30, max_windows=3)
    summary = evidence.report()
    assert len(summary["windows"]) == 3
    assert summary["covered_seconds"] == 90
    assert summary["unobserved_seconds"] == 510
    assert summary["verified_mechanics"] == 0
    assert summary["windows"][-1]["end"] == 600


def test_local_only_url_rejected_before_open(tmp_path):
    with pytest.raises(study.video.VideoError, match="URLs are not fetched"):
        study.validate_source(Path("https://video.example/v.mp4"), "ffprobe")


def test_model_assessment_uses_owner_selected_route_not_auto_hosted(tmp_path, monkeypatch):
    owner_movie = tmp_path / "clip.mp4"
    owner_movie.write_bytes(b"video")
    w = study.Window(10, 20, [12.5], [owner_movie], [], audio_note="Silent.")
    seen = study.Study("clip.mp4", 30, [w], 10)
    monkeypatch.setattr(study, "study_local", lambda *a, **kw: seen)
    calls = []
    from star import media_places, vision
    monkeypatch.setattr(media_places, "require_video_provider",
                        lambda settings, home: calls.append("route") or "pc")
    monkeypatch.setattr(vision, "ask",
                        lambda settings, prompt, images, **kw: calls.append(prompt) or
                        SimpleNamespace(text="Possible double-jump; requires test",
                                        model="test-vision", seconds=1.0))
    report = study.analyze_local(SimpleNamespace(), tmp_path, owner_movie, "Describe movement")
    assert report["window_interpretations"][0]["status"] == "model_interpretation_unverified"
    assert calls[0] == "route"
    assert "Describe movement" in calls[1]


def test_model_route_denial_happens_before_decoding(tmp_path, monkeypatch):
    from star import media_places
    def blocked(settings, home):
        raise PermissionError("No authorized local vision model")
    monkeypatch.setattr(media_places, "require_video_provider", blocked)
    with pytest.raises(PermissionError, match="No authorized"):
        study.analyze_local(SimpleNamespace(), tmp_path, tmp_path / "any.mp4", "Watch")
