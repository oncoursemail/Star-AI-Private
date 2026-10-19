"""Adversarial evidence checks and real failing-to-passing pytest replay."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from star.debug_common import MAX_REPORT_BYTES, SCHEMA, redact_debug, sanitize_tree, write_report
from star.debug_evidence import (
    DebugEvidenceTools, TOOL_NAMES, compare_reports, diagnostic_plan, read_report,
    source_window, summarize_report,
)
from star.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
TEST_SOURCE = "def test_value():\n    assert True\n"
DIGEST = hashlib.sha256(TEST_SOURCE.encode()).hexdigest()


def report(*, passed=False, run_id=None, producer="pytest"):
    outcome = "passed" if passed else "failed"
    return {
        "schema": SCHEMA, "producer": producer, "run_id": run_id or ("candidate" if passed else "baseline"),
        "status": outcome, "exit_code": 0 if passed else 1, "truncated": False,
        "test_hashes": {"test_app.py": DIGEST}, "harness_hashes": {},
        "tests": [{"nodeid": "test_app.py::test_value", "file": "test_app.py", "phase": "call", "outcome": outcome}],
        "failures": [] if passed else [{"nodeid": "test_app.py::test_value", "file": "test_app.py", "line": 2,
                                       "exception_type": "AssertionError", "message": "assert 2 == 3"}],
    }


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "test_app.py").write_text(TEST_SOURCE, encoding="utf-8")
    return Workspace(root)


def save(workspace, payload, filename="capture.json"):
    write_report(workspace.root / filename, payload)
    return read_report(workspace, filename)


@pytest.mark.parametrize("secret", [
    "password=abc", "api_key='tiny'", 'access_token: "short"',
    "Authorization: Bearer small", "Cookie: session=tiny",
    "https://someone:short@example.com/fail?token=tiny#private",
    'clientSecret="tiny"', "refreshToken=short", "aws_access_key_id=small", "access_key=abc",
    '{"Authorization": "Bearer tiny", "Cookie": "session=small"}',
    'payload={"api_key":"tiny"}', '{"message": "password=small"}',
    'tokenizer={"api_key":"tiny"}', '{"tokens": "password=small"}',
])
def test_diagnostic_redaction_covers_short_values_before_output(secret):
    result = redact_debug(secret)
    assert not any(value in result for value in ("abc", "tiny", "short", "small", "someone", "private"))


def test_hashes_for_files_named_after_tokens_remain_comparable():
    clean = sanitize_tree({"test_hashes": {"tests/test_tokens.py": DIGEST}, "access_token": "tiny"})
    assert clean["test_hashes"]["tests/test_tokens.py"] == DIGEST
    assert clean["access_token"] == "[REDACTED]"


@pytest.mark.parametrize("name", ["clientSecret", "refreshToken", "AWSAccessKeyID", "access_key", "password"])
def test_named_variable_values_are_redacted_when_imported(name):
    clean = sanitize_tree({"variables": [{"name": name, "value": "tiny", "scope": "locals"}], name: "tiny"})
    assert "tiny" not in json.dumps(clean)
    assert clean["variables"][0]["scope"] == "locals"


def test_keys_that_collapse_after_redaction_are_rejected():
    with pytest.raises(ValueError, match="collide"):
        sanitize_tree({"test[password=first]": "one", "test[password=second]": "two"})


def test_repeated_redaction_preserves_parameter_display_identically():
    first = redact_debug("test.py::test_value[password=first]")
    assert first == redact_debug("test.py::test_value[password=second]")
    assert redact_debug(first) == first
    assert redact_debug(redact_debug(first)) == first


def test_report_write_is_atomic_redacted_and_explicit(workspace):
    target = workspace.root / "capture.json"
    target.write_text("old", encoding="utf-8")
    write_report(target, {**report(), "message": "password=small"})
    assert "small" not in target.read_text(encoding="utf-8")
    assert not list(workspace.root.glob(".star-debug-*"))
    with pytest.raises(ValueError):
        write_report(workspace.root / "missing" / "capture.json", report())
    with pytest.raises(ValueError):
        write_report(workspace.root / "capture.txt", report())


@pytest.mark.parametrize("raw", [
    '{"schema":"star-debug-evidence-v1","schema":"other"}',
    '{"schema":"star-debug-evidence-v1","producer":"pytest","status":"passed","duration_ms":NaN}',
    "[1,2,3]", "{broken", "[]" * 100,
])
def test_invalid_json_is_rejected(workspace, raw):
    (workspace.root / "capture.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        read_report(workspace, "capture.json")


@pytest.mark.parametrize(("key", "value"), [
    ("producer", "arbitrary-shell"), ("producer", []), ("producer", {}),
    ("tests", [{}]), ("tests", "not-a-list"),
    ("tests", [{"nodeid": "case", "outcome": []}]),
    ("failures", ["wrong"]), ("exit_code", True), ("duration_ms", "fast"),
    ("truncated", "false"), ("test_hashes", {"test_app.py": 123}),
    ("harness_hashes", {"conftest.py": []}), ("duration_ms", -1),
])
def test_invalid_report_shapes_are_rejected(workspace, key, value):
    payload = report()
    payload[key] = value
    (workspace.root / "capture.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        read_report(workspace, "capture.json")


def test_read_limits_cover_size_nesting_and_bad_numbers(workspace):
    file = workspace.root / "capture.json"
    file.write_bytes(b" " * (MAX_REPORT_BYTES + 1))
    with pytest.raises(ValueError):
        read_report(workspace, "capture.json")
    payload = report()
    nested = "x"
    for _ in range(20):
        nested = [nested]
    payload["extra"] = nested
    file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        read_report(workspace, "capture.json")
    with pytest.raises(ValueError):
        sanitize_tree({"number": float("inf")})


def test_workspace_boundary_and_protected_files_apply(workspace, tmp_path):
    (tmp_path / "outside.json").write_text(json.dumps(report()), encoding="utf-8")
    (workspace.root / ".env.json").write_text(json.dumps(report()), encoding="utf-8")
    for path in ("../outside.json", str(tmp_path / "outside.json"), ".env.json"):
        with pytest.raises(PermissionError):
            read_report(workspace, path)


def test_external_symlink_cannot_be_read_or_written(workspace, tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(report()), encoding="utf-8")
    link = workspace.root / "link.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This account cannot create symbolic links")
    with pytest.raises(PermissionError):
        read_report(workspace, "link.json")
    with pytest.raises(PermissionError):
        write_report(link, report(passed=True))
    assert json.loads(outside.read_text(encoding="utf-8"))["status"] == "failed"


def test_source_window_is_small_redacted_and_does_not_import(workspace):
    source = "raise RuntimeError('must never execute')\npassword = 'small'\n" + "x = 1\n" * 80
    (workspace.root / "reproducer.py").write_text(source, encoding="utf-8")
    result = source_window(workspace, "reproducer.py", 2, radius=1)
    assert result["start_line"] == 1 and result["end_line"] == 3
    assert len(result["lines"]) == 3
    assert "small" not in json.dumps(result)
    assert result["sha256"] == hashlib.sha256((workspace.root / "reproducer.py").read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        source_window(workspace, "reproducer.py", 99)
    with pytest.raises(ValueError):
        source_window(workspace, "reproducer.py", 1, radius=13)


def test_failure_grouping_keeps_source_and_observed_counts(workspace):
    payload = report()
    payload["failures"] *= 7
    summary = summarize_report(workspace, save(workspace, payload))
    assert summary["failing_test_count"] == 1
    assert summary["failure_group_count"] == 1
    group = summary["failure_groups"][0]
    assert group["count"] == 7 and group["source"]["start_line"] == 1
    assert summary["execution"] == "read_only_evidence"
    assert summary["verified_fix"] is False
    assert summary["next_probe"]["classification"] == "assertion"


def test_summary_stays_under_agent_output_budget(workspace):
    payload = report()
    payload["failures"] = [{"message": "m" * 12000, "file": "f" * 500, "line": i} for i in range(100)]
    payload["variables"] = [{"value": "v" * 12000} for _ in range(20)]
    summary = summarize_report(workspace, save(workspace, payload))
    assert len(json.dumps(summary, ensure_ascii=False)) <= 24000
    assert summary["verified_fix"] is False


def test_matching_replay_is_consistent_evidence_never_a_certificate():
    result = compare_reports(report(), report(passed=True))
    assert result["status"] == "evidence_consistent"
    assert result["reasons"] == [] and result["verified_fix"] is False
    assert "does not authenticate" in result["notice"]


def test_distinct_parameter_cases_cannot_collapse_after_reader_redaction(workspace):
    before, after = report(), report(passed=True)
    before["tests"][0]["nodeid"] = "test_app.py::test_value[password=first]"
    after["tests"][0]["nodeid"] = "test_app.py::test_value[password=second]"
    # Simulate legacy reports without collector-side identity hashes. The reader
    # must capture identity before it sanitizes display names.
    for filename, value in (("baseline.json", before), ("candidate.json", after)):
        (workspace.root / filename).write_text(json.dumps(value), encoding="utf-8")
    first, second = read_report(workspace, "baseline.json"), read_report(workspace, "candidate.json")
    assert first["tests"][0]["nodeid"] == second["tests"][0]["nodeid"]
    assert first["tests"][0]["identity_sha256"] != second["tests"][0]["identity_sha256"]
    assert compare_reports(first, second)["status"] == "inconclusive"


def test_opaque_original_identity_preserves_real_same_case_with_redacted_display(workspace):
    before, after = report(), report(passed=True)
    for payload in (before, after):
        payload["tests"][0].update(nodeid="test_app.py::test_value[password=[REDACTED]]", identity_sha256=DIGEST)
    assert compare_reports(save(workspace, before, "baseline.json"),
                           save(workspace, after, "candidate.json"))["status"] == "evidence_consistent"


def test_pre_redacted_legacy_names_without_original_identity_are_inconclusive(workspace):
    before, after = report(), report(passed=True)
    for payload in (before, after):
        payload["tests"][0]["nodeid"] = "test_app.py::test_value[password=[REDACTED]]"
    result = compare_reports(save(workspace, before, "baseline.json"), save(workspace, after, "candidate.json"))
    assert "original_test_identity_missing" in result["reasons"]


def test_large_comparison_is_bounded_and_keeps_inconclusive_status(workspace):
    before, after = report(), report(passed=True)
    before["tests"] = [{"nodeid": f"{i}" + "b" * 1800, "file": "test_app.py", "outcome": "failed"} for i in range(30)]
    after["tests"] = [{"nodeid": f"{i}" + "a" * 1800, "file": "test_app.py", "outcome": "failed"} for i in range(30)]
    result = compare_reports(save(workspace, before, "baseline.json"), save(workspace, after, "candidate.json"))
    assert result["status"] == "inconclusive" and result["reasons"]
    assert len(json.dumps(result, ensure_ascii=False)) <= 24000


@pytest.mark.parametrize("mutation", [
    "skip", "xfail", "missing", "renamed", "changed_test", "changed_harness", "added_harness",
    "truncated", "retry", "failed_retry", "setup_only", "teardown_failure", "missing_exit",
    "same_run", "new_failure", "new_skipped", "file_mapping", "missing_hash", "malformed_run",
])
def test_incomplete_or_weakened_repair_evidence_stays_inconclusive(mutation):
    before, after = report(), report(passed=True)
    row = after["tests"][0]
    if mutation in {"skip", "xfail"}:
        row["outcome"] = {"skip": "skipped", "xfail": "xfailed"}[mutation]
    elif mutation == "missing":
        after["tests"] = []
    elif mutation == "renamed":
        row["nodeid"] += "_different"
    elif mutation == "changed_test":
        after["test_hashes"]["test_app.py"] = "a" * 64
    elif mutation == "changed_harness":
        before["harness_hashes"]["conftest.py"] = DIGEST
        after["harness_hashes"]["conftest.py"] = "b" * 64
    elif mutation == "added_harness":
        after["harness_hashes"]["conftest.py"] = DIGEST
    elif mutation == "truncated":
        after["truncated"] = True
    elif mutation == "retry":
        row["attempt"] = 1
    elif mutation == "failed_retry":
        after["tests"].append({**row, "outcome": "failed", "attempt": 0})
        row["attempt"] = 1
    elif mutation == "setup_only":
        row["phase"] = "setup"
    elif mutation == "teardown_failure":
        after["tests"].append({**row, "phase": "teardown", "outcome": "error"})
    elif mutation == "missing_exit":
        after.pop("exit_code")
    elif mutation == "same_run":
        after["run_id"] = before["run_id"]
    elif mutation == "new_failure":
        after["tests"].append({**row, "nodeid": "test_app.py::test_other", "outcome": "failed"})
    elif mutation == "new_skipped":
        after["tests"].append({**row, "nodeid": "test_app.py::test_other", "outcome": "skipped"})
    elif mutation == "file_mapping":
        row["file"] = "elsewhere.py"
    elif mutation == "missing_hash":
        after["test_hashes"] = {}
    elif mutation == "malformed_run":
        after["run_id"] = {"untrusted": True}
    result = compare_reports(before, after)
    assert result["status"] == "inconclusive", mutation
    assert result["reasons"] and result["verified_fix"] is False


def test_same_passing_reports_do_not_establish_a_reproduced_bug():
    before = report(passed=True, run_id="first")
    result = compare_reports(before, report(passed=True))
    assert "baseline_has_no_reproduced_failing_test" in result["reasons"]


def test_collector_mismatch_and_debugger_capture_cannot_certify_test_replay():
    assert compare_reports(report(), report(passed=True, producer="playwright"))["status"] == "inconclusive"
    assert compare_reports(report(producer="debugpy"), report(passed=True, producer="debugpy"))["status"] == "inconclusive"


def test_tool_opt_in_prompt_scope_and_argument_validation(workspace):
    off = DebugEvidenceTools(workspace)
    enabled = DebugEvidenceTools(workspace, enabled=True)
    assert off.definitions("Debug my crash") == []
    assert DebugEvidenceTools(None, enabled=True).definitions("Debug my crash") == []
    assert enabled.definitions("Write a friendly greeting") == []
    assert {item["name"] for item in enabled.definitions("Find the assertion failure")} == TOOL_NAMES
    with pytest.raises(PermissionError):
        off.call("star_debug_plan", {"symptom": "slow", "runtime": "python"}, enabled=TOOL_NAMES)
    with pytest.raises(PermissionError):
        enabled.call("star_debug_plan", {"symptom": "slow", "runtime": "python"}, enabled=set())
    for args in ({"symptom": "slow", "runtime": "python", "command": "execute something"},
                 {"symptom": "slow", "runtime": "unknown"}, []):
        with pytest.raises(ValueError):
            enabled.call("star_debug_plan", args, enabled=TOOL_NAMES)


@pytest.mark.parametrize(("symptom", "runtime", "probe"), [
    ("SyntaxError", "python", "Ruff"), ("ModuleNotFoundError", "python", "collection"),
    ("deadlock timeout", "python", "faulthandler"), ("CPU slow", "python", "py-spy"),
    ("HTTP 503", "browser", "Playwright"), ("frame time spike", "roblox", "MicroProfiler"),
    ("memory leak", "java", "JFR"), ("CPU", "dotnet", "dotnet-trace"),
    ("race condition", "rust", "Loom"),
])
def test_probe_plans_are_specific_and_do_not_claim_installation(symptom, runtime, probe):
    result = diagnostic_plan(symptom, runtime)
    assert probe in result["recommended_probe"]
    assert result["tool_availability"] == "not_probed" and result["execution"] == "plan_only"
    assert result["classification_is_hypothesis"] is True


def test_real_pytest_repair_replays_unchanged_test_and_detects_weakened_test(workspace):
    app = workspace.root / "app.py"
    test_file = workspace.root / "test_app.py"
    app.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    test_file.write_text("from app import add\ndef test_value():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(workspace.root)]),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("STAR_TEST_SHARD", None)

    def collect(name):
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "star.debug_pytest",
                                 "-p", "no:cacheprovider", f"--star-debug-report={name}", "test_app.py"],
                                cwd=workspace.root, env=env, capture_output=True, text=True, timeout=20)
        return result.returncode, read_report(workspace, name)

    failed_exit, before = collect("baseline.json")
    app.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    passed_exit, after = collect("candidate.json")
    assert (failed_exit, passed_exit) == (1, 0)
    assert compare_reports(before, after)["status"] == "evidence_consistent"
    test_file.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    _, weakened = collect("weakened.json")
    assert "test_source_changed" in compare_reports(before, weakened)["reasons"]
    assert compare_reports(before, weakened)["verified_fix"] is False
