"""Host-verified paired outcomes prevent aggregate-only regressions."""
from dataclasses import replace

import pytest

from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_quality_route_selector import (
    QualityGatedRouteSelector,
    VerifiedPairedRouteCases,
    VerifiedRouteTrialSummary,
)

SUITE = "3" * 64
COHORT = "c" * 64
NOW = 1_800_000_000


def _catalog():
    return HostInferenceCatalog((
        HostModelRoute("base", "commentary", "cpu", "llamacpp", "a" * 64,
                       "b" * 64, 320, 0),
        HostModelRoute("fast", "commentary", "gpu", "llamacpp", "c" * 64,
                       "b" * 64, 320, 1400),
    ))


def _aggregate(c, alias, *, correct=30, p95=410):
    return VerifiedRouteTrialSummary(
        alias, c.profile_for(alias), "commentary", "game_recording", SUITE,
        30, correct, p95, 2800, NOW - 100, True,
        eval_cohort_sha256=COHORT,
    )


def _pair(c, *, baseline=None, candidate=None, critical=None):
    baseline = baseline if baseline is not None else (True,) * 30
    candidate = candidate if candidate is not None else (True,) * 30
    critical = critical if critical is not None else (False,) * 30
    return VerifiedPairedRouteCases(
        "base", "fast", c.profile_for("base"), c.profile_for("fast"),
        "commentary", "game_recording", SUITE, baseline, candidate, critical,
        NOW - 100, True, eval_cohort_sha256=COHORT,
    )


def _advise(c, rows, *pairs):
    s = QualityGatedRouteSelector(catalog=c, summaries=rows, paired_cases=tuple(pairs))
    return s.advise(
        owner_approved=True, baseline_alias="base", task_kind="commentary",
        workload="game_recording", suite_sha256=SUITE,
        now_unix_s=NOW, max_p95_ms=900, max_total_gpu_mib=6656,
    )


def test_aggregate_speed_gain_cannot_promote_without_paired_case_proof():
    c = _catalog()
    baseline = _aggregate(c, "base")
    fast = _aggregate(c, "fast", p95=110)
    advice = _advise(c, (baseline, fast))
    assert advice.route_alias == "base"
    assert advice.reason == "verified_baseline_only"


def test_identical_verified_successes_with_matched_pair_can_promote():
    c = _catalog()
    advice = _advise(c, (_aggregate(c, "base"), _aggregate(c, "fast", p95=95)),
                     _pair(c))
    assert advice.route_alias == "fast"
    assert not advice.authorizes_model_launch


def test_aggregate_tie_can_hide_regressions_on_known_game_tasks():
    c = _catalog()
    # Both candidates score 29/30. The faster one fails a task that the
    # current deployed baseline passed, while recovering a different task.
    base = (True,) * 29 + (False,)
    fast = (False,) + (True,) * 29
    assert sum(base) == sum(fast) == 29
    advice = _advise(
        c, (_aggregate(c, "base", correct=29),
            _aggregate(c, "fast", correct=29, p95=60)),
        _pair(c, baseline=base, candidate=fast),
    )
    assert advice.route_alias == "base"


def test_critical_task_failure_blocks_promotion_even_if_baseline_also_fails():
    c = _catalog()
    base = (False,) + (True,) * 29
    fast = base
    critical = (True,) + (False,) * 29
    advice = _advise(
        c, (_aggregate(c, "base", correct=29),
            _aggregate(c, "fast", correct=29, p95=60)),
        _pair(c, baseline=base, candidate=fast, critical=critical),
    )
    assert advice.route_alias == "base"


@pytest.mark.parametrize("changes", [
    {"host_verified": False},
    {"measured_unix_s": NOW + 10},
    {"measured_unix_s": NOW - 9 * 86400},
    {"candidate_profile": "route-" + "0" * 32},
    {"candidate_outcomes": (False,) + (True,) * 29},
    {"baseline_outcomes": (False,) + (True,) * 29},
    {"suite_sha256": "4" * 64},
    {"workload": "offline"},
])
def test_nonmatching_or_untrusted_paired_receipts_cannot_promote(changes):
    c = _catalog()
    proof = replace(_pair(c), **changes)
    summary = (_aggregate(c, "base"), _aggregate(c, "fast", p95=80))
    # Bad profile is an invalid registration and rejected at construction.
    if "candidate_profile" in changes:
        with pytest.raises(ValueError, match="profile"):
            _advise(c, summary, proof)
    else:
        assert _advise(c, summary, proof).route_alias == "base"


def test_duplicate_or_malformed_paired_evidence_rejected():
    c = _catalog()
    proof = _pair(c)
    summary = (_aggregate(c, "base"), _aggregate(c, "fast"))
    with pytest.raises(ValueError, match="duplicate"):
        _advise(c, summary, proof, proof)
    for changes in (
        {"baseline_outcomes": (1,) + (True,) * 29},
        {"candidate_outcomes": (True,) * 31},
        {"critical_cases": (False,) * 29},
        {"host_verified": 1},
        {"measured_unix_s": 10**1000},
    ):
        with pytest.raises(ValueError):
            replace(proof, **changes)
