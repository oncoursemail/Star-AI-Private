"""Deterministic, bounded latency-jitter regressions for the private maze lab.

Synthetic milliseconds/world ticks do not measure live inference or actuation.
The test engine, not an agent or a prompt, owns the final score.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

from star.signed_maze_lab import MazeScenario, MazeTrialScore, run_maze_benchmark, run_signed_maze_trial


def corridor() -> MazeScenario:
    return MazeScenario("jitter_corridor", ("#####", "#S.G#", "#####"))


def test_jitter_consumes_world_time_even_when_all_steps_are_correct() -> None:
    baseline = run_signed_maze_trial(corridor(), owner_approved=True)
    jitter = run_signed_maze_trial(
        corridor(), owner_approved=True, decision_delay_schedule=(0, 3),
    )
    assert baseline.success and jitter.success
    assert baseline.moves == jitter.moves == 2
    assert baseline.world_ticks == 3
    assert jitter.world_ticks == 6
    assert jitter.decision_delay_ticks == 0  # fixed-delay parameter remains its default
    assert jitter.decision_delay_schedule_used
    assert jitter.decision_delay_total_ticks == 3
    assert jitter.decision_delay_p95_ticks == jitter.decision_delay_max_ticks == 3
    assert jitter.frames == 3


def test_jitter_deadline_is_enforced_per_capture_not_average_delay() -> None:
    jitter = run_signed_maze_trial(
        corridor(), owner_approved=True, max_frames=20,
        decision_delay_schedule=(0, 3), action_deadline_ticks=1,
    )
    assert jitter.late_actions_suppressed > 0
    assert jitter.invalid_move_attempts == 0
    assert jitter.decision_delay_max_ticks == 3
    assert jitter.decision_delay_total_ticks >= 3


def test_repeating_jitter_schedule_is_deterministic_and_independently_scored() -> None:
    settings = {"owner_approved": True, "decision_delay_schedule": (0, 1, 0, 2)}
    first = run_signed_maze_trial(corridor(), **settings)
    again = run_signed_maze_trial(corridor(), **settings)
    assert first == again
    assert first.success
    assert first.decision_delay_p95_ticks <= first.decision_delay_max_ticks
    assert first.decision_delay_total_ticks <= first.frames * first.decision_delay_max_ticks
    assert "source_key" not in asdict(first)
    assert "session_id" not in asdict(first)


def test_zero_jitter_is_behaviorally_backward_compatible() -> None:
    baseline = run_signed_maze_trial(corridor(), owner_approved=True)
    explicit = run_signed_maze_trial(
        corridor(), owner_approved=True, decision_delay_schedule=(0,),
    )
    assert baseline.success and explicit.success
    assert baseline.moves == explicit.moves
    assert baseline.world_ticks == explicit.world_ticks
    assert explicit.decision_delay_schedule_used and not baseline.decision_delay_schedule_used
    assert explicit.decision_delay_total_ticks == 0


def test_constant_delay_retains_old_telemetry_and_reports_p95() -> None:
    fixed = run_signed_maze_trial(corridor(), owner_approved=True, decision_delay_ticks=2)
    assert fixed.success
    assert fixed.decision_delay_total_ticks == fixed.frames * 2
    assert fixed.decision_delay_p95_ticks == 2
    assert fixed.decision_delay_max_ticks == 2
    assert not fixed.decision_delay_schedule_used


def test_benchmark_passes_same_trace_to_distinct_hidden_maps() -> None:
    cases = (
        corridor(),
        MazeScenario("jitter_corridor_2", ("#####", "#S.G#", "#####")),
    )
    results = run_maze_benchmark(
        cases, owner_approved=True, max_frames=20,
        decision_delay_schedule=(0, 2), action_deadline_ticks=1,
    )
    assert len(results) == 2
    assert results[0].scenario_id != results[1].scenario_id
    assert all(r.decision_delay_schedule_used for r in results)
    assert all(r.decision_delay_max_ticks == 2 for r in results)


@pytest.mark.parametrize("trace", [
    (), [], [0, 1], (True,), (1.0,), ("1",), (-1,), (25,),
    tuple([0] * 257), (None,),
])
def test_invalid_jitter_trace_is_refused_before_execution(trace: object) -> None:
    with pytest.raises(ValueError, match="decision delay schedule"):
        run_signed_maze_trial(
            corridor(), owner_approved=True,
            decision_delay_schedule=trace,  # type: ignore[arg-type]
        )


def test_nonzero_fixed_delay_cannot_be_mixed_with_jitter_trace() -> None:
    with pytest.raises(ValueError, match="cannot mix"):
        run_signed_maze_trial(
            corridor(), owner_approved=True,
            decision_delay_ticks=1, decision_delay_schedule=(0, 2),
        )


@pytest.mark.parametrize("corruption", [
    {"decision_delay_p95_ticks": -1},
    {"decision_delay_p95_ticks": True},
    {"decision_delay_max_ticks": 25},
    {"decision_delay_max_ticks": 0},
    {"decision_delay_total_ticks": -1},
    {"decision_delay_total_ticks": True},
    {"decision_delay_total_ticks": 9000},
    {"decision_delay_samples": True},
    {"decision_delay_samples": -1},
    {"decision_delay_samples": 9000},
    {"decision_delay_schedule_used": 1},
])
def test_latency_summary_cannot_be_arbitrarily_modified(corruption: dict[str, object]) -> None:
    score = run_signed_maze_trial(corridor(), owner_approved=True, decision_delay_schedule=(0, 3))
    with pytest.raises(ValueError, match="telemetry"):
        MazeTrialScore(**{**asdict(score), **corruption})


def patrolling_corridor() -> MazeScenario:
    from star.game_navigation_memory import GridPosition

    return MazeScenario(
        "jitter_patrol",
        ("########", "#S...G.#", "#......#", "#......#", "########"),
        patrol=(
            GridPosition(2, 1), GridPosition(3, 1),
            GridPosition(4, 1), GridPosition(4, 2),
            GridPosition(3, 2), GridPosition(2, 2),
        ),
    )


def test_bursty_thinking_delay_causes_real_engine_scored_collision() -> None:
    case = patrolling_corridor()
    zero = run_signed_maze_trial(
        case, owner_approved=True, max_frames=45, decision_delay_schedule=(0,),
    )
    jitter = run_signed_maze_trial(
        case, owner_approved=True, max_frames=45, decision_delay_schedule=(0, 1),
    )
    assert zero.success and zero.moves == 6 and zero.moving_hazard_hits == 0
    assert not jitter.success
    assert jitter.reason == "moving_hazard_hit_during_decision"
    assert jitter.moving_hazard_hits == jitter.moving_hazard_delay_hits == 1
    assert jitter.invalid_move_attempts == 0
    assert jitter.efficiency_bps == 0  # Prior movement does NOT count as winning.
    assert jitter.decision_delay_p95_ticks == 1
    assert jitter.world_ticks > zero.world_ticks


def test_same_trace_different_pattern_changes_outcomes_not_only_total_latency() -> None:
    case = patrolling_corridor()
    bursty = run_signed_maze_trial(
        case, owner_approved=True, max_frames=45, decision_delay_schedule=(0, 1),
    )
    sparse = run_signed_maze_trial(
        case, owner_approved=True, max_frames=45,
        decision_delay_schedule=(0, 0, 1),
    )
    assert not bursty.success and sparse.success
    assert sparse.moving_hazard_hits == 0
    assert sparse.decision_delay_max_ticks == bursty.decision_delay_max_ticks == 1
    # Peak latency alone does not determine correctness; timing pattern matters.
