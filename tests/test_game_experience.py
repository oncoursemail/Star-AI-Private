from __future__ import annotations

from copy import deepcopy
import json

import pytest

from star import game_experience as game


@pytest.fixture
def episode():
    return {
        "game": "Animal Arena Prototype",
        "source_kind": "owned_studio_playtest",
        "source_id": "session-20261024-abc",
        "steps": [
            {"at": 1, "action": "move", "seen": "The player starts near a wall", "success": True},
            {"at": 3, "action": "jump", "seen": "A jump visibly reaches the ledge", "success": True},
            {"at": 5, "action": "jump", "seen": "A second jump hits the edge", "success": False},
        ],
    }


def test_analysis_is_evidence_grounded_and_not_verified(episode):
    report = game.analyze_episode(episode)
    assert report["game"] == "Animal Arena Prototype"
    assert report["verified_mechanics"] == 0
    assert report["observations"] == 3
    actions = {x["action"]: x for x in report["candidate_mechanics"]}
    assert actions["jump"]["status"] == "mixed_results"
    assert actions["jump"]["successes"] == 1
    assert actions["jump"]["failures"] == 1
    assert actions["move"]["status"] == "insufficient_evidence"
    assert all(item["status"] == "not_run" for item in report["suggested_experiments"])
    assert "landing" in " ".join(i["idea"] for i in report["original_design_ideas"])


def test_episode_digest_is_stable_under_key_reordering(episode):
    reordered = dict(reversed(list(episode.items())))
    assert game.analyze_episode(episode)["episode_sha256"] == game.analyze_episode(reordered)["episode_sha256"]


@pytest.mark.parametrize("path,value", [
    (("source_kind",), "youtube_url"),
    (("source_kind",), []),
    (("source_id",), "https://token.example.com/x"),
    (("steps", 0, "at"), -1),
    (("steps", 1, "at"), 1),
    (("steps", 1, "at"), float("nan")),
    (("steps", 0, "action"), []),
    (("steps", 0, "action"), "publish_to_roblox"),
    (("steps", 0, "success"), "true"),
    (("steps", 0, "frame_sha256"), "abcd"),
    (("steps", 0, "seen"), "x" * 501),
])
def test_invalid_untrusted_trace_rejected(episode, path, value):
    copy = deepcopy(episode)
    node = copy
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        game.analyze_episode(copy)


def test_episode_count_bounded(episode):
    episode["steps"] = [{"at": index, "action": "observe"} for index in range(65)]
    with pytest.raises(ValueError, match="1 to 64"):
        game.analyze_episode(episode)


def test_observations_save_as_unreviewed_project_scoped_candidates(tmp_path, episode):
    result = game.save_candidate(tmp_path, "ProjectA", episode)
    assert result["reviewed"] is False
    found = game.search_candidates(tmp_path, "ProjectA", "Animal Arena")
    assert len(found["candidates"]) == 1
    assert found["candidates"][0]["reviewed"] is False
    assert found["candidates"][0]["note_id"] == result["note_id"]
    assert game.search_candidates(tmp_path, "ProjectB", "Animal Arena")["candidates"] == []


def test_repeat_events_without_outcome_does_not_prove_success():
    report = game.analyze_episode({
        "game": "Puzzle Stage",
        "source_kind": "owner_observation",
        "source_id": "note-001",
        "steps": [
            {"at": 2, "action": "interact", "seen": "door looked brighter"},
            {"at": 7, "action": "interact", "seen": "button still present"},
        ],
    })
    action = report["candidate_mechanics"][0]
    assert action["status"] == "insufficient_evidence"
    assert action["ungraded"] == 2


def test_search_limits_validate_before_access(tmp_path):
    with pytest.raises(ValueError):
        game.search_candidates(tmp_path, "ProjectA", "game", limit=99)


def test_save_does_not_auto_review(tmp_path, episode):
    saved = game.save_candidate(tmp_path, "ProjectA", episode)
    from star.knowledge import KnowledgeStore
    store = KnowledgeStore(tmp_path / "knowledge")
    try:
        assert store.find("ProjectA", "Animal Arena", reviewed_only=True) == []
        raw = store.find("ProjectA", "Animal Arena", reviewed_only=False)
        assert json.loads(raw[0].text)["verified_mechanics"] == 0
    finally:
        store.close()
