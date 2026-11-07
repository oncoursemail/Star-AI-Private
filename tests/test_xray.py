"""X-ray Eyes (star/xray.py + star/data/xray). Lune-backed tests skip when Lune is not installed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from star import xray

FIXTURES = Path(__file__).parent / "fixtures" / "xray"
CLEAN = FIXTURES / "sample_clean.rbxlx"
DEFECTS = FIXTURES / "sample_defects.rbxlx"
MANIFEST = FIXTURES / "sample_defects.rbxlx.json"
LUNE = xray.find_lune()
needs_lune = pytest.mark.skipif(LUNE is None, reason="Lune not installed (set STAR_LUNE)")


def _finding(**over):
    base = {"detector": "near_miss_gap", "severity": "medium", "path": "Workspace.A", "partner": "Workspace.B",
            "value": 0.05, "unit": "studs", "message": "A is 0.05 studs away from B", "fix": "Move A"}
    return {**base, **over}


# --------------------------------------------------------------------------- pure Python

def test_normalize_turns_lune_empty_tables_into_lists_and_dicts():
    report = xray.normalize({"findings": {}, "changes": {}, "counts": [], "skipped": [], "ms": []})
    assert report["findings"] == [] and report["changes"] == []
    assert report["counts"] == {} and report["skipped"] == {} and report["ms"] == {}


def test_markdown_lists_findings_changes_and_skips():
    report = {"mode": "lune", "parts": 3, "total": 2, "counts": {"near_miss_gap": 1, "contrast": 1},
              "findings": [_finding(), _finding(detector="contrast", severity="high", path="StarterGui.HUD.Title",
                                                value=1.2, unit=": 1 contrast", viewport=None, message="low | contrast")],
              "changes": [{"op": "translate", "path": "Workspace.A", "dx": 0, "dy": -0.05, "dz": 0, "reason": "close near-miss gap"}],
              "skipped": {"unreachable": "Studio only"}, "textMetrics": "estimated"}
    md = xray.render_markdown(report)
    assert "**2 findings**: 1 high, 1 medium, 0 low" in md
    assert "| high | contrast | `StarterGui.HUD.Title` |" in md
    assert "low / contrast" in md  # a pipe inside a message cannot break the table
    assert "| 1 | `Workspace.A` | (0, -0.05, 0) | close near-miss gap |" in md
    assert "unreachable (Studio only)" in md and "estimated font metrics" in md


def test_fail_on_severity_threshold():
    report = xray.normalize({"findings": [_finding(severity="medium")]})
    assert xray._fails(report, "medium") and xray._fails(report, "low")
    assert not xray._fails(report, "high") and not xray._fails(report, None)


def test_find_lune_prefers_env(tmp_path, monkeypatch):
    fake = tmp_path / ("lune.exe" if xray.os.name == "nt" else "lune")
    fake.write_text("")
    monkeypatch.setenv("STAR_LUNE", str(fake))
    assert xray.find_lune() == str(fake)


def test_scan_file_refuses_wrong_type_and_overwriting_the_input(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("x")
    with pytest.raises(xray.XrayError, match="not a Roblox place"):
        xray.scan_file(other)
    with pytest.raises(xray.XrayError, match="never overwritten"):
        xray.scan_file(CLEAN, apply_to=CLEAN, lune="unused")


def test_studio_code_is_the_module_plus_a_read_only_host():
    code = xray.studio_code({"detectors": ["floating"]})
    assert code.count("\nreturn Xray") == 0  # the module's own return is replaced by the host
    assert '[==[{"maxFindings": 200, "detectors": ["floating"]}]==]' in code
    assert 'return "STAR_XRAY " .. HttpService:JSONEncode(report)' in code
    for api in ("GetTextBoundsAsync", "GetPartBoundsInBox", "PathfindingService", "CreateHumanoidModelFromDescription"):
        assert api in code
    # nothing in the host writes to the place: the only instances it makes are never parented
    host = code.split("-- STAR:xray (reads only)")[1]
    assert ".Parent =" not in host and "rig:Destroy()" in host


def test_cli_needs_a_mode(capsys):
    with pytest.raises(SystemExit):
        xray.main([])


# --------------------------------------------------------------------------- Lune (headless engine data)

@needs_lune
def test_luau_selftest_known_answers():
    result = xray.run_lune("selftest")
    failed = [r for r in result["results"] if not r["ok"]]
    assert result["ok"] and not failed, failed


@needs_lune
def test_studio_snippet_compiles(tmp_path):
    snippet = tmp_path / "snippet.luau"
    snippet.write_text(xray.studio_code(), encoding="utf-8")
    assert xray.run_lune("compile", str(snippet)) == {"ok": True}


@needs_lune
def test_clean_sample_place_has_no_findings(tmp_path):
    out = tmp_path / "r.json"
    assert xray.main(["--place", str(CLEAN), "--json", str(out), "--fail-on", "low"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["total"] == 0 and report["parts"] == 58 and report["grid"] == 1


@needs_lune
def test_saved_defect_place_every_planted_defect_found():
    plants = json.loads(MANIFEST.read_text(encoding="utf-8"))
    report = xray.scan_file(DEFECTS)
    assert len(plants) == 11
    for plant in plants:
        refs = [(f["detector"], r) for f in report["findings"]
                for r in [f["path"], f.get("partner"), *(f.get("members") or [])] if r]
        assert any(det == plant["detector"] and ref in plant["targets"] for det, ref in refs), plant
    assert report["skipped"]["unreachable"].startswith("needs PathfindingService")


@needs_lune
def test_apply_fixes_writes_a_copy_and_closes_gap_and_z_fighting(tmp_path):
    before = hashlib.sha256(DEFECTS.read_bytes()).hexdigest()
    copy = tmp_path / "fixed.rbxlx"
    report = xray.scan_file(DEFECTS, {"fixes": True}, apply_to=copy)
    assert hashlib.sha256(DEFECTS.read_bytes()).hexdigest() == before
    paths = [c["path"] for c in report["changes"]]
    assert len(paths) == len(set(paths)) and report["applied"] == len(paths)
    fixed = xray.scan_file(copy)
    plants = {p["detector"]: p["targets"][0] for p in json.loads(MANIFEST.read_text(encoding="utf-8"))}
    for detector in ("near_miss_gap", "z_fighting"):
        target = plants[detector]
        hits = [f for f in report["findings"] if f["detector"] == detector and target in (f["path"], f.get("partner"))]
        left = [f for f in fixed["findings"] if f["detector"] == detector and target in (f["path"], f.get("partner"))]
        assert hits and not left, (detector, left)


@needs_lune
def test_planted_defect_exam_recall_and_false_alarms():
    result = xray.exam(trials=40, seed=7)
    assert result["clean"]["total"] == 0
    for d in result["detectors"]:
        assert d["planted"] == 40
        assert d["recall"] >= 0.95, d
    assert result["falseAlarms"] <= 2, result["alarms"]


@needs_lune
def test_ten_thousand_parts_in_seconds():
    result = xray.run_lune("perf", "225")
    assert result["parts"] >= 10_000
    assert result["scanSeconds"] < 10, result
    assert result["total"] == 0  # 225 clean houses: still no false alarms
