"""Offline proof of STAR's read-only visual and gameplay quality gate."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from star.starry_eye_quality import audit, concept_similarity, rank_concepts
from star.workspace import Workspace


def _setup(tmp_path: Path, *, trace: bool = True) -> tuple[Workspace, dict]:
    (tmp_path / "app.luau").write_text("local App = {}\nreturn App\n", encoding="utf-8")
    canvas = Image.new("RGB", (320, 240), "#151a25")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((20, 40, 150, 80), fill="#776600")
    draw.line((0, 180, 320, 110), fill="#4455aa", width=9)
    canvas.save(tmp_path / "desktop.png")
    canvas.copy().save(tmp_path / "after.png")
    manifest = {
        "project": "ObbyGame", "artifact": "main-menu", "source": "app.luau",
        "views": {
            "desktop": {"file": "desktop.png", "width": 320, "height": 240},
            "after": {"file": "after.png", "width": 320, "height": 240},
        },
        "layout": {"desktop": [
            {"id": "Play", "rect": [12, 18, 105, 52], "interactive": True,
             "foreground": "#ffffff", "background": "#151a25"},
            {"id": "Shop", "rect": [145, 18, 105, 52], "interactive": True},
        ]},
        "expect_events": [{"name": "goal_reached"}],
        "budgets": {"p95_frame_ms": {"max": 33.3}},
    }
    if trace:
        trace_data = {"engine": "roblox", "run_finished": True,
                      "events": [{"name": "spawn", "t_ms": 0},
                                 {"name": "goal_reached", "t_ms": 4000}],
                      "metrics": {"p95_frame_ms": 16.4}}
        (tmp_path / "trace.json").write_text(json.dumps(trace_data), encoding="utf-8")
        manifest["trace_file"] = "trace.json"
    return Workspace(tmp_path), manifest


def _save(tmp_path: Path, manifest: dict) -> str:
    (tmp_path / "quality.json").write_text(json.dumps(manifest), encoding="utf-8")
    return "quality.json"


def test_real_screenshots_layout_and_completed_trace_pass_but_never_approve(tmp_path):
    work, manifest = _setup(tmp_path)
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "automated_checks_passed"
    assert result["failed_count"] == result["unverified_count"] == 0
    assert result["automated_check_count"] >= 7
    assert not result["owner_approved"]
    assert not result["runtime_executed_by_this_tool"]
    assert len(result["evidence_key"]) == len(result["trace_sha256"]) == 64


def test_exposed_as_read_only_star_agent_workspace_tool(tmp_path):
    work, manifest = _setup(tmp_path)
    assert work.call("workspace_starry_eye_audit", {"path": _save(tmp_path, manifest)})["status"] == "automated_checks_passed"


def test_missing_trace_is_not_mistaken_for_test_success(tmp_path):
    work, manifest = _setup(tmp_path, trace=False)
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "insufficient_evidence"
    assert result["unverified_count"] == 2
    assert {"event_unverified", "metric_unverified"} <= {f["code"] for f in result["findings"]}


def test_incomplete_trace_is_not_positive_evidence(tmp_path):
    work, manifest = _setup(tmp_path)
    path = tmp_path / "trace.json"
    content = json.loads(path.read_text())
    content["run_finished"] = False
    path.write_text(json.dumps(content))
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "insufficient_evidence"


def test_missing_goal_and_bad_frame_budget_fail(tmp_path):
    work, manifest = _setup(tmp_path)
    path = tmp_path / "trace.json"
    content = json.loads(path.read_text())
    content["events"].pop()
    content["metrics"]["p95_frame_ms"] = 99.5
    path.write_text(json.dumps(content))
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "automated_checks_failed"
    assert {"event_missing", "budget_exceeded"} <= {f["code"] for f in result["findings"]}


def test_viewport_clipping_small_buttons_overlap_and_low_contrast(tmp_path):
    work, manifest = _setup(tmp_path)
    manifest["layout"] = {"desktop": [
        {"id": "Play", "rect": [-4, 0, 20, 18], "interactive": True,
         "foreground": "#151a25", "background": "#171b27"},
        {"id": "Shop", "rect": [2, 3, 30, 18], "interactive": True},
    ]}
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "automated_checks_failed"
    assert {"ui_clipped", "tiny_hit_target", "ui_hit_target_overlap", "low_text_contrast"} <= {
        f["code"] for f in result["findings"]}


def test_declared_intentional_overlap_is_not_flagged(tmp_path):
    work, manifest = _setup(tmp_path)
    manifest["layout"] = {"desktop": [
        {"id": "A", "rect": [10, 10, 90, 50], "interactive": True, "allow_overlap_with": ["B"]},
        {"id": "B", "rect": [30, 20, 90, 50], "interactive": True},
    ]}
    result = audit(work, _save(tmp_path, manifest))
    assert not any(f["code"] == "ui_hit_target_overlap" for f in result["findings"])


def test_motion_does_not_claim_animation_from_unchanged_frames(tmp_path):
    work, manifest = _setup(tmp_path)
    manifest["motion"] = [{"from": "desktop", "to": "after", "expected": "moving", "threshold": 0.01}]
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "automated_checks_failed"
    assert any(f["code"] == "frozen_frames" for f in result["findings"])


def test_motion_detects_pixel_change_not_perceptual_quality(tmp_path):
    work, manifest = _setup(tmp_path)
    image = Image.open(tmp_path / "after.png")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 70, 160, 100), fill="white")
    image.save(tmp_path / "after.png")
    manifest["motion"] = [{"from": "desktop", "to": "after", "expected": "moving"}]
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "automated_checks_passed"
    assert not any(f["code"] == "frozen_frames" for f in result["findings"])


def test_expected_static_frame_change_is_caught(tmp_path):
    work, manifest = _setup(tmp_path)
    Image.new("RGB", (320, 240), "white").save(tmp_path / "after.png")
    manifest["motion"] = [{"from": "desktop", "to": "after", "expected": "static"}]
    result = audit(work, _save(tmp_path, manifest))
    assert any(f["code"] == "unexpected_frame_change" for f in result["findings"])


def test_uniform_frame_is_a_review_warning_not_artistic_rejection(tmp_path):
    work, manifest = _setup(tmp_path)
    Image.new("RGB", (320, 240), "black").save(tmp_path / "after.png")
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "automated_checks_passed"
    assert any(f["code"] == "nearly_uniform_frame" and f["status"] == "review"
               for f in result["findings"])


def test_invalid_events_are_not_granted_runtime_receipt(tmp_path):
    work, manifest = _setup(tmp_path)
    path = tmp_path / "trace.json"
    record = json.loads(path.read_text())
    record["events"][1]["t_ms"] = -10
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        audit(work, _save(tmp_path, manifest))
    record["events"][1]["t_ms"] = float("nan")
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        audit(work, _save(tmp_path, manifest))


def test_unsupported_engine_rejected(tmp_path):
    work, manifest = _setup(tmp_path)
    path = tmp_path / "trace.json"
    record = json.loads(path.read_text())
    record["engine"] = "unknown_executable"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="recognized"):
        audit(work, _save(tmp_path, manifest))


def test_evidence_source_protection_uses_workspace_policy(tmp_path):
    work, manifest = _setup(tmp_path)
    (tmp_path / ".env").write_text("PRIVATE=secret")
    manifest["source"] = ".env"
    with pytest.raises(PermissionError):
        audit(work, _save(tmp_path, manifest))


def test_traversal_and_absolute_paths_refused(tmp_path):
    work, manifest = _setup(tmp_path)
    for value in ("../outside.png", "/tmp/outside.png", ".git/config"):
        manifest["views"]["desktop"]["file"] = value
        with pytest.raises((PermissionError, ValueError, FileNotFoundError)):
            audit(work, _save(tmp_path, manifest))


def test_symlink_evidence_refused_even_when_inside_workspace(tmp_path):
    work, manifest = _setup(tmp_path)
    try:
        (tmp_path / "alias.png").symlink_to(tmp_path / "desktop.png")
    except (PermissionError, OSError):
        pytest.skip("No symlink privileges")
    manifest["views"]["desktop"]["file"] = "alias.png"
    with pytest.raises(ValueError, match="symlink|ordinary"):
        audit(work, _save(tmp_path, manifest))


def test_tampered_screenshot_changes_evidence_key(tmp_path):
    work, manifest = _setup(tmp_path)
    name = _save(tmp_path, manifest)
    original = audit(work, name)["evidence_key"]
    with Image.open(tmp_path / "desktop.png") as im:
        im.putpixel((5, 5), (255, 255, 255))
        im.save(tmp_path / "desktop.png")
    assert audit(work, name)["evidence_key"] != original


def test_evidence_without_checks_is_inconclusive(tmp_path):
    work, manifest = _setup(tmp_path, trace=False)
    manifest.pop("expect_events")
    manifest.pop("budgets")
    manifest.pop("layout")
    result = audit(work, _save(tmp_path, manifest))
    assert result["status"] == "insufficient_evidence"


def _idea(genre="obby", core_loop="jump between moving platforms",
          setting="rainforest canopy", art_style="hand-painted watercolor",
          twist="gravity reverses at each checkpoint"):
    return {"genre": genre, "core_loop": core_loop, "setting": setting,
            "art_style": art_style, "twist": twist}


def test_diversity_ranker_rejects_same_game_reskinned_in_name(tmp_path):
    duplicate = _idea()
    different = _idea(core_loop="build paths from musical notes", setting="clockwork museum",
                      art_style="low resolution pixel art", twist="rhythm changes platforms")
    ranked = rank_concepts([duplicate, different], history=[_idea()], count=2, required_genre="obby")
    assert [part["index"] for part in ranked["selected"]] == [1]
    assert ranked["rejected"][0]["reason"] == "near_duplicate"
    assert not ranked["originality_proven"]


def test_shared_genre_does_not_force_duplicate_idea():
    first = _idea()
    second = _idea(core_loop="investigate disappearing trails", setting="frozen observatory",
                   art_style="monochrome ink", twist="footprints predict the future")
    assert concept_similarity(first, second) < 0.4
    assert rank_concepts([first, second], count=2)["considered"] == 2


def test_diversity_genre_constraints_and_workspace_tool(tmp_path):
    work, _ = _setup(tmp_path)
    ideas = [_idea(), _idea(genre="tycoon", core_loop="manage haunted bakery",
                              twist="customers trade secrets")]
    result = work.call("workspace_game_concept_rank", {
        "candidates": ideas, "history": [], "required_genre": "tycoon"})
    assert [r["index"] for r in result["selected"]] == [1]
    assert result["rejected"][0]["reason"] == "genre_mismatch"


@pytest.mark.parametrize("invalid", [
    {}, {"genre": 17}, {"twist": ""}, {"core_loop": "x"}, {"setting": None},
])
def test_invalid_concept_data_is_rejected(invalid):
    with pytest.raises(ValueError):
        rank_concepts([invalid])


def test_concept_caps_and_invalid_budget_types(tmp_path):
    work, manifest = _setup(tmp_path)
    with pytest.raises(ValueError):
        rank_concepts([_idea()] * 81)
    with pytest.raises(ValueError):
        rank_concepts([_idea()], count=True)
    manifest["budgets"]["p95_frame_ms"]["max"] = True
    with pytest.raises(ValueError):
        audit(work, _save(tmp_path, manifest))
