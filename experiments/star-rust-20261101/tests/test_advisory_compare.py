"""Synthetic contract tests; not application performance measurements."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("advisory_compare", Path(__file__).parents[1] / "advisory_compare.py")
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def run(variant="baseline", count=30, elapsed=100):
    return {"schema_version": 1, "workload_id": "synthetic-v1", "environment_id": "test-only",
            "quality_gate_id": "fixture-v1", "mode": "warm", "variant": variant,
            "rows": [{"case_id": f"case-{i}", "trial": 0, "elapsed_ms": elapsed,
                      "verified": True, "authorization_violations": 0, "timed_out": False}
                     for i in range(count)]}


class ComparisonTests(unittest.TestCase):
    def test_faster_is_review_only(self):
        result = m.compare(run(), run("candidate", elapsed=80))
        self.assertEqual(result["status"], "review_candidate")
        self.assertFalse(result["deployment_authorized"])
        self.assertFalse(result["statistical_significance_established"])

    def test_correctness_loss_rejects_fast_result(self):
        candidate = run("candidate", elapsed=1)
        candidate["rows"][0]["verified"] = False
        self.assertEqual(m.compare(run(), candidate)["status"], "reject")

    def test_other_improvement_does_not_hide_lost_case(self):
        baseline, candidate = run(), run("candidate", elapsed=1)
        baseline["rows"][1]["verified"] = False
        candidate["rows"][0]["verified"] = False
        self.assertEqual(m.compare(baseline, candidate)["status"], "reject")

    def test_unauthorized_rejects(self):
        candidate = run("candidate", elapsed=80)
        candidate["rows"][0].update(verified=False, authorization_violations=1)
        self.assertEqual(m.compare(run(), candidate)["status"], "reject")

    def test_baseline_unauthorized_is_not_clean_comparison(self):
        baseline = run()
        baseline["rows"][0].update(verified=False, authorization_violations=1)
        self.assertEqual(m.compare(baseline, run("candidate", elapsed=80))["status"], "reject")

    def test_new_timeout_rejects_even_if_previously_unverified(self):
        baseline, candidate = run(), run("candidate", elapsed=80)
        baseline["rows"][0]["verified"] = False
        candidate["rows"][0].update(verified=False, timed_out=True)
        self.assertIn("new_timeout_observed", m.compare(baseline, candidate)["reasons"])

    def test_no_speed_gain_is_inconclusive(self):
        self.assertEqual(m.compare(run(), run("candidate", elapsed=99))["status"], "inconclusive")

    def test_repeats_are_not_new_cases(self):
        a, b = run(), run("candidate", elapsed=80)
        for data in (a, b):
            for i, row in enumerate(data["rows"]):
                row.update(case_id="one-case", trial=i)
        self.assertEqual(m.compare(a, b)["status"], "inconclusive")

    def test_no_verified_outputs_not_win(self):
        a, b = run(), run("candidate", elapsed=80)
        for data in (a, b):
            for row in data["rows"]:
                row["verified"] = False
        self.assertEqual(m.compare(a, b)["status"], "inconclusive")

    def test_mismatched_context(self):
        for key in m.META_KEYS:
            candidate = run("candidate")
            candidate[key] = "cold" if key == "mode" else "different"
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.compare(run(), candidate)

    def test_missing_pair(self):
        with self.assertRaises(ValueError):
            m.compare(run(), run("candidate", count=29))

    def test_duplicate_pair(self):
        candidate = run("candidate")
        candidate["rows"].append(deepcopy(candidate["rows"][0]))
        with self.assertRaises(ValueError):
            m.validate(candidate)

    def test_row_order_does_not_matter(self):
        candidate = run("candidate", elapsed=80)
        candidate["rows"].reverse()
        self.assertEqual(m.compare(run(), candidate)["status"], "review_candidate")

    def test_invalid_numeric_inputs(self):
        for value in (True, "100", float("nan"), float("inf"), -1, 0, 10 ** 400, 86_400_001):
            candidate = run("candidate")
            candidate["rows"][0]["elapsed_ms"] = value
            with self.subTest(value=str(value)[:20]), self.assertRaises(ValueError):
                m.validate(candidate)

    def test_strict_booleans_and_integers(self):
        for key, value in (("trial", True), ("trial", 0.5), ("verified", 1),
                           ("timed_out", "false"), ("authorization_violations", False)):
            candidate = run("candidate")
            candidate["rows"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.validate(candidate)

    def test_invalid_schema_or_extra_fields(self):
        for key, value in (("schema_version", True), ("schema_version", 2), ("extra", "x")):
            data = run()
            data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.validate(data)

    def test_invalid_options(self):
        for kwargs in ({"min_cases": 1}, {"min_cases": True}, {"min_p95_improvement": 1},
                       {"min_p95_improvement": -1}, {"min_p95_improvement": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                m.compare(run(), run("candidate"), **kwargs)

    def test_verified_timeout_is_inconsistent(self):
        data = run()
        data["rows"][0]["timed_out"] = True
        with self.assertRaises(ValueError):
            m.validate(data)

    def test_input_not_modified(self):
        a, b = run(), run("candidate", elapsed=80)
        before = deepcopy((a, b))
        m.compare(a, b)
        self.assertEqual((a, b), before)

    def test_json_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.json"
            for text in ('{"x": 1, "x": 2}', '{"x": NaN}', '{"x": Infinity}', '{bad'):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(ValueError):
                    m.load_run(path)
            path.write_text(json.dumps(run()), encoding="utf-8")
            self.assertEqual(m.load_run(path), run())

    def test_percentile_includes_failed_latency(self):
        a, b = run(count=100), run("candidate", count=100, elapsed=50)
        for i in range(10):
            a["rows"][i]["verified"] = False
            b["rows"][i].update(verified=False, elapsed_ms=200)
        result = m.compare(a, b)
        self.assertEqual(result["candidate"]["p95_ms"], 200)
        self.assertEqual(result["status"], "inconclusive")

    def test_empty_and_excessive_rows(self):
        for rows in ([], [run()["rows"][0]] * (m.MAX_ROWS + 1)):
            data = run()
            data["rows"] = rows
            with self.assertRaises(ValueError):
                m.validate(data)


if __name__ == "__main__":
    unittest.main()
