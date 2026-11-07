"""A trusted host's exact measured route attempts must not be cherry-picked."""
from dataclasses import replace
from hashlib import sha256
import math

import pytest

from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_quality_route_selector import QualityGatedRouteSelector
from star.stream_route_evidence_seal import verify_route_evaluation
from star.stream_route_measured_evaluator import (
    IndependentlyScoredAttempt, IndependentlyScoredRouteRun,
    RegisteredRouteCase, RegisteredRouteSuite, assemble_measured_route_evidence,
)

KEY = b"host-only-test-key-0123456789-123456789" * 2
NOW = 1_800_000_000
BUILD = "a" * 64


def digest(text):
    return sha256(text.encode()).hexdigest()


def catalog():
    return HostInferenceCatalog((
        HostModelRoute("baseline", "speech", "cpu", "llamacpp",
                       "1" * 64, "2" * 64, 500, 0),
        HostModelRoute("candidate", "speech", "gpu", "llamacpp",
                       "3" * 64, "2" * 64, 500, 1500),
    ))


def example():
    c = catalog()
    suite = RegisteredRouteSuite(
        task_kind="speech", workload="game_recording", rubric_sha256="e" * 64,
        preregistered_unix_s=NOW - 400,
        cases=tuple(RegisteredRouteCase(digest(f"case-{i}"), i == 3)
                    for i in range(30)),
    )

    def run(alias, delay, gpu, t):
        return IndependentlyScoredRouteRun(
            route_alias=alias, route_profile=c.profile_for(alias),
            completed_unix_s=NOW - t,
            attempts=tuple(
                IndependentlyScoredAttempt(
                    case_sha256=case.case_sha256,
                    scoring_artifact_sha256=digest(f"artifact-{alias}-{i}"),
                    passed=True,
                    end_to_end_ms=delay + (100 if i > 27 else 0),
                    total_gpu_peak_mib=gpu + (50 if i == 29 else 0),
                )
                for i, case in enumerate(suite.cases)
            ),
        )

    return c, suite, run("baseline", 550, 2400, 80), run("candidate", 200, 2900, 75)


def assemble(c, suite, baseline, candidate, **changes):
    args = dict(
        host_key=KEY, catalog=c, suite=suite,
        expected_suite_sha256=suite.suite_sha256,
        baseline=baseline, candidate=candidate,
        evaluator_build_sha256=BUILD,
        issued_unix_s=NOW - 10,
    )
    args.update(changes)
    return assemble_measured_route_evidence(**args)


def advise(c, bundle, *, now=NOW):
    return QualityGatedRouteSelector(
        catalog=c, summaries=bundle.summaries, paired_cases=bundle.paired_cases,
        require_signed_evidence=True, evidence_seal=bundle.seal,
        evidence_verification_key=KEY,
    ).advise(
        owner_approved=True, baseline_alias="baseline", task_kind="speech",
        workload="game_recording", suite_sha256=bundle.summaries[0].suite_sha256,
        now_unix_s=now, max_p95_ms=1000, max_total_gpu_mib=8000,
    )


def test_complete_measured_attempts_flow_into_signed_quality_advice():
    c, suite, base, fast = example()
    result = assemble(c, suite, base, fast)
    assert [x.trials for x in result.summaries] == [30, 30]
    assert [x.verified_successes for x in result.summaries] == [30, 30]
    assert [x.p95_end_to_end_ms for x in result.summaries] == [650, 300]
    assert [x.total_gpu_peak_mib for x in result.summaries] == [2450, 2950]
    assert result.paired_cases[0].critical_cases[3]
    assert verify_route_evaluation(host_key=KEY, seal=result.seal,
                                   summaries=result.summaries, paired_cases=result.paired_cases)
    advice = advise(c, result)
    assert advice.route_alias == "candidate"
    assert advice.baseline_p95_ms == 650
    assert advice.selected_p95_ms == 300
    assert not advice.authorizes_model_launch
    assert not advice.authorizes_game_action
    assert KEY.hex() not in repr(result)
    assert not hasattr(result, "host_key")


def test_random_cohorts_and_artifact_manifests_do_not_reuse_identifiers():
    c, suite, base, fast = example()
    one = assemble(c, suite, base, fast)
    two = assemble(c, suite, base, fast)
    assert one.seal.cohort_sha256 != two.seal.cohort_sha256
    assert one.seal.artifact_manifest_sha256 != two.seal.artifact_manifest_sha256
    assert one.seal.signature_hmac_sha256 != two.seal.signature_hmac_sha256


def test_failures_count_in_denominator_and_block_regressions():
    c, suite, base, fast = example()
    failed = replace(fast.attempts[3], passed=False, end_to_end_ms=1100)
    fast = replace(fast, attempts=fast.attempts[:3] + (failed,) + fast.attempts[4:])
    bundle = assemble(c, suite, base, fast)
    assert bundle.summaries[1].trials == 30
    assert bundle.summaries[1].verified_successes == 29
    assert bundle.paired_cases[0].candidate_outcomes[3] is False
    assert advise(c, bundle).route_alias == "baseline"


@pytest.mark.parametrize("edit", [
    "omitted", "reordered", "repeated", "unknown", "duplicated_artifact",
    "shared_artifact", "route_alias", "route_profile", "task_kind",
    "pre_registration", "future_completion", "stale_completion",
    "swapped_candidate", "wrong_suite", "wrong_rubric", "wrong_critical",
])
def test_rejects_nonmatching_or_cherry_picked_measured_runs(edit):
    c, suite, base, fast = example()
    updates = {}
    if edit == "omitted":
        fast = replace(fast, attempts=fast.attempts[:-1])
    elif edit == "reordered":
        fast = replace(fast, attempts=(fast.attempts[1], fast.attempts[0]) + fast.attempts[2:])
    elif edit == "repeated":
        fast = replace(fast, attempts=fast.attempts[:-1] + (fast.attempts[0],))
    elif edit == "unknown":
        fast = replace(fast, attempts=(replace(fast.attempts[0], case_sha256="f" * 64),)
                       + fast.attempts[1:])
    elif edit == "duplicated_artifact":
        fast = replace(fast, attempts=fast.attempts[:1] + (
            replace(fast.attempts[1], scoring_artifact_sha256=fast.attempts[0].scoring_artifact_sha256),
        ) + fast.attempts[2:])
    elif edit == "shared_artifact":
        fast = replace(fast, attempts=(replace(
            fast.attempts[0], scoring_artifact_sha256=base.attempts[0].scoring_artifact_sha256,
        ),) + fast.attempts[1:])
    elif edit == "route_alias":
        fast = replace(fast, route_alias="fake-model")
    elif edit == "route_profile":
        fast = replace(fast, route_profile=c.profile_for("baseline"))
    elif edit == "task_kind":
        suite = replace(suite, task_kind="coding")
        updates["expected_suite_sha256"] = suite.suite_sha256
    elif edit == "pre_registration":
        suite = replace(suite, preregistered_unix_s=NOW - 40)
        updates["expected_suite_sha256"] = suite.suite_sha256
    elif edit == "future_completion":
        fast = replace(fast, completed_unix_s=NOW)
    elif edit == "stale_completion":
        fast = replace(fast, completed_unix_s=NOW - 800)
    elif edit == "swapped_candidate":
        fast = base
    elif edit == "wrong_suite":
        updates["expected_suite_sha256"] = "f" * 64
    elif edit == "wrong_rubric":
        suite = replace(suite, rubric_sha256="b" * 64)
        updates["expected_suite_sha256"] = example()[1].suite_sha256
    else:
        cases = list(suite.cases)
        cases[3] = replace(cases[3], critical=False)
        suite = replace(suite, cases=tuple(cases))
        updates["expected_suite_sha256"] = example()[1].suite_sha256
    with pytest.raises((ValueError, TypeError)):
        assemble(c, suite, base, fast, **updates)


@pytest.mark.parametrize("field,value", [
    ("passed", 1), ("passed", "True"),
    ("end_to_end_ms", 0), ("end_to_end_ms", float("nan")),
    ("end_to_end_ms", float("inf")), ("end_to_end_ms", True),
    ("total_gpu_peak_mib", -1), ("total_gpu_peak_mib", float("inf")),
    ("total_gpu_peak_mib", 99999999999999999999999999999999),
    ("scoring_artifact_sha256", "NOT-A-DIGEST"),
    ("case_sha256", "A" * 64),
])
def test_malformed_independent_score_never_reaches_hmac(field, value):
    c, suite, base, fast = example()
    assert math.isfinite(fast.attempts[0].end_to_end_ms)
    with pytest.raises(ValueError):
        replace(fast.attempts[0], **{field: value})


def test_suite_rejects_duplicate_case_commitments_and_bool_flags():
    _, suite, _, _ = example()
    with pytest.raises(ValueError, match="unique"):
        replace(suite, cases=suite.cases[:-1] + (suite.cases[0],))
    with pytest.raises(ValueError, match="boolean"):
        replace(suite.cases[0], critical=1)
    with pytest.raises(ValueError, match="bounded"):
        replace(suite, cases=())


def test_hmac_detects_any_later_aggregate_mutation():
    c, suite, base, fast = example()
    bundle = assemble(c, suite, base, fast)
    forged_summary = replace(bundle.summaries[1], p95_end_to_end_ms=1)
    assert not verify_route_evaluation(
        host_key=KEY, seal=bundle.seal,
        summaries=(bundle.summaries[0], forged_summary),
        paired_cases=bundle.paired_cases,
    )


def test_fails_closed_on_invalid_host_key_and_incoherent_issuance():
    c, suite, base, fast = example()
    with pytest.raises(ValueError, match="key"):
        assemble(c, suite, base, fast, host_key=b"bad")
    with pytest.raises(ValueError, match="stale scored run"):
        assemble(c, suite, base, fast, issued_unix_s=NOW + 700)


def test_separate_preregistration_digest_required_for_changed_case_order():
    c, suite, base, fast = example()
    pinned = suite.suite_sha256
    modified = replace(suite, cases=(suite.cases[1], suite.cases[0]) + suite.cases[2:])
    with pytest.raises(ValueError, match="committed"):
        assemble(c, modified, base, fast, expected_suite_sha256=pinned)
