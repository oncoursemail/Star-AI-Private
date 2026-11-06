"""Engine-clock latency and deadline regressions for the private signed maze lab.

No game input, model inference, network traffic or OBS runs in these tests.
The test engine owns time, hazards, movement and final success assessment.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

from star.game_navigation_memory import GridPosition
from star.signed_maze_lab import (
    MazeScenario, MazeTrialScore, run_maze_benchmark, run_signed_maze_trial,
)


def corridor() -> MazeScenario:
    return MazeScenario("latency_corridor", ("#####", "#S.G#", "#####"))


def patrolling_corridor() -> MazeScenario:
    return MazeScenario(
        "latency_patrol",
        ("########", "#S...G.#", "#......#", "#......#", "########"),
        patrol=(
            GridPosition(2, 1), GridPosition(3, 1),
            GridPosition(4, 1), GridPosition(4, 2),
            GridPosition(3, 2), GridPosition(2, 2),
        ),
    )


def test_synthetic_thinking_uses_world_ticks_without_changing_static_route() -> None:
    fast = run_signed_maze_trial(corridor(), owner_approved=True)
    slow = run_signed_maze_trial(
        corridor(), owner_approved=True, decision_delay_ticks=3,
    )
    assert fast.success and slow.success
    assert fast.frames == slow.frames == 3
    assert fast.moves == slow.moves == 2
    assert fast.world_ticks == 3
    assert slow.world_ticks == 12  # 3 captures + 3 simulated ticks between each
    assert slow.decision_delay_ticks == 3
    assert slow.invalid_move_attempts == fast.invalid_move_attempts == 0
    assert slow.late_actions_suppressed == 0


def test_host_advances_patrol_during_model_thinking_and_scores_collision() -> None:
    case = patrolling_corridor()
    immediate = run_signed_maze_trial(
        case, owner_approved=True, max_frames=45, sensor_radius=1,
    )
    delayed = run_signed_maze_trial(
        case, owner_approved=True, max_frames=45, sensor_radius=1,
        decision_delay_ticks=1,
    )
    assert immediate.success and immediate.moving_hazard_hits == 0
    assert not delayed.success
    assert delayed.reason == "moving_hazard_hit_during_decision"
    assert delayed.moving_hazard_delay_hits == delayed.moving_hazard_hits == 1
    assert delayed.world_ticks == 6
    assert delayed.invalid_move_attempts == 0
    assert delayed.efficiency_bps == 0  # No credit from prior motion.
    assert not delayed.source_revoked


def test_stale_move_can_be_rejected_by_independent_engine_at_commit() -> None:
    score = run_signed_maze_trial(
        patrolling_corridor(), owner_approved=True, max_frames=45,
        sensor_radius=1, decision_delay_ticks=2,
    )
    assert not score.success
    assert score.reason == "engine_rejected_moving_hazard"
    assert score.invalid_move_attempts == 1
    assert score.moving_hazard_hits == score.moving_hazard_delay_hits == 0


def test_owner_opt_in_action_deadline_suppresses_delayed_advice() -> None:
    suppressed = run_signed_maze_trial(
        corridor(), owner_approved=True, max_frames=9,
        decision_delay_ticks=1, action_deadline_ticks=0,
    )
    permitted = run_signed_maze_trial(
        corridor(), owner_approved=True, max_frames=9,
        decision_delay_ticks=1, action_deadline_ticks=1,
    )
    assert not suppressed.success
    assert suppressed.reason == "frame_budget_exhausted"
    assert suppressed.moves == 0
    assert suppressed.late_actions_suppressed > 0
    assert suppressed.invalid_move_attempts == 0
    assert suppressed.world_ticks == 9
    assert permitted.success and permitted.moves == 2
    assert permitted.late_actions_suppressed == 0
    assert permitted.world_ticks == 6


def test_delay_cannot_borrow_world_ticks_beyond_trial_budget() -> None:
    score = run_signed_maze_trial(
        corridor(), owner_approved=True, max_frames=10, decision_delay_ticks=24,
    )
    assert not score.success and score.reason == "frame_budget_exhausted"
    assert score.moves == 0 and score.frames == 1
    assert score.world_ticks == 10


def test_benchmark_preserves_per_scenario_latency_losses() -> None:
    cases = (corridor(), patrolling_corridor())
    results = run_maze_benchmark(
        cases, owner_approved=True, max_frames=45,
        sensor_radius=1, decision_delay_ticks=1,
    )
    assert results[0].success
    assert not results[1].success
    assert results[1].moving_hazard_delay_hits == 1
    assert all(r.decision_delay_ticks == 1 for r in results)


@pytest.mark.parametrize("delay", (True, 1.0, -1, 25, "1", None))
def test_invalid_delay_is_rejected_before_private_execution(delay: object) -> None:
    with pytest.raises(ValueError, match="decision delay"):
        run_signed_maze_trial(
            corridor(), owner_approved=True,
            decision_delay_ticks=delay,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("deadline", (True, -1, 25, 1.0, "1"))
def test_invalid_deadline_is_rejected_before_private_execution(deadline: object) -> None:
    with pytest.raises(ValueError, match="action deadline"):
        run_signed_maze_trial(
            corridor(), owner_approved=True,
            action_deadline_ticks=deadline,  # type: ignore[arg-type]
        )


def test_scored_real_time_claims_cannot_be_modified_independently() -> None:
    score = run_signed_maze_trial(
        patrolling_corridor(), owner_approved=True,
        decision_delay_ticks=1, sensor_radius=1,
    )
    fields = asdict(score)
    for corrupt in (
        {"world_ticks": 0},
        {"world_ticks": True},
        {"decision_delay_ticks": True},
        {"decision_delay_ticks": -1},
        {"late_actions_suppressed": score.frames + 1},
        {"moving_hazard_delay_hits": 2},
        {"moving_hazard_delay_hits": True},
    ):
        with pytest.raises(ValueError, match="telemetry"):
            MazeTrialScore(**{**fields, **corrupt})


def test_owner_gate_and_disabled_default_are_unchanged() -> None:
    with pytest.raises(PermissionError):
        run_signed_maze_trial(corridor(), decision_delay_ticks=1)
    baseline = run_signed_maze_trial(corridor(), owner_approved=True)
    explicit = run_signed_maze_trial(
        corridor(), owner_approved=True,
        decision_delay_ticks=0, action_deadline_ticks=None,
    )
    assert baseline == explicit
