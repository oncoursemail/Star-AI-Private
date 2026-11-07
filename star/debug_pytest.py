"""Opt-in, bounded pytest evidence; this plugin does not start test processes.

Usage: python -m pytest -p star.debug_pytest --star-debug-report=report.json

Each executed phase has its own record. Verification must require a real passing
``call`` for the original node ID and reject a later setup/teardown error. Reports
are diagnostics, not a trusted test oracle or permission to run generated code.
"""
from __future__ import annotations

from collections import Counter, deque
from fnmatch import fnmatch
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
import uuid

import pytest

from .debug_common import SCHEMA, redact_debug, sha256_file, write_report

MAX_TEST_RECORDS = 5000
MAX_FAILURE_RECORDS = 50
MAX_FRAMES = 64
MAX_MESSAGE = 2000
MAX_RECORD_BYTES = 1_200_000
MAX_HARNESS_FILES = 256
MAX_HARNESS_ENTRIES = 10_000
_HARNESS_NAMES = {"conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"}
_SKIP_DIRECTORIES = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
_SENSITIVE_ARGUMENT = re.compile(r"(?i)(?:password|passwd|secret|token|api[-_]?key|authorization|cookie)")
_EXCEPTION = re.compile(r"^(?:E\s+)?([\w.]+(?:Error|Exception|Interrupt|Exit)|Failed)(?::|\s+while\b)")


def pytest_addoption(parser):
    group = parser.getgroup("star-debug", "Opt-in STAR diagnostic evidence")
    group.addoption(
        "--star-debug-report",
        metavar="PATH.json",
        default=None,
        help="Write bounded, redacted pytest evidence to an explicit local JSON path.",
    )


def pytest_configure(config):
    target = config.getoption("star_debug_report", default=None)
    if target is None:
        return
    # Workers must not race to overwrite the controller's report. Distributed
    # execution is reported as incomplete until per-worker integrity is supported.
    if hasattr(config, "workerinput"):
        return
    config.pluginmanager.register(_EvidenceCollector(config, Path(target)), "star-debug-evidence")


class _EvidenceCollector:
    def __init__(self, config, output: Path):
        self.config = config
        self.output = output
        self.root = Path(config.rootpath).resolve()
        self.started = time.perf_counter()
        self.run_id = str(uuid.uuid4())
        self.tests: list[dict] = []
        self.failures: list[dict] = []
        self.test_hashes: dict[str, str] = {}
        self.harness_hashes: dict[str, str] = {}
        self._hash_paths: dict[str, Path] = {}
        self._harness_scope: list[tuple[Path, bool]] = []
        self._outcomes: dict[str, str] = {}
        self._bytes = 0
        self.truncated = False
        self.incomplete_reasons: list[str] = []
        self.deselected = 0
        self.collection_errors = 0
        self.internal_errors = 0
        self.interrupted = False
        self.distributed = bool(config.getoption("numprocesses", default=0))
        self.argv = self._arguments(config.invocation_params.args)

    def _incomplete(self, reason: str):
        if reason not in self.incomplete_reasons:
            self.incomplete_reasons.append(reason)

    def _text(self, value, limit: int = MAX_MESSAGE) -> str:
        text = redact_debug(value, limit=limit)
        if len(text) > limit:
            self.truncated = True
            return text[:limit]
        return text

    def _exception_text(self, excinfo) -> str:
        try:
            return self._text(str(excinfo.value))
        except Exception:
            self._incomplete("exception_message_unavailable")
            return "The exception message could not be rendered."

    def _arguments(self, arguments) -> list[str]:
        result: list[str] = []
        hide_next = False
        for index, argument in enumerate(arguments):
            if index >= 100:
                self.truncated = True
                break
            value = str(argument)
            if hide_next:
                result.append("[REDACTED]")
                hide_next = False
            elif value.startswith("-") and _SENSITIVE_ARGUMENT.search(value.split("=", 1)[0]):
                key, separator, _ = value.partition("=")
                result.append(self._text(key + ("=[REDACTED]" if separator else ""), 512))
                hide_next = not separator
            else:
                result.append(self._text(value, 512))
        return result

    def _path(self, value) -> str:
        path = Path(str(value))
        if not path.is_absolute():
            path = self.root / path
        try:
            label = path.resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            label = str(path)
        return self._text(label, 512)

    def _reserve(self, value) -> bool:
        size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        if self._bytes + size > MAX_RECORD_BYTES:
            self.truncated = True
            return False
        self._bytes += size
        return True

    def _failure(self, failure: dict):
        if len(self.failures) >= MAX_FAILURE_RECORDS:
            self.truncated = True
        elif self._reserve(failure):
            self.failures.append(failure)

    def _local_path(self, path: Path) -> Path | None:
        """Accept paths below root without traversing any symbolic-link component."""
        absolute = Path(os.path.abspath(path))
        try:
            relative = absolute.relative_to(self.root)
        except ValueError:
            self._incomplete("harness_source_outside_root")
            return None
        current = self.root
        for component in relative.parts:
            current /= component
            if current.is_symlink():
                self._incomplete("harness_symlink_unsupported")
                return None
        return absolute

    def _harness_roots(self):
        # Never fall back to recursive scanning of a home folder or filesystem.
        if self.root == Path(self.root.anchor) or self.root == Path.home().resolve():
            self._incomplete("harness_root_too_broad")
            return
        if self.config.getoption("pyargs", default=False):
            self._incomplete("harness_pyargs_unsupported")
            return
        for index, argument in enumerate(self.config.args):
            if index >= 100:
                self.truncated = True
                self._incomplete("harness_discovery_limit")
                break
            raw = Path(str(argument).split("::", 1)[0])
            target = raw if raw.is_absolute() else Path(self.config.invocation_params.dir) / raw
            path = self._local_path(target)
            if path is not None:
                self._harness_scope.append((path, path.is_dir()))

    def _discover_harness(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        visited: set[Path] = set()
        examined = 0
        patterns = tuple(self.config.getini("norecursedirs"))

        def include(path: Path):
            nonlocal examined
            examined += 1
            if examined > MAX_HARNESS_ENTRIES:
                self.truncated = True
                self._incomplete("harness_discovery_limit")
                return
            local = self._local_path(path)
            if local is None or not local.exists():
                return
            label = local.relative_to(self.root).as_posix()
            if self._text(label, 512) != label:
                self._incomplete("harness_source_path_redacted")
                return
            if not local.is_file():
                self._incomplete("harness_source_not_hashable")
                return
            if len(found) >= MAX_HARNESS_FILES and label not in found:
                self.truncated = True
                self._incomplete("harness_discovery_limit")
                return
            found[label] = local

        def directory_files(directory: Path):
            for name in _HARNESS_NAMES:
                include(directory / name)

        if not self._harness_scope:
            return found
        directory_files(self.root)
        if self.config.inipath is not None:
            include(Path(self.config.inipath))
        for target, is_directory in self._harness_scope:
            directory = target if is_directory else target.parent
            for ancestor in (directory, *directory.parents):
                if not ancestor.is_relative_to(self.root):
                    break
                directory_files(ancestor)
                if ancestor == self.root:
                    break
            if not is_directory:
                continue
            pending = [directory]
            while pending:
                current = pending.pop()
                if current in visited:
                    continue
                visited.add(current)
                try:
                    with os.scandir(current) as entries:
                        for entry in entries:
                            examined += 1
                            if examined > MAX_HARNESS_ENTRIES:
                                self.truncated = True
                                self._incomplete("harness_discovery_limit")
                                return found
                            if entry.name in _HARNESS_NAMES:
                                include(Path(entry.path))
                            elif entry.is_symlink():
                                # A directory link could hide applicable fixtures;
                                # don't traverse it or claim complete evidence.
                                if entry.name not in _SKIP_DIRECTORIES:
                                    self._incomplete("harness_symlink_unsupported")
                            elif entry.is_dir(follow_symlinks=False) and entry.name not in _SKIP_DIRECTORIES:
                                if not any(fnmatch(entry.name, pattern) or fnmatch(entry.path, pattern)
                                           for pattern in patterns):
                                    pending.append(Path(entry.path))
                except OSError:
                    self._incomplete("harness_discovery_unreadable")
        return found

    def _capture_harness(self):
        self._harness_roots()
        for label, source in self._discover_harness().items():
            digest = sha256_file(source)
            if not digest:
                self._incomplete("harness_source_not_hashable")
            elif self._reserve({label: digest}):
                self.harness_hashes[label] = digest

    def _check_harness(self):
        current = {label: sha256_file(source) for label, source in self._discover_harness().items()}
        if current != self.harness_hashes:
            self._incomplete("harness_source_changed_during_run")

    @pytest.hookimpl(tryfirst=True)
    def pytest_sessionstart(self, session):
        # Replace stale evidence before any collection or test code executes.
        # If the process is killed later, this marker cannot certify a repair.
        pending = {
            "schema": SCHEMA,
            "producer": "pytest",
            "run_id": self.run_id,
            "status": "incomplete",
            "exit_code": None,
            "duration_ms": 0,
            "truncated": False,
            "environment": {},
            "summary": {},
            "tests": [],
            "failures": [],
            "test_hashes": {},
            "harness_hashes": {},
            "argv": self.argv,
            "incomplete_reasons": ["run_in_progress"],
        }
        try:
            write_report(self.output, pending)
        except (OSError, ValueError) as exc:
            raise pytest.UsageError("STAR evidence write failed: " + redact_debug(exc, limit=300)) from exc
        # Initial conftests have already been imported by pytest configuration.
        # This snapshot precedes collection/execution, not arbitrary plugin imports.
        self._capture_harness()

    def pytest_deselected(self, items):
        self.deselected += len(items)

    def pytest_collection_finish(self, session):
        for item in session.items:
            source = Path(item.path)
            try:
                relative = source.resolve().relative_to(self.root).as_posix()
            except (OSError, ValueError):
                self._incomplete("test_source_outside_root")
                continue
            label = self._text(relative, 512)
            resolved = source.resolve()
            if not any(resolved == target or (is_directory and resolved.is_relative_to(target))
                       for target, is_directory in self._harness_scope):
                self._incomplete("test_outside_harness_discovery_scope")
            if label != relative:
                self._incomplete("test_source_path_redacted")
                continue
            if label in self.test_hashes:
                continue
            if len(self.test_hashes) >= MAX_TEST_RECORDS:
                self.truncated = True
                break
            digest = sha256_file(source)
            if not digest:
                self._incomplete("test_source_not_hashable")
                continue
            if not self._reserve({label: digest}):
                break
            self.test_hashes[label] = digest
            self._hash_paths[label] = source

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        if not report.failed:
            return
        failure = self._exception_failure(report, call.excinfo)
        # Only a bounded primitive dictionary is attached; no live frames/locals.
        report.star_debug_failure = failure

    def _exception_failure(self, report, excinfo) -> dict:
        file, zero_line, _ = report.location
        phase = report.when
        frames: list[dict] = []
        exception_type = "TestFailure"
        message = "The test phase failed."
        if excinfo is not None:
            exception_type = self._text(excinfo.typename, 128)
            message = self._exception_text(excinfo)
            traceback = excinfo.traceback
            if len(traceback) > MAX_FRAMES:
                self.truncated = True
            for entry in traceback[-MAX_FRAMES:]:
                frames.append({
                    "file": self._path(entry.path),
                    "line": entry.lineno + 1,
                    "function": self._text(entry.frame.code.name, 128),
                })
        elif isinstance(report.longrepr, str):
            # pytest represents strict XPASS as a short string, not an exception.
            message = self._text(report.longrepr)
            if report.longrepr.startswith("[XPASS(strict)]"):
                exception_type = "UnexpectedPass"
        category = "assertion" if exception_type in {"AssertionError", "Failed"} else "exception"
        if exception_type == "UnexpectedPass":
            category = "unexpected_pass"
        elif phase in {"setup", "teardown"}:
            category = phase
        return {
            "nodeid": self._text(report.nodeid, 512),
            "identity_sha256": hashlib.sha256(report.nodeid.encode("utf-8")).hexdigest(),
            "category": category,
            "phase": phase,
            "exception_type": exception_type,
            "message": message,
            "file": frames[-1]["file"] if frames else self._path(file),
            "line": frames[-1]["line"] if frames else zero_line + 1,
            "frames": frames,
        }

    @staticmethod
    def _phase_outcome(report) -> str:
        if getattr(report, "wasxfail", None) is not None:
            if report.skipped:
                return "xfailed"
            if report.passed:
                return "xpassed"
        if report.failed:
            if isinstance(report.longrepr, str) and report.longrepr.startswith("[XPASS(strict)]"):
                return "xpassed"
            return "failed" if report.when == "call" else "error"
        return report.outcome

    def pytest_runtest_logreport(self, report):
        # Hash the original ID before redaction: distinct secret-bearing parameter
        # IDs may have the same safe display text. This is identity, not attestation.
        identity_sha256 = hashlib.sha256(report.nodeid.encode("utf-8")).hexdigest()
        nodeid = self._text(report.nodeid, 512)
        phase_outcome = self._phase_outcome(report)
        file, zero_line, _ = report.location
        record = {
            "nodeid": nodeid,
            "identity_sha256": identity_sha256,
            "outcome": phase_outcome,
            "file": self._path(file),
            "line": zero_line + 1,
            "duration_ms": round(max(0.0, report.duration) * 1000, 3),
            "phase": report.when,
        }
        if len(self.tests) >= MAX_TEST_RECORDS:
            self.truncated = True
        elif self._reserve(record):
            self.tests.append(record)
        if identity_sha256 not in self._outcomes and len(self._outcomes) >= MAX_TEST_RECORDS:
            self.truncated = True
        else:
            previous = self._outcomes.get(identity_sha256)
            if phase_outcome == "error":
                self._outcomes[identity_sha256] = "error"
            elif previous != "error" and (report.when == "call" or report.skipped):
                self._outcomes[identity_sha256] = phase_outcome
        if report.failed:
            failure = getattr(report, "star_debug_failure", None)
            if failure is None:
                self._incomplete("missing_failure_details")
                failure = self._exception_failure(report, None)
            self._failure(failure)

    def pytest_collectreport(self, report):
        if not report.failed:
            return
        self.collection_errors += 1
        captured = getattr(report, "star_debug_collection_failure", None)
        if captured is not None:
            self._failure(captured)
            return
        crash = getattr(report.longrepr, "reprcrash", None)
        fallback = report.longrepr if isinstance(report.longrepr, str) else getattr(report.longrepr, "longrepr", "")
        raw_message = str(getattr(crash, "message", fallback))
        # A collector's exception can embed a formatted traceback with --showlocals.
        # Keep only its final exception line; never copy formatted tracebacks.
        if len(raw_message) > 64_000:
            self.truncated = True
        lines = raw_message[-64_000:].splitlines()
        selected = "Collection failed before tests could run."
        exception_type = "CollectionError"
        for line in reversed(lines):
            match = _EXCEPTION.match(line.strip())
            if match:
                exception_type = match.group(1)
                selected = line.strip().removeprefix("E ").lstrip()
                break
        self._failure({
            "nodeid": self._text(report.nodeid, 512),
            "category": "collection",
            "phase": "collection",
            "exception_type": self._text(exception_type, 128),
            "message": self._text(selected),
            "file": self._path(getattr(crash, "path", report.nodeid.split("::", 1)[0])),
            "line": getattr(crash, "lineno", None),
            "frames": [],
        })

    def pytest_exception_interact(self, node, call, report):
        if call.when != "collect" or call.excinfo is None:
            return
        exception = call.excinfo.value
        # pytest wraps import and syntax errors in CollectError. Follow its
        # explicit cause rather than copying the formatted wrapper traceback.
        seen: set[int] = set()
        while exception.__cause__ is not None and id(exception) not in seen and len(seen) < 8:
            seen.add(id(exception))
            exception = exception.__cause__
        frames: deque[dict] = deque(maxlen=MAX_FRAMES)
        traceback = exception.__traceback__
        count = 0
        while traceback is not None:
            code = traceback.tb_frame.f_code
            frames.append({
                "file": self._path(code.co_filename),
                "line": traceback.tb_lineno,
                "function": self._text(code.co_name, 128),
            })
            count += 1
            traceback = traceback.tb_next
        if count > MAX_FRAMES:
            self.truncated = True
        try:
            message = self._text(str(exception))
        except Exception:
            self._incomplete("exception_message_unavailable")
            message = "The exception message could not be rendered."
        report.star_debug_collection_failure = {
            "nodeid": self._text(report.nodeid, 512),
            "category": "collection",
            "phase": "collection",
            "exception_type": self._text(type(exception).__name__, 128),
            "message": message,
            "file": frames[-1]["file"] if frames else self._path(node.path),
            "line": frames[-1]["line"] if frames else None,
            "frames": list(frames),
        }

    def pytest_internalerror(self, excrepr, excinfo):
        self.internal_errors += 1
        # No excrepr text: it can contain captured locals.
        self._failure({
            "nodeid": "",
            "category": "internal",
            "phase": "internal",
            "exception_type": self._text(excinfo.typename, 128),
            "message": self._exception_text(excinfo),
            "file": "",
            "line": None,
            "frames": [],
        })

    def pytest_keyboard_interrupt(self, excinfo):
        self.interrupted = True

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        self._check_harness()
        for label, source in self._hash_paths.items():
            if sha256_file(source) != self.test_hashes[label]:
                self._incomplete("test_source_changed_during_run")
        counts = Counter(self._outcomes.values())
        exit_code = int(exitstatus)
        if self.distributed:
            self._incomplete("distributed_execution_unsupported")
        if self.interrupted:
            self._incomplete("interrupted")
        if exit_code == 5:
            self._incomplete("no_tests_collected")
        if self.truncated:
            self._incomplete("capture_truncated")
        if self.collection_errors or self.internal_errors or exit_code in {3, 4}:
            status = "error"
        elif exit_code in {2, 5} or self.incomplete_reasons:
            status = "incomplete"
        elif exit_code == 1 or self.failures:
            status = "failed"
        elif exit_code != 0:
            status = "error"
        elif not counts["passed"]:
            self._incomplete("no_passing_test_calls")
            status = "incomplete"
        else:
            status = "passed"
        report = {
            "schema": SCHEMA,
            "producer": "pytest",
            "run_id": self.run_id,
            "status": status,
            "exit_code": exit_code,
            "duration_ms": round((time.perf_counter() - self.started) * 1000, 3),
            "truncated": self.truncated,
            "environment": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": sys.platform,
                "machine": self._text(platform.machine(), 128),
            },
            "summary": {
                "collected": int(session.testscollected),
                "recorded_tests": len(self._outcomes),
                "passed": counts["passed"],
                "failed": counts["failed"],
                "errors": counts["error"],
                "skipped": counts["skipped"],
                "xfailed": counts["xfailed"],
                "xpassed": counts["xpassed"],
                "deselected": self.deselected,
                "collection_errors": self.collection_errors,
                "internal_errors": self.internal_errors,
                "phases_recorded": len(self.tests),
            },
            "tests": self.tests,
            "failures": self.failures,
            "test_hashes": self.test_hashes,
            "harness_hashes": self.harness_hashes,
            "harness_capture_phase": "session_start",
            "argv": self.argv,
            "incomplete_reasons": self.incomplete_reasons,
        }
        try:
            write_report(self.output, report)
        except (OSError, ValueError) as exc:
            # A missing report must not leave a successful command that looks like
            # a verified result. Never rewrite the original test outcome otherwise.
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
            terminal = self.config.pluginmanager.get_plugin("terminalreporter")
            if terminal is not None:
                terminal.write_line("STAR evidence write failed: " + redact_debug(exc, limit=300), red=True)
