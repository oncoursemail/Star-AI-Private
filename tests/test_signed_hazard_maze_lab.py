"""Independent damage-risk and lethal-tile checks for STAR's private signed maze lab."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from star.game_navigation_memory import GridPosition
from star.signed_maze_lab import MazeScenario, MazeTrialScore, run_maze_benchmark, run_signed_maze_trial


def test_lethal_hazard_is_seen_but_not_treated_as_a_wall() -> None:
    case = MazeScenario('lethal_detour', ('#######', '#S.!G.#', '#.....#', '#######'))
    danger = case.local_capture(GridPosition(2, 1))
    assert any(tile.position == GridPosition(3, 1)
               and tile.walkable and tile.risk_bps == 10000 for tile in danger)
    assert case.walkable(GridPosition(3, 1))
    assert not case.safe_for_engine(GridPosition(3, 1))
    assert case.shortest_path_length() == 5
    score = run_signed_maze_trial(case, owner_approved=True)
    assert score.success and score.reason == 'goal_witnessed'
    assert score.invalid_move_attempts == 0
    assert score.hazard_tile_entries == score.risk_exposure_bps == 0
    assert score.optimal_moves == score.moves == 5


def test_known_risk_is_penalized_by_advisor_on_longer_detour() -> None:
    case = MazeScenario('cost_detour', ('#######', '#S.~G.#', '#.....#', '#######'))
    score = run_signed_maze_trial(case, owner_approved=True)
    assert score.success and score.invalid_move_attempts == 0
    assert score.moves == 5  # geometric shortest path is 3 but hazardous
    assert score.optimal_moves == 3
    assert score.hazard_tile_entries == 0
    assert score.risk_exposure_bps == 0
    assert score.efficiency_bps == 6000


def test_unavoidable_bounded_exposure_is_scored_not_hidden() -> None:
    case = MazeScenario('required_exposure', ('#####', '#S~G#', '#####'))
    score = run_signed_maze_trial(case, owner_approved=True)
    assert score.success and score.moves == 2
    assert score.hazard_tile_entries == 1
    assert score.risk_exposure_bps == 6000
    assert score.efficiency_bps == 10000  # efficiency is NOT hazard avoidance
    assert not score.source_revoked
    assert 'source_key' not in asdict(score)
    assert 'session_id' not in asdict(score)


def test_multiple_known_traps_avoided_and_scored_as_success() -> None:
    case = MazeScenario('two_lethals', ('#######', '#S.!!G#', '#.....#', '#######'))
    score = run_signed_maze_trial(case, owner_approved=True)
    assert score.success
    assert score.invalid_move_attempts == 0
    assert score.risk_exposure_bps == 0


def test_lethal_only_route_rejected_even_if_terrain_passable() -> None:
    with pytest.raises(ValueError, match='reachable'):
        MazeScenario('impossible', ('#####', '#S!G#', '#####'))


@pytest.mark.parametrize('unsupported', ['?', 'X', 'V', '9'])
def test_no_undefined_risk_symbols(unsupported: str) -> None:
    with pytest.raises(ValueError, match='rectangular'):
        MazeScenario('malformed', (f'S{unsupported}G', '...'))


def test_one_trial_failure_does_not_mask_hazard_success() -> None:
    first = MazeScenario('exposure', ('#####', '#S~G#', '#####'))
    second = MazeScenario('detour', ('#######', '#S.!G.#', '#.....#', '#######'))
    results = run_maze_benchmark((first, second), owner_approved=True, max_frames=3)
    assert results[0].success and results[0].risk_exposure_bps == 6000
    assert not results[1].success and results[1].reason == 'frame_budget_exhausted'
    assert results[1].efficiency_bps == 0


def test_out_of_band_score_fails_closed() -> None:
    score = run_signed_maze_trial(
        MazeScenario('basic', ('#####', '#S.G#', '#####')),
        owner_approved=True,
    )
    with pytest.raises(ValueError, match='exposure'):
        MazeTrialScore(**{**asdict(score), 'hazard_tile_entries': 1})
    with pytest.raises(ValueError, match='exposure'):
        MazeTrialScore(**{**asdict(score), 'risk_exposure_bps': 6000})
    with pytest.raises(ValueError, match='exposure'):
        MazeTrialScore(**{**asdict(score), 'risk_exposure_bps': True})


def test_private_approval_and_strict_frame_cap_still_apply() -> None:
    case = MazeScenario('bounded', ('#####', '#S~G#', '#####'))
    with pytest.raises(PermissionError):
        run_signed_maze_trial(case)
    too_short = run_signed_maze_trial(case, owner_approved=True, max_frames=1)
    assert not too_short.success
    assert too_short.risk_exposure_bps == 6000
    assert too_short.efficiency_bps == 0
