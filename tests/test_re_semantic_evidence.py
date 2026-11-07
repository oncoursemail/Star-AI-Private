"""Original synthetic regressions for non-vacuous recompilation evidence.

These tests compare supplied records. They do not execute PS3 instructions or
establish real hardware, emulator, translator, or game correctness.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from star.re_semantic_evidence import compare_semantic_evidence


def digest(text):
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def example():
    contract = {
        "schema_version": "star-semantic-contract-v1",
        "suite_id": "original-synthetic-suite",
        "suite_sha256": digest("suite source fixture"),
        "reference_artifact_sha256": digest("reference artifact"),
        "candidate_artifact_sha256": digest("candidate artifact"),
        "cases": [
            {"case_id": "integer-result", "input_sha256": digest("integer inputs"),
             "observables": [
                 {"name": "r3", "kind": "bits", "width_bits": 32},
                 {"name": "output-memory", "kind": "memory_sha256", "size_bytes": 4},
                 {"name": "syscalls", "kind": "events", "max_events": 8},
             ]},
            {"case_id": "float-bits", "input_sha256": digest("float inputs"),
             "observables": [{"name": "f1", "kind": "bits", "width_bits": 32}]},
        ],
    }
    observations = [
        [{"name": "r3", "kind": "bits", "width_bits": 32, "hex": "00000007"},
         {"name": "output-memory", "kind": "memory_sha256", "size_bytes": 4, "sha256": digest("data")},
         {"name": "syscalls", "kind": "events",
          "events": [{"tag": "write", "data_hex": "0102"}, {"tag": "exit", "data_hex": "00"}]}],
        [{"name": "f1", "kind": "bits", "width_bits": 32, "hex": "00000000"}],
    ]
    reports = []
    for side in ("reference", "candidate"):
        reports.append({
            "schema_version": "star-semantic-evidence-v1",
            "suite_id": contract["suite_id"], "suite_sha256": contract["suite_sha256"],
            "artifact_sha256": contract[f"{side}_artifact_sha256"],
            "producer_id": f"{side}-observer", "run_id": f"{side}-run-001",
            "complete": True, "exit_code": 0, "unsupported_operations": 0, "unverified_stubs": 0,
            "cases": [{"case_id": case["case_id"], "input_sha256": case["input_sha256"],
                       "status": "complete", "observations": deepcopy(observations[index])}
                      for index, case in enumerate(contract["cases"])],
        })
    return contract, reports[0], reports[1]


def codes(result):
    return {issue["code"] for issue in result["issues"]}


def test_complete_matching_records_have_a_narrow_honest_scope():
    supplied = example()
    saved = deepcopy(supplied)
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "MATCH"
    assert result["comparison_complete"] is True
    assert result["counts"]["expected_cases"] == result["counts"]["compared_cases"] == 2
    assert result["counts"]["compared_observables"] == 4
    assert result["first_counterexample"] is None
    assert result["scope"] == "supplied_records_only"
    assert result["read_only"] is True
    assert result["executed"] is False
    assert result["runtime_verified"] is False
    assert result["reference_authenticity"] == "unverified"
    assert result["independence_verified"] is False
    assert supplied == saved


def test_empty_reports_with_success_claims_never_match():
    contract, reference, candidate = example()
    reference["cases"] = []
    candidate["cases"] = []
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPLETE"
    assert result["comparison_complete"] is False
    assert result["counts"]["compared_cases"] == 0
    assert "missing_case" in codes(result)


def test_empty_contract_cannot_make_an_empty_comparison_vacuously_true():
    contract, reference, candidate = example()
    contract["cases"] = reference["cases"] = candidate["cases"] = []
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)


@pytest.mark.parametrize("side", [1, 2])
def test_missing_case_prevents_match_even_when_every_reported_case_agrees(side):
    supplied = example()
    supplied[side]["cases"].pop()
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPLETE"
    assert "missing_case" in codes(result)


@pytest.mark.parametrize("side", [1, 2])
def test_incomplete_run_does_not_become_complete_from_case_results(side):
    supplied = example()
    supplied[side]["complete"] = False
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPLETE"
    assert "run_not_complete" in codes(result)


@pytest.mark.parametrize("exit_code", [None, 1, -11, 0xC0000005, -(1 << 31), (1 << 32) - 1])
@pytest.mark.parametrize("side", [1, 2])
def test_unsuccessful_or_unreported_exit_cannot_be_hidden_by_complete_matching_cases(side, exit_code):
    supplied = example()
    supplied[side]["exit_code"] = exit_code
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPLETE"
    assert result["comparison_complete"] is False
    assert result["counts"]["compared_cases"] == 0
    assert ("exit_code_unreported" if exit_code is None else "exit_code_nonzero") in codes(result)


@pytest.mark.parametrize("exit_code", [True, False, 0.0, "0", -(1 << 31) - 1, 1 << 32])
def test_exit_code_requires_a_bounded_integer_or_explicit_null(exit_code):
    supplied = example()
    supplied[2]["exit_code"] = exit_code
    with pytest.raises(ValueError):
        compare_semantic_evidence(*supplied)


def test_exit_code_cannot_be_silently_omitted():
    supplied = example()
    del supplied[2]["exit_code"]
    with pytest.raises(ValueError):
        compare_semantic_evidence(*supplied)


@pytest.mark.parametrize("status", ["skipped", "unsupported", "error", "unknown"])
@pytest.mark.parametrize("side", [1, 2])
def test_noncomplete_case_status_never_matches_even_with_equal_observations(side, status):
    supplied = example()
    supplied[side]["cases"][0]["status"] = status
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPLETE"
    assert f"case_{status}" in codes(result)


@pytest.mark.parametrize("field", ["unsupported_operations", "unverified_stubs"])
@pytest.mark.parametrize("side", [1, 2])
def test_unhandled_or_unverified_work_cannot_be_hidden_by_matching_outputs(side, field):
    supplied = example()
    supplied[side][field] = 1
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPLETE"
    assert field in codes(result)


def test_measured_interpreter_fallback_is_not_automatically_an_unsupported_operation():
    contract, reference, candidate = example()
    for report in (reference, candidate):
        report["cases"][0]["observations"][2]["events"].insert(
            0, {"tag": "interpreter_fallback", "data_hex": "01"})
    assert compare_semantic_evidence(contract, reference, candidate)["verdict"] == "MATCH"


@pytest.mark.parametrize("side", [1, 2])
def test_duplicate_case_cannot_replace_missing_coverage(side):
    supplied = example()
    supplied[side]["cases"][1] = deepcopy(supplied[side]["cases"][0])
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPARABLE"
    assert {"duplicate_case", "missing_case"} <= codes(result)


def test_extra_case_is_rejected_instead_of_silently_ignored():
    contract, reference, candidate = example()
    extra = deepcopy(candidate["cases"][0])
    extra["case_id"] = "unexpected"
    candidate["cases"].append(extra)
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert "unexpected_case" in codes(result)


@pytest.mark.parametrize("field,new_value", [
    ("suite_id", "different-suite"), ("suite_sha256", digest("other suite")),
    ("artifact_sha256", digest("other executable")),
])
@pytest.mark.parametrize("side", [1, 2])
def test_suite_and_role_specific_artifact_identity_must_match_contract(side, field, new_value):
    supplied = example()
    supplied[side][field] = new_value
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPARABLE"
    assert result["counts"]["compared_cases"] == 0


@pytest.mark.parametrize("side", [1, 2])
def test_case_inputs_are_pinned_independently_of_matching_outputs(side):
    supplied = example()
    supplied[side]["cases"][0]["input_sha256"] = digest("different inputs")
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "INCOMPARABLE"
    assert "input_pin_mismatch" in codes(result)


@pytest.mark.parametrize("field,code", [("producer_id", "same_producer"), ("run_id", "same_run")])
def test_distinct_report_labels_are_required_for_comparison(field, code):
    contract, reference, candidate = example()
    candidate[field] = reference[field]
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert code in codes(result)
    assert result["independence_verified"] is False


def test_same_test_image_can_be_observed_by_distinct_producers_and_runs():
    contract, reference, candidate = example()
    contract["candidate_artifact_sha256"] = contract["reference_artifact_sha256"]
    candidate["artifact_sha256"] = reference["artifact_sha256"]
    assert compare_semantic_evidence(contract, reference, candidate)["verdict"] == "MATCH"


def test_missing_observable_prevents_match():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"].pop()
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPLETE"
    assert "missing_observable" in codes(result)


def test_duplicate_observable_is_ambiguous_even_when_values_agree():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"].append(deepcopy(candidate["cases"][0]["observations"][0]))
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert "duplicate_observable" in codes(result)


def test_unexpected_observable_is_not_discarded():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"].append(
        {"name": "undeclared", "kind": "bits", "width_bits": 8, "hex": "01"})
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert "unexpected_observable" in codes(result)


@pytest.mark.parametrize("replacement,code", [
    ({"name": "r3", "kind": "events", "events": []}, "observable_kind_mismatch"),
    ({"name": "r3", "kind": "bits", "width_bits": 16, "hex": "0007"}, "bit_width_mismatch"),
])
def test_observable_layout_must_match_the_declared_contract(replacement, code):
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][0] = replacement
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert code in codes(result)


def test_memory_length_cannot_change_while_reusing_a_digest():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][1]["size_bytes"] = 8
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert "memory_size_mismatch" in codes(result)


def test_events_cannot_exceed_the_contracts_declared_capture_budget():
    contract, reference, candidate = example()
    contract["cases"][0]["observables"][2]["max_events"] = 1
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPARABLE"
    assert "event_budget_exceeded" in codes(result)


def test_case_and_observable_order_can_change_but_identity_is_preserved():
    contract, reference, candidate = example()
    candidate["cases"].reverse()
    for case in candidate["cases"]:
        case["observations"].reverse()
    assert compare_semantic_evidence(contract, reference, candidate)["verdict"] == "MATCH"


def test_hex_letter_case_does_not_change_raw_values():
    contract, reference, candidate = example()
    for report in (reference, candidate):
        report["cases"][0]["observations"][0]["hex"] = "000000af"
    candidate["cases"][0]["observations"][0]["hex"] = "000000AF"
    candidate["suite_sha256"] = candidate["suite_sha256"].upper()
    candidate["artifact_sha256"] = candidate["artifact_sha256"].upper()
    candidate["cases"][0]["input_sha256"] = candidate["cases"][0]["input_sha256"].upper()
    assert compare_semantic_evidence(contract, reference, candidate)["verdict"] == "MATCH"


def test_raw_signed_zero_difference_is_preserved_without_float_guessing():
    contract, reference, candidate = example()
    candidate["cases"][1]["observations"][0]["hex"] = "80000000"
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "MISMATCH"
    assert result["first_counterexample"] == {
        "case_id": "float-bits", "observable": "f1", "kind": "bits", "width_bits": 32,
        "reference": "00000000", "candidate": "80000000",
    }


def test_nan_payload_bits_are_compared_exactly():
    contract, reference, candidate = example()
    reference["cases"][1]["observations"][0]["hex"] = "7fc00001"
    candidate["cases"][1]["observations"][0]["hex"] = "7fc00002"
    assert compare_semantic_evidence(contract, reference, candidate)["verdict"] == "MISMATCH"


def test_memory_digest_difference_identifies_region_and_size():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][1]["sha256"] = digest("else")
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "MISMATCH"
    difference = result["first_counterexample"]
    assert difference["observable"] == "output-memory"
    assert difference["size_bytes"] == 4
    assert difference["reference"] == digest("data")
    assert difference["candidate"] == digest("else")


def test_event_order_is_semantic_evidence_not_a_set():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][2]["events"].reverse()
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "MISMATCH"
    assert result["first_counterexample"]["event_index"] == 0
    assert result["first_counterexample"]["reference"]["tag"] == "write"
    assert result["first_counterexample"]["candidate"]["tag"] == "exit"


def test_added_event_reports_first_divergence_after_common_prefix():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][2]["events"].append({"tag": "unexpected", "data_hex": ""})
    result = compare_semantic_evidence(contract, reference, candidate)
    difference = result["first_counterexample"]
    assert result["verdict"] == "MISMATCH"
    assert difference["event_index"] == 2
    assert difference["reference"] is None
    assert difference["candidate"] == {"tag": "unexpected", "data_hex": ""}


def test_first_counterexample_follows_contract_order_and_counts_all_differences():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][0]["hex"] = "00000008"
    candidate["cases"][1]["observations"][0]["hex"] = "80000000"
    candidate["cases"].reverse()
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["first_counterexample"]["case_id"] == "integer-result"
    assert result["counts"]["mismatched_observables"] == 2
    assert result["counts"]["compared_cases"] == 2


def test_incomplete_data_is_not_compared_even_if_an_available_value_differs():
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][0]["hex"] = "00000008"
    candidate["cases"].pop()
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPLETE"
    assert result["first_counterexample"] is None
    assert result["counts"]["compared_observables"] == 0


@pytest.mark.parametrize("field,value", [
    ("schema_version", "unknown"), ("complete", 1), ("unsupported_operations", True),
    ("unsupported_operations", -1), ("unverified_stubs", 1_000_001),
    ("unverified_stubs", 1.5), ("producer_id", ""), ("run_id", "spaces are ambiguous"),
    ("suite_sha256", "z" * 64), ("unexpected", True),
])
def test_malformed_evidence_fields_raise_instead_of_matching(field, value):
    contract, reference, candidate = example()
    candidate[field] = value
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)


@pytest.mark.parametrize("replacement", [
    {"name": "r3", "kind": "bits", "width_bits": True, "hex": "0"},
    {"name": "r3", "kind": "bits", "width_bits": 129, "hex": "0" * 33},
    {"name": "r3", "kind": "bits", "width_bits": 32, "hex": "0x000007"},
    {"name": "r3", "kind": "bits", "width_bits": 32, "hex": "7"},
    {"name": "r3", "kind": "bits", "width_bits": 32, "hex": 7.0},
    {"name": "r3", "kind": "bits", "width_bits": 3, "hex": "f"},
    {"name": "r3", "kind": "float", "value": 0.0},
    {"name": "r3", "kind": "events", "events": [{"tag": "write", "data_hex": "1"}]},
    {"name": "r3", "kind": "events", "events": [{"tag": "write", "data_hex": "aa" * 129}]},
])
def test_ambiguous_widths_float_values_or_invalid_event_bytes_are_rejected(replacement):
    contract, reference, candidate = example()
    candidate["cases"][0]["observations"][0] = replacement
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)


def test_128_bit_observations_are_supported_without_numeric_rounding():
    contract, reference, candidate = example()
    contract["cases"][1]["observables"][0]["width_bits"] = 128
    for report in (reference, candidate):
        report["cases"][1]["observations"][0].update(width_bits=128, hex="fedcba98765432100123456789abcdef")
    assert compare_semantic_evidence(contract, reference, candidate)["verdict"] == "MATCH"


def expanded_example(count):
    contract, reference, candidate = example()
    source_spec = contract["cases"][1]
    source_ref = reference["cases"][1]
    source_candidate = candidate["cases"][1]
    contract["cases"], reference["cases"], candidate["cases"] = [], [], []
    for number in range(count):
        for target, source in ((contract, source_spec), (reference, source_ref), (candidate, source_candidate)):
            record = deepcopy(source)
            record.update(case_id=f"case-{number}", input_sha256=digest(f"input-{number}"))
            target["cases"].append(record)
    return contract, reference, candidate


def test_case_count_boundary_is_nonvacuous_and_bounded():
    supplied = expanded_example(256)
    result = compare_semantic_evidence(*supplied)
    assert result["verdict"] == "MATCH"
    assert result["counts"]["compared_cases"] == 256
    with pytest.raises(ValueError):
        compare_semantic_evidence(*expanded_example(257))


def test_contract_cannot_repeat_case_or_observable_identity():
    contract, reference, candidate = example()
    contract["cases"].append(deepcopy(contract["cases"][0]))
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)
    contract, reference, candidate = example()
    contract["cases"][0]["observables"].append(deepcopy(contract["cases"][0]["observables"][0]))
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)


def test_nonempty_cases_need_at_least_one_declared_observable():
    contract, reference, candidate = example()
    contract["cases"][0]["observables"] = []
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)


def test_total_events_are_bounded_across_cases():
    contract, reference, candidate = expanded_example(33)
    for expected in contract["cases"]:
        expected["observables"] = [{"name": "events", "kind": "events", "max_events": 128}]
    for report in (reference, candidate):
        for case in report["cases"]:
            case["observations"] = [{"name": "events", "kind": "events",
                                     "events": [{"tag": "event", "data_hex": "00"} for _ in range(128)]}]
    with pytest.raises(ValueError):
        compare_semantic_evidence(contract, reference, candidate)


def test_issue_details_and_output_size_remain_bounded():
    contract, reference, candidate = expanded_example(40)
    reference["cases"] = []
    candidate["cases"] = []
    result = compare_semantic_evidence(contract, reference, candidate)
    assert result["verdict"] == "INCOMPLETE"
    assert len(result["issues"]) == 24
    assert result["counts"]["issues"] == 80
    assert result["counts"]["omitted_issues"] == 56
    assert len(json.dumps(result)) < 24_000
