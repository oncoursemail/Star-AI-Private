"""Static, offline checks for the Studio scene-integrity compiler."""
import math

import pytest

from star.studio_scene_integrity import (
    SceneCheck,
    StudioSceneTest,
    compile_scene_integrity,
)


def test_compiles_read_only_multiclient_studio_test():
    spec = StudioSceneTest(
        "aquarium_arena_v1",
        (
            SceneCheck(
                ("Workspace", "Aquarium", "Arena", "North Wall"),
                "Part", anchored=True, can_collide=True,
                max_transparency=0.1, expected_position=(0, 8, 14),
                position_tolerance_studs=0.25,
                minimum_size=(12, 10, 0.5),
            ),
            SceneCheck(
                ("Workspace", "Aquarium", "Arena"),
                "Model", min_descendants=20,
            ),
            SceneCheck(
                ("StarterGui", "MatchHud", "HealthBar"), "Frame",
            ),
        ),
        simulated_clients=4,
    )
    result = compile_scene_integrity(spec)
    assert not result.verified_in_studio
    assert len(result.spec_sha256) == 64
    assert result == compile_scene_integrity(spec)
    server, plugin = result.server_script, result.plugin_script
    assert "game:GetService(\"Workspace\")" in server
    assert "FindFirstChild(\"North Wall\")" in server
    assert "object1.Anchored ~= true" in server
    assert "object1.CanCollide ~= true" in server
    assert "object1.Transparency > 0.1" in server
    assert "Vector3.new(0.0, 8.0, 14.0)" in server
    assert "size1.X < 12.0" in server
    assert "object2:GetDescendants()" in server
    assert "local worked, passed, detail = pcall(verify)" in server
    assert 'if not game:GetService("RunService"):IsStudio() then return end' in server
    assert 'object1.ClassName ~= "Part"' in server
    assert "sts:EndTest('FAIL:verifier_error')" in server
    assert "ExecuteMultiplayerTestAsync(4," in plugin
    assert "if result ~=" in plugin
    assert "PASS:aquarium_arena_v1:" in server and "PASS:aquarium_arena_v1:" in plugin
    assert not any(t in server for t in ("HttpService", "require(", "loadstring(", "SetAsync(", "Destroy()"))


@pytest.mark.parametrize("path", [
    ("Workspace",), ("NotAService", "Part"),
    ("Workspace", "Arena\nprint('owned')"),
    ("Workspace", ""),
])
def test_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        SceneCheck(path, "Part")


@pytest.mark.parametrize("updates", [
    {"anchored": 1},
    {"can_collide": "true"},
    {"max_transparency": float("nan")},
    {"max_transparency": 1.1},
    {"minimum_size": (1, 0, 2)},
    {"minimum_size": (1, math.inf, 2)},
    {"expected_position": (1, "a", 2)},
    {"position_tolerance_studs": float("nan")},
    {"position_tolerance_studs": 100},
    {"min_descendants": 3},
])
def test_rejects_invalid_checks(updates):
    with pytest.raises(ValueError):
        SceneCheck(("Workspace", "Wall"), "Part", **updates)


def test_no_nonbasepart_property_checks():
    with pytest.raises(ValueError):
        SceneCheck(("Workspace", "Wall"), "Model", anchored=True)
    with pytest.raises(ValueError):
        SceneCheck(("Workspace", "Wall"), "Model", minimum_size=(1, 1, 1))
    with pytest.raises(ValueError):
        SceneCheck(("Workspace", "Wall"), "Frame", max_transparency=0.5)


def test_rejects_invalid_suite():
    check = SceneCheck(("Workspace", "Arena"), "Model", min_descendants=3)
    for kwargs in (
        {"suite_id": "a\nprint('owned')"},
        {"suite_id": "bad spaced"},
        {"simulated_clients": 9},
        {"simulated_clients": True},
        {"checks": (check, check)},
        {"checks": tuple()},
        {"checks": [check]},
        {"checks": tuple([check] * 65)},
    ):
        data = {"suite_id": "arena", "checks": (check,)}
        data.update(kwargs)
        with pytest.raises(ValueError):
            StudioSceneTest(**data)


def test_spec_change_invalidate_marker():
    test = StudioSceneTest(
        "arena", (SceneCheck(("Workspace", "Arena"), "Model"),)
    )
    one = compile_scene_integrity(test)
    changed = StudioSceneTest(
        "arena", (SceneCheck(("Workspace", "Arena"), "Folder"),)
    )
    two = compile_scene_integrity(changed)
    assert one.spec_sha256 != two.spec_sha256
    assert one.plugin_script != two.plugin_script


def test_bad_compiler_input_rejected():
    with pytest.raises(TypeError):
        compile_scene_integrity({"suite_id": "arena"})