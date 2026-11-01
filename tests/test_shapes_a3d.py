"""3D part templates (star/shapes/a3d.py): every template x style builds a valid, grounded, attached spec for any
planner answer. Pure Python: no Blender, no network."""
import random

import pytest

from star.asset3d import spec as A
from star.shapes import a3d, core

NAMES = list(a3d.TEMPLATES)
STYLES = A.STYLES


def _world_boxes(sp):
    out = []
    for p in sp["parts"]:
        lo, hi = A.local_aabb(p)
        out.append(([p["pos"][i] + lo[i] for i in range(3)], [p["pos"][i] + hi[i] for i in range(3)]))
    return out


def _touch(a, b, tol):
    return all(a[0][i] <= b[1][i] + tol and b[0][i] <= a[1][i] + tol for i in range(3))


def _components(boxes, tol=0.001):
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if _touch(boxes[i], boxes[j], tol):
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(boxes))})


def _check(raw, t, style):
    assert raw["category"] == t.category
    assert raw["style"] == style
    sp = A.ground(A.prepare(raw))
    n = len(sp["parts"])
    assert 1 <= len(raw["parts"]) <= A.MAX_PARTS and n <= A.MAX_PARTS, n
    ids = [p["id"] for p in sp["parts"]]
    assert len(ids) == len(set(ids))
    boxes = _world_boxes(sp)
    lo = [min(b[0][i] for b in boxes) for i in range(3)]
    hi = [max(b[1][i] for b in boxes) for i in range(3)]
    assert abs(lo[2]) < 1e-6
    dims = [hi[i] - lo[i] for i in range(3)]
    rlo, rhi = A.SIZE_RANGE[t.category]
    assert rlo <= max(dims) <= rhi, (t.name, dims)
    if t.category in ("weapon", "vehicle"):
        assert dims[0] >= 0.95 * max(dims[1], dims[2]), (t.name, dims)
    floating = [ids[i] for i, b in enumerate(boxes) if not any(_touch(b, c, 0.001) for j, c in enumerate(boxes) if j != i)]
    assert not floating, (t.name, floating)
    assert _components(boxes) == 1, t.name
    if style in ("lowpoly", "roblox"):
        assert not any(p["cuts"] for p in sp["parts"]), "no booleans in lowpoly/roblox"
    if style == "lowpoly":
        assert not any(p["seams"] for p in sp["parts"])
    assert all(p["type"] != "lathe" or not p["cuts"] for p in sp["parts"]), "booleans on lathes break the bake"
    return sp


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("name", NAMES)
def test_defaults_and_every_variant(name, style):
    t = a3d.TEMPLATES[name]
    raw, notes = a3d.build_spec(name, None, style)
    _check(raw, t, style)
    assert notes == []
    var = t.params.get("variant")
    for v in var.choices if var else ():
        raw, _ = a3d.build_spec(name, {"params": {"variant": v}}, style)
        _check(raw, t, style)


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("name", NAMES)
def test_extreme_params(name, style):
    t = a3d.TEMPLATES[name]
    var = t.params.get("variant")
    for v in var.choices if var else (None,):
        for end in ("lo", "hi"):
            params = {k: (p.lo if end == "lo" else p.hi) for k, p in t.params.items() if p.kind in ("num", "int")}
            params.update({k: end == "hi" for k, p in t.params.items() if p.kind == "bool"})
            if v:
                params["variant"] = v
            raw, _ = a3d.build_spec(name, {"params": params}, style)
            _check(raw, t, style)


def _random_answer(t, rng):
    params = {}
    for k, p in t.params.items():
        roll = rng.random()
        if roll < 0.1:
            params[k] = rng.choice(["", "lots", None, [], {}, "NaN", float("nan"), -1e9, 1e9, True])
        elif p.kind == "enum":
            params[k] = rng.choice(p.choices + ("Something Else",))
        elif p.kind == "bool":
            params[k] = rng.choice([True, False, "yes", "no", 0, 1])
        else:
            span = p.hi - p.lo
            params[k] = rng.uniform(p.lo - span, p.hi + span)
    colors = {r: rng.choice(["#a0b0c0", "a0b0c0", "red", 7, "#zzzzzz"]) for r in t.roles}
    kinds = {r: rng.choice(a3d.KINDS + ("unobtainium",)) for r in t.roles}
    return {"name": "x", "params": params, "colors": colors, "kinds": kinds}


@pytest.mark.parametrize("name", NAMES)
def test_random_and_garbage_answers(name):
    t = a3d.TEMPLATES[name]
    rng = random.Random(name)
    for i in range(24):
        style = STYLES[i % len(STYLES)]
        raw, _ = a3d.build_spec(name, _random_answer(t, rng), style)
        _check(raw, t, style)
    for junk in (None, "text", 5, [], {"params": "bad"}, {"params": None, "colors": "x", "kinds": []}):
        raw, _ = a3d.build_spec(name, junk, "pbr")
        _check(raw, t, "pbr")


@pytest.mark.parametrize("name", NAMES)
def test_template_metadata(name):
    t = a3d.TEMPLATES[name]
    assert t.name == name and t.category in A.CATEGORIES
    assert "\n" not in t.summary and len(t.summary) <= 110
    assert 3 <= len(t.roles) <= 6 and 3 <= len(t.params) <= 14
    assert all(r.kind in a3d.KINDS and core._HEX.match(r.color) for r in t.roles.values())
    for p in t.params.values():
        assert p.coerce(None) == p.default
        if p.kind == "enum":
            assert p.default in p.choices
        if p.kind in ("num", "int"):
            assert p.lo <= p.default <= p.hi
    assert t.keywords
    msgs = core.fill_prompt(t, "a brief", a3d.KINDS)
    assert len(msgs[0]["content"]) < 4000  # ~1k tokens: leaves room in a 4096-token context


def test_pick_prompt_is_small_and_keywords_route():
    msgs = core.pick_prompt(a3d.TEMPLATES, "a brief")
    assert len(msgs[0]["content"]) < 2500
    assert core.pick_by_keywords(a3d.TEMPLATES, "Realistic assault rifle with a rail handguard") == "firearm"
    assert core.pick_by_keywords(a3d.TEMPLATES, "Low-poly wooden barrel with iron hoops") == "barrel"
    assert core.pick_by_keywords(a3d.TEMPLATES, "office desk with two drawers and a desk lamp") == "table"
    assert core.pick_by_keywords(a3d.TEMPLATES, "a glowing alien obelisk") == "box_prop"


def test_colours_and_kinds_reach_the_parts():
    ans = {"params": {"variant": "car"}, "colors": {"body": "#123456", "tire": "#0f0f0f"},
           "kinds": {"body": "anodized", "rim": "gold"}}
    raw, notes = a3d.build_spec("vehicle", ans, "pbr")
    mats = {(p["mat"], p["color"]) for p in raw["parts"]}
    assert ("anodized", "#123456") in mats and ("gold", "#a9adb3") in mats
    assert any(p["color"] == "#0f0f0f" and p["mat"] == "rubber" for p in raw["parts"])
    assert notes == []


def test_variant_defaults_only_replace_untouched_roles():
    raw, _ = a3d.build_spec("firearm", {"params": {"variant": "rifle"}}, "pbr")
    assert any(p["id"] == "stock" and p["mat"] == "wood" for p in raw["parts"])
    raw, _ = a3d.build_spec("firearm", {"params": {"variant": "rifle"}, "kinds": {"furniture": "polymer"},
                                        "colors": {"furniture": "#222222"}}, "pbr")
    assert any(p["id"] == "stock" and p["mat"] == "polymer" and p["color"] == "#222222" for p in raw["parts"])


def test_build_spec_notes_category_and_fallback():
    raw, notes = a3d.build_spec("crate", {"params": {"length": 9, "bogus": 1}, "name": "Big Crate"}, "roblox",
                                category="furniture")
    assert raw["category"] == "furniture" and raw["name"] == "Big Crate"
    assert any("length" in n for n in notes) and any("bogus" in n for n in notes)
    raw, _ = a3d.build_spec("no_such_template", None, "weird_style")
    assert raw["style"] == "pbr" and raw["category"] == "prop"


def test_styles_differ_in_detail():
    for name in NAMES:
        n = {s: len(A.prepare(a3d.build_spec(name, None, s)[0])["parts"]) for s in STYLES}
        assert n["lowpoly"] <= n["pbr"], (name, n)
        assert n["lowpoly"] >= 5, (name, n)


def test_chest_lid_opens_about_the_back_hinge():
    closed = A.ground(A.prepare(a3d.build_spec("chest", {"params": {"lid_open": 0}}, "pbr")[0]))
    opened = A.ground(A.prepare(a3d.build_spec("chest", {"params": {"lid_open": 80}}, "pbr")[0]))
    hc = max(b[1][2] for b in _world_boxes(closed))
    ho = max(b[1][2] for b in _world_boxes(opened))
    assert ho > hc + 0.1
    assert any(p["id"] == "gold" for p in opened["parts"]) and not any(p["id"] == "gold" for p in closed["parts"])
