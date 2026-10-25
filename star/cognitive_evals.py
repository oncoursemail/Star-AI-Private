"""Explicit, digest-pinned import of STAR's existing development evaluation results.

NO automatic discovery, background scans, network requests, grading, model calls,
or permission escalation. A digest match proves file integrity only relative to
the caller-approved digest, NOT honest independent grading; the trusted operator
must verify the evaluator and its provenance before passing owner_confirmed=True.
Sealed holdouts are intentionally never eligible for this import.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .cognitive_governor import GradeReceipt, OutcomeLedger, _label

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_COMMIT = re.compile(r"[a-f0-9]{40}\Z")
_FINGERPRINT = re.compile(r"[a-f0-9]{12}\Z")
_CASE = re.compile(r"[A-Za-z0-9]{2,12}-[0-9]{1,5}\Z")
_ALLOWED_SUITES = frozenset({"golden-tasks-v2.json", "golden-tasks-creation-v1.json"})
_MAX_SIZE = 4_000_000


@dataclass(frozen=True)
class CheckedDevelopmentRun:
    """Reviewed source digest, not a cryptographic proof of evaluator behavior."""
    source_sha256: str
    suite_name: str
    model: str
    revision: str
    receipts: tuple[GradeReceipt, ...]


def preview_run(path: Path, *, expected_sha256: str, project: str) -> CheckedDevelopmentRun:
    """Validate a reviewed local development result, without recording anything."""
    _label(project, "project")
    if not isinstance(path, Path) or path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Only an existing ordinary local evaluator result is allowed")
    if not _SHA.fullmatch(expected_sha256):
        raise ValueError("Expected a full approved lowercase SHA-256")
    if not path.is_file() or not 0 < path.stat().st_size <= _MAX_SIZE:
        raise ValueError("Missing/oversized evaluation result")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError("Evaluator result does not match the owner's pinned digest")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("complete") is not True:
        raise ValueError("Only a complete schema-1 evaluation report is admissible")
    suite = payload.get("suite")
    run = payload.get("run")
    tasks = payload.get("tasks")
    if not isinstance(suite, dict) or not isinstance(run, dict) or not isinstance(tasks, dict):
        raise ValueError("Malformed evaluation document")
    suite_name = suite.get("file")
    if suite_name not in _ALLOWED_SUITES or not _SHA.fullmatch(str(suite.get("sha256", ""))):
        raise ValueError("Sealed holdouts and unknown task suites may not enter feedback")
    if (run.get("runner") != "star.eval_runner/1" or run.get("app_dirty") is not False
            or not _COMMIT.fullmatch(str(run.get("app_commit", "")))
            or not _FINGERPRINT.fullmatch(str(run.get("fingerprint", "")))):
        raise ValueError("Missing expected clean evaluator fingerprint and app revision")
    model = _label(run.get("model"), "model")
    # Revision includes exact app commit and evaluator configuration fingerprint;
    # never mix changed prompts, skill packs or a different engine as one population.
    revision = "app" + run["app_commit"][:12] + "." + run["fingerprint"]
    selected = suite.get("selected")
    if not isinstance(selected, list) or not 1 <= len(selected) <= 200 or len(selected) != len(set(selected)):
        raise ValueError("Invalid suite selection")
    if not tasks or len(tasks) > 200 or set(selected) != set(tasks):
        raise ValueError("Missing or extra graded cases")
    receipts = []
    for case_id, item in sorted(tasks.items()):
        if not isinstance(case_id, str) or not _CASE.fullmatch(case_id) or not isinstance(item, dict):
            raise ValueError("Invalid case identifier or task row")
        outcome = item.get("status")
        if outcome == "skipped":
            continue
        if outcome not in ("pass", "fail", "error"):
            raise ValueError("Unknown outcome; do not interpret it as a pass")
        expected_bool = outcome == "pass"
        if outcome != "error" and item.get("passed") is not expected_bool:
            raise ValueError("Contradictory pass/status fields")
        elapsed = item.get("seconds")
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 86400:
            raise ValueError("Missing or unreasonable evaluator duration")
        millis = round(elapsed * 1000)
        # Task families are explicit identifiers, never raw task prompts.
        family = ("creation" if suite_name == "golden-tasks-creation-v1.json" else "roblox")
        family += "-" + case_id.split("-", 1)[0]
        receipts.append(GradeReceipt(
            project=project, family=family, model=model, revision=revision,
            run_id="run" + actual[:20], case_id=case_id,
            result=outcome, elapsed_ms=millis,
            verifier="independent_eval", evidence_sha256=actual
        ))
    if not receipts:
        raise ValueError("No independently checkable pass/fail/error rows")
    return CheckedDevelopmentRun(actual, suite_name, model, revision, tuple(receipts))


def record_approved_run(ledger: OutcomeLedger, preview: CheckedDevelopmentRun,
                        *, owner_confirmed: bool = False) -> tuple[int, int]:
    """Import only after a real operator has reviewed source and evaluator provenance."""
    if owner_confirmed is not True:
        raise PermissionError("Reviewed digest, grader and test provenance require operator confirmation")
    if not isinstance(ledger, OutcomeLedger) or not isinstance(preview, CheckedDevelopmentRun):
        raise TypeError("Expected valid ledger and checked run")
    added = duplicates = 0
    for item in preview.receipts:
        if ledger.record_grade(item):
            added += 1
        else:
            duplicates += 1
    return added, duplicates


def main() -> int:
    parser = argparse.ArgumentParser(description="Operator-reviewed development eval import")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--approved-sha256", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--record-reviewed", action="store_true",
                        help="Explicit operator confirmation; absent means read-only preview")
    args = parser.parse_args()
    preview = preview_run(args.file, expected_sha256=args.approved_sha256, project=args.project)
    result = {"suite": preview.suite_name, "source_sha256": preview.source_sha256,
              "model": preview.model, "revision": preview.revision,
              "cases": len(preview.receipts)}
    if args.record_reviewed:
        if args.db is None:
            parser.error("--record-reviewed requires --db")
        result["added"], result["duplicates"] = record_approved_run(
            OutcomeLedger(args.db), preview, owner_confirmed=True
        )
    else:
        result["status"] = "PREVIEW ONLY - nothing stored"
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
