"""Adversarial geometry checks, no Roblox Studio or other external dependency."""
import copy
import unittest

from star.scene_topology import audit_scene


def scene():
    return {
        "project": "test_cottage",
        "complete": True,
        "expected_parts": ["foundation", "wall", "roof", "bench"],
        "parts": [
            {"id": "foundation", "center": [0, -0.5, 0], "size": [20, 1, 20]},
            {"id": "wall", "center": [-9.75, 4, 0], "size": [0.5, 8, 20]},
            {"id": "roof", "center": [0, 8.5, 0], "size": [20, 1, 20]},
            {"id": "bench", "center": [0, 1, 0], "size": [2, 2, 2]},
        ],
        "supports": [
            {"item": "wall", "surface": "foundation"},
            {"item": "bench", "surface": "foundation"},
            {"item": "roof", "surface": "wall"},
        ],
        "joins": [{"a": "wall", "b": "roof", "max_gap": 0.08}],
        "clearances": [
            {"id": "doorway", "center": [0, 3, 5], "size": [3, 5, 2]},
        ],
        "allowed_overlaps": [],
    }


class SceneTopologyTest(unittest.TestCase):
    def codes(self, s):
        return [f["code"] for f in audit_scene(s)["findings"]]

    def test_authored_scene_is_ready_only_for_studio_confirmation(self):
        result = audit_scene(scene())
        self.assertEqual(result["status"], "ready_for_studio_confirmation")
        self.assertFalse(result["studio_verified"])
        self.assertFalse(result["findings"])

    def test_missing_props_are_detected(self):
        p = scene()
        p["parts"].pop()
        self.assertIn("missing-prop", self.codes(p))
        self.assertEqual(audit_scene(p)["status"], "needs_repair")

    def test_partial_snapshot_is_unknown_not_missing(self):
        p = scene()
        p["complete"] = False
        p["parts"].pop()
        self.assertIn("prop-not-observed", self.codes(p))
        self.assertNotIn("missing-prop", self.codes(p))
        self.assertEqual(audit_scene(p)["status"], "needs_evidence")

    def test_prop_intersection_and_allowlist(self):
        p = scene()
        p["parts"].append({"id": "chest", "center": [0.2, 1, 0], "size": [2, 2, 2]})
        self.assertIn("unexpected-box-overlap", self.codes(p))
        p["allowed_overlaps"].append(["bench", "chest"])
        self.assertNotIn("unexpected-box-overlap", self.codes(p))

    def test_yaw_rotated_boxes_have_bounded_separation(self):
        p = scene()
        p["parts"].append({"id": "rotated", "center": [4, 3, 0], "size": [4, 2, 1], "yaw_degrees": 45})
        p["parts"].append({"id": "clip", "center": [4.5, 3, 0.5], "size": [1, 2, 1]})
        self.assertIn("unexpected-box-overlap", self.codes(p))
        p["parts"][-1]["center"] = [9, 2, 9]
        self.assertNotIn("unexpected-box-overlap", self.codes(p))

    def test_floating_support_and_disconnected_join(self):
        p = scene()
        p["parts"][2]["center"][1] = 10.5
        found = self.codes(p)
        self.assertIn("unsupported-part", found)
        self.assertIn("unattached-joint", found)

    def test_blocked_clearance(self):
        p = scene()
        p["parts"].append({"id": "debris", "center": [0, 3, 5], "size": [1, 1, 1]})
        self.assertIn("blocked-clearance", self.codes(p))
        p["clearances"][0]["ignore"] = ["debris"]
        self.assertNotIn("blocked-clearance", self.codes(p))

    def test_touching_interfaces_are_not_flagged_as_penetrating(self):
        self.assertNotIn("unexpected-box-overlap", self.codes(scene()))
        p = scene()
        p["parts"][3]["center"][1] = 0.5
        self.assertIn("unexpected-box-overlap", self.codes(p))

    def test_reject_duplicate_and_nonnumeric_dimensions(self):
        p = scene()
        p["parts"][0]["size"] = [20, float("nan"), 20]
        with self.assertRaises(ValueError):
            audit_scene(p)
        p = scene()
        p["parts"][1]["id"] = "foundation"
        with self.assertRaises(ValueError):
            audit_scene(p)
        p = scene()
        p["parts"][0]["size"] = [True, 1, 1]
        with self.assertRaises(ValueError):
            audit_scene(p)

    def test_invalid_overlap_allowlist_fails_closed(self):
        p = scene()
        p["allowed_overlaps"] = [["wall", "imaginary"]]
        with self.assertRaises(ValueError):
            audit_scene(p)
        p = scene()
        p["allowed_overlaps"] = [["bench", "bench"]]
        with self.assertRaises(ValueError):
            audit_scene(p)

    def test_output_does_not_depend_on_mutation_or_hash(self):
        p = scene()
        original = copy.deepcopy(p)
        self.assertEqual(audit_scene(p), audit_scene(p))
        self.assertEqual(p, original)


if __name__ == "__main__":
    unittest.main()
