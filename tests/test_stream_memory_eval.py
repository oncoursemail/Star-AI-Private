from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac

import pytest

from star.stream_memory_eval import (
    MemoryCase,
    MemoryEvalLimits,
    MemoryTrial,
    SignedMemoryTrial,
    evaluate_memory_transfer,
    roster_digest,
)

_KEY = b"star-test-validation-key-32-bytes-minimum"
_NOW = 1_800_000_100


def _cases() -> list[MemoryCase]:
    domains = ("roblox", "minecraft", "survival", "strategy", "general")
    rows: list[MemoryCase] = []
    for index in range(40):
        memory_required = index < 20
        rows.append(MemoryCase(
            case_id=f"case-{index:02d}",
            domain=domains[index // 8],
            memory_required=memory_required,
            temporal_update_required=memory_required and index < 10,
            forgetting_required=memory_required and 10 <= index < 20,
            procedural_transfer=memory_required and 5 <= index < 15,
        ))
    return rows


def _trial(case: MemoryCase, variant: str, index: int, *,
           result: str | None = None, stale: bool = False,
           deleted: bool = False, latency_ms: int = 100,
           memory_tokens: int = 600) -> MemoryTrial:
    if result is None:
        if case.memory_required:
            success = index < 10 if variant == "baseline" else True
        else:
            success = index < 38
        result = "success" if success else "failure"
    return MemoryTrial(
        trial_id=f"trial-{variant}-{case.case_id}",
        case_id=case.case_id,
        variant=variant,
        revision="memory-v1" if variant == "baseline" else "memory-v2",
        run_id=f"run-{variant}-{case.case_id}",
        result=result,
        memory_applied=case.memory_required,
        current_revision_used=case.temporal_update_required,
        source_verified=case.memory_required,
        action_grounded=case.procedural_transfer,
        stale_memory_reused=stale,
        deleted_memory_reused=deleted,
        latency_ms=latency_ms,
        memory_tokens=memory_tokens if variant == "candidate" and case.memory_required else 0,
        evidence_sha256=hashlib.sha256(
            f"{variant}:{case.case_id}:{result}:{stale}:{deleted}".encode()
        ).hexdigest(),
        observed_unix_s=_NOW - 50,
    )


def _sign(trial: MemoryTrial) -> SignedMemoryTrial:
    receipt = hmac.new(_KEY, trial.canonical_bytes(), hashlib.sha256).hexdigest()
    return SignedMemoryTrial(trial=trial, receipt=receipt)


def _campaign(cases: list[MemoryCase] | None = None) -> tuple[list[MemoryCase], list[SignedMemoryTrial]]:
    roster = _cases() if cases is None else cases
    trials: list[SignedMemoryTrial] = []
    for index, case in enumerate(roster):
        trials.append(_sign(_trial(case, "baseline", index)))
        trials.append(_sign(_trial(case, "candidate", index)))
    return roster, trials


def _evaluate(cases: list[MemoryCase], trials: list[SignedMemoryTrial],
              limits: MemoryEvalLimits | None = None):
    return evaluate_memory_transfer(
        cases,
        trials,
        validation_key=_KEY,
        expected_roster_sha256=roster_digest(cases),
        baseline_revision="memory-v1",
        candidate_revision="memory-v2",
        now_unix_s=_NOW,
        limits=limits or MemoryEvalLimits(),
    )


def test_successful_memory_candidate_is_eligible_for_manual_pilot() -> None:
    cases, trials = _campaign()
    report = _evaluate(cases, trials)

    assert report.verdict == "eligible_for_owner_pilot"
    assert report.completed_pairs == 40
    assert report.incomplete_pairs == 0
    assert report.distinct_domains == 5
    assert report.memory_task_gain == 0.5
    assert report.candidate_only_successes == 10
    assert report.baseline_only_successes == 0
    assert report.memory_application_rate == 1.0
    assert report.source_verification_rate == 1.0
    assert report.temporal_accuracy == 1.0
    assert report.action_grounding_rate == 1.0
    assert report.stale_memory_reuses == 0
    assert report.deleted_memory_reuses == 0
    assert report.candidate_latency_p95_ms == 100.0
    assert report.candidate_memory_tokens_p95 == 600.0


def test_incomplete_pair_is_inconclusive_not_a_failure() -> None:
    cases, trials = _campaign()
    trials = [item for item in trials
              if not (item.trial.case_id == "case-39" and item.trial.variant == "candidate")]

    report = _evaluate(cases, trials)

    assert report.verdict == "inconclusive"
    assert report.incomplete_pairs == 1
    assert report.completed_pairs == 39


def test_infrastructure_error_contaminates_pair_instead_of_counting_as_failure() -> None:
    cases, trials = _campaign()
    changed = []
    for item in trials:
        if item.trial.case_id == "case-00" and item.trial.variant == "candidate":
            changed.append(_sign(replace(item.trial, result="error")))
        else:
            changed.append(item)

    report = _evaluate(cases, changed)

    assert report.verdict == "inconclusive"
    assert report.infrastructure_errors == 1
    assert report.completed_pairs == 39


def test_stale_memory_reuse_is_a_hard_regression() -> None:
    cases, trials = _campaign()
    changed = []
    for item in trials:
        if item.trial.case_id == "case-00" and item.trial.variant == "candidate":
            changed.append(_sign(replace(
                item.trial,
                current_revision_used=False,
                stale_memory_reused=True,
            )))
        else:
            changed.append(item)

    report = _evaluate(cases, changed)

    assert report.verdict == "regressed"
    assert report.stale_memory_reuses == 1


def test_deleted_memory_reuse_is_a_hard_regression() -> None:
    cases, trials = _campaign()
    changed = []
    for item in trials:
        if item.trial.case_id == "case-10" and item.trial.variant == "candidate":
            changed.append(_sign(replace(item.trial, deleted_memory_reused=True)))
        else:
            changed.append(item)

    report = _evaluate(cases, changed)

    assert report.verdict == "regressed"
    assert report.deleted_memory_reuses == 1


def test_candidate_must_not_regress_tasks_that_do_not_need_memory() -> None:
    cases, trials = _campaign()
    changed = []
    for item in trials:
        trial = item.trial
        if trial.variant == "candidate" and trial.case_id in {"case-20", "case-21", "case-22", "case-23"}:
            trial = replace(trial, result="failure")
            changed.append(_sign(trial))
        else:
            changed.append(item)

    report = _evaluate(cases, changed)

    assert report.verdict == "regressed"
    assert report.no_memory_delta is not None
    assert report.no_memory_delta < -0.05


def test_no_material_gain_does_not_claim_a_successful_improvement() -> None:
    cases, trials = _campaign()
    changed = []
    for item in trials:
        trial = item.trial
        if trial.variant == "candidate" and trial.case_id in {
            f"case-{index:02d}" for index in range(10, 20)
        }:
            trial = replace(trial, result="failure")
        changed.append(_sign(trial) if trial is not item.trial else item)

    report = _evaluate(cases, changed)

    assert report.verdict == "no_material_gain"
    assert report.memory_task_gain == 0.0


def test_bad_receipt_is_rejected() -> None:
    cases, trials = _campaign()
    tampered = list(trials)
    first = tampered[0]
    tampered[0] = SignedMemoryTrial(first.trial, "0" * 64)

    with pytest.raises(ValueError, match="invalid independent"):
        _evaluate(cases, tampered)


def test_roster_mismatch_is_rejected() -> None:
    cases, trials = _campaign()
    changed_cases = list(cases)
    changed_cases[0] = replace(cases[0], domain="different")

    with pytest.raises(ValueError, match="preregistered"):
        evaluate_memory_transfer(
            changed_cases,
            trials,
            validation_key=_KEY,
            expected_roster_sha256=roster_digest(cases),
            baseline_revision="memory-v1",
            candidate_revision="memory-v2",
            now_unix_s=_NOW,
        )


def test_old_trial_is_rejected() -> None:
    cases, trials = _campaign()
    old = replace(trials[0].trial, observed_unix_s=_NOW - 40 * 86400)
    trials[0] = _sign(old)

    with pytest.raises(ValueError, match="validation age"):
        _evaluate(cases, trials)


def test_duplicate_case_variant_is_rejected() -> None:
    cases, trials = _campaign()
    trials.append(trials[0])

    with pytest.raises(ValueError, match="duplicate trial ID"):
        _evaluate(cases, trials)


def test_bool_is_not_accepted_as_latency_or_memory_tokens() -> None:
    case = _cases()[0]
    base = _trial(case, "baseline", 0)

    with pytest.raises(ValueError, match="latency_ms"):
        replace(base, latency_ms=True)
    with pytest.raises(ValueError, match="memory_tokens"):
        replace(base, memory_tokens=True)


def test_memory_lane_flags_require_memory_dependent_case() -> None:
    with pytest.raises(ValueError, match="memory_required"):
        MemoryCase(
            case_id="bad-case",
            domain="general",
            memory_required=False,
            temporal_update_required=True,
        )


def test_limits_reject_boolean_and_out_of_range_thresholds() -> None:
    with pytest.raises(ValueError, match="min_pairs"):
        MemoryEvalLimits(min_pairs=True)
    with pytest.raises(ValueError, match="min_source_verification_rate"):
        MemoryEvalLimits(min_source_verification_rate=1.1)


def test_paired_variants_must_use_distinct_run_ids() -> None:
    cases, trials = _campaign()
    changed = []
    baseline_run = trials[0].trial.run_id
    for item in trials:
        if item.trial.case_id == "case-00" and item.trial.variant == "candidate":
            changed.append(_sign(replace(item.trial, run_id=baseline_run)))
        else:
            changed.append(item)

    with pytest.raises(ValueError, match="distinct run IDs"):
        _evaluate(cases, changed)



def test_signed_trial_is_bound_to_declared_memory_revision() -> None:
    cases, trials = _campaign()
    changed = []
    for item in trials:
        if item.trial.case_id == "case-00" and item.trial.variant == "candidate":
            changed.append(_sign(replace(item.trial, revision="memory-v3")))
        else:
            changed.append(item)

    with pytest.raises(ValueError, match="revision does not match"):
        _evaluate(cases, changed)
