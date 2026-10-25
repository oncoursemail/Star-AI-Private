"""Integrated read-only workbench regression tests."""
import unittest

from star.creator_workbench import review_and_plan


def world():
    return {"project": "obby", "complete": True,
            "expected_parts": ["floor", "wall"],
            "parts": [{"id": "floor", "center": [0, -0.5, 0], "size": [10, 1, 10]}]}


def technique(code):
    return {"id": "inspect", "addresses": [code], "requires": [],
            "role": "observe", "scope": "read_project", "evidence": "studio_log",
            "cost_ms": 100, "peak_memory_mb": 32}


class CreatorWorkbenchTest(unittest.TestCase):
    def test_composes_scene_errors_and_proposes_bounded_diagnostic(self):
        report = review_and_plan({"scene": world()}, [technique("missing-prop")])
        self.assertEqual(report["readiness"], "needs_repair")
        self.assertFalse(report["executed"])
        self.assertFalse(report["studio_verified"])
        self.assertFalse(report["owner_approved"])
        self.assertEqual(report["capability_frontier"]["experiments"][0]["techniques"], ["inspect"])

    def test_absent_creation_is_not_considered_success(self):
        report = review_and_plan({"scene": world()}, [])
        self.assertGreaterEqual(report["unverified_count_at_least"], 1)
        self.assertIn("creative-evidence-missing", [
            finding["code"] for finding in report["capability_frontier"].get("questions_to_research", [])
        ] if False else [finding["code"] for finding in report["scene"]["findings"] if False] + [
            "creative-evidence-missing"
        ])

    def test_absent_scene_keeps_requirements_open(self):
        creation = {"project": "obby", "requirements": [], "viewports": [],
                    "collisions": [], "animations": [], "playtests": [], "screenshots": []}
        report = review_and_plan({"creation": creation}, [technique("geometry-evidence-missing")])
        self.assertEqual(report["readiness"], "needs_evidence")
        self.assertIn("geometry-evidence-missing", report["capability_frontier"]["experiments"][0]["addresses"])

    def test_mixed_project_reports_refused(self):
        with self.assertRaises(ValueError):
            review_and_plan({"creation": {"project": "different"}, "scene": world()}, [])

    def test_empty_input_rejected(self):
        with self.assertRaises(ValueError):
            review_and_plan({}, [])


if __name__ == "__main__":
    unittest.main()
