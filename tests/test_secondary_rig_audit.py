"""New fixture-only tests. These are not native Blender or Roblox test receipts."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("secondary_rig_audit", ROOT / "scripts" / "secondary_rig_audit.py")
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def sample():
    return {"bones": [{"name": "Root", "parent": None, "length": 1},
                      {"name": "Tip", "parent": "Root", "length": 0.5}],
            "vertices": [{"Root": 1}, {"Root": 0.25, "Tip": 0.75}], "scale": [1, 1, 1]}


def test_good_snapshot_is_unchanged_and_never_native():
    s = sample(); before = copy.deepcopy(s)
    r = MOD.audit(s)
    assert r["structural_ok"] and not r["native_motion_tested"] and not r["visual_quality_verified"]
    assert not r["modified"] and s == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0, True, "1", 10**400])
def test_degenerate_lengths(value):
    s = sample(); s["bones"][1]["length"] = value
    assert not MOD.audit(s)["structural_ok"]


def test_cycle_detected_without_recursion():
    s = sample(); s["bones"][0]["parent"] = "Tip"
    r = MOD.audit(s)
    assert any(f["code"] == "parent_cycle" for f in r["findings"])


def test_missing_parent():
    s = sample(); s["bones"][1]["parent"] = "Absent"
    assert not MOD.audit(s)["structural_ok"]


def test_duplicate_bone():
    s = sample(); s["bones"].append(dict(s["bones"][0]))
    assert not MOD.audit(s)["structural_ok"]


@pytest.mark.parametrize("weights", [{}, {"Ghost": 1}, {"Root": float("nan")}, {"Root": -0.1}, {"Root": True}, {"Root": 10**400}])
def test_invalid_weights(weights):
    s = sample(); s["vertices"][0] = weights
    assert not MOD.audit(s)["structural_ok"]


def test_influence_budget_is_explicit():
    s = sample()
    assert not MOD.audit(s, max_influences=1)["structural_ok"]
    assert MOD.audit(s, max_influences=2)["structural_ok"]


def test_nonunit_weight_sum_needs_review():
    s = sample(); s["vertices"][0] = {"Root": 0.5}
    r = MOD.audit(s)
    assert r["structural_ok"] and r["counts"]["unnormalized"] == 1


@pytest.mark.parametrize("scale", [[0,1,1], [-1,1,1]])
def test_nonpositive_scale_blocks(scale):
    s = sample(); s["scale"] = scale
    assert not MOD.audit(s)["structural_ok"]


def test_nonunit_scale_is_review_not_repaired():
    s = sample(); s["scale"] = [2,1,1]
    r = MOD.audit(s)
    assert any(f["code"] == "unapplied_scale_review" for f in r["findings"])
    assert s["scale"] == [2,1,1]


@pytest.mark.parametrize("s", [None, {}, {"bones": [], "vertices": [], "scale": [1,1,1]}])
def test_bad_shapes(s):
    with pytest.raises(ValueError): MOD.audit(s)


def test_empty_mesh_is_not_success():
    s = sample(); s["vertices"] = []
    assert not MOD.audit(s)["structural_ok"]


def test_findings_cap_cannot_hide_failures():
    s = sample(); s["vertices"] = [{} for _ in range(300)]
    r = MOD.audit(s)
    assert len(r["findings"]) == 200 and r["findings_capped"]
    assert r["errors"] == 300 and not r["structural_ok"]


def test_budgets():
    s = sample(); s["bones"] *= 257
    with pytest.raises(ValueError): MOD.audit(s)
    s = sample(); s["vertices"] = [{}] * 100001
    with pytest.raises(ValueError): MOD.audit(s)
    with pytest.raises(ValueError): MOD.audit(sample(), max_influences=True)


def test_cli_reads_only_selected_snapshot(tmp_path, capsys):
    path = tmp_path / "rig.json"; path.write_text(json.dumps(sample()))
    before = path.read_bytes()
    assert MOD.main(["--snapshot", str(path)]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["source"] == "untrusted_snapshot" and not r["native_motion_tested"]
    assert path.read_bytes() == before


def test_invalid_scale_rejects_nan_and_huge_integer():
    for value in [float("nan"), 10**400]:
        s = sample(); s["scale"][0] = value
        with pytest.raises(ValueError): MOD.audit(s)
