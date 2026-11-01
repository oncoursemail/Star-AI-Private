from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from star import intelligence, video_study


def hub(tmp_path, **kwargs):
    return intelligence.LocalIntelligence(
        home=tmp_path / "star-home", workspace=tmp_path,
        skills_enabled=False, graphify_enabled=False, roblox_research_enabled=False,
        design_enabled=False, map_plans_enabled=False,
        **kwargs,
    )


def episode():
    return {"game": "Test Obby", "source_kind": "owned_studio_playtest",
            "source_id": "test-session-001", "steps": [
                {"at": 1.0, "action": "jump", "success": True, "seen": "reached a ledge"}]}


def test_tools_are_off_without_owner_opt_in(tmp_path):
    reader = hub(tmp_path)
    try:
        offered = {entry["name"] for entry in reader.definitions("Watch Roblox games and learn mechanics")}
        assert "star_game_episode_analyze" not in offered
        assert "star_game_video_study" not in offered
        with pytest.raises(PermissionError):
            reader.call("star_game_episode_analyze", {"episode": episode()}, enabled={"star_game_episode_analyze"})
    finally:
        reader.close()


def test_game_learning_tools_offers_analysis_not_writes(tmp_path):
    reader = hub(tmp_path, game_experience_enabled=True)
    try:
        offered = {entry["name"] for entry in reader.definitions("Analyze game mechanics in Roblox")}
        assert "star_game_episode_analyze" in offered
        assert "star_game_experience_search" in offered
        assert "star_game_episode_save" not in offered
        summary = reader.call("star_game_episode_analyze", {"episode": episode()}, enabled=offered)
        assert summary["verified_mechanics"] == 0
        with pytest.raises(PermissionError):
            reader.call("star_game_episode_save", {"episode": episode()},
                        enabled={"star_game_episode_save"})
    finally:
        reader.close()


def test_candidate_saving_requires_separate_opt_in(tmp_path):
    reader = hub(tmp_path, game_experience_enabled=True, game_experience_write_enabled=True)
    try:
        names = {tool["name"] for tool in reader.definitions("Remember game playtest mechanics")}
        assert "star_game_episode_save" in names
        saved = reader.call("star_game_episode_save", {"episode": episode()}, enabled=names)
        result = reader.call("star_game_experience_search", {"query": "Test Obby"}, enabled=names)
        assert saved["reviewed"] is False
        assert result["candidates"][0]["reviewed"] is False
    finally:
        reader.close()


def test_video_study_selected_workspace_only(tmp_path, monkeypatch):
    clips = tmp_path / "clips"
    clips.mkdir()
    inside = clips / "my-video.mp4"
    inside.write_bytes(b"test")
    elsewhere = tmp_path.parent / "external.mp4"
    settings = SimpleNamespace(ffmpeg_dir="")
    reader = hub(tmp_path, video_study_enabled=True, video_settings=settings)
    paths = []
    def fake(settings, home, path, question, **kwargs):
        paths.append(Path(path))
        return {"verified_mechanics": 0, "window_interpretations": []}
    monkeypatch.setattr(video_study, "analyze_local", fake)
    try:
        names = {tool["name"] for tool in reader.definitions("Watch gameplay video")}
        assert "star_game_video_study" in names
        args = {"path": "clips/my-video.mp4", "question": "Can she jump?"}
        result = reader.call("star_game_video_study", args, enabled=names)
        assert result["verified_mechanics"] == 0
        assert paths == [inside]
        with pytest.raises(PermissionError):
            reader.call("star_game_video_study", {**args, "path": "../external.mp4"}, enabled=names)
        with pytest.raises(PermissionError):
            reader.call("star_game_video_study", {**args, "path": str(elsewhere)}, enabled=names)
    finally:
        reader.close()


def test_video_tool_disabled_without_selected_workspace(tmp_path):
    reader = intelligence.LocalIntelligence(
        home=tmp_path, skills_enabled=False, graphify_enabled=False,
        roblox_research_enabled=False, video_study_enabled=True,
        video_settings=SimpleNamespace(ffmpeg_dir=""),
    )
    try:
        assert "star_game_video_study" not in {
            tool["name"] for tool in reader.definitions("Watch a video")
        }
    finally:
        reader.close()
