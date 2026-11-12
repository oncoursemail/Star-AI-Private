"""Tests for STAR's synthetic cluster-bootstrap coverage benchmark."""
import pytest

from benchmarks.stream_cluster_coverage import (
    CoverageScenario,
    default_scenarios,
    simulate_coverage,
)


def test_default_scenarios_cover_small_large_equal_and_unequal_groups():
    scenarios = default_scenarios()
    assert len(scenarios) == 4
    assert {item.size_pattern for item in scenarios} == {"equal", "unequal"}
    assert {item.cluster_count for item in scenarios} == {20, 50}


def test_simulation_is_deterministic_for_a_fixed_seed():
    scenario = CoverageScenario("test_equal", 8, 0.05, 0.20, "equal")
    kwargs = {
        "simulation_replicates": 20,
        "bootstrap_replicates": 200,
        "random_seed": 7,
    }
    assert simulate_coverage(scenario, **kwargs) == simulate_coverage(scenario, **kwargs)


def test_simulation_reports_separate_bootstrap_and_hoeffding_coverage():
    scenario = CoverageScenario("test_unequal", 10, 0.05, 0.50, "unequal")
    result = simulate_coverage(
        scenario,
        simulation_replicates=20,
        bootstrap_replicates=200,
        random_seed=8,
    )
    assert 0.0 <= result.bootstrap_upper_coverage <= 1.0
    assert 0.0 <= result.weighted_hoeffding_coverage <= 1.0
    assert 0.0 <= result.session_incidence_hoeffding_coverage <= 1.0
    assert result.weighted_hoeffding_coverage_ci_low <= result.weighted_hoeffding_coverage
    assert result.weighted_hoeffding_coverage <= result.weighted_hoeffding_coverage_ci_high
    assert result.true_session_incidence > result.mean_event_rate


@pytest.mark.parametrize(
    "kwargs",
    [
        {"simulation_replicates": 19},
        {"simulation_replicates": 5001},
        {"bootstrap_replicates": 199},
        {"bootstrap_replicates": 5001},
        {"confidence_level": 1.0},
        {"random_seed": -1},
    ],
)
def test_invalid_simulation_settings_are_rejected(kwargs):
    scenario = CoverageScenario("invalid_test", 8, 0.05, 0.20, "equal")
    options = {
        "simulation_replicates": 20,
        "bootstrap_replicates": 200,
    }
    options.update(kwargs)
    with pytest.raises(ValueError):
        simulate_coverage(scenario, **options)


def test_excessive_resample_budget_is_rejected_before_work_starts():
    scenario = CoverageScenario("too_large", 500, 0.05, 0.20, "equal")
    with pytest.raises(ValueError, match="50,000,000"):
        simulate_coverage(
            scenario,
            simulation_replicates=5000,
            bootstrap_replicates=5000,
        )


def test_invalid_scenario_is_rejected():
    with pytest.raises(ValueError):
        simulate_coverage(
            CoverageScenario("bad name", 8, 0.05, 0.20, "equal"),
            simulation_replicates=20,
            bootstrap_replicates=200,
        )
