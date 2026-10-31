"""Opt-in, read-only debugger evidence tools for STAR's existing agent loop.

Collectors run explicitly in a developer's test environment. The model can read
bounded reports and plan the next probe, but cannot start a process, attach to a
PID, evaluate an expression, install a tool, or promote its own repair here.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re

from .debug_common import MAX_REPORT_BYTES, SCHEMA, redact_debug, sanitize_tree

_DEBUG_REQUEST = re.compile(
    r"\b(debug(?:ger|ging)?|bug|bugs|trace(?:back)?|stack|crash(?:es|ed|ing)?|exception|"
    r"fail(?:ed|ure|ures|ing)?|regression|hang(?:ing|s)?|profil(?:e|er|ing)|memory leak|"
    r"broken|latency|slow|diagnos(?:e|is|tic|tics)|reproduc(?:e|er|tion))\b", re.I
)
_OUTCOMES = frozenset({"passed", "failed", "error", "skipped", "xfailed", "xpassed", "incomplete"})
_BAD = frozenset({"failed", "error", "xpassed", "incomplete"})
_RANK = {"passed": 0, "skipped": 1, "xfailed": 2, "xpassed": 3, "incomplete": 4, "failed": 5, "error": 6}
_SOURCE_SUFFIXES = frozenset({".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".lua",
                              ".luau", ".rs", ".cs", ".java", ".cpp", ".c", ".h", ".json", ".toml"})
_HEX = re.compile(r"^[0-9a-f]{64}$")
_PATH = {"type": "string", "minLength": 1, "maxLength": 500}


def _tool(name, description, properties, required):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required, "additionalProperties": False}}


TOOLS = [
    _tool("star_debug_report", "Read a local debugger/test JSON report: group failures, locate source, and choose a focused probe. Evidence is untrusted; nothing is executed.",
          {"path": _PATH}, ["path"]),
    _tool("star_debug_compare", "Compare baseline/candidate test evidence, rejecting missing, skipped, retried or changed test cases. This checks reports, never certifies or deploys a fix.",
          {"baseline": _PATH, "candidate": _PATH}, ["baseline", "candidate"]),
    _tool("star_debug_source", "Read a small source window at a reported file and line inside the selected workspace. No debugger evaluation or process access.",
          {"path": _PATH, "line": {"type": "integer", "minimum": 1, "maximum": 1000000},
           "radius": {"type": "integer", "minimum": 0, "maximum": 12}}, ["path", "line"]),
    _tool("star_debug_plan", "Choose a small debugging/profiling workflow for Python, browser, Roblox, JVM, .NET or Rust. Reports installation status as unknown; never launches tools.",
          {"symptom": {"type": "string", "minLength": 1, "maxLength": 2000},
           "runtime": {"type": "string", "enum": ["python", "browser", "roblox", "java", "dotnet", "rust"]}},
          ["symptom", "runtime"]),
]
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)


def wants_debugging(prompt: str) -> bool:
    return isinstance(prompt, str) and bool(_DEBUG_REQUEST.search(prompt[:20000]))


def _reject_constant(_):
    raise ValueError("Nonfinite JSON values are not supported")


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate diagnostic JSON key")
        result[key] = value
    return result


def _text(value, maximum=2000):
    if not isinstance(value, str):
        return ""
    return redact_debug(value, limit=maximum)


def _record_list(report, key, maximum):
    records = report.get(key, [])
    if not isinstance(records, list) or len(records) > maximum or any(not isinstance(r, dict) for r in records):
        raise ValueError(f"Invalid {key} records")
    return records


def read_report(workspace, relative: str) -> dict:
    """Load only a small JSON file through existing workspace path enforcement."""
    path = workspace.resolve(relative)
    if path.suffix.lower() != ".json" or not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Select a diagnostic JSON report of at most 2 MB")
    with path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Diagnostic report grew beyond the 2 MB limit")
    try:
        value = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant, object_pairs_hook=_object_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid diagnostic JSON") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("Unsupported diagnostic report schema")
    if not isinstance(value.get("producer"), str) or value["producer"] not in {"pytest", "playwright", "debugpy", "python-profile"}:
        raise ValueError("Unsupported diagnostic report producer")
    if not isinstance(value.get("status"), str) or len(value["status"]) > 40:
        raise ValueError("Invalid diagnostic status")
    if type(value.get("truncated", False)) is not bool:
        raise ValueError("Invalid truncation indicator")
    exit_code = value.get("exit_code")
    if exit_code is not None and type(exit_code) is not int:
        raise ValueError("Invalid diagnostic exit code")
    for test in _record_list(value, "tests", 20000):
        if (not isinstance(test.get("nodeid"), str) or not 0 < len(test["nodeid"]) <= 2000
                or not isinstance(test.get("outcome"), str) or test["outcome"] not in _OUTCOMES):
            raise ValueError("Invalid diagnostic test record")
        identity = test.get("identity_sha256")
        if identity is not None and (not isinstance(identity, str) or not _HEX.fullmatch(identity)):
            raise ValueError("Invalid diagnostic test identity")
    for key, limit in (("failures", 1000), ("diagnostics", 2000), ("frames", 100)):
        _record_list(value, key, limit)
    for field in ("test_hashes", "harness_hashes"):
        hashes = value.get(field, {})
        if not isinstance(hashes, dict) or len(hashes) > 10000 or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in hashes.items()):
            raise ValueError("Invalid diagnostic source hashes")
    duration = value.get("duration_ms")
    if duration is not None and (type(duration) not in (int, float) or not 0 <= duration <= 31536000000):
        raise ValueError("Invalid diagnostic duration")
    # Structural validation and redaction precede any model-facing output.
    try:
        clean = sanitize_tree(value)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Diagnostic content exceeds its structural budget") from exc
    clean["identity_incomplete"] = False
    for original, sanitized in zip(value.get("tests", []), clean.get("tests", [])):
        # Collectors hash original identities before redacting their display name.
        # Legacy reports receive an identity here, before reader-side redaction.
        # This preserves distinct parameter cases; hashes do not authenticate a run.
        sanitized["identity_sha256"] = original.get("identity_sha256") or hashlib.sha256(original["nodeid"].encode()).hexdigest()
        if not original.get("identity_sha256") and any(marker in original["nodeid"] for marker in ("[REDACTED", "[TRUNCATED]")):
            clean["identity_incomplete"] = True
    clean["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    clean["report_path"] = _text(relative, 500)
    return clean


def source_window(workspace, relative: str, line: int, radius: int = 5) -> dict:
    if type(line) is not int or not 1 <= line <= 1000000 or type(radius) is not int or not 0 <= radius <= 12:
        raise ValueError("Invalid source window")
    path = workspace.resolve(relative)
    if path.suffix.lower() not in _SOURCE_SUFFIXES or not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("Select a small source file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError("Source file grew beyond the read limit")
    lines = raw.decode("utf-8-sig").splitlines()
    if line > len(lines):
        raise ValueError("Reported line is beyond the current source file")
    first, last = max(1, line - radius), min(len(lines), line + radius)
    return {"path": _text(relative, 500), "sha256": hashlib.sha256(raw).hexdigest(),
            "start_line": first, "end_line": last,
            "lines": [{"line": n, "text": _text(lines[n - 1], 500)} for n in range(first, last + 1)],
            "notice": "Current workspace source; check that its revision matches the capture."}


def _outcomes(report):
    combined = {}
    for test in report.get("tests", []):
        key = test.get("identity_sha256") or hashlib.sha256(test["nodeid"].encode()).hexdigest()
        status = test["outcome"]
        item = combined.setdefault(key, {"nodeid": test["nodeid"], "outcome": "passed", "call_passed": False,
                                        "files": set(), "attempts": set()})
        if _RANK[status] > _RANK[item["outcome"]]:
            item["outcome"] = status
        phase = test.get("phase", "call")
        if status == "passed" and phase == "call":
            item["call_passed"] = True
        if isinstance(test.get("file"), str) and test["file"]:
            item["files"].add(test["file"])
        attempt = test.get("attempt", 0)
        if type(attempt) is int and attempt >= 0:
            item["attempts"].add(attempt)
        else:
            item["outcome"] = "incomplete"
    for item in combined.values():
        if item["outcome"] == "passed" and not item["call_passed"]:
            item["outcome"] = "incomplete"
    return combined


def classify_failure(text: str) -> str:
    text = text.lower()
    groups = (
        ("memory", ("memoryerror", "out of memory", "memory leak", "heap", "allocation")),
        ("syntax", ("syntaxerror", "indentationerror", "parse error", "typecheck", "cannot find name")),
        ("environment", ("modulenotfound", "importerror", "no module named", "collection", "executable not found")),
        ("hang", ("timeout", "timed out", "deadlock", "hang", "blocked thread")),
        ("network", ("http", "network", "connection", "fetch", "websocket", "cors")),
        ("flaky", ("flaky", "retry", "intermittent", "race condition")),
        ("cpu", ("cpu", "slow", "lag", "frame time", "latency", "profile")),
        ("visual", ("layout", "overlap", "screenshot", "texture", "clipped")),
        ("assertion", ("assert", "expected", "mismatch", "wrong value")),
    )
    return next((name for name, phrases in groups if any(p in text for p in phrases)), "exception")


def summarize_report(workspace, report):
    outcomes = _outcomes(report)
    grouped = {}
    for failure in report.get("failures", []) + report.get("diagnostics", []):
        raw_category = _text(failure.get("category"), 80)
        message = _text(failure.get("message", failure.get("description", "")), 2000)
        exception = _text(failure.get("exception_type"), 120)
        category = raw_category or classify_failure(exception + " " + message)
        source = _text(failure.get("file", failure.get("path", "")), 500)
        line = failure.get("line")
        line = line if type(line) is int and line > 0 else None
        frame_data = [f for f in failure.get("frames", [])[:8] if isinstance(f, dict)] if isinstance(failure.get("frames"), list) else []
        if not source and frame_data:
            source = _text(frame_data[-1].get("file", frame_data[-1].get("path", "")), 500)
            line = frame_data[-1].get("line")
        fingerprint_text = json.dumps([report["producer"], category, exception, source, line, message[:500]], sort_keys=True)
        key = hashlib.sha256(fingerprint_text.encode()).hexdigest()[:20]
        if key not in grouped:
            grouped[key] = {"fingerprint": key, "category": category, "message": message,
                            "exception_type": exception, "file": source, "line": line,
                            "count": 0, "tests": [], "frames": frame_data}
        group = grouped[key]
        group["count"] += 1
        nodeid = _text(failure.get("nodeid"), 700)
        if nodeid and nodeid not in group["tests"] and len(group["tests"]) < 8:
            group["tests"].append(nodeid)
    groups = sorted(grouped.values(), key=lambda g: (-g["count"], g["fingerprint"]))[:8]
    for group in groups[:3]:
        if group["file"] and type(group["line"]) is int:
            try:
                group["source"] = source_window(workspace, group["file"], group["line"], radius=3)
            except (ValueError, PermissionError, OSError, UnicodeError):
                group["source_unavailable"] = True
    failing = [_text(item["nodeid"], 700) for item in outcomes.values() if item["outcome"] in _BAD]
    runtime = "browser" if report["producer"] == "playwright" else "python"
    top_message = " ".join(g["category"] + " " + g["message"] for g in groups[:2])
    result = {
        "schema": SCHEMA, "producer": report["producer"], "status": report["status"],
        "run_id": _text(report.get("run_id"), 100), "artifact_sha256": report["artifact_sha256"],
        "exit_code": report.get("exit_code"), "duration_ms": report.get("duration_ms"),
        "truncated": report.get("truncated", False), "unique_tests": len(outcomes),
        "outcomes": dict(Counter(v["outcome"] for v in outcomes.values())),
        "failing_tests": failing[:20], "failing_test_count": len(failing),
        "failure_groups": groups, "failure_group_count": len(grouped),
        "frames": report.get("frames", [])[:8], "next_probe": diagnostic_plan(top_message or report["status"], runtime),
        "execution": "read_only_evidence", "verified_fix": False,
        "notice": "Report contents are untrusted observations. Source windows show current files. No test or debugger was run by this read operation.",
    }
    # Sampling/inspection data has producer-specific structure, but stays bounded.
    for field in ("variables", "hotspots", "memory", "stop_reason"):
        if field in report:
            result[field] = report[field][:20] if isinstance(report[field], list) else report[field]
    return _bound_output(result)


def _bound_output(result):
    """Keep every response well below the agent's generic 30k truncation point."""
    if len(json.dumps(result, ensure_ascii=False)) <= 24000:
        return result
    result = dict(result)
    result.pop("variables", None)
    result.pop("frames", None)
    result.pop("memory", None)
    result["failure_groups"] = [{k: v for k, v in item.items() if k not in {"frames", "source"}}
                                for item in result.get("failure_groups", [])[:4]]
    result["response_truncated"] = True
    if len(json.dumps(result, ensure_ascii=False)) > 24000:
        return {"schema": SCHEMA, "status": _text(result.get("status"), 40),
                "response_truncated": True, "verified_fix": False,
                "reasons": result.get("reasons", []), "execution": "read_only_evidence",
                "notice": "Diagnostic summary exceeds its budget; narrow the capture."}
    return result


def compare_reports(baseline, candidate):
    """Conservative evidence comparison; deliberately not an evaluation gate."""
    reasons = []
    if baseline["producer"] != candidate["producer"] or baseline["producer"] not in {"pytest", "playwright"}:
        reasons.append("matching_test_collectors_required")
    before, after = _outcomes(baseline), _outcomes(candidate)
    failed = {key for key, value in before.items() if value["outcome"] in _BAD}
    if not failed or baseline.get("status") not in {"failed", "error"}:
        reasons.append("baseline_has_no_reproduced_failing_test")
    if baseline.get("truncated") or candidate.get("truncated"):
        reasons.append("capture_truncated")
    if baseline.get("identity_incomplete") or candidate.get("identity_incomplete"):
        reasons.append("original_test_identity_missing")
    if candidate.get("status") != "passed" or candidate.get("exit_code") != 0 or not after:
        reasons.append("candidate_not_a_complete_successful_run")
    if candidate.get("failures"):
        reasons.append("candidate_contains_failure_evidence")
    if not before or not after:
        reasons.append("test_identity_evidence_missing")
    missing = sorted(set(before) - set(after))
    unresolved = sorted(key for key in failed if key not in after or after[key]["outcome"] != "passed")
    regressions = sorted(key for key, value in after.items() if value["outcome"] in _BAD)
    newly_skipped = sorted(key for key, value in after.items() if value["outcome"] in {"skipped", "xfailed"}
                           and (key not in before or before[key]["outcome"] != value["outcome"]))
    if missing:
        reasons.append("baseline_test_ids_missing")
    if unresolved:
        reasons.append("original_failures_not_passed")
    if regressions:
        reasons.append("candidate_has_failed_or_incomplete_tests")
    if newly_skipped:
        reasons.append("candidate_introduced_skip_or_xfail")
    if any(len(v["attempts"]) > 1 or any(a > 0 for a in v["attempts"]) for v in after.values()):
        reasons.append("candidate_required_retries")
    if (not isinstance(baseline.get("run_id"), str) or not baseline["run_id"]
            or not isinstance(candidate.get("run_id"), str) or not candidate["run_id"]
            or candidate["run_id"] == baseline["run_id"]):
        reasons.append("distinct_run_identity_required")
    changed_hashes = []
    required_files = set().union(*(v["files"] for v in before.values())) if before else set()
    if not required_files or any(not before[k]["files"] for k in failed):
        reasons.append("test_source_identity_missing")
    for file in sorted(required_files):
        original = baseline.get("test_hashes", {}).get(file, "")
        current = candidate.get("test_hashes", {}).get(file, "")
        if not _HEX.fullmatch(original) or not _HEX.fullmatch(current):
            reasons.append("test_source_hash_missing")
        elif original != current:
            changed_hashes.append(file)
    if changed_hashes:
        reasons.append("test_source_changed")
    for key in set(before) & set(after):
        if before[key]["files"] != after[key]["files"]:
            reasons.append("test_source_mapping_changed")
            break
    # Added configuration or fixtures can also weaken a test, so compare whole maps.
    old_harness, new_harness = baseline.get("harness_hashes", {}), candidate.get("harness_hashes", {})
    if old_harness != new_harness or any(not _HEX.fullmatch(digest) for digest in old_harness.values()):
        reasons.append("harness_source_changed_or_missing")
    reasons = sorted(set(reasons))
    return _bound_output({
        "schema": SCHEMA, "status": "evidence_consistent" if not reasons else "inconclusive",
        "reasons": reasons, "original_failure_count": len(failed), "candidate_test_count": len(after),
        "missing_tests": [_text(before[key]["nodeid"], 300) for key in missing[:20]],
        "unresolved_failures": [_text(before[key]["nodeid"], 300) for key in unresolved[:20]],
        "regressions": [_text(after[key]["nodeid"], 300) for key in regressions[:20]],
        "newly_skipped": [_text(after[key]["nodeid"], 300) for key in newly_skipped[:20]],
        "changed_test_sources": [_text(file, 300) for file in changed_hashes[:20]],
        "baseline_sha256": baseline.get("artifact_sha256"), "candidate_sha256": candidate.get("artifact_sha256"),
        "verified_fix": False, "execution": "read_only_evidence",
        "notice": ("This compares supplied reports and recorded source hashes. It does not authenticate who ran them, "
                   "prove test intent or coverage, enable a feature, approve a lesson, or replace STAR's independent evaluation gate."),
    })


def diagnostic_plan(symptom: str, runtime: str):
    category = classify_failure(symptom)
    if runtime not in {"python", "browser", "roblox", "java", "dotnet", "rust"}:
        raise ValueError("Unsupported debugging runtime")
    if runtime == "python":
        choices = {
            "syntax": ("Ruff / Python parser", "Check the reported source line and syntax before opening a debugger."),
            "environment": ("pytest collection report", "Check interpreter, dependency and setup/collection failures before changing application logic."),
            "memory": ("tracemalloc / Scalene", "Compare allocation snapshots around the same repeated operation; inspect retained growth."),
            "cpu": ("py-spy / cProfile", "Capture a short profile of the reproducer and inspect the largest cumulative-time functions."),
            "hang": ("py-spy dump / faulthandler", "Capture blocked thread stacks first; distinguish waiting on I/O from a CPU loop."),
            "flaky": ("pytest replay / Hypothesis", "Keep failing seed and action sequence; repeat unchanged input before editing."),
        }
        tool, question = choices.get(category, ("debugpy DAP capture", "Stop at the failing line or uncaught exception and inspect the relevant stack and values."))
        sources = ["https://github.com/microsoft/debugpy", "https://docs.pytest.org/en/stable/reference/reference.html"]
    elif runtime == "browser":
        tool = "Chrome performance/heap tools" if category in {"cpu", "memory"} else "Playwright trace + failure recorder"
        question = "Reproduce the action; inspect page errors, HTTP error responses and transport failures separately, then the original source stack."
        sources = ["https://playwright.dev/docs/trace-viewer", "https://github.com/ChromeDevTools/chrome-devtools-mcp"]
    elif runtime == "roblox":
        tool = "Studio MicroProfiler / Script Profiler" if category in {"cpu", "memory", "hang"} else "Studio debugger + isolated multiplayer test"
        question = "Select the correct studio_id and client/server context; compare authoritative state and each client's observed state."
        sources = ["https://create.roblox.com/docs/studio/mcp", "https://create.roblox.com/docs/performance-optimization/microprofiler"]
    elif runtime == "java":
        tool, question = "JFR / jcmd", "Use a short recording to distinguish GC, allocation, blocking and CPU work before considering a rewrite."
        sources = ["https://docs.oracle.com/en/java/javase/25/docs/specs/man/jcmd.html"]
    elif runtime == "dotnet":
        tool, question = "dotnet-counters / dotnet-trace", "Inspect counters, then collect a bounded EventPipe trace for the observed CPU, GC or thread-pool problem."
        sources = ["https://learn.microsoft.com/en-us/dotnet/core/diagnostics/eventpipe"]
    else:
        tool, question = "Clippy / Miri / Loom / samply", "Use static checks first; choose Miri for small memory tests, Loom for modeled concurrency, or samply for a measured hotspot."
        sources = ["https://github.com/rust-lang/miri", "https://github.com/tokio-rs/loom", "https://github.com/mstange/samply"]
    return {"runtime": runtime, "classification": category, "classification_is_hypothesis": True,
            "recommended_probe": tool, "question": question, "tool_availability": "not_probed",
            "budget": {"initial_capture_seconds": 15, "max_hypotheses": 3, "max_repair_attempts": 2},
            "steps": ["Preserve the failing input, expected behavior, source revision and test identity.",
                      question, "Patch the smallest source change supported by observed evidence.",
                      "Replay the original unchanged test; then run affected regression checks.",
                      "Keep skipped, failed-retry, changed-test or incomplete evidence unresolved."],
            "sources": sources, "execution": "plan_only"}


class DebugEvidenceTools:
    def __init__(self, workspace, *, enabled=False):
        self.workspace = workspace
        self.enabled = enabled is True

    @staticmethod
    def owns(name):
        return name in TOOL_NAMES

    def definitions(self, prompt):
        return TOOLS if self.enabled and self.workspace is not None and wants_debugging(prompt) else []

    def call(self, name, args, *, enabled):
        if not self.enabled or self.workspace is None or name not in TOOL_NAMES or name not in enabled:
            raise PermissionError("Debug evidence tools are not enabled for this task")
        from jsonschema import Draft202012Validator, ValidationError
        schema = next(t["inputSchema"] for t in TOOLS if t["name"] == name)
        try:
            Draft202012Validator(schema).validate(args)
        except ValidationError as exc:
            raise ValueError("Invalid debug evidence arguments") from exc
        if name == "star_debug_report":
            return summarize_report(self.workspace, read_report(self.workspace, args["path"]))
        if name == "star_debug_compare":
            return compare_reports(read_report(self.workspace, args["baseline"]),
                                   read_report(self.workspace, args["candidate"]))
        if name == "star_debug_source":
            return source_window(self.workspace, args["path"], args["line"], args.get("radius", 5))
        return diagnostic_plan(args["symptom"], args["runtime"])
