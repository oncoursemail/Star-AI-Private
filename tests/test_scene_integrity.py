"""Offline geometry/placement regression tests. These never open Blender or Studio."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from star.architecture_pipeline import PALETTES, make_plan, validate_brief
from star.architecture_quality import audit_plan
from star.scene_integrity import audit_scene, propose_shell_repair
from star.scene_quality_cli import main as scene_quality_main

BASE = {"name": "Harbor Works", "style": "industrial",
        "width_studs": 48, "depth_studs": 32, "floors": 2, "bays": 4}


def plan():
    return make_plan(validate_brief(BASE))


def part_by_name(building, name):
    return next(part for part in building["parts"] if part["name"] == name)


def codes(report):
    return {item["code"] for item in report["issues"]}


def prop(name, x=0.0, z=0.5, *, support="foundation"):
    return {
        "name": name, "kind": "box", "material": "door", "role": "prop",
        "center": [x, 0, z], "size": [1, 1, 1], "angle_y": 0,
        "placement": {"target_center": [x, 0, 0.5], "max_offset_studs": 0.1,
                      "support_name": support},
    }


class SceneIntegrityTests(unittest.TestCase):
    def test_every_supported_style_passes_preflight(self):
        for style in PALETTES:
            with self.subTest(style=style):
                candidate = make_plan(validate_brief({**BASE, "style": style}))
                review = audit_plan(candidate)
                self.assertTrue(review["valid"], review["errors"])
                self.assertTrue(review["scene_integrity"]["valid"])
                self.assertTrue(review["blueprint_integrity"]["valid"])
                self.assertIn("visual_review_required", review["status"])

    def test_missing_wall_is_blocked_even_with_forged_metrics(self):
        building = plan()
        building["parts"] = [p for p in building["parts"] if p["name"] != "side_left_f0"]
        building["metrics"]["parts_before_material_batch"] -= 1
        building["metrics"]["estimated_triangles"] -= 12
        report = audit_plan(building)
        self.assertFalse(report["valid"])
        self.assertIn("missing_component", codes(report["blueprint_integrity"]))

    def test_shifted_wall_door_roof_and_window_are_each_rejected(self):
        for name in ("front_f0_b0_left", "side_right_f1", "entry_door",
                     "front_f1_b0_glazing", "flat_roof"):
            with self.subTest(part=name):
                building = plan()
                part_by_name(building, name)["center"][0] += 0.7
                report = audit_plan(building)
                self.assertFalse(report["valid"])
                self.assertIn("misaligned_component", codes(report["blueprint_integrity"]))

    def test_glazing_displaced_into_wall_is_detected_as_occlusion(self):
        building = plan()
        glass = part_by_name(building, "front_f0_b0_glazing")
        glass["center"][1] += 0.35
        glass["center"][0] += 0.8  # clip through an actual window jamb/wall flank
        report = audit_plan(building)
        self.assertIn("blocked_opening", codes(report["scene_integrity"]))

    def test_duplicate_coplanar_geometry_is_z_fighting_candidate(self):
        building = plan()
        dupe = deepcopy(part_by_name(building, "entry_door"))
        dupe["name"] = "decoy_entry_door"
        building["parts"].append(dupe)
        report = audit_scene(building["parts"])
        self.assertIn("duplicate_geometry", codes(report))

    def test_semantic_prop_overlap_and_missing_support_are_blocked(self):
        building = plan()
        first, second = prop("crate_a"), prop("crate_b", x=0.4)
        report = audit_scene(building["parts"] + [first, second])
        self.assertIn("prop_intersection", codes(report))
        second["placement"]["support_name"] = "missing_floor"
        self.assertIn("missing_support", codes(audit_scene(building["parts"] + [second])))

    def test_floating_prop_and_anchor_offset_blocked(self):
        building = plan()
        thing = prop("crate")
        thing["center"] = [2, 0, 2]
        finding = codes(audit_scene(building["parts"] + [thing]))
        self.assertIn("misplaced_prop", finding)
        self.assertIn("floating_prop", finding)

    def test_unannotated_extra_prop_cannot_be_accepted(self):
        building = plan()
        spare = prop("random_spare")
        spare.pop("role")
        spare.pop("placement")
        building["parts"].append(spare)
        # Keep correct accounting so this test checks *semantic* protection.
        building["metrics"]["parts_before_material_batch"] += 1
        building["metrics"]["estimated_triangles"] += 12
        report = audit_plan(building)
        self.assertIn("unplanned_object", codes(report["blueprint_integrity"]))

    def test_sat_distinguishes_rotated_aabb_false_positive(self):
        initial = {"name": "beam_a", "kind": "box", "material": "door",
                   "center": [0, 0, 0], "size": [4, 0.5, 0.2], "angle_y": 45}
        second = {**initial, "name": "beam_b", "center": [0.3, 0, 0.3]}
        self.assertTrue(audit_scene([initial, second])["valid"])
        second["center"] = [0.08, 0, 0.08]
        self.assertIn("overlapping_openings", codes(audit_scene([initial, second])))

    def test_surface_texture_metadata_has_bounded_validation(self):
        candidate = prop("poster")
        candidate["texture"] = {"tile_studs": 0, "normal": "https://bad.example/test"}
        result = audit_scene([candidate])
        self.assertIn("texture_scale", codes(result))
        self.assertIn("texture_asset", codes(result))
        candidate["texture"] = {"tile_studs": 2, "color": "rbxassetid://123"}
        result = audit_scene([candidate])
        self.assertNotIn("texture_scale", codes(result))
        self.assertNotIn("texture_asset", codes(result))

    def test_generated_shell_repair_is_proposed_not_applied(self):
        building = plan()
        before = deepcopy(building)
        part_by_name(building, "entry_door")["center"][0] += 3
        building["parts"] = [p for p in building["parts"] if p["name"] != "side_left_f0"]
        changed = deepcopy(building)
        repair = propose_shell_repair(building)
        self.assertEqual(building, changed)
        self.assertTrue(repair["original_unchanged"])
        self.assertFalse(repair["studio_changed"])
        self.assertEqual(repair["status"], "proposed_not_applied")
        self.assertTrue(repair["proposed_audit"]["valid"], repair["proposed_audit"]["errors"])
        self.assertEqual({c["action"] for c in repair["changes"]},
                         {"restore_missing", "restore_blueprint"})
        self.assertEqual(part_by_name(repair["proposed_plan"], "entry_door"),
                         part_by_name(before, "entry_door"))

    def test_repair_never_silently_deletes_unknown_parts(self):
        building = plan()
        building["parts"].append({
            "name": "junk_block", "kind": "box", "material": "wall",
            "center": [99, 99, 99], "size": [1, 1, 1], "angle_y": 0})
        repair = propose_shell_repair(building)
        self.assertEqual(repair["status"], "blocked_review_required")
        self.assertIn("junk_block", [p["name"] for p in repair["proposed_plan"]["parts"]])


    def test_authored_contract_catches_missing_props_even_when_metrics_match(self):
        building = plan()
        building["scene_contract"] = {
            "required": [{"name": "checkout_register", "center": [0, 0, 0.5],
                          "size": [1, 1, 1]}],
            "connections": [{"first": "checkout_register", "second": "foundation"}],
        }
        report = audit_plan(building)
        self.assertIn("missing_required_prop", codes(report["scene_contract"]))
        self.assertIn("missing_connection", codes(report["scene_contract"]))

    def test_contract_catches_wrong_sizing_and_disconnected_components(self):
        building = plan()
        item = prop("crate")
        building["parts"].append(item)
        building["metrics"]["parts_before_material_batch"] += 1
        building["metrics"]["estimated_triangles"] += 12
        building["scene_contract"] = {
            "required": [{"name": "crate", "center": [0, 0, .5], "size": [1, 1, 1]}],
            "connections": [{"first": "crate", "second": "foundation"}],
        }
        self.assertTrue(audit_plan(building)["valid"], audit_plan(building)["errors"])
        item["size"] = [2, 1, 1]
        item["center"][2] += 2
        report = audit_plan(building)
        self.assertIn("wrong_required_placement", codes(report["scene_contract"]))
        self.assertIn("unattached_component", codes(report["scene_contract"]))

    def test_contract_is_optional_and_untrusted_malformed_contract_blocks(self):
        building = plan()
        self.assertFalse(audit_plan(building)["scene_contract"]["present"])
        building["scene_contract"] = {"required": [42]}
        self.assertIn("invalid_contract", codes(audit_plan(building)["scene_contract"]))

    def test_bad_prop_input_fails_closed(self):
        item = prop("bad")
        item["center"] = [float("nan"), 0, 0]
        building = plan()
        building["parts"].append(item)
        report = audit_plan(building)
        self.assertFalse(report["valid"])

    def test_read_only_evaluation_is_deterministic(self):
        building = plan()
        before = deepcopy(building)
        self.assertEqual(audit_plan(building), audit_plan(building))
        self.assertEqual(building, before)



class SceneCLIRegressionTests(unittest.TestCase):
    def test_clean_plan_can_be_inspected_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.json"
            path.write_text(json.dumps(plan()), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = scene_quality_main([str(path)])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report["audit"]["valid"])
            self.assertTrue(report["plan_unchanged"])
            self.assertFalse(report["studio_changed"])
            self.assertEqual({p.name for p in Path(folder).iterdir()}, {"source.json"})

    def test_cli_writes_exclusive_safe_repair_proposal(self):
        with tempfile.TemporaryDirectory() as folder:
            original, proposed = Path(folder) / "original.json", Path(folder) / "proposal.json"
            broken = plan()
            broken["parts"] = [p for p in broken["parts"] if p["name"] != "side_left_f0"]
            raw = json.dumps(broken)
            original.write_text(raw, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = scene_quality_main([str(original), "--repair-proposal", str(proposed)])
            self.assertEqual(code, 0)
            self.assertEqual(original.read_text(), raw)
            self.assertTrue(proposed.is_file())
            self.assertTrue(audit_plan(json.loads(proposed.read_text()))["valid"])
            self.assertEqual(json.loads(output.getvalue())["proposal"]["status"], "proposed_not_applied")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                scene_quality_main([str(original), "--repair-proposal", str(proposed)])
            self.assertEqual(original.read_text(), raw)

    def test_cli_refuses_to_apply_unknown_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            original, proposed = Path(folder) / "original.json", Path(folder) / "proposal.json"
            broken = plan()
            broken["parts"].append({
                "name": "mystery_box", "kind": "box", "material": "wall",
                "center": [200, 0, 0], "size": [1, 1, 1], "angle_y": 0,
            })
            original.write_text(json.dumps(broken), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = scene_quality_main([str(original), "--repair-proposal", str(proposed)])
            self.assertEqual(code, 2)
            self.assertFalse(proposed.exists())
            self.assertEqual(json.loads(output.getvalue())["proposal"]["status"], "blocked_review_required")

    def test_cli_rejects_missing_and_oversized_input(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "not_here.json"
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
                scene_quality_main([str(missing)])
            self.assertEqual(e.exception.code, 2)
            huge = Path(folder) / "huge.json"
            huge.write_bytes(b" " * (6 * 1024 * 1024 + 1))
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
                scene_quality_main([str(huge)])
            self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
