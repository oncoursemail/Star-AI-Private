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


# --------------------------------------------------------------------------- roblox-scenes fixes (10-29 eval defects)

def test_kit_menu_offers_landmarks_only_when_the_brief_names_them():
    from star.roblox_build import prompts
    cozy = [line.split("(")[0] for line in prompts.kit_menu("Cozy bookshop interior: tall bookcases and a reading table.").splitlines()]
    assert "lighthouse" not in cozy and "subway_car" not in cozy and "bamboo_cluster" not in cozy
    assert "bookcase_tall" in cozy and "reading_table" in cozy
    fishing = [line.split("(")[0] for line in prompts.kit_menu("A lake with a wooden dock and a lighthouse.").splitlines()]
    assert "lighthouse" in fishing and "dock" in fishing
    # a common word in a kit summary ("the", "car" in "train car") no longer pulls in an unrelated themed kit
    subway = [line.split("(")[0] for line in prompts.kit_menu("Subway platform with a stopped train car.").splitlines()]
    assert "bumper_car" not in subway and "subway_car" in subway


def test_cohere_drops_off_brief_kits_and_caps_set_pieces():
    from star.roblox_build import art
    spec, _ = _spec(props=[["lighthouse", 0, 0], ["subway_car", 5, 5], ["chair", 1, 1]] + [["dock", 0, i * 3] for i in range(6)])
    out, log = art.cohere(spec, "Cozy fishing cabin on a lake with a dock")
    kinds = [p["kit"] for p in out["props"]]
    assert "lighthouse" not in kinds and "subway_car" not in kinds and "chair" in kinds
    assert kinds.count("dock") == art.BIG_KIT_CAP and log


def test_fit_rooms_shrinks_big_empty_rooms_towards_their_furniture():
    from star.roblox_build import art
    raw = {"name": "T", "style": "midpoly", "size": [120, 120], "zones": [{"id": "hall", "rect": [-50, -50, 50, 50]}],
           "rooms": [{"zone": "hall", "h": 14, "openings": [{"side": "S", "at": 0.5, "w": 6, "h": 9, "kind": "door"}]}],
           "spawn": [0, 40], "focal": [{"id": "f", "at": [0, 0]}], "props": [["table", 0, 0], ["chair", 3, 0], ["shelf", -6, 4]]}
    spec, _ = scene.normalize(raw)
    out, log = art.fit_rooms(spec)
    x0, z0, x1, z1 = out["zones"][0]["rect"]
    assert (x1 - x0) < 100 and (z1 - z0) < 100 and log
    assert x0 <= -6 and x1 >= 3 and z0 <= 0 and z1 >= 40   # props, focal and spawn stay inside


def test_scatter_frames_outdoor_maps_and_keeps_routes_clear():
    from star.roblox_build import art
    raw = {"name": "T", "style": "lowpoly", "size": [120, 120], "ground": "grass", "zones": [],
           "paths": [{"from": [0, 55], "to": [0, -20], "w": 8}], "spawn": [0, 50], "focal": [{"id": "f", "at": [0, -20]}]}
    spec, _ = scene.normalize(raw)
    out, _log = art.scatter(spec, "Forest camp clearing with tents and tall pines")
    added = out["props"]
    assert len(added) >= 8
    assert all(abs(p["at"][0]) > 5 for p in added if p["kit"] != "cliff")   # nothing on the path
    edge = [p for p in added if p["why"] == "edge framing"]
    assert edge and all(max(abs(p["at"][0]), abs(p["at"][1])) > 30 for p in edge)   # denser at the edge


def test_night_scenes_get_a_measured_preset_path_lights_and_lit_windows():
    from star.roblox_build import art
    raw = {"name": "T", "style": "midpoly", "mood": "cold_night", "size": [120, 120], "ground": "snow",
           "zones": [{"id": "cabin", "rect": [-10, -10, 10, 10]}],
           "rooms": [{"zone": "cabin", "h": 12, "windows": "plain", "openings": [{"side": "S", "at": 0.5, "kind": "door"}]}],
           "paths": [{"from": [0, 55], "to": [0, 12], "w": 6}], "spawn": [0, 50], "focal": [{"id": "f", "at": [0, 0]}]}
    spec, _ = scene.normalize(raw)
    out, _log = art.apply_all(spec, "Snowy winter cabin at night with lanterns")
    assert out["preset"] == "moonlit_night_exterior"
    assert any(p["why"] == "path light at night" for p in out["props"])
    compiled = scene.compile_spec(out)
    assert compiled["preset"] == "moonlit_night_exterior"
    assert any(p.get("kit") == "room" and p.get("sem") == "glass" and p.get("light") for p in compiled["parts"])


def test_water_sits_above_a_part_ground():
    spec, _ = _spec(props=[["water", 20, 20, 0, {"w": 10, "d": 10}]])
    parts = scene.compile_spec(spec)["parts"]
    top = max(aabb(p)[1][1] for p in parts if p.get("prop") == 0)
    assert top > 0.0


def test_camera_candidates_cover_every_shot_and_picker_luau_is_bounded():
    spec, _ = _spec(props=[["table", 0, -8], ["chair", 2, -8]])
    compiled = scene.compile_spec(spec)
    cands = compiled["candidates"]
    assert set(cands) == {"hero", "wide", "detail", "overview"} and all(cands.values())
    code = luau.pick_cameras_luau("T", cands, (6000, 200, 6000))
    assert "workspace:Raycast" in code and "GetPartBoundsInRadius" in code and len(code) < 60000
    with pytest.raises(ValueError):
        luau.pick_cameras_luau("T", {"bad id!": cands["hero"]}, (0, 0, 0))
