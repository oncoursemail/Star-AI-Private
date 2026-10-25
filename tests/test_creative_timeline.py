"""Bounded creator choreography tests; no Blender/Roblox side effects."""
from __future__ import annotations

import copy
import json
import math
import random
import unittest

from star.creative_timeline import (
    audit_timeline,
    blender_nla_plan,
    build_creator_handoff,
    expand_cues,
    roblox_graph_handoff,
    validate_spec,
)


def sample():
    return {
        "version": 1, "name": "ArcaneSword", "fps": 30, "total_frames": 90,
        "clips": [
            {"id": "run", "action": "RunCycle", "duration": 30, "loop": True,
             "target": "full_body", "markers": [{"id": "FootDownL", "frame": 6}, {"id": "FootDownR", "frame": 21}]},
            {"id": "slash", "action": "SwordSlash", "duration": 28, "loop": False,
             "target": "upper_body", "markers": [{"id": "Impact", "frame": 14}]},
        ],
        "layers": [
            {"id": "locomotion", "clip": "run", "start": 0, "end": 90,
             "blend": "replace", "weight": 1, "fade_in": 0, "fade_out": 0},
            {"id": "attack", "clip": "slash", "start": 20, "end": 48,
             "blend": "add", "weight": 0.85, "fade_in": 3, "fade_out": 5},
        ],
        "cues": [
            {"id": "SwordTrail", "layer": "attack", "marker": "Impact", "kind": "vfx",
             "resource": "CinematicSwordArc", "offset": -3, "duration": 13},
            {"id": "SwordHit", "layer": "attack", "marker": "Impact", "kind": "sound",
             "resource": "SwordHitSound", "offset": 0, "duration": 1},
            {"id": "HudPulse", "layer": "attack", "marker": "Impact", "kind": "ui",
             "resource": "ComboIndicator", "offset": 0, "duration": 7, "reduced_motion": "instant"},
            {"id": "Footstep", "layer": "locomotion", "marker": "FootDownL", "kind": "sound",
             "resource": "Step", "offset": 0, "duration": 1},
        ],
        "budgets": {"max_vfx": 2, "max_ui": 2, "max_camera": 1, "require_base_pose": True},
    }


class TimelineTests(unittest.TestCase):
    def test_valid_spec_detached_no_mutation(self):
        raw = sample()
        result = validate_spec(raw)
        self.assertEqual(result, raw)
        result["clips"].clear()
        self.assertEqual(len(raw["clips"]), 2)

    def test_canonical_digest_stable(self):
        a = sample()
        b = json.loads(json.dumps(a, sort_keys=True))
        self.assertEqual(audit_timeline(a)["spec_sha256"], audit_timeline(b)["spec_sha256"])

    def test_different_spec_changes_digest(self):
        a = sample()
        b = sample()
        b["clips"][1]["action"] = "UpdatedSwordSlash"
        self.assertNotEqual(audit_timeline(a)["spec_sha256"], audit_timeline(b)["spec_sha256"])

    def test_cue_timing_and_repeated_markers(self):
        e = expand_cues(sample())
        self.assertEqual([(x["id"], x["at_frame"]) for x in e], [
            ("Footstep", 6), ("SwordTrail", 31), ("HudPulse", 34), ("SwordHit", 34),
            ("Footstep", 36), ("Footstep", 66),
        ])
        self.assertEqual(e[1]["until_frame"], 44)
        self.assertEqual(e[1]["iteration"], 0)

    def test_nla_plan_stays_1_based_and_has_no_side_effects(self):
        x = blender_nla_plan(sample())
        self.assertEqual(x["strips"][0]["frame_start"], 1)
        self.assertEqual(x["strips"][0]["frame_end_exclusive"], 91)
        self.assertEqual(x["strips"][0]["repeat"], 3)
        self.assertEqual(x["strips"][1]["blend_type"], "ADD")
        self.assertEqual(x["strips"][1]["blend_out"], 5)
        self.assertFalse(x["native_applied"])

    def test_graph_handoff_is_advisory(self):
        x = roblox_graph_handoff(sample())
        self.assertFalse(x["studio_tested"])
        self.assertIsNone(x["published_graph_asset_id"])
        self.assertEqual(x["clips"][1]["markers"], ["Impact"])

    def test_complete_handoff_no_claim_of_native_success(self):
        x = build_creator_handoff(sample())
        self.assertEqual(x["audit"]["status"], "static_checks_passed_native_review_required")
        self.assertEqual(x["audit"]["expanded_event_count"], 6)
        self.assertFalse(x["audit"]["art_approved"])

    def test_reject_bad_json_duplicate_keys_and_infinity(self):
        for bad in ('{"version":1,"version":1}', '{"x":NaN}', '{', '[]'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_spec(bad)
        invalid = sample()
        invalid["layers"][0]["weight"] = math.nan
        with self.assertRaises(ValueError):
            validate_spec(invalid)

    def test_reject_unknown_root_and_nested_fields(self):
        for path in ("root", "clip", "layer", "cue", "marker", "budget"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                data = sample()
                obj = {"root": data, "clip": data["clips"][0], "layer": data["layers"][0],
                       "cue": data["cues"][0], "marker": data["clips"][0]["markers"][0],
                       "budget": data["budgets"]}[path]
                obj["untrusted_command"] = "print('hi')"
                validate_spec(data)

    def test_bad_ids_and_repeated_ids(self):
        for s in ("../attack", "with.dot", "x\n", "", "x" * 80, "123"):
            with self.subTest(s=s), self.assertRaises(ValueError):
                data = sample()
                data["name"] = s
                validate_spec(data)
        for category in ("clips", "layers", "cues"):
            with self.subTest(category=category), self.assertRaises(ValueError):
                data = sample()
                data[category].append(copy.deepcopy(data[category][0]))
                validate_spec(data)

    def test_reject_unknown_references_and_marker(self):
        for path, value in (("clip", "Missing"), ("layer", "Missing"), ("marker", "NoSuchMarker")):
            data = sample()
            if path == "clip":
                data["layers"][0]["clip"] = value
            else:
                data["cues"][0][path] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_spec(data)

    def test_reject_non_integral_loop_and_nonloop_repetition(self):
        data = sample()
        data["layers"][0]["end"] = 89
        with self.assertRaises(ValueError):
            validate_spec(data)
        data = sample()
        data["clips"][0]["loop"] = False
        with self.assertRaises(ValueError):
            validate_spec(data)

    def test_reject_invalid_fade_and_weight(self):
        for field, value in (("fade_in", 80), ("fade_out", -1), ("weight", 0),
                             ("weight", 1.1), ("weight", True), ("weight", "1")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                data = sample()
                data["layers"][1][field] = value
                validate_spec(data)

    def test_reject_cues_outside_timeline(self):
        for cue in (0, 1):
            data = sample()
            data["cues"][cue]["offset"] = -60
            with self.assertRaises(ValueError):
                validate_spec(data)
        data = sample()
        data["cues"][0]["duration"] = 1000
        with self.assertRaises(ValueError):
            validate_spec(data)

    def test_reject_missing_ui_and_camera_reduced_motion(self):
        data = sample()
        del data["cues"][2]["reduced_motion"]
        with self.assertRaises(ValueError):
            validate_spec(data)
        data = sample()
        data["cues"][2]["kind"] = "camera"
        data["cues"][2]["reduced_motion"] = "flash"
        with self.assertRaises(ValueError):
            validate_spec(data)

    def test_reject_gameplay_authority_cue(self):
        data = sample()
        data["cues"][0]["kind"] = "damage_player"
        with self.assertRaises(ValueError):
            validate_spec(data)

    def test_no_base_pose_is_review_not_pass(self):
        data = sample()
        data["layers"][0]["start"] = 30
        x = audit_timeline(data)
        self.assertEqual(x["status"], "static_review_required")
        self.assertIn({"code": "base_pose_gap", "severity": "review", "start_frame": 0, "end_frame": 30}, x["findings"])

    def test_oversubscribed_full_body_blend_is_review(self):
        data = sample()
        data["layers"].append({"id": "alt", "clip": "run", "start": 0, "end": 90,
                                "blend": "replace", "weight": 1, "fade_in": 0, "fade_out": 0})
        result = audit_timeline(data)
        self.assertIn("base_pose_overlap", [x["code"] for x in result["findings"]])

    def test_budget_peak_half_open_semantics(self):
        data = sample()
        data["budgets"]["max_vfx"] = 0
        self.assertIn("declared_vfx_concurrency_exceeded", [x["code"] for x in audit_timeline(data)["findings"]])
        data["budgets"]["max_vfx"] = 1
        self.assertNotIn("declared_vfx_concurrency_exceeded", [x["code"] for x in audit_timeline(data)["findings"]])

    def test_repeated_event_bomb_rejected(self):
        data = sample()
        data["clips"][0]["duration"] = 2
        data["clips"][0]["markers"] = [{"id": "FootDownL", "frame": 0}]
        data["layers"][0]["end"] = 90
        data["cues"] = [data["cues"][3]] * 6
        with self.assertRaises(ValueError):
            validate_spec(data)

    def test_large_specs_rejected(self):
        data = sample()
        data["clips"][0]["action"] = "A" * 65_000
        with self.assertRaises(ValueError):
            validate_spec(data)
        with self.assertRaises(ValueError):
            validate_spec(" " * 64001)

    def test_reject_malformed_types_without_typeerror(self):
        for branch, field in (("clip", "target"), ("layer", "blend"), ("layer", "clip"),
                              ("cue", "layer"), ("cue", "kind"), ("cue", "marker")):
            for unexpected in ([], {}, None, True, 5):
                data = sample()
                node = {"clip": data["clips"][0], "layer": data["layers"][0], "cue": data["cues"][0]}[branch]
                node[field] = unexpected
                with self.subTest(field=field, unexpected=repr(unexpected)), self.assertRaises(ValueError):
                    validate_spec(data)

    def test_fuzz_input_always_valueerror_for_invalid(self):
        random.seed(9)
        seed = sample()
        for _ in range(80):
            data = copy.deepcopy(seed)
            branch = random.choice([data, data["clips"][0], data["layers"][0], data["cues"][0]])
            key = random.choice(list(branch.keys()))
            branch[key] = random.choice([[], {}, None, False, -99, float("inf"), "../a", 10_000])
            try:
                validate_spec(data)
            except ValueError:
                pass
            except Exception as exc:  # pragma: no cover - regression signal
                self.fail(f"unexpected {type(exc).__name__} for mutated field {key}: {exc}")


if __name__ == "__main__":
    unittest.main()