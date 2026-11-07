"""Deterministic, offline animation sampling and reference comparisons for STAR.

Evaluates bounded STAR Blender-to-Roblox recipe *Euler key values*. It does not
simulate Blender interpolation, Roblox joint transforms, IK, physics or contact.
Reached through the Blender MCP tool `star_blender_animation_motion_qa` (star/blender_mcp.py).
"""
from __future__ import annotations

import math

from .blender_animation import R15_HIERARCHY, R6_JOINTS, analyze_animation, validate_animation


def sample_clip(recipe: object) -> tuple[dict[str, tuple[float, float, float]], ...]:
    """Per-frame linearly interpolated *authored* Euler joint values; no I/O."""
    clip = validate_animation(recipe)
    names = sorted(R15_HIERARCHY if clip["rig"] == "r15" else R6_JOINTS)
    current: dict[str, tuple[float, float, float]] = {key: (0.0, 0.0, 0.0) for key in names}
    keys = []
    for pose in clip["keyframes"]:
        current = dict(current)
        for name, rotations in pose["bones"].items():
            current[name] = (float(rotations[0]), float(rotations[1]), float(rotations[2]))
        keys.append((pose["frame"], current))
    samples: list[dict[str, tuple[float, float, float]]] = []
    for (frame_a, pose_a), (frame_b, pose_b) in zip(keys, keys[1:]):
        span = frame_b - frame_a
        for frame in range(frame_a, frame_b):
            alpha = (frame - frame_a) / span
            samples.append({name: tuple(a + (b - a) * alpha for a, b in zip(pose_a[name], pose_b[name]))
                            for name in names})
    samples.append(dict(keys[-1][1]))
    return tuple(samples)


def motion_quality_report(recipe: object) -> dict:
    """Flag rate/acceleration and looping *tangent* discontinuities for review."""
    clip = validate_animation(recipe)
    poses = sample_clip(clip)
    fps = clip["fps"]
    names = tuple(poses[0])
    speeds: list[float] = []
    max_speed = 0.0
    max_acceleration = 0.0
    for name in names:
        for axis in range(3):
            rates = [(poses[i][name][axis] - poses[i - 1][name][axis]) * fps
                     for i in range(1, len(poses))]
            speeds.extend(abs(rate) for rate in rates)
            max_speed = max(max_speed, *(abs(rate) for rate in rates))
            for previous, latest in zip(rates, rates[1:]):
                max_acceleration = max(max_acceleration, abs(latest - previous) * fps)
    loop_tangent_gap = 0.0
    if clip["loop"] and len(poses) >= 3:
        for name in names:
            for axis in range(3):
                outgoing = (poses[1][name][axis] - poses[0][name][axis]) * fps
                incoming = (poses[-1][name][axis] - poses[-2][name][axis]) * fps
                loop_tangent_gap = max(loop_tangent_gap, abs(outgoing - incoming))
    speeds.sort()
    p95_speed = speeds[math.ceil(.95 * len(speeds)) - 1] if speeds else 0
    warnings: list[str] = []
    if max_speed > 540:
        warnings.append("High sampled Euler-axis velocity: inspect the transition in Blender and Studio")
    if max_acceleration > 6000:
        warnings.append("Sharp Euler-axis velocity change: inspect easing and motion continuity")
    if clip["loop"] and loop_tangent_gap > 180:
        warnings.append("Loop pose closes, but incoming and outgoing Euler-axis velocities differ")
    if max_speed < .001:
        warnings.append("Clip has no sampled joint motion")
    return {
        "name": clip["name"],
        "rig": clip["rig"],
        "fps": fps,
        "sampled_frames": len(poses),
        "sampled_joint_axes": len(names) * 3,
        "max_euler_axis_speed_deg_s": round(max_speed, 2),
        "p95_euler_axis_speed_deg_s": round(p95_speed, 2),
        "max_euler_axis_acceleration_deg_s2": round(max_acceleration, 2),
        "loop_tangent_gap_deg_s": round(loop_tangent_gap, 2) if clip["loop"] else None,
        "warnings": warnings,
        "existing_preflight": analyze_animation(clip),
        "native_animation_tested": False,
        "limitations": "Authored Euler values with linear interpolation, not Roblox/Blender rendered frames, quaternions, skeletal world transforms, foot contacts, skin deformation or runtime physics. Review real frames and playtest before approval.",
    }


def compare_clip_to_reference(reference: object, candidate: object, *, tolerance_deg: float = 5.0) -> dict:
    """Compare authored motion samples against an approved reference, not taste."""
    if type(tolerance_deg) not in (int, float) or not math.isfinite(tolerance_deg) or not 0 <= tolerance_deg <= 120:
        raise ValueError("Tolerance must be a finite number in 0..120 degrees")
    a, b = validate_animation(reference), validate_animation(candidate)
    if (a["rig"], a["fps"], a["frame_count"]) != (b["rig"], b["fps"], b["frame_count"]):
        raise ValueError("Reference and candidate must have the same rig, fps and frame count")
    previous, changed = sample_clip(a), sample_clip(b)
    differences = [abs(left - right)
                   for pa, pb in zip(previous, changed)
                   for bone in pa
                   for left, right in zip(pa[bone], pb[bone])]
    frame_errors = [max(abs(left - right)
                        for bone in pa
                        for left, right in zip(pa[bone], pb[bone]))
                    for pa, pb in zip(previous, changed)]
    return {
        "reference": a["name"],
        "candidate": b["name"],
        "sampled_frames": len(previous),
        "tolerance_deg": tolerance_deg,
        "mean_euler_axis_difference_deg": round(sum(differences) / len(differences), 3),
        "max_euler_axis_difference_deg": round(max(differences), 3),
        "frames_outside_tolerance": sum(error > tolerance_deg for error in frame_errors),
        "within_authored_value_tolerance": all(error <= tolerance_deg for error in frame_errors),
        "quality_or_studio_equivalence_proven": False,
    }
