"""Offline development-response checks; no model transport or promotion authority."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE = ROOT / "evals/general_knowledge/development-v1.prompts.json"
DEFAULT_ORACLES = ROOT / "evals/general_knowledge/development-v1.oracles.json"
MAX_FILE = 1_048_576
MAX_RESPONSE = 8_192
IDS = [f"GF-{number:02}" for number in range(1, 11)]
DECLARATION = "operator_declared_not_authenticated"
SCOPE = "Ten public development tasks; artifact consistency only, no model delivery, broad knowledge or gain proof."


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _reject(message):
    raise ValueError(message)


def _keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        _reject("Unexpected or missing artifact fields")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        _reject("Invalid integer field")


def _label(value):
    if (type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}", value)
            or "://" in value):
        _reject("Invalid declared identity label")


def _hash(value, length=64):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        _reject("Invalid identity digest")


def _tree(value):
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > 20_000 or depth > 16:
            _reject("JSON complexity limit exceeded")
        if type(item) is dict:
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            item.encode("utf-8")  # refuse unpaired surrogate text
        elif type(item) is float and not math.isfinite(item):
            _reject("Nonfinite JSON number")
        elif type(item) is int and abs(item) > 10**18:
            _reject("JSON integer limit exceeded")


def parse_json(data: bytes, limit=MAX_FILE):
    if type(data) is not bytes or len(data) > limit:
        _reject("JSON byte limit exceeded")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _reject("Duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: _reject("Nonfinite JSON number"))
        _tree(value)
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        _reject("Invalid bounded JSON")
    return value


def _bytes(path, limit=MAX_FILE):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        _reject("JSON byte limit exceeded")
    return data


def _read(path, limit=MAX_FILE):
    data = _bytes(path, limit)
    return parse_json(data, limit), digest(data)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class Artifact:
    raw: bytes

    @property
    def data(self):
        return parse_json(self.raw, 100_000)

    @property
    def sha256(self):
        return digest(self.raw)


def load_suite(path=DEFAULT_SUITE) -> Artifact:
    artifact = Artifact(_bytes(path, 100_000))
    data = artifact.data
    _keys(data, ("schema_version", "suite_id", "status", "split", "authorship", "scope", "system", "tasks"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["split"] != "development":
        _reject("Only the development suite version is supported")
    _label(data["suite_id"])
    if type(data["system"]) is not str or not 1 <= len(data["system"]) <= 2000:
        _reject("Invalid shared prompt")
    if type(data["tasks"]) is not list or len(data["tasks"]) != 10:
        _reject("Exactly ten development tasks are required")
    for task, identifier in zip(data["tasks"], IDS):
        _keys(task, ("id", "category", "prompt", "response_fields"))
        if task["id"] != identifier or type(task["prompt"]) is not str or not 1 <= len(task["prompt"]) <= 6000:
            _reject("Invalid ordered task or prompt")
        _label(task["category"])
        fields = task["response_fields"]
        if type(fields) is not list or not 1 <= len(fields) <= 4 or len(set(fields)) != len(fields):
            _reject("Invalid response fields")
        for field in fields:
            _label(field)
    return artifact


def load_oracles(suite: Artifact, path=DEFAULT_ORACLES) -> Artifact:
    artifact = Artifact(_bytes(path, 100_000))
    data = artifact.data
    _keys(data, ("schema_version", "suite_id", "status", "visibility", "grading_policy", "cases"))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["suite_id"] != suite.data["suite_id"]:
        _reject("Oracle suite identity differs")
    _keys(data["cases"], IDS)
    for task in suite.data["tasks"]:
        case = data["cases"][task["id"]]
        _keys(case, ("expected", "derivation"))
        _keys(case["expected"], task["response_fields"])
        if type(case["derivation"]) is not str or not case["derivation"]:
            _reject("Missing oracle derivation")
        _format(case["expected"], case["expected"])
    return artifact


def grader_digest():
    return digest(Path(__file__).read_bytes())


def prepare(suite: Artifact, repeats=1) -> dict:
    """Allowlisted messages only. This function never reads an oracle file."""
    _integer(repeats, 1, 3)
    requests = []
    for task in suite.data["tasks"]:
        messages = [{"role": "system", "content": suite.data["system"]},
                    {"role": "user", "content": task["prompt"]}]
        fingerprint = digest(_canonical({"task_id": task["id"], "messages": messages}))
        for attempt in range(1, repeats + 1):
            requests.append({"task_id": task["id"], "attempt": attempt,
                             "request_sha256": fingerprint, "messages": messages})
    return {"schema_version": 1, "kind": "general_foundation_prepared", "suite_id": suite.data["suite_id"],
            "suite_sha256": suite.sha256, "grader_sha256": grader_digest(), "repeats": repeats,
            "requests": requests, "scope": SCOPE}


def _model(value):
    _keys(value, ("model_id", "revision", "weights_sha256", "tokenizer_sha256", "quantization"))
    for key in ("model_id", "revision", "quantization"):
        _label(value[key])
    for key in ("weights_sha256", "tokenizer_sha256"):
        _hash(value[key])


def _identity(value):
    _keys(value, ("app_commit", "source_sha256", "request_builder_sha256", "adapter_sha256",
                  "backend_build", "model", "mode", "options"))
    _hash(value["app_commit"], 40)
    for key in ("source_sha256", "request_builder_sha256", "adapter_sha256"):
        _hash(value[key])
    _label(value["backend_build"])
    _label(value["mode"])
    _model(value["model"])
    options = value["options"]
    _keys(options, ("temperature", "top_p", "max_output_tokens", "seed", "stop", "tools"))
    for key, low, high in (("temperature", 0, 2), ("top_p", 0, 1)):
        if type(options[key]) not in (int, float) or not math.isfinite(options[key]) or not low <= options[key] <= high:
            _reject("Invalid declared generation options")
    _integer(options["max_output_tokens"], 16, 512)
    if options["seed"] is not None:
        _integer(options["seed"], 0, 2**32 - 1)
    if type(options["stop"]) is not list or len(options["stop"]) > 4 or any(type(x) is not str or not 1 <= len(x) <= 80 for x in options["stop"]):
        _reject("Invalid stop declaration")
    if options["tools"] != [] or type(options["tools"]) is not list:
        _reject("This corpus requires declared tools disabled")


def _format(value, expected):
    _keys(value, expected)
    for key, reference in expected.items():
        item = value[key]
        if reference is None:
            if item is not None and type(item) is not int:
                _reject("Expected nullable integer")
        elif type(reference) is list:
            if type(item) is not list or len(item) > 16 or any(type(x) is not str or len(x) > 128 for x in item):
                _reject("Expected bounded identifier array")
        elif type(item) is not type(reference):
            _reject("Wrong response value type")
        if key in {"end_utc", "delivery_date"}:
            pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z" if key == "end_utc" else r"\d{4}-\d{2}-\d{2}"
            if not re.fullmatch(pattern, item):
                _reject("Wrong date representation")
            datetime.fromisoformat(item.replace("Z", "+00:00"))
    if "denominator" in expected and (value["denominator"] <= 0 or math.gcd(value["numerator"], value["denominator"]) != 1):
        _reject("Expected a reduced positive-denominator fraction")


def _rows(suite, oracles, run):
    _tree(run)
    _keys(run, ("schema_version", "kind", "suite_id", "suite_sha256", "oracle_sha256", "grader_sha256", "identity", "repeats", "rows"))
    if type(run["schema_version"]) is not int or run["schema_version"] != 1 or run["kind"] != "general_foundation_raw_run":
        _reject("Expected a raw run; saved grades are not accepted")
    for key, expected in (("suite_id", suite.data["suite_id"]), ("suite_sha256", suite.sha256),
                          ("oracle_sha256", oracles.sha256), ("grader_sha256", grader_digest())):
        if run[key] != expected:
            _reject("Suite, oracle or grader identity differs")
    _identity(run["identity"])
    plan = prepare(suite, run["repeats"])
    if type(run["rows"]) is not list or len(run["rows"]) != len(plan["requests"]):
        _reject("Full task and attempt coverage is required")
    for row, request in zip(run["rows"], plan["requests"]):
        _keys(row, ("task_id", "attempt", "request_sha256", "response_sha256", "outcome", "response", "error_code"))
        _integer(row["attempt"], 1, run["repeats"])
        if any(row[key] != request[key] for key in ("task_id", "attempt", "request_sha256")):
            _reject("Ordered row or request identity differs")
        if type(row["response"]) is not str or len(row["response"].encode("utf-8")) > MAX_RESPONSE:
            _reject("Raw response byte limit exceeded")
        if row["response_sha256"] != digest(row["response"].encode("utf-8")):
            _reject("Raw response digest differs")
        if row["outcome"] == "completed" and row["error_code"] is None:
            continue
        if (row["outcome"] != "transport_error" or row["response"] != ""
                or row["error_code"] not in {"timeout", "connection_failed", "cancelled", "unavailable"}):
            _reject("Invalid terminal response or bounded error code")
    return run["rows"]


def score_run(suite: Artifact, oracles: Artifact, run: dict) -> dict:
    rows, scored, counts = _rows(suite, oracles, run), [], {}
    for row in rows:
        if row["outcome"] == "transport_error":
            status = "transport_error"
        elif not row["response"].strip():
            status = "empty"
        else:
            expected = oracles.data["cases"][row["task_id"]]["expected"]
            try:
                answer = parse_json(row["response"].encode("utf-8"), MAX_RESPONSE)
                _format(answer, expected)
                status = "pass" if answer == expected else "incorrect"
            except (ValueError, TypeError, OverflowError):
                status = "invalid_format"
        counts[status] = counts.get(status, 0) + 1
        scored.append({key: row[key] for key in ("task_id", "attempt", "request_sha256", "response_sha256", "error_code")}
                      | {"status": status})
    return {"schema_version": 1, "kind": "general_foundation_scores", "suite_sha256": suite.sha256,
            "oracle_sha256": oracles.sha256, "grader_sha256": grader_digest(), "identity": run["identity"],
            "provenance": DECLARATION, "scope": SCOPE, "repeats": run["repeats"], "total": len(scored),
            "counts": counts, "rows": scored}


def _app_build(value):
    """Exact, predeclared software identity. Labels are NOT authentication."""
    _keys(value, ("app_commit", "source_sha256"))
    _hash(value["app_commit"], 40)
    _hash(value["source_sha256"])


def compare_runs(suite, oracles, baseline, candidate, *, axis="same",
                 expected_baseline_model=None, expected_candidate_model=None,
                 expected_baseline_app=None, expected_candidate_app=None):
    before, after = score_run(suite, oracles, baseline), score_run(suite, oracles, candidate)
    if axis not in {"same", "model", "app"} or before["repeats"] != after["repeats"]:
        _reject("Invalid comparison axis or repeats")
    first, second = dict(before["identity"]), dict(after["identity"])
    if axis == "model":
        _model(expected_baseline_model)
        _model(expected_candidate_model)
        if first.pop("model") != expected_baseline_model or second.pop("model") != expected_candidate_model:
            _reject("Declared model pair differs from the explicit expected pair")
    elif expected_baseline_model is not None or expected_candidate_model is not None:
        _reject("Expected model pairs require explicit model-axis comparison")
    if axis == "app":
        # Compare app revisions with the model, tokenizer, adapter, prompt
        # builder, backend, mode and inference options held identical.
        _app_build(expected_baseline_app)
        _app_build(expected_candidate_app)
        if (expected_baseline_app["app_commit"] == expected_candidate_app["app_commit"]
                or expected_baseline_app["source_sha256"] == expected_candidate_app["source_sha256"]):
            _reject("App comparison requires distinct committed source identities")
        fields = ("app_commit", "source_sha256")
        before_app = {key: first.pop(key) for key in fields}
        after_app = {key: second.pop(key) for key in fields}
        if before_app != expected_baseline_app or after_app != expected_candidate_app:
            _reject("Declared source pair differs from the explicit expected app pair")
    elif expected_baseline_app is not None or expected_candidate_app is not None:
        _reject("Expected app pairs require explicit app-axis comparison")
    if _canonical(first) != _canonical(second):
        _reject("Declared source, model, adapter, backend, mode or options differ")
    changes = [{"task_id": a["task_id"], "attempt": a["attempt"], "baseline": a["status"], "candidate": b["status"]}
               for a, b in zip(before["rows"], after["rows"]) if a["status"] != b["status"]]
    return {"kind": "general_foundation_comparison", "axis": axis, "provenance": DECLARATION,
            "scope": SCOPE, "comparison_status": "incomplete_transport" if any(
                item["counts"].get("transport_error", 0) for item in (before, after)) else "artifact_consistent",
            "baseline": before, "candidate": after, "changes": changes}


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("list", "prepare", "score", "compare"))
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--oracles", type=Path, default=DEFAULT_ORACLES)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--axis", choices=("same", "model", "app"), default="same")
    parser.add_argument("--baseline-model", help="Explicit expected model identity JSON; model-axis only")
    parser.add_argument("--candidate-model", help="Explicit expected model identity JSON; model-axis only")
    parser.add_argument("--baseline-app", help="Expected app_commit/source_sha256 JSON; app-axis only")
    parser.add_argument("--candidate-app", help="Expected app_commit/source_sha256 JSON; app-axis only")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(arguments)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        suite = load_suite(args.suite)
        if args.command == "list":
            result = {"suite_id": suite.data["suite_id"], "suite_sha256": suite.sha256,
                      "scope": SCOPE, "tasks": [{k: task[k] for k in ("id", "category")} for task in suite.data["tasks"]]}
        elif args.command == "prepare":
            result = prepare(suite, args.repeats)
        else:
            oracles = load_oracles(suite, args.oracles)
            if args.command == "score":
                if args.run is None:
                    _reject("Score requires an explicit raw run")
                result = score_run(suite, oracles, _read(args.run)[0])
            else:
                if args.baseline is None or args.candidate is None:
                    _reject("Compare requires two explicit raw runs")
                result = compare_runs(suite, oracles, _read(args.baseline)[0], _read(args.candidate)[0],
                    axis=args.axis, expected_baseline_model=parse_json(args.baseline_model.encode(), 2048) if args.baseline_model else None,
                    expected_candidate_model=parse_json(args.candidate_model.encode(), 2048) if args.candidate_model else None,
                    expected_baseline_app=parse_json(args.baseline_app.encode(), 1024) if args.baseline_app else None,
                    expected_candidate_app=parse_json(args.candidate_app.encode(), 1024) if args.candidate_app else None)
        text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.out is None:
            print(text, end="")
        else:
            with args.out.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
    except (OSError, ValueError, TypeError, RecursionError):
        print("Artifact rejected: invalid, mismatched, unreadable or existing output; no model was called.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
