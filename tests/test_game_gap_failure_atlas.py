"""Scenario-stratified game gap diagnosis; no gameplay or learning side effects."""

from dataclasses import replace
import json
import math

import pytest

from star.game_gap_failure_atlas import audit_game_gap_failure_atlas
from star.game_realtime_gap_audit import GameModeGapPair, GameModeGapProtocol
from star.game_skill_gate import GamePerformanceTrial


def evidence(
    *,
    paused_wins: set[int] | None = None,
    live_wins: set[int] | None = None,
    late: set[int] | None = None,
    order: tuple[int, ...] | None = None,
    scenarios: int = 2,
    per_scenario: int = 10,
):
    size = scenarios * per_scenario
    assert size >= 20
    paused_wins = set(range(size)) if paused_wins is None else paused_wins
    live_wins = set() if live_wins is None else live_wins
    late = set(range(size)) if late is None else late
    cases = tuple((f"secret_map_{i // per_scenario}", i + 2341) for i in range(size))
    protocol = GameModeGapProtocol(game_scope="secret_game_version", cases=cases, max_scene_deadline_ms=350)
    pairs = []
    for i in range(size):
        common = dict(
            game_scope="secret_game_version",
            scenario_id=cases[i][0],
            seed=cases[i][1],
            split="holdout",
            host_verified=True,
        )
        pair = GameModeGapPair(
            paused=GamePerformanceTrial(
                case_id=f"p-{i}",
                mode="paused",
                success=i in paused_wins,
                progress=0.9 if i in paused_wins else 0.3,
                action_delay_ms=100,
                **common,
            ),
            realtime=GamePerformanceTrial(
                case_id=f"r-{i}",
                mode="realtime",
                success=i in live_wins,
                progress=0.8 if i in live_wins else 0.2,
                action_delay_ms=500 if i in late else 120,
                **common,
            ),
            matching_start_verified=True,
            independent_outcome_verified=True,
            realtime_scene_deadline_ms=300,
        )
        pairs.append(pair)
    if order is not None:
        pairs = [pairs[i] for i in order]
    return protocol, pairs


def test_broad_timing_gap_diagnosis_is_descriptive_not_permission():
    protocol, pairs = evidence(live_wins={8, 9, 17, 18, 19})
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.gap_status == "realtime_gap_detected"
    assert atlas.distribution == "deficit_in_all_scenarios"
    assert atlas.followup == "capture_to_engine_ack_timing_probe"
    assert atlas.paired_cases == 20
    assert atlas.paused_only_losses == atlas.late_paused_only_losses == 15
    assert [s.cases for s in atlas.scenarios] == [10, 10]
    assert [s.paused_only_wins for s in atlas.scenarios] == [8, 7]
    assert [s.realtime_wins for s in atlas.scenarios] == [2, 3]
    assert atlas.protocol_sha256 == protocol.digest
    assert not any(
        (
            atlas.authorizes_training,
            atlas.authorizes_gameplay,
            atlas.authorizes_streaming,
            atlas.authorizes_model_promotion,
            atlas.establishes_cause,
        )
    )


def test_strong_pause_weak_realtime_without_deadline_misses_probes_perception():
    protocol, pairs = evidence(live_wins={8, 9, 17, 18, 19}, late=set())
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.followup == "moving_world_perception_policy_probe"
    assert atlas.late_paused_only_losses == 0
    assert all(s.realtime_deadline_misses == 0 for s in atlas.scenarios)
    assert all(s.realtime_p95_action_delay_ms == 120 for s in atlas.scenarios)


def test_concentrated_map_gap_is_not_mistaken_for_uniform_deficit():
    protocol, pairs = evidence(live_wins=set(range(10, 20)))
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.gap_status == "realtime_gap_detected"
    assert atlas.distribution == "deficit_in_single_scenario"
    assert atlas.followup == "scenario_heterogeneity_reproduction_probe"
    assert atlas.scenarios[0].directional_loss == 10
    assert atlas.scenarios[1].directional_loss == 0


def test_opposite_map_directions_not_hidden_by_pooled_sign_test():
    # 16 paused-only failures versus 4 live-only wins across 24 cases.
    # The global exact sign test detects the gap; one map moves oppositely.
    pause = set(range(16))
    live = set(range(16, 20))
    protocol, pairs = evidence(paused_wins=pause, live_wins=live, scenarios=3, per_scenario=8)
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.gap_status == "realtime_gap_detected"
    assert atlas.distribution == "opposing_scenario_directions"
    assert atlas.followup == "scenario_heterogeneity_reproduction_probe"
    assert [s.directional_loss for s in atlas.scenarios] == [8, 8, -4]


def test_two_of_three_scenarios_bad_not_all_scenarios():
    protocol, pairs = evidence(live_wins=set(range(16, 24)), scenarios=3, per_scenario=8)
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.distribution == "deficit_in_multiple_scenarios"


def test_all_weak_modes_require_strategy_not_bigger_faster_hardware():
    protocol, pairs = evidence(paused_wins=set(), live_wins=set(), late=set())
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.gap_status == "both_modes_struggle"
    assert atlas.distribution == "no_positive_scenario_deficit"
    assert atlas.followup == "grounding_and_strategy_practice_probe"


def test_similar_modes_call_for_new_holdout_not_model_promotion():
    wins = set(range(0, 20, 2))
    protocol, pairs = evidence(paused_wins=wins, live_wins=wins)
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.gap_status == "no_large_gap_detected"
    assert atlas.followup == "fresh_preregistered_holdout_probe"


def test_scenario_tokens_ordered_by_frozen_protocol_not_input():
    protocol, pairs = evidence(
        live_wins=set(range(16, 24)),
        scenarios=3,
        per_scenario=8,
        order=tuple(range(23, -1, -1)),
    )
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert [s.scenario_slot for s in atlas.scenarios] == [0, 1, 2]
    assert [s.realtime_wins for s in atlas.scenarios] == [0, 0, 8]
    assert atlas.scenarios[0].paused_mean_progress == 0.9


def test_holdout_names_seeds_and_case_ids_not_present_in_return_value():
    protocol, pairs = evidence(live_wins=set(range(10, 20)))
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    value = repr(atlas)
    assert "secret_map_" not in value
    assert "secret_game_version" not in value
    assert "2341" not in value
    assert "p-0" not in value
    assert "r-0" not in value
    assert "not cryptographic" not in value.lower()  # note explains weaker claims distinctly


def test_changed_scope_or_duplicate_pair_rejected_by_parent_audit():
    protocol, pairs = evidence()
    with pytest.raises(ValueError):
        audit_game_gap_failure_atlas(protocol, pairs[:-1] + [pairs[0]])
    with pytest.raises(ValueError):
        audit_game_gap_failure_atlas(
            protocol,
            [
                replace(pairs[0], paused=replace(pairs[0].paused, game_scope="other")),
                *pairs[1:],
            ],
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda pair: replace(pair, matching_start_verified=False),
        lambda pair: replace(pair, realtime=replace(pair.realtime, split="practice")),
        lambda pair: replace(pair, realtime=replace(pair.realtime, action_delay_ms=math.inf)),
        lambda pair: replace(pair, realtime_scene_deadline_ms=500),
    ],
)
def test_invalid_attestations_and_timings_cannot_produce_recommendation(mutator):
    protocol, pairs = evidence()
    with pytest.raises((TypeError, ValueError)):
        rows = [mutator(pairs[0]), *pairs[1:]]
        audit_game_gap_failure_atlas(protocol, rows)


def test_out_of_scope_payload_rejected_and_no_streaming_side_effects():
    protocol, pairs = evidence()
    with pytest.raises(ValueError):
        audit_game_gap_failure_atlas(protocol, "malicious")  # type: ignore[arg-type]
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert "authorizes_gameplay=False" in str(atlas)
    assert "do not use scenario-level results for model selection" in atlas.note.lower()


def test_report_aggregates_finite_and_json_safe():
    protocol, pairs = evidence(live_wins={2, 12}, late={0, 1, 10})
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    from dataclasses import asdict

    payload = json.dumps(asdict(atlas), allow_nan=False)
    assert "Infinity" not in payload
    assert atlas.scenarios[0].realtime_p95_action_delay_ms == 500
    assert atlas.scenarios[1].realtime_p95_action_delay_ms == 500
    assert atlas.late_paused_only_losses == 3


def test_list_mutation_after_parent_validation_cannot_change_atlas(monkeypatch):
    from star import game_gap_failure_atlas as module

    protocol, pairs = evidence(live_wins={8, 9, 17, 18, 19})
    real_validator = module.audit_realtime_gap

    def adversarial_after_validation(p, rows):
        outcome = real_validator(p, rows)
        # Simulate a host producer overwriting its shared mutable list after
        # the earlier audit completes and before the scenario grouping starts.
        pairs[0] = pairs[10]
        return outcome

    monkeypatch.setattr(module, "audit_realtime_gap", adversarial_after_validation)
    atlas = module.audit_game_gap_failure_atlas(protocol, pairs)
    assert atlas.gap_status == "realtime_gap_detected"
    assert [s.paused_only_wins for s in atlas.scenarios] == [8, 7]


def test_bounded_uneven_scenarios_and_no_missing_groups():
    protocol, pairs = evidence(live_wins={0, 1, 2, 3}, scenarios=5, per_scenario=4)
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert len(atlas.scenarios) == 5
    assert sum(s.cases for s in atlas.scenarios) == 20
    assert sum(s.paused_wins for s in atlas.scenarios) == 20
    assert sum(s.realtime_wins for s in atlas.scenarios) == 4


def test_scenario_progress_is_local_not_pooled():
    protocol, pairs = evidence(live_wins=set(range(10)))
    atlas = audit_game_gap_failure_atlas(protocol, pairs)
    assert [s.realtime_mean_progress for s in atlas.scenarios] == [0.8, 0.2]
    assert [s.paused_mean_progress for s in atlas.scenarios] == [0.9, 0.9]
