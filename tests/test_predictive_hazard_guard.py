"""Owner-gated private maze experiments: bounded one-tick risk envelope.

All movement is synthetic; no game input, broadcasting or online learning.
"""
from __future__ import annotations

import json

import pytest

from star.game_navigation_memory import (
    GridPosition, GroundedNavigationMemory, NavigationObservation, ObservedTile,
)
from star.game_navigation_source_bridge import (
    AuthenticatedNavigationBridge, NavigationSourceRevoked, sign_navigation_packet,
)
from star.signed_maze_lab import MazeScenario, run_signed_maze_trial


def moving_trial() -> MazeScenario:
    return MazeScenario(
        "bounded_forecast", ("#######", "#S..G.#", "#.....#", "#######"),
        patrol=(GridPosition(3, 1), GridPosition(2, 1)),
    )


def test_same_sensors_forecast_avoids_verified_collision() -> None:
    scenario = moving_trial()
    # Same signed observations and same independently advancing engine.
    # Only the advisor's opt-in one-step reachability envelope changes.
    baseline = run_signed_maze_trial(
        scenario, owner_approved=True, sensor_radius=2, max_frames=55,
    )
    guarded = run_signed_maze_trial(
        scenario, owner_approved=True, sensor_radius=2,
        predictive_risk_guard=True, max_frames=55,
    )
    assert not baseline.success
    assert baseline.reason == "moving_hazard_hit_player"
    assert baseline.moving_hazard_hits == 1
    assert guarded.success and guarded.reason == "goal_witnessed"
    assert guarded.moving_hazard_hits == 0
    assert guarded.invalid_move_attempts == 0
    assert guarded.moves == 5 and guarded.optimal_moves == 3
    assert guarded.risk_exposure_bps == 0
    assert not guarded.source_revoked


def test_forecast_never_guesses_unobserved_enemy() -> None:
    # At radius 1 the moving hazard is initially invisible. Guarding cannot
    # assert safety from a missing observation.
    scored = run_signed_maze_trial(
        moving_trial(), owner_approved=True, sensor_radius=1,
        predictive_risk_guard=True,
    )
    assert not scored.success and scored.moving_hazard_hits == 1
    assert scored.efficiency_bps == 0


def test_no_hazard_guard_preserves_normal_private_maze() -> None:
    scenario = MazeScenario("static_corridor", ("#####", "#S.G#", "#####"))
    base = run_signed_maze_trial(scenario, owner_approved=True)
    guarded = run_signed_maze_trial(
        scenario, owner_approved=True, predictive_risk_guard=True,
    )
    assert base == guarded
    assert base.success and base.moves == 2


def test_advisor_excludes_one_step_of_host_observed_high_risk() -> None:
    player = GridPosition(0, 0)
    tiles = tuple(
        ObservedTile(GridPosition(x, y), True, 10000 if (x, y) == (2, 0) else 0)
        for x, y in ((0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (3, 1),
                     (3, 0), (4, 0))
    )
    obs = NavigationObservation(
        game_id="maze", game_version="v1", episode_id="private",
        sequence=1, captured_ms=1010, player=player,
        goal=GridPosition(1, 0), tiles=tiles,
    )
    base = GroundedNavigationMemory()
    guarded = GroundedNavigationMemory(predictive_risk_guard=True)
    for nav in (base, guarded):
        nav.start(game_id="maze", game_version="v1", episode_id="private",
                  owner_approved=True)
        assert not nav.ingest(obs, now_ms=1010)  # unauthenticated refused
        assert nav.ingest(obs, now_ms=1010, host_verified=True)
    # The current observed risk tile is (2,0); its neighbor (1,0) may be
    # occupied one frame later, even though it is currently safe.
    assert base.advise(now_ms=1011).action_id == "right"
    hint = guarded.advise(now_ms=1011)
    assert hint.status == "move" and hint.action_id == "down"
    assert not hint.authorizes_input and not hint.authorizes_broadcast


def test_signed_forecast_risk_cannot_be_modified_in_transit() -> None:
    scenario = moving_trial()
    tiles = scenario.local_capture(
        scenario.start, moving_hazard=GridPosition(3, 1), sensor_radius=2,
    )
    assert any(t.position == GridPosition(3, 1) and t.risk_bps == 10000
               for t in tiles)
    obs = NavigationObservation(
        game_id="synthetic_maze", game_version="v1", episode_id=scenario.scenario_id,
        sequence=1, captured_ms=1010, player=scenario.start, goal=scenario.goal,
        tiles=tiles,
    )
    nav = GroundedNavigationMemory(predictive_risk_guard=True)
    host = AuthenticatedNavigationBridge(
        navigator=nav, source_id="private_lab", session_id="a" * 32,
        source_key=b"private-host-key-32-bytes-minimum-test!!",
        game_id="synthetic_maze", game_version="v1",
        episode_id=scenario.scenario_id, clock_ms=lambda: 1010.0,
    )
    host.enable(owner_approved=True)
    original = sign_navigation_packet(
        obs, source_id="private_lab", session_id="a" * 32,
        source_key=b"private-host-key-32-bytes-minimum-test!!",
    )
    edited = json.loads(original)
    for tile in edited["tiles"]:
        if tile[0:2] == [3, 1]:
            tile[3] = 0
    with pytest.raises(NavigationSourceRevoked):
        host.accept(json.dumps(edited).encode("utf-8"))
    assert nav.metrics()["observed_cells"] == 0
    assert host.metrics()["revoked"]


@pytest.mark.parametrize("bad", [True, 0, -1, 3, 2.0, "2", None])
def test_bounded_sensor_radius_rejects_invalid_values(bad: object) -> None:
    scenario = moving_trial()
    with pytest.raises(ValueError, match="radius"):
        scenario.local_capture(scenario.start, sensor_radius=bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="radius"):
        run_signed_maze_trial(scenario, owner_approved=True,
                              sensor_radius=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [None, 1, 0, "true", [], 1.0])
def test_opt_in_guard_requires_explicit_boolean(bad: object) -> None:
    with pytest.raises(ValueError, match="boolean"):
        GroundedNavigationMemory(predictive_risk_guard=bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="boolean"):
        run_signed_maze_trial(
            moving_trial(), owner_approved=True,
            predictive_risk_guard=bad,  # type: ignore[arg-type]
        )


def test_guard_remains_explicit_private_owner_opt_in() -> None:
    with pytest.raises(PermissionError):
        run_signed_maze_trial(moving_trial(), predictive_risk_guard=True, sensor_radius=2)
