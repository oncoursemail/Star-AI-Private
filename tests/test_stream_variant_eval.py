"""Offline tests for paired, signed STAR stream-variant evaluation."""
from dataclasses import replace

import pytest

from star.stream_variant_eval import (
    SignedStreamTrial,
    StreamCase,
    StreamTrial,
    StreamVariantLimits,
    evaluate_stream_variants,
    roster_digest,
    sign_stream_trial,
)

NOW = 1_800_000_000
KEY = b"star-test-host-validation-key-32-bytes-minimum"
ENV = "a" * 64


def cases(count=30, *, split="holdout"):
    domains = ("voice", "gaming", "creator", "knowledge")
    required_dimensions = {
        "voice": ("turn_taking", "groundedness"),
        "gaming": ("held_out_skill", "game_completion"),
        "creator": ("game_completion",),
        "knowledge": ("groundedness",),
    }
    required_metrics = {
        "voice": ("first_content_ms", "first_audible_ms", "audio_underrun_rate", "obs_output_skip_rate"),
        "gaming": ("game_frame_p99_ms", "audio_underrun_rate", "obs_output_skip_rate", "peak_vram_mib"),
        "creator": ("first_content_ms", "peak_cpu_millicores", "peak_ram_mib"),
        "knowledge": ("first_content_ms", "tokens_per_second", "memory_tokens"),
    }
    return [
        StreamCase(
            case_id=f"case-{i:03d}",
            domain=domains[i % len(domains)],
            split=split,
            required_dimensions=required_dimensions[domains[i % len(domains)]],
            required_metrics=required_metrics[domains[i % len(domains)]],
        )
        for i in range(count)
    ]


def trial(case, variant, i, **changes):
    candidate = variant == "candidate"
    values = {
        "trial_id": f"{variant}-{i:03d}",
        "experiment_id": "experiment-001",
        "case_id": case.case_id,
        "variant": variant,
        "revision": "candidate-v2" if candidate else "baseline-v1",
        "environment_sha256": ENV,
        "execution_status": "completed",
        "task_success": True,
        "turn_taking_success": True if "turn_taking" in case.required_dimensions else None,
        "groundedness_success": True if "groundedness" in case.required_dimensions else None,
        "held_out_skill_success": True if "held_out_skill" in case.required_dimensions else None,
        "game_completion_success": True if "game_completion" in case.required_dimensions else None,
        "first_content_ms": (400.0 if candidate else 450.0) if "first_content_ms" in case.required_metrics else None,
        "first_audible_ms": (520.0 if candidate else 600.0) if "first_audible_ms" in case.required_metrics else None,
        "game_frame_p99_ms": (17.2 if candidate else 17.0) if "game_frame_p99_ms" in case.required_metrics else None,
        "audio_underrun_rate": 0.001 if "audio_underrun_rate" in case.required_metrics else None,
        "obs_output_skip_rate": 0.001 if "obs_output_skip_rate" in case.required_metrics else None,
        "peak_cpu_millicores": (3100 if candidate else 3000) if "peak_cpu_millicores" in case.required_metrics else None,
        "peak_ram_mib": (6100 if candidate else 6000) if "peak_ram_mib" in case.required_metrics else None,
        "peak_vram_mib": (7100 if candidate else 7000) if "peak_vram_mib" in case.required_metrics else None,
        "tokens_per_second": (23.0 if candidate else 20.0) if "tokens_per_second" in case.required_metrics else None,
        "memory_tokens": (1250 if candidate else 1200) if "memory_tokens" in case.required_metrics else None,
        "evidence_sha256": f"{i + (1000 if candidate else 0):064x}",
        "observed_unix_s": NOW - 60,
    }
    values.update(changes)
    return StreamTrial(**values)


def signed_trials(roster, transform=None):
    output = []
    for i, case in enumerate(roster):
        for variant in ("baseline", "candidate"):
            item = trial(case, variant, i)
            if transform is not None:
                item = transform(item, case, variant, i)
            output.append(sign_stream_trial(item, validation_key=KEY))
    return output


def limits(**changes):
    values = {
        "min_pairs": 30,
        "min_holdout_pairs": 20,
        "min_holdout_domains": 3,
        "max_task_success_regression": 0.02,
        "max_turn_taking_regression": 0.03,
        "max_groundedness_regression": 0.03,
        "max_held_out_skill_regression": 0.03,
        "max_game_completion_regression": 0.03,
        "max_first_content_regression_fraction": 0.05,
        "max_first_audible_regression_fraction": 0.05,
        "max_game_frame_regression_fraction": 0.05,
        "max_audio_underrun_regression": 0.001,
        "max_obs_output_skip_regression": 0.001,
        "max_vram_regression_mib": 256,
        "max_cpu_regression_fraction": 0.10,
        "max_ram_regression_fraction": 0.10,
        "max_memory_tokens_regression_fraction": 0.10,
        "min_first_audible_improvement_fraction": 0.05,
        "max_validation_age_s": 7 * 86400,
    }
    values.update(changes)
    return StreamVariantLimits(**values)


def evaluate(roster, trials, **limit_changes):
    return evaluate_stream_variants(
        roster,
        trials,
        validation_key=KEY,
        expected_roster_sha256=roster_digest(roster),
        baseline_revision="baseline-v1",
        candidate_revision="candidate-v2",
        now_unix_s=NOW,
        limits=limits(**limit_changes),
    )


def test_candidate_passes_with_faster_audio_and_no_quality_regression():
    roster = cases()
    report = evaluate(roster, signed_trials(roster))

    assert report["overall"] == "PASS"
    assert report["promotion"] == "never_automatic"
    assert report["counts"]["complete_pairs"] == 30
    assert report["counts"]["holdout_domains"] == ["creator", "gaming", "knowledge", "voice"]
    assert report["dimensions"]["task_success"]["delta"] == 0.0
    assert report["metrics"]["first_audible_ms"]["improvement_fraction"] > 0.05
    assert report["metrics"]["tokens_per_second"]["improvement_fraction"] == 0.15


def test_candidate_quality_regression_fails_noninferiority():
    roster = cases()

    def degrade(item, case, variant, i):
        if variant == "candidate" and i < 4:
            return replace(item, task_success=False)
        return item

    report = evaluate(roster, signed_trials(roster, degrade))
    assert report["overall"] == "FAIL"
    gate = next(g for g in report["gates"] if g["name"] == "task_success_noninferiority")
    assert gate["status"] == "FAIL"


def test_candidate_game_frame_regression_is_detected():
    roster = cases()

    def degrade(item, case, variant, i):
        if variant == "candidate" and case.domain == "gaming":
            return replace(item, game_frame_p99_ms=22.0)
        return item

    report = evaluate(roster, signed_trials(roster, degrade))
    assert report["overall"] == "FAIL"
    gate = next(g for g in report["gates"] if g["name"] == "game_frame_p99_ms_nonregression")
    assert gate["status"] == "FAIL"


def test_cpu_and_ram_pressure_regressions_are_gated():
    roster = cases()

    def degrade(item, case, variant, i):
        if variant == "candidate" and case.domain == "creator":
            return replace(item, peak_cpu_millicores=5000, peak_ram_mib=9000)
        return item

    report = evaluate(roster, signed_trials(roster, degrade))
    assert report["overall"] == "FAIL"
    by_name = {g["name"]: g["status"] for g in report["gates"]}
    assert by_name["peak_cpu_millicores_nonregression"] == "FAIL"
    assert by_name["peak_ram_mib_nonregression"] == "FAIL"


def test_candidate_must_meet_an_explicit_speed_goal():
    roster = cases()

    def too_small(item, case, variant, i):
        if variant == "candidate" and case.domain == "voice":
            return replace(item, first_audible_ms=590.0)
        return item

    report = evaluate(roster, signed_trials(roster, too_small))
    assert report["overall"] == "FAIL"
    gate = next(g for g in report["gates"] if g["name"] == "first_audible_ms_improvement")
    assert gate["status"] == "FAIL"


def test_hmac_tampering_is_rejected():
    roster = cases()
    items = signed_trials(roster)
    tampered = replace(items[0].trial, task_success=False)
    items[0] = SignedStreamTrial(trial=tampered, receipt=items[0].receipt)

    with pytest.raises(ValueError, match="invalid independent host receipt"):
        evaluate(roster, items)


def test_roster_digest_mismatch_is_rejected():
    roster = cases()
    with pytest.raises(ValueError, match="roster differs"):
        evaluate_stream_variants(
            roster,
            signed_trials(roster),
            validation_key=KEY,
            expected_roster_sha256="b" * 64,
            baseline_revision="baseline-v1",
            candidate_revision="candidate-v2",
            now_unix_s=NOW,
            limits=limits(),
        )


def test_paired_environment_mismatch_is_rejected():
    roster = cases()

    def mismatch(item, case, variant, i):
        if i == 0 and variant == "candidate":
            return replace(item, environment_sha256="b" * 64)
        return item

    with pytest.raises(ValueError, match="same host/game/harness environment"):
        evaluate(roster, signed_trials(roster, mismatch))


def test_missing_pair_reduces_holdout_coverage_and_is_inconclusive():
    roster = cases()
    items = signed_trials(roster)[:-1]
    report = evaluate(roster, items)
    assert report["overall"] == "INCONCLUSIVE"
    assert report["counts"]["complete_pairs"] == 29
    assert any(g["name"] == "holdout_coverage" and g["status"] == "INCONCLUSIVE"
               for g in report["gates"])


def test_error_pair_is_excluded_not_counted_as_task_failure():
    roster = cases()

    def error_candidate(item, case, variant, i):
        if i == 0 and variant == "candidate":
            return replace(
                item,
                execution_status="error",
                task_success=None,
                turn_taking_success=None,
                groundedness_success=None,
                held_out_skill_success=None,
                game_completion_success=None,
                first_content_ms=None,
                first_audible_ms=None,
                game_frame_p99_ms=None,
                audio_underrun_rate=None,
                obs_output_skip_rate=None,
                peak_cpu_millicores=None,
                peak_ram_mib=None,
                peak_vram_mib=None,
                tokens_per_second=None,
                memory_tokens=None,
            )
        return item

    report = evaluate(roster, signed_trials(roster, error_candidate))
    assert report["counts"]["incomplete_or_error_pairs"] == 1
    assert report["counts"]["complete_pairs"] == 29
    assert report["overall"] == "INCONCLUSIVE"


def test_required_metric_missing_is_rejected():
    roster = cases()

    def missing(item, case, variant, i):
        if i == 0 and variant == "candidate":
            return replace(item, first_audible_ms=None)
        return item

    with pytest.raises(ValueError, match="missing required metric"):
        evaluate(roster, signed_trials(roster, missing))


def test_asymmetric_optional_metric_is_rejected():
    roster = cases()

    def asymmetry(item, case, variant, i):
        if i == 0 and variant == "baseline":
            return replace(item, peak_cpu_millicores=3000)
        return item

    with pytest.raises(ValueError, match="asymmetric metric availability"):
        evaluate(roster, signed_trials(roster, asymmetry))


def test_development_pairs_do_not_satisfy_holdout_minimums():
    roster = cases(split="development")
    report = evaluate(roster, signed_trials(roster))
    assert report["overall"] == "INCONCLUSIVE"
    assert report["counts"]["development_pairs"] == 30
    assert report["counts"]["holdout_pairs"] == 0


def test_stale_trials_are_rejected():
    roster = cases()

    def stale(item, case, variant, i):
        return replace(item, observed_unix_s=NOW - 8 * 86400)

    with pytest.raises(ValueError, match="outside the validation age limit"):
        evaluate(roster, signed_trials(roster, stale))


def test_future_trials_are_rejected():
    roster = cases()

    def future(item, case, variant, i):
        return replace(item, observed_unix_s=NOW + 120)

    with pytest.raises(ValueError, match="future-dated"):
        evaluate(roster, signed_trials(roster, future))


def test_duplicate_trial_ids_are_rejected():
    roster = cases()
    items = signed_trials(roster)
    items[1] = sign_stream_trial(
        replace(items[1].trial, trial_id=items[0].trial.trial_id),
        validation_key=KEY,
    )
    with pytest.raises(ValueError, match="trial IDs must be unique"):
        evaluate(roster, items)


def test_invalid_speed_limit_configuration_is_rejected():
    with pytest.raises(ValueError, match="explicit speed/throughput"):
        StreamVariantLimits()


def test_invalid_boolean_or_nonfinite_measurements_are_rejected():
    case = cases(1)[0]
    with pytest.raises(ValueError, match="first_audible_ms"):
        trial(case, "baseline", 0, first_audible_ms=float("nan"))
    with pytest.raises(ValueError, match="task_success"):
        trial(case, "baseline", 0, task_success=1)


def test_trial_constructor_does_not_accept_private_content_fields():
    case = cases(1)[0]
    with pytest.raises(TypeError):
        trial(case, "baseline", 0, transcript="do not retain")


def test_paired_mcnemar_reports_directional_evidence():
    roster = cases()

    def improve(item, case, variant, i):
        if variant == "candidate" and i < 6:
            return replace(item, task_success=True)
        if variant == "baseline" and i < 6:
            return replace(item, task_success=False)
        return item

    report = evaluate(roster, signed_trials(roster, improve))
    task = report["dimensions"]["task_success"]
    assert task["candidate_only_successes"] == 6
    assert task["baseline_only_successes"] == 0
    assert task["mcnemar_one_sided_p"] == pytest.approx(1 / 64)
