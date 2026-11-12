"""Monte Carlo coverage study for STAR's session-clustered turn evaluator.

Run from the repository root:
    python -m benchmarks.stream_cluster_coverage --replicates 1000 --bootstrap-replicates 500

The study is synthetic and does not read private audio, transcripts, viewer data,
or live STAR measurements.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
import random
from statistics import NormalDist
from typing import Literal

from star.stream_turntaking_cluster import (
    hoeffding_upper_bound,
    weighted_hoeffding_upper_bound,
)

SizePattern = Literal["equal", "unequal"]
_MAX_TOTAL_RESAMPLE_DRAWS = 50_000_000
_MAX_CLUSTERS = 500
_MAX_SIMULATIONS = 5_000
_MAX_BOOTSTRAPS = 5_000


@dataclass(frozen=True)
class CoverageScenario:
    name: str
    cluster_count: int
    mean_event_rate: float
    intracluster_correlation: float
    size_pattern: SizePattern


@dataclass(frozen=True)
class CoverageResult:
    scenario: str
    cluster_count: int
    size_pattern: str
    min_cluster_size: int
    max_cluster_size: int
    mean_cluster_size: float
    mean_event_rate: float
    intracluster_correlation: float
    true_session_incidence: float
    simulation_replicates: int
    bootstrap_replicates: int
    nominal_confidence: float
    bootstrap_upper_coverage: float
    bootstrap_coverage_ci_low: float
    bootstrap_coverage_ci_high: float
    weighted_hoeffding_coverage: float
    weighted_hoeffding_coverage_ci_low: float
    weighted_hoeffding_coverage_ci_high: float
    session_incidence_hoeffding_coverage: float
    session_incidence_coverage_ci_low: float
    session_incidence_coverage_ci_high: float
    mean_bootstrap_upper_margin: float


def _validate_fraction(value: float, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in {low}..{high}")
    numeric = float(value)
    if not math.isfinite(numeric) or not low <= numeric <= high:
        raise ValueError(f"{name} must be a finite number in {low}..{high}")
    return numeric


def _validate_scenario(scenario: CoverageScenario) -> None:
    if not isinstance(scenario, CoverageScenario):
        raise TypeError("scenario must be CoverageScenario")
    if (
        type(scenario.name) is not str
        or not scenario.name
        or len(scenario.name) > 80
        or not all(char.isalnum() or char in "_-" for char in scenario.name)
    ):
        raise ValueError("scenario name must be a bounded identifier")
    if (
        type(scenario.cluster_count) is not int
        or not 5 <= scenario.cluster_count <= _MAX_CLUSTERS
    ):
        raise ValueError("cluster_count must be in 5..500")
    _validate_fraction(scenario.mean_event_rate, "mean_event_rate", 0.001, 0.5)
    _validate_fraction(
        scenario.intracluster_correlation,
        "intracluster_correlation",
        0.0,
        0.95,
    )
    if scenario.size_pattern not in ("equal", "unequal"):
        raise ValueError("size_pattern must be equal or unequal")


def _cluster_sizes(scenario: CoverageScenario) -> tuple[int, ...]:
    if scenario.size_pattern == "equal":
        return (10,) * scenario.cluster_count
    pattern = (2, 4, 8, 16, 32)
    return tuple(pattern[index % len(pattern)] for index in range(scenario.cluster_count))


def _beta_one_minus_moment(alpha: float, beta: float, power: int) -> float:
    """E[(1-P)^power] for P ~ Beta(alpha, beta)."""
    log_value = (
        math.lgamma(beta + power)
        + math.lgamma(alpha + beta)
        - math.lgamma(alpha + beta + power)
        - math.lgamma(beta)
    )
    return math.exp(log_value)


def _true_session_incidence(
    sizes: tuple[int, ...],
    mean_rate: float,
    intracluster_correlation: float,
) -> float:
    if intracluster_correlation == 0.0:
        probabilities = [1.0 - (1.0 - mean_rate) ** size for size in sizes]
    else:
        concentration = 1.0 / intracluster_correlation - 1.0
        alpha = mean_rate * concentration
        beta = (1.0 - mean_rate) * concentration
        probabilities = [
            1.0 - _beta_one_minus_moment(alpha, beta, size)
            for size in sizes
        ]
    return sum(probabilities) / len(probabilities)


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(probability * len(ordered))) - 1]


def _wilson_coverage_interval(successes: int, trials: int) -> tuple[float, float]:
    """Two-sided 95% Monte Carlo interval for an estimated coverage proportion."""
    z = NormalDist().inv_cdf(0.975)
    rate = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = rate + z_squared / (2.0 * trials)
    spread = z * math.sqrt(
        rate * (1.0 - rate) / trials
        + z_squared / (4.0 * trials * trials)
    )
    return (
        max(0.0, (center - spread) / denominator),
        min(1.0, (center + spread) / denominator),
    )


def simulate_coverage(
    scenario: CoverageScenario,
    *,
    simulation_replicates: int = 200,
    bootstrap_replicates: int = 300,
    confidence_level: float = 0.95,
    random_seed: int = 20261112,
) -> CoverageResult:
    """Compare percentile cluster bootstrap with weighted Hoeffding coverage."""
    _validate_scenario(scenario)
    if (
        type(simulation_replicates) is not int
        or not 20 <= simulation_replicates <= _MAX_SIMULATIONS
    ):
        raise ValueError("simulation_replicates must be in 20..5000")
    if (
        type(bootstrap_replicates) is not int
        or not 200 <= bootstrap_replicates <= _MAX_BOOTSTRAPS
    ):
        raise ValueError("bootstrap_replicates must be in 200..5000")
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not math.isfinite(float(confidence_level))
        or not 0.8 <= float(confidence_level) <= 0.99
    ):
        raise ValueError("confidence_level must be between 0.8 and 0.99")
    if type(random_seed) is not int or not 0 <= random_seed <= 4_294_967_295:
        raise ValueError("random_seed must be in 0..4294967295")
    if simulation_replicates * bootstrap_replicates * scenario.cluster_count > _MAX_TOTAL_RESAMPLE_DRAWS:
        raise ValueError("requested simulation exceeds the 50,000,000 resample-draw budget")

    confidence = float(confidence_level)
    mean_rate = float(scenario.mean_event_rate)
    icc = float(scenario.intracluster_correlation)
    sizes = _cluster_sizes(scenario)
    true_incidence = _true_session_incidence(sizes, mean_rate, icc)
    rng = random.Random(random_seed)

    if icc == 0.0:
        alpha = beta = None
    else:
        concentration = 1.0 / icc - 1.0
        alpha = mean_rate * concentration
        beta = (1.0 - mean_rate) * concentration

    bootstrap_covered = 0
    hoeffding_covered = 0
    incidence_covered = 0
    bootstrap_margins: list[float] = []

    for _ in range(simulation_replicates):
        successes_by_group: list[int] = []
        session_events: list[int] = []
        for size in sizes:
            group_rate = (
                mean_rate
                if icc == 0.0
                else rng.betavariate(alpha, beta)  # type: ignore[arg-type]
            )
            successes = sum(rng.random() < group_rate for _ in range(size))
            successes_by_group.append(successes)
            session_events.append(int(successes > 0))

        observed_rate = sum(successes_by_group) / sum(sizes)
        bootstrap_rates: list[float] = []
        cluster_count = len(sizes)
        for _ in range(bootstrap_replicates):
            sampled_indices = [
                rng.randrange(cluster_count) for _ in range(cluster_count)
            ]
            sampled_successes = sum(successes_by_group[index] for index in sampled_indices)
            sampled_opportunities = sum(sizes[index] for index in sampled_indices)
            bootstrap_rates.append(sampled_successes / sampled_opportunities)

        bootstrap_upper = _nearest_rank(bootstrap_rates, confidence)
        bootstrap_covered += int(bootstrap_upper >= mean_rate)
        bootstrap_margins.append(bootstrap_upper - observed_rate)

        hoeffding_upper, _ = weighted_hoeffding_upper_bound(
            successes_by_group,
            sizes,
            confidence,
        )
        hoeffding_covered += int(hoeffding_upper >= mean_rate)

        incidence_upper = hoeffding_upper_bound(
            sum(session_events),
            cluster_count,
            confidence,
        )
        incidence_covered += int(incidence_upper >= true_incidence)

    bootstrap_ci = _wilson_coverage_interval(bootstrap_covered, simulation_replicates)
    hoeffding_ci = _wilson_coverage_interval(hoeffding_covered, simulation_replicates)
    incidence_ci = _wilson_coverage_interval(incidence_covered, simulation_replicates)

    return CoverageResult(
        scenario=scenario.name,
        cluster_count=scenario.cluster_count,
        size_pattern=scenario.size_pattern,
        min_cluster_size=min(sizes),
        max_cluster_size=max(sizes),
        mean_cluster_size=sum(sizes) / len(sizes),
        mean_event_rate=mean_rate,
        intracluster_correlation=icc,
        true_session_incidence=true_incidence,
        simulation_replicates=simulation_replicates,
        bootstrap_replicates=bootstrap_replicates,
        nominal_confidence=confidence,
        bootstrap_upper_coverage=bootstrap_covered / simulation_replicates,
        bootstrap_coverage_ci_low=bootstrap_ci[0],
        bootstrap_coverage_ci_high=bootstrap_ci[1],
        weighted_hoeffding_coverage=hoeffding_covered / simulation_replicates,
        weighted_hoeffding_coverage_ci_low=hoeffding_ci[0],
        weighted_hoeffding_coverage_ci_high=hoeffding_ci[1],
        session_incidence_hoeffding_coverage=incidence_covered / simulation_replicates,
        session_incidence_coverage_ci_low=incidence_ci[0],
        session_incidence_coverage_ci_high=incidence_ci[1],
        mean_bootstrap_upper_margin=sum(bootstrap_margins) / len(bootstrap_margins),
    )


def default_scenarios() -> tuple[CoverageScenario, ...]:
    return (
        CoverageScenario("small_equal_moderate_icc", 20, 0.05, 0.20, "equal"),
        CoverageScenario("small_unequal_high_icc", 20, 0.05, 0.50, "unequal"),
        CoverageScenario("medium_equal_moderate_icc", 50, 0.05, 0.20, "equal"),
        CoverageScenario("medium_unequal_high_icc", 50, 0.05, 0.50, "unequal"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replicates", type=int, default=200)
    parser.add_argument("--bootstrap-replicates", type=int, default=300)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--scenario", default="all")
    args = parser.parse_args()

    scenarios = default_scenarios()
    if args.scenario != "all":
        scenarios = tuple(item for item in scenarios if item.name == args.scenario)
        if not scenarios:
            parser.error("unknown scenario name")

    results = [
        simulate_coverage(
            scenario,
            simulation_replicates=args.replicates,
            bootstrap_replicates=args.bootstrap_replicates,
            confidence_level=args.confidence,
            random_seed=args.seed + index,
        )
        for index, scenario in enumerate(scenarios)
    ]
    print(
        json.dumps(
            {
                "method": "beta-binomial session-cluster Monte Carlo",
                "synthetic_only": True,
                "results": [asdict(result) for result in results],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
