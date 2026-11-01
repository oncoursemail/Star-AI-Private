"""Offline tests for digest-pinned, operator-reviewed development eval import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from star.cognitive_evals import preview_run, record_approved_run
from star.cognitive_governor import OutcomeLedger


class CognitiveEvalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "report.json"
        self.db = Path(self.temp.name) / "private" / "cognitive.sqlite3"

    def report(self):
        return {
            "schema": 1,
            "suite": {
                "file": "golden-tasks-v2.json",
                "sha256": "a" * 64,
                "tasks_total": 50,
                "automated": 34,
                "selected": ["ANI-05", "ENG-03"],
            },
            "run": {
                "app_commit": "b" * 40,
                "app_dirty": False,
                "runner": "star.eval_runner/1",
                "model": "star-fast",
                "fingerprint": "c" * 12,
            },
            "complete": True,
            "tasks": {
                "ANI-05": {"status": "pass", "passed": True, "seconds": 1.2},
                "ENG-03": {"status": "fail", "passed": False, "seconds": 0.1},
            },
        }

    def save(self, report):
        self.path.write_text(json.dumps(report), encoding="utf-8")
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def preview(self, report):
        digest = self.save(report)
        return preview_run(self.path, expected_sha256=digest, project="OwnedDev")

    def test_preview_no_database_and_correct_scoping(self):
        r = self.preview(self.report())
        self.assertEqual((r.suite_name, r.model), ("golden-tasks-v2.json", "star-fast"))
        self.assertEqual(len(r.receipts), 2)
        self.assertEqual([x.family for x in r.receipts], ["roblox-ANI", "roblox-ENG"])
        self.assertEqual([x.result for x in r.receipts], ["pass", "fail"])
        self.assertFalse(self.db.exists())

    def test_requires_explicit_approval_to_record(self):
        r = self.preview(self.report())
        ledger = OutcomeLedger(self.db)
        with self.assertRaises(PermissionError):
            record_approved_run(ledger, r)
        self.assertFalse(self.db.exists())
        self.assertEqual(record_approved_run(ledger, r, owner_confirmed=True), (2, 0))
        self.assertEqual(record_approved_run(ledger, r, owner_confirmed=True), (0, 2))
        s = ledger.summary(project="OwnedDev", family="roblox-ENG",
                           model=r.model, revision=r.revision)
        self.assertEqual((s.distinct_cases, s.failed), (1, 1))

    def test_wrong_digest_refused_without_side_effects(self):
        self.save(self.report())
        with self.assertRaises(ValueError):
            preview_run(self.path, expected_sha256="0" * 64, project="OwnedDev")
        self.assertFalse(self.db.exists())

    def test_unapproved_or_unknown_suite_refused(self):
        for suite in ("sealed-holdout.json", "golden-tasks-blind-v2.json", "../golden-tasks-v2.json"):
            data = self.report()
            data["suite"]["file"] = suite
            with self.assertRaises(ValueError):
                self.preview(data)

    def test_dirty_app_wrong_runner_and_invalid_provenance_refused(self):
        for name, value in (("app_dirty", True), ("runner", "model-score/1"),
                            ("app_commit", "short"), ("fingerprint", "invalid")):
            data = self.report()
            data["run"][name] = value
            with self.assertRaises(ValueError):
                self.preview(data)

    def test_incomplete_schema_and_bad_case_selection_refused(self):
        for mutation in ("incomplete", "wrong_schema", "missing_case", "extra_case"):
            data = self.report()
            if mutation == "incomplete":
                data["complete"] = False
            elif mutation == "wrong_schema":
                data["schema"] = 2
            elif mutation == "missing_case":
                del data["tasks"]["ANI-05"]
            else:
                data["tasks"]["UI-01"] = {"status": "pass", "passed": True, "seconds": 0}
            with self.assertRaises(ValueError):
                self.preview(data)

    def test_mismatched_verdict_and_missing_time_refused(self):
        for mutation in ("status_disagrees", "missing_time", "negative_time", "nan"):
            data = self.report()
            if mutation == "status_disagrees":
                data["tasks"]["ANI-05"]["passed"] = False
            elif mutation == "missing_time":
                del data["tasks"]["ANI-05"]["seconds"]
            elif mutation == "negative_time":
                data["tasks"]["ANI-05"]["seconds"] = -1
            else:
                data["tasks"]["ANI-05"]["seconds"] = float("nan")
            with self.assertRaises(ValueError):
                self.preview(data)

    def test_skipped_tasks_do_not_count_as_pass(self):
        data = self.report()
        data["tasks"]["ENG-03"]["status"] = "skipped"
        data["tasks"]["ENG-03"]["passed"] = False
        r = self.preview(data)
        self.assertEqual(len(r.receipts), 1)
        self.assertEqual(r.receipts[0].result, "pass")

    def test_all_skipped_refused(self):
        data = self.report()
        for v in data["tasks"].values():
            v["status"] = "skipped"
        with self.assertRaises(ValueError):
            self.preview(data)

    def test_oversize_file_and_symlink_refused(self):
        self.path.write_bytes(b"x" * 4_000_001)
        with self.assertRaises(ValueError):
            preview_run(self.path, expected_sha256=hashlib.sha256(
                self.path.read_bytes()).hexdigest(), project="OwnedDev")
        target = Path(self.temp.name) / "target.json"
        target.write_text("{}", encoding="utf-8")
        link = Path(self.temp.name) / "link.json"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(ValueError):
            preview_run(link, expected_sha256="0" * 64, project="OwnedDev")

    def test_cli_preview_does_not_write(self):
        digest = self.save(self.report())
        result = subprocess.run([sys.executable, "-m", "star.cognitive_evals",
                                 "--file", str(self.path), "--approved-sha256", digest,
                                 "--project", "OwnedDev", "--db", str(self.db)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREVIEW ONLY", result.stdout)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
