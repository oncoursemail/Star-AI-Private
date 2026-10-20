"""Real subprocess suites verify the collector independently of its records."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


_ROOT = Path(__file__).resolve().parents[1]


def _environment():
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    env["PYTHONPATH"] = str(_ROOT)
    env["STAR_CAPTURE_PROBE_SECRET"] = "do-not-record-the-environment-value"
    return env


def _run_suite(tmp_path, files, *arguments, enabled=True):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
    report_path = tmp_path / "evidence.json"
    command = [sys.executable, "-m", "pytest", "-p", "star.debug_pytest", "-q"]
    if enabled:
        command.append("--star-debug-report=" + str(report_path))
    command.extend(arguments)
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=_environment(),
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
    return result, report


def test_real_failure_has_evidence_and_passing_calls_without_locals_or_output(tmp_path):
    source = """
        import sys

        def test_pass():
            assert 1 + 1 == 2

        def test_bad():
            private_local = "never-record-this-local-value"
            print("never-record-this-stdout-value")
            print("never-record-this-stderr-value", file=sys.stderr)
            raise ValueError("password=tiny-private-password")
    """
    result, report = _run_suite(tmp_path, {"test_sample.py": source}, "--showlocals")
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["schema"] == "star-debug-evidence-v1"
    assert report["producer"] == "pytest"
    assert report["status"] == "failed"
    assert report["exit_code"] == 1
    assert report["summary"]["passed"] == 1
    assert report["summary"]["failed"] == 1
    passing = [entry for entry in report["tests"] if entry["nodeid"].endswith("::test_pass")]
    assert {entry["phase"] for entry in passing} == {"setup", "call", "teardown"}
    assert all(entry["outcome"] == "passed" for entry in passing)
    failure = report["failures"][0]
    assert failure["exception_type"] == "ValueError"
    assert failure["phase"] == "call"
    assert failure["file"] == "test_sample.py"
    assert failure["frames"][-1]["function"] == "test_bad"
    assert failure["line"] > 0
    assert "[REDACTED]" in failure["message"]
    serialized = json.dumps(report)
    for hidden in ("never-record-this-local-value", "never-record-this-stdout-value",
                   "never-record-this-stderr-value", "tiny-private-password",
                   "do-not-record-the-environment-value"):
        assert hidden not in serialized
    assert report["test_hashes"]["test_sample.py"] == hashlib.sha256(
        (tmp_path / "test_sample.py").read_bytes()
    ).hexdigest()
    assert not report["truncated"]
    assert report["duration_ms"] >= 0


def test_setup_and_teardown_errors_cannot_be_mistaken_for_passing_tests(tmp_path):
    result, report = _run_suite(tmp_path, {"test_phases.py": """
        import pytest

        @pytest.fixture
        def broken_setup():
            raise RuntimeError("setup failed")

        @pytest.fixture
        def broken_teardown():
            yield
            raise RuntimeError("teardown failed")

        def test_setup(broken_setup):
            pass

        def test_teardown(broken_teardown):
            assert True
    """})
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["status"] == "failed"
    assert report["summary"]["errors"] == 2
    assert report["summary"]["passed"] == 0
    assert {failure["phase"] for failure in report["failures"]} == {"setup", "teardown"}
    assert {failure["category"] for failure in report["failures"]} == {"setup", "teardown"}
    rows = [entry for entry in report["tests"] if entry["nodeid"].endswith("::test_teardown")]
    assert any(entry["phase"] == "call" and entry["outcome"] == "passed" for entry in rows)
    assert any(entry["phase"] == "teardown" and entry["outcome"] == "error" for entry in rows)


def test_collection_import_error_is_distinct_and_does_not_capture_formatted_locals(tmp_path):
    result, report = _run_suite(tmp_path, {"test_import.py": """
        private_local = "unrelated-collection-local"
        import missing_star_collector_dependency_98765
    """}, "--showlocals")
    assert result.returncode == 2, result.stdout + result.stderr
    assert report["status"] == "error"
    assert report["summary"]["collection_errors"] == 1
    assert report["tests"] == []
    failure = report["failures"][0]
    assert failure["category"] == "collection"
    assert failure["exception_type"] == "ModuleNotFoundError"
    assert "missing_star_collector_dependency_98765" in failure["message"]
    assert "unrelated-collection-local" not in json.dumps(report)


def test_skip_xfail_and_xpass_have_separate_outcomes(tmp_path):
    result, report = _run_suite(tmp_path, {"test_marks.py": """
        import pytest

        def test_pass():
            assert True

        @pytest.mark.skip(reason="not available")
        def test_skip():
            raise AssertionError("must not run")

        @pytest.mark.xfail(reason="known problem")
        def test_xfail():
            assert False

        @pytest.mark.xfail(reason="now works")
        def test_xpass():
            assert True

        @pytest.mark.xfail(reason="strict expectation", strict=True)
        def test_strict_xpass():
            assert True
    """})
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["status"] == "failed"
    assert report["summary"]["passed"] == 1
    assert report["summary"]["skipped"] == 1
    assert report["summary"]["xfailed"] == 1
    assert report["summary"]["xpassed"] == 2
    assert len(report["failures"]) == 1
    assert report["failures"][0]["exception_type"] == "UnexpectedPass"
    assert report["failures"][0]["category"] == "unexpected_pass"


@pytest.mark.parametrize("source,exit_code,reason", [
    ("", 5, "no_tests_collected"),
    ("import pytest\n@pytest.mark.skip(reason='skip')\ndef test_one(): pass", 0, "no_passing_test_calls"),
    ("import pytest\n@pytest.mark.xfail\ndef test_one(): assert False", 0, "no_passing_test_calls"),
])
def test_empty_skipped_or_expected_failure_suites_are_not_verification(tmp_path, source, exit_code, reason):
    result, report = _run_suite(tmp_path, {"test_none.py": source})
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert report["status"] == "incomplete"
    assert reason in report["incomplete_reasons"]


def test_interrupt_after_passing_test_is_incomplete(tmp_path):
    result, report = _run_suite(tmp_path, {"test_interrupted.py": """
        def test_first():
            assert True
        def test_interrupt():
            raise KeyboardInterrupt()
    """})
    assert result.returncode == 2, result.stdout + result.stderr
    assert report["status"] == "incomplete"
    assert report["summary"]["passed"] == 1
    assert "interrupted" in report["incomplete_reasons"]


def test_internal_plugin_error_is_reported_separately(tmp_path):
    result, report = _run_suite(tmp_path, {
        "test_simple.py": "def test_ok(): assert True",
        "conftest.py": """
            def pytest_collection_modifyitems(items):
                private_local = "do-not-include-internal-locals"
                raise RuntimeError("internal collection hook failed")
        """,
    }, "--showlocals")
    assert result.returncode == 3, result.stdout + result.stderr
    assert report["status"] == "error"
    assert report["summary"]["internal_errors"] == 1
    assert report["failures"][0]["category"] == "internal"
    assert "do-not-include-internal-locals" not in json.dumps(report)


def test_truncated_records_never_claim_verification(tmp_path):
    result, report = _run_suite(tmp_path, {
        "conftest.py": """
            def pytest_configure(config):
                import star.debug_pytest
                star.debug_pytest.MAX_TEST_RECORDS = 4
        """,
        "test_many.py": """
            import pytest
            @pytest.mark.parametrize("number", range(5))
            def test_ok(number):
                assert number >= 0
        """,
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["truncated"]
    assert report["status"] == "incomplete"
    assert len(report["tests"]) == 4


def test_long_failure_message_is_bounded_and_flagged(tmp_path):
    result, report = _run_suite(tmp_path, {"test_long.py": """
        def test_long():
            raise RuntimeError("lengthy-message-" * 1000)
    """})
    assert result.returncode == 1
    assert len(report["failures"][0]["message"]) <= 2000
    assert report["truncated"]
    assert report["status"] == "incomplete"


def test_changed_test_source_during_run_invalidates_evidence(tmp_path):
    result, report = _run_suite(tmp_path, {"test_change.py": """
        from pathlib import Path
        def test_change():
            path = Path(__file__)
            path.write_text(path.read_text() + "\\n# changed during execution\\n")
            assert True
    """})
    assert result.returncode == 0
    assert report["status"] == "incomplete"
    assert "test_source_changed_during_run" in report["incomplete_reasons"]


def test_argument_pairs_are_redacted_without_changing_node_ids(tmp_path):
    result, report = _run_suite(tmp_path, {
        "conftest.py": """
            def pytest_addoption(parser):
                parser.addoption("--access-token")
        """,
        "test_tokens.py": "def test_token_refresh(): assert True",
    }, "--access-token", "short-credential-value", "test_tokens.py::test_token_refresh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "passed"
    assert "short-credential-value" not in json.dumps(report)
    assert "test_tokens.py::test_token_refresh" in report["argv"]
    assert len(report["test_hashes"]["test_tokens.py"]) == 64


def test_secret_parameter_ids_remain_distinct_after_display_redaction(tmp_path):
    result, report = _run_suite(tmp_path, {"test_params.py": """
        import pytest

        @pytest.mark.parametrize("value", [False, True],
                                 ids=["password=first-private-value", "password=second-private-value"])
        def test_parameters(value):
            assert value
    """})
    assert result.returncode == 1, result.stdout + result.stderr
    assert report["status"] == "failed"
    assert report["summary"]["recorded_tests"] == 2
    assert report["summary"]["failed"] == report["summary"]["passed"] == 1
    raw_ids = [f"test_params.py::test_parameters[password={value}-private-value]"
               for value in ("first", "second")]
    identities = [hashlib.sha256(nodeid.encode("utf-8")).hexdigest() for nodeid in raw_ids]
    rows = report["tests"]
    assert {row["identity_sha256"] for row in rows} == set(identities)
    assert len({row["nodeid"] for row in rows}) == 1
    for identity in identities:
        assert {row["phase"] for row in rows if row["identity_sha256"] == identity} == {
            "setup", "call", "teardown",
        }
    assert report["failures"][0]["identity_sha256"] == identities[0]
    serialized = json.dumps(report)
    assert "first-private-value" not in serialized
    assert "second-private-value" not in serialized


def test_plugin_without_explicit_option_does_not_write_report(tmp_path):
    result, report = _run_suite(tmp_path, {"test_ok.py": "def test_ok(): assert True"}, enabled=False)
    assert result.returncode == 0
    assert report is None
    assert not (tmp_path / "evidence.json").exists()


def test_repeated_pytest_invocation_has_fresh_ids_and_no_stale_failures(tmp_path):
    (tmp_path / "test_fail.py").write_text("def test_fail(): assert False", encoding="utf-8")
    (tmp_path / "test_pass.py").write_text("def test_pass(): assert True", encoding="utf-8")
    (tmp_path / "repeat.py").write_text(textwrap.dedent("""
        import json
        from pathlib import Path
        import pytest
        arguments = ["-q", "-p", "star.debug_pytest", "--star-debug-report=evidence.json"]
        first_code = pytest.main(arguments + ["test_fail.py"])
        first = json.loads(Path("evidence.json").read_text())
        second_code = pytest.main(arguments + ["test_pass.py"])
        second = json.loads(Path("evidence.json").read_text())
        assert first_code == 1 and second_code == 0
        assert first["run_id"] != second["run_id"]
        assert first["failures"] and not second["failures"]
        assert second["status"] == "passed"
        assert set(second["test_hashes"]) == {"test_pass.py"}
    """), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "repeat.py"], cwd=tmp_path, env=_environment(),
        capture_output=True, text=True, timeout=25, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_abrupt_exit_replaces_previous_passing_report_with_incomplete_marker(tmp_path):
    (tmp_path / "evidence.json").write_text(
        json.dumps({"status": "passed", "run_id": "old-run"}), encoding="utf-8",
    )
    result, report = _run_suite(tmp_path, {"test_exit.py": """
        import os
        def test_exit():
            os._exit(23)
    """})
    assert result.returncode == 23
    assert report["status"] == "incomplete"
    assert report["run_id"] != "old-run"
    assert report["exit_code"] is None
    assert report["incomplete_reasons"] == ["run_in_progress"]


def test_harness_hashes_cover_local_config_and_applicable_conftest_ancestors(tmp_path):
    files = {
        "pytest.ini": "[pytest]\n",
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "setup.cfg": "[tool:pytest]\n",
        "tox.ini": "[pytest]\n",
        "conftest.py": "# root fixtures\n",
        "tests/conftest.py": "# parent fixtures\n",
        "tests/nested/conftest.py": "# nested fixtures\n",
        "tests/nested/test_ok.py": "def test_ok(): assert True\n",
        "unrelated/conftest.py": "raise RuntimeError('unrelated harness must not load')\n",
    }
    result, report = _run_suite(tmp_path, files, "tests/nested/test_ok.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "passed"
    expected = set(files) - {"tests/nested/test_ok.py", "unrelated/conftest.py"}
    assert set(report["harness_hashes"]) == expected
    for name in expected:
        assert report["harness_hashes"][name] == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    assert report["harness_capture_phase"] == "session_start"


@pytest.mark.parametrize("target", ["conftest.py", "setup.cfg"])
@pytest.mark.parametrize("operation", ["edit", "add", "delete"])
def test_harness_mutation_during_execution_invalidates_report(tmp_path, target, operation):
    initial = "# baseline harness content\n"
    if operation == "edit":
        action = 'path.write_text(path.read_text() + "# changed\\n")'
    elif operation == "add":
        action = 'path.write_text("# newly added harness\\n")'
    else:
        action = "path.unlink()"
    files = {
        "pytest.ini": "[pytest]\n",
        "test_mutation.py": (
            "from pathlib import Path\n"
            "def test_mutation():\n"
            f"    path = Path({target!r})\n"
            f"    {action}\n"
            "    assert True\n"
        ),
    }
    if operation != "add":
        initial_path = tmp_path / target
        initial_path.write_text(initial, encoding="utf-8")
        # Preserve the actual bytes before mutation; Windows text writes may
        # translate LF to CRLF, and evidence hashes intentionally keep that detail.
        initial_hash = hashlib.sha256(initial_path.read_bytes()).hexdigest()
    result, report = _run_suite(tmp_path, files, "test_mutation.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "incomplete"
    assert "harness_source_changed_during_run" in report["incomplete_reasons"]
    if operation == "add":
        assert target not in report["harness_hashes"]
    else:
        assert report["harness_hashes"][target] == initial_hash


def test_changed_harness_between_runs_is_visible_even_when_test_source_is_unchanged(tmp_path):
    source = "from pathlib import Path\ndef test_ready(): assert Path('ready.txt').read_text() == 'yes'\n"
    first, baseline = _run_suite(tmp_path, {
        "pytest.ini": "[pytest]\n",
        "conftest.py": "# baseline fixture\n",
        "test_ready.py": source,
        "ready.txt": "no",
    }, "test_ready.py")
    second, candidate = _run_suite(tmp_path, {
        "conftest.py": "# changed fixture\n",
        "ready.txt": "yes",
    }, "test_ready.py")
    assert first.returncode == 1 and second.returncode == 0
    assert baseline["test_hashes"] == candidate["test_hashes"]
    assert baseline["harness_hashes"] != candidate["harness_hashes"]
    from star.debug_evidence import compare_reports
    comparison = compare_reports(baseline, candidate)
    assert comparison["status"] == "inconclusive"
    assert "harness_source_changed_or_missing" in comparison["reasons"]


def test_new_harness_between_runs_cannot_hide_an_original_failure(tmp_path):
    first, baseline = _run_suite(tmp_path, {
        "pytest.ini": "[pytest]\n",
        "test_ready.py": "from pathlib import Path\ndef test_ready(): assert Path('ready.txt').read_text() == 'yes'\n",
        "ready.txt": "no",
    }, "test_ready.py")
    second, candidate = _run_suite(tmp_path, {
        "conftest.py": "# newly introduced fixture module\n",
        "ready.txt": "yes",
    }, "test_ready.py")
    assert first.returncode == 1 and second.returncode == 0
    assert "conftest.py" not in baseline["harness_hashes"]
    assert "conftest.py" in candidate["harness_hashes"]
    from star.debug_evidence import compare_reports
    assert compare_reports(baseline, candidate)["status"] == "inconclusive"


def test_harness_discovery_is_bounded_and_cannot_claim_complete_evidence(tmp_path):
    result, report = _run_suite(tmp_path, {
        "conftest.py": """
            def pytest_configure(config):
                import star.debug_pytest
                star.debug_pytest.MAX_HARNESS_ENTRIES = 3
        """,
        "test_ok.py": "def test_ok(): assert True\n",
    }, "test_ok.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["status"] == "incomplete"
    assert report["truncated"]
    assert "harness_discovery_limit" in report["incomplete_reasons"]
