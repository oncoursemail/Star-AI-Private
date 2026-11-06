"""Offline signed-frame gameplay rehearsals; no real-game dispatch or OBS."""
from __future__ import annotations

from dataclasses import asdict
import pytest

from star.signed_maze_lab import (
    MazeScenario, run_signed_maze_trial, run_maze_benchmark,
)


def small_corridor() -> MazeScenario:
    return MazeScenario("corridor", ("#####", "#S.G#", "#####"))


def zigzag(left_gap: int, right_gap: int) -> MazeScenario:
    # Hidden map truth: repeated alternate partitions force observation,
    # exploration, re-routing and real engine-side movement.
    rows: list[str] = []
    for y in range(5):
        cells = ["." for _ in range(7)]
        for x, gap in ((2, left_gap), (4, right_gap)):
            if y != gap:
                cells[x] = "#"
        if y == 2:
            cells[0] = "S"
            cells[6] = "G"
        rows.append("".join(cells))
    return MazeScenario(f"zigzag_{left_gap}_{right_gap}", tuple(rows))


def test_signed_engine_loop_solves_corridor_and_counts_real_steps() -> None:
    trial = run_signed_maze_trial(small_corridor(), owner_approved=True)
    assert trial.success
    assert trial.reason == "goal_witnessed"
    assert trial.moves == trial.optimal_moves == 2
    assert trial.efficiency_bps == 10000
    assert trial.frames >= 3
    assert trial.invalid_move_attempts == 0
    assert not trial.source_revoked
    assert "source_key" not in asdict(trial)
    assert "session_id" not in asdict(trial)


@pytest.mark.parametrize("left,right", [
    (0, 0), (0, 4), (4, 0), (4, 4),
])
def test_signed_hidden_zigzag_mazes_reach_actual_goal(
    left: int, right: int,
) -> None:
    result = run_signed_maze_trial(
        zigzag(left, right), owner_approved=True, max_frames=256,
    )
    assert result.success, result
    assert result.invalid_move_attempts == 0
    assert result.moves >= result.optimal_moves
    assert result.efficiency_bps <= 10000
    assert result.frames > result.moves


def test_preregistered_multi_trial_score_preserves_individual_failures() -> None:
    cases = (small_corridor(), zigzag(0, 4))
    results = run_maze_benchmark(cases, owner_approved=True, max_frames=2)
    assert len(results) == 2
    assert all(not result.success for result in results)
    assert all(result.reason == "frame_budget_exhausted" for result in results)
    assert all(result.efficiency_bps == 0 for result in results)


def test_unknown_unreachable_and_malformed_maze_refused() -> None:
    for bad in [
        ("S.G",), ("S##", "#G#"),
        ("S.G", "###", "S.."),
        ("S.G", "##"), ("SXG", "..."),
        ("S.G", "###", "G.."),
    ]:
        with pytest.raises(ValueError):
            MazeScenario("bad", bad)
    with pytest.raises(ValueError):
        MazeScenario("../escape", ("S.G", "..."))
    with pytest.raises(ValueError):
        MazeScenario("huge", ("S" + "." * 15 + "G", "#################"))


def test_owner_opt_in_and_resource_budgets() -> None:
    case = small_corridor()
    with pytest.raises(PermissionError):
        run_signed_maze_trial(case)
    with pytest.raises(PermissionError):
        run_maze_benchmark((case,))
    for value in (True, 0, -1, 513, 1.1):
        with pytest.raises(ValueError):
            run_signed_maze_trial(case, owner_approved=True, max_frames=value)
    for invalid in ((), (case, case), tuple([case] * 33)):
        with pytest.raises(ValueError):
            run_maze_benchmark(invalid, owner_approved=True)


def test_repeated_runs_are_independent_and_secret_free() -> None:
    # Independent signing keys / sessions; no hidden context carried between runs.
    a = run_signed_maze_trial(small_corridor(), owner_approved=True)
    b = run_signed_maze_trial(small_corridor(), owner_approved=True)
    assert a == b
    assert a.success and b.success
