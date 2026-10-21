"""Compare bounded, caller-supplied semantic observations without executing code.

This original evidence-consistency checker prevents empty or partially reported
runs from being called matches. A MATCH proves equality of the supplied records
only. Producer labels, completion claims and hashes do not authenticate a run.
"""
from __future__ import annotations

import re

CONTRACT_VERSION = "star-semantic-contract-v1"
EVIDENCE_VERSION = "star-semantic-evidence-v1"
MAX_CASES = 256
MAX_OBSERVABLES = 16
MAX_EVENTS = 128
MAX_TOTAL_EVENTS = 4096
MAX_EVENT_BYTES = 128
MAX_MEMORY_BYTES = 128 * 1024 * 1024
MAX_ISSUES = 24
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,119}\Z")
_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
_HEX = re.compile(r"[a-fA-F0-9]*\Z")
_STATUSES = frozenset({"complete", "skipped", "unsupported", "error", "unknown"})


def _keys(value: object, names: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != names:
        raise ValueError(f"{label} has missing, unknown, or invalid fields")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded ASCII identifier")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        raise ValueError("SHA-256 values must contain exactly 64 hexadecimal characters")
    return value.lower()


def _integer(value: object, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} to {high}")
    return value


def _items(value: object, low: int, high: int, label: str) -> list:
    if type(value) is not list or not low <= len(value) <= high:
        raise ValueError(f"{label} must be a list with {low} to {high} entries")
    return value


def _observable(value: object, *, specification: bool) -> dict:
    if type(value) is not dict or type(value.get("kind")) is not str:
        raise ValueError("Each observable must declare its kind")
    kind = value["kind"]
    common = {"name", "kind"}
    if kind == "bits":
        keys = common | {"width_bits"} | (set() if specification else {"hex"})
    elif kind == "memory_sha256":
        keys = common | {"size_bytes"} | (set() if specification else {"sha256"})
    elif kind == "events":
        keys = common | ({"max_events"} if specification else {"events"})
    else:
        raise ValueError("Observable kind must be bits, memory_sha256, or events")
    _keys(value, keys, "Observable")
    result: dict = {"name": _identifier(value["name"], "Observable name"), "kind": kind}
    if kind == "bits":
        width = _integer(value["width_bits"], 1, 128, "width_bits")
        result["width_bits"] = width
        if not specification:
            raw = value["hex"]
            if (type(raw) is not str or len(raw) != (width + 3) // 4 or not _HEX.fullmatch(raw)
                    or int(raw, 16) >= 1 << width):
                raise ValueError("Bit observations require a zero-padded raw hex value of the declared width")
            result["hex"] = raw.lower()
    elif kind == "memory_sha256":
        result["size_bytes"] = _integer(value["size_bytes"], 0, MAX_MEMORY_BYTES, "size_bytes")
        if not specification:
            result["sha256"] = _digest(value["sha256"])
    elif specification:
        result["max_events"] = _integer(value["max_events"], 1, MAX_EVENTS, "max_events")
    else:
        result["events"] = []
        for event in _items(value["events"], 0, MAX_EVENTS, "events"):
            _keys(event, {"tag", "data_hex"}, "Event")
            tag = _identifier(event["tag"], "Event tag")
            raw = event["data_hex"]
            if (type(raw) is not str or len(raw) > MAX_EVENT_BYTES * 2
                    or len(raw) % 2 or not _HEX.fullmatch(raw)):
                raise ValueError("Event data_hex must be bounded whole-byte hexadecimal data")
            result["events"].append({"tag": tag, "data_hex": raw.lower()})
    return result


def _contract(value: object) -> dict:
    value = _keys(value, {"schema_version", "suite_id", "suite_sha256", "reference_artifact_sha256",
                  "candidate_artifact_sha256", "cases"}, "Contract")
    if value["schema_version"] != CONTRACT_VERSION:
        raise ValueError("Unsupported semantic contract schema_version")
    result = {"suite_id": _identifier(value["suite_id"], "suite_id"),
              "suite_sha256": _digest(value["suite_sha256"]),
              "reference_artifact_sha256": _digest(value["reference_artifact_sha256"]),
              "candidate_artifact_sha256": _digest(value["candidate_artifact_sha256"]),
              "cases": []}
    case_ids = set()
    for case in _items(value["cases"], 1, MAX_CASES, "Contract cases"):
        _keys(case, {"case_id", "input_sha256", "observables"}, "Contract case")
        case_id = _identifier(case["case_id"], "case_id")
        if case_id in case_ids:
            raise ValueError("Contract case IDs must be unique")
        case_ids.add(case_id)
        observables = [_observable(item, specification=True)
                       for item in _items(case["observables"], 1, MAX_OBSERVABLES, "Contract observables")]
        if len({item["name"] for item in observables}) != len(observables):
            raise ValueError("Contract observable names must be unique within each case")
        result["cases"].append({"case_id": case_id, "input_sha256": _digest(case["input_sha256"]),
                                "observables": observables})
    return result


def _evidence(value: object) -> dict:
    value = _keys(value, {"schema_version", "suite_id", "suite_sha256", "artifact_sha256", "producer_id",
                  "run_id", "complete", "exit_code", "unsupported_operations", "unverified_stubs",
                  "cases"}, "Evidence")
    if value["schema_version"] != EVIDENCE_VERSION:
        raise ValueError("Unsupported semantic evidence schema_version")
    if type(value["complete"]) is not bool:
        raise ValueError("Evidence complete must be a boolean")
    exit_code = value["exit_code"]
    if exit_code is not None:
        exit_code = _integer(exit_code, -(1 << 31), (1 << 32) - 1, "exit_code")
    result = {"suite_id": _identifier(value["suite_id"], "suite_id"),
              "suite_sha256": _digest(value["suite_sha256"]),
              "artifact_sha256": _digest(value["artifact_sha256"]),
              "producer_id": _identifier(value["producer_id"], "producer_id"),
              "run_id": _identifier(value["run_id"], "run_id"), "complete": value["complete"],
              "exit_code": exit_code,
              "unsupported_operations": _integer(value["unsupported_operations"], 0, 1_000_000,
                                                 "unsupported_operations"),
              "unverified_stubs": _integer(value["unverified_stubs"], 0, 1_000_000, "unverified_stubs"),
              "cases": []}
    total_events = 0
    for case in _items(value["cases"], 0, MAX_CASES, "Evidence cases"):
        _keys(case, {"case_id", "input_sha256", "status", "observations"}, "Evidence case")
        if type(case["status"]) is not str or case["status"] not in _STATUSES:
            raise ValueError("Unsupported evidence case status")
        observations = [_observable(item, specification=False)
                        for item in _items(case["observations"], 0, MAX_OBSERVABLES, "Observations")]
        total_events += sum(len(item["events"]) for item in observations if item["kind"] == "events")
        if total_events > MAX_TOTAL_EVENTS:
            raise ValueError("Evidence exceeds its total ordered-event budget")
        result["cases"].append({"case_id": _identifier(case["case_id"], "case_id"),
                                "input_sha256": _digest(case["input_sha256"]), "status": case["status"],
                                "observations": observations})
    return result


class _Issues:
    def __init__(self):
        self.items: list[dict] = []
        self.total = 0
        self.incomparable = False
        self.incomplete = False

    def add(self, category: str, code: str, side: str, case_id: str = "", observable: str = "") -> None:
        self.total += 1
        if category == "incomparable":
            self.incomparable = True
        else:
            self.incomplete = True
        if len(self.items) < MAX_ISSUES:
            item = {"category": category, "code": code, "side": side}
            if case_id:
                item["case_id"] = case_id
            if observable:
                item["observable"] = observable
            self.items.append(item)


def _index(items: list[dict], key: str, issues: _Issues, side: str, case_id: str = "") -> dict:
    result = {}
    for item in items:
        name = item[key]
        if name in result:
            issues.add("incomparable", "duplicate_case" if key == "case_id" else "duplicate_observable",
                       side, name if key == "case_id" else case_id, "" if key == "case_id" else name)
        else:
            result[name] = item
    return result


def _coverage(contract: dict, report: dict, side: str, issues: _Issues) -> dict:
    for field in ("suite_id", "suite_sha256"):
        if report[field] != contract[field]:
            issues.add("incomparable", f"{field}_mismatch", side)
    if report["artifact_sha256"] != contract[f"{side}_artifact_sha256"]:
        issues.add("incomparable", "artifact_pin_mismatch", side)
    if report["complete"] is not True:
        issues.add("incomplete", "run_not_complete", side)
    if report["exit_code"] is None:
        issues.add("incomplete", "exit_code_unreported", side)
    elif report["exit_code"] != 0:
        issues.add("incomplete", "exit_code_nonzero", side)
    for field in ("unsupported_operations", "unverified_stubs"):
        if report[field]:
            issues.add("incomplete", field, side)

    actual = _index(report["cases"], "case_id", issues, side)
    expected_ids = {case["case_id"] for case in contract["cases"]}
    for extra in sorted(set(actual) - expected_ids):
        issues.add("incomparable", "unexpected_case", side, extra)
    covered = {}
    for case in contract["cases"]:
        case_id = case["case_id"]
        found = actual.get(case_id)
        if found is None:
            issues.add("incomplete", "missing_case", side, case_id)
            continue
        if found["input_sha256"] != case["input_sha256"]:
            issues.add("incomparable", "input_pin_mismatch", side, case_id)
        if found["status"] != "complete":
            issues.add("incomplete", f"case_{found['status']}", side, case_id)
        observations = _index(found["observations"], "name", issues, side, case_id)
        names = {item["name"] for item in case["observables"]}
        for extra in sorted(set(observations) - names):
            issues.add("incomparable", "unexpected_observable", side, case_id, extra)
        for spec in case["observables"]:
            name = spec["name"]
            observed = observations.get(name)
            if observed is None:
                issues.add("incomplete", "missing_observable", side, case_id, name)
                continue
            if observed["kind"] != spec["kind"]:
                issues.add("incomparable", "observable_kind_mismatch", side, case_id, name)
            elif spec["kind"] == "bits" and observed["width_bits"] != spec["width_bits"]:
                issues.add("incomparable", "bit_width_mismatch", side, case_id, name)
            elif spec["kind"] == "memory_sha256" and observed["size_bytes"] != spec["size_bytes"]:
                issues.add("incomparable", "memory_size_mismatch", side, case_id, name)
            elif spec["kind"] == "events" and len(observed["events"]) > spec["max_events"]:
                issues.add("incomparable", "event_budget_exceeded", side, case_id, name)
        covered[case_id] = observations
    return covered


def _counterexample(case_id: str, spec: dict, reference: dict, candidate: dict) -> dict | None:
    kind = spec["kind"]
    output = {"case_id": case_id, "observable": spec["name"], "kind": kind}
    if kind == "bits":
        if reference["hex"] == candidate["hex"]:
            return None
        output.update(width_bits=spec["width_bits"], reference=reference["hex"], candidate=candidate["hex"])
    elif kind == "memory_sha256":
        if reference["sha256"] == candidate["sha256"]:
            return None
        output.update(size_bytes=spec["size_bytes"], reference=reference["sha256"], candidate=candidate["sha256"])
    else:
        left, right = reference["events"], candidate["events"]
        if left == right:
            return None
        index = next((i for i, (a, b) in enumerate(zip(left, right)) if a != b), min(len(left), len(right)))
        output.update(event_index=index, reference=left[index] if index < len(left) else None,
                      candidate=right[index] if index < len(right) else None,
                      reference_event_count=len(left), candidate_event_count=len(right))
    return output


def compare_semantic_evidence(contract: dict, reference: dict, candidate: dict) -> dict:
    """Require exact, nonempty coverage before comparing raw observations.

    Malformed schemas raise ValueError. Well-formed reports with inconsistent
    identities or ambiguous/extra coverage are INCOMPARABLE. Missing or unfinished
    coverage is INCOMPLETE. Only coherent complete reports can return MISMATCH
    or MATCH. suite_sha256 identifies the caller's suite; it is not the hash of
    this contract's JSON encoding. Actual input-file pins belong to the reader.
    """
    expected, left, right = _contract(contract), _evidence(reference), _evidence(candidate)
    issues = _Issues()
    if left["producer_id"] == right["producer_id"]:
        issues.add("incomparable", "same_producer", "both")
    if left["run_id"] == right["run_id"]:
        issues.add("incomparable", "same_run", "both")
    reference_cases = _coverage(expected, left, "reference", issues)
    candidate_cases = _coverage(expected, right, "candidate", issues)
    output = {
        "schema_version": "star-semantic-comparison-v1",
        "verdict": "INCOMPARABLE" if issues.incomparable else "INCOMPLETE" if issues.incomplete else "MATCH",
        "scope": "supplied_records_only", "read_only": True, "executed": False, "runtime_verified": False,
        "reference_authenticity": "unverified", "independence_verified": False,
        "comparison_complete": False, "first_counterexample": None,
        "counts": {"expected_cases": len(expected["cases"]), "reference_cases": len(left["cases"]),
                   "candidate_cases": len(right["cases"]), "compared_cases": 0, "compared_observables": 0,
                   "mismatched_observables": 0, "issues": issues.total,
                   "omitted_issues": issues.total - len(issues.items)},
        "issues": issues.items,
        "notice": (
            "MATCH means all declared raw observations in the supplied complete records agree. "
            "Completion, unsupported-operation/stub counts, suite/input/artifact hashes, and distinct "
            "producer/run labels are caller claims, not authenticated executions. This does not prove "
            "unreported behavior, all-instruction correctness, game compatibility, timing, or speed. "
            "No code was executed and no lesson was promoted."
        ),
    }
    if issues.incomparable or issues.incomplete:
        return output
    output["comparison_complete"] = True
    for case in expected["cases"]:
        case_id = case["case_id"]
        output["counts"]["compared_cases"] += 1
        for spec in case["observables"]:
            output["counts"]["compared_observables"] += 1
            difference = _counterexample(case_id, spec, reference_cases[case_id][spec["name"]],
                                         candidate_cases[case_id][spec["name"]])
            if difference is not None:
                output["verdict"] = "MISMATCH"
                output["counts"]["mismatched_observables"] += 1
                if output["first_counterexample"] is None:
                    output["first_counterexample"] = difference
    return output
