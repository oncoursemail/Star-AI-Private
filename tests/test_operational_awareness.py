"""Offline evidence and permission-boundary checks for STAR's operational self-model.

No live model, network, Studio, GPU or external keys are needed.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from star import operational_awareness as awareness


def status(**overrides):
    base = {
        "skills": {"enabled": True, "count": 22, "names": ["roblox-ui-craft"]},
        "design": {"enabled": True, "read_only": True},
        "map_plans": {"enabled": True},
        "studio_lab": {"enabled": False},
        "graphify": {"enabled": False, "export_detected": False},
        "obsidian": {"enabled": False},
        "asset_forge": {"enabled": False},
        "doc_knowledge": {"enabled": False},
    }
    base.update(overrides)
    return base


class OperationalAwarenessTests(unittest.TestCase):
    def test_parkour_game_has_end_to_end_requirements(self):
        selected = {item.key for item in awareness.select_dimensions("Make a parkour game")}
        self.assertEqual(selected, {
            "visual_design", "luau_engineering", "animation",
            "vfx", "environment", "audio", "studio_testing",
        })

    def test_multiword_shooter_goal_still_requires_complete_game_proof(self):
        selected = {i.key for i in awareness.select_dimensions(
            "Build a 3v3 animal shooter game with native Roblox HUD")}
        self.assertIn("animation",selected)
        self.assertIn("audio",selected)
        self.assertIn("studio_testing",selected)

    def test_audio_task_does_not_invent_roblox_studio(self):
        selected = {item.key for item in awareness.select_dimensions("Create original sound effects")}
        self.assertIn("audio", selected)
        self.assertNotIn("studio_testing", selected)

    def test_generic_prompt_has_small_default(self):
        self.assertEqual({i.key for i in awareness.select_dimensions("Please help")},
                         {"research", "luau_engineering"})

    def test_bad_goal_refused(self):
        for prompt in ("", " ", "x", "x" * 261, "design\nsystem", "abc\rdo",
                       "help\x00me", "ok\x7f"):
            with self.subTest(prompt=repr(prompt)):
                with self.assertRaises(ValueError):
                    awareness.select_dimensions(prompt)

    def test_tool_attached_does_not_become_proven_skill(self):
        report = awareness.observe(
            "make a parkour game", status=status(),
            enabled_tools=["star_design_search", "star_skill_catalog"])
        design = next(x for x in report["dimensions"] if x["id"] == "visual_design")
        self.assertEqual(design["state"], "reference_or_tool_available_unverified")
        self.assertTrue(design["not_a_guarantee"])
        self.assertEqual(design["proof"]["recorded_passes"], 0)
        self.assertEqual(report["work_performed"], False)
        self.assertFalse(report["model_weights_changed"])

    def test_studio_disabled_needs_permission_and_test(self):
        report = awareness.observe("Make a parkour game", status=status(),
                                   enabled_tools=["star_design_search"])
        studio = next(x for x in report["dimensions"] if x["id"] == "studio_testing")
        self.assertEqual(studio["state"], "requires_owner_configuration_or_alternative")
        self.assertIs(studio["host_configured"], False)

    def test_missing_status_is_unknown_not_off(self):
        report = awareness.observe("make a parkour game", status={},
                                   enabled_tools=[])
        animation = next(x for x in report["dimensions"] if x["id"] == "animation")
        self.assertIsNone(animation["host_configured"])
        self.assertEqual(animation["state"], "not_observed_or_not_attached")

    def test_configured_gear_not_same_as_attached(self):
        report = awareness.observe(
            "Make a parkour game", status=status(studio_lab={"enabled": True}),
            enabled_tools=[])
        studio = next(x for x in report["dimensions"] if x["id"] == "studio_testing")
        self.assertIs(studio["host_configured"], True)
        self.assertEqual(studio["state"], "not_observed_or_not_attached")

    def test_audit_never_leaks_server_keys_or_local_paths(self):
        info = status()
        info["sensitive_key"] = {"api_key": "secret-123"}
        info["obsidian"]["path"] = "C:\\Users\\private\\document"
        info["skills"]["names"] = ["private-work-project"]
        result = awareness.observe("make a parkour game", status=info,
                                   enabled_tools=["star_design_search"])
        whole = json.dumps(result)
        for forbidden in ("secret-123", "C:\\Users", "private-work-project"):
            self.assertNotIn(forbidden, whole)

    def test_evaluation_claims_are_counts_not_calibration(self):
        observations = [
            {"dimension": "visual_design", "outcome": "fail"},
            {"dimension": "visual_design", "outcome": "pass"},
            {"dimension": "visual_design", "outcome": "reported_by_model"},
            {"dimension": "animation", "outcome": "pass"},
        ]
        result = awareness.observe("make a parkour game", status=status(),
                                   enabled_tools=[], observations=observations)
        proof = next(d["proof"] for d in result["dimensions"] if d["id"] == "visual_design")
        self.assertEqual(proof["recorded_attempts"], 2)
        self.assertEqual(proof["recorded_passes"], 1)
        self.assertEqual(proof["recorded_failures"], 1)
        self.assertIn("not a calibrated", proof["reliability"].lower())

    def test_non_iterable_and_unbounded_evidence_rejected(self):
        with self.assertRaises(ValueError):
            awareness.observe("roblox UI", status=status(), enabled_tools="tool")
        with self.assertRaises(ValueError):
            awareness.observe("roblox UI", status=status(), enabled_tools=[], observations=[{}] * 1001)

    def test_proposal_cannot_exceed_limit(self):
        for limit in (0, 8, -1, True, 3.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    awareness.improvement_plan("game", status=status(),
                                               enabled_tools=[], limit=limit)

    def test_plan_proposes_no_unauthorized_actions(self):
        plan = awareness.improvement_plan("make a parkour game", status=status(),
                                           enabled_tools=["star_design_search"])
        self.assertLessEqual(len(plan["experiments"]), 5)
        self.assertEqual(plan["started"], [])
        self.assertFalse(plan["model_retrained"])
        self.assertFalse(plan["experiments"][0]["can_run_without_approval"])
        self.assertFalse(plan["experiments"][0]["claims_quality_improvement"])
        self.assertEqual(plan["promoted_lessons"], [])

    def test_failures_raise_priority(self):
        base = awareness.improvement_plan("make a parkour game", status=status(),
                                          enabled_tools=[], limit=7)
        failures = [{"dimension":"audio","outcome":"fail"}] * 6
        tested = awareness.improvement_plan("make a parkour game", status=status(),
                                            enabled_tools=[], observations=failures, limit=7)
        order0 = [r["dimension"] for r in base["experiments"]]
        order1 = [r["dimension"] for r in tested["experiments"]]
        self.assertGreater(order0.index("audio"), order1.index("audio"))

    def test_metadata_from_atlas_never_grants_installation_or_permission(self):
        plan = awareness.improvement_plan("make a parkour game", status=status(),
                                          enabled_tools=[], limit=7)
        cataloged = [s for row in plan["experiments"]
                     for s in row["possible_research_sources"]]
        self.assertTrue(cataloged)
        self.assertTrue(all("not installed" in item["status"] for item in cataloged))
        self.assertTrue(plan["unreviewed_sources_do_not_grant_permissions"])
        self.assertTrue(plan["all_actions_proposed_only"])

    def test_never_calls_network_even_for_research_goal(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("Unexpected network")):
            result = awareness.improvement_plan(
                "Research every tool on GitHub", status=status(), enabled_tools=[])
        self.assertTrue(result["all_actions_proposed_only"])

    def test_atlas_index_is_metadata_only(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.sqlite3"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE candidates (provider TEXT, resource_id TEXT)")
            db.execute("INSERT INTO candidates VALUES ('github','org/repo')")
            db.commit()
            db.close()
            data = awareness._index_statistics(path)
            self.assertEqual(data["indexed_candidates"], 1)
            self.assertFalse(data["installed"])
            self.assertFalse(data["network_used"])
            self.assertTrue(data["review_required"])

    def test_symlinked_atlas_is_rejected(self):
        with TemporaryDirectory() as tmp:
            src = Path(tmp) / "real.sqlite3"
            src.write_bytes(b"external")
            link = Path(tmp) / "link.sqlite3"
            try:
                link.symlink_to(src)
            except OSError:
                self.skipTest("symlinks need a privilege this platform session lacks")
            self.assertNotIn("indexed_candidates", awareness._index_statistics(link))
            self.assertFalse(awareness._index_statistics(link)["installed"])

    def test_not_configured_database_does_not_create_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "new.sqlite3"
            self.assertEqual(awareness._index_statistics(path)["state"], "not_indexed")
            self.assertFalse(path.exists())

    def test_unknown_or_malformed_index_is_not_a_capability(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "junk.sqlite3"
            path.write_text("not a database")
            self.assertEqual(awareness._index_statistics(path)["state"], "unavailable")

    def test_tools_have_no_write_or_promotion_operations(self):
        names = {tool["name"] for tool in awareness.SELF_TOOLS}
        self.assertEqual(names, {"star_self_capabilities","star_self_improvement_plan"})
        self.assertTrue(all(tool["inputSchema"]["additionalProperties"] is False
                            for tool in awareness.SELF_TOOLS))
        self.assertTrue(all("goal" in tool["inputSchema"]["required"]
                            for tool in awareness.SELF_TOOLS))

    def test_output_bounded_and_serializable(self):
        report = awareness.improvement_plan("Make a parkour game",
                   status=status(), enabled_tools=["star_design_search"],limit=7)
        encoded = json.dumps(report,ensure_ascii=False)
        self.assertLess(len(encoded), 14000)
        self.assertIn("paired gate", encoded)

    def test_preflight_is_compact_and_never_claims_execution(self):
        brief = awareness.preflight_brief("Make a parkour game",
                status=status(), enabled_tools=["star_design_search"])
        self.assertLessEqual(len(brief),850)
        self.assertIn("not quality-verified",brief)
        self.assertIn("Studio",brief)
        self.assertNotIn("completed",brief.lower())
        self.assertIn("permissions",brief)
        self.assertNotIn("secret",brief.lower())

    def test_preflight_rejects_invalid_budget(self):
        with self.assertRaises(ValueError):
            awareness.preflight_brief("Make a parkour game",
                 status=status(),enabled_tools=[],max_chars=100)
        with self.assertRaises(ValueError):
            awareness.preflight_brief("Make a parkour game",
                 status=status(),enabled_tools=[],max_chars=10_000)


if __name__ == "__main__":
    unittest.main()
