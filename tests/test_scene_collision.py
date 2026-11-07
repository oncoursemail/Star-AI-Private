"""Adversarial offline QA for Roblox rotated blockouts and bounded collision checks."""
from __future__ import annotations

import math
import random

from star.map_plan import dry_run
from star.scene_collision import from_pose, intersects


def _codes(events):
    return {event["code"] for event in events}


def _plan(*parts, spawn=(0, 0.5, 0), bounds=(200, 80, 200)):
    return {
        "mapName": "Spatial Test",
        "bounds": {"size": list(bounds)},
        "parts": [
            {"name": "Floor", "position": [0, -0.5, 0], "size": [80, 1, 80], "role": "floor"},
            *parts,
        ],
        "spawns": [{"name": "Spawn", "position": list(spawn)}],
    }


def test_oriented_axes_match_yxz_and_rotation_equivalence():
    a = from_pose((0, 0, 0), (2, 2, 20), (0, 90, 0))
    assert all(math.isclose(a.lo[i], (-10, -1, -1)[i], abs_tol=1e-10) for i in range(3))
    assert all(math.isclose(a.hi[i], (10, 1, 1)[i], abs_tol=1e-10) for i in range(3))
    assert from_pose((0, 0, 0), (2, 2, 20), (0, 450, 0)).lo == a.lo
    assert not from_pose((0, 0, 0), (1, 1, 1), (0, 360, 0)).rotated


def test_exact_rotated_collision_rejects_aabb_ghost():
    long = from_pose((0, 0, 0), (2, 2, 20), (0, 45, 0))
    ghost = from_pose((6, 0, -6), (1, 1, 1))
    assert all(min(long.hi[i], ghost.hi[i]) - max(long.lo[i], ghost.lo[i]) > .05
               for i in range(3))  # AABBs really do overlap.
    assert not intersects(long, ghost)
    actual = from_pose((6, 0, 6), (1, 1, 1))
    assert intersects(long, actual)


def test_touching_boxes_are_not_colliding_and_tolerance_is_symmetric():
    original = from_pose((0, 0, 0), (2, 2, 2))
    assert not intersects(original, from_pose((2, 0, 0), (2, 2, 2)), tolerance=0)
    assert not intersects(original, from_pose((1.97, 0, 0), (2, 2, 2)))
    assert intersects(original, from_pose((1.80, 0, 0), (2, 2, 2)))


def test_sat_symmetry_for_randomized_3d_orientations():
    rng = random.Random(20261027)
    for _ in range(150):
        p = tuple(rng.uniform(-6, 6) for _ in range(3))
        q = tuple(rng.uniform(-6, 6) for _ in range(3))
        ra = tuple(rng.uniform(-180, 180) for _ in range(3))
        rb = tuple(rng.uniform(-180, 180) for _ in range(3))
        a = from_pose(p, (2, 4, 6), ra)
        b = from_pose(q, (3, 5, 1), rb)
        assert intersects(a, b) == intersects(b, a)


def test_map_dry_run_rejects_real_rotated_penetration_but_not_bounding_box_ghost():
    strip = {"name": "Long Wall", "position": [30, 8, 30], "size": [2, 2, 20],
             "rotation": [0, 45, 0], "role": "wall"}
    far_corner = {"name": "Decoration", "position": [36, 8, 24], "size": [1, 1, 1]}
    report = dry_run(_plan(strip, far_corner), include_operations=False)
    assert report["ok"] and "overlap" not in _codes(report["warnings"])
    assert report["collision_audit"]["method"] == "obb-sat"
    assert report["collision_audit"]["exhaustive"]
    far_corner["position"] = [36, 8, 36]
    report = dry_run(_plan(strip, far_corner), include_operations=False)
    assert any({row["a"], row["b"]} == {"Long Wall", "Decoration"}
               for notice in report["warnings"] if notice["code"] == "overlap"
               for row in notice["pairs"])
    assert any(row.get("approximate_depth") for notice in report["warnings"]
               if notice["code"] == "overlap" for row in notice["pairs"])


def test_rotated_nonbox_mesh_uses_conservative_volume_and_is_labeled():
    wedge = {"name": "Slope", "class": "WedgePart", "position": [20, 8, 20],
             "size": [4, 4, 4], "rotation": [0, 30, 0]}
    block = {"name": "Block", "position": [20, 8, 20], "size": [2, 2, 2]}
    report = dry_run(_plan(wedge, block), include_operations=False)
    collisions = next(x for x in report["warnings"] if x["code"] == "overlap")
    matching = next(pair for pair in collisions["pairs"]
                    if {pair["a"], pair["b"]} == {"Slope", "Block"})
    assert matching["approximate_shape"] is True


def test_spawn_headroom_uses_oriented_geometry_without_false_block():
    far_strip = {"name": "Roof", "position": [0, 6, 0], "size": [2, 2, 20],
                 "rotation": [0, 45, 0]}
    report = dry_run(_plan(far_strip, spawn=(6, 0.5, -6)), include_operations=False)
    assert "spawn-blocked" not in _codes(report["blockers"])
    assert report["ok"]


def test_budget_exhaustion_fails_closed_and_omits_mutating_operations():
    parts = [{"name": f"P{i}", "position": [10, 10, 10], "size": [4, 4, 4]}
             for i in range(400)]
    report = dry_run(_plan(*parts), include_operations=True)
    assert not report["ok"] and "operations" not in report
    assert "collision-audit-incomplete" in _codes(report["blockers"])
    assert not report["collision_audit"]["exhaustive"]
    assert report["collision_audit"]["candidates_checked"] == 50_000
    assert len(next(x for x in report["warnings"] if x["code"] == "overlap")["pairs"]) == 25


def test_adaptive_broadphase_handles_long_thin_obstacle_courses():
    parts = [{"name": f"R{i}", "position": [0, 3, i * 5 - 5000],
              "size": [2, 1, 2], "role": "platform", "floating": True} for i in range(1800)]
    plan = _plan(*parts, spawn=(20, 0.5, 0), bounds=(200, 80, 20000))
    plan["limits"] = {"maxObjects": 3000}
    report = dry_run(plan, include_operations=False)
    assert report["ok"]
    assert report["collision_audit"]["exhaustive"]
    assert report["collision_audit"]["candidates_checked"] == 0


def test_nonfinite_and_astronomical_coordinates_are_rejected_cleanly():
    plan = _plan({"name": "Bad", "position": [10**300, 2, 0], "size": [1, 1, 1]})
    report = dry_run(plan)
    assert not report["ok"] and _codes(report["blockers"]) == {"schema"}
    plan["parts"][-1]["position"] = [math.inf, 2, 0]
    report = dry_run(plan)
    assert not report["ok"] and _codes(report["blockers"]) == {"schema"}


def test_collision_report_caps_memory_and_tracks_unreported_pairs():
    parts = [{"name": f"S{i}", "position": [15, 12, 15], "size": [3, 3, 3]}
             for i in range(70)]
    report = dry_run(_plan(*parts), include_operations=False)
    audit = report["collision_audit"]
    notice = next(item for item in report["warnings"] if item["code"] == "overlap")
    assert audit["exhaustive"]
    assert audit["overlap_pairs_found"] > 25
    assert len(notice["pairs"]) == 25
    assert notice["more"] == audit["overlap_pairs_found"] - 25
    assert audit["broad_pairs_checked"] >= audit["candidates_checked"]


def test_broad_phase_work_budget_is_distinguished_from_sat_budget(monkeypatch):
    import star.map_plan as map_plan

    monkeypatch.setattr(map_plan, "MAX_BROAD_PAIRS", 1)
    plan = _plan(*[{"name": f"B{i}", "position": [11, 12, 11], "size": [4, 4, 4]}
                   for i in range(4)])
    report = dry_run(plan)
    assert not report["ok"] and "operations" not in report
    audit = report["collision_audit"]
    assert audit["truncated_reason"] == "broad_pair_budget"
    assert audit["broad_pairs_checked"] == 1
    assert audit["candidates_checked"] == 1
