"""Independent offline behavior checks; these do not run browser or game tests."""
from __future__ import annotations

import builtins
import json
import socket
import subprocess
import unittest
from unittest.mock import patch

from star.game_portability import (
    MAX_GUIDANCE_CHARS,
    MAX_LINEAR_MEMORY_MIB,
    REFERENCE_REVISION,
    TOPICS,
    plan_portability,
    reference_guidance,
)


class PortabilityInputTests(unittest.TestCase):
    def test_nonboolean_capability_reports_are_rejected(self):
        for name in ("webgpu", "memory64", "cross_origin_isolated", "threads"):
            for value in (0, 1, "true", "false", [], {}, 0.0):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(TypeError):
                        plan_portability("browser", required_linear_memory_mib=256, **{name: value})

    def test_memory_is_a_bounded_integer_not_a_boolean(self):
        for value in (True, False, 256.0, "256", None, [], {}):
            with self.subTest(value=value), self.assertRaises(TypeError):
                plan_portability("browser", required_linear_memory_mib=value)
        for value in (0, -1, MAX_LINEAR_MEMORY_MIB + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan_portability("browser", required_linear_memory_mib=value)
        for value in (1, MAX_LINEAR_MEMORY_MIB):
            with self.subTest(value=value):
                out = plan_portability("browser", required_linear_memory_mib=value)
                self.assertEqual(out["required_linear_memory_mib"], value)

    def test_requires_threads_rejects_coercion(self):
        for value in (None, 0, 1, "false", []):
            with self.subTest(value=value), self.assertRaises(TypeError):
                plan_portability("browser", required_linear_memory_mib=256, requires_threads=value)

    def test_enums_and_extra_arguments_are_strict(self):
        for target in (None, True, []):
            with self.subTest(target=target), self.assertRaises(TypeError):
                plan_portability(target, required_linear_memory_mib=256)
        for target in ("Browser", " browser ", "unknown", "x" * 10000):
            with self.subTest(target=target[:20]), self.assertRaises(ValueError):
                plan_portability(target, required_linear_memory_mib=256)
        for topic in (None, True, []):
            with self.subTest(topic=topic), self.assertRaises(TypeError):
                reference_guidance(topic)
        for topic in ("Browser", "unknown", "x" * 10000):
            with self.subTest(topic=topic[:20]), self.assertRaises(ValueError):
                reference_guidance(topic)
        with self.assertRaises(TypeError):
            plan_portability("browser", required_linear_memory_mib=256, shell="run")


class PortabilityPlanningTests(unittest.TestCase):
    def test_unknown_is_preserved_separately_from_reported_absence(self):
        unknown = plan_portability("browser", required_linear_memory_mib=6144)
        absent = plan_portability("browser", required_linear_memory_mib=6144, memory64=False, webgpu=False)
        self.assertIsNone(unknown["capability_reports"]["memory64"])
        self.assertIs(absent["capability_reports"]["memory64"], False)
        self.assertEqual(unknown["assessment"], "needs_capability_verification")
        self.assertEqual(absent["assessment"], "blocked_by_reported_capabilities")
        self.assertNotEqual(unknown["renderer_plan"], absent["renderer_plan"])

    def test_six_gib_never_selects_wasm32(self):
        for support in (None, False, True):
            with self.subTest(support=support):
                out = plan_portability("browser", required_linear_memory_mib=6144, memory64=support, webgpu=True)
                self.assertEqual(out["memory_plan"]["addressing"], "wasm64_required")
                self.assertFalse(out["runtime_verified"])
        blocked = plan_portability("browser", required_linear_memory_mib=6144, memory64=False)
        self.assertIn("memory64_unavailable", {item["code"] for item in blocked["findings"]})

    def test_small_requirement_does_not_select_memory64_for_speed(self):
        out = plan_portability("browser", required_linear_memory_mib=512, memory64=True, webgpu=True)
        self.assertEqual(out["memory_plan"]["addressing"], "wasm32")
        self.assertIn("memory64_not_required", {item["code"] for item in out["findings"]})
        self.assertEqual(out["assessment"], "candidate_requires_runtime_validation")

    def test_exact_wasm32_limit_requires_overhead_and_allocation_check(self):
        out = plan_portability("browser", required_linear_memory_mib=4096, webgpu=True)
        self.assertEqual(out["memory_plan"]["addressing"], "wasm32")
        limit = next(item for item in out["findings"] if item["code"] == "wasm32_at_limit")
        self.assertIn("overhead", limit["message"])
        self.assertIn("allocation", limit["message"])
        self.assertFalse(out["runtime_verified"])

    def test_required_threads_need_both_reported_prerequisites(self):
        for threads in (None, False, True):
            for isolated in (None, False, True):
                with self.subTest(threads=threads, isolated=isolated):
                    out = plan_portability(
                        "browser", required_linear_memory_mib=512, webgpu=True,
                        threads=threads, cross_origin_isolated=isolated, requires_threads=True,
                    )
                    if threads is False or isolated is False:
                        self.assertEqual(out["assessment"], "blocked_by_reported_capabilities")
                    elif threads is None or isolated is None:
                        self.assertEqual(out["assessment"], "needs_capability_verification")
                    else:
                        self.assertEqual(out["threading_plan"]["path"], "pthread_candidate")
                        self.assertEqual(out["assessment"], "candidate_requires_runtime_validation")
                    self.assertIs(out["capability_reports"]["threads"], threads)
                    self.assertIs(out["capability_reports"]["cross_origin_isolated"], isolated)
                    self.assertFalse(out["threading_plan"]["single_binary_fallback"])
                    self.assertIn("semantics permit", out["threading_plan"]["fallback"])
                    checks = " ".join(out["acceptance_checks"])
                    self.assertIn("main thread", checks)
                    self.assertIn("synchronously proxy", checks)
                    self.assertIn("distinct nonthreaded", checks)
                    self.assertFalse(out["runtime_verified"])

    def test_optional_threads_do_not_block_single_threaded_plan(self):
        out = plan_portability(
            "browser", required_linear_memory_mib=512, webgpu=True,
            threads=False, cross_origin_isolated=False,
        )
        self.assertEqual(out["threading_plan"]["path"], "single_threaded_candidate")
        self.assertEqual(out["assessment"], "candidate_requires_runtime_validation")

    def test_missing_webgpu_does_not_certify_an_alternative(self):
        out = plan_portability("browser", required_linear_memory_mib=512, webgpu=False)
        self.assertEqual(out["renderer_plan"], "verified_alternative_required")
        self.assertFalse(out["runtime_verified"])
        self.assertIn("without assuming", next(
            item["message"] for item in out["findings"] if item["code"] == "webgpu_unavailable"
        ))

    def test_browser_reports_do_not_validate_or_block_other_targets(self):
        for target, addressing in (("roblox", "engine_managed"), ("native", "native_abi_selection")):
            with self.subTest(target=target):
                out = plan_portability(
                    target, required_linear_memory_mib=6144, webgpu=False, memory64=False,
                    threads=False, cross_origin_isolated=False, requires_threads=True,
                )
                self.assertFalse(out["browser_capabilities_applicable"])
                self.assertEqual(out["memory_plan"]["addressing"], addressing)
                self.assertEqual(out["assessment"], "candidate_requires_runtime_validation")
                self.assertNotIn("blocked", {item["level"] for item in out["findings"]})
                self.assertIn("not_applied", out["findings"][0]["code"])
                self.assertTrue(out["requires_threads"])
                self.assertFalse(out["runtime_verified"])


class ReferenceGuidanceTests(unittest.TestCase):
    def test_each_topic_is_bounded_and_references_its_checks(self):
        for topic in TOPICS:
            with self.subTest(topic=topic):
                out = reference_guidance(topic)
                self.assertLessEqual(len(json.dumps(out)), MAX_GUIDANCE_CHARS)
                self.assertEqual(out["status"], "candidate")
                self.assertTrue(out["read_only"])
                self.assertFalse(out["executed"])
                self.assertFalse(out["runtime_verified"])
                source_ids = {source["id"] for source in out["sources"]}
                for lesson in out["lessons"]:
                    self.assertTrue(lesson["preconditions"])
                    self.assertTrue(lesson["acceptance_checks"])
                    self.assertTrue(set(lesson["source_ids"]).issubset(source_ids))
                self.assertTrue(all(source["url"].startswith("https://") for source in out["sources"]))

    def test_overview_covers_twelve_primary_docs_and_scopes_grand_v(self):
        out = reference_guidance()
        self.assertEqual(len(out["sources"]), 12)
        self.assertEqual(out["reference_context"]["revision"], REFERENCE_REVISION)
        self.assertIn("author-reported", out["reference_context"]["scope"])
        self.assertIn("not reproduced", out["reference_context"]["scope"])
        self.assertIn("no lesson import", out["learning_effect"])

    def test_reference_source_observations_do_not_imply_full_game_validation(self):
        integrity = reference_guidance("asset_integrity")
        first = integrity["lessons"][0]
        self.assertIn("Equal-size corruption", first["principle"])
        self.assertIn("trusted authorship", first["acceptance_checks"][1])
        multiplayer = reference_guidance("multiplayer")["lessons"][0]
        self.assertIn("two-player relay", multiplayer["principle"])
        self.assertIn("does not establish authoritative", multiplayer["principle"])
        for source in integrity["sources"]:
            if source["id"].startswith("grand_v"):
                self.assertIn(REFERENCE_REVISION, source["url"])

    def test_outputs_are_independent_and_deterministic(self):
        expected = reference_guidance("browser")
        modified = reference_guidance("browser")
        modified["lessons"][0]["acceptance_checks"].clear()
        modified["sources"][0]["url"] = "changed"
        self.assertEqual(reference_guidance("browser"), expected)
        planned = plan_portability("browser", required_linear_memory_mib=512)
        planned["capability_reports"]["webgpu"] = True
        self.assertIsNone(plan_portability("browser", required_linear_memory_mib=512)["capability_reports"]["webgpu"])

    def test_calls_do_not_touch_files_network_or_processes(self):
        def reject(*_args, **_kwargs):
            raise AssertionError("Offline guidance must not perform external actions")

        with (
            patch.object(builtins, "open", reject),
            patch.object(socket, "socket", reject),
            patch.object(socket, "create_connection", reject),
            patch.object(subprocess, "run", reject),
            patch.object(subprocess, "Popen", reject),
        ):
            for topic in TOPICS:
                reference_guidance(topic)
            for target in ("browser", "roblox", "native"):
                out = plan_portability(target, required_linear_memory_mib=512)
                self.assertEqual(out["capability_evidence"], "caller_supplied_not_probed_or_measured")
                self.assertFalse(out["runtime_verified"])

    def test_planner_output_remains_bounded(self):
        for target in ("browser", "roblox", "native"):
            for support in (None, False, True):
                out = plan_portability(
                    target, required_linear_memory_mib=MAX_LINEAR_MEMORY_MIB,
                    memory64=support, webgpu=support, threads=support,
                    cross_origin_isolated=support, requires_threads=True,
                )
                self.assertLessEqual(len(json.dumps(out)), MAX_GUIDANCE_CHARS)


if __name__ == "__main__":
    unittest.main()
