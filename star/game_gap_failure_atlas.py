"""Offline, scenario-stratified follow-up for real-time game performance gaps.

Only accepts the already validated, matched holdout protocol and results from
`game_realtime_gap_audit`. All grouping is descriptive: this is NOT a causal
estimator, a skill-promotion gate, a training loop, or a controller.

Scenario names and seeds are intentionally not included in the returned atlas.
The trusted test host keeps the opaque-index-to-scenario mapping. Do not feed
held-out case identities or per-case failures to a learning model.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Sequence

from .game_realtime_gap_audit import (
    GameModeGapPair,
    GameModeGapProtocol,
    audit_realtime_gap,
)


@dataclass(frozen=True)
class ScenarioGapSlice:
    """A bounded, anonymous scenario summary; not a per-case scorecard."""

    scenario_slot: int
    cases: int
    paused_wins: int
    realtime_wins: int
    paused_only_wins: int
    realtime_only_wins: int
    realtime_deadline_misses: int
    deadline_misses_on_paused_only_losses: int
    paused_mean_progress: float
    realtime_mean_progress: float
    realtime_p95_action_delay_ms: float

    @property
    def directional_loss(self) -> int:
        return self.paused_only_wins - self.realtime_only_wins


@dataclass(frozen=True)
class GameGapFailureAtlas:
    """Owner-review-only evidence; never authorizes training or play."""

    gap_status: str
    scenarios: tuple[ScenarioGapSlice, ...]
    distribution: str
    followup: str
    paired_cases: int
    paused_only_losses: int
    late_paused_only_losses: int
    protocol_sha256: str
    authorizes_training: bool = False
    authorizes_gameplay: bool = False
    authorizes_streaming: bool = False
    authorizes_model_promotion: bool = False
    establishes_cause: bool = False
    note: str = (
        "Anonymous exploratory stratification of a single preregistered holdout. "
        "Do not use scenario-level results for model selection, training, "
        "hyperparameter tuning or repeated-peeking significance claims. "
        "Clock deadlines correlate with, but do not establish causes of, failures."
    )


def _p95(values: list[float]) -> float:
    return sorted(values)[ceil(0.95 * len(values)) - 1]


def audit_game_gap_failure_atlas(
    protocol: GameModeGapProtocol,
    pairs: Sequence[GameModeGapPair],
) -> GameGapFailureAtlas:
    """Choose a *diagnostic* next experiment, without ever prescribing an action.

    The parent audit enforces 20..256 exactly matched unseen cases, >=2
    scenarios, finite timing and host-declared independent observations.
    Grouping preserves preregistered scenario order, including fully failed
    maps; no favorable maps or cases can be excluded. Scenario IDs and seeds
    are not returned. The output cannot authorize live activity.
    """
    # Work from one immutable copy for both audits. A host may append to or
    # replace elements of the caller-owned list after the parent returns.
    # Keep the parent validator strict about input collection types.
    if type(pairs) not in (list, tuple):
        raise ValueError("a bounded list or tuple of matched pairs is required")
    snapshot = tuple(pairs)
    gap = audit_realtime_gap(protocol, snapshot)
    # The preceding validator checks all identities, input types and counts.
    # Keep ordering fixed by the host's frozen protocol, not by outcome order.
    names = tuple(dict.fromkeys(name for name, _seed in protocol.cases))
    by_name: dict[str, list[GameModeGapPair]] = {name: [] for name in names}
    for pair in snapshot:
        by_name[pair.paused.scenario_id].append(pair)

    slices: list[ScenarioGapSlice] = []
    for slot, name in enumerate(names):
        rows = by_name[name]
        count = len(rows)
        paused_only = sum(p.paused.success and not p.realtime.success for p in rows)
        realtime_only = sum(p.realtime.success and not p.paused.success for p in rows)
        late_paused_only = sum(
            p.paused.success and not p.realtime.success and p.realtime.action_delay_ms > p.realtime_scene_deadline_ms
            for p in rows
        )
        slices.append(
            ScenarioGapSlice(
                scenario_slot=slot,
                cases=count,
                paused_wins=sum(p.paused.success for p in rows),
                realtime_wins=sum(p.realtime.success for p in rows),
                paused_only_wins=paused_only,
                realtime_only_wins=realtime_only,
                realtime_deadline_misses=sum(p.realtime.action_delay_ms > p.realtime_scene_deadline_ms for p in rows),
                deadline_misses_on_paused_only_losses=late_paused_only,
                paused_mean_progress=round(sum(p.paused.progress for p in rows) / count, 4),
                realtime_mean_progress=round(sum(p.realtime.progress for p in rows) / count, 4),
                realtime_p95_action_delay_ms=round(_p95([p.realtime.action_delay_ms for p in rows]), 3),
            )
        )

    positive = sum(item.directional_loss > 0 for item in slices)
    negative = sum(item.directional_loss < 0 for item in slices)
    if positive and negative:
        distribution = "opposing_scenario_directions"
    elif negative == len(slices):
        distribution = "realtime_advantage_in_all_scenarios"
    elif negative:
        distribution = "realtime_advantage_in_some_scenarios"
    elif positive == len(slices):
        distribution = "deficit_in_all_scenarios"
    elif positive >= 2:
        distribution = "deficit_in_multiple_scenarios"
    elif positive == 1:
        distribution = "deficit_in_single_scenario"
    else:
        distribution = "no_positive_scenario_deficit"

    # A high pooled significance can conceal map-specific failures. A
    # predeclared host should reproduce heterogeneous cases on NEW practice
    # seeds before trying to optimize a global low-latency policy.
    if gap.status == "both_modes_struggle":
        followup = "grounding_and_strategy_practice_probe"
    elif gap.status == "realtime_gap_detected":
        if distribution in ("opposing_scenario_directions", "deficit_in_single_scenario"):
            followup = "scenario_heterogeneity_reproduction_probe"
        elif (
            gap.paused_only_successes >= 3
            and gap.deadline_misses_in_paused_only_losses * 2 >= gap.paused_only_successes
        ):
            followup = "capture_to_engine_ack_timing_probe"
        else:
            followup = "moving_world_perception_policy_probe"
    else:
        followup = "fresh_preregistered_holdout_probe"

    return GameGapFailureAtlas(
        gap_status=gap.status,
        scenarios=tuple(slices),
        distribution=distribution,
        followup=followup,
        paired_cases=gap.pairs,
        paused_only_losses=gap.paused_only_successes,
        late_paused_only_losses=gap.deadline_misses_in_paused_only_losses,
        protocol_sha256=gap.protocol_sha256,
    )


__all__ = [
    "ScenarioGapSlice",
    "GameGapFailureAtlas",
    "audit_game_gap_failure_atlas",
]
