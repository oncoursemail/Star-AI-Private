"""Offline tests: adaptive keyframe screening, no actual GPU/OBS/gameplay required."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from star import chat_media, video_sampling, video_understanding as video


def make_preview(path: Path, colour: tuple[int, int, int], size=(160, 90)) -> Path:
    Image.new("RGB", size, colour).save(path)
    return path


def test_candidate_times_cover_all_windows_without_out_of_bounds():
    points = video_sampling.candidate_times(120, 4)
    assert len(points) == 12
    assert [slot for slot, _ in points] == [0] * 3 + [1] * 3 + [2] * 3 + [3] * 3
    assert all(0 < second < 120 for _, second in points)
    assert [round(second, 1) for slot, second in points if slot == 0] == [6, 15, 24]


@pytest.mark.parametrize("duration,windows", [(float("nan"), 4), (float("inf"), 4), (-1, 4),
                                               (5500, 4), (1, 0), (1, 7), (1, True)])
def test_adaptive_sampling_rejects_unbounded_requests(duration, windows):
    with pytest.raises(ValueError):
        video_sampling.candidate_times(duration, windows)


def test_adaptive_reduces_exact_duplicate_frames_without_false_events(tmp_path):
    candidates = []
    for window, second in video_sampling.candidate_times(40, 4):
        image = make_preview(tmp_path / f"{len(candidates)}.jpg", (30, 100, 180))
        candidates.append(video_sampling.inspect_candidate(window, second, image))
    chosen = video_sampling.choose_keyframes(candidates, 4)
    assert len(chosen) == 1
    assert chosen[0].second == pytest.approx(5.0)


def test_adaptive_preserves_visual_changes_and_actual_temporal_order(tmp_path):
    colours = [(60, 150, 30), (60, 150, 30), (180, 30, 60), (20, 20, 230)]
    candidates = []
    for slot, second in video_sampling.candidate_times(40, 4):
        preview = make_preview(tmp_path / f"{len(candidates)}.jpg", colours[slot])
        candidates.append(video_sampling.inspect_candidate(slot, second, preview))
    chosen = video_sampling.choose_keyframes(candidates, 4)
    assert [x.window for x in chosen] == [0, 2, 3]
    assert all(b.second > a.second for a, b in zip(chosen, chosen[1:]))


def test_adaptive_detects_equal_brightness_color_changes(tmp_path):
    red = video_sampling.inspect_candidate(0, 1, make_preview(tmp_path / "red.png", (255, 0, 0)))
    green = video_sampling.inspect_candidate(1, 2, make_preview(tmp_path / "green.png", (0, 255, 0)))
    assert video_sampling.distance(red, green) > 0.5


def test_adaptive_preview_rejects_bombs_and_corruption(tmp_path):
    too_big = make_preview(tmp_path / "large.png", (40, 40, 40), (1000, 600))
    with pytest.raises(ValueError, match="resolution"):
        video_sampling.inspect_candidate(0, 5, too_big)
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    with pytest.raises(OSError):
        video_sampling.inspect_candidate(0, 5, broken)


def fake_video_tools(monkeypatch, *, mode="changes", missing_previews=False, missing_full=False):
    calls = []

    def run(command, timeout):
        calls.append(command)
        if "ffprobe" in command[0]:
            return SimpleNamespace(stdout=json.dumps({
                "format": {"duration": "48"},
                "streams": [{"codec_type": "video", "width": 1280, "height": 720}],
            }))
        at = float(command[command.index("-ss") + 1])
        dest = Path(command[-1])
        is_preview = "scale=160:160:force_original_aspect_ratio=decrease" in command
        if (is_preview and missing_previews) or (not is_preview and missing_full):
            return SimpleNamespace(stdout="", returncode=1)
        if mode == "static":
            colour = (20, 40, 150)
        elif at < 16:
            colour = (100, 140, 40)
        elif at < 32:
            colour = (140, 20, 120)
        else:
            colour = (20, 70, 220)
        make_preview(dest, colour, size=(160, 90) if is_preview else (768, 432))
        return SimpleNamespace(stdout="", returncode=0)

    monkeypatch.setattr(video, "_run", run)
    monkeypatch.setattr(video, "ffmpeg_tools", lambda folder="": ("ffmpeg", "ffprobe"))
    return calls


def test_prepare_adaptive_is_opt_in_and_preserves_provenance(tmp_path, monkeypatch):
    calls = fake_video_tools(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    evidence = video.prepare(clip, tmp_path / "work", frames=4, frame_sampling="adaptive")
    assert evidence.frame_sampling == "adaptive"
    assert 1 < len(evidence.frames) <= 4
    assert len(evidence.frames) == len(evidence.times)
    assert all(evidence.times[i] < evidence.times[i + 1] for i in range(len(evidence.times) - 1))
    assert len([command for command in calls if "scale=160:160:force_original_aspect_ratio=decrease" in command]) == 12
    assert not list((tmp_path / "work" / "frames").glob("star-keyframes-*"))
    assert "low-resolution thumbnail candidates" in video.evidence_text(evidence)
    assert "You have NOT seen what happens between them" in video.evidence_text(evidence)
    assert "rest of the video was not seen" in video.footer(evidence)
    # No sound track, no imaginary transcript or falsely claimed video understanding.
    assert evidence.transcript == []


def test_prepare_static_reuses_one_frame_and_skips_extra_vision_tokens(tmp_path, monkeypatch):
    fake_video_tools(monkeypatch, mode="static")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    evidence = video.prepare(clip, tmp_path / "out", frames=4, frame_sampling="adaptive")
    assert len(evidence.frames) == 1
    assert "1 still frame sampled" in video.evidence_text(evidence)


def test_adaptive_broken_thumbnails_fallback_to_uniform(tmp_path, monkeypatch):
    fake_video_tools(monkeypatch, missing_previews=True)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    evidence = video.prepare(clip, tmp_path / "work", frames=4, frame_sampling="adaptive")
    assert len(evidence.frames) == 4
    assert evidence.times == [6, 18, 30, 42]


def test_uniform_mode_uses_only_four_decodes_and_no_thumbnails(tmp_path, monkeypatch):
    calls = fake_video_tools(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    evidence = video.prepare(clip, tmp_path / "work")
    assert evidence.frame_sampling == "uniform"
    assert len([command for command in calls if "-ss" in command]) == 4
    assert "low-resolution" not in video.evidence_text(evidence)


def test_stale_frame_from_previous_turn_never_becomes_new_evidence(tmp_path, monkeypatch):
    calls = fake_video_tools(monkeypatch, missing_full=True)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    folder = tmp_path / "work" / "frames"
    folder.mkdir(parents=True)
    old = make_preview(folder / "frame_01.jpg", (255, 0, 0))
    assert old.exists()
    with pytest.raises(video.VideoError, match="decode any frame"):
        video.prepare(clip, tmp_path / "work")
    assert len([call for call in calls if "-ss" in call]) == 4
    assert not old.exists()


def test_cancelled_frame_sampling_never_decodes_or_fabricates_success(tmp_path, monkeypatch):
    calls = fake_video_tools(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    with pytest.raises(RuntimeError, match="cancelled by user"):
        video.prepare(clip, tmp_path / "work", frame_sampling="adaptive", cancelled=lambda: True)
    assert len([call for call in calls if "-ss" in call]) == 0


def test_invalid_strategy_rejected_before_ffmpeg_probing(tmp_path, monkeypatch):
    calls = fake_video_tools(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"test")
    with pytest.raises(ValueError, match="sampling"):
        video.prepare(clip, tmp_path / "work", frame_sampling="download-all")
    assert calls == []


def test_chat_media_only_activates_adaptive_if_local_environment_explicit(tmp_path, monkeypatch):
    seen = []

    def stub_prepare(path, workdir, **kwargs):
        seen.append(kwargs["frame_sampling"])
        return video.Evidence(name=path.name, duration=1, frames=[path], times=[0.5],
                              audio_note="No sound.", frame_sampling=kwargs["frame_sampling"])

    monkeypatch.setattr(video, "prepare", stub_prepare)
    monkeypatch.setattr(chat_media.media_places, "require_video_provider", lambda settings, home: "pc")
    clip = tmp_path / "gameplay.mp4"
    clip.write_bytes(b"test")
    settings = SimpleNamespace(ffmpeg_dir="")
    monkeypatch.delenv("STAR_VIDEO_FRAME_SAMPLING", raising=False)
    chat_media.prepare_turn(settings, tmp_path, "What happens?", [clip], tmp_path / "a")
    monkeypatch.setenv("STAR_VIDEO_FRAME_SAMPLING", "adaptive")
    chat_media.prepare_turn(settings, tmp_path, "What happens?", [clip], tmp_path / "b")
    monkeypatch.setenv("STAR_VIDEO_FRAME_SAMPLING", "yes")
    chat_media.prepare_turn(settings, tmp_path, "What happens?", [clip], tmp_path / "c")
    assert seen == ["uniform", "adaptive", "uniform"]
