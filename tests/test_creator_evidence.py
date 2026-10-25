"""Offline, adversarial checks for STAR's creative evidence contract."""
import copy
import unittest

from star.creator_evidence import CaptureError, assess_creation, propose_memory


def good_packet():
    return {
        "project": "parkour_demo",
        "requirements": [{"id": "checkpoint", "passed": True, "evidence": "studio:log:checkpoint-1"}],
        "viewports": [
            {"id": "phone", "device": "phone", "safe_rect": [10, 10, 824, 370],
             "controls": [{"id": "jump", "rect": [730, 280, 80, 80], "interactive": True, "critical": True},
                          {"id": "retry", "rect": [610, 280, 90, 80], "interactive": True, "critical": True}]},
            {"id": "desktop", "device": "desktop", "safe_rect": [0, 0, 1920, 1080], "controls": []}],
        "collisions": [{"a": "wall", "b": "floor", "verified_in_studio": True,
                        "intersecting": True, "intentional": True}],
        "animations": [{"id": "jump", "played": True, "required_markers": ["land"],
                        "observed_markers": ["land"], "foot_slide_studs": 0.1}],
        "playtests": [{"id": "full_run", "passed": True, "method": "virtual_input",
                       "evidence": "studio:play:test-1", "runtime_errors": []}],
        "screenshots": [{"device": "phone", "sha256": "a" * 64},
                        {"device": "desktop", "sha256": "b" * 64}],
    }


class CreativeEvidenceTest(unittest.TestCase):
    def test_happy_path_remains_review_only(self):
        result = assess_creation(good_packet())
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["counts"], {"error": 0, "review": 0, "unverified": 0})
        self.assertIn("NOT permission", " ".join(result["limitations"]))

    def test_ui_collision_safe_area_and_touch_targets(self):
        p = good_packet()
        p["viewports"][0]["controls"][0]["rect"] = [800, 360, 20, 20]
        p["viewports"][0]["controls"][1]["rect"] = [804, 362, 20, 20]
        findings = assess_creation(p)["findings"]
        codes = {f["code"] for f in findings}
        self.assertTrue({"ui-control-overlap", "ui-safe-area", "ui-small-target"} <= codes)

    def test_intentional_3d_intersection_not_a_defect(self):
        result = assess_creation(good_packet())
        self.assertNotIn("unintended-penetration", {f["code"] for f in result["findings"]})
        p = good_packet()
        p["collisions"][0]["intentional"] = False
        self.assertEqual(assess_creation(p)["status"], "needs_repair")

    def test_unverified_collision_is_not_claimed_as_certain(self):
        p = good_packet()
        p["collisions"][0]["intentional"] = False
        p["collisions"][0]["verified_in_studio"] = False
        f = assess_creation(p)["findings"]
        self.assertIn("collision-not-measured", {x["code"] for x in f})
        self.assertNotIn("unintended-penetration", {x["code"] for x in f})

    def test_playtest_teleport_not_user_input(self):
        p = good_packet()
        p["playtests"][0]["method"] = "teleport_probe"
        self.assertEqual(assess_creation(p)["status"], "needs_evidence")

    def test_animation_markers_missing(self):
        p = good_packet()
        p["animations"][0]["observed_markers"] = []
        p["animations"][0]["foot_slide_studs"] = 0.7
        result = assess_creation(p)
        self.assertIn("animation-marker-missing", {x["code"] for x in result["findings"]})
        self.assertIn("animation-foot-sliding", {x["code"] for x in result["findings"]})

    def test_missing_evidence_fails_closed(self):
        p = good_packet()
        p["screenshots"] = []
        p["requirements"][0].pop("evidence")
        self.assertEqual(assess_creation(p)["status"], "needs_evidence")
        self.assertIn("visual-view-missing", {x["code"] for x in assess_creation(p)["findings"]})

    def test_invalid_and_oversized_inputs_fail_closed(self):
        p = good_packet()
        p["project"] = "../not-allowed"
        with self.assertRaises(CaptureError):
            assess_creation(p)
        p = good_packet()
        p["viewports"][0]["controls"][0]["rect"] = [0, 0, float("nan"), 5]
        with self.assertRaises(CaptureError):
            assess_creation(p)
        p = good_packet()
        p["arbitrary"] = "x" * 160_001
        with self.assertRaises(CaptureError):
            assess_creation(p)
        p = good_packet()
        p["requirements"].extend(copy.deepcopy(p["requirements"]) * 200)
        with self.assertRaises(CaptureError):
            assess_creation(p)

    def test_proposed_memory_is_non_mutating(self):
        packet = good_packet()
        packet["collisions"][0]["intentional"] = False
        report = assess_creation(packet)
        proposal = propose_memory(report)
        self.assertFalse(proposal["written"])
        self.assertFalse(proposal["approved"])
        self.assertEqual(len(proposal["graph_candidate"]["links"]), len(report["findings"]))
        self.assertIn(report["capture_sha256"], proposal["obsidian_markdown_candidate"])
        self.assertIn("Owner review required", proposal["obsidian_markdown_candidate"])


if __name__ == "__main__":
    unittest.main()
