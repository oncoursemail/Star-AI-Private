"""Offline quality-gated host route selection; no GPU, games, models or audio."""
from dataclasses import replace

import pytest

from star.stream_host_model_catalog import HostInferenceCatalog, HostModelRoute
from star.stream_quality_route_selector import (
    QualityGatedRouteSelector,
    VerifiedPairedRouteCases,
    VerifiedRouteTrialSummary,
)

SUITE = "1" * 64
OTHER = "2" * 64
NOW = 1_800_000_000


def host_route(alias, *, kind="commentary", device="cpu", vram=0, model="a"):
    return HostModelRoute(
        alias, kind, device, "llamacpp", model * 64, "b" * 64,
        320, vram,
    )


def catalog():
    return HostInferenceCatalog((
        host_route("baseline", model="a"),
        host_route("fast", model="c", device="gpu", vram=1500),
        host_route("slower", model="d", device="gpu", vram=2500),
    ))


def trial(c, alias, *, p95=250.0, correct=30, n=30,
          peak=3900.0, at=NOW - 100, **kwargs):
    return VerifiedRouteTrialSummary(
        alias, c.profile_for(alias), "commentary", "game_recording",
        SUITE, n, correct, p95, peak, at, True, **kwargs,
    )


def selector(*rows, c=None, **kwargs):
    c = c or catalog()
    return QualityGatedRouteSelector(catalog=c, summaries=tuple(rows), **kwargs)


def paired(c, candidate, *, baseline="baseline"):
    return VerifiedPairedRouteCases(
        baseline, candidate, c.profile_for(baseline), c.profile_for(candidate),
        "commentary", "game_recording", SUITE,
        (True,) * 30, (True,) * 30, (False,) * 30, NOW - 100, True,
    )


def advise(s, **kwargs):
    args = dict(owner_approved=True, baseline_alias="baseline",
                task_kind="commentary", workload="game_recording",
                suite_sha256=SUITE, now_unix_s=NOW,
                max_p95_ms=600, max_total_gpu_mib=6656)
    args.update(kwargs)
    return s.advise(**args)


def test_verified_equal_quality_faster_route_recommended_not_deployed():
    c = catalog()
    s = selector(trial(c, "baseline", p95=410), trial(c, "fast", p95=155),
                 c=c, paired_cases=(paired(c, "fast"),))
    a = advise(s)
    assert a.route_alias == "fast"
    assert a.reason == "faster_verified_route_for_manual_pilot"
    assert a.baseline_p95_ms == 410
    assert a.selected_p95_ms == 155
    assert a.selected_quality_lower_95 > 0.8
    assert a.authorizes_model_launch is False
    assert a.authorizes_game_action is False
    # The original host catalog is still authoritative for any eventual worker.
    assert c.bind.__name__ == "bind"
    assert c.route_for("fast").route_profile == c.profile_for("fast")


def test_disabled_by_default_and_unmeasured_fast_route_not_selected():
    c = catalog()
    s = selector(trial(c, "baseline", p95=410), c=c)
    assert advise(s, owner_approved=False).reason == "owner_opt_in_missing"
    a = advise(s)
    assert a.reason == "verified_baseline_only"
    assert a.route_alias == "baseline"


def test_tiny_or_weak_holdout_cannot_prove_faster_intelligence():
    c = catalog()
    cases = (
        trial(c, "fast", p95=100, correct=15, n=15),
        trial(c, "fast", p95=100, correct=21),  # low Wilson bound
        trial(c, "fast", p95=100, correct=29),  # 1 additional task failure
    )
    for row in cases:
        s = selector(trial(c, "baseline", p95=410), row, c=c)
        assert advise(s).route_alias == "baseline"


def test_no_baseline_quality_no_route_ever_qualified():
    c = catalog()
    s = selector(trial(c, "baseline", p95=420, correct=22),
                 trial(c, "fast", p95=60), c=c)
    assert advise(s).reason == "baseline_quality_or_freshness_unverified"
    assert advise(s).route_alias is None


@pytest.mark.parametrize("update", [
    {"suite_sha256": OTHER},
    {"workload": "offline"},
    {"trials": 31},
    {"host_verified": False},
    {"measured_unix_s": NOW + 10},
    {"measured_unix_s": NOW - 8 * 86400},
])
def test_unmatched_or_stale_candidate_cannot_qualify(update):
    c = catalog()
    s = selector(trial(c, "baseline", p95=410),
                 replace(trial(c, "fast", p95=90), **update), c=c)
    assert advise(s).route_alias == "baseline"


def test_decline_when_both_baseline_and_candidate_exceed_safety_envelope():
    c = catalog()
    s = selector(trial(c, "baseline", p95=420, peak=7100),
                 trial(c, "fast", p95=190, peak=7100), c=c)
    a = advise(s)
    assert a.route_alias is None
    assert a.reason == "no_quality_and_resource_qualified_route"


def test_budget_and_p95_apply_to_real_measured_deployment_not_prompt_hints():
    c = catalog()
    s = selector(trial(c, "baseline", p95=410),
                 trial(c, "fast", p95=120, peak=8000),
                 trial(c, "slower", p95=200, peak=5800), c=c,
                 paired_cases=(paired(c, "fast"), paired(c, "slower")))
    assert advise(s).route_alias == "slower"
    assert advise(s, max_total_gpu_mib=3000).route_alias is None
    assert advise(s, max_p95_ms=180).route_alias is None


def test_small_latency_gain_does_not_justify_switching_workers():
    c = catalog()
    s = selector(trial(c, "baseline", p95=410),
                 trial(c, "fast", p95=392), c=c)
    assert advise(s).route_alias == "baseline"


def test_malformed_evidence_and_revision_changes_fail_before_routing():
    c = catalog()
    b = trial(c, "baseline")
    with pytest.raises(ValueError, match="duplicate"):
        selector(b, b, c=c)
    with pytest.raises(ValueError, match="match current model"):
        selector(replace(b, route_profile="route-" + "f" * 32), c=c)
    with pytest.raises(ValueError, match="not in"):
        selector(replace(b, route_alias="nonexistent"), c=c)
    with pytest.raises(ValueError, match="task kind"):
        selector(replace(b, task_kind="speech"), c=c)
    with pytest.raises(ValueError):
        selector(replace(b, p95_end_to_end_ms=float("nan")), c=c)
    with pytest.raises(ValueError):
        selector(replace(b, total_gpu_peak_mib=10**1000), c=c)
    with pytest.raises(ValueError):
        selector(replace(b, trials=True), c=c)
    with pytest.raises(ValueError):
        selector(replace(b, verified_successes=31), c=c)
    with pytest.raises(ValueError):
        selector(replace(b, host_verified=1), c=c)
    with pytest.raises(ValueError):
        selector(replace(b, suite_sha256="NOT_HASH"), c=c)


@pytest.mark.parametrize("kwargs", [
    {"max_p95_ms": float("inf")}, {"max_total_gpu_mib": 10**1000},
    {"now_unix_s": True}, {"workload": "streaming_fake"},
    {"owner_approved": 1}, {"suite_sha256": "fake"},
])
def test_untrusted_or_invalid_advisory_arguments_fail_closed(kwargs):
    c = catalog()
    s = selector(trial(c, "baseline"), c=c)
    with pytest.raises(ValueError):
        advise(s, **kwargs)


def test_strict_task_scope_and_model_identity_no_cross_transfer():
    c = catalog()
    s = selector(trial(c, "baseline"), c=c)
    assert advise(s, task_kind="speech").route_alias is None
    assert advise(s, suite_sha256=OTHER).route_alias is None
    assert advise(s, baseline_alias="unregistered").route_alias is None
    new_catalog = HostInferenceCatalog((host_route("baseline", model="e"),))
    with pytest.raises(ValueError, match="match current model"):
        selector(trial(c, "baseline"), c=new_catalog)


def test_same_scoped_faster_candidate_deterministic_tie_breaking():
    c = catalog()
    s = selector(trial(c, "baseline", p95=410),
                 trial(c, "fast", p95=180, peak=5000),
                 trial(c, "slower", p95=180, peak=4500), c=c,
                 paired_cases=(paired(c, "fast"), paired(c, "slower")))
    assert advise(s).route_alias == "slower"


def test_no_duplicate_calibration_to_cherry_pick_best_run():
    c = catalog()
    fast = trial(c, "fast", p95=100)
    with pytest.raises(ValueError, match="duplicate"):
        selector(trial(c, "baseline"), fast,
                 replace(fast, p95_end_to_end_ms=20), c=c)
