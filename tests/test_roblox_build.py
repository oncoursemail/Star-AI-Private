"""Offline tests for STAR's Roblox environment builder (no Studio, no network)."""
from __future__ import annotations

import math

import pytest

from star.roblox_build import checks, kits, llm, luau, pipeline, scene
from star.roblox_build.geom import STYLES, Ctx, aabb, nearest_brick, part, rot_matrix, transform


def _spec(**extra):
    raw = {"name": "T", "style": "midpoly", "mood": "cozy_interior", "size": [60, 60], "ground": "grass",
           "zones": [{"id": "room", "rect": [-15, -15, 15, 15], "floor": "plank"}],
           "rooms": [{"zone": "room", "h": 14, "wall": "plaster", "roof": "flat",
                      "openings": [{"side": "S", "at": 0.5, "w": 6, "h": 9, "kind": "door"}]}],
           "spawn": [0, 25], "focal": [{"id": "f", "at": [0, -8]}], "props": []}
    raw.update(extra)
    spec, notes = scene.normalize(raw)
    return spec, notes


def test_every_kit_builds_in_every_style():
    for name in kits.KITS:
        for style in STYLES:
            parts = kits.build_kit(Ctx(style, seed=3, state="abandoned"), name, {})
            assert 0 < len(parts) <= 400, name
            for p in parts:
                assert all(math.isfinite(v) and v >= 0.05 for v in p["z"]), name
                assert all(math.isfinite(v) for v in p["p"]), name


def test_stud_colours_snap_to_brickcolors_and_get_studs():
    ctx = Ctx("stud", {"primary": "#123456"})
    p = part(ctx, "B", (4, 1, 4), (0, 0, 0), mat="wood")
    assert p["m"] == "Plastic" and p.get("studs") is True
    assert tuple(p["c"]) == nearest_brick(tuple(p["c"]))


def test_transform_yaw_matches_roblox_rotation():
    ctx = Ctx("midpoly")
    p = transform([part(ctx, "B", (1, 1, 1), (0, 0, 1))], (10, 0, 0), 90)[0]
    m = rot_matrix(0, 90, 0)
    assert p["p"][0] == pytest.approx(10 + m[0][2]) and p["p"][2] == pytest.approx(m[2][2], abs=1e-6)


def test_normalize_clamps_and_drops_unknown():
    spec, notes = _spec(props=[{"kit": "nope", "at": [0, 0]}, {"kit": "table", "at": [999, 0], "params": {"w": 99}}])
    assert len(spec["props"]) == 1 and spec["props"][0]["at"][0] == 30 and spec["props"][0]["params"]["w"] == 16
    assert any("unknown kit" in n for n in notes)


def test_room_without_door_is_reported_and_autofixed():
    spec, _ = _spec(rooms=[{"zone": "room", "h": 14, "wall": "plaster", "roof": "flat", "openings": []}])
    report = checks.run(spec, scene.compile_spec(spec))
    codes = {d["code"] for d in report["defects"]}
    assert "no_door" in codes and "unreachable" in codes
    fixed, _compiled, report2, log = pipeline.autofix(spec)
    assert any("door" in line for line in log)
    assert not {d["code"] for d in report2["defects"]} & {"no_door", "unreachable"}


def test_floating_prop_detected_and_dropped_to_floor():
    spec, _ = _spec(props=[{"kit": "table", "at": [0, 0], "y": 6}])
    report = checks.run(spec, scene.compile_spec(spec))
    assert any(d["code"] == "floating" for d in report["defects"])
    fixed, _c, report2, _log = pipeline.autofix(spec)
    assert "y" not in fixed["props"][0] and not any(d["code"] == "floating" for d in report2["defects"])


def test_z_fighting_found_for_coplanar_boxes():
    ctx = Ctx("midpoly")
    a = part(ctx, "B", (4, 1, 4), (0, 0.5, 0), color=(200, 0, 0))
    b = part(ctx, "B", (4, 1, 4), (1, 0.5, 0), color=(0, 0, 200))
    found = checks.z_fighting([a, b], [aabb(a), aabb(b)])
    assert found and found[0]["area"] > 1


def test_wall_props_snap_to_wall_and_lamps_reach_ceiling():
    spec, _ = _spec(props=[{"kit": "shelf", "at": [10, 0]}, {"kit": "pendant_lamp", "at": [0, 0], "params": {"y": 30}}])
    compiled = scene.compile_spec(spec)
    shelf = [aabb(p) for p in compiled["parts"] if p.get("prop") == 0]
    assert max(b[1][0] for b in shelf) == pytest.approx(15 - scene.WALL_T["midpoly"], abs=0.1)
    report = checks.run(spec, compiled)
    assert not any(d["code"] == "floating" and d.get("prop") == 1 for d in report["defects"])


def test_luau_chunks_are_bounded_and_marked():
    spec, _ = _spec(props=[{"kit": "pew", "at": [0, 0], "repeat": {"n": 10, "step": [0, 2.5]}}], sign_text='Café "Star"')
    compiled = scene.compile_spec(spec)
    chunks = luau.build_chunks("Test Build", compiled["parts"])
    assert chunks and all(luau.MARK in c for c in chunks)
    assert 'old:Destroy()' in chunks[0] and "MapDrafts" in chunks[0]
    assert "é" not in "".join(chunks)
    assert luau.MARK in luau.lighting_luau(compiled["lighting"])
    assert luau.safe_name("a b/c") == "a_b_c" and luau.safe_name("") == "Build"


def test_parse_json_tolerates_fences_and_trailing_commas():
    assert llm.parse_json('blah ```json\n{"a": [1, 2,],}\n``` end') == {"a": [1, 2]}
    assert llm.parse_json("<think>x</think>{\"ops\": []}") == {"ops": []}
    assert llm.parse_json("no json") is None


def test_apply_ops_edits_and_renormalizes():
    spec, _ = _spec(props=[{"kit": "table", "at": [0, 0]}, {"kit": "chair", "at": [2, 0]}])
    new, log = pipeline.apply_ops(spec, [{"op": "remove", "index": 1}, {"op": "move", "index": 0, "at": [5, 5]},
                                         {"op": "add", "prop": {"kit": "floor_lamp", "at": [-5, -5]}},
                                         {"op": "set", "field": "mood", "value": "warm_evening"}, {"op": "bogus"}])
    assert [p["kit"] for p in new["props"]] == ["table", "floor_lamp"] and new["props"][0]["at"] == [5, 5]
    assert new["mood"] == "warm_evening" and len(log) == 4


def test_cameras_stay_out_of_solid_parts():
    spec, _ = _spec(props=[{"kit": "column", "at": [0, 20], "params": {"h": 12, "w": 4}}])
    compiled = scene.compile_spec(spec)
    boxes = [aabb(p) for p in compiled["parts"] if p.get("t", 0) < 0.6 and p.get("kit") not in ("ground", "fill_light")]
    for cam in compiled["cameras"]:
        assert not any(all(b[0][i] < cam["position"][i] < b[1][i] for i in range(3)) for b in boxes), cam["id"]
