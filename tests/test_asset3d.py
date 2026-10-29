"""Pure-Python tests for the 3D asset pipeline (spec, layout, patching, QA notes). Blender is not needed."""
import json
from pathlib import Path

import pytest

from star.asset3d import author, critic, spec as S
from star.asset3d.llm import extract_json


def _box(id_, size, **kw):
    return {"id": id_, "type": "box", "size": size, **kw}


def test_validate_rejects_self_crossing_profile():
    bad = {"category": "weapon", "style": "pbr", "dims": [1, 1, 1],
           "parts": [{"id": "p", "type": "profile", "thickness": 0.1,
                      "points": [[0, 0], [2, 0], [2, 2], [1, -1], [0, 2]]}]}
    with pytest.raises(S.SpecError, match="cross"):
        S.validate(bad)


def test_unknown_material_falls_back_and_bad_colour_rejected():
    sp = S.validate({"parts": [_box("a", [1, 1, 1], mat="unobtainium")]})
    assert sp["parts"][0]["mat"] == "plastic"
    with pytest.raises(S.SpecError):
        S.validate({"parts": [_box("a", [1, 1, 1], color="red")]})


def test_attach_places_child_flush_on_parent_face():
    raw = {"parts": [_box("body", [1.0, 0.4, 0.2]),
                     _box("top", [0.2, 0.2, 0.1], attach={"to": "body", "side": "top", "u": 1, "sink": 0}),
                     _box("nose", [0.3, 0.2, 0.2], attach={"to": "body", "side": "front", "sink": 0})]}
    sp = S.prepare(raw)
    top = next(p for p in sp["parts"] if p["id"] == "top")
    nose = next(p for p in sp["parts"] if p["id"] == "nose")
    assert top["pos"][2] == pytest.approx(0.1 + 0.05)      # sits on the top face
    assert top["pos"][0] == pytest.approx(0.5 - 0.1)       # u = 1: flush with the front edge
    assert nose["pos"][0] == pytest.approx(0.5 + 0.15)     # in front of the body


def test_attach_default_sink_overlaps_parent():
    raw = {"parts": [_box("body", [1, 1, 1]), _box("c", [0.2, 0.2, 0.2], attach={"to": "body", "side": "left"})]}
    c = S.prepare(raw)["parts"][1]
    assert 0.5 < c["pos"][1] < 0.6  # overlaps a little, never floats


def test_mirror_and_array_expand():
    raw = {"parts": [_box("body", [1, 1, 1]),
                     _box("bolt", [0.05, 0.05, 0.05], count=3, step=[0.1, 0, 0], mirror_y=True,
                          attach={"to": "body", "side": "left"})]}
    sp = S.prepare(raw)
    ids = [p["id"] for p in sp["parts"]]
    assert len(ids) == 7 and "bolt_2" in ids and "bolt_2_m" in ids
    b2, b2m = (next(p for p in sp["parts"] if p["id"] == i) for i in ("bolt_2", "bolt_2_m"))
    assert b2m["pos"][1] == pytest.approx(-b2["pos"][1])


def test_side_relative_cut_sits_on_face():
    raw = {"parts": [_box("body", [1, 1, 1], cuts=[{"shape": "box", "size": [0.1, 0.1, 0.2], "side": "top"}])]}
    c = S.prepare(raw)["parts"][0]["cuts"][0]
    assert c["pos"][2] == pytest.approx(0.5)  # half in, half out


def test_ground_puts_lowest_point_at_zero():
    sp = S.ground(S.prepare({"parts": [_box("a", [1, 1, 2], pos=[3, 3, 3])]}))
    assert sp["parts"][0]["pos"] == pytest.approx([0, 0, 1])


def test_lathe_points_are_along_then_radius():
    p = S.validate({"parts": [{"id": "l", "type": "lathe", "axis": "x", "points": [[-0.3, 0.01], [0.3, 0.012]]}]})
    lo, hi = S.local_aabb(p["parts"][0])
    assert hi[0] - lo[0] == pytest.approx(0.6) and hi[1] == pytest.approx(0.012)


def test_patch_edit_add_remove():
    raw = {"parts": [_box("a", [1, 1, 1]), _box("b", [1, 1, 1])]}
    out = author.apply_patch(raw, {"edit": [{"id": "a", "set": {"size": [2, 2, 2]}}], "remove": ["b"],
                                   "add": [_box("c", [1, 1, 1])]})
    assert [p["id"] for p in out["parts"]] == ["a", "c"] and out["parts"][0]["size"] == [2, 2, 2]
    assert raw["parts"][0]["size"] == [1, 1, 1]  # original untouched


def test_example_prepares():
    sp = S.prepare(author.EXAMPLE)
    assert len(sp["parts"]) == 5


def test_extract_json_tolerates_fences():
    assert extract_json('Sure:\n```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}


def test_qa_notes_flags_floating_budget_and_size():
    sp = S.validate({"category": "prop", "style": "roblox", "dims": [1, 1, 1], "parts": [_box("a", [1, 1, 1])]})
    m = {"contact": {"floating_parts": ["x"]}, "qa": {"tris": 25000}, "dims": [9, 1, 1]}
    notes, pen = critic.qa_notes(m, sp)
    text = " ".join(notes)
    assert "floating" in text and "triangles" in text and "Roblox mesh limit" in text and "outside" in text
    assert pen >= 4


def test_eval_briefs_cover_categories_and_styles():
    d = json.loads((Path(S.__file__).parent / "eval_briefs.json").read_text(encoding="utf-8"))
    held = d["heldout"]
    assert len(held) >= 15
    assert {b["category"] for b in held} == set(S.CATEGORIES)
    assert {b["style"] for b in held} == set(S.STYLES)
    assert not {b["id"] for b in held} & {b["id"] for b in d["dev"]}
