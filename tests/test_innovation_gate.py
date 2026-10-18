"""Deterministic innovation-gate tests; no model, network, or GPU needed."""
from dataclasses import asdict
import json
import math
import pytest

from star.innovation_gate import PairedCase, PairedExperiment, parse_experiment, review_experiment

DIGEST = "a" * 64


def case(i, *, base=False, cand=False, base_ms=100.0, cand_ms=95.0,
         base_mem=512.0, cand_mem=512.0, independent=True, hidden=True, critical=False):
    return PairedCase(
        case_id=f"case_{i}", domain="code", baseline_pass=base, candidate_pass=cand,
        baseline_ms=base_ms, candidate_ms=cand_ms,
        baseline_peak_mib=base_mem, candidate_peak_mib=cand_mem,
        independent=independent, blind_holdout=hidden, critical=critical,
        evidence_sha256=DIGEST,
    )


def experiment(cases, *, objective="quality", base_hw="epyc7451", cand_hw="epyc7451",
               baseline_suite=DIGEST, candidate_suite=DIGEST):
    return PairedExperiment("exp001", objective, "rev_before", "rev_after", base_hw, cand_hw,
                            baseline_suite, candidate_suite, tuple(cases))


def test_significant_quality_gain_is_only_a_review_candidate():
    cases = [case(i, base=i >= 14, cand=True) for i in range(40)]
    result = review_experiment(experiment(cases))
    assert result.recommendation == "review_candidate"
    assert result.requires_owner_review is True
    assert result.wins == 14 and result.losses == 0 and result.ties == 26
    assert result.one_sided_sign_p < .05
    assert result.candidate_pass_rate == 1


def test_small_sample_and_no_gains_cannot_pass():
    assert review_experiment(experiment([case(i, base=False, cand=True) for i in range(12)])).recommendation == "needs_more_evidence"
    result = review_experiment(experiment([case(i, base=True, cand=True) for i in range(40)]))
    assert result.recommendation == "needs_more_evidence" and result.one_sided_sign_p == 1


def test_critical_regression_overrides_major_gain():
    cases = [case(i, base=i == 0, cand=i != 0, critical=i == 0) for i in range(40)]
    assert review_experiment(experiment(cases)).recommendation == "reject_regression"


def test_memory_and_quality_latency_caps():
    cases = [case(i, base=False, cand=True, cand_mem=550) for i in range(40)]
    assert review_experiment(experiment(cases)).recommendation == "reject_regression"
    cases = [case(i, base=False, cand=True, cand_ms=125) for i in range(40)]
    assert review_experiment(experiment(cases)).recommendation == "reject_regression"


def test_speed_mode_improves_measured_p95_without_breaking_quality():
    cases = [case(i, base=True, cand=True, cand_ms=85) for i in range(40)]
    assert review_experiment(experiment(cases, objective="speed")).recommendation == "review_candidate"
    failures = [case(i, base=True, cand=i != 0, cand_ms=20) for i in range(40)]
    assert review_experiment(experiment(failures, objective="speed")).recommendation == "reject_regression"
    too_small = [case(i, base=True, cand=True, cand_ms=99) for i in range(40)]
    assert review_experiment(experiment(too_small, objective="speed")).recommendation == "needs_more_evidence"


def test_different_hardware_suite_or_unverified_evidence_is_invalid():
    all_cases = [case(i, base=False, cand=True) for i in range(40)]
    assert review_experiment(experiment(all_cases, cand_hw="different")).recommendation == "invalid_evidence"
    assert review_experiment(experiment(all_cases, candidate_suite="b" * 64)).recommendation == "invalid_evidence"
    all_cases[3] = case(3, hidden=False)
    assert review_experiment(experiment(all_cases)).recommendation == "invalid_evidence"
    all_cases[3] = case(3, independent=False)
    assert review_experiment(experiment(all_cases)).recommendation == "invalid_evidence"


def test_strict_input_validation():
    with pytest.raises(ValueError, match="Duplicate"):
        experiment([case(1), case(1)])
    for bad in (float('nan'), float('inf'), 0, -1, True, "100"):
        with pytest.raises(ValueError, match="candidate_ms"):
            case(1, cand_ms=bad)
    with pytest.raises(ValueError, match="SHA-256"):
        PairedCase(**{**asdict(case(1)), "evidence_sha256": "oops"})
    with pytest.raises(ValueError, match="boolean|true or false"):
        PairedCase(**{**asdict(case(1)), "critical": 1})
    with pytest.raises(ValueError, match="differ"):
        PairedExperiment("exp1", "quality", "same", "same", "host", "host", DIGEST, DIGEST, (case(1),))
    with pytest.raises(ValueError, match="Objective"):
        experiment([case(1)], objective="deploy")
    with pytest.raises(ValueError, match="Invalid"):
        case("../evil")
    with pytest.raises(ValueError, match="1 to"):
        experiment([])
    with pytest.raises(ValueError, match="512"):
        experiment([case(i) for i in range(513)])


def test_parse_external_json_and_reject_bad_shapes():
    example = json.loads(json.dumps(asdict(experiment([case(1), case(2)]))))
    parsed = parse_experiment(example)
    assert isinstance(parsed.cases[0], PairedCase)
    assert parsed.experiment_id == "exp001"
    for bad in (None, [], {}, {**example, "cases": {}}, {**example, "cases": [{"oops": 42}]}):
        with pytest.raises(ValueError):
            parse_experiment(bad)


def test_no_auto_deploy_fields_and_determinism():
    cases = [case(i, base=i >= 20, cand=True) for i in range(40)]
    receipt = review_experiment(experiment(cases))
    assert receipt == review_experiment(experiment(cases))
    assert "deploy" not in asdict(receipt)
    assert math.isclose(receipt.one_sided_sign_p, 0.00000095, abs_tol=1e-8)
