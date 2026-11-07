"""Offline recipe sampling; native Blender or Roblox results are not inferred."""
from __future__ import annotations

import asyncio
import copy

import pytest

from star.animation_regression import compare_clip_to_reference, motion_quality_report, sample_clip
from star.blender_bridge import BlenderController
from star.blender_mcp import MOTION_QA, connect_blender, make_server
from star.desktop_core import Settings


def clip(*, loop=False):
    return {
        "name": "TestWave", "rig": "r15", "fps": 30, "frame_count": 20, "loop": loop,
        "keyframes": [
            {"frame": 0, "bones": {"RightUpperArm": [0, 0, 0]}},
            {"frame": 10, "bones": {"RightUpperArm": [40, 0, 0]}},
            {"frame": 20, "bones": {"RightUpperArm": [0, 0, 0]}},
        ],
    }


def test_sampling_interpolates_and_keeps_input_untouched():
    original = clip()
    copy_before = copy.deepcopy(original)
    poses = sample_clip(original)
    assert len(poses) == 21
    assert poses[0]["RightUpperArm"] == (0, 0, 0)
    assert poses[5]["RightUpperArm"] == (20, 0, 0)
    assert poses[10]["RightUpperArm"] == (40, 0, 0)
    assert poses[15]["RightUpperArm"] == (20, 0, 0)
    assert poses[20]["RightUpperArm"] == (0, 0, 0)
    assert original == copy_before


def test_loop_tangent_and_acceleration_warning_are_evidence_not_fake_native_pass():
    report = motion_quality_report(clip(loop=True))
    assert report["sampled_frames"] == 21
    assert report["max_euler_axis_speed_deg_s"] == 120.0
    assert report["loop_tangent_gap_deg_s"] == 240.0
    assert report["max_euler_axis_acceleration_deg_s2"] > 6000
    assert any("Loop pose closes" in item for item in report["warnings"])
    assert report["native_animation_tested"] is False
    assert report["existing_preflight"]["blender_export_supported"] is True


def test_reference_comparison_observes_frame_errors_without_calling_it_quality():
    reference = clip()
    candidate = copy.deepcopy(reference)
    candidate["keyframes"][1]["bones"]["RightUpperArm"][0] += 20
    report = compare_clip_to_reference(reference, candidate, tolerance_deg=5)
    assert not report["within_authored_value_tolerance"]
    assert report["max_euler_axis_difference_deg"] == 20
    assert report["frames_outside_tolerance"] > 0
    assert report["quality_or_studio_equivalence_proven"] is False
    assert compare_clip_to_reference(reference, reference)["within_authored_value_tolerance"]
    with pytest.raises(ValueError, match="Tolerance"):
        compare_clip_to_reference(reference, reference, tolerance_deg=float("nan"))
    candidate["fps"] = 24
    with pytest.raises(ValueError, match="same rig"):
        compare_clip_to_reference(reference, candidate)



def test_motion_check_tool_is_hidden_until_blender_and_its_own_switch_are_on(tmp_path):
    for settings, offered in ((Settings(), False), (Settings(blender_motion_qa=True), False),
                              (Settings(blender_enabled=True), False),
                              (Settings(blender_enabled=True, blender_motion_qa=True), True)):
        _, catalog = make_server(BlenderController(settings=settings, home=tmp_path))
        assert (MOTION_QA in {tool["name"] for tool in catalog}) is offered
    assert Settings().blender_motion_qa is False


def test_motion_check_tool_returns_report_and_reference_comparison(tmp_path):
    import json
    settings = Settings(project="Lab", blender_enabled=True, blender_motion_qa=True)
    candidate = clip(loop=True)
    candidate["keyframes"][1]["bones"]["RightUpperArm"][0] = 80

    async def check():
        async with connect_blender(settings, tmp_path) as client:
            reply = await client.call(MOTION_QA, {"clip": candidate, "reference": clip(loop=True)})
            assert reply["isError"] is False
            report = reply.get("structuredContent") or json.loads(reply["content"][0]["text"])
            assert report["max_euler_axis_speed_deg_s"] == 240.0
            assert report["reference_comparison"]["within_authored_value_tolerance"] is False
            bad = await client.call(MOTION_QA, {"clip": candidate, "script": "print(1)"})
            assert bad["isError"] is True
    asyncio.run(check())
    assert not list(tmp_path.iterdir())
