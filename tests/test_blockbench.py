import base64
import copy
import io
import json
import random

import pytest
from PIL import Image

from star.blockbench import build as B
from star.blockbench import checks as C
from star.blockbench import pipeline as PL
from star.blockbench import render as R
from star.blockbench import spec as S
from star.blockbench.palette import ramp

LANTERN = {"name": "Copper Lantern", "category": "block", "density": 2,
           "materials": {"frame": {"kind": "metal", "color": "#b8693e"}, "glass": {"kind": "glass", "color": "#d6eef2"},
                         "cap": {"kind": "metal", "color": "#7a4a30"}},
           "parts": [{"name": "base", "from": [-4, 0, -4], "to": [4, 1.5, 4], "material": "cap"},
                     {"name": "glass", "from": [-3, 1.5, -3], "to": [3, 8.5, 3], "material": "glass"},
                     {"name": "top", "from": [-4, 8.5, -4], "to": [4, 10, 4], "material": "cap"},
                     {"name": "handle", "from": [-0.5, 10, -2], "to": [0.5, 13, 2], "material": "frame",
                      "rotation": [0, 30, 10]}]}

BOAR = {"name": "boar", "category": "mob",
        "materials": {"hide": {"kind": "fur", "color": "#8a6a4a"}, "snout": {"kind": "skin", "color": "#c79a7a"}},
        "parts": [{"name": "body", "from": [-5, 6, -8], "to": [5, 14, 8], "pivot": [0, 10, 0], "material": "hide"},
                  {"name": "head", "parent": "body", "from": [-4, 7, -14], "to": [4, 14, -8], "pivot": [0, 10, -8],
                   "material": "hide", "decals": [{"face": "north", "kind": "eyes"}]},
                  {"name": "leg_l", "parent": "body", "from": [2, 0, -7], "to": [5, 6, -4], "pivot": [3.5, 6, -5.5],
                   "rotation": [10, 20, 0], "material": "hide"},
                  {"name": "leg_r", "parent": "body", "from": [-5, 0, -7], "to": [-2, 6, -4], "pivot": [-3.5, 6, -5.5],
                   "material": "hide", "mirror_of": "leg_l"}],
        "animations": [{"name": "walk", "length": 1, "bones": {
            "leg_l": {"rotation": {"0": [0, 0, 0], "0.5": [30, 0, 0], "1": [0, 0, 0]},
                      "position": {"0": [1, 2, 3]}}}}]}


def _built(sp):
    n, fixes = S.normalize(sp)
    return n, fixes, B.build(n)


def test_normalize_fixes_and_java_rules():
    n, fixes, _ = _built(LANTERN)
    assert n["name"] == "copper_lantern"
    handle = next(p for p in n["parts"] if p["name"] == "handle")
    assert handle["rotation"] == [0, 22.5, 0]  # one axis kept, snapped to 22.5
    assert any("one rotation axis" in f for f in fixes)
    sp = copy.deepcopy(LANTERN)
    sp["parts"][0]["to"] = [40, 1, 4]
    with pytest.raises(S.SpecError):
        S.normalize(sp)


def test_normalize_grounds_mobs_and_breaks_cycles():
    sp = copy.deepcopy(BOAR)
    for p in sp["parts"]:
        p["from"][1] += 3
        p["to"][1] += 3
    sp["parts"][0]["parent"] = "head"  # body <-> head cycle
    n, fixes = S.normalize(sp)
    assert min(p["from"][1] for p in n["parts"]) == 0
    assert any("cycle" in f for f in fixes)


def test_java_model_matches_spec_and_uv_in_range():
    n, _, b = _built(LANTERN)
    jm = b["java_model"]
    assert jm["elements"][0]["from"] == [4, 0, 4] and jm["elements"][0]["to"] == [12, 1.5, 12]
    for el in jm["elements"]:
        for f in el["faces"].values():
            assert all(0 <= c <= 16 for c in f["uv"])
    assert jm["elements"][3]["rotation"] == {"angle": 22.5, "axis": "y", "origin": [8, 11.5, 8]}


def test_bedrock_conventions_match_blockbench():
    n, _, b = _built(BOAR)
    bones = {x["name"]: x for x in b["bedrock_geometry"]["minecraft:geometry"][0]["bones"]}
    leg = bones["leg_l"]
    assert leg["cubes"][0]["origin"] == [-5, 0, -7]  # x mirrored like Blockbench 5.2.2
    assert leg["pivot"] == [-3.5, 6, -5.5]
    assert leg["rotation"] == [-10, -20, 0]
    assert leg["parent"] == "body"
    up = leg["cubes"][0]["uv"]["up"]
    assert up["uv_size"][0] < 0 and up["uv_size"][1] < 0
    anim = b["bedrock_animation"]["animations"]["animation.boar.walk"]
    assert anim["bones"]["leg_l"]["rotation"]["0.5"] == [-30, 0, 0]
    assert anim["bones"]["leg_l"]["position"]["0.0"] == [-1, 2, 3]
    bb = b["bbmodel"]
    assert bb["meta"]["model_format"] == "bedrock" and len(bb["groups"]) == 4
    assert bb["animations"][0]["animators"]


def test_build_is_deterministic():
    assert _built(BOAR)[2]["texture_png"] == _built(BOAR)[2]["texture_png"]


def test_ramp_is_hue_shifted_and_ordered():
    r = ramp("#8a6a4a")
    lum = [0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] for c in r]
    assert lum == sorted(lum)
    assert r[3][:3] == (0x8a, 0x6a, 0x4a)
    import colorsys
    hue = [colorsys.rgb_to_hsv(*(v / 255 for v in c[:3]))[0] for c in r]
    assert abs(hue[0] - hue[3]) > 0.02 and abs(hue[5] - hue[3]) > 0.01  # shadows and highlights shift hue


def test_checks_clean_model_scores_high():
    _, _, b = _built(BOAR)
    rep = C.check(b["bbmodel"])
    assert rep["score"] >= 90, rep["findings"]
    assert rep["stats"]["texel_density"] == 1.0


def test_checks_find_zfight_floating_density_noise():
    sp = copy.deepcopy(BOAR)
    sp["parts"].append({"name": "plate", "from": [-5, 14, -8], "to": [5, 15, 8], "material": "snout"})
    sp["parts"].append({"name": "cap", "from": [-5, 14, -8], "to": [5, 16, 8], "material": "snout"})  # shares plane with plate
    sp["parts"].append({"name": "orb", "from": [10, 20, 10], "to": [12, 22, 12], "material": "snout"})
    _, _, b = _built(sp)
    bb = b["bbmodel"]
    codes = {f["code"] for f in C.check(bb)["findings"]}
    assert {"z-fighting", "floating-parts"} <= codes
    # stretch one face's UV -> mixed density; noisy texture -> noise + palette
    bad = copy.deepcopy(bb)
    for el in bad["elements"]:
        u = el["faces"]["north"]["uv"]
        el["faces"]["north"]["uv"] = [u[0], u[1], u[0] + 1, u[1] + 1]
    img = Image.new("RGBA", (64, 64))
    rnd = random.Random(1)
    for y in range(64):
        for x in range(64):
            img.putpixel((x, y), (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    bad["textures"][0]["source"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    codes = {f["code"] for f in C.check(bad)["findings"]}
    assert {"mixed-texel-density", "texture-noise", "palette-too-large"} <= codes


def test_box_uv_layout_matches_blockbench_probe():
    el = {"from": [0, 0, 0], "to": [3, 5, 7], "uv_offset": [2, 4], "box_uv": True}
    f = R.box_uv_faces(el)
    assert f == {"north": [9, 11, 12, 16], "east": [2, 11, 9, 16], "south": [19, 11, 22, 16],
                 "west": [12, 11, 19, 16], "up": [12, 11, 9, 4], "down": [15, 4, 12, 11]}
    m = R.box_uv_faces(dict(el, mirror_uv=True))
    assert m["east"] == [19, 11, 12, 16] and m["west"] == [9, 11, 2, 16] and m["up"] == [9, 11, 12, 4]


def test_render_draws_model_and_animation_pose():
    _, _, b = _built(BOAR)
    img = R.render(b["bbmodel"], "front_left", size=128)
    bg = R.BG
    assert sum(1 for y in range(128) for x in range(128) if img.getpixel((x, y)) != bg) > 2000
    a = R.render(b["bbmodel"], "side", size=128, anim="walk", time=0.0)
    c = R.render(b["bbmodel"], "side", size=128, anim="walk", time=0.5)
    assert a.tobytes() != c.tobytes()


def test_write_outputs_resource_pack_passes_audit(tmp_path):
    from star import minecraft_assets
    n, _, b = _built(LANTERN)
    paths = B.write_outputs(n, b, tmp_path / "out")
    entries = {}
    root = tmp_path / "out" / "resourcepack"
    for p in root.rglob("*"):
        if p.is_file():
            entries[p.relative_to(root).as_posix()] = p.read_bytes()
    findings = []
    minecraft_assets._check_pack(entries, findings, "26.3")
    assert not [f for f in findings if f["severity"] == "error"], findings
    assert json.loads((tmp_path / "out" / "copper_lantern.bbmodel").read_text())["meta"]["format_version"] == "5.0"
    assert set(paths) >= {"bbmodel", "texture", "java_model", "resourcepack"}


def test_extract_json_handles_fences_and_trailing_commas():
    assert PL.extract_json('```json\n{"a": [1, 2,], "b": "}"}\n```') == {"a": [1, 2], "b": "}"}


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat(self, messages, **kw):
        self.calls += 1
        return self.replies.pop(0), 0.01, {}


def test_pipeline_loop_keeps_best_round(tmp_path):
    worse = copy.deepcopy(BOAR)
    worse["parts"].append({"name": "orb", "from": [10, 20, 10], "to": [12, 22, 12], "material": "snout"})
    planner = FakeLLM([json.dumps(worse), json.dumps(BOAR)])
    critic = FakeLLM([json.dumps({"scores": {"overall": 4}, "issues": [{"part": "orb", "problem": "floats", "fix": "remove"}]}),
                      json.dumps({"scores": {"overall": 7}, "issues": []})])
    rep = PL.run("a boar", category="mob", rounds=1, planner=planner, critic=critic, out_dir=tmp_path)
    assert rep["best_round"] == 1
    assert rep["rounds"][0]["checks"] < rep["rounds"][1]["checks"]
    assert (tmp_path / "final" / "boar.bbmodel").exists()
    assert (tmp_path / "round0" / "boar_views.png").exists()
