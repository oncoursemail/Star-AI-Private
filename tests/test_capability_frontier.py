"""Plan/routing safety and optimization tests for STAR Capability Frontier."""
import copy
import unittest

from star.capability_frontier import plan_frontier


def report():
    return {"findings": [
        {"code": "unexpected-box-overlap", "target": "wall+chest", "severity": "error"},
        {"code": "ui-control-overlap", "target": "phone/jump+retry", "severity": "error"},
        {"code": "visual-view-missing", "target": "phone", "severity": "unverified"},
    ]}


def recipe(ident, addresses, *, requires=(), scope="read_project", role="observe",
           ms=200, mem=64, evidence="static_check"):
    return {"id": ident, "addresses": list(addresses), "requires": list(requires),
            "scope": scope, "role": role, "cost_ms": ms,
            "peak_memory_mb": mem, "evidence": evidence}


class CapabilityFrontierTest(unittest.TestCase):
    def test_returns_real_hypotheses_not_execution_or_self_certification(self):
        techniques = [
            recipe("geometry-probe", ["unexpected-box-overlap"], ms=80),
            recipe("ui-probe", ["ui-control-overlap"], ms=100),
            recipe("screenshot", ["visual-view-missing"], ms=250, evidence="screen_capture"),
        ]
        result = plan_frontier(report(), techniques, max_steps=3)
        self.assertFalse(result["executed"])
        self.assertEqual(result["state"], "experiments_proposed")
        self.assertEqual(result["experiments"][0]["coverage_weight"], 13)
        self.assertEqual(result["experiments"][0]["estimated_ms"], 430)
        self.assertEqual(result["experiments"][0]["state"], "UNTESTED_PROPOSAL")
        self.assertIn("independent", result["promotion"])

    def test_dependency_gets_included_before_repair(self):
        report_data = {"findings": [{"code": "unattached-joint",
                                     "target": "wall+roof", "severity": "error"}]}
        techniques = [
            recipe("look", ["scene-unverified"], ms=100, evidence="studio_log"),
            recipe("snap-repair", ["unattached-joint"], requires=("look",), scope="studio_edit",
                   role="repair", ms=500, evidence="studio_playtest"),
        ]
        result = plan_frontier(report_data, techniques,
                               allowed_scopes=("read_project", "studio_edit"))
        self.assertEqual(result["experiments"][0]["techniques"], ["look", "snap-repair"])
        self.assertIn("studio_edit", result["experiments"][0]["authority"])

    def test_permission_absence_blocks_even_when_technically_viable(self):
        techniques = [recipe("snap-repair", ["unexpected-box-overlap"],
                             scope="studio_edit", role="repair")]
        result = plan_frontier(report(), techniques)
        self.assertEqual(result["state"], "blocked_or_unmeasured")
        self.assertIn("studio_edit", result["scopes_needing_separate_permission"])
        self.assertEqual(result["experiments"], [])

    def test_cost_and_memory_limits_are_real(self):
        techniques = [recipe("expensive", ["unexpected-box-overlap"], ms=20_000, mem=4_000)]
        outcome = plan_frontier(report(), techniques, wall_time_ms=10_000, peak_memory_mb=2_000)
        self.assertEqual(outcome["experiments"], [])
        self.assertIn("unexpected-box-overlap", outcome["capability_gaps"])

    def test_selects_cheaper_equal_coverage(self):
        techniques = [
            recipe("slow", ["unexpected-box-overlap"], ms=600),
            recipe("fast", ["unexpected-box-overlap"], ms=100),
        ]
        output = plan_frontier({"findings": report()["findings"][:1]}, techniques, max_steps=1)
        self.assertEqual(output["experiments"][0]["techniques"], ["fast"])

    def test_no_defects_still_require_engine_proof(self):
        outcome = plan_frontier({"findings": []}, [])
        self.assertEqual(outcome["state"], "evidence_needed")
        self.assertFalse(outcome["executed"])

    def test_unknown_dependency_fails(self):
        with self.assertRaises(ValueError):
            plan_frontier(report(), [recipe("a", ["ui-control-overlap"], requires=("missing",))])

    def test_cycle_fails(self):
        with self.assertRaises(ValueError):
            plan_frontier(report(), [
                recipe("a", ["ui-control-overlap"], requires=("b",)),
                recipe("b", ["visual-view-missing"], requires=("a",)),
            ])

    def test_invalid_scope_not_accepted_even_if_caller_requests_it(self):
        bad = recipe("inject", ["ui-control-overlap"])
        bad["scope"] = "override_policy"
        with self.assertRaises(ValueError):
            plan_frontier(report(), [bad], allowed_scopes=("override_policy",))

    def test_boolean_budget_and_duplicate_names_fail(self):
        with self.assertRaises(ValueError):
            plan_frontier(report(), [], wall_time_ms=True)
        with self.assertRaises(ValueError):
            plan_frontier(report(), [recipe("same", ["ui-control-overlap"]),
                                     recipe("same", ["visual-view-missing"])])

    def test_untrusted_model_data_does_not_mutate_report(self):
        p = report()
        t = [recipe("look", ["unexpected-box-overlap"])]
        before = copy.deepcopy((p, t))
        plan_frontier(p, t)
        self.assertEqual((p, t), before)

    def test_non_top_five_possible_options_do_not_become_fake_gaps(self):
        p = {"findings": [
            {"code": "common", "target": "a", "severity": "error"},
            {"code": "rare", "target": "b", "severity": "review"},
        ]}
        techniques = [recipe(f"common{i}", ["common"], ms=i + 1) for i in range(8)]
        techniques.append(recipe("rare", ["rare"], ms=200))
        result = plan_frontier(p, techniques, max_steps=1)
        self.assertNotIn("rare", result["capability_gaps"])


if __name__ == "__main__":
    unittest.main()
