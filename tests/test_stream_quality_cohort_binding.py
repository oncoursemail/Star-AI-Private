"""Cross-run calibration cannot be spliced into a faster-model recommendation."""
from dataclasses import replace

import pytest

from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_quality_route_selector import (
    QualityGatedRouteSelector,
    VerifiedPairedRouteCases,
    VerifiedRouteTrialSummary,
)

SUITE = "a" * 64
COHORT = "c" * 64
OTHER_COHORT = "d" * 64
NOW = 1_800_000_000


def _catalog():
    return HostInferenceCatalog((
        HostModelRoute("base", "commentary", "cpu", "llamacpp", "1" * 64, "2" * 64, 400, 0),
        HostModelRoute("fast", "commentary", "gpu", "llamacpp", "3" * 64, "2" * 64, 400, 1600),
    ))


def _summary(c, alias, latency, cohort=COHORT):
    return VerifiedRouteTrialSummary(
        alias, c.profile_for(alias), "commentary", "game_recording",
        SUITE, 30, 30, latency, 2800, NOW - 50, True,
        eval_cohort_sha256=cohort,
    )


def _receipt(c, cohort=COHORT):
    return VerifiedPairedRouteCases(
        "base", "fast", c.profile_for("base"), c.profile_for("fast"),
        "commentary", "game_recording", SUITE,
        (True,) * 30, (True,) * 30, (False,) * 30,
        NOW - 50, True, eval_cohort_sha256=cohort,
    )


def _advise(c, baseline, candidate, receipt):
    selector = QualityGatedRouteSelector(
        catalog=c, summaries=(baseline, candidate), paired_cases=(receipt,),
    )
    return selector.advise(
        owner_approved=True, baseline_alias="base", task_kind="commentary",
        workload="game_recording", suite_sha256=SUITE,
        now_unix_s=NOW, max_p95_ms=900, max_total_gpu_mib=7000,
    )


def test_matching_cohort_with_matched_cases_permits_manual_advice_only():
    c = _catalog()
    advice = _advise(c, _summary(c, "base", 400), _summary(c, "fast", 90), _receipt(c))
    assert advice.route_alias == "fast"
    assert not advice.authorizes_model_launch
    assert not advice.authorizes_game_action


@pytest.mark.parametrize("which", ["baseline", "candidate", "receipt"])
def test_identical_suite_and_outcomes_cannot_combine_different_run_cohorts(which):
    c = _catalog()
    baseline = _summary(c, "base", 400)
    candidate = _summary(c, "fast", 90)
    receipt = _receipt(c)
    if which == "baseline":
        baseline = replace(baseline, eval_cohort_sha256=OTHER_COHORT)
    elif which == "candidate":
        candidate = replace(candidate, eval_cohort_sha256=OTHER_COHORT)
    else:
        receipt = replace(receipt, eval_cohort_sha256=OTHER_COHORT)
    advice = _advise(c, baseline, candidate, receipt)
    assert advice.route_alias == "base"
    assert advice.reason == "verified_baseline_only"


@pytest.mark.parametrize("which", ["baseline", "candidate", "receipt"])
def test_legacy_missing_cohort_fails_closed_for_fast_route(which):
    c = _catalog()
    baseline = _summary(c, "base", 400)
    candidate = _summary(c, "fast", 90)
    receipt = _receipt(c)
    if which == "baseline":
        baseline = replace(baseline, eval_cohort_sha256=None)
    elif which == "candidate":
        candidate = replace(candidate, eval_cohort_sha256=None)
    else:
        receipt = replace(receipt, eval_cohort_sha256=None)
    assert _advise(c, baseline, candidate, receipt).route_alias == "base"


@pytest.mark.parametrize("bad", [True, 3, "", "z" * 64, "1" * 63, "A" * 64, 10**1000])
def test_invalid_cohort_digest_fails_before_recommendation(bad):
    c = _catalog()
    with pytest.raises(ValueError, match="cohort"):
        replace(_summary(c, "base", 400), eval_cohort_sha256=bad)
    with pytest.raises(ValueError, match="cohort"):
        replace(_receipt(c), eval_cohort_sha256=bad)
