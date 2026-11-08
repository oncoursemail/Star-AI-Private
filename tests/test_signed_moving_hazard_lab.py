"""Engine-owned moving-hazard tests: agent never receives patrol phase schedule."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from star.game_navigation_memory import GridPosition
from star.signed_maze_lab import MazeScenario, MazeTrialScore, run_signed_maze_trial


def corridor(patrol: tuple[GridPosition, ...]) -> MazeScenario:
    return MazeScenario(
        "moving_corridor", ("#######", "#S...G#", "##.####", "#######"),
        patrol=patrol,
    )


def test_successful_wait_for_patrol_to_clear_and_complete_signed_goal() -> None:
    # Hazard blocks the only route on frame 1, then moves into an alcove.
    scenario = corridor((GridPosition(2, 1),) + (GridPosition(2, 2),) * 6)
    score = run_signed_maze_trial(scenario, owner_approved=True)
    assert score.success, score
    assert score.reason == "goal_witnessed"
    assert score.moves == score.optimal_moves == 4
    assert score.moving_hazard_waits >= 1
    assert score.moving_hazard_hits == 0
    assert score.invalid_move_attempts == 0
    assert not score.source_revoked
    assert "patrol" not in asdict(score)


def test_fast_returning_moving_hazard_can_cause_real_engine_loss() -> None:
    # Fresh observation proves the next square safe, but the hazard returns
    # while the world advances. A turn-by-turn agent has no future guarantee.
    scenario = corridor((GridPosition(2, 1), GridPosition(2, 2)))
    score = run_signed_maze_trial(scenario, owner_approved=True)
    assert not score.success, score
    assert score.reason == "moving_hazard_hit_player"
    assert score.moving_hazard_hits == 1
    assert score.moving_hazard_waits >= 1
    assert score.efficiency_bps == 0
    assert score.invalid_move_attempts == 0
    assert not score.source_revoked


def test_moving_hazard_is_visible_only_when_currently_adjacent() -> None:
    scenario = corridor((GridPosition(2, 1), GridPosition(2, 2)))
    player = scenario.start
    frame1 = scenario.local_capture(player, moving_hazard=scenario.hazard_at_frame(1))
    frame2 = scenario.local_capture(player, moving_hazard=scenario.hazard_at_frame(2))
    assert next(t for t in frame1 if t.position == GridPosition(2, 1)).risk_bps == 10000
    assert next(t for t in frame2 if t.position == GridPosition(2, 1)).risk_bps == 0
    assert scenario.hazard_at_frame(3) == GridPosition(2, 1)
    with pytest.raises(ValueError):
        scenario.hazard_at_frame(0)


@pytest.mark.parametrize("patrol", [
    [GridPosition(2, 1), GridPosition(2, 2)],
    (GridPosition(2, 1),),
    (GridPosition(2, 1), GridPosition(2, 1)),
    (GridPosition(2, 1), GridPosition(4, 1)),
    (GridPosition(2, 1), GridPosition(0, 1)),
    (GridPosition(2, 1), GridPosition(5, 1)),
    tuple(GridPosition(2, 1) for _ in range(33)),
])
def test_invalid_or_unphysical_patrols_are_rejected(patrol: object) -> None:
    with pytest.raises(ValueError, match="patrol"):
        corridor(patrol)  # type: ignore[arg-type]


def test_moving_hazard_score_cannot_report_success_with_collision() -> None:
    score = run_signed_maze_trial(
        corridor((GridPosition(2, 1), GridPosition(2, 2))),
        owner_approved=True,
    )
    assert not score.success
    with pytest.raises(ValueError, match="moving-hazard"):
        MazeTrialScore(**{**asdict(score), "moving_hazard_hits": 2})
    with pytest.raises(ValueError, match="moving-hazard"):
        MazeTrialScore(**{**asdict(score), "moving_hazard_waits": True})


def test_private_opt_in_and_frame_budget_are_preserved() -> None:
    scenario = corridor((GridPosition(2, 1), GridPosition(2, 2)))
    with pytest.raises(PermissionError):
        run_signed_maze_trial(scenario)
    score = run_signed_maze_trial(scenario, owner_approved=True, max_frames=1)
    assert not score.success and score.reason == "frame_budget_exhausted"
    assert score.moving_hazard_waits == 1 and score.moving_hazard_hits == 0
