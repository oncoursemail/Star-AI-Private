"""Independent developer checks for supplied-trace diagnostics; not engine evidence.

Run: python ik_independent_review.py --module /path/to/star/ik_trace_quality.py
When kept under a repository's benchmarks/, the sibling star/ path is the default.
This script does not alter protected tests, evaluation baselines, or runtime settings.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest


parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--module", type=Path, default=Path(__file__).resolve().parents[1] / "star" / "ik_trace_quality.py")
options, remaining = parser.parse_known_args()
MODULE_PATH = options.module.resolve()
spec = importlib.util.spec_from_file_location("ik_trace_review_target", MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit("Cannot load diagnostic module")
ik = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ik)


def point(t=0.0, effector=None, target=None, **extras):
    effector = [0.0, 0.0, 0.0] if effector is None else effector
    return {"t": t, "effector": effector, "target": effector[:] if target is None else target, **extras}


def trace(samples=None, scale=1.0):
    return {"schema_version": 1, "rig_scale": scale, "chains": [{"name": "hand", "samples": [point()] if samples is None else samples}]}


def metrics(payload):
    return ik.report_ik_trace(payload)["chains"][0]["metrics"]


def plant(t, world, local, anchor=None, support="platform"):
    return point(t, world, contact=True, contact_frame=support, contact_position=local,
                 contact_anchor=local[:] if anchor is None else anchor)


class AnalyticPhysics(unittest.TestCase):
    def assertNear(self, actual, expected, tolerance=1e-10):
        self.assertTrue(math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance), (actual, expected))

    def test_static_position_and_scale(self):
        m = metrics(trace([point(effector=[3, 4, 0], target=[0, 0, 0])], scale=5))
        self.assertEqual(m["position_error_rig"]["max"], 1)
        self.assertEqual(m["position_error_rig"]["rms"], 1)

    def test_irregular_constant_velocity(self):
        # A 3-4-5 velocity vector, normalized by a five-unit rig.
        times = [0, 0.1, 0.55, 1.9, 3.2]
        payload = trace([point(t, [3*t, 4*t, 0]) for t in times], scale=5)
        m = metrics(payload)
        for key in ["mean", "rms", "max", "p95"]:
            self.assertNear(m["speed_rig_per_second"][key], 1)
        self.assertNear(m["acceleration_rig_per_second2"]["max"], 0)
        self.assertEqual(m["speed_rig_per_second"]["samples"], 4)

    def test_irregular_acceleration_midpoints(self):
        # x=t^2: interval velocities belong at midpoints; acceleration is 2.
        m = metrics(trace([point(t, [t*t, 0, 0]) for t in [0, 1, 3, 6]]))
        self.assertNear(m["acceleration_rig_per_second2"]["mean"], 2)
        self.assertNear(m["acceleration_rig_per_second2"]["max"], 2)
        self.assertEqual(m["acceleration_rig_per_second2"]["samples"], 2)

    def test_summary_nearest_rank_and_rms(self):
        payload = trace([point(i, [i, 0, 0], target=[0, 0, 0]) for i in range(20)])
        s = metrics(payload)["position_error_rig"]
        self.assertEqual(s["samples"], 20)
        self.assertNear(s["mean"], 9.5)
        self.assertEqual(s["p95"], 18)
        self.assertEqual(s["max"], 19)
        self.assertNear(s["rms"], math.sqrt(sum(i*i for i in range(20))/20))

    def test_missing_observations_are_null(self):
        m = metrics(trace())
        for key in ["orientation_error_deg", "speed_rig_per_second", "acceleration_rig_per_second2",
                    "angular_speed_deg_per_second", "contact_error_rig", "contact_drift_rig", "contact_slip_speed_rig_per_second"]:
            self.assertEqual(m[key], {"samples": 0, "mean": None, "rms": None, "p95": None, "max": None})

    def test_orientation_quarter_turn(self):
        q = [0, 0, math.sqrt(0.5), math.sqrt(0.5)]
        m = metrics(trace([point(effector_q=q, target_q=[0, 0, 0, 1])]))
        self.assertNear(m["orientation_error_deg"]["max"], 90)

    def test_quaternion_antipodes(self):
        q = [0.5, 0.5, 0.5, 0.5]
        negative = [-v for v in q]
        m = metrics(trace([point(0, effector_q=q, target_q=negative), point(1, effector_q=negative, target_q=q)]))
        self.assertNear(m["orientation_error_deg"]["max"], 0)
        self.assertNear(m["angular_step_deg"]["max"], 0)

    def test_small_angle_preserved(self):
        angle = 1e-8
        q = [0, 0, math.sin(angle/2), math.cos(angle/2)]
        m = metrics(trace([point(effector_q=q, target_q=[0, 0, 0, 1])]))
        self.assertNear(m["orientation_error_deg"]["max"], math.degrees(angle), tolerance=1e-14)

    def test_norm_tolerance_normalizes_small_error(self):
        m = metrics(trace([point(effector_q=[0, 0, 0, 1.0005], target_q=[0, 0, 0, 1])]))
        self.assertNear(m["orientation_error_deg"]["max"], 0)

    def test_missing_orientation_breaks_angular_adjacency(self):
        m = metrics(trace([point(0, effector_q=[0, 0, 0, 1], target_q=[0, 0, 0, 1]), point(1),
                           point(2, effector_q=[0, 0, 1, 0], target_q=[0, 0, 1, 0])]))
        self.assertEqual(m["orientation_error_deg"]["samples"], 2)
        self.assertEqual(m["angular_step_deg"]["samples"], 0)

    def test_angular_speed_uses_time(self):
        m = metrics(trace([point(0, effector_q=[0, 0, 0, 1], target_q=[0, 0, 0, 1]),
                           point(0.5, effector_q=[0, 0, 1, 0], target_q=[0, 0, 1, 0])]))
        self.assertNear(m["angular_speed_deg_per_second"]["max"], 360)

    def test_report_never_proves_quality(self):
        report = ik.report_ik_trace(trace())
        self.assertIs(report["quality_proven"], False)
        self.assertIs(report["engine_capture_verified"], False)
        self.assertTrue(report["limitations"])

    def test_input_not_mutated(self):
        payload = trace([plant(0, [0, 0, 0], [1, 0, 0]), plant(1, [1, 0, 0], [1, 0, 0])])
        before = copy.deepcopy(payload)
        ik.report_ik_trace(payload)
        self.assertEqual(payload, before)

    def test_randomized_translation_and_scale_invariance(self):
        rng = random.Random(37051)
        for case in range(25):
            times = [0.0]
            for unused in range(5):
                times.append(times[-1] + rng.uniform(0.1, 1.5))
            base = trace([point(t, [rng.uniform(-3, 3) for unused in range(3)],
                                     [rng.uniform(-3, 3) for unused in range(3)]) for t in times], scale=2)
            factor = rng.uniform(0.3, 5)
            shift = [rng.uniform(-10, 10) for unused in range(3)]
            transformed = copy.deepcopy(base)
            transformed["rig_scale"] *= factor
            for sample in transformed["chains"][0]["samples"]:
                for key in ["effector", "target"]:
                    sample[key] = [(v + s)*factor for v, s in zip(sample[key], shift)]
            a, b = metrics(base), metrics(transformed)
            for name in a:
                for statistic in ["mean", "rms", "p95", "max"]:
                    if a[name][statistic] is not None:
                        self.assertNear(a[name][statistic], b[name][statistic])


class ContactSemantics(unittest.TestCase):
    def test_moving_rotating_platform_has_zero_local_slip(self):
        # Fixed support-local point, while world-space pose translates/rotates.
        samples = [plant(0, [1, 0, 0], [1, 0, 0]), plant(1, [10, 1, 0], [1, 0, 0]),
                   plant(3, [19, 0, 0], [1, 0, 0])]
        m = metrics(trace(samples))
        self.assertGreater(m["speed_rig_per_second"]["max"], 0)
        for key in ["contact_error_rig", "contact_drift_rig", "contact_slip_speed_rig_per_second"]:
            self.assertEqual(m[key]["max"], 0)

    def test_contact_residual_is_distinct_from_drift(self):
        samples = [plant(0, [0, 0, 0], [1, 0, 0], anchor=[0, 0, 0]),
                   plant(2, [0, 0, 0], [1, 0, 0], anchor=[0, 0, 0])]
        m = metrics(trace(samples))
        self.assertEqual(m["contact_error_rig"]["max"], 1)
        self.assertEqual(m["contact_drift_rig"]["max"], 0)
        self.assertEqual(m["contact_slip_speed_rig_per_second"]["max"], 0)

    def test_local_slip_uses_scale_and_irregular_dt(self):
        samples = [plant(0, [0, 0, 0], [0, 0, 0], anchor=[0, 0, 0]),
                   plant(2, [0, 0, 0], [2, 0, 0], anchor=[0, 0, 0]),
                   plant(5, [0, 0, 0], [5, 0, 0], anchor=[0, 0, 0])]
        m = metrics(trace(samples, scale=2))
        self.assertEqual(m["contact_drift_rig"]["max"], 2.5)
        self.assertEqual(m["contact_slip_speed_rig_per_second"]["max"], 0.5)

    def test_reacquisition_resets_for_false_missing_or_new_support(self):
        for middle in [point(1, contact=False), point(1), point(1, contact=True),
                       plant(1, [0, 0, 0], [100, 0, 0], support="different")]:
            with self.subTest(middle=middle):
                samples = [plant(0, [0, 0, 0], [0, 0, 0]), middle,
                           plant(2, [0, 0, 0], [10, 0, 0])]
                m = metrics(trace(samples))
                self.assertEqual(m["contact_drift_rig"]["samples"], 0)
                self.assertEqual(m["contact_slip_speed_rig_per_second"]["samples"], 0)

    def test_reset_allows_new_anchor(self):
        payload = trace([plant(0, [0, 0, 0], [0, 0, 0]), point(1, contact=False),
                         plant(2, [0, 0, 0], [5, 0, 0])])
        report = ik.report_ik_trace(payload)["chains"][0]
        self.assertEqual(report["measured_contact_spans"], 2)
        self.assertEqual(report["contact_state_observations"], 3)
        self.assertEqual(report["contact_true_observations"], 2)

    def test_anchor_cannot_follow_foot_to_hide_slip(self):
        with self.assertRaises(ValueError):
            ik.report_ik_trace(trace([plant(0, [0, 0, 0], [0, 0, 0]),
                                      plant(1, [0, 0, 0], [5, 0, 0])]))


class ValidationBoundaries(unittest.TestCase):
    def invalid(self, payload):
        with self.assertRaises(ValueError):
            ik.report_ik_trace(payload)

    def test_nonfinite_boolean_and_huge_numbers(self):
        bad = [True, False, None, "1", float("nan"), float("inf"), -float("inf"), 10**1000]
        for value in bad:
            with self.subTest(value_type=type(value).__name__):
                self.invalid(trace([point(effector=[value, 0, 0])]))
                self.invalid(trace(scale=value))
                self.invalid(trace([point(t=value)]))

    def test_schema_strictness(self):
        for version in [True, False, 1.0, "1", 2, None]:
            p = trace(); p["schema_version"] = version; self.invalid(p)
        for location in ["trace", "chain", "sample"]:
            p = trace()
            target = p if location == "trace" else p["chains"][0] if location == "chain" else p["chains"][0]["samples"][0]
            target["quality_proven"] = True
            self.invalid(p)

    def test_arrays_names_and_counts(self):
        for vector in [[], [0, 0], [0, 0, 0, 0], (0, 0, 0), {"x": 0, "y": 0, "z": 0}]:
            self.invalid(trace([point(effector=vector, target=[0, 0, 0])]))
        for name in ["", "bad\nname", "x"*129, 4]:
            p = trace(); p["chains"][0]["name"] = name; self.invalid(p)
        p = trace(); p["chains"] *= 2; self.invalid(p)
        self.invalid(trace([]))
        p = trace(); p["chains"] = []; self.invalid(p)

    def test_timestamp_order_and_range(self):
        for first, second in [(0, 0), (1, 0), (0, 0.0000001), (-1, 0), (0, 86401)]:
            self.invalid(trace([point(first), point(second)]))

    def test_microsecond_resolution_near_day_boundary(self):
        # Decimal one-microsecond steps survive subtraction rounding at large t.
        m = metrics(trace([point(86399.0), point(86399.000001)]))
        self.assertEqual(m["speed_rig_per_second"]["samples"], 1)
        self.invalid(trace([point(86399.0), point(86399.0000005)]))

    def test_unnormalized_or_partial_quaternions(self):
        for q in [[0, 0, 0, 0], [0, 0, 0, 2], [0, 0, 0, -2], [True, 0, 0, 1], [0, 0, 0], [0, 0, 0, 1.01]]:
            self.invalid(trace([point(effector_q=q, target_q=[0, 0, 0, 1])]))
        self.invalid(trace([point(effector_q=[0, 0, 0, 1])]))
        self.invalid(trace([point(target_q=[0, 0, 0, 1])]))

    def test_contact_observation_contract(self):
        for extras in [dict(contact=1), dict(contact="true"), dict(contact_position=[0, 0, 0]),
                       dict(contact=True, contact_position=[0, 0, 0]),
                       dict(contact=False, contact_frame="p", contact_position=[0, 0, 0], contact_anchor=[0, 0, 0])]:
            self.invalid(trace([point(**extras)]))

    def test_resource_counts(self):
        self.invalid(trace([point()]*(ik.MAX_SAMPLES+1)))
        p = trace(); p["chains"] = [{"name": str(i), "samples": [point()]} for i in range(ik.MAX_CHAINS+1)]; self.invalid(p)
        p = trace(); p["chains"] = [{"name": str(i), "samples": [point()]*ik.MAX_SAMPLES} for i in range(3)]; self.invalid(p)

    def test_extreme_valid_values_stay_finite(self):
        payload = trace([point(0, [-1e9]*3, [1e9]*3), point(1e-6, [1e9]*3, [-1e9]*3),
                         point(2e-6, [-1e9]*3, [1e9]*3)], scale=1e-6)
        report = ik.report_ik_trace(payload)
        json.dumps(report, allow_nan=False)
        for summary in report["chains"][0]["metrics"].values():
            for key in ["mean", "rms", "p95", "max"]:
                self.assertTrue(summary[key] is None or math.isfinite(summary[key]))


class CliBoundaries(unittest.TestCase):
    def run_cli(self, data):
        with tempfile.TemporaryDirectory(prefix="ik-review-") as directory:
            path = Path(directory)/"trace.json"
            path.write_bytes(data)
            return subprocess.run([sys.executable, str(MODULE_PATH), str(path)], capture_output=True, timeout=10)

    def test_valid_cli_json(self):
        process = self.run_cli(json.dumps(trace()).encode())
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertIs(report["quality_proven"], False)

    def test_duplicate_keys_rejected(self):
        process = self.run_cli(b'{"schema_version":1,"schema_version":1,"rig_scale":1,"chains":[]}')
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"duplicate", process.stderr)
        self.assertEqual(process.stdout, b"")

    def test_decode_and_parse_errors(self):
        for data in [b"\xff\xffx", b"{", b'{"rig_scale":NaN}', b'{"rig_scale":Infinity}', b"["*1500+b"]"*1500]:
            with self.subTest(prefix=data[:20]):
                process = self.run_cli(data)
                self.assertEqual(process.returncode, 2, process.stderr)
                self.assertEqual(process.stdout, b"")
                self.assertNotIn(b"Traceback", process.stderr)

    def test_oversized_file_rejected(self):
        process = self.run_cli(b" "*(ik.MAX_FILE_BYTES+1))
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"byte limit", process.stderr)
        self.assertEqual(process.stdout, b"")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Named-pipe probe requires POSIX mkfifo")
    def test_named_pipe_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory(prefix="ik-review-fifo-") as directory:
            path = Path(directory)/"input.json"
            os.mkfifo(path)
            process = subprocess.run([sys.executable, str(MODULE_PATH), str(path)], capture_output=True, timeout=2)
            self.assertEqual(process.returncode, 2)
            self.assertIn(b"regular file", process.stderr)
            self.assertEqual(process.stdout, b"")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *remaining])
