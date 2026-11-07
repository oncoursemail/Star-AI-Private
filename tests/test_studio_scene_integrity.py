"""Static, offline checks for the Studio scene-integrity compiler."""
import math

import pytest

from star.studio_scene_integrity import (
    SceneCheck,
    DisjointParts,
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
    assert 'uniqueChild(object1, "North Wall")' in server
    assert "ambiguous_1" in server
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


def test_unique_path_fails_on_ambiguous_direct_children():
    test = StudioSceneTest(
        "unique_objects", (SceneCheck(("Workspace", "Lobby", "Exit Door"), "Part"),)
    )
    server = compile_scene_integrity(test).server_script
    assert "local function uniqueChild(parent, name)" in server
    assert "for _, child in ipairs(parent:GetChildren()) do" in server
    assert "if found then return nil, true end" in server
    assert "if ambiguous1 then return false, 'ambiguous_1' end" in server
    assert 'uniqueChild(object1, "Lobby")' in server
    assert 'uniqueChild(object1, "Exit Door")' in server
    assert "FindFirstChild" not in server
    assert "return false, 'missing_1'" in server


def test_scene_visual_style_checks_produce_read_only_luau():
    wall = SceneCheck(
        ("Workspace", "Aquarium", "Blue Wall"), "Part",
        expected_material="SmoothPlastic",
        expected_color_rgb=(45, 110, 200),
        color_tolerance_rgb=4,
        expected_orientation_degrees=(0, 90, 0),
        orientation_tolerance_degrees=2.5,
    )
    spec = StudioSceneTest("style_baseline", (wall,))
    server = compile_scene_integrity(spec).server_script
    assert "object1.Material ~= Enum.Material.SmoothPlastic" in server
    assert "Color3.fromRGB(45, 110, 200)" in server
    assert "expectedColor1.R) > 4/255" in server
    assert "CFrame.fromOrientation(math.rad(0.0), math.rad(90.0), math.rad(0.0))" in server
    assert "local minDot1 = math.cos(math.rad(2.5))" in server
    assert "object1.CFrame.RightVector:Dot(expectedCFrame1.RightVector)" in server
    assert "object1.CFrame.LookVector:Dot(expectedCFrame1.LookVector)" in server
    assert "return false, 'material_1'" in server
    assert "return false, 'color_1'" in server
    assert "return false, 'orientation_1'" in server
    changed = StudioSceneTest(
        "style_baseline", (SceneCheck(
            ("Workspace", "Aquarium", "Blue Wall"), "Part",
            expected_material="Metal", expected_color_rgb=(45, 110, 200),
        ),),
    )
    assert compile_scene_integrity(changed).spec_sha256 != compile_scene_integrity(spec).spec_sha256


@pytest.mark.parametrize("updates", [
    {"expected_material": "CustomMaterial; print('bad')"},
    {"expected_material": "Ball"},
    {"expected_color_rgb": [0, 0, 0]},
    {"expected_color_rgb": (0, True, 0)},
    {"expected_color_rgb": (0, -1, 0)},
    {"expected_color_rgb": (0, 256, 0)},
    {"expected_color_rgb": (0, 0)},
    {"expected_color_rgb": (0, math.nan, 0)},
    {"color_tolerance_rgb": -1},
    {"color_tolerance_rgb": 33},
    {"color_tolerance_rgb": 1.2},
    {"expected_orientation_degrees": (361, 0, 0)},
    {"expected_orientation_degrees": (0, 1, math.inf)},
    {"expected_orientation_degrees": [0, 90, 0]},
    {"orientation_tolerance_degrees": 25},
    {"orientation_tolerance_degrees": math.nan},
])
def test_rejects_bad_visual_style_fields(updates):
    with pytest.raises(ValueError):
        SceneCheck(("Workspace", "BlueWall"), "Part", **updates)


@pytest.mark.parametrize("updates", [
    {"expected_material": "Metal"},
    {"expected_color_rgb": (12, 23, 34)},
    {"expected_orientation_degrees": (0, 0, 0)},
])
def test_style_requires_basepart(updates):
    with pytest.raises(ValueError):
        SceneCheck(("Workspace", "NonPart"), "Model", **updates)


def test_disjoint_box_pair_compiles_oriented_sat_without_mesh_guessing():
    a = ("Workspace", "Arena", "PlayerSpawn")
    b = ("Workspace", "Arena", "Decoration")
    checks = (SceneCheck(a, "Part"), SceneCheck(b, "Part"))
    pair = DisjointParts(a, b, penetration_tolerance_studs=0.08)
    base = StudioSceneTest("collision_v1", checks)
    spec = StudioSceneTest("collision_v1", checks, simulated_clients=2, disjoint_pairs=(pair,))
    compiled = compile_scene_integrity(spec)
    assert compiled.spec_sha256 != compile_scene_integrity(base).spec_sha256
    server = compiled.server_script
    assert "local function blocksOverlap(a, b, tolerance)" in server
    assert "a.CFrame.RightVector" in server
    assert "aAxes[i]:Cross(bAxes[j])" in server
    assert "object1.Shape ~= Enum.PartType.Block" in server
    assert "object2.Shape ~= Enum.PartType.Block" in server
    assert "blocksOverlap(object1, object2, 0.08)" in server
    assert "return false, 'unsupported_shape_1'" in server
    assert "return false, 'unwanted_overlap_1'" in server
    assert "GetPartsInPart" not in server
    assert "Workspace" in server
    assert "PASS:collision_v1:" in compiled.plugin_script
    assert not compiled.verified_in_studio


@pytest.mark.parametrize("paths", [
    (("Workspace", "A"), ("Workspace", "A")),
    (("Workspace", "A"), ("Workspace", "B\nprint('bad')")),
    (("ReplicatedStorage", "A"), ("Workspace", "B")),
    (("Workspace",), ("Workspace", "B")),
])
def test_rejects_bad_disjoint_pair_paths(paths):
    with pytest.raises(ValueError):
        DisjointParts(*paths)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -0.01, 0.501, True, "zero"])
def test_rejects_bad_disjoint_tolerance(bad):
    with pytest.raises(ValueError):
        DisjointParts(("Workspace", "A"), ("Workspace", "B"),
                      penetration_tolerance_studs=bad)


def test_only_curated_distinct_part_pair_can_request_overlap_check():
    a, b, c = (("Workspace", v) for v in ("A", "B", "C"))
    parts = tuple(SceneCheck(p, "Part") for p in (a, b, c))
    pair = DisjointParts(a, b)
    reverse = DisjointParts(b, a)
    valid = StudioSceneTest("arena", parts, disjoint_pairs=(pair,))
    assert valid.disjoint_pairs == (pair,)
    for invalid in (
        [pair],
        (pair, reverse),
        tuple([pair] * 17),
        (DisjointParts(a, ("Workspace", "Missing")),),
    ):
        with pytest.raises(ValueError):
            StudioSceneTest("arena", parts, disjoint_pairs=invalid)
    with pytest.raises(ValueError):
        StudioSceneTest(
            "arena", (SceneCheck(a, "Part"), SceneCheck(b, "MeshPart")),
            disjoint_pairs=(pair,),
        )


def test_maximum_suite_remains_bounded_and_off_by_default():
    paths = tuple(("Workspace", f"P{i}") for i in range(64))
    checks = tuple(SceneCheck(path, "Part") for path in paths)
    pairs = tuple(DisjointParts(paths[i], paths[i + 16]) for i in range(16))
    compiled = compile_scene_integrity(StudioSceneTest(
        "test_max", checks, simulated_clients=8, disjoint_pairs=pairs,
    ))
    assert len(compiled.server_script) < 85_000
    assert compiled.server_script.count("unwanted_overlap_") == 16
    assert compiled.server_script.count("local function blocksOverlap") == 1
    assert "ExecuteMultiplayerTestAsync(8" in compiled.plugin_script
    assert not compiled.verified_in_studio
